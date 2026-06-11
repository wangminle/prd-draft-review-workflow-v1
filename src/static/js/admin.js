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
            'pi-agent': 'loadPiAgentConfig',
            agent: 'loadAgentSettings',
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
                        <label class="skill-toggle">
                            <input type="checkbox" ${skill.status === 'active' ? 'checked' : ''} data-toggle-skill="${this._escAttr(skill.skill_id)}">
                            <span class="skill-toggle-slider"></span>
                        </label>
                    </td>
                    <td>
                        <button class="btn btn-primary btn-sm" data-edit-skill="${this._escAttr(skill.skill_id)}">配置</button>
                    </td>
                </tr>
            `).join('');
            tbody.querySelectorAll('[data-edit-skill]').forEach((btn, i) => {
                btn.addEventListener('click', () => this.editSkillUpdateUrl(skills[i]));
            });
            // P4.Pre.6: 技能启用/禁用开关
            tbody.querySelectorAll('[data-toggle-skill]').forEach((cb, i) => {
                cb.addEventListener('change', () => this.toggleSkillStatus(skills[i].skill_id, cb.checked ? 'active' : 'inactive'));
            });
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="6" style="color:var(--color-danger)">加载失败: ${this._esc(e.message)}</td></tr>`;
        }
    },

    async toggleSkillStatus(skillId, status) {
        try {
            await API.toggleAdminSkill(skillId, { status });
        } catch (e) {
            alert('操作失败: ' + e.message);
            this.loadSkills();  // 回滚 UI
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

    /* ── Pi Agent 配置 ── */
    _piAgentData: null,

    async loadPiAgentConfig() {
        const area = document.getElementById('pi-agent-config-area');
        if (!area) return;
        try {
            const cfg = await API.getPiAgentConfig();
            this._piAgentData = cfg;
            area.innerHTML = this._renderPiAgentConfigHTML(cfg);
            this._bindPiAgentEvents(cfg);
        } catch (e) {
            area.innerHTML = `<div style="color:var(--color-danger);padding:16px">加载失败: ${this._esc(e.message)}</div>`;
        }
    },

    _renderPiAgentConfigHTML(cfg) {
        return `
        <div class="pi-agent-sections">
            <!-- 全局开关 -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>全局开关</h4>
                    <label class="pi-agent-toggle">
                        <input type="checkbox" id="pi-enabled" ${cfg.enabled ? 'checked' : ''}>
                        <span>启用 Pi Agent</span>
                    </label>
                </div>
                <p class="pi-agent-section-desc">启用后，智能对话页面将使用 Pi Agent 作为对话引擎（通过 RPC 子进程模式），替代直接 LLM 调用。</p>
            </div>

            <!-- 大模型配置 -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>🧠 大模型 (LLM)</h4>
                    <span class="pi-agent-status-badge ${cfg.llm_has_api_key ? 'badge-ok' : 'badge-warn'}">${cfg.llm_has_api_key ? '已配置' : '未配置'}</span>
                </div>
                <div class="pi-agent-fields">
                    <div class="field">
                        <label>Provider</label>
                        <select id="pi-llm-provider">
                            <option value="deepseek" ${cfg.llm_provider === 'deepseek' ? 'selected' : ''}>DeepSeek (原生)</option>
                            <option value="openai" ${cfg.llm_provider === 'openai' ? 'selected' : ''}>OpenAI</option>
                            <option value="openai_compatible" ${cfg.llm_provider === 'openai_compatible' ? 'selected' : ''}>OpenAI 兼容</option>
                            <option value="anthropic" ${cfg.llm_provider === 'anthropic' ? 'selected' : ''}>Anthropic</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>API Base URL</label>
                        <input id="pi-llm-api-base" value="${this._escAttr(cfg.llm_api_base || '')}" placeholder="https://api.deepseek.com/v1">
                    </div>
                    <div class="field">
                        <label>模型名</label>
                        <input id="pi-llm-model" value="${this._escAttr(cfg.llm_model || '')}" placeholder="deepseek-chat">
                    </div>
                    <div class="field">
                        <label>API Key</label>
                        <div class="sensitive-input">
                            <input type="password" id="pi-llm-api-key" placeholder="${cfg.llm_api_key_masked ? '已配置，留空不修改' : '输入 API Key'}" autocomplete="off">
                            <button type="button" class="sensitive-toggle-btn" data-toggle-target="pi-llm-api-key">可见</button>
                        </div>
                        ${cfg.llm_api_key_masked ? `<small style="color:var(--color-text-muted)">当前: ${this._esc(cfg.llm_api_key_masked)}</small>` : ''}
                    </div>
                    <div class="field-row">
                        <div class="field">
                            <label>Max Tokens</label>
                            <input type="number" id="pi-llm-max-tokens" value="${cfg.llm_max_tokens != null ? cfg.llm_max_tokens : 4096}">
                        </div>
                        <div class="field">
                            <label>Temperature</label>
                            <input type="number" id="pi-llm-temperature" value="${cfg.llm_temperature != null ? cfg.llm_temperature : 0.7}" step="0.1" min="0" max="2">
                        </div>
                    </div>
                    <div class="field">
                        <button class="btn btn-sm" style="background:var(--green-6);color:#fff" id="pi-llm-test-btn">连接测试</button>
                        <button class="btn btn-sm" style="background:var(--blue-6);color:#fff" id="pi-llm-speed-btn">测速</button>
                        <span id="pi-llm-test-feedback" style="margin-left:8px;font-size:var(--fs-13)"></span>
                    </div>
                </div>
            </div>

            <!-- Search Tool 配置 -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>🔍 Search Tool (知识库检索)</h4>
                    <label class="pi-agent-toggle">
                        <input type="checkbox" id="pi-search-enabled" ${cfg.search_enabled ? 'checked' : ''}>
                        <span>启用</span>
                    </label>
                </div>
                <div class="pi-agent-fields" id="pi-search-fields" style="${cfg.search_enabled ? '' : 'display:none'}">
                    <div class="field">
                        <label>Provider</label>
                        <select id="pi-search-provider">
                            <option value="builtin" ${cfg.search_provider === 'builtin' ? 'selected' : ''}>内置检索 (LanceDB+FTS5)</option>
                            <option value="openai_compatible" ${cfg.search_provider === 'openai_compatible' ? 'selected' : ''}>OpenAI 兼容 API</option>
                            <option value="tavily" ${cfg.search_provider === 'tavily' ? 'selected' : ''}>Tavily</option>
                            <option value="serpapi" ${cfg.search_provider === 'serpapi' ? 'selected' : ''}>SerpAPI</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>API Base URL (外部检索)</label>
                        <input id="pi-search-api-base" value="${this._escAttr(cfg.search_api_base || '')}" placeholder="https://api.tavily.com/v1">
                    </div>
                    <div class="field">
                        <label>API Key (外部检索)</label>
                        <div class="sensitive-input">
                            <input type="password" id="pi-search-api-key" placeholder="${cfg.search_api_key_masked ? '已配置，留空不修改' : '输入 API Key'}" autocomplete="off">
                            <button type="button" class="sensitive-toggle-btn" data-toggle-target="pi-search-api-key">可见</button>
                        </div>
                        ${cfg.search_api_key_masked ? `<small style="color:var(--color-text-muted)">当前: ${this._esc(cfg.search_api_key_masked)}</small>` : ''}
                    </div>
                    <div class="field">
                        <label>最大返回结果数</label>
                        <input type="number" id="pi-search-max-results" value="${cfg.search_max_results != null ? cfg.search_max_results : 5}" min="1" max="20">
                    </div>
                </div>
            </div>

            <!-- Vision 配置 -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>👁️ Vision (读图)</h4>
                    <label class="pi-agent-toggle">
                        <input type="checkbox" id="pi-vision-enabled" ${cfg.vision_enabled ? 'checked' : ''}>
                        <span>启用</span>
                    </label>
                </div>
                <div class="pi-agent-fields" id="pi-vision-fields" style="${cfg.vision_enabled ? '' : 'display:none'}">
                    <div class="field">
                        <label>Provider</label>
                        <select id="pi-vision-provider">
                            <option value="openai_compatible" ${cfg.vision_provider === 'openai_compatible' ? 'selected' : ''}>OpenAI 兼容</option>
                            <option value="openai" ${cfg.vision_provider === 'openai' ? 'selected' : ''}>OpenAI</option>
                            <option value="deepseek" ${cfg.vision_provider === 'deepseek' ? 'selected' : ''}>DeepSeek VL</option>
                            <option value="qwen" ${cfg.vision_provider === 'qwen' ? 'selected' : ''}>Qwen VL</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>API Base URL</label>
                        <input id="pi-vision-api-base" value="${this._escAttr(cfg.vision_api_base || '')}" placeholder="https://api.openai.com/v1">
                    </div>
                    <div class="field">
                        <label>API Key</label>
                        <div class="sensitive-input">
                            <input type="password" id="pi-vision-api-key" placeholder="${cfg.vision_api_key_masked ? '已配置，留空不修改' : '输入 API Key'}" autocomplete="off">
                            <button type="button" class="sensitive-toggle-btn" data-toggle-target="pi-vision-api-key">可见</button>
                        </div>
                        ${cfg.vision_api_key_masked ? `<small style="color:var(--color-text-muted)">当前: ${this._esc(cfg.vision_api_key_masked)}</small>` : ''}
                    </div>
                    <div class="field">
                        <label>视觉模型名</label>
                        <input id="pi-vision-model" value="${this._escAttr(cfg.vision_model || '')}" placeholder="gpt-4o / deepseek-vl">
                    </div>
                </div>
            </div>

            <!-- Extension 配置 -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>🔌 Extension (扩展与权限)</h4>
                </div>
                <div class="pi-agent-fields">
                    <div class="field">
                        <label>Extension 文件路径</label>
                        <input id="pi-extension-path" value="${this._escAttr(cfg.extension_path || '')}" placeholder="extensions/agent-limiter.ts">
                        <small style="color:var(--color-text-muted)">Pi Agent 启动时通过 --extension 加载的扩展文件</small>
                    </div>
                    <div class="field-row">
                        <div class="field">
                            <label>单次最大工具调用数</label>
                            <input type="number" id="pi-extension-max-tool-calls" value="${cfg.extension_max_tool_calls != null ? cfg.extension_max_tool_calls : 3}" min="1" max="50">
                        </div>
                        <div class="field">
                            <label>拦截的高风险工具</label>
                            <input id="pi-extension-blocked-tools" value="${this._escAttr(cfg.extension_blocked_tools || 'bash,write,edit')}" placeholder="bash,write,edit">
                        </div>
                    </div>
                </div>
            </div>

            <!-- Skill 安装配置 -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>📦 Skill 安装</h4>
                </div>
                <div class="pi-agent-fields">
                    <div class="field">
                        <label>Skill 安装目录</label>
                        <input id="pi-skills-install-dir" value="${this._escAttr(cfg.skills_install_dir || 'skills')}" placeholder="skills">
                    </div>
                    <div class="field">
                        <label>Skill Registry URL</label>
                        <input id="pi-skills-registry-url" value="${this._escAttr(cfg.skills_registry_url || '')}" placeholder="https://registry.example.com/skills">
                        <small style="color:var(--color-text-muted)">后续用于从 Skill Registry 拉取和安装新 Skill</small>
                    </div>
                    <div class="field">
                        <label>已安装 Skills (JSON)</label>
                        <textarea id="pi-skills-installed-list" rows="3" placeholder='["rag_search", "doc_analysis"]'>${this._esc(cfg.skills_installed_list || '')}</textarea>
                    </div>
                </div>
            </div>

            <!-- System Prompt -->
            <div class="pi-agent-section">
                <div class="pi-agent-section-head">
                    <h4>📝 System Prompt</h4>
                </div>
                <div class="pi-agent-fields">
                    <div class="field">
                        <label>Agent 系统提示词</label>
                        <textarea id="pi-system-prompt" rows="6" placeholder="定义 Agent 的角色、职责和限制...">${this._esc(cfg.system_prompt || '')}</textarea>
                        <small style="color:var(--color-text-muted)">Pi Agent 启动时通过 --system-prompt 注入，约束 Agent 行为和权限边界</small>
                    </div>
                </div>
            </div>
        </div>`;
    },

    _bindPiAgentEvents(cfg) {
        // 敏感输入切换
        this._bindSensitiveInputToggle('pi-llm-api-key');
        this._bindSensitiveInputToggle('pi-search-api-key');
        this._bindSensitiveInputToggle('pi-vision-api-key');

        // Search 启用/禁用切换
        const searchToggle = document.getElementById('pi-search-enabled');
        const searchFields = document.getElementById('pi-search-fields');
        if (searchToggle && searchFields) {
            searchToggle.addEventListener('change', () => {
                searchFields.style.display = searchToggle.checked ? '' : 'none';
            });
        }

        // Vision 启用/禁用切换
        const visionToggle = document.getElementById('pi-vision-enabled');
        const visionFields = document.getElementById('pi-vision-fields');
        if (visionToggle && visionFields) {
            visionToggle.addEventListener('change', () => {
                visionFields.style.display = visionToggle.checked ? '' : 'none';
            });
        }

        // LLM 连接测试
        const testBtn = document.getElementById('pi-llm-test-btn');
        const feedback = document.getElementById('pi-llm-test-feedback');
        if (testBtn) {
            testBtn.addEventListener('click', async () => {
                testBtn.disabled = true;
                feedback.textContent = '测试中...';
                feedback.style.color = 'var(--blue-6)';
                try {
                    const result = await API.testPiAgentConnection();
                    if (result.status === 'ok') {
                        feedback.textContent = '连接成功 ✓';
                        feedback.style.color = 'var(--green-6)';
                    } else {
                        feedback.textContent = '连接失败: ' + (result.detail || '');
                        feedback.style.color = 'var(--red-6)';
                    }
                } catch (e) {
                    feedback.textContent = '测试失败: ' + e.message;
                    feedback.style.color = 'var(--red-6)';
                }
                testBtn.disabled = false;
            });
        }

        // LLM 测速
        const speedBtn = document.getElementById('pi-llm-speed-btn');
        if (speedBtn) {
            speedBtn.addEventListener('click', async () => {
                speedBtn.disabled = true;
                feedback.textContent = '测速中...';
                feedback.style.color = 'var(--blue-6)';
                try {
                    const result = await API.speedTestPiAgent();
                    if (result.status === 'ok') {
                        feedback.textContent = `延迟 ${result.latency_ms}ms ✓`;
                        feedback.style.color = 'var(--green-6)';
                    } else {
                        feedback.textContent = '测速失败: ' + (result.detail || '');
                        feedback.style.color = 'var(--red-6)';
                    }
                } catch (e) {
                    feedback.textContent = '测速失败: ' + e.message;
                    feedback.style.color = 'var(--red-6)';
                }
                speedBtn.disabled = false;
            });
        }

        // 保存按钮
        const saveBtn = document.getElementById('pi-agent-save-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.savePiAgentConfig());
        }
    },

    async savePiAgentConfig() {
        const saveBtn = document.getElementById('pi-agent-save-btn');
        try {
            if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '保存中...'; }

            // 收集配置数据
            const data = {
                enabled: document.getElementById('pi-enabled')?.checked || false,
                // LLM
                llm_provider: document.getElementById('pi-llm-provider')?.value,
                llm_api_base: document.getElementById('pi-llm-api-base')?.value.trim(),
                llm_model: document.getElementById('pi-llm-model')?.value.trim(),
                llm_max_tokens: parseInt(document.getElementById('pi-llm-max-tokens')?.value || '4096'),
                llm_temperature: parseFloat(document.getElementById('pi-llm-temperature')?.value || '0.7'),
                // Search
                search_enabled: document.getElementById('pi-search-enabled')?.checked || false,
                search_provider: document.getElementById('pi-search-provider')?.value,
                search_api_base: document.getElementById('pi-search-api-base')?.value.trim() || null,
                search_max_results: parseInt(document.getElementById('pi-search-max-results')?.value || '5'),
                // Vision
                vision_enabled: document.getElementById('pi-vision-enabled')?.checked || false,
                vision_provider: document.getElementById('pi-vision-provider')?.value,
                vision_api_base: document.getElementById('pi-vision-api-base')?.value.trim() || null,
                vision_model: document.getElementById('pi-vision-model')?.value.trim() || null,
                // Extension
                extension_path: document.getElementById('pi-extension-path')?.value.trim() || null,
                extension_max_tool_calls: parseInt(document.getElementById('pi-extension-max-tool-calls')?.value || '3'),
                extension_blocked_tools: document.getElementById('pi-extension-blocked-tools')?.value.trim(),
                // Skills
                skills_install_dir: document.getElementById('pi-skills-install-dir')?.value.trim() || 'skills',
                skills_registry_url: document.getElementById('pi-skills-registry-url')?.value.trim() || null,
                skills_installed_list: document.getElementById('pi-skills-installed-list')?.value.trim() || null,
                // System Prompt
                system_prompt: document.getElementById('pi-system-prompt')?.value || null,
            };

            // 更新主配置
            await API.updatePiAgentConfig(data);

            // 单独更新 API Keys（如果有输入新值）
            const llmKey = document.getElementById('pi-llm-api-key')?.value;
            if (llmKey) await API.updatePiAgentLlmApiKey(llmKey);

            const searchKey = document.getElementById('pi-search-api-key')?.value;
            if (searchKey) await API.updatePiAgentSearchApiKey(searchKey);

            const visionKey = document.getElementById('pi-vision-api-key')?.value;
            if (visionKey) await API.updatePiAgentVisionApiKey(visionKey);

            // 刷新配置
            await this.loadPiAgentConfig();
            if (saveBtn) { saveBtn.textContent = '已保存 ✓'; saveBtn.style.background = 'var(--green-6)'; }
            setTimeout(() => {
                if (saveBtn) { saveBtn.textContent = '保存配置'; saveBtn.style.background = ''; saveBtn.disabled = false; }
            }, 2000);
        } catch (e) {
            alert('保存失败: ' + e.message);
            if (saveBtn) { saveBtn.textContent = '保存配置'; saveBtn.disabled = false; }
        }
    },

    /* ── Agent 设置 (P3.A.4) ── */
    async loadAgentSettings() {
        const area = document.getElementById('agent-settings-area');
        if (!area) return;
        area.innerHTML = '<p style="color:var(--color-text-muted)">加载中…</p>';
        try {
            const [profile, auths, runs, approvals] = await Promise.all([
                API.getAgentProfile(),
                API.listAgentAuthorizations(),
                API.listAgentRuns(),
                API.listPendingApprovals(),
            ]);
            const tools = profile.allowed_tools || [];
            const toolOptions = ['search', 'rag', 'skill_runner', 'artifact'];
            const toolLabels = { search: '知识检索', rag: 'RAG 检索', skill_runner: 'Skill 运行', artifact: '产物生成' };

            area.innerHTML = `
                <div class="pi-agent-sections">
                    <!-- Agent Profile -->
                    <div class="pi-agent-section">
                        <div class="pi-agent-section-head">
                            <h3>个人 Agent 配置</h3>
                            <span class="pi-agent-status-badge ${profile.status === 'active' ? 'badge-ok' : 'badge-warn'}">${profile.status === 'active' ? '已启用' : '已禁用'}</span>
                        </div>
                        <p style="color:var(--color-text-muted);margin:0 0 var(--sp-3)">配置你的个人 AI Agent，控制它可使用的工具和行为策略。</p>
                        <div class="pi-agent-fields">
                            <div class="pi-field">
                                <label>Agent 名称</label>
                                <input type="text" id="agent-name" value="${this._escAttr(profile.name)}" placeholder="My Agent">
                            </div>
                            <div class="pi-field">
                                <label>System Policy（Agent 行为策略）</label>
                                <textarea id="agent-system-policy" rows="3" placeholder="你是一个帮助用户完成需求评审的 Agent…">${this._esc(profile.system_policy || '')}</textarea>
                            </div>
                            <div class="pi-field">
                                <label>允许使用的工具</label>
                                <div style="display:flex;gap:var(--sp-3);flex-wrap:wrap;margin-top:var(--sp-2)">
                                    ${toolOptions.map(t => `
                                        <label style="display:flex;align-items:center;gap:var(--sp-1);cursor:pointer">
                                            <input type="checkbox" id="agent-tool-${t}" ${tools.includes(t) ? 'checked' : ''}>
                                            <span>${toolLabels[t] || t}</span>
                                        </label>
                                    `).join('')}
                                </div>
                            </div>
                            <div class="pi-field">
                                <label>状态</label>
                                <select id="agent-status">
                                    <option value="active" ${profile.status === 'active' ? 'selected' : ''}>启用</option>
                                    <option value="disabled" ${profile.status === 'disabled' ? 'selected' : ''}>禁用</option>
                                </select>
                            </div>
                            <button id="agent-save-btn" class="btn-primary" onclick="Admin._saveAgentProfile()" style="margin-top:var(--sp-3)">保存配置</button>
                        </div>
                    </div>

                    <!-- Authorizations -->
                    <div class="pi-agent-section">
                        <div class="pi-agent-section-head">
                            <h3>授权范围</h3>
                            <span class="pi-agent-status-badge">${auths.length} 条授权</span>
                        </div>
                        <p style="color:var(--color-text-muted);margin:0 0 var(--sp-3)">管理你的 Agent 在团队空间、项目和个人范围内的权限。</p>
                        ${auths.length > 0 ? `
                            <table class="admin-table" style="margin-bottom:var(--sp-3)">
                                <thead><tr><th>范围类型</th><th>范围 ID</th><th>权限</th><th>操作</th></tr></thead>
                                <tbody>
                                    ${auths.map(a => `
                                        <tr>
                                            <td>${a.scope_type}</td>
                                            <td>${a.scope_id ?? '-'}</td>
                                            <td>${(a.permissions || []).join(', ') || '-'}</td>
                                            <td><button class="btn-sm btn-danger" onclick="Admin._revokeAgentAuth(${a.id})">撤销</button></td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        ` : '<p style="color:var(--color-text-muted)">暂无授权条目。</p>'}
                        <div style="display:flex;gap:var(--sp-2);align-items:end;flex-wrap:wrap">
                            <div class="pi-field" style="flex:1;min-width:120px">
                                <label>范围类型</label>
                                <select id="auth-scope-type">
                                    <option value="personal">personal</option>
                                    <option value="workspace">workspace</option>
                                    <option value="project">project</option>
                                </select>
                            </div>
                            <div class="pi-field" style="flex:1;min-width:120px">
                                <label>范围 ID</label>
                                <input type="number" id="auth-scope-id" placeholder="可选">
                            </div>
                            <button class="btn-primary" onclick="Admin._addAgentAuth()" style="height:36px">添加授权</button>
                        </div>
                    </div>

                    <!-- Recent Runs -->
                    <div class="pi-agent-section">
                        <div class="pi-agent-section-head">
                            <h3>最近运行</h3>
                            <span class="pi-agent-status-badge">${runs.length} 条记录</span>
                        </div>
                        ${runs.length > 0 ? `
                            <table class="admin-table">
                                <thead><tr><th>ID</th><th>目标</th><th>状态</th><th>步骤</th><th>工具调用</th><th>创建时间</th></tr></thead>
                                <tbody>
                                    ${runs.slice(0, 20).map(r => `
                                        <tr>
                                            <td>${r.id}</td>
                                            <td title="${this._escAttr(r.goal)}">${r.goal.length > 40 ? r.goal.slice(0, 40) + '…' : r.goal}</td>
                                            <td><span class="pi-agent-status-badge ${r.status === 'completed' ? 'badge-ok' : r.status === 'failed' ? 'badge-warn' : ''}">${r.status}</span></td>
                                            <td>${r.total_steps}</td>
                                            <td>${r.total_tool_calls}</td>
                                            <td>${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '-'}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        ` : '<p style="color:var(--color-text-muted)">暂无运行记录。</p>'}
                    </div>

                    <!-- Pending Approvals -->
                    <div class="pi-agent-section">
                        <div class="pi-agent-section-head">
                            <h3>待审批请求</h3>
                            <span class="pi-agent-status-badge ${approvals.length > 0 ? 'badge-warn' : 'badge-ok'}">${approvals.length} 条待处理</span>
                        </div>
                        ${approvals.length > 0 ? `
                            <table class="admin-table">
                                <thead><tr><th>ID</th><th>运行 ID</th><th>操作类型</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
                                <tbody>
                                    ${approvals.map(a => `
                                        <tr>
                                            <td>${a.id}</td>
                                            <td>${a.run_id}</td>
                                            <td>${a.action_type}</td>
                                            <td>${a.status}</td>
                                            <td>${a.created_at ? new Date(a.created_at).toLocaleString('zh-CN') : '-'}</td>
                                            <td>
                                                <button class="btn-sm btn-primary" onclick="Admin._decideApproval(${a.id}, 'approved')">批准</button>
                                                <button class="btn-sm btn-danger" onclick="Admin._decideApproval(${a.id}, 'rejected')">拒绝</button>
                                            </td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        ` : '<p style="color:var(--color-text-muted)">暂无待审批请求。</p>'}
                    </div>
                </div>
            `;
        } catch (e) {
            area.innerHTML = `<p style="color:red">加载失败: ${e.message}</p>`;
        }
    },

    async _saveAgentProfile() {
        const btn = document.getElementById('agent-save-btn');
        try {
            if (btn) { btn.textContent = '保存中…'; btn.disabled = true; }
            const toolOptions = ['search', 'rag', 'skill_runner', 'artifact'];
            const allowedTools = toolOptions.filter(t => document.getElementById(`agent-tool-${t}`)?.checked);
            await API.updateAgentProfile({
                name: document.getElementById('agent-name')?.value || 'My Agent',
                system_policy: document.getElementById('agent-system-policy')?.value || null,
                allowed_tools: allowedTools,
                status: document.getElementById('agent-status')?.value || 'active',
            });
            if (btn) { btn.textContent = '已保存 ✓'; btn.style.background = 'var(--green-6)'; }
            setTimeout(() => {
                if (btn) { btn.textContent = '保存配置'; btn.style.background = ''; btn.disabled = false; }
            }, 2000);
        } catch (e) {
            alert('保存失败: ' + e.message);
            if (btn) { btn.textContent = '保存配置'; btn.disabled = false; }
        }
    },

    async _revokeAgentAuth(authId) {
        if (!confirm('确认撤销此授权？')) return;
        try {
            await API.revokeAgentAuthorization(authId);
            await this.loadAgentSettings();
        } catch (e) {
            alert('撤销失败: ' + e.message);
        }
    },

    async _addAgentAuth() {
        try {
            const scopeType = document.getElementById('auth-scope-type')?.value || 'personal';
            const scopeId = document.getElementById('auth-scope-id')?.value;
            await API.createAgentAuthorization({
                scope_type: scopeType,
                scope_id: scopeId ? parseInt(scopeId) : null,
                permissions: ['read', 'write', 'search', 'execute'],
            });
            await this.loadAgentSettings();
        } catch (e) {
            alert('添加失败: ' + e.message);
        }
    },

    async _decideApproval(reqId, decision) {
        const comment = decision === 'rejected' ? prompt('拒绝原因（可选）:') : null;
        try {
            await API.decideApproval(reqId, { decision, comment });
            await this.loadAgentSettings();
        } catch (e) {
            alert('操作失败: ' + e.message);
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
