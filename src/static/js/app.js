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
                    if (sidebar && !sidebar.classList.contains('collapsed')) {
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
    },

    /* ── 导航 ── */

    _bindUserMenu(triggerId, dropdownId) {
        const trigger = document.getElementById(triggerId);
        if (!trigger) return;
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            if (dropdownId) {
                const dd = document.getElementById(dropdownId);
                dd.style.display = dd.style.display === 'none' ? '' : 'none';
            } else {
                Auth.showChangePassword();
            }
        });
    },

    _bindNavigation() {
        // Logout
        document.getElementById('logout-btn').addEventListener('click', (e) => {
            e.preventDefault();
            API.log('info', 'auth.logout', { source: 'chat' }, '用户退出');
            this._resetSessionState();
            Auth.logout();
            sessionStorage.removeItem('lastPage');
            this._showLoginPage();
        });

        document.getElementById('admin-logout-btn').addEventListener('click', (e) => {
            e.preventDefault();
            API.log('info', 'auth.logout', { source: 'admin' }, '用户退出(admin)');
            this._resetSessionState();
            Auth.logout();
            sessionStorage.removeItem('lastPage');
            this._showLoginPage();
        });

        document.getElementById('review-logout-btn').addEventListener('click', (e) => {
            e.preventDefault();
            API.log('info', 'auth.logout', { source: 'review' }, '用户退出(review)');
            this._resetSessionState();
            Auth.logout();
            sessionStorage.removeItem('lastPage');
            this._showLoginPage();
        });

        document.getElementById('workspace-logout-btn').addEventListener('click', (e) => {
            e.preventDefault();
            API.log('info', 'auth.logout', { source: 'workspace' }, '用户退出(workspace)');
            this._resetSessionState();
            Auth.logout();
            sessionStorage.removeItem('lastPage');
            this._showLoginPage();
        });

        // User dropdown menu
        this._bindUserMenu('user-display', 'user-menu-dropdown');
        this._bindUserMenu('review-user-display', null);
        this._bindUserMenu('admin-user-display', null);

        // Change password
        document.getElementById('change-password-btn').addEventListener('click', () => {
            document.getElementById('user-menu-dropdown').style.display = 'none';
            Auth.showChangePassword();
        });

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

// Global: close user dropdown on outside click
document.addEventListener('click', (e) => {
    const dd = document.getElementById('user-menu-dropdown');
    if (dd && !dd.contains(e.target) && e.target.id !== 'user-display') {
        dd.style.display = 'none';
    }
});

// Global: re-align sidebar widths on window resize
let _resizeTimer;
window.addEventListener('resize', () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(() => App._alignSidebarToDivider(), 150);
});
