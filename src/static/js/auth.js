/* 认证相关逻辑 */
const Auth = {
    currentUser: null,

    async init() {
        const token = API.getToken();
        if (!token) return false;

        try {
            this.currentUser = await API.getMe();
            return true;
        } catch (e) {
            // 401/403 means token is genuinely invalid → clear and require re-login
            if (e.message && (e.message.includes('401') || e.message.includes('403'))) {
                API.clearToken();
                return false;
            }
            // Network/server error → token might still be valid, try to proceed
            // with a minimal user object so the user isn't dumped to login page
            this.currentUser = { id: 0, username: '用户', role: 'user' };
            return true;
        }
    },

    getUser() {
        return this.currentUser;
    },

    async login(username, password) {
        const result = await API.login(username, password);
        API.setToken(result.access_token);
        this.currentUser = await API.getMe();
        return this.currentUser;
    },

    async register(username, password) {
        const result = await API.register(username, password);
        API.setToken(result.access_token);
        this.currentUser = await API.getMe();
        return this.currentUser;
    },

    logout() {
        API.clearToken();
        this.currentUser = null;
    },

    isAdmin() {
        return this.currentUser && this.currentUser.role === 'admin';
    },

    isLoggedIn() {
        return !!this.currentUser;
    },

    showChangePassword() {
        Admin.showModal(`
            <h3>修改密码</h3>
            <div class="field">
                <label>旧密码</label>
                <input type="password" id="old-password" placeholder="输入当前密码">
            </div>
            <div class="field">
                <label>新密码</label>
                <input type="password" id="new-password" placeholder="输入新密码（至少6位）">
            </div>
            <div class="field">
                <label>确认新密码</label>
                <input type="password" id="confirm-password" placeholder="再次输入新密码">
            </div>
            <div id="change-password-error" class="field-error"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Auth.savePassword()">保存</button>
            </div>
        `);
    },

    async savePassword() {
        const oldPwd = document.getElementById('old-password').value;
        const newPwd = document.getElementById('new-password').value;
        const confirmPwd = document.getElementById('confirm-password').value;
        const errEl = document.getElementById('change-password-error');

        if (!oldPwd || !newPwd || !confirmPwd) {
            errEl.textContent = '请填写所有密码字段';
            return;
        }
        if (newPwd.length < 6) {
            errEl.textContent = '新密码至少6位';
            return;
        }
        if (newPwd !== confirmPwd) {
            errEl.textContent = '两次输入的新密码不一致';
            return;
        }

        try {
            await API.changePassword(oldPwd, newPwd);
            Admin.closeModal();
            alert('密码修改成功');
        } catch (e) {
            errEl.textContent = e.message || '修改失败';
        }
    },
};

/* 品牌配置应用 */
const Branding = {
    config: null,

    async load() {
        try {
            const resp = await fetch('/api/app/branding');
            if (resp.ok) {
                this.config = await resp.json();
                this.apply();
            }
        } catch (e) {
            console.warn('branding config load failed, using defaults:', e);
        }
    },

    apply() {
        if (!this.config) return;
        const c = this.config;

        // Page title & favicon
        if (c.app_title) {
            const titleEl = document.getElementById('page-title');
            if (titleEl) titleEl.textContent = c.app_title;
            document.title = c.app_title;
        }
        if (c.favicon) {
            const linkEl = document.getElementById('favicon-link');
            if (linkEl) linkEl.href = c.favicon;
        }

        // Theme colors
        if (c.theme) {
            const root = document.documentElement;
            if (c.theme.primary) root.style.setProperty('--color-brand', c.theme.primary);
            if (c.theme.primary_hover) root.style.setProperty('--color-brand-hover', c.theme.primary_hover);
            if (c.theme.primary) {
                root.style.setProperty('--blue-6', c.theme.primary);
                const metaEl = document.getElementById('theme-color-meta');
                if (metaEl) metaEl.content = c.theme.primary;
            }
            if (c.theme.accent) root.style.setProperty('--green-6', c.theme.accent);
        }

        // Text-based branding attributes
        const textMap = {
            'login-title': c.login_title,
            'login-subtitle': c.login_subtitle,
            'topbar-title': c.topbar_title || c.app_title,
            'app-version': c.app_version ? 'Ver. ' + c.app_version : null,
            'review-workspace-label': c.review_workspace_label,
            'chat-badge': c.admin_label ? null : null,  // chat badge stays as-is
            'review-badge': null,  // review badge stays as-is
            'admin-badge': c.admin_label,
            'admin-label': c.admin_label,
        };

        for (const [attr, text] of Object.entries(textMap)) {
            if (!text) continue;
            const els = document.querySelectorAll(`[data-branding="${attr}"]`);
            for (const el of els) {
                el.textContent = text;
            }
        }

        if (c.login_notice) {
            this.renderLoginNotice(c.login_notice);
        }

        // Logo assets (img replacement)
        const logoClassMap = {
            'login-logo': 'branding-logo branding-logo-login',
            'topbar-logo': 'branding-logo branding-logo-topbar',
        };

        // 互作 fallback：若只配置了一个 logo，另一处用同一张图但保持各自尺寸
        const logoUrlMap = {
            'login-logo': c.login_logo || c.topbar_logo || '',
            'topbar-logo': c.topbar_logo || c.login_logo || '',
        };

        for (const key of ['login-logo', 'topbar-logo']) {
            const url = logoUrlMap[key];
            if (!url) continue;
            const containers = document.querySelectorAll(`[data-branding="${key}"]`);
            for (const container of containers) {
                const classes = logoClassMap[key] || 'branding-logo';
                container.innerHTML = `<img src="${url}" alt="logo" class="${classes}">`;
            }
        }
    },

    renderLoginNotice(notice) {
        if (typeof notice !== 'string') return;
        const lines = notice.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
        if (!lines.length) return;

        const containers = document.querySelectorAll('[data-branding="login-notice"]');
        for (const container of containers) {
            container.innerHTML = '';
            container.setAttribute('aria-label', lines[0].replace(/[：:]\s*$/, ''));

            lines.forEach((line, index) => {
                const p = document.createElement('p');
                if (index === 0) {
                    const strong = document.createElement('strong');
                    strong.textContent = line;
                    p.appendChild(strong);
                } else {
                    p.textContent = line;
                }
                container.appendChild(p);
            });
        }
    },
};

window.Auth = Auth;
window.Branding = Branding;
