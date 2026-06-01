/* 对话模块 */
const Chat = {
    _currentConvId: null,
    _sending: false,
    _bound: false,
    _abortCtrl: null,
    _streamCtrl: null,
    _mermaidTimer: null,
    _contextSync: Promise.resolve(),
    _files: [],      // { file_id, filename, extracted_text }
    _urls: [],       // { url, extracted_text }
    _contextItems: [],   // 会话级上下文项 [{ id, context_type, title, file_id, url, manual_text, enabled }]
    _contextRules: [],   // 手动规则文本列表
    _contextBound: false,
    _mentionState: null,

    async init() {
        await this.loadModels();
        await this.loadPrompts();
        await this.loadConversations();
        if (!this._bound) {
            if (this._abortCtrl) this._abortCtrl.abort();
            this._abortCtrl = new AbortController();
            this._bindEvents();
            this._bound = true;
        }
        this._bindContextEvents();
    },

    destroy() {
        if (this._abortCtrl) {
            this._abortCtrl.abort();
            this._abortCtrl = null;
        }
        if (this._streamCtrl) {
            this._streamCtrl.abort();
            this._streamCtrl = null;
        }
        this._sending = false;
        this._bound = false;
        this._contextBound = false;
        this._currentConvId = null;
        this._contextSync = Promise.resolve();
        if (this._mermaidTimer) {
            clearTimeout(this._mermaidTimer);
            this._mermaidTimer = null;
        }
        this._hideMentionSuggestions();
    },

    async loadModels() {
        try {
            const models = await API.getModels();
            const sel = document.getElementById('model-select');
            sel.innerHTML = models
                .filter(m => m.enabled)
                .map(m => `<option value="${m.id}">${m.name}</option>`)
                .join('');
        } catch (e) {
            console.error('加载模型失败:', e);
        }
    },

    async loadPrompts() {
        try {
            const prompts = await API.getPrompts();
            const sel = document.getElementById('prompt-select');
            sel.innerHTML = '<option value="">默认</option>' +
                prompts.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
        } catch (e) {
            console.error('加载提示词失败:', e);
        }
    },

    async loadConversations() {
        try {
            const data = await API.getConversations();
            const list = document.getElementById('conversation-list');
            const items = data.conversations || data.items || data || [];
            list.innerHTML = items.map(c => `
                <div class="conv-item ${c.id === this._currentConvId ? 'active' : ''}"
                     data-id="${c.id}">
                    <span class="conv-title">${this._esc(c.title || '新对话')}</span>
                    <button class="conv-del" title="删除">&times;</button>
                </div>
            `).join('');
        } catch (e) {
            console.error('加载对话列表失败:', e);
        }
    },

    async selectConversation(convId) {
        if (String(this._currentConvId) === String(convId)) return;
        if (this._sending) return;
        const requestConvId = String(convId);
        this._currentConvId = convId;
        try {
            const data = await API.getConversation(convId);
            if (!this._isConversationCurrent(requestConvId)) return;
            const messages = this._normalizeHistoryMessages(data.messages || []);
            const container = document.getElementById('chat-messages');
            container.innerHTML = '';
            messages.forEach(m => this._appendMessage(m.role, m.content));
            this._scrollBottom();
        } catch (e) {
            console.error('加载对话失败:', e);
        }
        if (!this._isConversationCurrent(requestConvId)) return;
        try {
            const ctxData = await API.getContextItems(convId);
            if (!this._isConversationCurrent(requestConvId)) return;
            this._contextItems = (Array.isArray(ctxData) ? ctxData : []).map(item => ({
                id: String(item.id),
                context_type: item.context_type,
                title: item.title,
                file_id: item.file_id,
                url: item.url,
                manual_text: item.manual_text,
                enabled: item.enabled,
            }));
        } catch (e) {
            if (!this._isConversationCurrent(requestConvId)) return;
            this._contextItems = [];
            console.error('加载上下文失败:', e);
        }
        if (!this._isConversationCurrent(requestConvId)) return;
        this._renderContextPanel();
        document.querySelectorAll('.conv-item').forEach(el => {
            el.classList.toggle('active', el.dataset.id == convId);
        });
    },

    newConversation() {
        this._currentConvId = null;
        this._contextItems = [];
        this._renderContextPanel();
        this._closeContextDrawer();
        const container = document.getElementById('chat-messages');
        container.innerHTML = `
            <div class="welcome">
                <div class="welcome-icon">
                    <svg width="48" height="48" viewBox="0 0 48 48" fill="none"><rect width="48" height="48" rx="12" fill="#005AAA"/><path d="M14 24h20M24 14v20" stroke="#fff" stroke-width="3" stroke-linecap="round"/></svg>
                </div>
                <h2 class="welcome-title">开始新的对话</h2>
                <p class="welcome-desc">选择模型和提示词模板，在下方输入你的问题</p>
            </div>`;
        document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    },

    async sendMessage() {
        if (this._sending) return;
        this._sending = true;
        this._updateSendBtn();

        const input = document.getElementById('message-input');
        const rawText = input.value;
        const text = rawText.trim();
        if (!text) { this._sending = false; this._updateSendBtn(); return; }

        const modelId = document.getElementById('model-select').value;
        const promptName = document.getElementById('prompt-select').value;

        // Remove welcome message
        const welcome = document.querySelector('.welcome');
        if (welcome) welcome.remove();

        // Remove any leftover "思考中..." assistant messages
        document.querySelectorAll('.msg-assistant .typing-dots').forEach(el => {
            el.closest('.msg-assistant').remove();
        });

        // Show user message
        this._appendMessage('user', text);
        input.value = '';
        input.style.height = 'auto';
        this._hideMentionSuggestions();

        await this._flushContextSync();

        // Build file/URL context
        const fileIds = this._files.map(f => f.file_id);
        const url_texts = {};
        this._urls.forEach(u => {
            if (u.extracted_text) url_texts[u.url] = u.extracted_text;
        });
        const urls = this._urls.map(u => u.url);
        const pendingContextItems = this._contextItems
            .filter(item => item.enabled)
            .filter(item => !item.id || String(item.id).startsWith('ctx_'));
        const mentionedContextItems = this._collectMentionedContextItems(rawText);
        const mentionedContextFileIds = mentionedContextItems
            .filter(item => item.file_id)
            .map(item => item.file_id);
        const mentionContextItemIds = mentionedContextItems
            .map(item => parseInt(item.id, 10))
            .filter(id => Number.isInteger(id) && id > 0);
        const fallbackContextFileIds = pendingContextItems.filter(i => i.file_id).map(i => i.file_id);
        const contextFileIds = mentionedContextFileIds.length ? mentionedContextFileIds : fallbackContextFileIds;
        const contextRules = pendingContextItems
            .filter(i => i.context_type === 'manual_rule' && i.manual_text)
            .map(i => i.manual_text);
        this._clearAttachments();

        // Show typing indicator
        const assistantEl = this._appendMessage('assistant', '');
        const contentEl = assistantEl.querySelector('.msg-text');
        contentEl.innerHTML = '<span class="typing-dots">思考中...</span>';

        try {
            if (this._streamCtrl) this._streamCtrl.abort();
            this._streamCtrl = new AbortController();
            const reader = await API.chatStream({
                model_id: modelId,
                prompt_template: promptName || undefined,
                conversation_id: this._currentConvId,
                message: text,
                file_ids: [...fileIds, ...contextFileIds].length ? [...fileIds, ...contextFileIds] : undefined,
                urls: urls.length ? urls : undefined,
                url_texts: Object.keys(url_texts).length ? url_texts : undefined,
                context_rules: contextRules.length ? contextRules : undefined,
                mention_context_item_ids: mentionContextItemIds.length ? mentionContextItemIds : undefined,
            });

            let fullText = '';
            let hadError = false;
            const decoder = new TextDecoder();
            const signal = this._streamCtrl.signal;

            while (!signal.aborted) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6);
                    if (dataStr === '[DONE]') continue;

                    try {
                        const data = JSON.parse(dataStr);

                        if (data.error) {
                            contentEl.innerHTML = `<span class="msg-error">错误: ${this._esc(data.error)}</span>`;
                            hadError = true;
                            break;
                        }

                        if (data.conversation_id && !this._currentConvId) {
                            this._currentConvId = data.conversation_id;
                            await this._persistPendingContextItems(data.conversation_id, pendingContextItems);
                            this.loadConversations();
                        }

                        if (data.content) {
                            fullText += data.content;
                            contentEl.innerHTML = this._renderMarkdown(fullText);
                            this._queueMermaidRender(contentEl);
                            this._scrollBottom();
                        }

                        if (data.done) {
                            // Stream complete
                        }
                    } catch {
                        // Skip malformed JSON lines
                    }
                }
            }

            if (!fullText && !hadError) {
                contentEl.innerHTML = '<span class="msg-error">未收到回复</span>';
            }

        } catch (e) {
            if (this._streamCtrl && this._streamCtrl.signal.aborted) {
                contentEl.innerHTML = '<span class="msg-error">已取消</span>';
            } else {
                contentEl.innerHTML = `<span class="msg-error">发送失败: ${this._esc(e.message)}</span>`;
            }
        } finally {
            this._sending = false;
            this._streamCtrl = null;
            this._updateSendBtn();
        }
    },

    _normalizeHistoryMessages(messages) {
        const normalized = [];
        for (const m of messages) {
            const last = normalized[normalized.length - 1];
            if (
                last &&
                last.role === 'assistant' &&
                m.role === 'assistant' &&
                last.content === m.content
            ) {
                continue;
            }
            normalized.push(m);
        }
        return normalized;
    },

    _appendMessage(role, content) {
        const container = document.getElementById('chat-messages');
        const div = document.createElement('div');
        div.className = `msg msg-${role}`;

        const avatar = role === 'user' ? '你' : 'AI';
        div.innerHTML = `
            <div class="msg-avatar">${avatar}</div>
            <div class="msg-bubble">
                <div class="msg-text">${content ? this._renderMarkdown(content) : ''}</div>
            </div>`;

        container.appendChild(div);
        this._queueMermaidRender(div);
        this._scrollBottom();
        return div;
    },

    _renderMarkdown(text) {
        if (window.marked && window.DOMPurify) {
            const renderer = new window.marked.Renderer();
            renderer.code = (code, infostring) => {
                const rawCode = typeof code === 'object' && code !== null ? (code.text || '') : (code || '');
                const rawLang = typeof code === 'object' && code !== null ? (code.lang || '') : (infostring || '');
                const lang = String(rawLang).trim().toLowerCase();

                if (lang === 'mermaid') {
                    return `<div class="mermaid-container"><div class="mermaid-chart" data-mermaid="${this._escAttr(rawCode)}"></div></div>`;
                }

                const safeCode = this._esc(rawCode);
                const safeLangClass = this._escAttr(lang || 'text');
                return `<pre><code class="language-${safeLangClass}">${safeCode}</code></pre>`;
            };
            window.marked.setOptions({
                gfm: true,
                breaks: true,
                renderer,
            });
            return window.DOMPurify.sanitize(window.marked.parse(text));
        }

        let html = this._esc(text);
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        html = html.replace(/\n/g, '<br>');
        return html;
    },

    _queueMermaidRender(scope = document) {
        if (this._mermaidTimer) clearTimeout(this._mermaidTimer);
        this._mermaidTimer = setTimeout(() => {
            this._renderMermaidCharts(scope);
        }, 120);
    },

    async _renderMermaidCharts(scope = document) {
        if (!window.mermaid) return;
        const root = scope && typeof scope.querySelectorAll === 'function' ? scope : document;
        const charts = root.querySelectorAll('.mermaid-chart[data-mermaid]');
        if (charts.length === 0) return;

        try {
            window.mermaid.initialize({
                startOnLoad: false,
                theme: 'base',
                securityLevel: 'loose',
                themeVariables: { fontSize: '14px' },
            });

            for (const el of charts) {
                const code = el.getAttribute('data-mermaid');
                if (!code) continue;
                const id = 'chat-mermaid-' + Math.random().toString(36).substring(2, 8);
                const { svg } = await window.mermaid.render(id, code);
                el.innerHTML = svg;
                el.removeAttribute('data-mermaid');
            }
        } catch (e) {
            console.warn('Chat Mermaid render failed:', e);
            for (const el of charts) {
                el.innerHTML = '<p class="mermaid-error">流程图渲染失败，请检查 Mermaid 语法</p>';
                el.removeAttribute('data-mermaid');
            }
        }
    },

    _scrollBottom() {
        const container = document.getElementById('chat-messages');
        container.scrollTop = container.scrollHeight;
    },

    _esc(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    _escAttr(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    _updateSendBtn() {
        const btn = document.getElementById('send-btn');
        btn.disabled = this._sending;
        btn.classList.toggle('btn-loading', this._sending);
    },

    _clearAttachments() {
        this._files = [];
        this._urls = [];
        document.getElementById('file-list').style.display = 'none';
        document.getElementById('file-list').innerHTML = '';
        document.getElementById('url-list').style.display = 'none';
        document.getElementById('url-list').innerHTML = '';
        document.getElementById('input-status').textContent = '';
    },

    async handleFileUpload(files) {
        for (const file of files) {
            try {
                const result = await API.uploadFile(file);
                this._files.push(result);
                this._renderAttachments();
            } catch (e) {
                alert(`上传失败: ${e.message}`);
            }
        }
    },

    async handleUrlSubmit(url) {
        if (!url) return;
        try {
            const result = await API.submitUrl(url);
            this._urls.push(result);
            this._renderAttachments();
        } catch (e) {
            alert(`URL 处理失败: ${e.message}`);
        }
    },

    _renderAttachments() {
        // File list
        const fileList = document.getElementById('file-list');
        if (this._files.length) {
            fileList.style.display = 'flex';
            fileList.innerHTML = this._files.map((f, i) =>
                `<span class="attach-tag">📄 ${this._esc(f.filename)} <button onclick="Chat._removeFile(${i})">&times;</button></span>`
            ).join('');
        } else {
            fileList.style.display = 'none';
        }

        // URL list
        const urlList = document.getElementById('url-list');
        if (this._urls.length) {
            urlList.style.display = 'flex';
            urlList.innerHTML = this._urls.map((u, i) =>
                `<span class="attach-tag">🔗 ${this._esc(u.url)} <button onclick="Chat._removeUrl(${i})">&times;</button></span>`
            ).join('');
        } else {
            urlList.style.display = 'none';
        }

        // Status
        const status = document.getElementById('input-status');
        const count = this._files.length + this._urls.length;
        status.textContent = count ? `${count} 个附件` : '';
    },

    _removeFile(index) {
        this._files.splice(index, 1);
        this._renderAttachments();
    },

    _removeUrl(index) {
        this._urls.splice(index, 1);
        this._renderAttachments();
    },

    _collectMentionedContextItems(text) {
        const docs = this._contextItems.filter(item => item.file_id && item.title);
        const matched = docs.filter(item => text.includes(`@${item.title}`));
        const dedup = new Map();
        matched.forEach(item => {
            const key = item.id || item.file_id;
            dedup.set(String(key), item);
        });
        return Array.from(dedup.values());
    },

    _getMentionTrigger(text, caretPos) {
        const prefix = text.slice(0, caretPos);
        const match = prefix.match(/(^|\s)@([^\s@]*)$/);
        if (!match) return null;
        const query = match[2] || '';
        const atIndex = prefix.length - query.length - 1;
        return { query, atIndex, caretPos };
    },

    _getMentionCandidates() {
        const docs = this._contextItems.filter(item => item.file_id && item.title);
        const dedup = new Map();
        docs.forEach(item => {
            const key = String(item.id || item.file_id || item.title);
            if (!dedup.has(key)) dedup.set(key, item);
        });
        return Array.from(dedup.values());
    },

    _hideMentionSuggestions() {
        const panel = document.getElementById('mention-suggest');
        if (panel) {
            panel.style.display = 'none';
            panel.innerHTML = '';
        }
        this._mentionState = null;
    },

    _renderMentionSuggestions() {
        const panel = document.getElementById('mention-suggest');
        if (!panel || !this._mentionState || !this._mentionState.candidates.length) {
            this._hideMentionSuggestions();
            return;
        }
        const activeIndex = this._mentionState.activeIndex ?? 0;
        panel.innerHTML = this._mentionState.candidates.map((item, idx) => `
            <button type="button" class="mention-suggest-item ${idx === activeIndex ? 'active' : ''}" data-id="${this._esc(item.id)}" data-index="${idx}">
                <span class="mention-suggest-title">${this._esc(item.title)}</span>
                <span class="mention-suggest-tag">参考文档</span>
            </button>
        `).join('');
        panel.style.display = '';
    },

    _selectMentionCandidateByIndex(index) {
        if (!this._mentionState) return;
        const total = this._mentionState.candidates.length;
        if (!total) return;
        this._mentionState.activeIndex = (index + total) % total;
        this._renderMentionSuggestions();
    },

    _applyMentionCandidate(itemId) {
        const input = document.getElementById('message-input');
        if (!input || !this._mentionState) return;
        const candidate = this._mentionState.candidates.find(item => String(item.id) === String(itemId));
        if (!candidate) return;

        const trigger = this._mentionState.trigger;
        const value = input.value;
        const mentionToken = `@${candidate.title} `;
        input.value = `${value.slice(0, trigger.atIndex)}${mentionToken}${value.slice(trigger.caretPos)}`;
        const nextPos = trigger.atIndex + mentionToken.length;
        input.setSelectionRange(nextPos, nextPos);
        input.focus();
        this._hideMentionSuggestions();
    },

    _updateMentionSuggestions() {
        const input = document.getElementById('message-input');
        if (!input) return;
        const trigger = this._getMentionTrigger(input.value, input.selectionStart || 0);
        if (!trigger || trigger.query !== '') {
            this._hideMentionSuggestions();
            return;
        }
        const candidates = this._getMentionCandidates();
        if (!candidates.length) {
            this._hideMentionSuggestions();
            return;
        }
        this._mentionState = {
            trigger,
            candidates,
            activeIndex: 0,
        };
        this._renderMentionSuggestions();
    },

    _bindEvents() {
        const signal = this._abortCtrl.signal;

        // Send button
        document.getElementById('send-btn').addEventListener('click', () => this.sendMessage(), { signal });

        // Enter to send
        const input = document.getElementById('message-input');
        input.addEventListener('keydown', (e) => {
            if (this._mentionState && this._mentionState.candidates?.length) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this._selectMentionCandidateByIndex((this._mentionState.activeIndex ?? 0) + 1);
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this._selectMentionCandidateByIndex((this._mentionState.activeIndex ?? 0) - 1);
                    return;
                }
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    const item = this._mentionState.candidates[this._mentionState.activeIndex ?? 0];
                    if (item) this._applyMentionCandidate(item.id);
                    return;
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    this._hideMentionSuggestions();
                    return;
                }
            }
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        }, { signal });

        // Auto-resize textarea
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 200) + 'px';
            this._updateMentionSuggestions();
        }, { signal });

        input.addEventListener('click', () => this._updateMentionSuggestions(), { signal });

        document.getElementById('mention-suggest').addEventListener('click', (e) => {
            const item = e.target.closest('.mention-suggest-item');
            if (!item) return;
            this._applyMentionCandidate(item.dataset.id);
        }, { signal });

        document.addEventListener('mousedown', (e) => {
            const panel = document.getElementById('mention-suggest');
            const inputEl = document.getElementById('message-input');
            if (!panel || panel.style.display === 'none') return;
            if (panel.contains(e.target) || inputEl.contains(e.target)) return;
            this._hideMentionSuggestions();
        }, { signal });

        // New chat
        document.getElementById('new-chat-btn').addEventListener('click', () => this.newConversation(), { signal });

        // Conversation list clicks
        document.getElementById('conversation-list').addEventListener('click', (e) => {
            const item = e.target.closest('.conv-item');
            const del = e.target.closest('.conv-del');
            if (del && item) {
                e.stopPropagation();
                this._deleteConversation(item.dataset.id);
            } else if (item) {
                this.selectConversation(item.dataset.id);
            }
        }, { signal });

        // File upload
        document.getElementById('file-input').addEventListener('change', (e) => {
            this.handleFileUpload(e.target.files);
            e.target.value = '';
        }, { signal });

        // URL button
        document.getElementById('url-btn').addEventListener('click', () => {
            this.showUrlInputModal();
        }, { signal });

        // Search
        document.getElementById('conv-search').addEventListener('input', (e) => {
            this._searchConversations(e.target.value);
        }, { signal });
    },

    async _deleteConversation(convId) {
        if (!confirm('确定删除此对话？')) return;
        try {
            await API.deleteConversation(convId);
            if (this._currentConvId == convId) {
                this.newConversation();
            }
            await this.loadConversations();
        } catch (e) {
            alert('删除失败: ' + e.message);
        }
    },

    showUrlInputModal() {
        Admin.showModal(`
            <h3>添加链接</h3>
            <div class="field">
                <label>URL</label>
                <input id="modal-url-input" placeholder="https://example.com/article" type="url">
            </div>
            <div id="url-input-error" class="field-error"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Chat.submitUrlFromModal()">提交</button>
            </div>
        `);
    },

    async submitUrlFromModal() {
        const url = document.getElementById('modal-url-input').value.trim();
        const errEl = document.getElementById('url-input-error');
        if (!url) { errEl.textContent = '请输入URL'; return; }
        try {
            await this.handleUrlSubmit(url);
            Admin.closeModal();
        } catch (e) {
            errEl.textContent = e.message || '提交失败';
        }
    },

    /* ── 上下文面板 ── */

    _getPanels() {
        const panels = [
            document.getElementById('chat-context-body'),
            document.getElementById('context-drawer-body'),
        ];
        return panels.filter(p => p != null);
    },

    _renderContextPanel() {
        const typeLabels = {
            historical_doc: '历史文档',
            rule_doc: '规则文档',
            temporary: '临时资料',
            manual_rule: '手动规则',
        };

        for (const panel of this._getPanels()) {
            for (const [type, label] of Object.entries(typeLabels)) {
                const container = panel.querySelector(`[data-items-type="${type}"]`);
                if (!container) continue;
                const items = this._contextItems.filter(i => i.context_type === type);
                if (!items.length) {
                    container.innerHTML = '<div class="empty-state" style="padding:var(--sp-3);font-size:var(--fs-12)">暂无</div>';
                    continue;
                }
                container.innerHTML = items.map(item => `
                    <div class="context-item" data-id="${item.id}">
                        <input type="checkbox" class="context-item-check" ${item.enabled ? 'checked' : ''} data-id="${item.id}">
                        <span class="context-item-name" title="${this._esc(item.title)}">${this._esc(item.title)}</span>
                        <span class="context-item-type">${label}</span>
                        <button class="context-item-del" data-id="${item.id}" title="删除">&times;</button>
                    </div>
                `).join('');
            }

            // Update summary
            const enabled = this._contextItems.filter(i => i.enabled);
            const docs = enabled.filter(i => i.context_type !== 'manual_rule').length;
            const rules = enabled.filter(i => i.context_type === 'manual_rule').length;
            const summaryText = panel.querySelector('[data-role="summary-text"]');
            const summaryHint = panel.querySelector('[data-role="summary-hint"]');
            if (summaryText && summaryHint) {
                if (docs + rules > 0) {
                    summaryText.textContent = `${docs} 个文档 · ${rules} 条规则 · 将随消息发送`;
                    summaryHint.textContent = 'AI 会在后续回复中持续参考这些资料';
                } else {
                    summaryText.textContent = '暂无上下文';
                    summaryHint.textContent = '添加资料后，AI 会在回复中持续参考';
                }
            }
        }
    },

    _isPersistedContextItemId(id) {
        return !!id && !String(id).startsWith('ctx_');
    },

    _isConversationCurrent(conversationId) {
        return String(this._currentConvId) === String(conversationId);
    },

    _queueContextSync(run, errorMessage) {
        if (!this._currentConvId) return Promise.resolve();

        this._contextSync = this._contextSync
            .catch(() => {})
            .then(async () => {
                try {
                    await run();
                } catch (e) {
                    console.error(errorMessage, e);
                }
            });

        return this._contextSync;
    },

    async _flushContextSync() {
        await this._contextSync.catch(() => {});
    },

    _toggleContextItem(id) {
        const item = this._contextItems.find(i => i.id === id);
        if (item) {
            const conversationId = this._currentConvId;
            item.enabled = !item.enabled;
            this._renderContextPanel();
            if (conversationId && this._isPersistedContextItemId(id)) {
                const enabled = item.enabled;
                this._queueContextSync(
                    () => API.updateContextItem(conversationId, id, { enabled }),
                    '更新上下文项失败:'
                );
            }
        }
    },

    _removeContextItem(id) {
        const conversationId = this._currentConvId;
        this._contextItems = this._contextItems.filter(i => i.id !== id);
        this._renderContextPanel();
        if (conversationId && this._isPersistedContextItemId(id)) {
            this._queueContextSync(
                () => API.deleteContextItem(conversationId, id),
                '删除上下文项失败:'
            );
        }
    },

    _clearContext() {
        const conversationId = this._currentConvId;
        const ids = this._contextItems.map(i => i.id);
        this._contextItems = [];
        this._renderContextPanel();
        const persistedIds = ids.filter(id => this._isPersistedContextItemId(id));
        if (conversationId && persistedIds.length) {
            this._queueContextSync(
                () => Promise.all(persistedIds.map(id => API.deleteContextItem(conversationId, id))),
                '清空上下文失败:'
            );
        }
    },

    async _addContextFile(files, contextType) {
        const conversationId = this._currentConvId;
        for (const file of files) {
            try {
                const result = await API.uploadFile(file);
                const item = {
                    id: null,
                    context_type: contextType,
                    title: file.name,
                    file_id: result.file_id,
                    url: null,
                    manual_text: null,
                    enabled: true,
                };
                if (conversationId) {
                    try {
                        const saved = await API.createContextItem(conversationId, {
                            context_type: contextType,
                            title: file.name,
                            file_id: result.file_id,
                            enabled: true,
                        });
                        item.id = String(saved.id);
                    } catch (e) {
                        item.id = 'ctx_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
                        console.error('持久化上下文项失败:', e);
                    }
                } else {
                    item.id = 'ctx_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
                }
                if (!this._isConversationCurrent(conversationId)) continue;
                this._contextItems.push(item);
            } catch (e) {
                alert(`上传失败: ${e.message}`);
            }
        }
        this._renderContextPanel();
    },

    _addManualRule() {
        Admin.showModal(`
            <h3>添加手动规则</h3>
            <div class="field">
                <textarea id="modal-rule-input" rows="3" placeholder="例如：请按高级产品经理视角回答，重点关注边界、价值和验收口径" style="width:100%;resize:vertical;min-height:60px"></textarea>
            </div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Chat._submitManualRule()">添加</button>
            </div>
        `);
    },

    async _submitManualRule() {
        const text = document.getElementById('modal-rule-input').value.trim();
        if (!text) return;
        const conversationId = this._currentConvId;
        const item = {
            id: null,
            context_type: 'manual_rule',
            title: text.length > 40 ? text.slice(0, 40) + '...' : text,
            file_id: null,
            url: null,
            manual_text: text,
            enabled: true,
        };
        if (conversationId) {
            try {
                const saved = await API.createContextItem(conversationId, {
                    context_type: 'manual_rule',
                    title: item.title,
                    manual_text: text,
                    enabled: true,
                });
                item.id = String(saved.id);
            } catch (e) {
                item.id = 'ctx_rule_' + Date.now();
                console.error('持久化手动规则失败:', e);
            }
        } else {
            item.id = 'ctx_rule_' + Date.now();
        }
        if (!this._isConversationCurrent(conversationId)) return;
        this._contextItems.push(item);
        this._renderContextPanel();
        Admin.closeModal();
    },

    async _persistPendingContextItems(conversationId, items) {
        const pendingItems = items.filter(item => !item.id || String(item.id).startsWith('ctx_'));
        if (!pendingItems.length) return;

        for (const item of pendingItems) {
            try {
                const saved = await API.createContextItem(conversationId, {
                    context_type: item.context_type,
                    title: item.title,
                    file_id: item.file_id,
                    url: item.url,
                    manual_text: item.manual_text,
                    enabled: item.enabled,
                });
                this._contextItems = this._contextItems.map(existing =>
                    String(existing.id) === String(item.id)
                        ? { ...existing, id: String(saved.id) }
                        : existing
                );
            } catch (e) {
                console.error('补持久化上下文项失败:', e);
            }
        }

        this._renderContextPanel();
    },

    _bindContextEvents() {
        if (!this._contextBound) {
            const signal = this._abortCtrl.signal;
            const panels = this._getPanels();

            for (const panel of panels) {
                // Checkbox toggles + file upload changes (delegated)
                panel.addEventListener('change', (e) => {
                    if (e.target.classList.contains('context-item-check')) {
                        this._toggleContextItem(e.target.dataset.id);
                    }
                    const uploadType = e.target.dataset.contextUpload;
                    if (uploadType) {
                        this._addContextFile(e.target.files, uploadType);
                        e.target.value = '';
                    }
                }, { signal });

                // Delete buttons + manual rule button (delegated)
                panel.addEventListener('click', (e) => {
                    if (e.target.classList.contains('context-item-del')) {
                        this._removeContextItem(e.target.dataset.id);
                    }
                    if (e.target.dataset.action === 'add-manual-rule' || e.target.closest('[data-action="add-manual-rule"]')) {
                        this._addManualRule();
                    }
                }, { signal });
            }

            // Clear buttons — main panel + drawer
            document.querySelectorAll('[data-action="clear-context"]').forEach(btn => {
                btn.addEventListener('click', () => {
                    if (confirm('确定清空当前对话的所有上下文？')) {
                        this._clearContext();
                    }
                }, { signal });
            });

            // Drag-and-drop for context sections in both panels
            this._bindContextDragDrop(signal);

            // Narrow-screen context drawer toggle
            const drawerBtn = document.getElementById('context-drawer-btn');
            if (drawerBtn) {
                drawerBtn.addEventListener('click', () => this._toggleContextDrawer(), { signal });
            }
            const drawerClose = document.getElementById('context-drawer-close');
            if (drawerClose) {
                drawerClose.addEventListener('click', () => this._closeContextDrawer(), { signal });
            }
            const drawerOverlay = document.getElementById('context-drawer-overlay');
            if (drawerOverlay) {
                drawerOverlay.addEventListener('click', () => this._closeContextDrawer(), { signal });
            }
            this._contextBound = true;
        }
        this._renderContextPanel();
    },

    _bindContextDragDrop(signal) {
        for (const panel of this._getPanels()) {
            const dropTargets = panel.querySelectorAll('.context-section');
            const handler = (e) => {
                e.preventDefault();
                e.stopPropagation();
            };
            dropTargets.forEach(section => {
                section.addEventListener('dragover', (e) => {
                    handler(e);
                    section.classList.add('drag-over');
                }, { signal });
                section.addEventListener('dragleave', () => {
                    section.classList.remove('drag-over');
                }, { signal });
                section.addEventListener('drop', (e) => {
                    handler(e);
                    section.classList.remove('drag-over');
                    const type = section.dataset.type;
                    const files = e.dataTransfer.files;
                    if (files.length) {
                        this._addContextFile(files, type);
                    }
                }, { signal });
            });
        }
    },

    _toggleContextDrawer() {
        const drawer = document.getElementById('context-drawer');
        const overlay = document.getElementById('context-drawer-overlay');
        const shouldOpen = drawer ? !drawer.classList.contains('open') : false;
        if (shouldOpen) {
            if (drawer) drawer.hidden = false;
            if (overlay) overlay.hidden = false;
            requestAnimationFrame(() => {
                if (drawer) drawer.classList.add('open');
                if (overlay) overlay.classList.add('open');
            });
            return;
        }
        this._closeContextDrawer();
    },

    _closeContextDrawer() {
        const drawer = document.getElementById('context-drawer');
        const overlay = document.getElementById('context-drawer-overlay');
        if (drawer) {
            drawer.classList.remove('open');
            drawer.hidden = true;
        }
        if (overlay) {
            overlay.classList.remove('open');
            overlay.hidden = true;
        }
    },

    async _searchConversations(query) {
        if (!query.trim()) {
            await this.loadConversations();
            return;
        }
        try {
            const data = await API.searchMessages(query);
            const list = document.getElementById('conversation-list');
            const items = data.results || data || [];
            list.innerHTML = items.map(r => `
                <div class="conv-item" data-id="${r.conversation_id}">
                    <span class="conv-title">${this._esc(r.conversation_title || '对话')}</span>
                </div>
            `).join('');
        } catch (e) {
            console.error('搜索失败:', e);
        }
    },
};
