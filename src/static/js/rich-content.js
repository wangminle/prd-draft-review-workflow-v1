// 富内容渲染统一入口：KaTeX 公式 + 隔离式 SVG 预览
// Chat / Review 共用，避免两个页面富内容能力不一致（Issue #6 / #7）
window.RichContent = {
    // ── 对外入口 ──

    enhance(scope) {
        const root = this._root(scope);
        this.enhanceMath(root);
        this.enhanceSvg(root);
        return root;
    },

    // 在 marked 解析前保护公式区段，返回带 math-slot 占位符的文本。
    // marked 会把 \( \[ 等转义序列吃掉，必须先于 parse 处理；
    // 代码块/行内代码中的公式不提取（保持 pre/code 不渲染的语义）。
    protectMath(text) {
        if (!text || typeof text !== 'string') return '';
        if (!/\$\$|\\\[|\\\(/.test(text)) return text;
        const codeRe = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g;
        const parts = text.split(codeRe);
        return parts.map(part => {
            if (part == null || part === '') return '';
            if (part.startsWith('```') || part.startsWith('~~~') || part.startsWith('`')) return part;
            const mathRe = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g;
            return part.replace(mathRe, (match, dd, disp, inl) => {
                const latex = dd != null ? dd : (disp != null ? disp : (inl != null ? inl : ''));
                if (!latex.trim()) return match;
                const mode = (dd != null || disp != null) ? 'display' : 'inline';
                // encodeURIComponent 结果不含 " < > &，可安全放入双引号属性
                return `<span class="math-slot" data-lat="${encodeURIComponent(latex)}" data-mode="${mode}"></span>`;
            });
        }).join('');
    },

    // DOMPurify 清洗并插入页面后调用；与 Mermaid 一致：流式期间不渲染
    enhanceMath(scope) {
        const root = this._root(scope);
        let slots = [];
        try { slots = Array.from(root.querySelectorAll('.math-slot[data-lat]')); } catch (e) { /* non-DOM scope */ }
        const katexOk = typeof window.katex !== 'undefined' && window.katex && typeof window.katex.render === 'function';

        for (const slot of slots) {
            const encoded = slot.getAttribute('data-lat');
            if (!encoded) continue;
            let latex = '';
            try { latex = decodeURIComponent(encoded); } catch (e) { latex = ''; }
            if (!latex) continue;
            const displayMode = slot.getAttribute('data-mode') === 'display';
            if (!katexOk) {
                slot.textContent = latex;
                slot.classList.add('math-fallback');
                continue;
            }
            try {
                window.katex.render(latex, slot, {
                    throwOnError: false,
                    displayMode,
                    strict: false,
                });
                slot.removeAttribute('data-lat');
                slot.classList.add('math-ok');
            } catch (e) {
                // 单个公式错误不影响整条消息：降级显示源码
                slot.textContent = latex;
                slot.classList.add('math-error');
                this._log('warn', 'richcontent.math.render_failed', { reason: e?.message }, '公式渲染失败');
            }
        }

        // 兜底二次扫描：处理未走占位符路径的残留定界符（auto-render 默认忽略 pre/code）
        if (typeof window.renderMathInElement === 'function') {
            try {
                window.renderMathInElement(root, {
                    delimiters: [
                        { left: '$$', right: '$$', display: true },
                        { left: '\\[', right: '\\]', display: true },
                        { left: '\\(', right: '\\)', display: false },
                    ],
                    throwOnError: false,
                    ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
                    ignoredClasses: ['mermaid-source', 'svg-source', 'mermaid-source-code'],
                });
            } catch (e) {
                this._log('warn', 'richcontent.math.autorender_failed', { reason: e?.message }, '公式渲染失败');
            }
        } else if (slots.length && !katexOk) {
            this._log('warn', 'richcontent.math.lib_missing', { slot_count: slots.length }, '公式库未加载，已降级为源码显示');
        }
        return root;
    },

    // SVG 采用隔离式预览：清洗后生成 Blob URL 经 <img> 展示，
    // 避免 SVG DOM/CSS 影响主页面（Issue #7）
    enhanceSvg(scope) {
        const root = this._root(scope);
        let containers = [];
        try { containers = Array.from(root.querySelectorAll('.svg-container')); } catch (e) { /* non-DOM scope */ }

        for (const container of containers) {
            if (container.getAttribute('data-svg-enhanced') === '1') continue;
            container.setAttribute('data-svg-enhanced', '1');

            const sourceEl = container.querySelector('.svg-source');
            const img = container.querySelector('.svg-preview-img');
            const errEl = container.querySelector('.svg-error');
            const raw = sourceEl ? sourceEl.textContent : '';

            const clean = this.sanitizeSvg(raw);
            if (!clean) {
                if (errEl) {
                    errEl.textContent = 'SVG 预览不可用：内容未通过安全校验';
                    errEl.hidden = false;
                }
                container.classList.add('show-source');
                const toggleBtn = container.querySelector('.svg-toggle-btn');
                if (toggleBtn) toggleBtn.disabled = true;
                this._log('warn', 'richcontent.svg.rejected', { length: (raw || '').length }, 'SVG 内容被安全策略拒绝');
                continue;
            }

            if (img && typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function') {
                try {
                    const blob = new Blob([clean], { type: 'image/svg+xml;charset=utf-8' });
                    const url = URL.createObjectURL(blob);
                    img.setAttribute('data-svg-blob-url', url);
                    img.src = url;
                    img.hidden = false;
                } catch (e) {
                    if (errEl) {
                        errEl.textContent = 'SVG 预览生成失败';
                        errEl.hidden = false;
                    }
                    container.classList.add('show-source');
                    continue;
                }
            }

            const toggleBtn = container.querySelector('.svg-toggle-btn');
            if (toggleBtn && !toggleBtn.getAttribute('data-svg-bound')) {
                toggleBtn.setAttribute('data-svg-bound', '1');
                toggleBtn.addEventListener('click', () => {
                    const showSource = !container.classList.contains('show-source');
                    container.classList.toggle('show-source', showSource);
                    toggleBtn.textContent = showSource ? '查看图形' : '查看源码';
                });
            }
        }
        return root;
    },

    // 清洗 SVG 源码：含 script/style/foreignObject/href 等高风险内容时整体拒绝，
    // 且只接受单一 <svg> 根节点；返回可直接用于 Blob 的字符串，拒绝时返回 null
    _SVG_DANGEROUS_RE: /<\s*(script|style|foreignObject|foreignobject|image|use|iframe|object|embed|animate|animatetransform|set|a)\b|on[a-z]+\s*=|(?:xlink:)?href\s*=/i,

    sanitizeSvg(raw) {
        const text = String(raw == null ? '' : raw).trim();
        if (!text) return null;
        const purify = window.DOMPurify;
        if (!purify || typeof purify.sanitize !== 'function') return null;

        // 预检：原始输入含高危标签/属性/外部引用时直接拒绝，不做静默降级清洗
        try {
            if (this._SVG_DANGEROUS_RE.test(text)) return null;
        } catch (e) { /* regex failure should not bypass checks */ }

        let cleanStr = '';
        try {
            cleanStr = purify.sanitize(text, {
                USE_PROFILES: { svg: true, svgFilters: true },
                FORBID_TAGS: ['script', 'style', 'foreignObject', 'foreignobject', 'iframe', 'embed',
                    'object', 'image', 'a', 'use', 'animate', 'animateTransform', 'set'],
                FORBID_ATTR: ['style', 'href', 'xlink:href'],
                KEEP_CONTENT: false,
            });
        } catch (e) {
            return null;
        }
        if (!cleanStr || !cleanStr.trim()) return null;

        let doc = null;
        try {
            doc = new DOMParser().parseFromString(cleanStr, 'image/svg+xml');
        } catch (e) {
            return null;
        }
        if (!doc || doc.querySelector('parsererror')) return null;
        const svgRoot = doc.documentElement;
        if (!svgRoot || svgRoot.nodeName.toLowerCase() !== 'svg') return null;

        // 双保险：即使 DOMPurify 配置变化也不放行高危标签
        if (svgRoot.querySelector('script, style, foreignObject, foreignobject')) return null;

        try {
            return new XMLSerializer().serializeToString(svgRoot);
        } catch (e) {
            return null;
        }
    },

    // 回收指定范围内 SVG 预览的 Blob URL（消息删除、重渲染前调用）
    revoke(scope) {
        const root = this._root(scope);
        let nodes = [];
        try { nodes = Array.from(root.querySelectorAll('[data-svg-blob-url]')); } catch (e) { /* non-DOM scope */ }
        for (const el of nodes) {
            const url = el.getAttribute('data-svg-blob-url');
            if (url && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
                try { URL.revokeObjectURL(url); } catch (e) { /* already revoked */ }
            }
            el.removeAttribute('data-svg-blob-url');
        }
        return root;
    },

    revokeAll() {
        this.revoke(document);
    },

    // ── 内部工具 ──

    _root(scope) {
        return scope && typeof scope.querySelectorAll === 'function' ? scope : document;
    },

    _log(level, event, extra, userMsg) {
        if (window.API && typeof window.API.log === 'function') {
            try { window.API.log(level, event, extra, userMsg); } catch (e) { /* logging must not break render */ }
        }
    },
};

// 页面卸载时回收所有 Blob URL，避免内存泄漏
if (typeof window.addEventListener === 'function') {
    window.addEventListener('beforeunload', () => {
        try { window.RichContent.revokeAll(); } catch (e) { /* noop */ }
    });
}
