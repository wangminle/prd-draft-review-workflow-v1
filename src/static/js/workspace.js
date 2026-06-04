/* 团队空间页面 — P0.B.5 + P0.B.6 + P0.C.4 */
const Workspace = {
    _initialized: false,
    _currentTab: 'sources',
    _workspaceId: null,
    _sourcesCache: [],
    _selectedSourceId: null,
    _uploading: false,
    _memberRole: null,

    init() {
        if (this._initialized) return;
        this._initialized = true;
        this._bindTabs();
        this._bindUpload();
    },

    destroy() {
        this._initialized = false;
        this._workspaceId = null;
        this._sourcesCache = [];
        this._selectedSourceId = null;
        this._memberRole = null;
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

    async _getDefaultWorkspace() {
        if (this._workspaceId) return this._workspaceId;
        try {
            const workspaces = await API.getWorkspaces();
            if (workspaces && workspaces.length > 0) {
                this._workspaceId = workspaces[0].id;
                return this._workspaceId;
            }
        } catch (err) {
            console.error('获取团队空间失败:', err);
        }
        return null;
    },

    async _loadSources() {
        const listEl = document.getElementById('ws-sources-list');
        if (!listEl) return;
        try {
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
            const members = await API.getWorkspaceMembers(wsId);
            const me = Auth.getUser();
            this._memberRole = (members || []).find(m => m.user_id === me?.id)?.role || null;
            if (!members || members.length === 0) {
                listEl.innerHTML = '<p style="color:var(--color-text-muted);text-align:center;padding:40px">暂无团队成员</p>';
                return;
            }
            listEl.innerHTML = members.map(m => this._renderMemberRow(m)).join('');
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
            const canManage = this._memberRole === 'owner' || this._memberRole === 'admin';
            return `<tr data-source-id="${s.id}">
                <td>${typeIcons[s.source_type] || '📄'}</td>
                <td class="ws-source-title-cell" data-action="view-source" data-source-id="${s.id}" style="cursor:pointer;color:var(--color-brand)">${DOMPurify.sanitize(s.title)}</td>
                <td>${s.filename ? DOMPurify.sanitize(s.filename) : '-'}</td>
                <td>v${s.version}</td>
                <td>${tags}</td>
                <td>${statusHtml}</td>
                <td>
                    <button class="btn btn-ghost btn-sm ws-action-btn" data-action="view-source" data-source-id="${s.id}" title="查看详情">详情</button>
                    ${canManage && s.status === 'active' ? `<button class="btn btn-ghost btn-sm ws-action-btn ws-delete-btn" data-action="delete-source" data-source-id="${s.id}" data-source-title="${DOMPurify.sanitize(s.title)}" title="删除资料">删除</button>` : ''}
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

    _renderMemberRow(member) {
        const roleLabels = { owner: '负责人', admin: '管理员', member: '成员', viewer: '观察者' };
        return `<div class="ws-member-row">
            <span class="ws-member-username">${DOMPurify.sanitize(member.username || '')}</span>
            <span class="ws-member-role ws-role-${member.role}">${roleLabels[member.role] || member.role}</span>
        </div>`;
    },

    async _handleUpload(files) {
        if (this._uploading) return;
        const wsId = await this._getDefaultWorkspace();
        if (!wsId) {
            App._showToast('团队空间未初始化');
            return;
        }
        this._uploading = true;
        const uploadBtn = document.getElementById('ws-upload-btn');
        if (uploadBtn) uploadBtn.textContent = '上传中…';

        let successCount = 0;
        let failCount = 0;

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

        this._uploading = false;
        if (uploadBtn) uploadBtn.textContent = '+ 上传资料';

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

        const wsId = await this._getDefaultWorkspace();
        if (!wsId) return;

        try {
            await API.deleteWorkspaceSource(wsId, sourceId);
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
            const wsId = await this._getDefaultWorkspace();
            source = await API.getWorkspaceSourceDetail(wsId, sourceId);
        } catch (err) {
            detailEl.innerHTML = `<p style="color:var(--red-6);padding:24px">加载失败: ${err.message}</p>`;
            return;
        }

        const tags = (source.tags || []).join(', ') || '无';
        const typeLabels = { upload: '文件上传', lark_url: '飞书链接', api: 'API 导入' };
        const canManage = this._memberRole === 'owner' || this._memberRole === 'admin';

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
                    ${source.file_id ? `<button class="btn btn-outline btn-sm" data-action="download-source" data-source-id="${source.id}">下载原文件</button>` : ''}
                    ${canManage && source.status === 'active' ? `<button class="btn btn-ghost btn-sm ws-action-btn ws-delete-btn" data-action="delete-source" data-source-id="${source.id}" data-source-title="${DOMPurify.sanitize(source.title)}">删除</button>` : ''}
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
            const wsId = await this._getDefaultWorkspace();
            const { blob, filename } = await API.downloadWorkspaceSource(wsId, sourceId);
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
});

window.Workspace = Workspace;
