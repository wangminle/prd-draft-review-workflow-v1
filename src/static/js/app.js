/* 应用入口 */
const App = {
    async init() {
        Branding.load();
        this._showLoading();
        this._bindAuthForms();
        this._bindNavigation();
        this._bindSidebarToggle();
        this._alignSidebarToDivider();

        const loggedIn = await Auth.init();
        if (loggedIn) {
            const lastPage = sessionStorage.getItem('lastPage') || 'review';
            Notification.init();
            this._navigateTo(lastPage);
        } else {
            this._showLoginPage();
        }
    },

    _showLoading() {
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const app = document.getElementById('app');
        let loader = document.getElementById('app-loader');
        if (!loader) {
            loader = document.createElement('div');
            loader.id = 'app-loader';
            loader.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100vh;width:100%;font-size:14px;color:var(--gray-6)';
            loader.textContent = '加载中…';
            app.appendChild(loader);
        }
    },

    _hideLoading() {
        const loader = document.getElementById('app-loader');
        if (loader) loader.remove();
    },

    /* ── 页面切换 ── */

    _navigateTo(page) {
        const map = { chat: '_showUserPage', admin: '_showAdminPage', review: '_showReviewPage', workspace: '_showWorkspacePage' };
        const method = map[page] || map.review;
        this[method]();
    },

    _showLoginPage() {
        this._hideLoading();
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('login-page').classList.add('active');
    },

    _showToast(message, duration = 3000) {
        let toast = document.getElementById('app-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'app-toast';
            toast.setAttribute('aria-live', 'polite');
            toast.setAttribute('role', 'status');
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.className = 'app-toast show';
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => {
            toast.className = 'app-toast';
        }, duration);
    },

    /* 个人 Agent：所有登录用户通过统一账号菜单管理自己的配置（不含管理后台侧栏） */
    async _showAgentSettingsModal() {
        const overlay = document.getElementById('modal-overlay');
        const content = document.getElementById('modal-content');
        if (!overlay || !content) return;

        const esc = (str) => {
            if (str == null) return '';
            const d = document.createElement('div');
            d.textContent = String(str);
            return d.innerHTML;
        };
        const escAttr = (str) => {
            if (str == null) return '';
            return String(str)
                .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        };

        content.classList.add('agent-settings-modal');
        content.innerHTML = '<p class="agent-settings-loading">加载中…</p>';
        overlay.style.display = 'flex';

        const cleanup = () => {
            overlay.style.display = 'none';
            content.classList.remove('agent-settings-modal');
            overlay.onclick = null;
        };

        try {
            const [profile, auths, workspaces, runsResult, approvalsResult] = await Promise.all([
                API.getAgentProfile(),
                // 授权与 workspace 决定可保存的默认范围，失败时必须进入错误态，
                // 不能伪装成空列表后把 workspace 静默覆盖为 personal。
                API.listAgentAuthorizations(),
                API.getWorkspaces(),
                API.listAgentRuns()
                    .then(data => ({ data, error: null }))
                    .catch(error => ({ data: [], error })),
                API.listPendingApprovals()
                    .then(data => ({ data, error: null }))
                    .catch(error => ({ data: [], error })),
            ]);
            const runs = runsResult.data || [];
            const approvals = approvalsResult.data || [];
            const name = profile?.name || 'My Agent';
            const status = profile?.status || 'active';
            const scopeType = profile?.default_scope_type || 'personal';
            const tools = profile?.allowed_tools || [];
            const toolOptions = ['search', 'rag_search', 'skill_runner', 'artifact'];
            const toolLabels = { search: '知识检索', rag_search: 'RAG 检索', skill_runner: 'Skill 运行', artifact: '产物生成' };

            const allAuths = auths || [];
            const wsAuths = allAuths.filter(a => a.scope_type === 'workspace' && a.scope_id != null);
            const hasWsAuth = wsAuths.length > 0;
            const effectiveScope = (scopeType === 'workspace' && hasWsAuth) ? 'workspace' : 'personal';
            const authorizedIds = new Set(wsAuths.map(a => a.scope_id));
            const addableWorkspaces = (workspaces || []).filter(w => !authorizedIds.has(w.id));

            const wsAuthListHtml = hasWsAuth
                ? `<ul class="agent-auth-list">${wsAuths.map(a => {
                    const label = esc(a.workspace_name || `空间 #${a.scope_id}`);
                    return `<li><span>${label}</span><button type="button" class="btn btn-ghost btn-xs" data-revoke-auth="${a.id}">撤销</button></li>`;
                }).join('')}</ul>`
                : '<p class="agent-settings-hint">暂无授权。选择「已授权的团队资料」前，请先在下方为具体团队空间添加授权；未授权时 Agent 无法检索该空间。</p>';

            const otherAuths = allAuths.filter(a => a.scope_type !== 'workspace');
            const otherAuthHtml = otherAuths.length
                ? `<p class="agent-settings-hint">其他授权：${otherAuths.map(a => `${esc(a.scope_type)} #${a.scope_id ?? '-'}`).join('、')}</p>`
                : '';

            const addAuthHtml = addableWorkspaces.length
                ? `<div class="agent-auth-add">
                        <label>添加团队空间授权
                            <select id="agent-auth-workspace">
                                ${addableWorkspaces.map(w => `<option value="${w.id}">${esc(w.name || `空间 #${w.id}`)}</option>`).join('')}
                            </select>
                        </label>
                        <button type="button" id="agent-auth-add" class="btn btn-primary btn-sm">添加授权</button>
                    </div>`
                : ((workspaces || []).length
                    ? '<p class="agent-settings-hint">你加入的团队空间均已授权。</p>'
                    : '<p class="agent-settings-hint">你还没有加入任何团队空间，无法添加团队资料授权。</p>');

            const runsHtml = runsResult.error
                ? `<p class="agent-settings-error">最近运行加载失败：${esc(runsResult.error.message || '未知错误')}</p>`
                : (runs || []).length
                ? `<table class="admin-table"><thead><tr><th>ID</th><th>目标</th><th>状态</th><th>步骤</th><th>工具</th></tr></thead><tbody>
                    ${(runs || []).slice(0, 10).map(r => `<tr>
                        <td>${r.id}</td>
                        <td title="${escAttr(r.goal || '')}">${esc((r.goal || '').length > 36 ? r.goal.slice(0, 36) + '…' : (r.goal || ''))}</td>
                        <td>${esc(r.status)}</td>
                        <td>${r.total_steps ?? '-'}</td>
                        <td>${r.total_tool_calls ?? '-'}</td>
                    </tr>`).join('')}</tbody></table>`
                : '<p class="agent-settings-hint">暂无运行记录。</p>';

            const approvalsHtml = approvalsResult.error
                ? `<p class="agent-settings-error">待审批请求加载失败：${esc(approvalsResult.error.message || '未知错误')}</p>`
                : (approvals || []).length
                ? `<table class="admin-table"><thead><tr><th>ID</th><th>运行</th><th>操作</th><th>状态</th><th></th></tr></thead><tbody>
                    ${(approvals || []).map(a => `<tr>
                        <td>${a.id}</td>
                        <td>${a.run_id}</td>
                        <td>${esc(a.action_type)}</td>
                        <td>${esc(a.status)}</td>
                        <td>
                            <button type="button" class="btn btn-primary btn-xs" data-decide-approval="${a.id}" data-decision="approved">批准</button>
                            <button type="button" class="btn btn-ghost btn-xs" data-decide-approval="${a.id}" data-decision="rejected">拒绝</button>
                        </td>
                    </tr>`).join('')}</tbody></table>`
                : '<p class="agent-settings-hint">暂无待审批请求。</p>';

            content.innerHTML = `
                <button type="button" class="modal-close-btn" id="agent-settings-x" aria-label="关闭弹窗">&times;</button>
                <h3>个人 Agent</h3>
                <p class="agent-settings-lead">仅影响当前账号。系统级引擎请由管理员在「Pi Agent 配置」中管理。</p>
                <div class="pi-agent-sections">
                    <section class="pi-agent-section">
                        <div class="pi-agent-section-head"><h4>基本配置</h4></div>
                        <div class="pi-agent-fields">
                            <div class="field">
                                <label for="agent-name-input">Agent 名称</label>
                                <input id="agent-name-input" type="text" value="${escAttr(name)}">
                            </div>
                            <div class="field">
                                <label for="agent-scope-select">默认访问范围</label>
                                <select id="agent-scope-select">
                                    <option value="personal" ${effectiveScope === 'personal' ? 'selected' : ''}>我的资料</option>
                                    <option value="workspace" ${!hasWsAuth ? 'disabled' : ''} ${effectiveScope === 'workspace' ? 'selected' : ''}>已授权的团队资料${hasWsAuth ? '' : '（暂无授权）'}</option>
                                </select>
                                <p class="agent-settings-hint">选择「已授权的团队资料」不等于自动获得全部团队资料；Agent 只能访问下方已显式授权的空间。</p>
                            </div>
                            <div id="agent-authorized-workspaces" class="agent-authorized-box">
                                <div class="agent-authorized-title">当前已授权团队空间${hasWsAuth ? `（${wsAuths.length} 个）` : ''}</div>
                                ${wsAuthListHtml}
                                ${otherAuthHtml}
                                ${addAuthHtml}
                            </div>
                            <div class="field">
                                <label for="agent-system-policy">System Policy（行为策略）</label>
                                <textarea id="agent-system-policy" rows="3">${esc(profile?.system_policy || '')}</textarea>
                            </div>
                            <div class="field">
                                <span>允许使用的工具</span>
                                <div class="agent-tool-row">
                                    ${toolOptions.map(t => `
                                        <label class="agent-tool-item">
                                            <input type="checkbox" id="agent-tool-${t}" ${tools.includes(t) ? 'checked' : ''}>
                                            <span>${toolLabels[t] || t}</span>
                                        </label>`).join('')}
                                </div>
                            </div>
                            <div class="field">
                                <label for="agent-status-select">状态</label>
                                <select id="agent-status-select">
                                    <option value="active" ${status === 'active' ? 'selected' : ''}>启用</option>
                                    <option value="disabled" ${status === 'disabled' ? 'selected' : ''}>禁用</option>
                                </select>
                            </div>
                        </div>
                    </section>
                    <section class="pi-agent-section">
                        <div class="pi-agent-section-head"><h4>最近运行</h4><span>${(runs || []).length} 条</span></div>
                        ${runsHtml}
                    </section>
                    <section class="pi-agent-section">
                        <div class="pi-agent-section-head"><h4>待审批请求</h4><span>${(approvals || []).length} 条</span></div>
                        ${approvalsHtml}
                    </section>
                </div>
                <div class="btn-row">
                    <button type="button" id="agent-settings-cancel" class="btn btn-ghost">关闭</button>
                    <button type="button" id="agent-settings-save" class="btn btn-primary">保存</button>
                </div>`;

            document.getElementById('agent-settings-cancel').onclick = cleanup;
            document.getElementById('agent-settings-x').onclick = cleanup;
            overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

            document.getElementById('agent-settings-save').onclick = async () => {
                const newName = document.getElementById('agent-name-input').value.trim();
                const newScope = document.getElementById('agent-scope-select').value;
                const newStatus = document.getElementById('agent-status-select').value;
                const preservedTools = tools.filter(t => !toolOptions.includes(t));
                const selectedTools = toolOptions.filter(
                    t => document.getElementById(`agent-tool-${t}`)?.checked
                );
                const allowedTools = [...preservedTools, ...selectedTools];
                try {
                    await API.updateAgentProfile({
                        name: newName,
                        default_scope_type: newScope,
                        status: newStatus,
                        // 空字符串表示用户明确清空策略；null/缺省才表示不更新。
                        system_policy: document.getElementById('agent-system-policy')?.value ?? '',
                        allowed_tools: allowedTools,
                    });
                    this._showToast('Agent 设置已保存');
                    cleanup();
                } catch (err) {
                    this._showToast('保存失败: ' + (err.message || '未知错误'));
                }
            };

            document.getElementById('agent-auth-add')?.addEventListener('click', async () => {
                const wsId = document.getElementById('agent-auth-workspace')?.value;
                if (!wsId) return;
                try {
                    await API.createAgentAuthorization({
                        scope_type: 'workspace',
                        scope_id: parseInt(wsId, 10),
                        permissions: ['read', 'write', 'search', 'execute'],
                    });
                    this._showToast('已添加团队空间授权');
                    await this._showAgentSettingsModal();
                } catch (err) {
                    this._showToast('添加失败: ' + (err.message || '未知错误'));
                }
            });

            content.querySelectorAll('[data-revoke-auth]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    if (!confirm('确认撤销此授权？')) return;
                    try {
                        await API.revokeAgentAuthorization(btn.dataset.revokeAuth);
                        this._showToast('已撤销授权');
                        await this._showAgentSettingsModal();
                    } catch (err) {
                        this._showToast('撤销失败: ' + (err.message || '未知错误'));
                    }
                });
            });

            content.querySelectorAll('[data-decide-approval]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    const decision = btn.dataset.decision;
                    const comment = decision === 'rejected' ? prompt('拒绝原因（可选）:') : null;
                    try {
                        await API.decideApproval(btn.dataset.decideApproval, { decision, comment });
                        this._showToast(decision === 'approved' ? '已批准' : '已拒绝');
                        await this._showAgentSettingsModal();
                    } catch (err) {
                        this._showToast('操作失败: ' + (err.message || '未知错误'));
                    }
                });
            });
        } catch (err) {
            content.innerHTML = `<p class="agent-settings-error">加载 Agent 设置失败: ${esc(err.message)}</p>
                <div class="btn-row"><button type="button" class="btn btn-ghost" id="agent-settings-fail-close">关闭</button></div>`;
            document.getElementById('agent-settings-fail-close')?.addEventListener('click', cleanup);
            overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };
        }
    },

    _resetSessionState() {
        if (window.Review && typeof Review.resetState === 'function') {
            Review.resetState();
        }
        if (window.Chat && typeof Chat.destroy === 'function') {
            Chat.destroy();
        }
    },

    _showUserPage() {
        this._hideLoading();
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('user-page').classList.add('active');
        sessionStorage.setItem('lastPage', 'chat');

        const user = Auth.getUser();
        document.getElementById('user-display').textContent = user?.username || '';
        document.getElementById('go-admin').style.display = Auth.isAdmin() ? '' : 'none';

        Chat.init();
        this._alignSidebarToDivider();
    },

    _showAdminPage() {
        this._hideLoading();
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('admin-page').classList.add('active');
        sessionStorage.setItem('lastPage', 'admin');

        const user = Auth.getUser();
        document.getElementById('admin-user-display').textContent = user?.username || '';

        Admin.init();
        this._alignSidebarToDivider();
    },

    _showReviewPage() {
        this._hideLoading();
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('review-page').classList.add('active');
        sessionStorage.setItem('lastPage', 'review');

        const user = Auth.getUser();
        document.getElementById('review-user-display').textContent = user?.username || '';
        const reviewAdminLink = document.getElementById('go-admin-from-review');
        if (reviewAdminLink) {
            reviewAdminLink.style.display = Auth.isAdmin() ? '' : 'none';
        }

        Review.init();
        this._alignSidebarToDivider();
    },

    _showWorkspacePage() {
        this._hideLoading();
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('workspace-page').classList.add('active');
        sessionStorage.setItem('lastPage', 'workspace');

        const user = Auth.getUser();
        document.getElementById('workspace-user-display').textContent = user?.username || '';
        const wsAdminLink = document.getElementById('go-admin-from-workspace');
        if (wsAdminLink) {
            wsAdminLink.style.display = Auth.isAdmin() ? '' : 'none';
        }

        Workspace.init();
        Workspace.load();
        this._alignSidebarToDivider();

        // P2.C.3: 如果有 pending source detail 跳转（从对话/审查引用链接来），自动打开详情
        if (this._pendingSourceDetail) {
            const { wsId, sourceId } = this._pendingSourceDetail;
            this._pendingSourceDetail = null;
            setTimeout(() => {
                if (typeof Workspace !== 'undefined' && Workspace._showSourceDetail) {
                    Workspace._showSourceDetail(parseInt(sourceId));
                }
            }, 500);
        }
    },

    /* ── 侧栏折叠 + 对齐竖线 ── */

    _alignSidebarToDivider() {
        requestAnimationFrame(() => {
            document.querySelectorAll('.page').forEach(page => {
                const dividers = page.querySelectorAll('.topbar-divider');
                if (dividers.length >= 2) {
                    const secondDivider = dividers[1];
                    const x = secondDivider.getBoundingClientRect().right;
                    const sidebar = page.querySelector('.sidebar, .review-sidebar, .admin-sidebar, .workspace-sidebar');
                    const isNarrowAdmin = sidebar?.classList.contains('admin-sidebar')
                        && window.matchMedia('(max-width: 1100px)').matches;
                    if (isNarrowAdmin) {
                        // 窄屏宽度由媒体查询控制，避免内联宽度覆盖图标栏样式。
                        sidebar.style.width = '';
                    } else if (sidebar && !sidebar.classList.contains('collapsed')) {
                        sidebar.style.width = x + 'px';
                    }
                }
            });
        });
    },

    _bindSidebarToggle() {
        document.querySelectorAll('.sidebar-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const sidebar = btn.closest('aside');

                if (sidebar.classList.contains('collapsed')) {
                    sidebar.classList.remove('collapsed');
                    setTimeout(() => this._alignSidebarToDivider(), 300);
                } else {
                    sidebar.classList.add('collapsed');
                    sidebar.style.width = '';
                }
            });
        });
    },

    /* ── 认证表单 ── */

    _bindAuthForms() {
        // beforeunload: warn when login/register form has data
        window.addEventListener('beforeunload', (e) => {
            const loginPage = document.getElementById('login-page');
            if (loginPage && loginPage.classList.contains('active')) {
                const lu = document.getElementById('login-username')?.value;
                const lp = document.getElementById('login-password')?.value;
                const ru = document.getElementById('register-username')?.value;
                const rp = document.getElementById('register-password')?.value;
                if ((lu || lp) || (ru || rp)) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            }
        });

        // Login
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value;
            const errorEl = document.getElementById('login-error');

            try {
                errorEl.textContent = '';
                await Auth.login(username, password);
                this._resetSessionState();
                API.log('info', 'auth.login.frontend_success', { username }, '用户登录');
                Notification.init();
                if (password.length < 8) {
                    this._showToast('口令较为简短，有风险');
                }
                this._showReviewPage();
            } catch (err) {
                errorEl.textContent = err.message || '登录失败';
                API.log('error', 'auth.login.frontend_failed', { username, error: err.message }, '登录失败');
            }
        });

        // Register
        document.getElementById('register-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('register-username').value.trim();
            const password = document.getElementById('register-password').value;
            const errorEl = document.getElementById('register-error');

            try {
                errorEl.textContent = '';
                await Auth.register(username, password);
                this._resetSessionState();
                API.log('info', 'auth.register.frontend_success', { username }, '用户注册');
                Notification.init();
                this._showReviewPage();
            } catch (err) {
                errorEl.textContent = err.message || '注册失败';
                API.log('error', 'auth.register.frontend_failed', { username, error: err.message }, '注册失败');
            }
        });

        // Toggle login/register
        document.getElementById('show-register').addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('login-form-block').style.display = 'none';
            document.getElementById('register-form-block').style.display = '';
        });

        document.getElementById('show-login').addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('register-form-block').style.display = 'none';
            document.getElementById('login-form-block').style.display = '';
        });

        // 密码可见性切换（登录/注册）
        Auth._bindPasswordToggles(document.getElementById('login-form-block'));
        Auth._bindPasswordToggles(document.getElementById('register-form-block'));
    },

    /* ── 导航 ── */

    /* 统一账号菜单：四个页面（聊天/评审/团队空间/管理后台）右上角同一结构
       个人 Agent / 修改密码 / 退出登录 */
    _bindUserMenu(triggerId, dropdownId) {
        const trigger = document.getElementById(triggerId);
        const dd = document.getElementById(dropdownId);
        if (!trigger || !dd) return;
        const setOpen = (open) => {
            dd.style.display = open ? '' : 'none';
            trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        };
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            const willOpen = dd.style.display === 'none';
            document.querySelectorAll('.user-menu-dropdown').forEach((other) => {
                if (other !== dd) {
                    other.style.display = 'none';
                    other.parentElement?.querySelector('.topbar-user')?.setAttribute('aria-expanded', 'false');
                }
            });
            setOpen(willOpen);
        });
        trigger.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') setOpen(false);
        });
        dd.addEventListener('click', async (e) => {
            const item = e.target.closest('[data-user-menu-action]');
            if (!item) return;
            setOpen(false);
            const action = item.dataset.userMenuAction;
            if (action === 'agent-settings') {
                this._showAgentSettingsModal();
            } else if (action === 'change-password') {
                Auth.showChangePassword();
            } else if (action === 'logout') {
                this._logout(item.dataset.logoutSource || 'chat');
            }
        });
    },

    _logout(source) {
        API.log('info', 'auth.logout', { source }, `用户退出(${source})`);
        this._resetSessionState();
        Notification.destroy();
        Auth.logout();
        sessionStorage.removeItem('lastPage');
        this._showLoginPage();
    },

    _bindNavigation() {
        // 统一用户菜单：聊天 / 评审 / 团队空间 / 管理后台
        this._bindUserMenu('user-display', 'user-menu-dropdown');
        this._bindUserMenu('review-user-display', 'review-user-menu-dropdown');
        this._bindUserMenu('workspace-user-display', 'workspace-user-menu-dropdown');
        this._bindUserMenu('admin-user-display', 'admin-user-menu-dropdown');

        // Go to admin (from chat page topbar)
        document.getElementById('go-admin').addEventListener('click', (e) => {
            e.preventDefault();
            this._adminFromPage = 'chat';
            API.log('info', 'frontend.navigation', { from: 'chat', to: 'admin' }, '进入管理后台');
            Chat.destroy();
            this._showAdminPage();
        });

        // Back from admin — return to the page we came from, default to review
        document.getElementById('back-to-chat').addEventListener('click', (e) => {
            e.preventDefault();
            const from = this._adminFromPage || 'review';
            this._adminFromPage = null;
            API.log('info', 'frontend.navigation', { from: 'admin', to: from }, '离开管理后台');
            this._navigateTo(from);
        });

        // Back to chat from review
        document.getElementById('back-to-chat-from-review').addEventListener('click', (e) => {
            e.preventDefault();
            API.log('info', 'frontend.navigation', { from: 'review', to: 'chat' }, '进入智能对话');
            Review.destroy();
            this._showUserPage();
        });

        const goAdminFromReviewBtn = document.getElementById('go-admin-from-review');
        if (goAdminFromReviewBtn) {
            goAdminFromReviewBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this._adminFromPage = 'review';
                Review.destroy();
                API.log('info', 'frontend.navigation', { from: 'review', to: 'admin' }, '进入管理后台');
                this._showAdminPage();
            });
        }

        // Go to review workspace
        const goReviewBtn = document.getElementById('go-review');
        if (goReviewBtn) {
            goReviewBtn.addEventListener('click', (e) => {
                e.preventDefault();
                API.log('info', 'frontend.navigation', { from: 'chat', to: 'review' }, '进入审查工作台');
                Chat.destroy();
                this._showReviewPage();
            });
        }

        // Go to workspace (from chat page)
        const goWorkspaceBtn = document.getElementById('go-workspace');
        if (goWorkspaceBtn) {
            goWorkspaceBtn.addEventListener('click', (e) => {
                e.preventDefault();
                API.log('info', 'frontend.navigation', { from: 'chat', to: 'workspace' }, '进入团队空间');
                Chat.destroy();
                this._showWorkspacePage();
            });
        }

        // Go to workspace (from review page)
        const goWorkspaceFromReviewBtn = document.getElementById('go-workspace-from-review');
        if (goWorkspaceFromReviewBtn) {
            goWorkspaceFromReviewBtn.addEventListener('click', (e) => {
                e.preventDefault();
                API.log('info', 'frontend.navigation', { from: 'review', to: 'workspace' }, '进入团队空间');
                Review.destroy();
                this._showWorkspacePage();
            });
        }

        // Go to workspace (from admin page)
        const goWorkspaceFromAdminBtn = document.getElementById('go-workspace-from-admin');
        if (goWorkspaceFromAdminBtn) {
            goWorkspaceFromAdminBtn.addEventListener('click', (e) => {
                e.preventDefault();
                API.log('info', 'frontend.navigation', { from: 'admin', to: 'workspace' }, '进入团队空间');
                this._showWorkspacePage();
            });
        }

        // Go to chat from workspace
        const goChatFromWorkspaceBtn = document.getElementById('go-chat-from-workspace');
        if (goChatFromWorkspaceBtn) {
            goChatFromWorkspaceBtn.addEventListener('click', (e) => {
                e.preventDefault();
                API.log('info', 'frontend.navigation', { from: 'workspace', to: 'chat' }, '进入智能对话');
                Workspace.destroy();
                this._showUserPage();
            });
        }

        // Go to review from workspace
        const goReviewFromWorkspaceBtn = document.getElementById('go-review-from-workspace');
        if (goReviewFromWorkspaceBtn) {
            goReviewFromWorkspaceBtn.addEventListener('click', (e) => {
                e.preventDefault();
                API.log('info', 'frontend.navigation', { from: 'workspace', to: 'review' }, '进入审查工作台');
                Workspace.destroy();
                this._showReviewPage();
            });
        }

        // Go to admin from workspace
        const goAdminFromWorkspaceBtn = document.getElementById('go-admin-from-workspace');
        if (goAdminFromWorkspaceBtn) {
            goAdminFromWorkspaceBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this._adminFromPage = 'workspace';
                Workspace.destroy();
                API.log('info', 'frontend.navigation', { from: 'workspace', to: 'admin' }, '进入管理后台');
                this._showAdminPage();
            });
        }

        // Add user button
        document.getElementById('add-user-btn')?.addEventListener('click', () => {
            Admin.showAddUserForm();
        });

        // Add prompt button
        document.getElementById('add-prompt-btn')?.addEventListener('click', () => {
            Admin.createPrompt();
        });

        // Add review prompt button
        document.getElementById('add-review-prompt-btn')?.addEventListener('click', () => {
            Admin.createReviewPrompt();
        });

        // Add model button
        document.getElementById('add-model-btn')?.addEventListener('click', () => {
            Admin.createModel();
        });
    },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());

// Global: close user dropdowns on outside click
document.addEventListener('click', (e) => {
    document.querySelectorAll('.user-menu-dropdown').forEach((dd) => {
        const trigger = dd.parentElement?.querySelector('.topbar-user');
        if (!dd.contains(e.target) && e.target !== trigger && !trigger?.contains(e.target)) {
            dd.style.display = 'none';
            trigger?.setAttribute('aria-expanded', 'false');
        }
    });
});

// Global: re-align sidebar widths on window resize
let _resizeTimer;
window.addEventListener('resize', () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(() => App._alignSidebarToDivider(), 150);
});
