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