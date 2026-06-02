/* 管理后台逻辑 */
const Admin = {
    _lastTab: null,
    _modelDragPreview: null,

    init() {
        const savedTab = this._lastTab || localStorage.getItem('admin-active-tab') || 'stats';
        const navItems = document.querySelectorAll('.admin-nav-item');
        const panels = document.querySelectorAll('.admin-panel');

        navItems.forEach(t => t.classList.remove('active'));
        panels.forEach(p => p.classList.remove('active'));

        const activeNav = document.querySelector(`.admin-nav-item[data-tab="${savedTab}"]`);
        const activeTab = activeNav ? savedTab : 'stats';
        if (activeNav) {
            activeNav.classList.add('active');
            document.getElementById(`tab-${savedTab}`).classList.add('active');
        } else {
            navItems[0]?.classList.add('active');
            panels[0]?.classList.add('active');
        }

        this._loadActiveTab(activeTab);
    },

    _loadActiveTab(tab) {
        const tabMap = {
            users: 'loadUsers',
            prompts: 'loadPrompts',
            'review-prompts': 'loadReviewPrompts',
            models: 'loadModels',
            skills: 'loadSkills',
            stats: 'loadStats',
        };
        const fn = tabMap[tab];
        if (fn && this[fn]) this[fn]();
    },

    saveActiveTab(tab) {
        this._lastTab = tab;
        localStorage.setItem('admin-active-tab', tab);
    },

    /* ── HTML 转义 ── */
    _esc(str) {
        if (str == null) return '';
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    },
    _escAttr(str) {
        if (str == null) return '';
        return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
    _formatDateTime(value) {
        if (!value) return '-';
        return new Intl.DateTimeFormat('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(value));
    },

    /* ── 模态框 ── */
    showModal(html) {
        const overlay = document.getElementById('modal-overlay');
        const content = document.getElementById('modal-content');
        content.innerHTML = `
            <button type="button" class="modal-close-btn" data-action="modal-close" aria-label="关闭弹窗">&times;</button>
            ${html}
        `;
        overlay.style.display = 'flex';
        content.querySelector('[data-action="modal-close"]')?.addEventListener('click', () => this.closeModal());
    },

    closeModal() {
        const overlay = document.getElementById('modal-overlay');
        overlay.style.display = 'none';
        overlay.onclick = null;
        document.getElementById('modal-content').innerHTML = '';
    },

    _bindSensitiveInputToggle(inputId) {
        const input = document.getElementById(inputId);
        const toggle = document.querySelector(`[data-toggle-target="${inputId}"]`);
        if (!input || !toggle) return;

        const EYE_OPEN = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
        const EYE_OFF = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

        const syncIcon = () => {
            const isHidden = input.type === 'password';
            toggle.innerHTML = isHidden ? EYE_OFF : EYE_OPEN;
            toggle.style.color = isHidden ? 'var(--gray-6)' : 'var(--color-brand)';
            toggle.setAttribute('aria-label', isHidden ? '显示密码' : '隐藏密码');
        };
        const hideValue = () => {
            if (input.type !== 'password') {
                input.type = 'password';
                syncIcon();
            }
        };

        input.type = 'password';
        syncIcon();
        toggle.addEventListener('click', () => {
            input.type = input.type === 'password' ? 'text' : 'password';
            syncIcon();
            input.focus();
        });
        input.addEventListener('paste', () => requestAnimationFrame(hideValue));
    },

    _syncThinkingFieldsVisibility() {
        const supported = document.getElementById('modal-thinking-supported')?.value === 'true';
        const adapter = document.getElementById('modal-thinking-adapter')?.value;
        const cfgFields = document.getElementById('thinking-config-fields');
        const adapterFields = document.getElementById('thinking-adapter-fields');
        const payloadFields = document.getElementById('thinking-payload-fields');
        if (cfgFields) cfgFields.style.display = supported ? '' : 'none';
        if (adapterFields) adapterFields.style.display = supported ? '' : 'none';
        if (payloadFields) payloadFields.style.display = (supported && adapter === 'custom_json') ? '' : 'none';
    },

    _bindThinkingFieldsVisibility() {
        const supportedEl = document.getElementById('modal-thinking-supported');
        const adapterEl = document.getElementById('modal-thinking-adapter');
        if (supportedEl) supportedEl.addEventListener('change', () => this._syncThinkingFieldsVisibility());
        if (adapterEl) adapterEl.addEventListener('change', () => this._syncThinkingFieldsVisibility());
    },

    _bindNewThinkingFieldsVisibility() {
        const supportedEl = document.getElementById('modal-new-thinking-supported');
        const adapterEl = document.getElementById('modal-new-thinking-adapter');
        const sync = () => {
            const supported = supportedEl?.value === 'true';
            const adapter = adapterEl?.value;
            const cfgFields = document.getElementById('new-thinking-config-fields');
            const adapterFields = document.getElementById('new-thinking-adapter-fields');
            const payloadFields = document.getElementById('new-thinking-payload-fields');
            if (cfgFields) cfgFields.style.display = supported ? '' : 'none';
            if (adapterFields) adapterFields.style.display = supported ? '' : 'none';
            if (payloadFields) payloadFields.style.display = (supported && adapter === 'custom_json') ? '' : 'none';
        };
        if (supportedEl) supportedEl.addEventListener('change', sync);
        if (adapterEl) adapterEl.addEventListener('change', sync);
    },

    async _persistModelOrder(modelIds) {
        if (typeof API.reorderAdminModels === 'function') {
            await API.reorderAdminModels(modelIds);
            return;
        }
        if (typeof API.request === 'function') {
            await API.request('PUT', '/api/admin/models/order', { model_ids: modelIds });
            return;
        }
        throw new Error('前端 API 对象缺少模型排序接口，请刷新页面后重试');
    },

    _removeModelDragPreview() {
        this._modelDragPreview?.remove();
        this._modelDragPreview = null;
    },

    _createModelDragPreview(row) {
        this._removeModelDragPreview();

        const preview = document.createElement('div');
        preview.className = 'model-drag-preview';

        const badge = document.createElement('div');
        badge.className = 'model-drag-preview-badge';
        badge.textContent = '调整顺序';

        const title = document.createElement('div');
        title.className = 'model-drag-preview-title';
        title.textContent = row.querySelector('strong')?.textContent?.trim() || '模型配置';

        const meta = document.createElement('div');
        meta.className = 'model-drag-preview-meta';
        meta.textContent = row.querySelector('small')?.textContent?.trim() || '拖动到目标位置';

        preview.appendChild(badge);
        preview.appendChild(title);
        preview.appendChild(meta);
        document.body.appendChild(preview);
        this._modelDragPreview = preview;
        return preview;
    },

    _clearModelDropIndicators(tbody) {
        tbody.querySelectorAll('tr.is-drop-target-before, tr.is-drop-target-after').forEach(row => {
            row.classList.remove('is-drop-target-before', 'is-drop-target-after');
        });
    },

    _bindModelDragAndDrop(tbody, models) {
        let draggedRow = null;
        const getRows = () => Array.from(tbody.querySelectorAll('tr[data-model-id]'));
        const persistCurrentOrder = async () => {
            const modelIds = getRows().map(row => row.dataset.modelId);
            if (modelIds.length !== models.length) return;
            await this._persistModelOrder(modelIds);
        };
        const startDrag = (row, event) => {
            draggedRow = row;
            row.classList.add('is-dragging');
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', row.dataset.modelId || '');
                const preview = this._createModelDragPreview(row);
                event.dataTransfer.setDragImage(preview, 28, 20);
            }
        };
        const endDrag = async (row) => {
            row.classList.remove('is-dragging');
            draggedRow = null;
            this._removeModelDragPreview();
            this._clearModelDropIndicators(tbody);
            try {
                await persistCurrentOrder();
            } catch (e) {
                alert('保存模型顺序失败: ' + e.message);
                this.loadModels();
            }
        };

        getRows().forEach(row => {
            const handle = row.querySelector('[data-role="drag-handle"]');

            row.addEventListener('dragstart', (event) => {
                startDrag(row, event);
            });

            handle?.addEventListener('dragstart', (event) => {
                startDrag(row, event);
            });

            row.addEventListener('dragover', (event) => {
                event.preventDefault();
                if (!draggedRow || draggedRow === row) return;
                this._clearModelDropIndicators(tbody);
                const rect = row.getBoundingClientRect();
                const insertAfter = event.clientY > rect.top + rect.height / 2;
                row.classList.add(insertAfter ? 'is-drop-target-after' : 'is-drop-target-before');
                tbody.insertBefore(draggedRow, insertAfter ? row.nextSibling : row);
            });

            row.addEventListener('drop', (event) => {
                event.preventDefault();
                this._clearModelDropIndicators(tbody);
            });

            row.addEventListener('dragend', async () => {
                await endDrag(row);
            });

            handle?.addEventListener('dragend', async () => {
                await endDrag(row);
            });
        });
    },

    /* ── 用户管理 ── */
    async loadUsers() {
        const tbody = document.getElementById('user-table-body');
        try {
            const users = await API.getUsers();
            tbody.innerHTML = users.map(u => `
                <tr>
                    <td>${this._esc(u.username)}</td>
                    <td><span class="tag ${u.role === 'admin' ? 'tag-gray' : 'tag-blue'}">${u.role === 'admin' ? '管理员' : '用户'}</span></td>
                    <td>${u.is_active ? '<span style="color:var(--green-6)">启用</span>' : '<span style="color:var(--red-6)">禁用</span>'}</td>
                    <td class="user-time-cell">${this._formatDateTime(u.created_at)}</td>
                    <td class="user-time-cell">${this._formatDateTime(u.last_active_at)}</td>
                    <td class="user-actions-cell">
                        <button class="btn btn-primary btn-sm" data-edit-user="${u.id}" data-username="${this._escAttr(u.username)}" data-role="${this._escAttr(u.role)}" data-active="${u.is_active}">编辑</button>
                        <button class="btn btn-danger btn-sm" data-delete-user="${u.id}">删除</button>
                    </td>
                </tr>
            `).join('');
            tbody.querySelectorAll('[data-edit-user]').forEach(btn => {
                btn.addEventListener('click', () => {
                    this.editUser(Number(btn.dataset.editUser), btn.dataset.username, btn.dataset.role, btn.dataset.active === 'true');
                });
            });
            tbody.querySelectorAll('[data-delete-user]').forEach(btn => {
                btn.addEventListener('click', () => this.deleteUser(Number(btn.dataset.deleteUser)));
            });
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="6" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
        }
    },

    editUser(id, username, role, isActive) {
        this.showModal(`
            <h3>编辑用户</h3>
            <div class="field">
                <label>用户名</label>
                <input id="modal-username" value="${this._escAttr(username)}" readonly style="background:var(--gray-2);color:var(--color-text-muted);cursor:not-allowed">
            </div>
            <div class="field">
                <label>新密码（留空不修改）</label>
                <input type="password" id="modal-password" placeholder="留空则不修改">
            </div>
            <div class="field">
                <label>角色</label>
                <select id="modal-role">
                    <option value="user" ${role === 'user' ? 'selected' : ''}>用户</option>
                    <option value="admin" ${role === 'admin' ? 'selected' : ''}>管理员</option>
                </select>
            </div>
            <div class="field">
                <label>状态</label>
                <select id="modal-active">
                    <option value="true" ${isActive ? 'selected' : ''}>启用</option>
                    <option value="false" ${!isActive ? 'selected' : ''}>禁用</option>
                </select>
            </div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Admin.saveUser(${id})">保存</button>
            </div>
        `);
    },

    async saveUser(id) {
        const data = {
            role: document.getElementById('modal-role').value,
            is_active: document.getElementById('modal-active').value === 'true',
        };
        const pwd = document.getElementById('modal-password').value;
        if (pwd) data.password = pwd;
        await API.updateUser(id, data);
        this.closeModal();
        this.loadUsers();
    },

    async deleteUser(id) {
        if (!confirm('确定要删除此用户吗？所有相关对话也会被删除。')) return;
        await API.deleteUser(id);
        this.loadUsers();
    },

    showAddUserForm() {
        this.showModal(`
            <h3>添加用户</h3>
            <div class="field">
                <label>用户名</label>
                <input id="modal-new-username" required>
            </div>
            <div class="field">
                <label>密码</label>
                <input type="password" id="modal-new-password" required minlength="6">
            </div>
            <div class="field">
                <label>角色</label>
                <select id="modal-new-role">
                    <option value="user">用户</option>
                    <option value="admin">管理员</option>
                </select>
            </div>
            <div id="new-user-error" class="field-error"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Admin.createUser()">创建</button>
            </div>
        `);
    },

    async createUser() {
        const errEl = document.getElementById('new-user-error');
        const username = document.getElementById('modal-new-username').value.trim();
        const password = document.getElementById('modal-new-password').value;
        if (!username) { errEl.textContent = '请填写用户名'; return; }
        if (!password || password.length < 6) { errEl.textContent = '密码至少6位'; return; }
        try {
            await API.createUser({
                username,
                password,
                role: document.getElementById('modal-new-role').value,
            });
            this.closeModal();
            this.loadUsers();
        } catch (e) {
            errEl.textContent = '创建失败: ' + e.message;
        }
    },

    /* ── Prompt 模板管理 ── */
    async loadPrompts() {
        const tbody = document.getElementById('prompt-table-body');
        try {
            const data = await API.getAdminPrompts();
            tbody.innerHTML = data.map(p => `
                <tr>
                    <td>${this._esc(p.name)}</td>
                    <td>${this._esc(p.description) || '-'}</td>
                    <td>${p.is_builtin ? '<span class="tag tag-green">内置</span>' : '<span class="tag tag-blue">自定义</span>'}</td>
                    <td>
                        <button class="btn btn-primary btn-sm" data-edit-prompt="${p.id}">编辑</button>
                        ${p.is_builtin ? '' : `<button class="btn btn-danger btn-sm" data-delete-prompt="${p.id}">删除</button>`}
                    </td>
                </tr>
            `).join('');
            tbody.querySelectorAll('[data-edit-prompt]').forEach(btn => {
                btn.addEventListener('click', () => this.editPrompt(Number(btn.dataset.editPrompt)));
            });
            tbody.querySelectorAll('[data-delete-prompt]').forEach(btn => {
                btn.addEventListener('click', () => this.deletePrompt(Number(btn.dataset.deletePrompt)));
            });
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="4" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
        }
    },

    editPrompt(id) {
        this.showModal(`
            <h3>编辑提示词模板</h3>
            <div id="prompt-edit-loading">加载中...</div>
            <div id="prompt-edit-form" style="display:none">
                <div class="field">
                    <label>模板名称</label>
                    <input id="modal-prompt-name">
                </div>
                <div class="field">
                    <label>描述</label>
                    <input id="modal-prompt-desc">
                </div>
                <div class="field">
                    <label>系统提示词 (system_prompt)</label>
                    <textarea id="modal-prompt-system" rows="4"></textarea>
                </div>
                <div class="field">
                    <label>用户提示词模板 (用 {content} 代表用户输入)</label>
                    <textarea id="modal-prompt-user" rows="4"></textarea>
                </div>
                <div id="prompt-edit-error" class="field-error"></div>
                <div class="btn-row">
                    <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                    <button class="btn btn-primary btn-sm" onclick="Admin.savePrompt(${id})">保存</button>
                </div>
            </div>
        `);

        API.getAdminPrompts().then(prompts => {
            const p = prompts.find(x => x.id === id);
            if (!p) { document.getElementById('prompt-edit-loading').textContent = '找不到模板'; return; }
            document.getElementById('prompt-edit-loading').style.display = 'none';
            document.getElementById('prompt-edit-form').style.display = '';
            document.getElementById('modal-prompt-name').value = p.name || '';
            document.getElementById('modal-prompt-desc').value = p.description || '';
            document.getElementById('modal-prompt-system').value = p.system_prompt || '';
            document.getElementById('modal-prompt-user').value = p.user_prompt_template || '';
        }).catch(e => {
            document.getElementById('prompt-edit-loading').textContent = '加载失败: ' + e.message;
        });
    },

    async savePrompt(id) {
        const errEl = document.getElementById('prompt-edit-error');
        const name = document.getElementById('modal-prompt-name').value.trim();
        if (!name) { errEl.textContent = '请填写模板名称'; return; }
        try {
            await API.updatePrompt(id, {
                name,
                description: document.getElementById('modal-prompt-desc').value.trim(),
                system_prompt: document.getElementById('modal-prompt-system').value,
                user_prompt_template: document.getElementById('modal-prompt-user').value,
            });
            this.closeModal();
            this.loadPrompts();
        } catch (e) {
            errEl.textContent = '保存失败: ' + e.message;
        }
    },

    createPrompt() {
        this.showModal(`
            <h3>新建提示词模板</h3>
            <div class="field">
                <label>模板名称</label>
                <input id="modal-prompt-name" placeholder="例如: 产品分析">
            </div>
            <div class="field">
                <label>描述</label>
                <input id="modal-prompt-desc" placeholder="模板用途说明">
            </div>
            <div class="field">
                <label>系统提示词 (system_prompt)</label>
                <textarea id="modal-prompt-system" rows="4" placeholder="定义AI的角色和行为"></textarea>
            </div>
            <div class="field">
                <label>用户提示词模板 (用 {content} 代表用户输入)</label>
                <textarea id="modal-prompt-user" rows="4" placeholder="例如: 请分析以下需求文档:\n{content}"></textarea>
            </div>
            <div id="prompt-edit-error" class="field-error"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Admin.saveNewPrompt()">创建</button>
            </div>
        `);
    },

    async saveNewPrompt() {
        const errEl = document.getElementById('prompt-edit-error');
        const name = document.getElementById('modal-prompt-name').value.trim();
        if (!name) { errEl.textContent = '请填写模板名称'; return; }
        try {
            await API.createPrompt({
                name,
                description: document.getElementById('modal-prompt-desc').value.trim(),
                system_prompt: document.getElementById('modal-prompt-system').value,
                user_prompt_template: document.getElementById('modal-prompt-user').value,
            });
            this.closeModal();
            this.loadPrompts();
        } catch (e) {
            errEl.textContent = '创建失败: ' + e.message;
        }
    },

    async deletePrompt(id) {
        if (!confirm('确定要删除此模板吗？')) return;
        await API.deletePrompt(id);
        this.loadPrompts();
    },

    /* ── 模型配置 & API Key 管理 ── */
    async loadModels() {
        const tbody = document.getElementById('model-table-body');
        try {
            const models = await API.getAdminModels();
            tbody.innerHTML = models.map(m => `
                <tr data-model-id="${this._escAttr(m.model_id)}" draggable="true">
                    <td>
                        <div class="model-title-cell">
                            <button type="button" class="model-drag-handle" data-role="drag-handle" draggable="true" aria-label="拖动调整模型顺序" title="拖动调整模型顺序">
                                <span class="model-drag-dots" aria-hidden="true">
                                    <span class="model-drag-dot"></span>
                                    <span class="model-drag-dot"></span>
                                    <span class="model-drag-dot"></span>
                                    <span class="model-drag-dot"></span>
                                    <span class="model-drag-dot"></span>
                                    <span class="model-drag-dot"></span>
                                </span>
                            </button>
                            <div>
                                <strong>${this._esc(m.name)}</strong><br><small style="color:var(--color-text-muted)">${this._esc(m.model_id)}</small>
                            </div>
                        </div>
                    </td>
                    <td><small>${this._esc(m.api_base)}</small></td>
                    <td>
                        <code style="font-size:var(--fs-12)">${m.api_key_masked || '未配置'}</code>
                    </td>
                    <td>
                        ${m.enabled
                            ? '<span style="color:var(--green-6)">已启用</span>'
                            : '<span style="color:var(--red-6)">已禁用</span>'}
                        ${m.thinking_supported ? ' <span class="tag tag-blue" style="font-size:var(--fs-11)">思考</span>' : ''}
                    </td>
                    <td class="model-connection-cell">
                        <span data-role="model-connection-status">
                            ${m.last_test_status === 'ok'
                                ? `<span style="color:var(--green-6)">正常</span>${m.last_test_latency_ms ? ` <small>(${m.last_test_latency_ms}ms)</small>` : ''}`
                                : m.last_test_status === 'fail'
                                    ? '<span style="color:var(--red-6)">异常</span>'
                                    : '<span style="color:var(--color-text-muted)">未测试</span>'}
                        </span>
                        <span class="model-connection-feedback" data-role="model-connection-feedback"></span>
                    </td>
                    <td class="model-actions-cell">
                        <div class="model-actions">
                            <button class="btn btn-primary btn-sm" data-action="edit-model">配置</button>
                            <button class="btn btn-sm" style="background:var(--green-6);color:#fff" data-action="test-model">测速</button>
                            <button class="btn btn-sm" style="background:var(--red-6);color:#fff" data-action="delete-model">删除</button>
                        </div>
                    </td>
                </tr>
            `).join('');
            tbody.querySelectorAll('[data-action="edit-model"]').forEach((btn, i) => {
                btn.addEventListener('click', () => this.editModel(models[i].model_id));
            });
            tbody.querySelectorAll('[data-action="test-model"]').forEach((btn, i) => {
                btn.addEventListener('click', (e) => this.testAndSpeed(models[i].model_id, e));
            });
            tbody.querySelectorAll('[data-action="delete-model"]').forEach((btn, i) => {
                btn.addEventListener('click', () => this.deleteModel(models[i].model_id));
            });
            this._bindModelDragAndDrop(tbody, models);
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="6" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
        }
    },

    createModel() {
        this.showModal(`
            <h3>新建模型</h3>
            <div class="field">
                <label>模型 ID（唯一标识，如 deepseek-v4-flash）</label>
                <input id="modal-new-model-id" placeholder="deepseek-v4-flash">
            </div>
            <div class="field">
                <label>显示名称</label>
                <input id="modal-new-model-name" placeholder="DeepSeek V4 Flash">
            </div>
            <div class="field">
                <label>API Base URL</label>
                <input id="modal-new-api-base" placeholder="https://api.deepseek.com/v1">
            </div>
            <div class="field">
                <label>LLM 模型名</label>
                <input id="modal-new-llm-model" placeholder="deepseek-v4-flash">
            </div>
            <div class="field">
                <label>API Key</label>
                <div class="sensitive-input">
                    <input type="password" id="modal-new-api-key" placeholder="输入该模型的 API Key" autocomplete="off">
                    <button type="button" class="sensitive-toggle-btn" data-toggle-target="modal-new-api-key">可见</button>
                </div>
            </div>
            <div class="field">
                <label>Max Tokens</label>
                <input type="number" id="modal-new-max-tokens" value="4096">
            </div>
            <div class="field">
                <label>Temperature</label>
                <input type="number" id="modal-new-temperature" value="0.7" step="0.1" min="0" max="2">
            </div>
            <div class="field">
                <label>支持思考模式</label>
                <select id="modal-new-thinking-supported">
                    <option value="false">不支持</option>
                    <option value="true">支持</option>
                </select>
            </div>
            <div class="field" id="new-thinking-config-fields" style="display:none">
                <label>默认思考等级</label>
                <select id="modal-new-thinking-level">
                    <option value="off">关</option>
                    <option value="low">Low</option>
                    <option value="high">High</option>
                </select>
            </div>
            <div class="field" id="new-thinking-adapter-fields" style="display:none">
                <label>思考适配器</label>
                <select id="modal-new-thinking-adapter">
                    <option value="none">无</option>
                    <option value="openai_reasoning">OpenAI Reasoning</option>
                    <option value="deepseek_reasoner">DeepSeek Reasoner</option>
                    <option value="qwen_thinking">Qwen Thinking</option>
                    <option value="custom_json">自定义 JSON</option>
                </select>
            </div>
            <div class="field" id="new-thinking-payload-fields" style="display:none">
                <label>自定义思考参数 (JSON)</label>
                <textarea id="modal-new-thinking-payload" rows="4" placeholder='{"reasoning_effort":"{{level}}"}'></textarea>
                <small style="color:var(--color-text-muted)">支持 {{level}} 占位符，运行时替换为 low/high</small>
            </div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Admin.saveNewModel()">创建</button>
            </div>
        `);
        this._bindSensitiveInputToggle('modal-new-api-key');
        this._bindNewThinkingFieldsVisibility();
    },

    async saveNewModel() {
        const modelId = document.getElementById('modal-new-model-id').value.trim();
        const name = document.getElementById('modal-new-model-name').value.trim();
        const apiBase = document.getElementById('modal-new-api-base').value.trim();
        const llmModel = document.getElementById('modal-new-llm-model').value.trim();
        const apiKey = document.getElementById('modal-new-api-key').value;
        const maxTokens = parseInt(document.getElementById('modal-new-max-tokens').value);
        const temperature = parseFloat(document.getElementById('modal-new-temperature').value);
        const thinkingSupported = document.getElementById('modal-new-thinking-supported').value === 'true';
        const thinkingLevel = document.getElementById('modal-new-thinking-level').value;
        const thinkingAdapter = document.getElementById('modal-new-thinking-adapter').value;
        const thinkingPayloadRaw = document.getElementById('modal-new-thinking-payload').value.trim();
        const thinkingPayload = thinkingPayloadRaw || null;

        if (!modelId || !name || !apiBase || !llmModel) {
            alert('模型 ID、显示名称、API Base URL、LLM 模型名 为必填项');
            return;
        }

        if (thinkingPayload) {
            try { JSON.parse(thinkingPayload); } catch { alert('自定义思考参数必须是合法 JSON'); return; }
        }

        try {
            await API.createModel({
                model_id: modelId, name, api_base: apiBase, llm_model: llmModel,
                api_key: apiKey || undefined, max_tokens: maxTokens, temperature,
                thinking_supported: thinkingSupported,
                thinking_level: thinkingSupported ? thinkingLevel : 'off',
                thinking_adapter: thinkingSupported ? thinkingAdapter : 'none',
                thinking_payload: thinkingSupported ? thinkingPayload : null,
            });
            this.closeModal();
            this.loadModels();
        } catch (e) {
            alert('创建失败: ' + e.message);
        }
    },

    editModel(modelId) {
        this.showModal(`
            <h3>模型配置</h3>
            <div class="field">
                <label>模型 ID</label>
                <input id="modal-model-id-display" value="${this._escAttr(modelId)}" disabled style="background:var(--gray-2)">
            </div>
            <div class="field">
                <label>显示名称</label>
                <input id="modal-model-name" placeholder="如: DeepSeek V4 Flash">
            </div>
            <div class="field">
                <label>API Key</label>
                <div class="sensitive-input">
                    <input type="password" id="modal-api-key" placeholder="输入新的 API Key（留空不修改）" autocomplete="off">
                    <button type="button" class="sensitive-toggle-btn" data-toggle-target="modal-api-key">可见</button>
                </div>
                <small style="color:var(--color-text-muted)">输入新值将覆盖已有 Key，留空则不修改</small>
            </div>
            <div class="field">
                <label>API Base URL</label>
                <input id="modal-api-base" placeholder="https://api.example.com/v1">
            </div>
            <div class="field">
                <label>LLM 模型名</label>
                <input id="modal-llm-model" placeholder="model-name">
            </div>
            <div class="field">
                <label>Max Tokens</label>
                <input type="number" id="modal-max-tokens" value="4096">
            </div>
            <div class="field">
                <label>Temperature</label>
                <input type="number" id="modal-temperature" value="0.7" step="0.1" min="0" max="2">
            </div>
            <div class="field">
                <label>启用</label>
                <select id="modal-enabled">
                    <option value="true">启用</option>
                    <option value="false">禁用</option>
                </select>
            </div>
            <div class="field">
                <label>支持思考模式</label>
                <select id="modal-thinking-supported">
                    <option value="false">不支持</option>
                    <option value="true">支持</option>
                </select>
            </div>
            <div class="field" id="thinking-config-fields" style="display:none">
                <label>默认思考等级</label>
                <select id="modal-thinking-level">
                    <option value="off">关</option>
                    <option value="low">Low</option>
                    <option value="high">High</option>
                </select>
            </div>
            <div class="field" id="thinking-adapter-fields" style="display:none">
                <label>思考适配器</label>
                <select id="modal-thinking-adapter">
                    <option value="none">无</option>
                    <option value="openai_reasoning">OpenAI Reasoning</option>
                    <option value="deepseek_reasoner">DeepSeek Reasoner</option>
                    <option value="qwen_thinking">Qwen Thinking</option>
                    <option value="custom_json">自定义 JSON</option>
                </select>
            </div>
            <div class="field" id="thinking-payload-fields" style="display:none">
                <label>自定义思考参数 (JSON)</label>
                <textarea id="modal-thinking-payload" rows="4" placeholder='{"reasoning_effort":"{{level}}"}'></textarea>
                <small style="color:var(--color-text-muted)">支持 {{level}} 占位符，运行时替换为 low/high</small>
            </div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" id="btn-save-model">保存</button>
            </div>
        `);

        this._bindSensitiveInputToggle('modal-api-key');
        this._bindThinkingFieldsVisibility();
        document.getElementById('btn-save-model').addEventListener('click', () => this.saveModel(modelId));

        API.getAdminModels().then(models => {
            const m = models.find(x => x.model_id === modelId);
            if (m) {
                document.getElementById('modal-model-name').value = m.name || '';
                document.getElementById('modal-api-base').value = m.api_base || '';
                document.getElementById('modal-llm-model').value = m.llm_model || '';
                document.getElementById('modal-max-tokens').value = m.max_tokens || 4096;
                document.getElementById('modal-temperature').value = m.temperature || 0.7;
                document.getElementById('modal-enabled').value = String(m.enabled);
                document.getElementById('modal-thinking-supported').value = String(m.thinking_supported || false);
                document.getElementById('modal-thinking-level').value = m.thinking_level || 'off';
                document.getElementById('modal-thinking-adapter').value = m.thinking_adapter || 'none';
                if (m.thinking_payload) document.getElementById('modal-thinking-payload').value = m.thinking_payload;
                this._syncThinkingFieldsVisibility();
            }
        });
    },

    async saveModel(modelId) {
        const name = document.getElementById('modal-model-name').value.trim();
        const apiKey = document.getElementById('modal-api-key').value;
        const apiBase = document.getElementById('modal-api-base').value;
        const llmModel = document.getElementById('modal-llm-model').value;
        const maxTokens = parseInt(document.getElementById('modal-max-tokens').value);
        const temperature = parseFloat(document.getElementById('modal-temperature').value);
        const enabled = document.getElementById('modal-enabled').value === 'true';
        const thinkingSupported = document.getElementById('modal-thinking-supported').value === 'true';
        const thinkingLevel = document.getElementById('modal-thinking-level').value;
        const thinkingAdapter = document.getElementById('modal-thinking-adapter').value;
        const thinkingPayloadRaw = document.getElementById('modal-thinking-payload').value.trim();
        const thinkingPayload = thinkingPayloadRaw || null;

        if (thinkingPayload) {
            try { JSON.parse(thinkingPayload); } catch { alert('自定义思考参数必须是合法 JSON'); return; }
        }

        try {
            if (apiKey) await API.updateModelApiKey(modelId, apiKey);
            await API.updateModelConfig(modelId, {
                name, api_base: apiBase, llm_model: llmModel,
                max_tokens: maxTokens, temperature, enabled,
                thinking_supported: thinkingSupported,
                thinking_level: thinkingSupported ? thinkingLevel : 'off',
                thinking_adapter: thinkingSupported ? thinkingAdapter : 'none',
                thinking_payload: thinkingSupported ? thinkingPayload : null,
            });
            this.closeModal();
            this.loadModels();
        } catch (e) {
            alert('保存失败: ' + e.message);
        }
    },

    async testAndSpeed(modelId, evt) {
        const btn = evt ? evt.currentTarget : null;
        const row = document.querySelector(`tr[data-model-id="${this._escAttr(modelId)}"]`);
        const connectionCell = row?.querySelector('[data-role="model-connection-status"]');
        const feedbackEl = row?.querySelector('[data-role="model-connection-feedback"]');
        try {
            if (btn) btn.disabled = true;
            if (feedbackEl) {
                feedbackEl.textContent = '连接测试中...';
                feedbackEl.style.color = 'var(--blue-6)';
            }
            const connResult = await API.testModelConnection(modelId);
            if (connResult.status !== 'ok') {
                if (btn) btn.disabled = false;
                if (feedbackEl) {
                    feedbackEl.textContent = '连接失败';
                    feedbackEl.style.color = 'var(--red-6)';
                }
                alert('连接失败: ' + (connResult.detail || '无法连接到服务器'));
                this.loadModels();
                return;
            }
            if (feedbackEl) {
                feedbackEl.textContent = '测速中...';
                feedbackEl.style.color = 'var(--blue-6)';
            }
            const speedResult = await API.speedTestModel(modelId);
            if (btn) btn.disabled = false;
            if (speedResult.status === 'ok') {
                if (feedbackEl) {
                    feedbackEl.textContent = `延迟 ${speedResult.latency_ms}ms`;
                    feedbackEl.style.color = 'var(--green-6)';
                }
            } else {
                if (feedbackEl) {
                    feedbackEl.textContent = '测速失败';
                    feedbackEl.style.color = 'var(--red-6)';
                }
                alert('连接成功但测速失败: ' + (speedResult.detail || '未知错误'));
            }
            this.loadModels();
        } catch (e) {
            if (btn) btn.disabled = false;
            if (connectionCell) connectionCell.style.color = '';
            if (feedbackEl) {
                feedbackEl.textContent = '测试失败';
                feedbackEl.style.color = 'var(--red-6)';
            }
            alert('测试失败: ' + e.message);
        }
    },

    async deleteModel(modelId) {
        if (!confirm(`确定删除模型 "${this._esc(modelId)}"？删除后不可恢复。`)) return;
        try {
            await API.deleteModel(modelId);
            this.loadModels();
        } catch (e) {
            alert('删除失败: ' + e.message);
        }
    },

    /* ── Skills 管理 ── */
    async loadSkills() {
        const tbody = document.getElementById('skill-table-body');
        if (!tbody) return;
        try {
            const skills = await API.getAdminSkills();
            tbody.innerHTML = skills.map(skill => `
                <tr>
                    <td>
                        <strong>${this._esc(skill.name)}</strong><br>
                        <small style="color:var(--color-text-muted)">${this._esc(skill.skill_id)}</small>
                    </td>
                    <td>${this._esc(skill.description)}</td>
                    <td><small>${this._esc(skill.local_path) || '-'}</small></td>
                    <td>
                        ${skill.update_url
                            ? `<small title="${this._escAttr(skill.update_url)}">${this._esc(skill.update_url)}</small>`
                            : '<span style="color:var(--color-text-muted)">未配置</span>'}
                    </td>
                    <td>
                        <button class="btn btn-primary btn-sm" data-edit-skill="${this._escAttr(skill.skill_id)}">配置</button>
                    </td>
                </tr>
            `).join('');
            tbody.querySelectorAll('[data-edit-skill]').forEach((btn, i) => {
                btn.addEventListener('click', () => this.editSkillUpdateUrl(skills[i]));
            });
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="5" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
        }
    },

    editSkillUpdateUrl(skill) {
        this.showModal(`
            <h3>配置 Skill 更新地址</h3>
            <div class="field">
                <label>Skill</label>
                <input value="${this._escAttr(skill.name)}（${this._escAttr(skill.skill_id)}）" readonly style="background:var(--gray-2);color:var(--color-text-muted);cursor:not-allowed">
            </div>
            <div class="field">
                <label>基本功能</label>
                <textarea rows="3" readonly style="background:var(--gray-2);color:var(--color-text-muted);cursor:not-allowed">${this._esc(skill.description)}</textarea>
            </div>
            <div class="field">
                <label>更新地址</label>
                <input id="modal-skill-update-url" value="${this._escAttr(skill.update_url || '')}" placeholder="例如：https://example.com/skills/${this._escAttr(skill.skill_id)}.git">
                <small style="color:var(--color-text-muted)">本期只保存地址，不自动拉取更新；后续可接入 SkillRegistry 或 pi-agent 编排。</small>
            </div>
            <div id="skill-edit-error" class="field-error" aria-live="polite"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Admin.saveSkillUpdateUrl('${this._escAttr(skill.skill_id)}')">保存</button>
            </div>
        `);
    },

    async saveSkillUpdateUrl(skillId) {
        const errEl = document.getElementById('skill-edit-error');
        const updateUrl = document.getElementById('modal-skill-update-url').value.trim();
        try {
            await API.updateAdminSkill(skillId, { update_url: updateUrl || null });
            this.closeModal();
            this.loadSkills();
        } catch (e) {
            errEl.textContent = '保存失败: ' + e.message;
        }
    },

    /* ── 统计 ── */
    _formatDateTime(value) {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return this._esc(value);
        return new Intl.DateTimeFormat('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }).format(date);
    },

    _renderRecentVisits(records = []) {
        const tbody = document.getElementById('recent-visits-body');
        if (!tbody) return;
        if (!records.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="color:var(--color-text-muted)">最近7天暂无访问记录</td></tr>';
            return;
        }
        tbody.innerHTML = records.map(item => `
            <tr>
                <td>${this._formatDateTime(item.timestamp)}</td>
                <td>${this._esc(item.username || '-')}</td>
                <td>${this._esc(item.action || '-')}</td>
                <td>${this._esc(item.path || '-')}</td>
                <td>${this._esc(item.client_ip || '-')}</td>
                <td>${item.result === 'success' ? '<span class="tag tag-green">成功</span>' : `<span class="tag tag-gray">${this._esc(item.result || '-')}</span>`}</td>
            </tr>
        `).join('');
    },

    async loadStats() {
        const grid = document.getElementById('stats-grid');
        const visitsBody = document.getElementById('recent-visits-body');
        try {
            const s = await API.getStats();
            grid.innerHTML = `
                <div class="stat-card"><div class="stat-value">${s.user_count}</div><div class="stat-label">用户数</div></div>
                <div class="stat-card"><div class="stat-value">${s.conversation_count}</div><div class="stat-label">对话数</div></div>
                <div class="stat-card"><div class="stat-value">${s.message_count}</div><div class="stat-label">消息数</div></div>
            `;
            this._renderRecentVisits(s.recent_visits || []);
        } catch (e) {
            grid.innerHTML = `<div style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</div>`;
            if (visitsBody) {
                visitsBody.innerHTML = `<tr><td colspan="6" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
            }
        }
    },

    /* ── 评审风格Prompt管理 ── */
    async loadReviewPrompts() {
        const tbody = document.getElementById('review-prompt-table-body');
        try {
            const data = await API.getReviewPrompts();
            tbody.innerHTML = data.map(p => `
                <tr>
                    <td>${this._esc(p.name)}</td>
                    <td>${this._esc(p.description) || '-'}</td>
                    <td>${p.is_active ? '<span style="color:var(--green-6)">启用</span>' : '<span style="color:var(--color-text-muted)">禁用</span>'}</td>
                    <td>
                        <button class="btn btn-primary btn-sm" data-edit-rp="${p.id}">编辑</button>
                    </td>
                </tr>
            `).join('');
            tbody.querySelectorAll('[data-edit-rp]').forEach(btn => {
                btn.addEventListener('click', () => this.editReviewPrompt(Number(btn.dataset.editRp)));
            });
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="4" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
        }
    },

    editReviewPrompt(id) {
        this.showModal(`
            <h3>编辑评审风格Prompt</h3>
            <div id="rp-edit-loading">加载中...</div>
            <div id="rp-edit-form" style="display:none">
                <div class="field">
                    <label>名称</label>
                    <input id="modal-rp-name">
                </div>
                <div class="field">
                    <label>描述</label>
                    <input id="modal-rp-desc">
                </div>
                <div class="field">
                    <label>提示词内容</label>
                    <textarea id="modal-rp-content" rows="8"></textarea>
                </div>
                <div id="rp-edit-error" class="field-error"></div>
                <div class="btn-row">
                    <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                    <button class="btn btn-primary btn-sm" onclick="Admin.saveReviewPrompt(${id})">保存</button>
                </div>
            </div>
        `);

        API.getReviewPrompts().then(prompts => {
            const p = prompts.find(x => x.id === id);
            if (!p) { document.getElementById('rp-edit-loading').textContent = '找不到提示词'; return; }
            document.getElementById('rp-edit-loading').style.display = 'none';
            document.getElementById('rp-edit-form').style.display = '';
            document.getElementById('modal-rp-name').value = p.name || '';
            document.getElementById('modal-rp-desc').value = p.description || '';
            document.getElementById('modal-rp-content').value = p.content || '';
        }).catch(e => {
            document.getElementById('rp-edit-loading').textContent = '加载失败: ' + e.message;
        });
    },

    async saveReviewPrompt(id) {
        const errEl = document.getElementById('rp-edit-error');
        const name = document.getElementById('modal-rp-name').value.trim();
        if (!name) { errEl.textContent = '请填写名称'; return; }
        try {
            await API.updateReviewPrompt(id, {
                name,
                description: document.getElementById('modal-rp-desc').value.trim(),
                content: document.getElementById('modal-rp-content').value,
            });
            this.closeModal();
            this.loadReviewPrompts();
        } catch (e) {
            errEl.textContent = '保存失败: ' + e.message;
        }
    },

    createReviewPrompt() {
        this.showModal(`
            <h3>新建评审风格Prompt</h3>
            <div class="field">
                <label>名称</label>
                <input id="modal-rp-name" placeholder="例如: 快速审查">
            </div>
            <div class="field">
                <label>描述</label>
                <input id="modal-rp-desc" placeholder="提示词用途说明">
            </div>
            <div class="field">
                <label>提示词内容</label>
                <textarea id="modal-rp-content" rows="8" placeholder="定义审查的维度和输出格式"></textarea>
            </div>
            <div id="rp-edit-error" class="field-error"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Admin.saveNewReviewPrompt()">创建</button>
            </div>
        `);
    },

    async saveNewReviewPrompt() {
        const errEl = document.getElementById('rp-edit-error');
        const name = document.getElementById('modal-rp-name').value.trim();
        if (!name) { errEl.textContent = '请填写名称'; return; }
        try {
            await API.createReviewPrompt({
                name,
                description: document.getElementById('modal-rp-desc').value.trim(),
                content: document.getElementById('modal-rp-content').value,
            });
            this.closeModal();
            this.loadReviewPrompts();
        } catch (e) {
            errEl.textContent = '创建失败: ' + e.message;
        }
    },
};

window.Admin = Admin;

/* ── Tab 切换 ── */
document.addEventListener('click', (e) => {
    const tab = e.target.closest('.admin-nav-item');
    if (!tab) return;

    const tabName = tab.dataset.tab;
    document.querySelectorAll('.admin-nav-item').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.admin-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    Admin.saveActiveTab(tabName);
    Admin._loadActiveTab(tabName);
});
