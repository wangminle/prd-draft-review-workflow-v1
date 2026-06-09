/* API 调用封装 */
const API = {
    _token: null,
    _base: '',

    setToken(token) {
        this._token = token;
        localStorage.setItem('token', token);
    },

    getToken() {
        if (!this._token) {
            this._token = localStorage.getItem('token');
        }
        return this._token;
    },

    clearToken() {
        this._token = null;
        localStorage.removeItem('token');
    },

    async request(method, path, body) {
        const headers = { 'Content-Type': 'application/json' };
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const opts = { method, headers };
        if (body !== undefined) {
            opts.body = JSON.stringify(body);
        }
        const resp = await fetch(`${this._base}${path}`, opts);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        return resp.json();
    },

    /* 认证 */
    login(username, password) {
        return this.request('POST', '/api/auth/login', { username, password });
    },

    register(username, password) {
        return this.request('POST', '/api/auth/register', { username, password });
    },

    getMe() {
        return this.request('GET', '/api/auth/me');
    },

    changePassword(oldPwd, newPwd) {
        return this.request('PUT', '/api/auth/password', { old_password: oldPwd, new_password: newPwd });
    },

    /* 对话 */
    async chatStream(payload) {
        const headers = { 'Content-Type': 'application/json' };
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers,
            body: JSON.stringify({ ...payload, stream: true }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        return resp.body.getReader();
    },

    getModels() {
        return this.request('GET', '/api/chat/models');
    },

    getPrompts() {
        return this.request('GET', '/api/chat/prompts');
    },

    /* 上传 */
    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch('/api/upload/file', { method: 'POST', headers, body: formData });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        return resp.json();
    },

    async submitUrl(url) {
        return this.request('POST', '/api/upload/url', { url });
    },

    /* 历史记录 */
    getConversations(page = 1) {
        return this.request('GET', `/api/history/conversations?page=${page}&page_size=20`);
    },

    getConversation(id) {
        return this.request('GET', `/api/history/conversations/${id}`);
    },

    deleteConversation(id) {
        return this.request('DELETE', `/api/history/conversations/${id}`);
    },

    searchMessages(q) {
        return this.request('GET', `/api/history/search?q=${encodeURIComponent(q)}`);
    },

    /* 管理 — 用户 */
    getUsers() { return this.request('GET', '/api/admin/users'); },
    createUser(data) { return this.request('POST', '/api/admin/users', data); },
    updateUser(id, data) { return this.request('PUT', `/api/admin/users/${id}`, data); },
    deleteUser(id) { return this.request('DELETE', `/api/admin/users/${id}`); },

    /* 管理 — Prompt 模板 */
    getAdminPrompts() { return this.request('GET', '/api/admin/prompts'); },
    createPrompt(data) { return this.request('POST', '/api/admin/prompts', data); },
    updatePrompt(id, data) { return this.request('PUT', `/api/admin/prompts/${id}`, data); },
    deletePrompt(id) { return this.request('DELETE', `/api/admin/prompts/${id}`); },

    /* 管理 — 模型配置 & API Key */
    getAdminModels() { return this.request('GET', '/api/admin/models'); },
    createModel(data) { return this.request('POST', '/api/admin/models', data); },
    updateModelConfig(modelId, data) { return this.request('PUT', `/api/admin/models/${modelId}`, data); },
    updateModelApiKey(modelId, apiKey) { return this.request('PUT', `/api/admin/models/${modelId}/api-key`, { api_key: apiKey }); },
    reorderAdminModels(modelIds) { return this.request('PUT', '/api/admin/models/order', { model_ids: modelIds }); },
    deleteModel(modelId) { return this.request('DELETE', `/api/admin/models/${modelId}`); },
    testModelConnection(modelId) { return this.request('POST', `/api/admin/models/${modelId}/test-connection`); },
    speedTestModel(modelId) { return this.request('POST', `/api/admin/models/${modelId}/speed-test`); },

    /* 管理 — Skills */
    getAdminSkills() { return this.request('GET', '/api/admin/skills'); },
    updateAdminSkill(skillId, data) { return this.request('PUT', `/api/admin/skills/${encodeURIComponent(skillId)}`, data); },

    /* 管理 — Pi Agent 配置 */
    getPiAgentConfig() { return this.request('GET', '/api/pi-agent/config'); },
    updatePiAgentConfig(data) { return this.request('PUT', '/api/pi-agent/config', data); },
    updatePiAgentLlmApiKey(apiKey) { return this.request('PUT', '/api/pi-agent/config/llm-api-key', { api_key: apiKey }); },
    updatePiAgentSearchApiKey(apiKey) { return this.request('PUT', '/api/pi-agent/config/search-api-key', { api_key: apiKey }); },
    updatePiAgentVisionApiKey(apiKey) { return this.request('PUT', '/api/pi-agent/config/vision-api-key', { api_key: apiKey }); },
    testPiAgentConnection() { return this.request('POST', '/api/pi-agent/config/test-connection'); },
    speedTestPiAgent() { return this.request('POST', '/api/pi-agent/config/speed-test'); },

    /* 管理 — 统计 */
    getStats() { return this.request('GET', '/api/admin/stats'); },

    /* ── 团队空间 ── */

    getWorkspaces() { return this.request('GET', '/api/workspace'); },
    getDefaultWorkspace() { return this.request('GET', '/api/workspace/default'); },
    updateDefaultWorkspace(data) { return this.request('PUT', '/api/workspace/default', data); },
    getDefaultWorkspaceMembers() { return this.request('GET', '/api/workspace/default/members'); },
    updateDefaultWorkspaceMember(userId, data) { return this.request('PUT', `/api/workspace/default/members/${userId}`, data); },
    getWorkspaceMembers(wsId) { return this.request('GET', `/api/workspace/${wsId}/members`); },
    getWorkspaceSources(wsId, params) {
        let url = `/api/workspace/${wsId}/sources`;
        if (params) {
            const qs = new URLSearchParams(params).toString();
            if (qs) url += '?' + qs;
        }
        return this.request('GET', url);
    },
    getWorkspaceSourceDetail(wsId, sourceId) { return this.request('GET', `/api/workspace/${wsId}/sources/${sourceId}`); },
    deleteWorkspaceSource(wsId, sourceId) { return this.request('DELETE', `/api/workspace/${wsId}/sources/${sourceId}`); },
    updateSourceTags(wsId, sourceId, tags) { return this.request('PUT', `/api/workspace/${wsId}/sources/${sourceId}/tags`, { tags }); },

    async downloadWorkspaceSource(wsId, sourceId) {
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch(`/api/workspace/${wsId}/sources/${sourceId}/download`, { method: 'GET', headers });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        const disposition = resp.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="([^"]+)"/);
        return {
            blob: await resp.blob(),
            filename: match ? match[1] : `source-${sourceId}`,
        };
    },

    async uploadWorkspaceSource(wsId, formData) {
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch(`/api/workspace/${wsId}/sources`, { method: 'POST', headers, body: formData });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        return resp.json();
    },

    /* ── 项目引用资料 ── */

    addProjectSourceRef(projectId, data) { return this.request('POST', `/api/review/project/${projectId}/sources`, data); },
    listProjectSourceRefs(projectId) { return this.request('GET', `/api/review/project/${projectId}/sources`); },

    /* ── 知识库检索 ── */
    retrieveKnowledge(wsId, query, topK = 5) {
        return this.request('POST', `/api/workspace/${wsId}/retrieve`, { query, top_k: topK });
    },

    /* ── 需求审查 ── */

    getReviewProjects() { return this.request('GET', '/api/review/projects'); },
    createReviewProject(data) { return this.request('POST', '/api/review/projects', data); },
    getReviewProject(id) { return this.request('GET', `/api/review/projects/${id}`); },
    deleteReviewProject(id) { return this.request('DELETE', `/api/review/projects/${id}`); },
    deleteReviewDoc(projectId, docId) { return this.request('DELETE', `/api/review/projects/${projectId}/documents/${docId}`); },

    async uploadReviewDocs(projectId, formData) {
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch(`/api/review/projects/${projectId}/documents`, {
            method: 'POST', headers, body: formData,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        return resp.json();
    },

    async uploadHistoricalDocs(projectId, formData) {
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch(`/api/review/projects/${projectId}/historical-documents`, {
            method: 'POST', headers, body: formData,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(`${resp.status} ${err.detail || resp.statusText}`);
        }
        return resp.json();
    },

    getReviewDocs(projectId) { return this.request('GET', `/api/review/projects/${projectId}/documents`); },

    listReviews(projectId) {
        return this.request('GET', `/api/review/projects/${projectId}/reviews`);
    },

    startReview(projectId, data) {
        return this.request('POST', `/api/review/projects/${projectId}/reviews`, data);
    },

    async getReviewProgress(projectId, reviewId) {
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const ticketResp = await fetch('/api/auth/sse-ticket', { method: 'POST', headers });
        if (!ticketResp.ok) {
            const err = await ticketResp.json().catch(() => ({ detail: ticketResp.statusText }));
            throw new Error(`${ticketResp.status} ${err.detail || ticketResp.statusText}`);
        }
        const data = await ticketResp.json();
        const url = `${this._base}/api/review/projects/${projectId}/reviews/${reviewId}`;
        return new EventSource(`${url}?ticket=${encodeURIComponent(data.ticket)}`);
    },

    async getReviewTaskStatus(projectId, reviewId) {
        return this.request('GET', `/api/review/projects/${projectId}/reviews/${reviewId}/status`);
    },

    getReviewAnalyses(projectId, reviewId) {
        return this.request('GET', `/api/review/projects/${projectId}/reviews/${reviewId}/analyses`);
    },

    getSystemReview(projectId, reviewId) {
        return this.request('GET', `/api/review/projects/${projectId}/reviews/${reviewId}/system-review`);
    },

    getReviewReport(projectId, reviewId) {
        return this.request('GET', `/api/review/projects/${projectId}/reviews/${reviewId}/report`);
    },

    async getReviewReportMd(projectId, reviewId) {
        const headers = {};
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        const resp = await fetch(`/api/review/projects/${projectId}/reviews/${reviewId}/report?format=markdown`, { headers });
        if (!resp.ok) throw new Error('导出失败');
        return resp.text();
    },

    cancelReview(projectId, reviewId) {
        return this.request('POST', `/api/review/projects/${projectId}/reviews/${reviewId}/cancel`);
    },

    getReviewContext(projectId) {
        return this.request('GET', `/api/review/projects/${projectId}/context`);
    },

    updateReviewContext(projectId, data) {
        return this.request('PUT', `/api/review/projects/${projectId}/context`, data);
    },

    getReviewPrompts() { return this.request('GET', '/api/review/prompts'); },
    createReviewPrompt(data) { return this.request('POST', '/api/review/prompts', data); },
    updateReviewPrompt(id, data) { return this.request('PUT', `/api/review/prompts/${id}`, data); },

    /* 前端日志 */
    log(level, action, detail, message) {
        const page = document.querySelector('.page.active')?.id || 'unknown';
        const headers = { 'Content-Type': 'application/json' };
        if (this.getToken()) {
            headers['Authorization'] = `Bearer ${this.getToken()}`;
        }
        fetch('/api/log', {
            method: 'POST',
            headers,
            body: JSON.stringify({ level, action, message: message || action, page, detail }),
        }).catch(() => {});
    },

    /* 上下文项 CRUD */
    getContextItems(convId) {
        return this.request('GET', `/api/chat/conversations/${convId}/context`);
    },
    createContextItem(convId, data) {
        return this.request('POST', `/api/chat/conversations/${convId}/context`, data);
    },
    updateContextItem(convId, itemId, data) {
        return this.request('PUT', `/api/chat/conversations/${convId}/context/${itemId}`, data);
    },
    deleteContextItem(convId, itemId) {
        return this.request('DELETE', `/api/chat/conversations/${convId}/context/${itemId}`);
    },

    /* ── Agent (P3) ── */
    getAgentProfile() { return this.request('GET', '/api/agent/profile'); },
    updateAgentProfile(data) { return this.request('PUT', '/api/agent/profile', data); },
    listAgentAuthorizations() { return this.request('GET', '/api/agent/profile/authorizations'); },
    createAgentAuthorization(data) { return this.request('POST', '/api/agent/profile/authorizations', data); },
    revokeAgentAuthorization(authId) { return this.request('DELETE', `/api/agent/profile/authorizations/${authId}`); },
    createAgentRun(data) { return this.request('POST', '/api/agent/runs', data); },
    getAgentRun(runId) { return this.request('GET', `/api/agent/runs/${runId}`); },
    listAgentRuns() { return this.request('GET', '/api/agent/runs'); },
    listPendingApprovals() { return this.request('GET', '/api/agent/approvals'); },
    decideApproval(reqId, data) { return this.request('POST', `/api/agent/approvals/${reqId}/decide`, data); },
    listMCPServers() { return this.request('GET', '/api/agent/mcp/servers'); },
    createMCPServer(data) { return this.request('POST', '/api/agent/mcp/servers', data); },
    listMCPServerPolicies(serverId) { return this.request('GET', `/api/agent/mcp/servers/${serverId}/policies`); },
    createMCPServerPolicy(serverId, data) { return this.request('POST', `/api/agent/mcp/servers/${serverId}/policies`, data); },
};
