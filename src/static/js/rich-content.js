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
                // 预留宽高：Blob 加载前 <img> 无固有尺寸，会造成布局跳动（CLS）；
                // 从清洗结果的 width/height/viewBox 推导出整数尺寸写为属性
                const dims = this._svgIntrinsicSize(clean);
                if (dims) {
                    img.setAttribute('width', String(dims.w));
                    img.setAttribute('height', String(dims.h));
                }
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

        // 归一化：模型常用 style="stop-color:..." 写渐变，而 FORBID_ATTR 会把 style
        // 整体剥除，<stop> 将回退到默认 stop-color:black，整图变黑底。
        // 清洗前先把白名单内的 style 声明转成表示属性，再交给 DOMPurify。
        const normalizable = this._normalizeSvgStyles(text);

        let cleanStr = '';
        try {
            cleanStr = purify.sanitize(normalizable, {
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

        // 原生表示属性（fill/filter/clip-path/mask/marker-*）的取值校验：
        // DOMPurify 只按属性名白名单放行、不校验取值，直接写在属性上的
        // 外链或 data: url() 会绕过 style 归一化路径的白名单，需在此统一拦截
        this._sanitizeSvgUrlAttrs(svgRoot);

        try {
            return new XMLSerializer().serializeToString(svgRoot);
        } catch (e) {
            return null;
        }
    },

    // URL 型表示属性清单：取值可含 url() 引用，需统一校验片段引用合规。
    // marker-* 前缀匹配 marker-start/mid/end 等 SVG 1.1 属性（markerWidth 等
    // 驼峰属性小写后不含连字符，不会被前缀匹配误伤）。
    _SVG_URL_ATTRS: ['fill', 'stroke', 'filter', 'clip-path', 'mask', 'marker',
        'marker-start', 'marker-mid', 'marker-end'],

    // 清洗后的 SVG DOM 上统一校验 URL 型属性：仅放行本地片段引用 url(#id)
    // （可带引号、可跟严格白名单纯色 fallback），其余（外链/data:/相对路径）删除该属性。
    // 返回被删除的属性数量，便于测试观测。
    _sanitizeSvgUrlAttrs(root) {
        if (!root || typeof root.querySelectorAll !== 'function') return 0;
        let removed = 0;
        for (const el of Array.from(root.querySelectorAll('*'))) {
            if (!el.attributes) continue;
            for (const attr of Array.from(el.attributes)) {
                const name = String(attr.name).toLowerCase();
                const isUrlAttr = this._SVG_URL_ATTRS.includes(name) || name.startsWith('marker-');
                if (!isUrlAttr) continue;
                if (!this._validSvgUrlAttrValue(String(attr.value))) {
                    el.removeAttribute(attr.name);
                    removed += 1;
                }
            }
        }
        return removed;
    },

    // 校验 URL 型表示属性取值：只放行"本地片段引用 + 可选纯色 fallback"或纯颜色。
    // 允许的形态（大小写不敏感，空格容忍）：
    //   url(#id) / url('#id') / url("#id")  —— 本地片段引用
    //   url(#id) #fff / url(#id) rgba(...)  —— 片段引用 + 合法纯色 fallback
    //   #hex / rgb() / hsl() / 颜色关键字    —— 纯颜色（无 url）
    // 其余一律拒绝（返回 false → 调用方删除属性）。
    _validSvgUrlAttrValue(value) {
        const v = String(value == null ? '' : value).trim();
        if (!v) return false;
        // 全局拒绝：反斜杠（CSS 转义）、CSS 注释、尖括号
        if (v.includes('\\') || v.includes('/*') || v.includes('<') || v.includes('>')) return false;
        // 提取所有 url(...) 引用，逐个校验为本地片段
        const urlRe = /url\(\s*(['"]?)([^)'"]*)\1\s*(#[^)'"]*)?\s*\)/gi;
        let m;
        let urlCount = 0;
        let rest = v;
        while ((m = urlRe.exec(v)) !== null) {
            urlCount += 1;
            const frag = (m[3] || '').trim();
            const quoted = m[1];
            const rawRef = (m[2] || '').trim();
            // 合法形态：url(#id) 或 url('#id')——引号包裹的 # 开头引用
            if (quoted) {
                if (!rawRef.startsWith('#') || !/^#[a-zA-Z0-9_:.-]+$/.test(rawRef)) return false;
                if (frag) return false; // url('#id' #extra) 形态无意义，拒绝
            } else {
                // 无引号：整段必须是 # 开头的本地片段
                if (!rawRef.startsWith('#') || !/^#[a-zA-Z0-9_:.-]+$/.test(rawRef)) return false;
                if (frag) return false;
            }
            rest = rest.replace(m[0], ' ');
        }
        if (urlCount === 0) {
            // 无 url()：按纯颜色校验（复用颜色分支的整串正则）
            return this._isPlainColorValue(v);
        }
        // 去掉 url() 后的剩余部分必须是合法纯色 fallback（或空）
        const restTrimmed = rest.trim();
        if (!restTrimmed) return true;
        return this._isPlainColorValue(restTrimmed);
    },

    // 纯颜色整串校验：hex / rgb / hsl / 命名颜色（与 _validStyleValue 颜色分支一致，去掉 url 部分）
    _isPlainColorValue(v) {
        return /^(#[0-9a-f]{3,8}|rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*(?:,\s*[\d.]+%?\s*)?\)|hsla?\(\s*[\d.]+\s*,\s*[\d.]+%\s*,\s*[\d.]+%\s*(?:,\s*[\d.]+%?\s*)?\)|[a-zA-Z][a-zA-Z-]*)$/i
            .test(String(v));
    },

    // 允许从 style 归一化到表示属性的属性名白名单（颜色/描边/字体/颜色类）
    _STYLE_PROPS: {
        'fill': true, 'fill-opacity': true, 'fill-rule': true,
        'stroke': true, 'stroke-width': true, 'stroke-opacity': true,
        'stroke-dasharray': true, 'stroke-linecap': true, 'stroke-linejoin': true,
        'stroke-miterlimit': true, 'stop-color': true, 'stop-opacity': true,
        'opacity': true, 'font-family': true, 'font-size': true, 'font-weight': true,
        'font-style': true, 'text-anchor': true,
    },

    // 把白名单内的 style 声明转换为同名表示属性并移除 style。
    // 解析失败（非良构 XML）时原样返回，保持旧的清洗路径不变；
    // 输出仍会经过 DOMPurify，归一化只做保真，不承担安全职责。
    _normalizeSvgStyles(raw) {
        const text = String(raw == null ? '' : raw);
        // XML 允许属性名与等号间有空白（style = "..."、制表符均可），
        // 必须大小写不敏感且容忍空白，否则这些合法写法会漏掉归一化后被 DOMPurify 剥成黑底
        if (!/\bstyle\s*=/i.test(text)) return text;
        let doc = null;
        try {
            doc = new DOMParser().parseFromString(text, 'image/svg+xml');
        } catch (e) { return text; }
        if (!doc || doc.querySelector('parsererror')) return text;

        let touched = false;
        for (const el of Array.from(doc.querySelectorAll('*'))) {
            const style = el.getAttribute('style');
            if (!style) continue;
            for (const decl of style.split(';')) {
                const idx = decl.indexOf(':');
                if (idx < 0) continue;
                const prop = decl.slice(0, idx).trim().toLowerCase();
                const value = decl.slice(idx + 1).trim().replace(/!important$/i, '').trim();
                if (!prop || !value || !this._STYLE_PROPS[prop]) continue;
                if (!this._validStyleValue(prop, value)) continue;
                el.setAttribute(prop, value);
                touched = true;
            }
            el.removeAttribute('style');
        }
        if (!touched) return text;
        try {
            return new XMLSerializer().serializeToString(doc.documentElement);
        } catch (e) {
            return text;
        }
    },

    // 按属性做整串白名单校验：只放行纯颜色/数值/枚举/字体名取值，
    // 从结构上杜绝 CSS 转义（u\72l）、CSS 注释、外链与 data: url() 等绕过手段
    _validStyleValue(prop, value) {
        const v = String(value);
        // 全局拒绝：反斜杠（CSS 转义）、CSS 注释、尖括号
        if (v.includes('\\') || v.includes('/*') || v.includes('<') || v.includes('>')) return false;
        switch (prop) {
            case 'fill': case 'stroke': case 'stop-color':
                // 复用 URL 型属性取值校验：纯色 / 本地片段引用（可带引号）/ 片段引用+纯色 fallback，
                // 兼容 style="fill:url(#g) #fff" 与 style="fill:url('#g')" 两种常见渐变写法
                return this._validSvgUrlAttrValue(v);
            case 'fill-opacity': case 'stroke-opacity': case 'stop-opacity': case 'opacity':
                return /^[0-9]*\.?[0-9]+$/.test(v);
            case 'stroke-width': case 'stroke-miterlimit':
                return /^[0-9]*\.?[0-9]+(?:px|em|%)?$/.test(v);
            case 'stroke-dasharray':
                return /^[0-9.\s,]+$/.test(v);
            case 'stroke-linecap':
                return /^(butt|round|square|inherit)$/i.test(v);
            case 'stroke-linejoin':
                return /^(miter|round|bevel|inherit)$/i.test(v);
            case 'fill-rule':
                return /^(nonzero|evenodd|inherit)$/i.test(v);
            case 'font-family':
                // 字体名列表：允许引号/逗号/空格，禁止括号与特殊符号
                return /^[^\\<>{}()/*]+$/.test(v);
            case 'font-size':
                return /^[0-9]*\.?[0-9]+(?:px|pt|em|rem|%)$|^(xx-small|x-small|small|medium|large|x-large|xx-large|larger|smaller|inherit)$/i.test(v);
            case 'font-weight':
                return /^[0-9]{1,3}$|^(normal|bold|bolder|lighter|inherit)$/i.test(v);
            case 'font-style':
                return /^(normal|italic|oblique|inherit)$/i.test(v);
            case 'text-anchor':
                return /^(start|middle|end|inherit)$/i.test(v);
            default:
                return false;
        }
    },

    // SVG 预留尺寸上限：防御布局型 DoS——viewBox="0 0 1 100000000" 之类
    // 极端比例会把页面放大到数千万像素（Chromium 上限 33554432px），聊天页几乎无法滚动。
    // 超限时不写 width/height 属性，交给 CSS max-height/max-width 约束展示。
    _SVG_SIZE_MAX: 20000,          // 单边最大 px（覆盖 4K 全屏级）
    _SVG_AREA_MAX: 4000000,        // 面积上限（2000×2000）
    _SVG_RATIO_MAX: 20,            // 宽高比上限（1:20 ~ 20:1）

    // 从清洗后的 SVG 根节点提取固有尺寸（width/height 优先，回退 viewBox），
    // 供 <img> 预留宽高；只接受纯数字或 px 单位，百分比等相对值返回 null。
    // 超出边长/面积/宽高比上限的返回 null（布局安全优先于 CLS 预留）
    _svgIntrinsicSize(cleanStr) {
        const rootMatch = /<svg\b[^>]*>/i.exec(String(cleanStr || ''));
        if (!rootMatch) return null;
        const root = rootMatch[0];
        const num = (s) => {
            const m = /^\s*([0-9]*\.?[0-9]+)\s*(?:px)?\s*$/i.exec(String(s));
            if (!m) return null;
            const n = parseFloat(m[1]);
            return isFinite(n) && n > 0 ? Math.round(n) : null;
        };
        const withinLimits = (w, h) => {
            if (w > this._SVG_SIZE_MAX || h > this._SVG_SIZE_MAX) return false;
            if (w * h > this._SVG_AREA_MAX) return false;
            const ratio = Math.max(w, h) / Math.min(w, h);
            return ratio <= this._SVG_RATIO_MAX;
        };
        const wAttr = /(?:^|\s)width\s*=\s*["']([^"']+)["']/i.exec(root);
        const hAttr = /(?:^|\s)height\s*=\s*["']([^"']+)["']/i.exec(root);
        if (wAttr && hAttr) {
            const w = num(wAttr[1]);
            const h = num(hAttr[1]);
            if (w && h && withinLimits(w, h)) return { w, h };
        }
        const vb = /(?:^|\s)viewBox\s*=\s*["']\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)/i.exec(root);
        if (vb) {
            const w = num(vb[3]);
            const h = num(vb[4]);
            if (w && h && withinLimits(w, h)) return { w, h };
        }
        return null;
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
