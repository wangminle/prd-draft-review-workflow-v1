/* P4.D.5: 通知铃铛 + Inbox 模块 */
const Notification = {
    _sse: null,
    _unreadCount: 0,
    _currentTab: 'unread',
    _pageIds: ['chat', 'review', 'workspace', 'admin'],
    _bound: false,

    init() {
        if (!this._bound) {
            this._bindBellActions();
            this._bindGlobalClose();
            this._bound = true;
        }
        this.loadUnreadCount();
        this.connectSSE();
    },

    destroy() {
        if (this._sse) {
            this._sse.close();
            this._sse = null;
        }
    },

    /* ── SSE 实时推送 ── */

    connectSSE() {
        if (this._sse) {
            this._sse.close();
            this._sse = null;
        }
        const token = API.getToken();
        if (!token) return;
        // 使用 SSE ticket 方式连接，类似审查进度 SSE
        const headers = { 'Authorization': `Bearer ${token}` };
        fetch('/api/auth/sse-ticket', { method: 'POST', headers })
            .then(r => r.json())
            .then(data => {
                const url = `/api/notifications/stream?ticket=${encodeURIComponent(data.ticket)}`;
                this._sse = new EventSource(url);
                this._sse.onmessage = (event) => {
                    try {
                        const notif = JSON.parse(event.data);
                        this._unreadCount += 1;
                        this._updateBadge();
                        // 如果当前有打开的 dropdown，追加到列表
                        this._appendLiveNotification(notif);
                        App._showToast(notif.title || '收到新通知');
                    } catch (e) {
                        console.warn('SSE notification parse error:', e);
                    }
                };
                this._sse.onerror = () => {
                    this._sse.close();
                    this._sse = null;
                };
            })
            .catch(() => {});
    },

    /* ── 未读数 ── */

    async loadUnreadCount() {
        try {
            const data = await API.getUnreadNotificationCount();
            this._unreadCount = data.unread_count || 0;
            this._updateBadge();
        } catch (e) {
            console.warn('Failed to load unread count:', e);
        }
    },

    _updateBadge() {
        for (const pid of this._pageIds) {
            const badge = document.getElementById(`notif-badge-${pid}`);
            if (!badge) continue;
            if (this._unreadCount > 0) {
                badge.textContent = this._unreadCount > 99 ? '99+' : this._unreadCount;
                badge.style.display = '';
            } else {
                badge.style.display = 'none';
            }
        }
    },

    /* ── Bell 按钮绑定 ── */

    _bindBellActions() {
        for (const pid of this._pageIds) {
            // Bell 按钮点击 → 打开/关闭 dropdown
            const bellBtn = document.querySelector(`#notif-bell-${pid} .notification-bell-btn`);
            if (!bellBtn) continue;
            bellBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleDropdown(pid);
            });

            // 全部已读按钮
            const markAllBtn = document.getElementById(`notif-mark-all-read-${pid}`);
            if (markAllBtn) {
                markAllBtn.addEventListener('click', async () => {
                    try {
                        await API.batchMarkNotificationsRead();
                        this._unreadCount = 0;
                        this._updateBadge();
                        this._loadList(pid);
                    } catch (e) {
                        console.warn('batch read failed:', e);
                    }
                });
            }

            // Tab 切换
            const dropdown = document.getElementById(`notif-dropdown-${pid}`);
            if (!dropdown) continue;
            dropdown.querySelectorAll('.notification-tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    dropdown.querySelectorAll('.notification-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    this._currentTab = tab.dataset.notifTab;
                    this._loadList(pid);
                });
            });
        }
    },

    _bindGlobalClose() {
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.notification-bell-wrap')) {
                for (const pid of this._pageIds) {
                    const dd = document.getElementById(`notif-dropdown-${pid}`);
                    if (dd) dd.style.display = 'none';
                }
            }
        });
    },

    _toggleDropdown(pid) {
        const dd = document.getElementById(`notif-dropdown-${pid}`);
        if (!dd) return;
        const isVisible = dd.style.display !== 'none';
        // 先关闭所有
        for (const p of this._pageIds) {
            const other = document.getElementById(`notif-dropdown-${p}`);
            if (other) other.style.display = 'none';
        }
        if (!isVisible) {
            dd.style.display = '';
            this._loadList(pid);
        }
    },

    /* ── 通知列表加载 ── */

    async _loadList(pid) {
        const listEl = document.getElementById(`notif-list-${pid}`);
        if (!listEl) return;

        const statusMap = { unread: 'unread', read: 'read', archived: 'archived' };
        const status = statusMap[this._currentTab] || null;

        try {
            const data = await API.listNotifications(status);
            const items = data.items || [];
            if (!items.length) {
                listEl.innerHTML = '<div class="notification-empty">暂无通知</div>';
                return;
            }
            listEl.innerHTML = items.map(n => this._renderNotificationItem(n, pid)).join('');
            this._bindItemActions(listEl, pid);
        } catch (e) {
            listEl.innerHTML = '<div class="notification-empty">加载失败</div>';
        }
    },

    _renderNotificationItem(n, pid) {
        const isUnread = n.status === 'unread';
        const cls = `notification-item ${isUnread ? 'unread' : 'read'}`;
        const timeStr = this._formatTime(n.created_at);
        const dotHtml = '<span class="notification-item-dot"></span>';
        const actionsHtml = isUnread
            ? `<span class="notification-item-action" data-notif-action="read" data-notif-id="${n.id}">标记已读</span>`
            : `<span class="notification-item-action" data-notif-action="archive" data-notif-id="${n.id}">归档</span>`;
        const jumpHtml = n.object_type && n.object_id
            ? `<span class="notification-item-action" data-notif-action="jump" data-notif-otype="${n.object_type}" data-notif-oid="${n.object_id}">查看</span>`
            : '';
        return `
            <div class="${cls}" data-notif-id="${n.id}">
                ${dotHtml}
                <div class="notification-item-body">
                    <div class="notification-item-title">${this._esc(n.title || '')}</div>
                    <div class="notification-item-time">${timeStr}</div>
                </div>
                <div class="notification-item-actions">
                    ${jumpHtml}
                    ${actionsHtml}
                </div>
            </div>
        `;
    },

    _bindItemActions(listEl, pid) {
        listEl.querySelectorAll('[data-notif-action]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const action = btn.dataset.notifAction;
                const id = parseInt(btn.dataset.notifId);
                try {
                    if (action === 'read') {
                        await API.markNotificationRead(id);
                        this._unreadCount = Math.max(0, this._unreadCount - 1);
                        this._updateBadge();
                    } else if (action === 'archive') {
                        await API.archiveNotification(id);
                    } else if (action === 'jump') {
                        this._jumpToObject(btn.dataset.notifOtype, parseInt(btn.dataset.notifOid));
                        // 同时标记已读
                        await API.markNotificationRead(id);
                        this._unreadCount = Math.max(0, this._unreadCount - 1);
                        this._updateBadge();
                    }
                    this._loadList(pid);
                } catch (e) {
                    console.warn('notification action failed:', e);
                }
            });
        });
    },

    _appendLiveNotification(notif) {
        // 在当前打开的 dropdown 中追加
        for (const pid of this._pageIds) {
            const dd = document.getElementById(`notif-dropdown-${pid}`);
            if (!dd || dd.style.display === 'none') continue;
            if (this._currentTab !== 'unread') continue;
            const listEl = document.getElementById(`notif-list-${pid}`);
            if (!listEl) continue;
            // 移除空态
            const empty = listEl.querySelector('.notification-empty');
            if (empty) empty.remove();
            const html = this._renderNotificationItem(notif, pid);
            listEl.insertAdjacentHTML('afterbegin', html);
            this._bindItemActions(listEl, pid);
        }
    },

    /* ── 跳转到相关对象 ── */

    _jumpToObject(objectType, objectId) {
        // 关闭所有 dropdown
        for (const pid of this._pageIds) {
            const dd = document.getElementById(`notif-dropdown-${pid}`);
            if (dd) dd.style.display = 'none';
        }
        if (objectType === 'review_request' || objectType === 'review_round') {
            App._showReviewPage();
            // 通知 Review 模块跳到对应协作审查
            if (typeof Review._showCollabRequest === 'function') {
                Review._showCollabRequest(objectId);
            }
        } else if (objectType === 'agent_approval') {
            App._showAdminPage();
            // 通知 Admin 模块跳到审批页
            if (typeof Admin._showAgentApprovals === 'function') {
                Admin._showAgentApprovals();
            }
        } else if (objectType === 'agent_conversation') {
            // P5.A.3: 跳转到智能对话页
            App._showUserPage();
        } else if (objectType === 'artifact') {
            App._showReviewPage();
            if (typeof Review._showArtifactDetail === 'function') {
                Review._showArtifactDetail(objectId);
            }
        } else if (objectType === 'comment') {
            App._showReviewPage();
        }
    },

    /* ── 工具 ── */

    _formatTime(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        const now = new Date();
        const diff = (now - d) / 1000;
        if (diff < 60) return '刚刚';
        if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
        return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(d);
    },

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    },
};

window.Notification = Notification;