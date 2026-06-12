/* 团队空间页面 — P0.B.5 + P0.B.6 + P0.C.4 + P1.A.3 + P5.A.1 个人资料 */
const Workspace = {
    _initialized: false,
    _currentTab: 'sources',
    _sourceScope: 'team', // P5.A.1: 'team' or 'personal'
    _workspaceId: null,
    _sourcesCache: [],
    _selectedSourceId: null,
    _uploading: false,
    _memberRole: null,
    _canManage: false,

    init() {
        if (this._initialized) return;
        this._initialized = true;
        this._bindTabs();
        this._bindUpload();
        this._bindSourceScopeToggle();
    },

    destroy() {
        this._initialized = false;
        this._workspaceId = null;
        this._sourcesCache = [];
        this._selectedSourceId = null;
        this._memberRole = null;
        this._canManage = false;
    },

    async load() {
        await this._loadMembers();
        this._loadSources();
    },

    _bindTabs() {
        document.querySelectorAll('.workspace-nav-item').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.wsTab;
                this._switchTab(tab);
            });
        });
    },

    _bindUpload() {
        const uploadBtn = document.getElementById('ws-upload-btn');
        if (!uploadBtn) return;

        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.multiple = true;
        fileInput.accept = '.docx,.pdf,.md,.txt,.markdown';
        fileInput.style.display = 'none';
        document.body.appendChild(fileInput);

        uploadBtn.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', async () => {
            const files = fileInput.files;
            if (!files || files.length === 0) return;
            await this._handleUpload(files);
            fileInput.value = '';
        });
    },

    _switchTab(tab) {
        this._currentTab = tab;
        document.querySelectorAll('.workspace-nav-item').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.wsTab === tab);
        });
        document.querySelectorAll('.workspace-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === `ws-tab-${tab}`);
        });
        if (tab === 'sources') this._loadSources();
        if (tab === 'members') this._loadMembers();
    },

    _bindSourceScopeToggle() {
        /* P5.A.1: 团队资料/我的资料 切换按钮 */
        document.addEventListener('click', (e) => {
            const scopeBtn = e.target.closest('[data-source-scope]');
            if (scopeBtn) {
                const scope = scopeBtn.dataset.sourceScope;
                if (scope === this._sourceScope) return;
                this._sourceScope = scope;
                // 更新按钮状态
                document.querySelectorAll('[data-source-scope]').forEach(b => {
                    b.classList.toggle('active', b.dataset.sourceScope === scope);
                });
                // 更新上传按钮文案
                const uploadBtn = document.getElementById('ws-upload-btn');
                if (uploadBtn) {
                    uploadBtn.textContent = scope === 'personal' ? '+ 上传个人资料' : '+ 上传资料';
                }
                this._hideSourceDetail();
                this._loadSources();
            }
        });
    },

    async _getDefaultWorkspace() {
        if (this._workspaceId) return this._workspaceId;
        try {
            const ws = await API.getDefaultWorkspace();
            if (ws) {
                this._workspaceId = ws.id;
                return this._workspaceId;
            }
        } catch (err) {
            console.error('获取默认团队空间失败:', err);
        }
        return null;
    },

    async _loadSources() {
        const listEl = document.getElementById('ws-sources-list');
        if (!listEl) return;
        try {
            if (this._sourceScope === 'personal') {
                // P5.A.1: 加载个人私有资料
                const sources = await API.getPersonalSources();
                this._sourcesCache = sources || [];
                if (this._sourcesCache.length === 0) {
                    listEl.innerHTML = this._renderEmpty('还没有个人资料', '上传 DOCX/PDF/Markdown 文件作为您的私有知识库，仅您个人可访问');
                    return;
                }
                listEl.innerHTML = this._renderSourceTable();
            } else {
                // 团队资料
                const wsId = await this._getDefaultWorkspace();
                if (!wsId) {
                    listEl.innerHTML = this._renderEmpty('团队空间尚未初始化', '请联系管理员创建团队空间');
                    return;
                }
                const sources = await API.getWorkspaceSources(wsId);
                this._sourcesCache = sources || [];
                if (this._sourcesCache.length === 0) {
                    listEl.innerHTML = this._renderEmpty('还没有共享资料', '上传 DOCX/PDF/Markdown 文件，团队成员均可查看和引用');
                    return;
                }
                listEl.innerHTML = this._renderSourceTable();
            }
        } catch (err) {
            console.error('加载资料失败:', err);
            listEl.innerHTML = this._renderEmpty('加载失败', err.message);
        }
    },

    async _loadMembers() {
        const listEl = document.getElementById('ws-members-list');
        if (!listEl) return;
        try {
            const wsId = await this._getDefaultWorkspace();
            if (!wsId) {
                listEl.innerHTML = '<p style="color:var(--color-text-muted);text-align:center;padding:40px">团队空间尚未初始化</p>';
                return;
            }
            const members = await API.getDefaultWorkspaceMembers();
            const me = Auth.getUser();
            const myMember = (members || []).find(m => m.user_id === me?.id);
            this._memberRole = myMember?.role || null;
            this._canManage = this._memberRole === 'owner' || this._memberRole === 'admin';
            if (!members || members.length === 0) {
                listEl.innerHTML = '<p style="color:var(--color-text-muted);text-align:center;padding:40px">暂无团队成员</p>';
                return;
            }
            listEl.innerHTML = this._renderMemberTable(members);
        } catch (err) {
            console.error('加载成员失败:', err);
            listEl.innerHTML = '<p style="color:var(--color-text-muted);text-align:center;padding:40px">加载失败</p>';
        }
    },

    _renderEmpty(title, desc) {
        return `<div class="ws-empty">
            <div class="ws-empty-icon">
                <svg width="64" height="64" viewBox="0 0 64 64" fill="none" aria-hidden="true">
                    <rect width="64" height="64" rx="16" fill="#E0EEFA"/>
                    <path d="M22 32h20M32 22v20" stroke="#5A9DD5" stroke-width="3" stroke-linecap="round"/>
                </svg>
            </div>
            <h2 class="ws-empty-title">${DOMPurify.sanitize(title)}</h2>
            <p class="ws-empty-desc">${DOMPurify.sanitize(desc)}</p>
        </div>`;
    },

    _renderSourceTable() {
        const typeIcons = { upload: '📄', lark_url: '🔗', api: '⚡' };
        const rows = this._sourcesCache.map(s => {
            const statusHtml = s.status === 'processing' ? ' <span class="ws-status-chip ws-status-processing">处理中</span>'
                : s.status === 'failed' ? ' <span class="ws-status-chip ws-status-failed">失败</span>'
                : s.status === 'archived' ? ' <span class="ws-status-chip ws-status-archived">已归档</span>'
                : '';
            const tags = (s.tags || []).map(t => `<span class="ws-tag-chip">${DOMPurify.sanitize(t)}</span>`).join('');
            const canManage = this._canManage;
            const canDelete = this._sourceScope === 'personal' || canManage;
            return `<tr data-source-id="${s.id}">
                <td>${typeIcons[s.source_type] || '📄'}</td>
                <td class="ws-source-title-cell" data-action="view-source" data-source-id="${s.id}" style="cursor:pointer;color:var(--color-brand)">${DOMPurify.sanitize(s.title)}</td>
                <td>${s.filename ? DOMPurify.sanitize(s.filename) : '-'}</td>
                <td>v${s.version}</td>
                <td>${tags}</td>
                <td>${statusHtml}</td>
                <td>
                    <button class="btn btn-ghost btn-sm ws-action-btn" data-action="view-source" data-source-id="${s.id}" title="查看详情">详情</button>
                    ${canDelete && s.status === 'active' ? `<button class="btn btn-ghost btn-sm ws-action-btn ws-delete-btn" data-action="delete-source" data-source-id="${s.id}" data-source-title="${DOMPurify.sanitize(s.title)}" title="删除资料">删除</button>` : ''}
                </td>
            </tr>`;
        }).join('');

        return `<div class="table-wrap"><table class="table ws-sources-table">
            <thead><tr>
                <th style="width:36px">类型</th>
                <th>标题</th>
                <th>文件名</th>
                <th style="width:60px">版本</th>
                <th>标签</th>
                <th style="width:70px">状态</th>
                <th style="width:120px">操作</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
    },

    _renderMemberTable(members) {
        const roleLabels = { owner: '负责人', admin: '管理员', member: '成员', viewer: '观察者' };
        const me = Auth.getUser();
        const rows = members.map(m => {
            const isSelf = m.user_id === me?.id;
            const statusLabel = m.status === 'active' ? '活跃' : '已停用';
            const statusClass = m.status === 'active' ? 'ws-status-active' : 'ws-status-inactive';

            let roleCell;
            if (isSelf || !this._canManage) {
                roleCell = `<span class="ws-member-role ws-role-${m.role}">${roleLabels[m.role] || m.role}</span>`;
            } else {
                const roles = ['owner', 'admin', 'member', 'viewer'];
                const currentRole = m.role;
                const options = roles.map(r =>
                    `<option value="${r}" ${currentRole === r ? 'selected' : ''}>${roleLabels[r]}</option>`
                ).join('');
                roleCell = `<select class="ws-role-select" data-user-id="${m.user_id}" data-current-role="${currentRole}" data-action="change-role">${options}</select>`;
            }

            let actionCell = '';
            if (this._canManage && !isSelf) {
                if (m.status === 'active') {
                    actionCell = `<button class="btn btn-ghost btn-sm ws-action-btn" data-action="deactivate-member" data-user-id="${m.user_id}" data-username="${DOMPurify.sanitize(m.username)}">停用</button>`;
                } else {
                    actionCell = `<button class="btn btn-ghost btn-sm ws-action-btn" data-action="reactivate-member" data-user-id="${m.user_id}" data-username="${DOMPurify.sanitize(m.username)}">恢复</button>`;
                }
            }

            return `<tr>
                <td>${DOMPurify.sanitize(m.username || '')}</td>
                <td>${roleCell}</td>
                <td><span class="ws-status-chip ${statusClass}">${statusLabel}</span></td>
                <td>${actionCell}</td>
            </tr>`;
        }).join('');

        return `<div class="table-wrap"><table class="table ws-members-table">
            <thead><tr>
                <th>用户名</th>
                <th>角色</th>
                <th>状态</th>
                <th style="width:80px">操作</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
    },

    async _changeMemberRole(userId, newRole, currentRole) {
        const roleLabels = { owner: '负责人', admin: '管理员', member: '成员', viewer: '观察者' };
        const isDowngrade = (currentRole === 'owner' && newRole !== 'owner');
        const isUpgrade = (currentRole === 'viewer' && newRole === 'owner') || (currentRole === 'member' && newRole === 'owner');

        if (isDowngrade) {
            const confirmed = await this._confirmRoleChange(userId, currentRole, newRole, roleLabels);
            if (!confirmed) {
                await this._loadMembers();
                return;
            }
        } else if (currentRole !== newRole) {
            const confirmed = await this._confirmMemberAction(
                await this._getMemberUsername(userId),
                `将角色从 ${roleLabels[currentRole]} 改为 ${roleLabels[newRole]}`
            );
            if (!confirmed) {
                await this._loadMembers();
                return;
            }
        }

        try {
            await API.updateDefaultWorkspaceMember(userId, { role: newRole });
            App._showToast('角色已更新');
            await this._loadMembers();
        } catch (err) {
            App._showToast('更新角色失败: ' + (err.message || '未知错误'));
            await this._loadMembers();
        }
    },

    async _getMemberUsername(userId) {
        try {
            const members = await API.getDefaultWorkspaceMembers();
            const m = members.find(m => m.user_id === userId);
            return m ? m.username : `用户#${userId}`;
        } catch { return `用户#${userId}`; }
    },

    _confirmRoleChange(userId, currentRole, newRole, roleLabels) {
        return new Promise(resolve => {
            const overlay = document.getElementById('modal-overlay');
            const content = document.getElementById('modal-content');
            if (!overlay || !content) { resolve(false); return; }

            content.innerHTML = `
                <div style="padding:24px">
                    <h3 style="margin:0 0 12px;font-size:var(--fs-16);font-weight:var(--fw-semibold);color:var(--red-6)">⚠️ 确认降级角色</h3>
                    <p style="margin:0 0 20px;color:var(--color-text-muted)">将用户角色从「${roleLabels[currentRole]}」降级为「${roleLabels[newRole]}」。<br>降级后该用户将失去团队管理权限，此操作需要再次确认。</p>
                    <div style="display:flex;gap:8px;justify-content:flex-end">
                        <button id="ws-role-cancel" class="btn btn-ghost">取消</button>
                        <button id="ws-role-confirm" class="btn btn-primary" style="background:var(--red-6)">确认降级</button>
                    </div>
                </div>`;
            overlay.style.display = 'flex';

            const cleanup = () => { overlay.style.display = 'none'; };
            document.getElementById('ws-role-cancel').onclick = () => { cleanup(); resolve(false); };
            document.getElementById('ws-role-confirm').onclick = () => { cleanup(); resolve(true); };
            overlay.onclick = (e) => { if (e.target === overlay) { cleanup(); resolve(false); } };
        });
    },

    async _toggleMemberStatus(userId, username, currentStatus) {
        const newStatus = currentStatus === 'active' ? 'inactive' : 'active';
        const action = newStatus === 'inactive' ? '停用' : '恢复';
        const confirmed = await this._confirmMemberAction(username, action);
        if (!confirmed) return;

        try {
            await API.updateDefaultWorkspaceMember(userId, { status: newStatus });
            App._showToast(`已${action}用户 ${username}`);
            await this._loadMembers();
        } catch (err) {
            App._showToast(`${action}失败: ` + (err.message || '未知错误'));
        }
    },

    _confirmMemberAction(username, action) {
        return new Promise(resolve => {
            const overlay = document.getElementById('modal-overlay');
            const content = document.getElementById('modal-content');
            if (!overlay || !content) { resolve(false); return; }

            content.innerHTML = `
                <div style="padding:24px">
                    <h3 style="margin:0 0 12px;font-size:var(--fs-16);font-weight:var(--fw-semibold)">确认${action}</h3>
                    <p style="margin:0 0 20px;color:var(--color-text-muted)">确定要${action}用户「${DOMPurify.sanitize(username)}」吗？${action === '停用' ? '停用后该用户将无法访问团队空间和创建项目。' : '恢复后该用户将重新获得团队空间访问权限。'}</p>
                    <div style="display:flex;gap:8px;justify-content:flex-end">
                        <button id="ws-member-cancel" class="btn btn-ghost">取消</button>
                        <button id="ws-member-confirm" class="btn btn-primary">${action}</button>
                    </div>
                </div>`;
            overlay.style.display = 'flex';

            const cleanup = () => { overlay.style.display = 'none'; };
            document.getElementById('ws-member-cancel').onclick = () => { cleanup(); resolve(false); };
            document.getElementById('ws-member-confirm').onclick = () => { cleanup(); resolve(true); };
            overlay.onclick = (e) => { if (e.target === overlay) { cleanup(); resolve(false); } };
        });
    },

    async _handleUpload(files) {
        if (this._uploading) return;
        this._uploading = true;
        const uploadBtn = document.getElementById('ws-upload-btn');
        if (uploadBtn) uploadBtn.textContent = '上传中…';

        let successCount = 0;
        let failCount = 0;

        if (this._sourceScope === 'personal') {
            // P5.A.1: 上传个人资料
            for (const file of files) {
                try {
                    const formData = new FormData();
                    formData.append('file', file);
                    await API.uploadPersonalSource(formData);
                    successCount++;
                } catch (err) {
                    console.error('上传个人资料失败:', file.name, err);
                    failCount++;
                }
            }
        } else {
            // 团队资料
            const wsId = await this._getDefaultWorkspace();
            if (!wsId) {
                App._showToast('团队空间未初始化');
                this._uploading = false;
                if (uploadBtn) uploadBtn.textContent = '+ 上传资料';
                return;
            }
            for (const file of files) {
                try {
                    const formData = new FormData();
                    formData.append('file', file);
                    await API.uploadWorkspaceSource(wsId, formData);
                    successCount++;
                } catch (err) {
                    console.error('上传失败:', file.name, err);
                    failCount++;
                }
            }
        }

        this._uploading = false;
        if (uploadBtn) uploadBtn.textContent = this._sourceScope === 'personal' ? '+ 上传个人资料' : '+ 上传资料';

        if (successCount > 0) {
            App._showToast(`成功上传 ${successCount} 个文件${failCount > 0 ? `，${failCount} 个失败` : ''}`);
            await this._loadSources();
        } else {
            App._showToast('所有文件上传失败');
        }
    },

    async _deleteSource(sourceId, sourceTitle) {
        const confirmed = await this._confirmDelete(sourceTitle);
        if (!confirmed) return;

        try {
            if (this._sourceScope === 'personal') {
                // P5.A.1: 删除个人资料
                await API.deletePersonalSource(sourceId);
            } else {
                const wsId = await this._getDefaultWorkspace();
                if (!wsId) return;
                await API.deleteWorkspaceSource(wsId, sourceId);
            }
            App._showToast('资料已删除');
            await this._loadSources();
            if (this._selectedSourceId === sourceId) {
                this._selectedSourceId = null;
                this._hideSourceDetail();
            }
        } catch (err) {
            App._showToast('删除失败: ' + (err.message || '未知错误'));
        }
    },

    _confirmDelete(title) {
        return new Promise(resolve => {
            const overlay = document.getElementById('modal-overlay');
            const content = document.getElementById('modal-content');
            if (!overlay || !content) { resolve(false); return; }

            content.innerHTML = `
                <div style="padding:24px">
                    <h3 style="margin:0 0 12px;font-size:var(--fs-16);font-weight:var(--fw-semibold)">确认删除</h3>
                    <p style="margin:0 0 20px;color:var(--color-text-muted)">确定要删除资料「${DOMPurify.sanitize(title)}」吗？删除后历史引用不受影响，但列表中不再显示。</p>
                    <div style="display:flex;gap:8px;justify-content:flex-end">
                        <button id="ws-delete-cancel" class="btn btn-ghost">取消</button>
                        <button id="ws-delete-confirm" class="btn btn-primary" style="background:var(--red-6)">删除</button>
                    </div>
                </div>`;
            overlay.style.display = 'flex';

            const cancelBtn = document.getElementById('ws-delete-cancel');
            const confirmBtn = document.getElementById('ws-delete-confirm');

            const cleanup = () => { overlay.style.display = 'none'; };

            cancelBtn.onclick = () => { cleanup(); resolve(false); };
            confirmBtn.onclick = () => { cleanup(); resolve(true); };
            overlay.onclick = (e) => { if (e.target === overlay) { cleanup(); resolve(false); } };
        });
    },

    async _showSourceDetail(sourceId) {
        this._selectedSourceId = sourceId;

        const detailEl = document.getElementById('ws-source-detail');
        const listEl = document.getElementById('ws-sources-list');
        if (!detailEl || !listEl) return;

        detailEl.innerHTML = '<p style="text-align:center;color:var(--color-text-muted);padding:24px">加载中…</p>';
        detailEl.style.display = 'block';
        listEl.style.display = 'none';

        let source;
        try {
            if (this._sourceScope === 'personal') {
                source = await API.getPersonalSourceDetail(sourceId);
            } else {
                const wsId = await this._getDefaultWorkspace();
                source = await API.getWorkspaceSourceDetail(wsId, sourceId);
            }
        } catch (err) {
            detailEl.innerHTML = `<p style="color:var(--red-6);padding:24px">加载失败: ${err.message}</p>`;
            return;
        }

        const tags = (source.tags || []).join(', ') || '无';
        const typeLabels = { upload: '文件上传', lark_url: '飞书链接', api: 'API 导入' };
        const canManage = this._canManage;

        let refsHtml = '';
        if (source.project_refs && source.project_refs.length > 0) {
            refsHtml = `<div style="margin-top:16px"><h4 style="font-size:var(--fs-14);font-weight:var(--fw-medium);margin-bottom:8px">引用此资料的项目</h4><ul style="margin:0;padding-left:20px">${source.project_refs.map(r => `<li>项目 #${r.project_id}（${r.ref_type}）</li>`).join('')}</ul></div>`;
        }

        let textHtml = '';
        if (source.extracted_text) {
            const preview = source.extracted_text.length > 500 ? source.extracted_text.slice(0, 500) + '…' : source.extracted_text;
            textHtml = `<div style="margin-top:16px"><h4 style="font-size:var(--fs-14);font-weight:var(--fw-medium);margin-bottom:8px">正文预览</h4><pre style="background:var(--gray-1);padding:12px;border-radius:var(--radius-sm);font-size:var(--fs-13);max-height:200px;overflow-y:auto;white-space:pre-wrap">${DOMPurify.sanitize(preview)}</pre></div>`;
        }

        detailEl.innerHTML = `
            <div class="panel-head" style="flex-wrap:wrap;gap:8px">
                <div>
                    <h3 class="panel-title">${DOMPurify.sanitize(source.title)}</h3>
                    <p style="margin:4px 0 0;font-size:var(--fs-12);color:var(--color-text-muted)">v${source.version} · ${typeLabels[source.source_type] || source.source_type} · ${source.created_at ? new Date(source.created_at).toLocaleDateString('zh-CN') : ''}</p>
                </div>
                <div style="display:flex;gap:8px">
                    ${source.file_id ? `<button class="btn btn-outline btn-sm" data-action="download-source" data-source-id="${source.id}" data-source-scope="${this._sourceScope}">下载原文件</button>` : ''}
                    ${(this._sourceScope === 'personal' || canManage) && source.status === 'active' ? `<button class="btn btn-ghost btn-sm ws-action-btn ws-delete-btn" data-action="delete-source" data-source-id="${source.id}" data-source-title="${DOMPurify.sanitize(source.title)}">删除</button>` : ''}
                    <button class="btn btn-ghost btn-sm" id="ws-detail-close">返回列表</button>
                </div>
            </div>
            <div style="margin-top:12px">
                <div style="display:grid;grid-template-columns:120px 1fr;gap:8px 16px;font-size:var(--fs-14)">
                    <span style="color:var(--color-text-muted)">文件名</span><span>${source.filename ? DOMPurify.sanitize(source.filename) : '-'}</span>
                    <span style="color:var(--color-text-muted)">内容哈希</span><span style="font-family:monospace;font-size:var(--fs-12)">${source.content_hash || '-'}</span>
                    <span style="color:var(--color-text-muted)">标签</span><span>${tags}</span>
                    <span style="color:var(--color-text-muted)">状态</span><span>${source.status}</span>
                </div>
            </div>
            ${textHtml}
            ${refsHtml}`;

        document.getElementById('ws-detail-close')?.addEventListener('click', () => {
            this._hideSourceDetail();
        });
        detailEl.querySelector('[data-action="download-source"]')?.addEventListener('click', () => {
            this._downloadSource(source.id);
        });
    },

    async _downloadSource(sourceId) {
        try {
            let blob, filename;
            if (this._sourceScope === 'personal') {
                const result = await API.downloadPersonalSource(sourceId);
                blob = result.blob;
                filename = result.filename;
            } else {
                const wsId = await this._getDefaultWorkspace();
                const result = await API.downloadWorkspaceSource(wsId, sourceId);
                blob = result.blob;
                filename = result.filename;
            }
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (err) {
            alert(`下载失败: ${err.message}`);
        }
    },

    _hideSourceDetail() {
        const detailEl = document.getElementById('ws-source-detail');
        const listEl = document.getElementById('ws-sources-list');
        if (detailEl) detailEl.style.display = 'none';
        if (listEl) listEl.style.display = '';
        this._selectedSourceId = null;
    },
};

document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action="delete-source"]');
    if (btn) {
        e.preventDefault();
        const sourceId = parseInt(btn.dataset.sourceId, 10);
        const sourceTitle = btn.dataset.sourceTitle || '此资料';
        Workspace._deleteSource(sourceId, sourceTitle);
        return;
    }

    const viewBtn = e.target.closest('[data-action="view-source"]');
    if (viewBtn) {
        e.preventDefault();
        const sourceId = parseInt(viewBtn.dataset.sourceId, 10);
        Workspace._showSourceDetail(sourceId);
        return;
    }

    const deactivateBtn = e.target.closest('[data-action="deactivate-member"]');
    if (deactivateBtn) {
        e.preventDefault();
        const userId = parseInt(deactivateBtn.dataset.userId, 10);
        const username = deactivateBtn.dataset.username;
        Workspace._toggleMemberStatus(userId, username, 'active');
        return;
    }

    const reactivateBtn = e.target.closest('[data-action="reactivate-member"]');
    if (reactivateBtn) {
        e.preventDefault();
        const userId = parseInt(reactivateBtn.dataset.userId, 10);
        const username = reactivateBtn.dataset.username;
        Workspace._toggleMemberStatus(userId, username, 'inactive');
        return;
    }
});

document.addEventListener('change', (e) => {
    const select = e.target.closest('[data-action="change-role"]');
    if (select) {
        const userId = parseInt(select.dataset.userId, 10);
        const newRole = select.value;
        Workspace._changeMemberRole(userId, newRole);
    }
});

window.Workspace = Workspace;
