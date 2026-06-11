const Review = {
    currentProjectId: null,
    selectedDocumentId: null,
    selectedDocName: null,
    currentContext: {},
    currentTaskId: null,
    currentMode: null,
    eventSource: null,
    _pollTimer: null,
    _bound: false,
    _stateVersion: 0,
    _reviewHistory: [],       // [{ task_id, mode, status, ... }]
    _reviewDocMap: {},        // { docId_mode: { taskId, status } }
    _reviewTaskMap: {},       // { docId_mode: { taskId, status, mode, documentIds } }
    _docsCache: [],           // cached doc list for filename lookup
    _lastReport: null,
    _isReviewRunning: false,
    _shellState: 'no-result',  // 'no-result' | 'has-result'
    DEFAULT_TEAM_REVIEW_GUIDANCE: [
        '需求范围要写实：明确写清当前需求到底解决什么，不只写背景价值。',
        '能力边界要写全：写清做什么、不做什么、依赖什么前置条件。',
        '权益和分类要结构化：把用户权益、对象分类、场景分类讲清楚。',
        '用户侧命名要可理解：使用用户能理解的名称，避免内部黑话。',
        '多入口文案要统一：不同页面、入口、账号体系下文案要保持一致。',
        '技术方案要分期但不能糊涂：分阶段推进时写清阶段边界、适用范围和当前落点。',
    ],

    MODE_MAP: {
        quick: {
            label: '单篇快速审查',
            steps: ['预处理', '分类', '逐篇分析'],
            skills: ['docx-to-markdown', 'prd-overview-classify', 'prd-per-analysis'],
            defaultTab: 'per-analysis'
        },
        review: {
            label: '需求深度分析',
            steps: ['预处理', '分类', '逐篇分析', '体系Review', '报告生成'],
            skills: ['docx-to-markdown', 'prd-overview-classify', 'prd-per-analysis', 'system-review', 'report-generator'],
            defaultTab: 'system-review'
        },
        insight: {
            label: '挖掘下一阶段需求',
            steps: ['预处理', '分类', '逐篇分析', '体系Review', '需求洞察', '报告生成'],
            skills: ['docx-to-markdown', 'prd-overview-classify', 'prd-per-analysis', 'system-review', 'requirement-insights', 'report-generator'],
            defaultTab: 'insight'
        },
        draft: {
            label: '基于历史生成PRD',
            steps: ['预处理', '分类', '逐篇分析', '体系Review', '需求洞察', 'PRD草稿生成', '报告生成'],
            skills: ['docx-to-markdown', 'prd-overview-classify', 'prd-per-analysis', 'system-review', 'requirement-insights', 'report-generator', 'report-generator'],
            defaultTab: 'draft'
        },
        pm: {
            label: 'PM发展建议',
            steps: ['预处理', '分类', '逐篇分析', '体系Review', '报告生成'],
            skills: ['docx-to-markdown', 'prd-overview-classify', 'prd-per-analysis', 'system-review', 'report-generator'],
            defaultTab: 'pm-assessment'
        },
        full: {
            label: '批量整体评估',
            steps: ['预处理', '分类', '逐篇分析', '体系Review', '需求洞察', '报告生成'],
            skills: ['docx-to-markdown', 'prd-overview-classify', 'prd-per-analysis', 'system-review', 'requirement-insights', 'report-generator'],
            defaultTab: 'overview'
        },
    },

    init() {
        if (!this._bound) {
            this._bindProjectActions();
            this._bindDocActions();
            this._bindResourceActions();
            this._bindContextTabs();
            this._bindActionCards();
            this._bindProgressActions();
            this._bindResultActions();
            this._bindSourcePicker();
            this._bindP4Actions();
            this._bound = true;
        }
        this._showWorkspaceShell();
        this.loadProjects();
        this.loadModels();
        this._syncActionAvailability();
    },

    _setShellState(state) {
        this._shellState = state;
        const shell = document.getElementById('review-shell');
        if (!shell) return;
        shell.classList.remove('no-result', 'has-result');
        shell.classList.add(state);
    },

    destroy() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        if (this._pollTimer) {
            clearTimeout(this._pollTimer);
            this._pollTimer = null;
        }
    },

    _nextStateVersion() {
        this._stateVersion += 1;
        return this._stateVersion;
    },

    _isStaleState(stateVersion) {
        return stateVersion !== this._stateVersion;
    },

    resetState() {
        this.destroy();
        this._nextStateVersion();
        this.currentProjectId = null;
        this.selectedDocumentId = null;
        this.selectedDocName = null;
        this.currentContext = {};
        this.currentTaskId = null;
        this.currentMode = null;
        this._reviewHistory = [];
        this._reviewDocMap = {};
        this._reviewTaskMap = {};
        this._docsCache = [];
        this._lastReport = null;
        this._isReviewRunning = false;
        this._shellState = 'no-result';

        const clear = (id) => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        };
        clear('project-list');
        clear('doc-list');
        clear('historical-doc-list');
        clear('progress-docs');
        clear('result-content');

        const projectName = document.getElementById('workspace-project-name');
        if (projectName) projectName.textContent = '需求审查工作台';
        const docCount = document.getElementById('workspace-doc-count');
        if (docCount) docCount.textContent = '请选择项目和文档';
        this._syncSelectedDocTitle();
        const contextVersion = document.getElementById('context-version');
        if (contextVersion) contextVersion.textContent = '默认';
        this._setContextInputs({});
        this._setResourceControlsEnabled(false);
    },

    _showWorkspaceShell() {
        this._setShellState('no-result');
        document.getElementById('review-empty').style.display = 'none';
        document.getElementById('review-workspace').style.display = '';
        document.getElementById('review-progress').style.display = 'none';
        document.getElementById('review-result').style.display = 'none';
        const hasProject = Boolean(this.currentProjectId);
        document.getElementById('doc-section').style.display = hasProject ? '' : 'none';
        document.getElementById('upload-section').style.display = hasProject ? '' : 'none';
        document.getElementById('workspace-project-name').textContent = hasProject ? '' : '需求审查工作台';
        document.getElementById('workspace-doc-count').textContent = hasProject ? '' : '请选择项目和文档';
        this._syncSelectedDocTitle();
        document.getElementById('context-version').textContent = '默认';
        this.currentContext = {};
        this._renderHistoricalDocs([]);
        this._setContextInputs({});
        this._setResourceControlsEnabled(hasProject);
        if (!hasProject) {
            const docList = document.getElementById('doc-list');
            if (docList) docList.innerHTML = '';
            const resultContent = document.getElementById('result-content');
            if (resultContent) resultContent.innerHTML = '';
        }
    },

    /* ── 模型选择 ── */

    async loadModels() {
        try {
            const models = await API.getModels();
            this._models = models;
            const sel = document.getElementById('review-model-select');
            const enabled = models.filter(m => m.enabled);
            sel.innerHTML = enabled.map(m => `<option value="${m.id}">${m.name}</option>`).join('');
            const statusEl = document.getElementById('review-model-status');
            if (enabled.length) {
                statusEl.textContent = `${enabled.length}个模型可用`;
                statusEl.style.color = 'var(--green-6)';
            } else {
                statusEl.textContent = '无可用模型，请先在管理后台配置';
                statusEl.style.color = 'var(--red-6)';
            }
            this._updateReviewThinkingDropdown();
            sel.addEventListener('change', () => this._updateReviewThinkingDropdown());
        } catch (e) {
            const statusEl = document.getElementById('review-model-status');
            if (statusEl) {
                statusEl.textContent = '模型加载失败';
                statusEl.style.color = 'var(--red-6)';
            }
        }
    },

    _updateReviewThinkingDropdown() {
        const sel = document.getElementById('review-model-select');
        const thinkingSel = document.getElementById('review-thinking-level-select');
        if (!sel || !thinkingSel) return;
        const modelId = sel.value;
        const model = (this._models || []).find(m => m.id === modelId);
        if (model && model.thinking_supported) {
            thinkingSel.style.display = '';
            thinkingSel.value = localStorage.getItem('thinking_level') || 'off';
        } else {
            thinkingSel.style.display = 'none';
            thinkingSel.value = 'off';
        }
        thinkingSel.addEventListener('change', () => {
            localStorage.setItem('thinking_level', thinkingSel.value);
        });
    },

    _getReviewThinkingLevel() {
        const thinkingSel = document.getElementById('review-thinking-level-select');
        if (!thinkingSel || thinkingSel.style.display === 'none') return undefined;
        return thinkingSel.value;
    },

    _getSelectedModelId() {
        const sel = document.getElementById('review-model-select');
        return sel?.value || null;
    },

    /* ── 项目管理 ── */

    async loadProjects() {
        const stateVersion = this._stateVersion;
        const list = document.getElementById('project-list');
        try {
            const projects = await API.getReviewProjects();
            if (this._isStaleState(stateVersion)) return;
            if (!projects.length) {
                list.innerHTML = '<div class="empty-state"><p>暂无项目，点击"新建"开始</p></div>';
                this._syncSelectedDocTitle();
                return;
            }
            list.innerHTML = projects.map(p => `
                <div class="project-item ${p.id === this.currentProjectId ? 'active' : ''}" data-id="${p.id}">
                    <div class="project-item-name">${this._esc(p.name)}</div>
                    <div class="project-item-meta">${p.doc_count || 0}篇文档 · ${p.report_count || 0}份报告</div>
                    <button class="project-delete-btn" data-id="${p.id}" title="删除项目">&times;</button>
                </div>
            `).join('');
            list.querySelectorAll('.project-item').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.classList.contains('project-delete-btn')) return;
                    this.selectProject(parseInt(el.dataset.id));
                });
            });
            list.querySelectorAll('.project-delete-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const id = parseInt(btn.dataset.id);
                    if (!confirm('确定删除该项目及其所有文档和报告？')) return;
                    try {
                        await API.deleteReviewProject(id);
                        if (this.currentProjectId === id) {
                            this.currentProjectId = null;
                            this.selectedDocumentId = null;
                            this.selectedDocName = null;
                            this.currentContext = {};
                            this._showWorkspaceShell();
                            this._syncActionAvailability();
                        }
                        await this.loadProjects();
                    } catch (e) {
                        alert('删除失败: ' + (e.message || ''));
                    }
                });
            });
        } catch (e) {
            if (this._isStaleState(stateVersion)) return;
            list.innerHTML = '<div class="empty-state"><p>加载失败</p></div>';
        }
    },

    async selectProject(id) {
        this.currentProjectId = id;
        this.selectedDocumentId = null;
        this.selectedDocName = null;
        this._syncSelectedDocTitle();
        API.log('info', 'project.select', { project_id: id }, '选择审查项目');
        document.querySelectorAll('.project-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.id) === id);
        });
        document.getElementById('doc-section').style.display = '';
        document.getElementById('upload-section').style.display = '';
        document.getElementById('review-empty').style.display = 'none';
        document.getElementById('review-workspace').style.display = '';
        document.getElementById('review-progress').style.display = 'none';
        document.getElementById('review-result').style.display = 'none';
        this._setShellState('no-result');
        await this.loadProjectDetail(id);
    },

    async loadProjectDetail(id) {
        const stateVersion = this._stateVersion;
        try {
            const project = await API.getReviewProject(id);
            if (this._isStaleState(stateVersion) || this.currentProjectId !== id) return;
            const docs = project.documents || [];
            const requirementDocs = docs.filter(d => (d.document_type || 'requirement') !== 'historical');
            const historicalDocs = docs.filter(d => (d.document_type || 'requirement') === 'historical');
            document.getElementById('workspace-project-name').textContent = project.name;
            document.getElementById('workspace-doc-count').textContent = `${requirementDocs.length} 篇需求 · ${historicalDocs.length} 篇历史`;
            document.getElementById('context-version').textContent = project.context_version ? `V${project.context_version}` : '默认';
            this._renderHistoricalDocs(historicalDocs);
            await this.loadReviewContext(stateVersion, id);
            if (this._isStaleState(stateVersion) || this.currentProjectId !== id) return;
            await this._loadReviewHistory(id, stateVersion);
            if (this._isStaleState(stateVersion) || this.currentProjectId !== id) return;
            // Render doc list AFTER history is loaded so status reflects completed modes
            this._renderDocList(requirementDocs);
            this._setResourceControlsEnabled(true);
            this._syncActionAvailability();
            this._updateActionCardStatus();
        } catch (e) {
            console.error('Failed to load project detail:', e);
        }
    },

    _renderDocList(docs) {
        this._docsCache = docs;
        const list = document.getElementById('doc-list');
        if (this.selectedDocumentId && !docs.some(d => d.id === this.selectedDocumentId)) {
            this.selectedDocumentId = null;
            this.selectedDocName = null;
        }
        if (this.selectedDocumentId) {
            const selectedDoc = docs.find(d => d.id === this.selectedDocumentId);
            this.selectedDocName = selectedDoc ? selectedDoc.filename : this.selectedDocName;
        }
        this._syncSelectedDocTitle();
        if (!docs.length) {
            list.innerHTML = '<div class="empty-state"><p>暂无文档，点击"上传"添加</p></div>';
            this._syncSelectedDocTitle();
            this._syncActionAvailability();
            return;
        }
        list.innerHTML = docs.map(d => {
            const { statusClass, statusLabel } = this._computeDocStatus(d);
            return `
            <div class="doc-item ${d.id === this.selectedDocumentId ? 'selected' : ''}" data-id="${d.id}">
                <svg class="doc-item-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span class="doc-item-name" title="${this._esc(d.filename)}">${this._esc(d.filename)}</span>
                <span class="doc-item-status ${statusClass}">${statusLabel}</span>
                <button class="doc-delete-btn" data-id="${d.id}" title="删除文档">&times;</button>
            </div>
        `}).join('');
        list.querySelectorAll('.doc-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.classList.contains('doc-delete-btn')) return;
                this.selectDocument(parseInt(item.dataset.id));
            });
        });
        list.querySelectorAll('.doc-delete-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const docId = parseInt(btn.dataset.id);
                const doc = this._docsCache.find(d => d.id === docId);
                const docName = doc ? doc.filename : '该文档';
                if (!confirm(`确定删除文档"${docName}"？`)) return;
                try {
                    await API.deleteReviewDoc(this.currentProjectId, docId);
                    if (this.selectedDocumentId === docId) {
                        this.selectedDocumentId = null;
                        this.selectedDocName = null;
                        this._syncSelectedDocTitle();
                        this._syncActionAvailability();
                    }
                    await this.loadProjectDetail(this.currentProjectId);
                } catch (e) {
                    alert('删除失败: ' + (e.message || ''));
                }
            });
        });
    },

    _computeDocStatus(doc) {
        const dbStatus = doc.status || 'uploaded';
        const completedModes = [];
        for (const mode of Object.keys(this.MODE_MAP)) {
            const key = `${doc.id}_${mode}`;
            const entry = this._reviewDocMap[key];
            if (entry) {
                const label = this.MODE_MAP[mode].label;
                completedModes.push(label);
            }
        }
        if (completedModes.length > 0) {
            return { statusClass: 'reviewed', statusLabel: '已审查' + completedModes.length };
        }
        if (dbStatus === 'classified') {
            return { statusClass: 'classified', statusLabel: '已分类' };
        }
        if (dbStatus === 'analysis_failed') {
            return { statusClass: 'failed', statusLabel: '分析失败' };
        }
        const classMap = {
            uploaded: 'uploaded',
            converted: 'converted',
            classified: 'classified',
            analyzed: 'analyzed',
            analysis_failed: 'failed',
            failed: 'failed',
        };
        return { statusClass: classMap[dbStatus] || 'uploaded', statusLabel: this._statusLabel(dbStatus) };
    },

    selectDocument(id) {
        const prevDocId = this.selectedDocumentId;
        this.selectedDocumentId = id;
        const doc = this._docsCache.find(d => d.id === id);
        this.selectedDocName = doc ? doc.filename : '';
        this._syncSelectedDocTitle();
        API.log('info', 'document.select', {
            project_id: this.currentProjectId,
            document_id: id,
            filename: this.selectedDocName,
        }, '选择审查文档');
        document.querySelectorAll('.doc-item').forEach(item => {
            item.classList.toggle('selected', parseInt(item.dataset.id) === id);
        });
        this._syncActionAvailability();
        this._updateActionCardStatus();

        // 切换文档时，刷新当前页面到新文档对应状态
        if (prevDocId !== id) {
            this._navigateOnDocSwitch();
        }
    },

    _syncSelectedDocTitle() {
        const titleEl = document.getElementById('workspace-selected-doc-title');
        if (!titleEl) return;
        if (this.selectedDocName) {
            titleEl.textContent = this.selectedDocName;
            titleEl.title = this.selectedDocName;
            titleEl.classList.remove('is-empty');
        } else {
            titleEl.textContent = this.currentProjectId ? '选择左侧文档后开始审查' : '选择项目和文档后开始审查';
            titleEl.title = '';
            titleEl.classList.add('is-empty');
        }
    },

    _navigateOnDocSwitch() {
        const hasVisibleResult = this._shellState !== 'no-result';

        // 关闭 SSE / 轮询，停止监听旧文档的审查进度
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        this._isReviewRunning = false;

        // 在进度页或结果页：检查新文档在当前模式下是否有历史
        const mode = this.currentMode;
        const docId = this.selectedDocumentId;
        if (!docId) {
            this._showWorkspace();
            return;
        }

        const runningTask = this._findDocModeTask(docId, mode, ['running', 'pending']);
        const reviewed = this._isDocModeReviewed(docId, mode);
        const fallback = this._resolveResultTask(docId, mode);
        const currentResultHasDoc = this._currentResultContainsDocument(docId);
        if (!hasVisibleResult && !fallback?.taskId) {
            return;
        }
        if (!hasVisibleResult) {
            this.currentMode = fallback.mode || this.currentMode;
            this.currentTaskId = fallback.taskId;
            this._syncActionCardSelection(null);
            this._showResult({ activeTab: 'overview' });
            return;
        }
        if (runningTask?.taskId) {
            this.currentTaskId = runningTask.taskId;
            this._syncActionCardSelection(mode);
            this._showResult();
        } else if (reviewed && reviewed.taskId) {
            // 新文档有当前模式的历史结果 → 在结果区更新
            this._syncActionCardSelection(mode);
            this.currentTaskId = reviewed.taskId;
            this._showResult();
        } else if (fallback?.taskId) {
            this.currentMode = fallback.mode || this.currentMode;
            this.currentTaskId = fallback.taskId;
            this._syncActionCardSelection(null);
            this._showResult({ activeTab: 'overview' });
        } else if (currentResultHasDoc) {
            // 当前已加载的是批量/共享结果，直接复用当前任务重新按新文档渲染
            this._showResult();
        } else {
            // 新文档没有当前模式的历史 → 保持三栏，右侧显示上下文空态
            this._showResultEmptyState(mode);
        }
    },

    _currentResultContainsDocument(docId) {
        if (!docId) return false;
        const analyses = this._lastReport?.analyses;
        if (!Array.isArray(analyses) || !analyses.length) return false;
        return analyses.some(a => a.document_id === docId);
    },

    _showWorkspace() {
        this._setShellState('no-result');
        document.getElementById('review-empty').style.display = 'none';
        document.getElementById('review-workspace').style.display = '';
        document.getElementById('review-progress').style.display = 'none';
        document.getElementById('review-result').style.display = 'none';
        this._hideP4Panels();
    },

    _syncActionAvailability() {
        const hasDocument = Boolean(this.selectedDocumentId);
        document.querySelectorAll('.action-card').forEach(card => {
            const mode = card.dataset.mode;
            const needsDoc = mode !== 'full';
            card.disabled = needsDoc && !hasDocument;
            card.classList.toggle('is-disabled', needsDoc && !hasDocument);
        });
    },

    async _loadReviewHistory(projectId, stateVersion = this._stateVersion) {
        this._reviewHistory = [];
        this._reviewDocMap = {};
        this._reviewTaskMap = {};
        try {
            const tasks = await API.listReviews(projectId);
            if (this._isStaleState(stateVersion) || this.currentProjectId !== projectId) return;
            this._reviewHistory = tasks || [];
            (tasks || []).forEach(task => {
                const documentIds = Array.isArray(task.document_ids) ? task.document_ids : [];
                if (documentIds.length !== 1 || task.mode === 'full') return;
                const key = `${documentIds[0]}_${task.mode}`;
                const existing = this._reviewTaskMap[key];
                if (!existing || task.task_id > existing.taskId) {
                    this._reviewTaskMap[key] = {
                        taskId: task.task_id,
                        status: task.status,
                        mode: task.mode,
                        documentIds,
                    };
                }
            });
            const tasksWithResults = (tasks || []).filter(t => ['completed', 'completed_with_warnings', 'cancelled', 'failed'].includes(t.status));
            const analysesResults = await Promise.all(
                tasksWithResults.map(t => API.getReviewAnalyses(projectId, t.task_id).catch(() => []))
            );
            if (this._isStaleState(stateVersion) || this.currentProjectId !== projectId) return;
            const sharedResultModes = new Set(['review', 'insight', 'draft', 'pm']);
            tasksWithResults.forEach((task, i) => {
                if (task.mode === 'full') return;
                if (sharedResultModes.has(task.mode) && task.total_docs !== 1) return;
                const analyses = analysesResults[i] || [];
                analyses.forEach(a => {
                    const key = `${a.document_id}_${task.mode}`;
                    const existing = this._reviewDocMap[key];
                    if (!existing || task.task_id > existing.taskId) {
                        this._reviewDocMap[key] = { taskId: task.task_id, status: task.status };
                    }
                });
            });
            if (this._docsCache.length) {
                this._renderDocList(this._docsCache);
            }
        } catch (e) {
            if (this._isStaleState(stateVersion)) return;
            console.error('加载审查历史失败:', e);
        }
    },

    _isDocModeCompleted(docId, mode) {
        const key = `${docId}_${mode}`;
        return this._reviewDocMap[key] || null;
    },

    _isDocModeReviewed(docId, mode) {
        const entry = this._isDocModeCompleted(docId, mode);
        if (!entry) return null;
        if (entry.status === 'completed_with_warnings') return { ...entry, label: '部分完成' };
        if (entry.status === 'completed') return { ...entry, label: '已完成' };
        if (entry.status === 'cancelled') return { ...entry, label: '已取消' };
        if (entry.status === 'failed') return { ...entry, label: '未完成' };
        return entry;
    },

    _syncActionCardSelection(mode) {
        document.querySelectorAll('.action-card').forEach(card => {
            card.classList.toggle('selected', mode && card.dataset.mode === mode);
        });
    },

    _normalizeTaskInfo(task) {
        if (!task) return null;
        return {
            taskId: task.taskId ?? task.task_id,
            status: task.status,
            mode: task.mode,
            currentStep: task.currentStep ?? task.current_step ?? 0,
            totalDocs: task.totalDocs ?? task.total_docs ?? 0,
            completedDocs: task.completedDocs ?? task.completed_docs ?? 0,
            contextVersion: task.contextVersion ?? task.context_version ?? 1,
            documentIds: Array.isArray(task.documentIds) ? task.documentIds : (Array.isArray(task.document_ids) ? task.document_ids : []),
        };
    },

    _upsertReviewTask(task) {
        const normalized = this._normalizeTaskInfo(task);
        if (!normalized?.taskId) return null;
        const existingIndex = this._reviewHistory.findIndex(item => item.task_id === normalized.taskId);
        const raw = {
            task_id: normalized.taskId,
            status: normalized.status,
            mode: normalized.mode,
            current_step: normalized.currentStep,
            total_docs: normalized.totalDocs,
            completed_docs: normalized.completedDocs,
            context_version: normalized.contextVersion,
            document_ids: normalized.documentIds,
        };
        if (existingIndex >= 0) {
            this._reviewHistory.splice(existingIndex, 1, raw);
        } else {
            this._reviewHistory.unshift(raw);
        }
        if (normalized.documentIds.length === 1 && normalized.mode !== 'full') {
            const key = `${normalized.documentIds[0]}_${normalized.mode}`;
            const existing = this._reviewTaskMap[key];
            if (!existing || normalized.taskId >= existing.taskId) {
                this._reviewTaskMap[key] = normalized;
            }
        }
        return normalized;
    },

    _getTaskInfo(taskId = this.currentTaskId) {
        if (!taskId) return null;
        const task = this._reviewHistory.find(item => item.task_id === taskId);
        return this._normalizeTaskInfo(task);
    },

    _isRunningTask(taskInfo) {
        return ['running', 'pending'].includes(taskInfo?.status);
    },

    _findDocModeTask(docId, mode, statuses = null) {
        if (!docId || !mode) return null;
        const entry = this._reviewTaskMap[`${docId}_${mode}`];
        if (!entry) return null;
        if (Array.isArray(statuses) && statuses.length && !statuses.includes(entry.status)) {
            return null;
        }
        return entry;
    },

    _findLatestTaskForDocument(docId, statuses = null) {
        if (!docId) return null;
        let latest = null;
        for (const mode of Object.keys(this.MODE_MAP)) {
            const entry = this._findDocModeTask(docId, mode, statuses);
            if (!entry?.taskId) continue;
            if (!latest || entry.taskId > latest.taskId) {
                latest = { ...entry, mode };
            }
        }
        return latest;
    },

    _resolveResultTask(docId, preferredMode = this.currentMode) {
        if (!docId) return null;
        if (preferredMode) {
            const running = this._findDocModeTask(docId, preferredMode, ['running', 'pending']);
            if (running?.taskId) {
                return { ...running, mode: preferredMode };
            }
            const preferred = this._isDocModeReviewed(docId, preferredMode);
            if (preferred?.taskId) {
                return { ...preferred, mode: preferredMode };
            }
        }
        return this._findLatestTaskForDocument(docId, ['running', 'pending']) || this._findLatestTaskForDocument(docId);
    },

    _setActiveResultTab(tabName) {
        document.querySelectorAll('.result-tab').forEach(t => t.classList.remove('active'));
        const targetTab = tabName ? document.querySelector(`.result-tab[data-tab="${tabName}"]`) : null;
        if (targetTab) {
            targetTab.classList.add('active');
        } else {
            document.querySelector('.result-tab[data-tab="overview"]')?.classList.add('active');
        }
    },

    _updateActionCardStatus() {
        const docId = this.selectedDocumentId;
        document.querySelectorAll('.action-card').forEach(card => {
            const mode = card.dataset.mode;
            let badge = card.querySelector('.action-card-badge');
            if (!docId || !mode) {
                if (badge) badge.remove();
                return;
            }
            const runningTask = this._findDocModeTask(docId, mode, ['running', 'pending']);
            if (runningTask) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'action-card-badge';
                    card.appendChild(badge);
                }
                badge.textContent = runningTask.status === 'pending' ? '排队中' : '进行中';
                badge.classList.remove('badge-cancelled');
                return;
            }
            const reviewed = this._isDocModeReviewed(docId, mode);
            if (reviewed) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'action-card-badge';
                    card.appendChild(badge);
                }
                badge.textContent = reviewed.label;
                badge.classList.toggle('badge-cancelled', reviewed.status === 'cancelled');
            } else {
                if (badge) badge.remove();
            }
        });
    },

    _statusLabel(s) {
        const m = {
            uploaded: '待处理',
            converted: '已转换',
            classified: '已分类',
            analyzed: '已分析',
            analysis_failed: '分析失败',
            failed: '失败',
        };
        return m[s] || '待处理';
    },

    /* ── 文档上传 ── */

    async uploadDocs(files) {
        if (!this.currentProjectId) return;
        const formData = new FormData();
        for (const f of files) formData.append('files', f);
        try {
            await API.uploadReviewDocs(this.currentProjectId, formData);
            await this.loadProjectDetail(this.currentProjectId);
        } catch (e) {
            alert('上传失败: ' + (e.message || '未知错误'));
        }
    },

    async uploadHistoricalDocs(files) {
        if (!this.currentProjectId) {
            alert('请先选择项目');
            return;
        }
        const formData = new FormData();
        for (const f of files) formData.append('files', f);
        try {
            await API.uploadHistoricalDocs(this.currentProjectId, formData);
            await this.loadProjectDetail(this.currentProjectId);
        } catch (e) {
            alert('导入历史文档失败: ' + (e.message || '未知错误'));
        }
    },

    async loadReviewContext(stateVersion = this._stateVersion, projectId = this.currentProjectId) {
        if (!projectId) return;
        try {
            const ctx = await API.getReviewContext(projectId);
            if (this._isStaleState(stateVersion) || this.currentProjectId !== projectId) return;
            this.currentContext = ctx.context_data || {};
            document.getElementById('context-version').textContent = ctx.version ? `V${ctx.version}` : '默认';
            this._setContextInputs(this.currentContext);
        } catch (e) {
            if (this._isStaleState(stateVersion) || this.currentProjectId !== projectId) return;
            this.currentContext = {};
            this._setContextInputs({});
        }
    },

    _renderHistoricalDocs(docs) {
        const list = document.getElementById('historical-doc-list');
        if (!list) return;
        if (!this.currentProjectId) {
            list.innerHTML = '<div class="resource-empty">选择项目后可导入历史文档</div>';
            return;
        }
        if (!docs.length) {
            list.innerHTML = '<div class="resource-empty">暂无历史文档</div>';
            return;
        }
        list.innerHTML = docs.map(d => `
            <div class="resource-list-item" title="${this._esc(d.filename)}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/></svg>
                <span>${this._esc(d.filename)}</span>
                <button class="hist-doc-del" data-id="${d.id}" title="删除">&times;</button>
            </div>
        `).join('');
        list.querySelectorAll('.hist-doc-del').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const docId = parseInt(btn.dataset.id);
                if (!confirm('确定删除该历史文档？')) return;
                try {
                    await API.deleteReviewDoc(this.currentProjectId, docId);
                    await this.loadProjectDetail(this.currentProjectId);
                } catch (err) {
                    alert('删除失败: ' + (err.message || '未知错误'));
                }
            });
        });
    },

    _setContextInputs(data) {
        const specsEl = document.getElementById('project-specs-input');
        const guidanceEl = document.getElementById('professional-guidance-input');
        const guidance = data.professional_guidance || this.DEFAULT_TEAM_REVIEW_GUIDANCE;
        if (specsEl) specsEl.value = (data.specifications || []).join('\n');
        if (guidanceEl) guidanceEl.value = guidance.join('\n');
    },

    _setResourceControlsEnabled(enabled) {
        const historyInput = document.getElementById('history-upload-input');
        const specsEl = document.getElementById('project-specs-input');
        const guidanceEl = document.getElementById('professional-guidance-input');
        const saveSpecsBtn = document.getElementById('save-specs-btn');
        const saveGuidanceBtn = document.getElementById('save-guidance-btn');
        if (historyInput) historyInput.disabled = !enabled;
        if (specsEl) specsEl.disabled = !enabled;
        if (guidanceEl) guidanceEl.disabled = !enabled;
        if (saveSpecsBtn) saveSpecsBtn.disabled = !enabled;
        if (saveGuidanceBtn) saveGuidanceBtn.disabled = !enabled;
    },

    _linesFromTextarea(id) {
        return (document.getElementById(id)?.value || '')
            .split('\n')
            .map(s => s.trim())
            .filter(Boolean);
    },

    async saveResourceContext(kind) {
        if (!this.currentProjectId) {
            alert('请先选择项目');
            return;
        }
        const payload = { ...this.currentContext };
        if (kind === 'specifications') {
            payload.specifications = this._linesFromTextarea('project-specs-input');
            payload.change_log = '前端更新需求规范';
        } else if (kind === 'professional_guidance') {
            payload.professional_guidance = this._linesFromTextarea('professional-guidance-input');
            payload.change_log = '前端更新团队指导意见';
        }
        try {
            await API.updateReviewContext(this.currentProjectId, payload);
            await this.loadProjectDetail(this.currentProjectId);
        } catch (e) {
            alert('保存失败: ' + (e.message || '未知错误'));
        }
    },

    /* ── 分析模式选择 ── */

    _bindActionCards() {
        document.querySelectorAll('.action-card').forEach(card => {
            card.addEventListener('click', () => {
                const mode = card.dataset.mode;
                if (mode !== 'full' && !this.selectedDocumentId) return;
                this._syncActionCardSelection(mode);
                API.log('info', 'review.mode_click', {
                    project_id: this.currentProjectId,
                    document_id: this.selectedDocumentId,
                    mode,
                }, '点击审查模式');
                this.startReview(mode);
            });
        });
    },

    async startReview(mode) {
        if (this._isReviewRunning) return;
        if (!this.currentProjectId) {
            alert('请先选择项目');
            return;
        }
        // Single-doc modes require document selection; full mode uses all project docs
        const singleDocModes = ['quick', 'review', 'insight', 'draft', 'pm'];
        if (singleDocModes.includes(mode) && !this.selectedDocumentId) {
            alert('请先在左侧选择一篇需求文档');
            return;
        }

        // Check if this doc+mode already has a review (completed or cancelled)
        if (this.selectedDocumentId) {
            const runningTask = this._findDocModeTask(this.selectedDocumentId, mode, ['running', 'pending']);
            if (runningTask) {
                this.currentMode = mode;
                this._syncActionCardSelection(mode);
                this.currentTaskId = runningTask.taskId;
                await this._showResult({ activeTab: (this.MODE_MAP[mode] || this.MODE_MAP.quick).defaultTab, preserveActiveTab: true });
                return;
            }
            const existing = this._isDocModeReviewed(this.selectedDocumentId, mode);
            if (existing) {
                this.currentMode = mode;
                this._syncActionCardSelection(mode);
                this.currentTaskId = existing.taskId;
                API.log('info', 'review.result_open_existing', {
                    project_id: this.currentProjectId,
                    document_id: this.selectedDocumentId,
                    mode,
                    task_id: existing.taskId,
                    status: existing.status,
                }, '打开已有审查结果');
                this._showResult();
                return;
            }
        }

        // No existing result → start new review
        const modelId = this._getSelectedModelId();
        if (!modelId) {
            alert('请先在管理后台配置LLM模型和API Key');
            return;
        }

        this.currentMode = mode;
        this._syncActionCardSelection(mode);
        this._isReviewRunning = true;
        this._updateResultActions();
        try {
            const resp = await API.startReview(this.currentProjectId, {
                mode,
                model_id: modelId,
                document_ids: mode === 'full' ? undefined : [this.selectedDocumentId],
                thinking_level: this._getReviewThinkingLevel(),
            });
            this.currentTaskId = resp.task_id;
            API.log('info', 'review.start.frontend_success', {
                project_id: this.currentProjectId,
                document_id: this.selectedDocumentId,
                mode,
                task_id: resp.task_id,
            }, '启动审查成功');
            this._upsertReviewTask({ ...resp, mode, document_ids: mode === 'full' ? [] : [this.selectedDocumentId] });
            await this._showResult({ activeTab: (this.MODE_MAP[mode] || this.MODE_MAP.quick).defaultTab, preserveActiveTab: true });
            this._listenProgress(resp.task_id);
        } catch (e) {
            this._isReviewRunning = false;
            this._updateResultActions();
            API.log('error', 'review.start.frontend_failed', {
                project_id: this.currentProjectId,
                document_id: this.selectedDocumentId,
                mode,
                error: e.message,
            }, '启动审查失败');
            alert('启动审查失败: ' + (e.message || '未知错误'));
        }
    },

    async reReview() {
        if (this._isReviewRunning) return;
        const modelId = this._getSelectedModelId();
        if (!modelId) {
            alert('请先在管理后台配置LLM模型和API Key');
            return;
        }
        const mode = this.currentMode;
        this._syncActionCardSelection(mode);
        this._isReviewRunning = true;
        this._updateResultActions();
        try {
            const resp = await API.startReview(this.currentProjectId, {
                mode,
                model_id: modelId,
                document_ids: mode === 'full' ? undefined : [this.selectedDocumentId],
                force_reanalysis: true,
                thinking_level: this._getReviewThinkingLevel(),
            });
            this.currentTaskId = resp.task_id;
            API.log('info', 'review.restart.frontend_success', {
                project_id: this.currentProjectId,
                document_id: this.selectedDocumentId,
                mode,
                task_id: resp.task_id,
            }, '重新审查成功');
            this._upsertReviewTask({ ...resp, mode, document_ids: mode === 'full' ? [] : [this.selectedDocumentId] });
            await this._showResult({ activeTab: (this.MODE_MAP[mode] || this.MODE_MAP.quick).defaultTab, preserveActiveTab: true });
            this._listenProgress(resp.task_id);
        } catch (e) {
            this._isReviewRunning = false;
            this._updateResultActions();
            API.log('error', 'review.restart.frontend_failed', {
                project_id: this.currentProjectId,
                document_id: this.selectedDocumentId,
                mode,
                error: e.message,
            }, '重新审查失败');
            alert('启动审查失败: ' + (e.message || '未知错误'));
        }
    },

    /* ── 进度跟踪 ── */

    _showProgress(mode, taskInfo) {
        this._renderEmbeddedProgress(mode, taskInfo);
    },

    _renderEmbeddedProgress(mode, taskInfo = null) {
        const modeConfig = this.MODE_MAP[mode] || this.MODE_MAP.quick;
        const statusText = taskInfo?.status === 'pending' ? '排队中' : '审查进行中';
        document.getElementById('result-content').innerHTML = `
            <div class="embedded-progress">
                <div class="progress-header">
                    <div>
                        <h3 class="progress-title" id="progress-task-title">${modeConfig.label} — ${statusText}</h3>
                        <div class="embedded-progress-hint">任务会在后台持续执行，完成后返回当前标签即可查看结果。</div>
                    </div>
                </div>
                <div class="pipeline-steps" id="pipeline-steps">
                    ${modeConfig.steps.map((name, i) => {
                        const skill = modeConfig.skills?.[i] || '';
                        return `
                            <div class="pipeline-step" data-step="${i}">
                                <div class="step-indicator pending" id="step-ind-${i}">${i + 1}</div>
                                <div class="step-info">
                                    <div class="step-title-row">
                                        <div class="step-name">${name}</div>
                                        <div class="step-skill">${skill}</div>
                                    </div>
                                    <div class="step-detail" id="step-detail-${i}">等待中</div>
                                </div>
                                <div class="step-time" id="step-time-${i}"></div>
                            </div>
                        `;
                    }).join('')}
                </div>
                <div class="progress-docs" id="progress-docs"></div>
            </div>
        `;
    },

    async _listenProgress(taskId) {
        if (this.eventSource) {
            this.eventSource.close();
        }
        if (this._pollTimer) {
            clearTimeout(this._pollTimer);
            this._pollTimer = null;
        }
        try {
            this.eventSource = await API.getReviewProgress(this.currentProjectId, taskId);
            this.eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const current = this._getTaskInfo(taskId) || { taskId, mode: this.currentMode, documentIds: this.selectedDocumentId ? [this.selectedDocumentId] : [] };
                this._upsertReviewTask({ ...current, status: data.task_status, current_step: data.current_step });
                this._updateProgress(data);
                if (['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(data.task_status)) {
                    this.eventSource.close();
                    this.eventSource = null;
                    this.loadProjectDetail(this.currentProjectId);
                    if (taskId === this.currentTaskId) {
                        this._isReviewRunning = false;
                        this._updateResultActions();
                        this._syncResultTitle();
                        this._showResult({ preserveActiveTab: true });
                    }
                }
            };
            this.eventSource.onerror = () => {
                this.eventSource.close();
                this.eventSource = null;
                this._pollProgress(taskId);
            };
        } catch (e) {
            console.error('SSE connection failed, falling back to polling');
            this._pollProgress(taskId);
        }
    },

    async _refreshRunningResult() {
        if (!this.currentTaskId || !this.currentProjectId) return;
        try {
            const report = await API.getReviewReport(this.currentProjectId, this.currentTaskId);
            const aggregated = await this._aggregateDocReports(report);
            this._renderReport(aggregated);
        } catch (e) { /* ignore - will retry next SSE event */ }
    },

    async _pollProgress(taskId) {
        const poll = async () => {
            try {
                const data = await API.getReviewTaskStatus(this.currentProjectId, taskId);
                const current = this._getTaskInfo(taskId) || { taskId, mode: this.currentMode, documentIds: this.selectedDocumentId ? [this.selectedDocumentId] : [] };
                this._upsertReviewTask({ ...current, status: data.task_status, current_step: data.current_step });
                this._updateProgress(data);
                if (['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(data.task_status)) {
                    if (taskId === this.currentTaskId) {
                        this._isReviewRunning = false;
                        this._updateResultActions();
                        this._syncResultTitle();
                        this._showResult({ preserveActiveTab: true });
                    }
                    this.loadProjectDetail(this.currentProjectId);
                    this._pollTimer = null;
                    return;
                }
            } catch (e) { /* ignore */ }
            this._pollTimer = setTimeout(poll, 3000);
        };
        poll();
    },

    _updateProgress(data) {
        if (data.step_statuses) {
            let steps;
            try { steps = typeof data.step_statuses === 'string' ? JSON.parse(data.step_statuses) : data.step_statuses; } catch { steps = {}; }
            Object.entries(steps).forEach(([idx, status]) => {
                const i = parseInt(idx);
                const ind = document.getElementById(`step-ind-${i}`);
                const detail = document.getElementById(`step-detail-${i}`);
                if (!ind) return;
                ind.className = 'step-indicator ' + status;
                if (status === 'completed') {
                    ind.textContent = '\u2713';
                    if (detail) detail.textContent = '已完成';
                } else if (status === 'running') {
                    ind.textContent = i + 1;
                    if (detail) detail.textContent = '处理中...';
                } else if (status === 'failed') {
                    ind.textContent = '\u2717';
                    if (detail) detail.textContent = '失败';
                }
            });
        }
        if (data.step_details) {
            let details;
            try { details = typeof data.step_details === 'string' ? JSON.parse(data.step_details) : data.step_details; } catch { details = {}; }
            Object.entries(details).forEach(([idx, info]) => {
                const i = parseInt(idx);
                const timeEl = document.getElementById(`step-time-${i}`);
                if (timeEl && info.elapsed_seconds) {
                    timeEl.textContent = `${info.elapsed_seconds}s`;
                }
            });
        }
        if (data.doc_progress) {
            const docsEl = document.getElementById('progress-docs');
            if (!docsEl) return;
            docsEl.innerHTML = data.doc_progress.map(d => `
                <div class="progress-doc-item">
                    <span>${this._esc(d.filename || d.title || '')}</span>
                    <span class="doc-item-status ${d.status}">${this._statusLabel(d.status)}</span>
                </div>
            `).join('');
        }
    },

    /* ── 结果展示 ── */

    _showResultForRunning(mode) {
        this._showResult({ activeTab: (this.MODE_MAP[mode] || this.MODE_MAP.quick).defaultTab, preserveActiveTab: true });
    },

    _showResultEmptyState(mode) {
        this._setShellState('has-result');
        // Work panel: keep workspace visible
        document.getElementById('review-empty').style.display = 'none';
        document.getElementById('review-workspace').style.display = '';
        // Result panel: show empty context state
        document.getElementById('review-progress').style.display = 'none';
        document.getElementById('review-result').style.display = '';

        const modeConfig = this.MODE_MAP[mode] || this.MODE_MAP.quick;
    this._setActiveResultTab('overview');

        this._isReviewRunning = false;
        this.currentTaskId = null;
        const titleEl = document.getElementById('result-project-name');
        if (titleEl) titleEl.textContent = `${this.selectedDocName || '文档'} — ${modeConfig.label}`;
        this._updateResultActions();
        document.getElementById('result-content').innerHTML = `
            <div class="empty-state">
                <p style="font-size:var(--fs-15);color:var(--color-text-secondary);margin-bottom:var(--sp-3)">当前文档暂无"${modeConfig.label}"审查结果</p>
                <p style="font-size:var(--fs-13);color:var(--color-text-muted)">点击左侧操作卡片启动审查后，AI 生成的分析会展示在这里。</p>
            </div>`;
        this._hideP4Panels();
    },

    async _showResult(options = {}) {
        const { activeTab = null, preserveActiveTab = false } = options;
        this._setShellState('has-result');
        // Work panel: keep workspace visible
        document.getElementById('review-empty').style.display = 'none';
        document.getElementById('review-workspace').style.display = '';
        // Result panel: show result
        document.getElementById('review-progress').style.display = 'none';
        document.getElementById('review-result').style.display = '';

        // All 6 tabs always visible — auto-activate the default tab for this mode
        const mode = this.currentMode;
        const modeConfig = this.MODE_MAP[mode] || this.MODE_MAP.quick;
        const defaultTab = modeConfig.defaultTab || 'overview';
        if (activeTab) {
            this._setActiveResultTab(activeTab);
        } else if (!preserveActiveTab) {
            this._setActiveResultTab(defaultTab);
        }

        const taskInfo = this._getTaskInfo(this.currentTaskId);
        if (this._isRunningTask(taskInfo)) {
            this._isReviewRunning = true;
            this._syncResultTitle();
            this._updateResultActions();
            this._renderEmbeddedProgress(mode, taskInfo);
            try {
                const data = await API.getReviewTaskStatus(this.currentProjectId, this.currentTaskId);
                this._upsertReviewTask({ ...taskInfo, status: data.task_status, current_step: data.current_step });
                if (['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(data.task_status)) {
                    this._isReviewRunning = false;
                    await this.loadProjectDetail(this.currentProjectId);
                    return this._showResult({ activeTab: document.querySelector('.result-tab.active')?.dataset.tab || activeTab, preserveActiveTab: true });
                }
                this._updateProgress(data);
                this._listenProgress(this.currentTaskId);
            } catch (e) {
                this._listenProgress(this.currentTaskId);
            }
            return;
        }

        this._isReviewRunning = false;
        this._syncResultTitle();
        this._updateResultActions();

        try {
            const currentReport = await API.getReviewReport(this.currentProjectId, this.currentTaskId);
            const aggregated = await this._aggregateDocReports(currentReport);
            this._renderReport(aggregated);
        } catch (e) {
            document.getElementById('result-content').innerHTML = '<div class="empty-state"><p>加载报告失败</p></div>';
        }
        // P4: 结果显示后触发协作审查/产物/评论/讲解准备面板
        this._showP4PanelsAfterResult();
    },

    async _aggregateDocReports(currentReport) {
        const docId = this.selectedDocumentId;
        if (!docId) return currentReport;

        // Find all task IDs for this doc across all modes
        const allModes = Object.keys(this.MODE_MAP);
        const taskIds = new Set();
        for (const m of allModes) {
            const entry = this._isDocModeCompleted(docId, m);
            if (entry && entry.taskId) {
                taskIds.add(entry.taskId);
            }
        }
        // Current task is already loaded
        taskIds.delete(this.currentTaskId);
        if (taskIds.size === 0) return currentReport;

        // Fetch other tasks' reports and merge
        const merged = { ...currentReport };
        merged.pm_assessment =
            this._normalizePmAssessment(merged.pm_assessment) ||
            this._normalizePmAssessment(merged.system_review?.pm_scores) ||
            this._normalizePmAssessment(merged.system_review?.pm_growth);
        const reports = await Promise.all(
            [...taskIds].map(tid => API.getReviewReport(this.currentProjectId, tid).catch(() => null))
        );

        for (const report of reports) {
            if (!report) continue;
            // Merge analyses (dedupe by document_id)
            if (report.analyses?.length && !merged.analyses?.length) {
                merged.analyses = report.analyses;
            }
            // Merge system_review (prefer the one with more data)
            if (report.system_review && !merged.system_review) {
                merged.system_review = report.system_review;
            } else if (report.system_review && merged.system_review) {
                // Fill in missing dimensions
                for (const key of ['business_value', 'architecture', 'competition', 'product_strategy', 'tech_evolution', 'pm_growth', 'action_plan', 'pm_scores', 'insights']) {
                    if (report.system_review[key] && !merged.system_review[key]) {
                        merged.system_review = { ...merged.system_review, [key]: report.system_review[key] };
                    }
                }
            }
            const candidatePm =
                this._normalizePmAssessment(report.pm_assessment) ||
                this._normalizePmAssessment(report.system_review?.pm_scores) ||
                this._normalizePmAssessment(report.system_review?.pm_growth);
            if (candidatePm && !this._normalizePmAssessment(merged.pm_assessment)) {
                merged.pm_assessment = candidatePm;
            }
            // Merge insights
            if (report.insights && !merged.insights) {
                merged.insights = report.insights;
            }
            // Merge prd_draft
            if (report.prd_draft && !merged.prd_draft) {
                merged.prd_draft = report.prd_draft;
            }
            if (report.draft && !merged.draft) {
                merged.draft = report.draft;
            }
        }

        merged.pm_assessment =
            this._normalizePmAssessment(merged.pm_assessment) ||
            this._normalizePmAssessment(merged.system_review?.pm_scores) ||
            this._normalizePmAssessment(merged.system_review?.pm_growth);
        return merged;
    },

    _renderOverview(report) {
        const analyses = report.analyses || [];
        const avgScore = analyses.length ? (analyses.reduce((s, a) => s + (a.quality_score || 0), 0) / analyses.length).toFixed(1) : '-';

        // Spec compliance stats
        const totalViolations = analyses.reduce((s, a) => s + (a.spec_violations?.length || 0), 0);
        const docsWithViolations = analyses.filter(a => a.spec_violations?.length > 0).length;
        const violationRate = analyses.length ? ((docsWithViolations / analyses.length) * 100).toFixed(0) : '0';
        const avgViolationPerDoc = analyses.length ? (totalViolations / analyses.length).toFixed(1) : '0';
        const allViolations = analyses.flatMap(a => (a.spec_violations || []).map(v => ({ doc: a.filename || a.doc_id || '', violation: v })));

        const scoreColor = (score) => {
            if (score === '-') return 'var(--color-brand)';
            const n = parseFloat(score);
            if (n >= 4) return 'var(--green-6)';
            if (n >= 3) return 'var(--blue-6)';
            if (n >= 2) return 'var(--orange-6)';
            return 'var(--red-6)';
        };

        const barColor = (score) => {
            const n = parseFloat(score) || 0;
            if (n >= 4) return 'green';
            if (n >= 3) return 'blue';
            if (n >= 2) return 'orange';
            return 'red';
        };

        return `
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:var(--sp-4);margin-bottom:var(--sp-5)">
                <div class="overview-score-card">
                    <div class="overview-score-number" style="color:var(--blue-6)">${analyses.length}</div>
                    <div class="overview-score-info"><div class="overview-score-title">文档总数</div><div class="overview-score-sub">已上传分析</div></div>
                </div>
                <div class="overview-score-card">
                    <div class="overview-score-number" style="color:var(--blue-6)">${report.categories?.length || 0}</div>
                    <div class="overview-score-info"><div class="overview-score-title">文档分类</div><div class="overview-score-sub">自动归类</div></div>
                </div>
                <div class="overview-score-card">
                    <div class="overview-score-number" style="color:${scoreColor(avgScore)}">${avgScore}</div>
                    <div class="overview-score-info"><div class="overview-score-title">平均评分</div><div class="overview-score-sub">满分 5.0</div></div>
                </div>
                <div class="overview-score-card">
                    <div class="overview-score-number" style="color:${totalViolations > 0 ? 'var(--color-danger)' : 'var(--color-success)'}">${totalViolations}</div>
                    <div class="overview-score-info"><div class="overview-score-title">规范缺失项</div><div class="overview-score-sub">需关注</div></div>
                </div>
                <div class="overview-score-card">
                    <div class="overview-score-number" style="color:${violationRate > 50 ? 'var(--color-danger)' : violationRate > 0 ? 'var(--color-warning)' : 'var(--color-success)'}">${violationRate}%</div>
                    <div class="overview-score-info"><div class="overview-score-title">违规文档占比</div><div class="overview-score-sub">${docsWithViolations} / ${analyses.length} 篇</div></div>
                </div>
            </div>

            ${totalViolations > 0 ? `
            <div class="zone" style="margin-top:var(--sp-5)">
                <div class="zone-header">
                    <span class="zone-header-icon orange"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
                    规范符合性统计
                </div>
                <div class="zone-body">
                    <div class="zone-row"><span class="zone-label">规范缺失总数</span><span class="zone-value" style="color:var(--color-danger);font-weight:var(--fw-semibold)">${totalViolations} 项</span></div>
                    <div class="zone-row"><span class="zone-label">涉及文档数</span><span class="zone-value">${docsWithViolations} / ${analyses.length} 篇 (${violationRate}%)</span></div>
                    <div class="zone-row"><span class="zone-label">平均每篇缺失</span><span class="zone-value">${avgViolationPerDoc} 项</span></div>
                    <div class="zone-row"><span class="zone-label">合规率</span><span class="zone-value"><div class="progress-bar" style="max-width:300px"><div class="progress-bar-fill ${100 - parseInt(violationRate) >= 80 ? 'green' : 100 - parseInt(violationRate) >= 50 ? 'orange' : 'red'}" style="width:${100 - parseInt(violationRate)}%"></div></div><span style="margin-left:var(--sp-2);font-weight:var(--fw-semibold)">${100 - parseInt(violationRate)}%</span></span></div>
                    ${allViolations.length ? `
                    <div style="margin-top:var(--sp-4)">
                        <div style="font-size:var(--fs-13);font-weight:var(--fw-semibold);margin-bottom:var(--sp-3)">缺失项明细</div>
                        ${allViolations.map(v => `
                            <div style="display:flex;align-items:center;gap:var(--sp-3);padding:var(--sp-2) 0;font-size:var(--fs-13)">
                                <span style="color:var(--color-text-muted);min-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${this._esc(v.doc)}</span>
                                <span class="spec-violation">${this._esc(v.violation)}</span>
                            </div>
                        `).join('')}
                    </div>` : ''}
                </div>
            </div>` : `
            <div class="zone" style="margin-top:var(--sp-5)">
                <div class="zone-header">
                    <span class="zone-header-icon green"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></span>
                    规范符合性统计
                </div>
                <div class="zone-body" style="text-align:center;padding:var(--sp-7);color:var(--color-success)">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:var(--sp-2)"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    所有文档均符合规范要求
                </div>
            </div>`}

            ${analyses.length ? `
            <div class="result-section" style="margin-top:var(--sp-5)">
                <h3>逐篇评分概览</h3>
                ${analyses.map(a => {
                    const score = a.quality_score || 0;
                    const pct = (score / 5 * 100).toFixed(0);
                    const clr = barColor(score);
                    return `
                    <div class="doc-score-bar">
                        <span class="doc-score-bar-name">${this._esc(a.filename || a.doc_id || '')}</span>
                        <div class="doc-score-bar-track"><div class="doc-score-bar-fill" style="width:${pct}%;background:var(--${clr === 'green' ? 'green' : clr === 'blue' ? 'blue' : clr === 'orange' ? 'orange' : 'red'}-6)"></div></div>
                        <span class="doc-score-bar-num" style="color:var(--${clr === 'green' ? 'green' : clr === 'blue' ? 'blue' : clr === 'orange' ? 'orange' : 'red'}-6)">${score || '-'}</span>
                    </div>`;
                }).join('')}
            </div>` : ''}
            ${report.system_review ? `
            <div class="result-section">
                <h3>体系Review摘要</h3>
                <p style="font-size:var(--fs-13);color:var(--color-text-secondary);line-height:var(--lh-relaxed)">
                    ${this._esc(report.system_review.action_plan?.summary || '暂无摘要')}
                </p>
            </div>` : ''}
        `;
    },

    _renderPerAnalysis(report) {
        const analyses = report.analyses || [];
        if (!analyses.length) return '<div class="empty-state"><p>暂无逐篇分析结果</p><p style="font-size:var(--fs-12);color:var(--color-text-muted);margin-top:var(--sp-2)">执行任意审查模式后，逐篇分析结果将在此展示</p></div>';

        // Only show the currently selected document's analysis
        const docId = this.selectedDocumentId;
        const filtered = docId ? analyses.filter(a => a.document_id === docId) : analyses;
        if (!filtered.length) return '<div class="empty-state"><p>当前文档无逐篇分析结果</p><p style="font-size:var(--fs-12);color:var(--color-text-muted);margin-top:var(--sp-2)">请对该文档执行审查后查看</p></div>';
        const isSingleDocView = filtered.length === 1;

        return filtered.map((a, i) => {
            const score = a.quality_score || 0;
            const scorePct = (score / 5 * 100).toFixed(0);
            const scoreColor = score >= 4 ? 'green' : score >= 3 ? 'blue' : score >= 2 ? 'orange' : 'red';
            const cardTitle = isSingleDocView ? '分析结果' : (a.filename || a.doc_id || '');
            return `
            <div class="doc-analysis-card ${i > 0 ? 'collapsed' : ''}" data-idx="${i}">
                <div class="doc-analysis-header" onclick="Review.toggleAnalysisCard(${i})">
                    <span class="doc-analysis-toggle">${i > 0 ? '▶' : '▼'}</span>
                    <span class="doc-analysis-title">${this._esc(cardTitle)}</span>
                    <div style="display:flex;align-items:center;gap:var(--sp-3)">
                        <div class="doc-score-bar-track" style="width:60px;height:6px"><div class="doc-score-bar-fill" style="width:${scorePct}%;height:100%;border-radius:3px;background:var(--${scoreColor}-6)"></div></div>
                        <span class="doc-analysis-score" style="color:var(--${scoreColor}-6)">${score || '-'} / 5</span>
                    </div>
                    <span class="doc-analysis-summary">${this._esc(a.core_problem || '-')}</span>
                </div>
                <div class="doc-analysis-body">
                    <div class="analysis-zone">
                        <div class="analysis-zone-header core"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> 核心信息</div>
                        <div class="analysis-zone-body">
                            <div class="analysis-field"><div class="analysis-field-label">核心问题</div><div class="analysis-field-value">${this._esc(a.core_problem || '-')}</div></div>
                            <div style="display:flex;gap:var(--sp-6)">
                                <div class="analysis-field" style="flex:1"><div class="analysis-field-label">分类</div><div class="analysis-field-value">${this._esc(a.category || '-')}</div></div>
                                <div class="analysis-field" style="flex:1"><div class="analysis-field-label">质量评分</div><div class="analysis-field-value"><div style="display:flex;align-items:center;gap:var(--sp-2)"><div class="progress-bar" style="max-width:100px"><div class="progress-bar-fill ${scoreColor}" style="width:${scorePct}%"></div></div><span style="font-weight:var(--fw-semibold);color:var(--${scoreColor}-6)">${score}/5</span></div></div></div>
                            </div>
                        </div>
                    </div>
                    <div class="analysis-zone">
                        <div class="analysis-zone-header boundary"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg> 边界定义</div>
                        <div class="analysis-zone-body">
                            <div style="display:flex;gap:var(--sp-5)">
                                <div class="analysis-field" style="flex:1"><div class="analysis-field-label">做什么（范围内）</div><div class="analysis-field-value">${this._renderBulletList(a.boundary_in)}</div></div>
                                <div class="analysis-field" style="flex:1"><div class="analysis-field-label">不做什么（范围外）</div><div class="analysis-field-value">${this._renderBulletList(a.boundary_out)}</div></div>
                            </div>
                            ${a.boundary_issues?.length ? `<div class="analysis-field" style="margin-top:var(--sp-3)"><div class="analysis-field-label">边界外问题</div><div class="analysis-field-value">${a.boundary_issues.map(b => `<div style="padding:var(--sp-1) 0">• ${this._esc(b.issue || b)}</div>`).join('')}</div></div>` : ''}
                        </div>
                    </div>
                    ${a.spec_violations?.length ? `
                    <div class="analysis-zone">
                        <div class="analysis-zone-header compliance"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> 规范合规</div>
                        <div class="analysis-zone-body">
                            <div class="analysis-field"><div class="analysis-field-label">缺失项（${a.spec_violations.length} 项）</div><div class="analysis-field-value">${a.spec_violations.map(v => `<span class="spec-violation">${this._esc(v)}</span>`).join(' ')}</div></div>
                        </div>
                    </div>` : `
                    <div class="analysis-zone">
                        <div class="analysis-zone-header" style="background:#E8F8EE;color:var(--green-6)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> 规范合规</div>
                        <div class="analysis-zone-body"><div class="analysis-field-value" style="color:var(--green-6)">符合所有规范要求</div></div>
                    </div>`}
                    ${this._renderExpertReview(a.expert_review)}
                </div>
            </div>
        `;}).join('');
    },

    toggleAnalysisCard(idx) {
        const card = document.querySelector(`.doc-analysis-card[data-idx="${idx}"]`);
        if (!card) return;
        const isCollapsed = card.classList.contains('collapsed');
        card.classList.toggle('collapsed');
        const toggle = card.querySelector('.doc-analysis-toggle');
        if (toggle) toggle.textContent = isCollapsed ? '▼' : '▶';
    },

    _expertReviewStatusMeta(status) {
        const normalized = String(status || '').toLowerCase();
        if (normalized === 'pass') return { label: '通过', color: '#1D9A52', bg: '#E8F8EE', border: '#B7E4C7' };
        if (normalized === 'missing') return { label: '缺失', color: '#D9485F', bg: '#FDECEE', border: '#F5C2C7' };
        if (normalized === 'risk') return { label: '有风险', color: '#D9822B', bg: '#FFF4E5', border: '#F5D19B' };
        return { label: status || '未判断', color: '#2F6FDB', bg: '#EEF4FF', border: '#C7D8FF' };
    },

    _renderExpertReview(expertReview) {
        if (!expertReview || typeof expertReview !== 'object') return '';
        const checks = Array.isArray(expertReview.checks) ? expertReview.checks : [];
        return `
                    <div class="analysis-zone">
                        <div class="analysis-zone-header" style="background:#FFF4E5;color:#D9822B"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l2.4 6.8H21l-5.2 4 2 7-5.8-4.3-5.8 4.3 2-7-5.2-4h6.6L12 2z"/></svg> 专家意见评审结论</div>
                        <div class="analysis-zone-body">
                            <div class="analysis-field"><div class="analysis-field-label">整体结论</div><div class="analysis-field-value">${this._esc(expertReview.summary || '-')}</div></div>
                            ${checks.length ? `<div class="analysis-field" style="margin-top:var(--sp-3)"><div class="analysis-field-label">六项规则核查</div><div class="analysis-field-value">${checks.map(check => {
                                const meta = this._expertReviewStatusMeta(check.status);
                                return `<div style="padding:var(--sp-3) 0;border-bottom:1px dashed var(--color-border)">
                                    <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3)">
                                        <strong>${this._esc(check.rule_name || check.rule_key || '未命名规则')}</strong>
                                        <span style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:var(--fs-12);font-weight:var(--fw-semibold);color:${meta.color};background:${meta.bg};border:1px solid ${meta.border}">${this._esc(meta.label)}</span>
                                    </div>
                                    <div style="margin-top:var(--sp-2);color:var(--color-text-secondary)">依据：${this._esc(check.evidence || '文档未体现')}</div>
                                    <div style="margin-top:var(--sp-1)">建议：${this._esc(check.suggestion || '-')}</div>
                                </div>`;
                            }).join('')}</div></div>` : ''}
                        </div>
                    </div>`;
    },

    _renderBulletList(text) {
        if (!text) return '-';
        if (Array.isArray(text)) {
            if (!text.length) return '-';
            return '<ul style="margin:0;padding-left:var(--sp-5);list-style:disc">' + text.map(t => `<li>${this._esc(typeof t === 'object' ? (t.issue || JSON.stringify(t)) : t)}</li>`).join('') + '</ul>';
        }
        // Try JSON.parse for string values that are actually JSON arrays
        const str = String(text);
        if (str.startsWith('[')) {
            try {
                const parsed = JSON.parse(str);
                if (Array.isArray(parsed) && parsed.length) {
                    return '<ul style="margin:0;padding-left:var(--sp-5);list-style:disc">' + parsed.map(t => `<li>${this._esc(typeof t === 'object' ? (t.issue || JSON.stringify(t)) : t)}</li>`).join('') + '</ul>';
                }
            } catch (_) { /* not valid JSON, fall through */ }
        }
        const items = str.split(/[;\n；]/).map(s => s.trim()).filter(Boolean);
        if (items.length <= 1) return this._esc(text);
        return '<ul style="margin:0;padding-left:var(--sp-5);list-style:disc">' + items.map(s => `<li>${this._esc(s)}</li>`).join('') + '</ul>';
    },

    _renderSystemReview(report) {
        const sr = report.system_review;
        if (!sr) return '<div class="empty-state"><p>暂无需求深度分析结果</p><p style="font-size:var(--fs-12);color:var(--color-text-muted);margin-top:var(--sp-2)">执行「需求深度分析」或「批量整体评估」后，6维度分析结果将在此展示</p></div>';

        // Pairs: (left, right) — must align on the same horizontal line
        const pairs = [
            [{ key: 'business_value',  label: '业务价值分析',   icon: '📊' },
             { key: 'competition',     label: '品牌与竞争定位',   icon: '🎯' }],
            [{ key: 'architecture',    label: '需求体系架构',     icon: '🏗' },
             { key: 'product_strategy',label: '产品策略评估',     icon: '🧭' }],
            [{ key: 'tech_evolution',  label: '技术架构演进',     icon: '⚙' },
             { key: 'action_plan',     label: '行动计划与优先级', icon: '📋' }],
        ];

        const hasContent = (d) => {
            const val = sr[d.key];
            if (!val || typeof val !== 'object') return false;
            const realKeys = Object.keys(val).filter(k => !['project_name','output_type','metadata','_schema_valid','dimensions','_schema_valid'].includes(k));
            return realKeys.length > 0;
        };

        const renderBlock = (d) => {
            const content = this._renderDimSections(sr[d.key]);
            return `<div class="sr-dim-block">
                <div class="sr-dim-title">${d.icon} <strong>${this._esc(d.label)}</strong></div>
                <div class="sr-dim-body">${content}</div>
            </div>`;
        };

        let anyVisible = false;
        const rows = pairs.map(([leftD, rightD]) => {
            const leftOk = hasContent(leftD);
            const rightOk = hasContent(rightD);
            if (!leftOk && !rightOk) return '';

            anyVisible = true;
            if (leftOk && rightOk) {
                return `<div class="sr-row">
                    ${renderBlock(leftD)}
                    ${renderBlock(rightD)}
                </div>`;
            }
            // Only one side has content — full width
            const single = leftOk ? leftD : rightD;
            return `<div class="sr-row sr-row-single">${renderBlock(single)}</div>`;
        });

        if (!anyVisible) return '<div class="empty-state"><p>暂无需求深度分析结果</p></div>';
        return `<div class="sr-rows">${rows.join('')}</div>`;
    },

    _renderDimSections(data) {
        if (!data || typeof data !== 'object') return '';
        const SKIP = ['project_name','output_type','metadata','_schema_valid','dimensions'];
        const keys = Object.keys(data).filter(k => !SKIP.includes(k));
        if (!keys.length) return '';

        return keys.map(k => {
            const val = data[k];
            if (val == null || val === '' || (Array.isArray(val) && val.length === 0)) return '';
            const label = this._dimLabel(k);
            const body = this._renderDimValue(val);
            if (!body) return '';
            return `<div class="sr-sub-section"><div class="sr-sub-title">${label}</div>${body}</div>`;
        }).join('');
    },

    _renderDimValue(val) {
        if (val == null) return '';
        if (typeof val === 'string') return `<p class="sr-text">${this._esc(val)}</p>`;
        if (typeof val === 'number') return `<p class="sr-text">${val}</p>`;
        if (Array.isArray(val)) {
            if (!val.length) return '';
            return `<ul class="sr-list">${val.map(item => {
                if (typeof item === 'string') return `<li>${this._esc(item)}</li>`;
                if (typeof item === 'object' && item !== null) return `<li>${this._renderObjItem(item)}</li>`;
                return `<li>${this._esc(String(item))}</li>`;
            }).join('')}</ul>`;
        }
        if (typeof val === 'object') {
            const entries = Object.entries(val).filter(([_,v]) => v != null && v !== '' && (!Array.isArray(v) || v.length > 0));
            if (!entries.length) return '';
            // If entries are all simple scalars, render as key-value rows
            const allSimple = entries.every(([_,v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean');
            if (allSimple) {
                return `<div class="sr-kv-rows">${entries.map(([kk,vv]) => `<div class="sr-kv-row"><span class="sr-kv-key">${this._dimLabel(kk)}</span><span class="sr-kv-val">${this._esc(String(vv))}</span></div>`).join('')}</div>`;
            }
            // Mixed: render each entry as a sub-section
            return entries.map(([kk, vv]) => {
                const body = this._renderDimValue(vv);
                if (!body) return '';
                return `<div class="sr-sub-sub"><div class="sr-sub-sub-title">${this._dimLabel(kk)}</div>${body}</div>`;
            }).join('');
        }
        return '';
    },

    _renderObjItem(obj) {
        const entries = Object.entries(obj).filter(([_,v]) => v != null && v !== '');
        if (entries.length <= 2) {
            return entries.map(([k,v]) => `<span class="sr-item-kv"><b>${this._dimLabel(k)}</b>: ${this._esc(String(v))}</span>`).join('，');
        }
        return entries.map(([k,v]) => `<div class="sr-item-row"><b>${this._dimLabel(k)}</b>: ${this._esc(String(v))}</div>`).join('');
    },

    _dimLabel(key) {
        const map = {
            // Business value
            strategic_value: '战略价值', business_goals: '商业目标', user_insights: '用户洞察',
            user_value: '用户价值', tech_barrier: '技术壁垒', market_scale: '市场规模',
            strategic_synergy: '战略协同', feasibility: '可行性',
            goal: '目标', coverage: '覆盖度', confidence: '置信度', source: '来源',
            insight: '洞察', evidence: '证据',
            // Architecture
            evolution_stages: '演进阶段', category_assessment: '分类评估',
            dependency_issues: '依赖问题', architecture_gaps: '架构缺口',
            stage: '阶段', versions: '涉及版本', core_problems: '核心问题',
            doc_count: '文档数', assessment: '评估', gap: '缺口',
            type: '类型', description: '描述', severity: '严重程度',
            // Competition
            market_landscape: '市场格局', competitor_comparison: '竞品对比', differentiation: '差异化定位',
            position: '市场定位', key_players: '主要玩家', tech_route_difference: '技术路线差异',
            dimension: '对比维度', us: '我方', competitors: '竞品',
            our_position: '我方表现', competitor_position: '竞品表现',
            unique_strengths: '独特优势', weaknesses: '劣势', opportunities: '机会',
            // Product strategy
            current_strategy_assessment: '当前策略评估', recommendations: '改进建议', roadmap: '产品路线图',
            prioritization: '优先级', focus: '聚焦度', consistency: '一致性', phases: '阶段',
            recommendation: '建议', reason: '理由', impact: '影响',
            period: '周期', items: '事项',
            action: '行动', timing: '时间',
            // Tech evolution
            current_architecture: '当前架构', key_metrics: '关键指标', tech_evolution: '技术演进',
            evolution_recommendations: '演进建议',
            pattern: '架构模式', core_decisions: '核心决策',
            name: '指标名称', value: '当前值', target: '目标值', source_doc_index: '来源',
            trends: '趋势', tech_debt: '技术债务', alignment_with_strategy: '战略一致性',
            decision: '决策', rationale: '理由',
            // Action plan
            short_term: '短期（1-3月）', mid_term: '中期（3-6月）', long_term: '长期（6-12月）',
            milestones: '里程碑', risks: '风险',
            time: '时间', measures: '应对措施', probability: '概率',
            // Generic
            score: '评分', summary: '摘要', status: '状态', details: '详情',
            level: '级别', priority: '优先级', deadline: '截止',
            advantage: '优势', disadvantage: '劣势',
        };
        if (map[key]) return map[key];
        return key.replace(/_/g, ' ');
    },

    _renderStructuredContent(data, contextKey) {
        if (data == null) return '';
        if (typeof data === 'string') return `<div class="dim-sub-content"><p>${this._esc(data)}</p></div>`;

        if (Array.isArray(data)) {
            return `<div class="dim-sub-content"><ul style="padding-left:var(--sp-5);margin:0">${data.map(item => {
                if (typeof item === 'string') return `<li>${this._esc(item)}</li>`;
                if (typeof item === 'object' && item !== null) return `<li style="margin-bottom:var(--sp-3)">${this._renderObjectItem(item)}</li>`;
                return `<li>${this._esc(String(item))}</li>`;
            }).join('')}</ul></div>`;
        }

        if (typeof data === 'object') {
            return this._renderObjectSections(data);
        }

        return `<div class="dim-sub-content"><p>${this._esc(String(data))}</p></div>`;
    },

    _renderObjectSections(obj) {
        if (!obj || typeof obj !== 'object') return '';
        return Object.entries(obj).map(([key, value]) => {
            if (value == null) return '';
            const label = this._formatKeyLabel(key);
            if (typeof value === 'string') {
                return `<div class="dim-sub-section"><div class="dim-sub-title">${label}</div><div class="dim-sub-content"><p>${this._esc(value)}</p></div></div>`;
            }
            if (typeof value === 'number') {
                return `<div class="dim-sub-section"><div class="dim-sub-title">${label}</div><div class="dim-sub-content"><p>${value}</p></div></div>`;
            }
            if (Array.isArray(value)) {
                return `<div class="dim-sub-section"><div class="dim-sub-title">${label}</div><div class="dim-sub-content"><ul style="padding-left:var(--sp-5);margin:0">${value.map(item => {
                    if (typeof item === 'string') return `<li>${this._esc(item)}</li>`;
                    if (typeof item === 'object' && item !== null) return `<li style="margin-bottom:var(--sp-3)">${this._renderObjectItem(item)}</li>`;
                    return `<li>${this._esc(String(item))}</li>`;
                }).join('')}</ul></div></div>`;
            }
            if (typeof value === 'object') {
                const hasInnerScalars = Object.values(value).some(v => typeof v === 'string' || typeof v === 'number');
                if (hasInnerScalars) {
                    return `<div class="dim-sub-section"><div class="dim-sub-title">${label}</div><div class="dim-sub-content">${this._renderKeyValueRows(value)}</div></div>`;
                }
                return `<div class="dim-sub-section"><div class="dim-sub-title">${label}</div>${this._renderObjectSections(value)}</div>`;
            }
            return '';
        }).join('');
    },

    _renderKeyValueRows(obj) {
        if (!obj || typeof obj !== 'object') return '';
        return Object.entries(obj).map(([k, v]) => {
            if (v == null) return '';
            const label = this._formatKeyLabel(k);
            if (typeof v === 'string' || typeof v === 'number') {
                const isScore = typeof v === 'number' && v >= 0 && v <= 5 && (k.includes('score') || k.includes('rating'));
                const scoreClass = isScore ? (v >= 4 ? 'high' : v >= 3 ? 'medium' : 'low') : '';
                return `<div class="dim-item-row"><span class="dim-item-label">${label}</span><span class="dim-item-value">${isScore ? `<span class="dim-score-chip ${scoreClass}">${v}/5</span> ` : ''}${this._esc(String(v))}</span></div>`;
            }
            if (typeof v === 'boolean') {
                return `<div class="dim-item-row"><span class="dim-item-label">${label}</span><span class="dim-item-value">${v ? '✅ 是' : '❌ 否'}</span></div>`;
            }
            if (Array.isArray(v)) {
                return `<div class="dim-item-row"><span class="dim-item-label">${label}</span><span class="dim-item-value">${v.map(item => this._esc(String(item))).join('、')}</span></div>`;
            }
            if (typeof v === 'object') {
                return `<div class="dim-item-row"><span class="dim-item-label">${label}</span><span class="dim-item-value">${this._renderObjectItem(v)}</span></div>`;
            }
            return '';
        }).join('');
    },

    _renderObjectItem(obj) {
        if (!obj || typeof obj !== 'object') return this._esc(String(obj));
        const entries = Object.entries(obj).filter(([_, v]) => v != null);
        if (entries.length <= 3) {
            return entries.map(([k, v]) => `<strong>${this._formatKeyLabel(k)}</strong>: ${this._esc(String(v))}`).join('；');
        }
        return entries.map(([k, v]) => `<div style="padding:var(--sp-1) 0"><strong>${this._formatKeyLabel(k)}</strong>: ${this._esc(String(v))}</div>`).join('');
    },

    _formatKeyLabel(key) {
        const map = {
            score: '评分', evidence: '证据', summary: '摘要', recommendation: '建议',
            strengths: '优势', weaknesses: '劣势', risks: '风险', opportunities: '机会',
            highlights: '亮点', blindspots: '盲点', growth_path: '成长路径',
            short_term: '短期', mid_term: '中期', long_term: '长期',
            writing_scores: '写作评分', thinking_scores: '思维评分', pm_type: 'PM类型',
            goals: '目标', metrics: '指标', timeline: '时间线',
            next_steps: '下一步', priority_items: '高优先级',
            user_value: '用户价值', tech_barrier: '技术壁垒', market_scale: '市场规模',
            strategic_synergy: '战略协同', feasibility: '可行性',
            categories: '分类', dependencies: '依赖', evolution_stages: '演进阶段',
            competitors: '竞争对手', market_position: '市场定位',
            strategy: '策略', roadmap: '路线图',
            tech_debt: '技术债务', decisions: '决策',
            action_items: '行动项', milestones: '里程碑',
            label: '标签', name: '名称', description: '描述', type: '类型',
            impact: '影响', urgency: '紧急度', status: '状态',
        };
        if (map[key]) return map[key];
        return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    },

    _parseJsonLikeText(text) {
        if (typeof text !== 'string') return null;
        let cleaned = text.trim();
        if (cleaned.startsWith('```')) {
            const lines = cleaned.split(/\r?\n/);
            if (lines[0]?.startsWith('```')) lines.shift();
            if (lines[lines.length - 1]?.trim() === '```') lines.pop();
            cleaned = lines.join('\n').trim();
        }
        try { return JSON.parse(cleaned); } catch (_) { /* try object slice below */ }
        const start = cleaned.indexOf('{');
        const end = cleaned.lastIndexOf('}');
        if (start !== -1 && end > start) {
            try { return JSON.parse(cleaned.slice(start, end + 1)); } catch (_) { /* ignore */ }
        }
        return null;
    },

    _hasPmContent(value) {
        return Boolean(value && (
            value.writing_scores ||
            value.thinking_scores ||
            value.pm_type ||
            value.highlights?.length ||
            value.blindspots?.length ||
            value.growth_path
        ));
    },

    _unwrapPmAssessment(value) {
        let current = value;
        for (let i = 0; i < 4 && current && !this._hasPmContent(current); i++) {
            if (current.pm_scores) current = current.pm_scores;
            else if (current.pm_assessment) current = current.pm_assessment;
            else if (current.dimensions?.pm_assessment) current = current.dimensions.pm_assessment;
            else if (current.raw_text) current = this._parseJsonLikeText(current.raw_text);
            else break;
        }
        if (current?.raw_text && !this._hasPmContent(current)) {
            const parsed = this._parseJsonLikeText(current.raw_text);
            if (parsed) current = parsed;
        }
        return current;
    },

    _normalizePmAssessment(value) {
        const unwrapped = this._unwrapPmAssessment(value);
        return this._hasPmContent(unwrapped) ? unwrapped : null;
    },

    _renderPmAssessment(report) {
        const pm =
            this._normalizePmAssessment(report.pm_assessment) ||
            this._normalizePmAssessment(report.system_review?.pm_scores) ||
            this._normalizePmAssessment(report.system_review?.pm_growth);
        if (!pm) return '<div class="empty-state"><p>暂无PM发展建议结果</p><p style="font-size:var(--fs-12);color:var(--color-text-muted);margin-top:var(--sp-2)">执行「PM发展建议」后，PM评分结果将在此展示</p></div>';
        const wScores = pm.writing_scores || {};
        const tScores = pm.thinking_scores || {};

        const scoreBarColor = (score) => {
            if (score >= 4) return 'var(--green-6)';
            if (score >= 3) return 'var(--blue-6)';
            if (score >= 2) return 'var(--orange-6)';
            return 'var(--red-6)';
        };

        return `
            ${pm.pm_type ? `
            <div style="display:flex;align-items:center;gap:var(--sp-3);padding:var(--sp-4) var(--sp-6);background:var(--blue-1);border-radius:var(--radius-large);margin-bottom:var(--sp-5)">
                <span class="zone-header-icon blue" style="width:32px;height:32px;font-size:var(--fs-16)">&#x1F464;</span>
                <div><div style="font-size:var(--fs-14);font-weight:var(--fw-semibold);color:var(--blue-6)">PM类型：${this._esc(pm.pm_type)}</div></div>
            </div>` : ''}

            ${Object.keys(wScores).length || Object.keys(tScores).length ? `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-5);margin-bottom:var(--sp-5)">
                <div class="zone">
                    <div class="zone-header"><span class="zone-header-icon blue">&#x270D;</span> 写作风格</div>
                    <div class="zone-body">
                        ${Object.entries(wScores).map(([k, v]) => {
                            const score = v.score || 0;
                            const pct = (score / 5 * 100).toFixed(0);
                            return `
                            <div class="pm-score-bar">
                                <span class="pm-score-bar-label">${this._esc(v.label || k)}</span>
                                <div class="pm-score-bar-track"><div class="pm-score-bar-fill" style="width:${pct}%;background:${scoreBarColor(score)}"></div></div>
                                <span class="pm-score-bar-num" style="color:${scoreBarColor(score)}">${score}</span>
                            </div>`;
                        }).join('')}
                    </div>
                </div>
                <div class="zone">
                    <div class="zone-header"><span class="zone-header-icon purple">&#x1F9E0;</span> 产品思维</div>
                    <div class="zone-body">
                        ${Object.entries(tScores).map(([k, v]) => {
                            const score = v.score || 0;
                            const pct = (score / 5 * 100).toFixed(0);
                            return `
                            <div class="pm-score-bar">
                                <span class="pm-score-bar-label">${this._esc(v.label || k)}</span>
                                <div class="pm-score-bar-track"><div class="pm-score-bar-fill" style="width:${pct}%;background:${scoreBarColor(score)}"></div></div>
                                <span class="pm-score-bar-num" style="color:${scoreBarColor(score)}">${score}</span>
                            </div>`;
                        }).join('')}
                    </div>
                </div>
            </div>` : ''}

            ${pm.highlights?.length ? `
            <div class="result-section" style="margin-bottom:var(--sp-5)">
                <h3>亮点</h3>
                ${pm.highlights.map(h => `
                    <div class="pm-highlight-card">
                        <span class="pm-highlight-icon">&#x2726;</span>
                        <span>${this._esc(h)}</span>
                    </div>
                `).join('')}
            </div>` : ''}

            ${pm.blindspots?.length ? `
            <div class="result-section" style="margin-bottom:var(--sp-5)">
                <h3>盲点</h3>
                ${pm.blindspots.map(b => `
                    <div class="pm-blindspot-card">
                        <span class="pm-blindspot-icon">&#x26A0;</span>
                        <span>${this._esc(b)}</span>
                    </div>
                `).join('')}
            </div>` : ''}

            ${pm.growth_path ? `
            <div class="result-section">
                <h3>成长路径</h3>
                <div class="growth-timeline">
                    ${pm.growth_path.short_term?.length ? `
                    <div class="growth-timeline-item">
                        <div class="growth-timeline-dot"></div>
                        <div class="growth-timeline-period">短期 1-3月</div>
                        <div class="growth-timeline-content">${pm.growth_path.short_term.map(s => this._esc(s)).join('；')}</div>
                    </div>` : ''}
                    ${pm.growth_path.mid_term?.length ? `
                    <div class="growth-timeline-item">
                        <div class="growth-timeline-dot"></div>
                        <div class="growth-timeline-period">中期 3-6月</div>
                        <div class="growth-timeline-content">${pm.growth_path.mid_term.map(s => this._esc(s)).join('；')}</div>
                    </div>` : ''}
                    ${pm.growth_path.long_term?.length ? `
                    <div class="growth-timeline-item">
                        <div class="growth-timeline-dot"></div>
                        <div class="growth-timeline-period">长期 6-12月</div>
                        <div class="growth-timeline-content">${pm.growth_path.long_term.map(s => this._esc(s)).join('；')}</div>
                    </div>` : ''}
                </div>
            </div>` : ''}
        `;
    },

    /* ── 事件绑定 ── */

    _bindProjectActions() {
        document.getElementById('new-project-btn').addEventListener('click', () => {
            this.showNewProjectModal();
        });
    },

    showNewProjectModal() {
        Admin.showModal(`
            <h3>新建审查项目</h3>
            <div class="field">
                <label>项目名称</label>
                <input id="modal-project-name" placeholder="输入项目名称">
            </div>
            <div class="field">
                <label>项目描述</label>
                <input id="modal-project-desc" placeholder="简要描述项目目的">
            </div>
            <div id="new-project-error" class="field-error"></div>
            <div class="btn-row">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Review.createProject()">创建</button>
            </div>
        `);
    },

    async createProject() {
        const errEl = document.getElementById('new-project-error');
        const name = document.getElementById('modal-project-name').value.trim();
        if (!name) { errEl.textContent = '请填写项目名称'; return; }
        try {
            await API.createReviewProject({ name, description: document.getElementById('modal-project-desc').value.trim() || '' });
            Admin.closeModal();
            await this.loadProjects();
        } catch (e) {
            errEl.textContent = '创建失败: ' + (e.message || '');
        }
    },

    _bindDocActions() {
        document.getElementById('doc-upload-input').addEventListener('change', (e) => {
            if (e.target.files.length) {
                this.uploadDocs(e.target.files);
                e.target.value = '';
            }
        });

        const dropZone = document.getElementById('doc-drop-zone');
        dropZone.addEventListener('dragenter', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
        });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            if (files.length) this.uploadDocs(files);
        });

        document.getElementById('edit-context-btn').addEventListener('click', () => {
            if (!this.currentProjectId) return;
            this.showContextEditor();
        });
    },

    _bindResourceActions() {
        document.getElementById('history-upload-input').addEventListener('change', (e) => {
            if (e.target.files.length) {
                this.uploadHistoricalDocs(e.target.files);
                e.target.value = '';
            }
        });

        document.getElementById('save-specs-btn').addEventListener('click', () => {
            this.saveResourceContext('specifications');
        });

        document.getElementById('save-guidance-btn').addEventListener('click', () => {
            this.saveResourceContext('professional_guidance');
        });
    },

    _bindContextTabs() {
        const tabs = document.querySelectorAll('.context-tab');
        const panels = document.querySelectorAll('.review-resource-section');
        if (!tabs.length || !panels.length) return;

        const activateTab = (tabName) => {
            tabs.forEach(tab => {
                tab.classList.toggle('active', tab.dataset.contextTab === tabName);
            });
            panels.forEach(panel => {
                panel.classList.toggle('active', panel.dataset.contextPanel === tabName);
            });
        };

        tabs.forEach(tab => {
            tab.addEventListener('click', () => activateTab(tab.dataset.contextTab));
        });
    },

    async showContextEditor() {
        try {
            const ctx = await API.getReviewContext(this.currentProjectId);
            const data = ctx.context_data || {};
            Admin.showModal(`
                <h3>编辑评审上下文</h3>
                <div class="field">
                    <label>需求规范（每行一条）</label>
                    <textarea id="modal-ctx-specs" rows="4" placeholder="例如: 需求必须包含目标用户">${this._esc((data.specifications || []).join('\n'))}</textarea>
                </div>
                <div class="field">
                    <label>团队指导意见（每行一条）</label>
                    <textarea id="modal-ctx-guidance" rows="4" placeholder="例如: 优先关注跨角色协同边界是否清楚">${this._esc((data.professional_guidance || this.DEFAULT_TEAM_REVIEW_GUIDANCE).join('\n'))}</textarea>
                </div>
                <div class="field">
                    <label>必需章节（每行一条）</label>
                    <textarea id="modal-ctx-sections" rows="4" placeholder="例如: 目标与背景">${this._esc((data.required_sections || []).join('\n'))}</textarea>
                </div>
                <div class="field">
                    <label>评分量表覆盖（JSON格式，key为维度名）</label>
                    <textarea id="modal-ctx-scoring" rows="3" placeholder="例如: {\"完整性\": {\"weight\": 2}}">${this._esc(data.scoring_overrides ? JSON.stringify(data.scoring_overrides, null, 2) : '')}</textarea>
                </div>
                <div class="field">
                    <label>类别覆盖（JSON格式，key为类别名）</label>
                    <textarea id="modal-ctx-category" rows="3" placeholder="例如: {\"新功能\": {\"priority\": \"high\"}}">${this._esc(data.category_overrides ? JSON.stringify(data.category_overrides, null, 2) : '')}</textarea>
                </div>
                <div class="field">
                    <label>变更说明</label>
                    <input id="modal-ctx-log" placeholder="简要说明本次修改原因">
                </div>
                <div id="ctx-edit-error" class="field-error"></div>
                <div class="btn-row">
                    <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                    <button class="btn btn-primary btn-sm" onclick="Review.saveContext()">保存</button>
                </div>
            `);
        } catch (e) {
            alert('加载上下文失败: ' + (e.message || ''));
        }
    },

    async saveContext() {
        const errEl = document.getElementById('ctx-edit-error');
        try {
            const specsRaw = document.getElementById('modal-ctx-specs').value;
            const guidanceRaw = document.getElementById('modal-ctx-guidance').value;
            const sectionsRaw = document.getElementById('modal-ctx-sections').value;
            const scoringRaw = document.getElementById('modal-ctx-scoring').value.trim();
            const categoryRaw = document.getElementById('modal-ctx-category').value.trim();

            let scoring_overrides = undefined;
            if (scoringRaw) {
                try { scoring_overrides = JSON.parse(scoringRaw); } catch { errEl.textContent = '评分量表覆盖 JSON 格式错误'; return; }
            }
            let category_overrides = undefined;
            if (categoryRaw) {
                try { category_overrides = JSON.parse(categoryRaw); } catch { errEl.textContent = '类别覆盖 JSON 格式错误'; return; }
            }

            await API.updateReviewContext(this.currentProjectId, {
                specifications: specsRaw ? specsRaw.split('\n').filter(s => s.trim()) : undefined,
                professional_guidance: guidanceRaw ? guidanceRaw.split('\n').filter(s => s.trim()) : undefined,
                required_sections: sectionsRaw ? sectionsRaw.split('\n').filter(s => s.trim()) : undefined,
                scoring_overrides,
                category_overrides,
                change_log: document.getElementById('modal-ctx-log').value.trim() || '前端编辑',
            });
            Admin.closeModal();
            await this.loadProjectDetail(this.currentProjectId);
        } catch (e) {
            errEl.textContent = '保存失败: ' + (e.message || '');
        }
    },

    _bindProgressActions() {
        const cancelBtn = document.getElementById('cancel-review-btn');
        if (!cancelBtn) return;
        cancelBtn.addEventListener('click', async () => {
            if (!this.currentTaskId || !this.currentProjectId) return;
            if (!confirm('确定要取消审查吗？已完成的步骤会保留，下次可继续审查。')) return;
            try {
                await API.cancelReview(this.currentProjectId, this.currentTaskId);
            } catch (e) { /* ignore */ }
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            this._isReviewRunning = false;
            // Switch to result page with intermediate data
            this._showResult();
            await this.loadProjectDetail(this.currentProjectId);
        });
    },

    _bindResultActions() {
        const TAB_MODE_MAP = {
            'per-analysis': 'quick',
            'system-review': 'review',
            'insight': 'insight',
            'draft': 'draft',
            'pm-assessment': 'pm',
        };
        document.querySelectorAll('.result-tab').forEach(tab => {
            tab.addEventListener('click', async () => {
                if (tab.classList.contains('disabled')) return;
                this._setActiveResultTab(tab.dataset.tab);
                // Sync currentMode to the tab's corresponding review mode
                const tabMode = TAB_MODE_MAP[tab.dataset.tab];
                if (tabMode) {
                    this.currentMode = tabMode;
                    this._syncActionCardSelection(tabMode);
                }
                const runningTask = this._findDocModeTask(this.selectedDocumentId, tabMode, ['running', 'pending']);
                if (runningTask?.taskId && runningTask.taskId !== this.currentTaskId) {
                    this.currentTaskId = runningTask.taskId;
                    await this._showResult({ activeTab: tab.dataset.tab, preserveActiveTab: true });
                    return;
                }
                const targetTask = this._resolveResultTask(this.selectedDocumentId, tabMode);
                if (targetTask?.taskId && targetTask.taskId !== this.currentTaskId) {
                    this.currentTaskId = targetTask.taskId;
                    await this._showResult({ activeTab: tab.dataset.tab, preserveActiveTab: true });
                    return;
                }
                API.log('info', 'result.tab_click', {
                    project_id: this.currentProjectId,
                    document_id: this.selectedDocumentId,
                    task_id: this.currentTaskId,
                    tab: tab.dataset.tab,
                    mode: this.currentMode,
                }, '切换结果标签');
                this._syncResultTitle();
                this._updateResultActions();
                this._renderReport(this._lastReport || {});
            });
        });

        document.getElementById('back-to-workspace-btn').addEventListener('click', () => {
            document.getElementById('review-result').style.display = 'none';
            document.getElementById('review-workspace').style.display = '';
        });

        document.getElementById('re-review-btn').addEventListener('click', () => {
            const btn = document.getElementById('re-review-btn');
            if (btn.dataset.action === 'cancel') {
                this._cancelFromResult();
            } else if (btn.dataset.action === 'start') {
                this.startReview(this.currentMode);
            } else {
                this.reReview();
            }
        });

        document.getElementById('export-md-btn').addEventListener('click', async () => {
            if (!this.currentProjectId || !this.currentTaskId) return;
            try {
                const md = await API.getReviewReportMd(this.currentProjectId, this.currentTaskId);
                const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `review-report-${this.currentTaskId}.md`;
                a.click();
                URL.revokeObjectURL(url);
            } catch (e) {
                alert('导出失败: ' + (e.message || ''));
            }
        });

        // Delegated handler for code block copy buttons and citation links
        document.getElementById('result-content').addEventListener('click', (e) => {
            // P2.C.3: Citation link click — jump to workspace source detail
            const citation = e.target.closest('.review-citation-resolved');
            if (citation) {
                const wsId = citation.dataset.workspaceId;
                const sourceId = citation.dataset.sourceId;
                if (typeof App !== 'undefined') {
                    App._pendingSourceDetail = { wsId, sourceId };
                    App._navigateTo('workspace');
                }
                return;
            }
            const btn = e.target.closest('.code-copy-btn');
            if (!btn) return;
            const code = btn.dataset.code;
            if (!code) return;
            navigator.clipboard.writeText(code).then(() => {
                btn.textContent = '已复制';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.textContent = '复制';
                    btn.classList.remove('copied');
                }, 1500);
            }).catch(() => {
                const ta = document.createElement('textarea');
                ta.value = code;
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                btn.textContent = '已复制';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.textContent = '复制';
                    btn.classList.remove('copied');
                }, 1500);
            });
        });
    },

    _syncResultTitle() {
        const activeTab = document.querySelector('.result-tab.active');
        const tabLabel = activeTab?.textContent || '概览';
        const modeConfig = this.MODE_MAP[this.currentMode] || this.MODE_MAP.quick;
        const docName = this.selectedDocName || '文档';
        const titleEl = document.getElementById('result-project-name');
        if (!titleEl) return;

        const reviewed = this._isDocModeReviewed(this.selectedDocumentId, this.currentMode);
        if (this._isReviewRunning) {
            titleEl.textContent = `${docName} — ${tabLabel}`;
        } else if (reviewed && reviewed.status === 'cancelled') {
            titleEl.textContent = `${docName} — ${tabLabel}（审查未完成）`;
        } else if (reviewed && reviewed.status === 'failed') {
            titleEl.textContent = `${docName} — ${tabLabel}（审查中断）`;
        } else {
            titleEl.textContent = `${docName} — ${tabLabel}`;
        }
    },

    _updateResultActions() {
        const btn = document.getElementById('re-review-btn');
        if (!btn) return;
        const reviewed = this._isDocModeReviewed(this.selectedDocumentId, this.currentMode);

        if (this._isReviewRunning) {
            btn.textContent = '取消审查';
            btn.dataset.action = 'cancel';
            btn.className = 'btn btn-ghost btn-sm';
        } else if (!reviewed) {
            btn.textContent = '开始审查';
            btn.dataset.action = 'start';
            btn.className = 'btn btn-primary btn-sm';
        } else if (reviewed.status === 'cancelled') {
            btn.textContent = '继续审查';
            btn.dataset.action = 're-review';
            btn.className = 'btn btn-outline btn-sm';
        } else {
            btn.textContent = '重新审查';
            btn.dataset.action = 're-review';
            btn.className = 'btn btn-outline btn-sm';
        }
    },

    async _cancelFromResult() {
        if (!this.currentTaskId || !this.currentProjectId) return;
        if (!confirm('确定要取消审查吗？已完成的步骤会保留，下次可继续审查。')) return;
        try {
            await API.cancelReview(this.currentProjectId, this.currentTaskId);
        } catch (e) { /* ignore */ }
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        this._isReviewRunning = false;
        this._updateResultActions();
        this._syncResultTitle();
        // Reload with intermediate results
        try {
            const report = await this._aggregateDocReports(await API.getReviewReport(this.currentProjectId, this.currentTaskId));
            this._renderReport(report);
        } catch (e) { /* ignore */ }
        await this.loadProjectDetail(this.currentProjectId);
    },

    _renderReport(report) {
        this._lastReport = report;
        const contentEl = document.getElementById('result-content');
        const activeTab = document.querySelector('.result-tab.active')?.dataset.tab || 'overview';
        if (activeTab === 'overview') contentEl.innerHTML = this._renderOverview(report);
        else if (activeTab === 'per-analysis') contentEl.innerHTML = this._renderPerAnalysis(report);
        else if (activeTab === 'system-review') contentEl.innerHTML = this._renderSystemReview(report);
        else if (activeTab === 'pm-assessment') contentEl.innerHTML = this._renderPmAssessment(report);
        else if (activeTab === 'insight') contentEl.innerHTML = this._renderInsight(report);
        else if (activeTab === 'draft') contentEl.innerHTML = this._renderDraft(report);
        this._renderMermaidCharts();
        // P2.C.3: 补充引用来源的 title
        this._fillCitationTitlesInReport(contentEl);
    },

    _renderInsight(report) {
        const insights = report.insights || report.system_review?.insights;
        if (!insights) {
            if (!report.system_review) {
                return '<div class="empty-state"><p>暂无需求洞察结果</p><p style="font-size:var(--fs-12);color:var(--color-text-muted);margin-top:var(--sp-2)">执行「挖掘下一阶段需求」或「批量整体评估」后，需求洞察将在此展示</p></div>';
            }
            const nextSteps = report.system_review.action_plan?.next_steps || [];
            const priorityItems = report.system_review.action_plan?.priority_items || [];
            return `
                <div style="padding:var(--sp-5);margin-bottom:var(--sp-4)">
                    <p style="font-size:var(--fs-14);color:var(--color-text-secondary);line-height:var(--lh-relaxed);margin:0">
                        基于体系Review结果，以下为从现有文档中挖掘的下一阶段需求方向
                    </p>
                </div>
                ${nextSteps.length ? `
                <div class="insight-card">
                    <div class="insight-card-icon direction"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg></div>
                    <div class="insight-card-body">
                        <div class="insight-card-title">建议的下一步方向</div>
                        <ul class="insight-card-list">
                            ${nextSteps.map(s => `<li>${this._esc(s)}</li>`).join('')}
                        </ul>
                    </div>
                </div>` : ''}
                ${priorityItems.length ? `
                <div class="insight-card">
                    <div class="insight-card-icon priority"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg></div>
                    <div class="insight-card-body">
                        <div class="insight-card-title">高优先级需求</div>
                        <ul class="insight-card-list">
                            ${priorityItems.map(s => `<li>${this._esc(s)}</li>`).join('')}
                        </ul>
                    </div>
                </div>` : ''}
            `;
        }
        if (typeof insights === 'string') {
            return `<div class="result-section"><h3>需求洞察</h3><div class="md-render">${this._renderMarkdown(insights)}</div></div>`;
        }

        // Dedicated insight renderer: evolution + features + gaps
        const evMatches = (insights.evolution?.matches || []).filter(m => m && typeof m === 'object');
        const featureDims = (insights.features?.feature_dimensions || []).filter(f => f && typeof f === 'object');
        const gapItems = (insights.gap?.gap_assessments || []).filter(g => g && typeof g === 'object');
        const overlapItems = (insights.gap?.overlap_assessments || []).filter(g => g && typeof g === 'object');

        const statusLabel = s => s === 'resolved' ? '已解决' : s === 'partial' ? '部分解决' : '未解决';
        const statusClass = s => s === 'resolved' ? 'resolved' : s === 'partial' ? 'partial' : 'unresolved';
        const issueIcon = s => s === 'resolved' ? '✅' : s === 'partial' ? '🟡' : '🔴';

        let html = '<div class="result-section"><h3>需求洞察</h3>';

        // ── Evolution Tracking ──
        html += '<div class="insight-block"><div class="insight-block-header">📈 演进追踪 — 边界外问题跨版本收敛</div>';
        if (evMatches.length) {
            // Mermaid evolution graph
            const mermaidCode = this._buildEvolutionMermaid(evMatches);
            if (mermaidCode) {
                html += `<div class="mermaid-container"><div class="mermaid-chart"><pre class="mermaid-source">${this._esc(mermaidCode)}</pre></div></div>`;
            }
            html += '<div class="insight-evo-list">';
            for (const m of evMatches) {
                const st = m.status || 'unresolved';
                html += `<div class="insight-evo-item ${statusClass(st)}">
                    <div class="insight-evo-status">${issueIcon(st)} ${statusLabel(st)}</div>
                    <div class="insight-evo-issue">${this._esc(m.issue || '')}</div>
                    ${m.resolved_version ? `<div class="insight-evo-meta">已在 ${this._esc(m.resolved_version)} 中解决</div>` : ''}
                    ${m.resolved_in ? `<div class="insight-evo-meta">解决方案: ${this._esc(m.resolved_in)}</div>` : ''}
                </div>`;
            }
            html += '</div>';
        } else {
            html += '<div class="empty-state"><p>暂无演进追踪结果</p></div>';
        }
        html += '</div>';

        // ── Feature Panorama ──
        html += '<div class="insight-block"><div class="insight-block-header">🗺️ 功能全景 — 文档覆盖的功能维度</div>';
        if (featureDims.length) {
            html += '<div class="insight-feature-grid">';
            for (const f of featureDims) {
                html += `<div class="insight-feature-card">
                    <div class="insight-feature-name">${this._esc(f.name || '未命名')}</div>
                    ${f.description ? `<div class="insight-feature-desc">${this._esc(String(f.description).substring(0, 120))}</div>` : ''}
                    ${f.source_docs && f.source_docs.length ? `<div class="insight-feature-sources">覆盖 ${f.source_docs.length} 篇文档</div>` : ''}
                </div>`;
            }
            html += '</div>';
        } else {
            html += '<div class="empty-state"><p>暂无功能维度数据</p></div>';
        }
        html += '</div>';

        // ── Gaps & Overlaps ──
        html += '<div class="insight-block"><div class="insight-block-header">🔍 缺口与重叠分析</div>';
        if (gapItems.length || overlapItems.length) {
            if (gapItems.length) {
                html += '<div class="insight-sub-title">⚠️ 功能缺口</div><div class="insight-gap-list">';
                for (const g of gapItems) {
                    html += `<div class="insight-gap-item">
                        <div class="insight-gap-name">${this._esc(g.name || g.feature || '未命名缺口')}</div>
                        ${g.description ? `<div class="insight-gap-desc">${this._esc(String(g.description).substring(0, 150))}</div>` : ''}
                        ${g.priority ? `<span class="insight-gap-priority ${(g.priority||'').toLowerCase()}">${this._esc(g.priority)}</span>` : ''}
                    </div>`;
                }
                html += '</div>';
            }
            if (overlapItems.length) {
                html += '<div class="insight-sub-title">🔄 功能重叠</div><div class="insight-gap-list">';
                for (const o of overlapItems) {
                    html += `<div class="insight-gap-item">
                        <div class="insight-gap-name">${this._esc(o.name || o.feature || '未命名重叠')}</div>
                        ${o.description ? `<div class="insight-gap-desc">${this._esc(String(o.description).substring(0, 150))}</div>` : ''}
                    </div>`;
                }
                html += '</div>';
            }
        } else {
            html += '<div class="empty-state"><p>暂未发现显著的功能缺口或重叠</p></div>';
        }
        html += '</div></div>';
        return html;
    },

    _buildEvolutionMermaid(matches) {
        if (!matches || matches.length === 0) return null;
        const lines = ['graph TD'];
        const nodeIds = {};
        let idCounter = 0;
        const safeId = (label) => {
            const id = 'N' + (idCounter++);
            nodeIds[label] = id;
            return id;
        };
        const trunc = (s, max = 30) => {
            s = String(s || '').trim();
            return s.length > max ? s.substring(0, max) + '…' : s;
        };

        for (const m of matches) {
            const issueLabel = trunc(m.issue);
            const issueId = nodeIds[issueLabel] || safeId(issueLabel);
            const status = m.status || 'unresolved';

            if (m.resolved_version && status !== 'unresolved') {
                const verLabel = trunc(m.resolved_version);
                const verId = nodeIds[verLabel] || safeId(verLabel);
                const style = status === 'resolved' ? 'resolved' : 'partial';
                lines.push(`${issueId}["${issueLabel}"] -->|${status === 'resolved' ? '已解决' : '部分解决'}| ${verId}["${verLabel}"]`);
                lines.push(`style ${issueId} fill:#${style === 'resolved' ? 'd4edda' : 'fff3cd'},stroke:#${style === 'resolved' ? '28a745' : 'ffc107'}`);
                lines.push(`style ${verId} fill:#${style === 'resolved' ? 'd4edda' : 'fff3cd'},stroke:#${style === 'resolved' ? '28a745' : 'ffc107'}`);
            } else {
                lines.push(`${issueId}["${issueLabel}"]`);
                lines.push(`style ${issueId} fill:#f8d7da,stroke:#dc3545`);
            }
        }
        return lines.join('\n');
    },

    async _renderMermaidCharts() {
        const charts = Array.from(document.querySelectorAll('.mermaid-chart')).filter(el => this._getMermaidSource(el));
        if (charts.length === 0) return;
        if (!window.mermaid) {
            this._markMermaidChartsFailed(charts, 'Mermaid library not loaded');
            return;
        }
        try {
            mermaid.initialize({ startOnLoad: false, theme: 'base', securityLevel: 'loose', themeVariables: { fontSize: '14px' } });
            for (const el of charts) {
                const rawCode = this._getMermaidSource(el);
                if (!rawCode) continue;
                const code = this._normalizeMermaidCode(rawCode);
                try {
                    await mermaid.parse(code);
                    const id = 'mermaid-' + Math.random().toString(36).substring(2, 8);
                    const { svg } = await mermaid.render(id, code);
                    el.innerHTML = svg;
                    el.removeAttribute('data-mermaid');
                } catch (renderErr) {
                    this._markMermaidChartsFailed([el], renderErr?.message || 'Mermaid render failed');
                }
            }
        } catch (e) {
            console.warn('Mermaid render failed:', e);
            this._markMermaidChartsFailed(charts, e?.message || 'Mermaid render failed');
        }
    },

    _markMermaidChartsFailed(charts, reason = 'Mermaid render failed') {
        const list = Array.from(charts || []);
        if (window.API && typeof window.API.log === 'function') {
            window.API.log('error', 'review.mermaid.render_failed', {
                reason,
                chart_count: list.length,
            }, 'Mermaid 渲染失败');
        }
        for (const el of list) {
            const code = this._getMermaidSource(el);
            if (!code) continue;
            const safeCode = this._esc(code);
            const message = reason === 'Mermaid library not loaded' ? '流程图库加载失败，请刷新页面' : '流程图渲染失败';
            el.innerHTML = `<p class="mermaid-error">${message}</p><details class="mermaid-source-details"><summary>查看源码</summary><pre class="mermaid-source-code">${safeCode}</pre></details>`;
            el.removeAttribute('data-mermaid');
        }
    },

    _getMermaidSource(el) {
        return el.getAttribute('data-mermaid') || el.querySelector('.mermaid-source')?.textContent || '';
    },

    _normalizeMermaidCode(code) {
        return String(code || '')
            .replace(/(^|[\s>|-])([A-Za-z][\w-]*)\[([^"\]\n][^\]\n]*)\]/g, (_, prefix, id, label) => {
                return `${prefix}${id}["${this._escapeMermaidLabel(label)}"]`;
            })
            .replace(/(^|[\s>|-])([A-Za-z][\w-]*)\{([^"{}\n][^{}\n]*)\}/g, (_, prefix, id, label) => {
                return `${prefix}${id}{"${this._escapeMermaidLabel(label)}"}`;
            });
    },

    _escapeMermaidLabel(label) {
        return String(label || '').replace(/"/g, '\\"');
    },

    _renderDraft(report) {
        const draft = report.draft || report.prd_draft;
        if (!draft) {
            return `
                <div class="result-section">
                    <h3>PRD草稿</h3>
                    <div class="empty-state"><p>暂无PRD草稿</p><p style="font-size:var(--fs-12);color:var(--color-text-muted);margin-top:var(--sp-2)">执行「基于历史生成PRD」后，PRD草稿将在此展示</p></div>
                </div>
            `;
        }
        // String: 直接渲染 Markdown
        if (typeof draft === 'string') {
            return `<div class="result-section"><h3>PRD草稿</h3><div class="md-render">${this._renderMarkdown(draft)}</div></div>`;
        }

        // Structured PRD dict
        // 优先用 content/raw_text/markdown 字段，但需要提取纯 PRD 部分
        const MD_KEYS = ['content', 'raw_text', 'prd_markdown', 'markdown'];
        for (const mk of MD_KEYS) {
            if (draft[mk] && typeof draft[mk] === 'string') {
                const prdText = this._extractPrdFromMd(draft[mk]);
                return `<div class="result-section"><h3>PRD草稿</h3><div class="md-render">${this._renderMarkdown(prdText)}</div></div>`;
            }
        }

        // 没有 content/raw_text，按结构化字段渲染
        const SKIP = ['project_name','output_type','metadata','_schema_valid','dimensions','files','summary','role','task','raw_text','content','prd_markdown','markdown'];
        const sections = [
            { key: 'background', title: '项目背景', icon: '📖' },
            { key: 'target_users', title: '目标用户', icon: '👥' },
            { key: 'core_features', title: '核心功能', icon: '⚡' },
            { key: 'feature_details', title: '功能详情', icon: '📋' },
            { key: 'non_functional_requirements', title: '非功能需求', icon: '🔧' },
            { key: 'milestones', title: '里程碑', icon: '🗓' },
            { key: 'risks', title: '风险与应对', icon: '⚠️' },
            { key: 'boundary_gaps_references', title: '边界缺口参考', icon: '🔗' },
        ];

        const renderedKeys = new Set(sections.map(s => s.key));
        const extraKeys = Object.keys(draft).filter(k => !SKIP.includes(k) && !renderedKeys.has(k) && draft[k] != null && draft[k] !== '' && !(typeof draft[k] === 'object' && !Array.isArray(draft[k]) && Object.keys(draft[k]).length === 0));

        // 如果所有结构化字段都为空，也没有 content/raw_text，显示空态
        const hasContent = sections.some(s => draft[s.key] != null && draft[s.key] !== '' && !(typeof draft[s.key] === 'object' && !Array.isArray(draft[s.key]) && Object.keys(draft[s.key]).length === 0)) || extraKeys.length > 0;
        if (!hasContent) {
            return `<div class="result-section"><h3>PRD草稿</h3><div class="empty-state"><p>暂无PRD草稿</p></div></div>`;
        }

        let html = '<div class="result-section"><h3>PRD草稿</h3>';
        const projName = draft.project_name || '';
        if (projName) {
            html += `<div class="prd-header"><h2 class="prd-title">📄 ${this._esc(projName)}</h2></div>`;
        }

        html += '<div class="prd-body">';

        for (const sec of sections) {
            const val = draft[sec.key];
            if (val == null || val === '' || (Array.isArray(val) && val.length === 0) || (typeof val === 'object' && !Array.isArray(val) && Object.keys(val).length === 0)) continue;
            html += `<div class="prd-section"><div class="prd-section-title">${sec.icon} ${this._esc(sec.title)}</div>`;
            html += this._renderDraftValue(val);
            html += '</div>';
        }

        for (const key of extraKeys) {
            const val = draft[key];
            html += `<div class="prd-section"><div class="prd-section-title">📌 ${this._esc(this._dimLabel(key))}</div>`;
            html += this._renderDraftValue(val);
            html += '</div>';
        }

        html += '</div></div>';
        return html;
    },

    _extractPrdFromMd(text) {
        if (!text) return text;
        // 从混合 Markdown 中提取 PRD 草稿专属部分
        const NON_PRD_HEADERS = [
            '文档分类', '逐篇分析', '体系Review', '体系审查',
            'PM发展建议', 'PM评估', '需求洞察', '挖掘下一阶段需求',
            'action-plan', 'product-strategy', 'tech-evolution',
            'architecture', 'competition',
        ];
        const lines = text.split('\n');
        // 找到 PRD 相关标题的起始行
        const PRD_KEYWORDS = ['PRD', 'prd', '产品需求', '草稿', '需求定义', '项目背景', '目标用户', '核心功能'];
        let prdStart = -1;
        for (let i = 0; i < lines.length; i++) {
            const l = lines[i];
            if (l.startsWith('#') || l.startsWith('##')) {
                for (const kw of PRD_KEYWORDS) {
                    if (l.toLowerCase().includes(kw.toLowerCase())) {
                        const isNonPrd = NON_PRD_HEADERS.some(nh => l.includes(nh));
                        if (!isNonPrd) {
                            prdStart = i;
                            break;
                        }
                    }
                }
                if (prdStart >= 0) break;
            }
        }

        if (prdStart >= 0) {
            // 从 prdStart 开始，遇到非 PRD 的 ## 标题时截断
            let prdEnd = lines.length;
            for (let i = prdStart + 1; i < lines.length; i++) {
                const l = lines[i];
                if (l.startsWith('## ') || l.startsWith('# ')) {
                    const isNonPrd = NON_PRD_HEADERS.some(nh => l.includes(nh));
                    if (isNonPrd) {
                        prdEnd = i;
                        break;
                    }
                }
            }
            return lines.slice(prdStart, prdEnd).join('\n').trim();
        }

        // 没有找到 PRD 标题，去掉 LLM preamble
        const preambleEnd = text.indexOf('#');
        if (preambleEnd > 0) {
            const preamble = text.substring(0, preambleEnd);
            if (preamble.includes('作为') || preamble.includes('好的')) {
                return text.slice(preambleEnd).trim();
            }
        }

        return text;
    },

    _renderDraftValue(val) {
        if (val == null) return '';
        if (typeof val === 'string') return `<div class="md-render">${this._renderMarkdown(val)}</div>`;
        if (typeof val === 'number') return `<div class="prd-text">${val}</div>`;
        if (Array.isArray(val)) {
            if (!val.length) return '';
            // Check if items are simple strings
            if (typeof val[0] === 'string') {
                // Strings may contain Markdown — render each as md-render
                return `<ul class="prd-list">${val.map(s => `<li class="md-render">${this._renderMarkdown(s)}</li>`).join('')}</ul>`;
            }
            // Items are objects — render each as a card
            return `<div class="prd-items">${val.map(item => this._renderDraftItem(item)).join('')}</div>`;
        }
        if (typeof val === 'object') {
            return this._renderDraftKvRows(val);
        }
        return '';
    },

    _renderDraftItem(item) {
        if (!item || typeof item !== 'object') return '';
        // Render key-value pairs as rows with labels
        const entries = Object.entries(item).filter(([_,v]) => v != null && v !== '' && (!Array.isArray(v) || v.length > 0));
        if (!entries.length) return '';
        return `<div class="prd-item">${entries.map(([k, v]) => {
            const label = this._dimLabel(k);
            if (typeof v === 'string') {
                return `<div class="prd-item-row"><span class="prd-item-label">${this._esc(label)}</span><span class="prd-item-text md-render">${this._renderMarkdown(v)}</span></div>`;
            }
            if (Array.isArray(v)) {
                const items = v.map(x => typeof x === 'string' ? `<li class="md-render">${this._renderMarkdown(x)}</li>` : `<li>${this._esc(String(x))}</li>`).join('');
                return `<div class="prd-item-row"><span class="prd-item-label">${this._esc(label)}</span><ul class="prd-item-sublist">${items}</ul></div>`;
            }
            return `<div class="prd-item-row"><span class="prd-item-label">${this._esc(label)}</span><span class="prd-item-text">${this._esc(String(v))}</span></div>`;
        }).join('')}</div>`;
    },

    _renderDraftKvRows(obj) {
        const entries = Object.entries(obj).filter(([_,v]) => v != null && v !== '');
        if (!entries.length) return '';
        return entries.map(([k, v]) => {
            const label = this._dimLabel(k);
            const body = this._renderDraftValue(v);
            if (!body) return '';
            return `<div class="prd-kv-block"><div class="prd-kv-label">${this._esc(label)}</div><div class="prd-kv-content">${body}</div></div>`;
        }).join('');
    },

    _renderMarkdown(text) {
        if (!text) return '';
        if (window.marked && window.DOMPurify) {
            return this._renderMarkdownWithLibraries(text);
        }
        return this._renderMarkdownFallback(text);
    },

    _renderMarkdownWithLibraries(text) {
        // P2.C.3/P2.C.4: 替换 [来源ID:x] 引用标记为可点击链接 + 段落标注
        text = this._replaceCitationMarkers(text);

        const renderer = new window.marked.Renderer();
        renderer.code = (code, infostring) => {
            const rawCode = typeof code === 'object' && code !== null ? (code.text || '') : (code || '');
            const rawLang = typeof code === 'object' && code !== null ? (code.lang || '') : (infostring || '');
            const lang = String(rawLang).trim();

            if (lang.toLowerCase() === 'mermaid') {
                return `<div class="mermaid-container"><div class="mermaid-chart"><pre class="mermaid-source">${this._esc(rawCode)}</pre></div></div>`;
            }

            const safeCode = this._esc(rawCode);
            const safeLang = this._esc(lang || 'text');
            const safeLangClass = this._escAttr(lang || 'text');
            const safeCodeAttr = this._escAttr(rawCode);
            return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-lang">${safeLang}</span><button class="code-copy-btn" data-code="${safeCodeAttr}">复制</button></div><pre><code class="language-${safeLangClass}">${safeCode}</code></pre></div>`;
        };
        window.marked.setOptions({
            breaks: true,
            gfm: true,
            renderer,
        });
        return window.DOMPurify.sanitize(window.marked.parse(text), {
            USE_PROFILES: { html: true, svg: true, svgFilters: true },
        });
    },

    _renderMarkdownFallback(text) {
        let html = this._esc(text);
        html = html.replace(/^######\s+(.+)$/gm, '<h6>$1</h6>');
        html = html.replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>');
        html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');
        html = html.replace(/```mermaid\n([\s\S]*?)```/g, (_, code) => {
            return `<div class="mermaid-container"><div class="mermaid-chart"><pre class="mermaid-source">${this._esc(code)}</pre></div></div>`;
        });
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>');
        html = this._wrapListItems(html, /^\*\s+(.+)$/gm, 'ul');
        html = this._wrapListItems(html, /^\d+\.\s+(.+)$/gm, 'ol');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        html = html.replace(/\n/g, '<br>');
        return html;
    },

    _wrapListItems(html, pattern, tag) {
        // Strip 'g' flag — we match one-at-a-time per line, global flag leaks lastIndex across strings
        const flags = pattern.flags.replace('g', '');
        const regex = new RegExp(pattern.source, flags);
        const lines = html.split('\n');
        const result = [];
        let i = 0;
        while (i < lines.length) {
            const m = regex.exec(lines[i]);
            if (m) {
                const items = [`<li>${m[1]}</li>`];
                let j = i + 1;
                while (j < lines.length) {
                    const m2 = regex.exec(lines[j]);
                    if (m2) { items.push(`<li>${m2[1]}</li>`); j++; } else break;
                }
                result.push(`<${tag}>${items.join('')}</${tag}>`);
                i = j;
            } else {
                result.push(lines[i]);
                i++;
            }
        }
        return result.join('\n');
    },

    _escAttr(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    /* ── 工具 ── */

    _esc(s) {
        if (s == null) return '';
        const d = document.createElement('div');
        d.textContent = String(s);
        return d.innerHTML;
    },

    /* ── P2.C.3/P2.C.4: 引用标记替换与段落标注 ── */

    _replaceCitationMarkers(text) {
        if (!text) return text;

        // 替换 [来源ID:x] 为可点击引用链接
        text = text.replace(/\[来源ID:\s*(\d+)\]/g, (match, sourceId) => {
            return `<span class="review-citation" data-source-id="${sourceId}" data-project-id="${this.currentProjectId || ''}">[来源 #${sourceId}]</span>`;
        });

        // P2.C.4: 标注包含引用的段落（仅在当前项目有引用资料时）
        if (this.currentProjectId) {
            const paragraphs = text.split(/\n\n+/);
            const annotated = paragraphs.map(p => {
                if (p.includes('review-citation')) {
                    return `<div class="review-knowledge-based">${p}</div>`;
                }
                return p;  // 审查报告不标注 model-inference，避免过度干扰
            });
            text = annotated.join('\n\n');
        }

        return text;
    },

    async _fillCitationTitlesInReport(contentEl) {
        const citations = contentEl.querySelectorAll('.review-citation');
        if (!citations.length) return;

        const projectId = this.currentProjectId;
        if (!projectId) return;

        try {
            // 获取项目引用的 source 列表
            const refs = await API.listProjectSourceRefs(projectId);
            const sourceIds = (refs || []).map(r => r.source_id);

            if (!sourceIds.length) return;

            // 获取 workspace source 详情以拿到 title
            const ws = await API.getDefaultWorkspace();
            const wsId = ws?.id;
            if (!wsId) return;

            const sources = await API.getWorkspaceSources(wsId);
            const sourceMap = {};
            (sources || []).forEach(s => { sourceMap[s.id] = s; });

            citations.forEach(el => {
                const sourceId = parseInt(el.dataset.sourceId, 10);
                const source = sourceMap[sourceId];
                if (source) {
                    const title = source.title || source.filename || `来源 #${sourceId}`;
                    el.textContent = `[${title}]`;
                    el.title = source.filename || '';
                    el.classList.add('review-citation-resolved');
                    el.dataset.workspaceId = String(wsId);
                    el.dataset.sourceId = String(sourceId);
                }
            });
        } catch (e) {
            console.warn('获取引用来源详情失败:', e);
        }
    },

    /* ── P0.C.4 团队资料选择器 ── */

    _sourcePickerSelected: [],

    _bindSourcePicker() {
        const addBtn = document.getElementById('add-source-ref-btn');
        if (addBtn) {
            addBtn.addEventListener('click', () => this._openSourcePicker());
        }
        const cancelBtn = document.getElementById('source-picker-cancel');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this._closeSourcePicker());
        }
        const confirmBtn = document.getElementById('source-picker-confirm');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => this._confirmSourcePicker());
        }
        const overlay = document.getElementById('source-picker-overlay');
        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) this._closeSourcePicker();
            });
        }
    },

    async _openSourcePicker() {
        if (!this.currentProjectId) {
            App._showToast('请先选择一个审查项目');
            return;
        }
        this._sourcePickerSelected = [];
        const overlay = document.getElementById('source-picker-overlay');
        const listEl = document.getElementById('source-picker-list');
        const countEl = document.getElementById('source-picker-selected-count');
        const confirmBtn = document.getElementById('source-picker-confirm');
        if (!overlay || !listEl) return;

        listEl.innerHTML = '<p style="text-align:center;color:var(--color-text-muted);padding:24px">加载中…</p>';
        overlay.style.display = 'flex';
        if (countEl) countEl.textContent = '已选 0 项';
        if (confirmBtn) confirmBtn.disabled = true;

        try {
            const workspaces = await API.getWorkspaces();
            if (!workspaces || workspaces.length === 0) {
                listEl.innerHTML = '<p style="text-align:center;color:var(--color-text-muted);padding:24px">没有可用的团队空间</p>';
                return;
            }
            const wsId = workspaces[0].id;
            const sources = await API.getWorkspaceSources(wsId);
            if (!sources || sources.length === 0) {
                listEl.innerHTML = '<p style="text-align:center;color:var(--color-text-muted);padding:24px">团队资料库暂无资料，请先在团队空间上传资料</p>';
                return;
            }
            const existingRefs = await API.listProjectSourceRefs(this.currentProjectId).catch(() => []);
            const existingSourceIds = new Set((existingRefs || []).map(r => r.source_id));

            listEl.innerHTML = sources
                .filter(s => s.status === 'active')
                .map(s => {
                    const alreadyLinked = existingSourceIds.has(s.id);
                    const typeLabels = { upload: '文件上传', lark_url: '飞书链接', api: 'API 导入' };
                    return `<div class="source-picker-row${alreadyLinked ? ' source-picker-linked' : ''}" data-source-id="${s.id}" data-source-title="${this._esc(s.title)}">
                        <label style="display:flex;align-items:center;gap:8px;flex:1;cursor:${alreadyLinked ? 'default' : 'pointer'}">
                            ${alreadyLinked ? '<span style="color:var(--green-6);font-size:var(--fs-12)">✓ 已引用</span>' : '<input type="checkbox" class="source-picker-checkbox" data-source-id="${s.id}" />'}
                            <strong>${this._esc(s.title)}</strong>
                            <span style="color:var(--color-text-muted);font-size:var(--fs-12)">${this._esc(s.filename || '')}</span>
                            <span style="color:var(--color-text-muted);font-size:var(--fs-12)">v${s.version}</span>
                            <span style="color:var(--color-text-muted);font-size:var(--fs-12)">${typeLabels[s.source_type] || s.source_type}</span>
                        </label>
                        <select class="source-picker-reftype" data-source-id="${s.id}" style="font-size:var(--fs-12);padding:2px 8px;border:1px solid var(--color-border);border-radius:var(--radius-sm);background:var(--color-bg-white)"${alreadyLinked ? ' disabled' : ''}>
                            <option value="context">上下文</option>
                            <option value="reference">参考资料</option>
                            <option value="background">背景资料</option>
                        </select>
                    </div>`;
                }).join('');

            listEl.querySelectorAll('.source-picker-checkbox').forEach(cb => {
                cb.addEventListener('change', () => this._updateSourcePickerSelection());
            });
        } catch (err) {
            listEl.innerHTML = `<p style="text-align:center;color:var(--red-6);padding:24px">加载失败: ${this._esc(err.message)}</p>`;
        }
    },

    _updateSourcePickerSelection() {
        const checkboxes = document.querySelectorAll('.source-picker-checkbox');
        this._sourcePickerSelected = [];
        checkboxes.forEach(cb => {
            if (cb.checked) {
                const sourceId = parseInt(cb.dataset.sourceId, 10);
                const row = cb.closest('.source-picker-row');
                const refType = row ? row.querySelector('.source-picker-reftype').value : 'context';
                const title = row ? row.dataset.sourceTitle : '';
                this._sourcePickerSelected.push({ source_id: sourceId, ref_type: refType, title });
            }
        });
        const countEl = document.getElementById('source-picker-selected-count');
        const confirmBtn = document.getElementById('source-picker-confirm');
        if (countEl) countEl.textContent = `已选 ${this._sourcePickerSelected.length} 项`;
        if (confirmBtn) confirmBtn.disabled = this._sourcePickerSelected.length === 0;
    },

    _closeSourcePicker() {
        const overlay = document.getElementById('source-picker-overlay');
        if (overlay) overlay.style.display = 'none';
        this._sourcePickerSelected = [];
    },

    async _confirmSourcePicker() {
        if (!this.currentProjectId || this._sourcePickerSelected.length === 0) return;

        const confirmBtn = document.getElementById('source-picker-confirm');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = '引用中…';
        }

        let success = 0;
        let failed = 0;
        for (const item of this._sourcePickerSelected) {
            try {
                await API.addProjectSourceRef(this.currentProjectId, {
                    source_id: item.source_id,
                    ref_type: item.ref_type,
                });
                success++;
            } catch (err) {
                console.error('引用资料失败:', item.title, err);
                failed++;
            }
        }

        this._closeSourcePicker();
        if (confirmBtn) {
            confirmBtn.textContent = '确认引用';
            confirmBtn.disabled = true;
        }

        if (success > 0) {
            App._showToast(`成功引用 ${success} 份资料${failed > 0 ? `，${failed} 份失败` : ''}`);
        } else {
            App._showToast('引用资料失败');
        }
    },

    /* ═══════════════════════════════════════════
       P4: 协作审查 + 产物 + 评论 + 讲解准备
       ═══════════════════════════════════════════ */

    _currentCommentObjectType: null,
    _currentCommentObjectId: null,
    _presentationConvId: null,

    _bindP4Actions() {
        // P4.B.5: 讲解准备按钮
        const prepBtn = document.getElementById('prepare-presentation-btn');
        if (prepBtn) {
            prepBtn.addEventListener('click', () => this._startPresentation());
        }
        // P4.B.2: 创建物料按钮
        const createArtifactBtn = document.getElementById('create-artifact-btn');
        if (createArtifactBtn) {
            createArtifactBtn.addEventListener('click', () => this._showCreateArtifactDialog());
        }
        // P4.A.4: 发起协作审查按钮
        const collabBtn = document.getElementById('initiate-collab-btn');
        if (collabBtn) {
            collabBtn.addEventListener('click', () => this._showInitiateCollabDialog());
        }
        // P4.D.6: 评论提交按钮
        const commentSubmitBtn = document.getElementById('comment-submit-btn');
        if (commentSubmitBtn) {
            commentSubmitBtn.addEventListener('click', () => this._submitComment());
        }
    },

    /* ── P4.B.5: 讲解准备 ── */

    _startPresentation() {
        if (!this.currentProjectId) {
            App._showToast('请先选择项目');
            return;
        }
        // 切换到对话页，创建 presentation 模式对话
        const projectId = this.currentProjectId;
        const docId = this.selectedDocumentId;
        const mode = 'presentation';
        // 通过 Chat 模块创建对话
        App._showUserPage();
        setTimeout(() => {
            if (typeof Chat !== 'undefined' && Chat.createConversationWithMode) {
                Chat.createConversationWithMode(mode, projectId);
            } else {
                // fallback: 直接创建对话
                Chat._newChat();
                App._showToast('已进入讲解准备模式，在对话中迭代优化物料');
            }
        }, 300);
        API.log('info', 'presentation.start', { project_id: projectId, document_id: docId }, '开始讲解准备');
    },

    /* ── P4.B.2: 产物管理 ── */

    async _loadArtifacts(objectType, objectId) {
        try {
            const artifacts = await API.listArtifacts(objectType, objectId);
            this._renderArtifactCards(artifacts);
            const section = document.getElementById('review-artifact-section');
            if (section) section.style.display = artifacts.length > 0 ? '' : 'none';
        } catch (e) {
            console.warn('加载产物失败:', e);
        }
    },

    _renderArtifactCards(artifacts) {
        const list = document.getElementById('review-artifact-list');
        if (!list) return;
        if (!artifacts.length) {
            list.innerHTML = '<div class="empty-state"><p>暂无讲解物料</p></div>';
            return;
        }
        const typeLabels = {
            explanation_json: '讲解稿',
            mermaid_diagram: '流程图',
            html_presentation: 'HTML 展示',
            svg_summary: 'SVG 概要',
            meeting_pack: '会议材料包',
        };
        const typeIcons = {
            explanation_json: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/></svg>',
            mermaid_diagram: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
            html_presentation: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
            svg_summary: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
            meeting_pack: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
        };
        list.innerHTML = artifacts.map(a => {
            const label = typeLabels[a.artifact_type] || a.artifact_type;
            const icon = typeIcons[a.artifact_type] || typeIcons.explanation_json;
            const statusCls = a.status === 'confirmed' ? 'confirmed' : 'draft';
            const statusLabel = a.status === 'confirmed' ? '已确认' : '草稿';
            const confirmBtn = a.status === 'draft'
                ? `<button class="btn btn-primary btn-xs" data-artifact-action="confirm" data-artifact-id="${a.id}">确认物料</button>`
                : `<button class="btn btn-ghost btn-xs" data-artifact-action="unconfirm" data-artifact-id="${a.id}">取消确认</button>`;
            return `
                <div class="artifact-card" data-artifact-id="${a.id}">
                    <div class="artifact-card-icon">${icon}</div>
                    <div class="artifact-card-info">
                        <div class="artifact-card-type">${this._esc(label)}</div>
                        <div class="artifact-card-status ${statusCls}">${statusLabel}</div>
                    </div>
                    <div class="artifact-card-actions">
                        ${confirmBtn}
                        <button class="btn btn-ghost btn-xs" data-artifact-action="view" data-artifact-id="${a.id}">查看</button>
                    </div>
                </div>
            `;
        }).join('');
        list.querySelectorAll('[data-artifact-action]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const action = btn.dataset.artifactAction;
                const id = parseInt(btn.dataset.artifactId);
                try {
                    if (action === 'confirm') {
                        await API.confirmArtifact(id);
                        App._showToast('物料已确认');
                        this._loadArtifacts(this._currentCommentObjectType, this._currentCommentObjectId);
                    } else if (action === 'unconfirm') {
                        await API.unconfirmArtifact(id);
                        App._showToast('已取消确认，物料回到草稿状态');
                        this._loadArtifacts(this._currentCommentObjectType, this._currentCommentObjectId);
                    } else if (action === 'view') {
                        const artifact = await API.getArtifact(id);
                        this._showArtifactContent(artifact);
                    }
                } catch (e) {
                    App._showToast('操作失败: ' + (e.message || ''));
                }
            });
        });
    },

    _showArtifactContent(artifact) {
        Admin.showModal(`
            <h3>物料详情: ${this._esc(artifact.artifact_type)}</h3>
            <div style="margin-top:12px;max-height:400px;overflow-y:auto">
                <pre style="background:var(--gray-1);padding:12px;border-radius:8px;font-size:13px;overflow-x:auto">${this._esc(artifact.content_json || '')}</pre>
            </div>
            <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">关闭</button>
            </div>
        `);
    },

    _showCreateArtifactDialog() {
        if (!this.currentProjectId) {
            App._showToast('请先选择项目');
            return;
        }
        Admin.showModal(`
            <h3>创建讲解物料</h3>
            <div class="field">
                <label style="font-size:13px;font-weight:600;margin-bottom:4px;display:block">物料类型</label>
                <select id="artifact-type-input" style="width:100%;height:36px;padding:0 12px;border:1px solid var(--color-border);border-radius:8px;font-size:14px">
                    <option value="explanation_json">讲解稿</option>
                    <option value="mermaid_diagram">流程图</option>
                    <option value="html_presentation">HTML 展示</option>
                    <option value="svg_summary">SVG 概要</option>
                </select>
            </div>
            <div class="field" style="margin-top:12px">
                <label style="font-size:13px;font-weight:600;margin-bottom:4px;display:block">内容 (JSON)</label>
                <textarea id="artifact-content-input" rows="6" style="width:100%;padding:12px;border:1px solid var(--color-border);border-radius:8px;font-size:13px" placeholder='{"title": "讲解稿", "sections": []}'></textarea>
            </div>
            <div id="artifact-create-error" class="field-error"></div>
            <div class="btn-row" style="margin-top:16px">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Review._createArtifactSubmit()">创建</button>
            </div>
        `);
    },

    async _createArtifactSubmit() {
        const type = document.getElementById('artifact-type-input').value;
        const content = document.getElementById('artifact-content-input').value;
        const errEl = document.getElementById('artifact-create-error');
        if (!content.trim()) {
            errEl.textContent = '请输入内容';
            return;
        }
        try {
            await API.createArtifact({
                object_type: this._currentCommentObjectType || 'review_request',
                object_id: this._currentCommentObjectId || 0,
                artifact_type: type,
                content_json: content,
            });
            Admin.closeModal();
            App._showToast('物料创建成功');
            this._loadArtifacts(this._currentCommentObjectType, this._currentCommentObjectId);
        } catch (e) {
            errEl.textContent = e.message || '创建失败';
        }
    },

    /* ── P4.A.4: 协作审查 ── */

    async _loadCollabRequests(projectId) {
        try {
            const requests = await API.listReviewRequests(projectId);
            this._renderCollabCards(requests);
            const section = document.getElementById('review-collab-section');
            if (section) section.style.display = requests.length > 0 ? '' : 'none';
        } catch (e) {
            console.warn('加载协作审查失败:', e);
        }
    },

    _renderCollabCards(requests) {
        const list = document.getElementById('review-collab-list');
        if (!list) return;
        if (!requests.length) {
            list.innerHTML = '<div class="empty-state"><p>暂无协作审查请求</p></div>';
            return;
        }
        const statusLabels = {
            pending_approval: '待审批',
            approved: '已通过',
            rejected: '已驳回',
            cancelled: '已取消',
        };
        list.innerHTML = requests.map(r => {
            const statusLabel = statusLabels[r.status] || r.status;
            const actionsHtml = r.status === 'rejected'
                ? `<button class="btn btn-outline btn-xs" data-collab-action="resubmit" data-collab-id="${r.id}">重新提交</button>`
                : '';
            return `
                <div class="collab-request-card" data-collab-id="${r.id}">
                    <div class="collab-request-info">
                        <div class="collab-request-goal">${this._esc(r.goal || '协作审查')}</div>
                        <div class="collab-request-status ${r.status}">${statusLabel} · 第 ${r.current_round} 轮</div>
                    </div>
                    <div class="collab-request-actions">
                        ${actionsHtml}
                        <button class="btn btn-ghost btn-xs" data-collab-action="detail" data-collab-id="${r.id}">详情</button>
                    </div>
                </div>
            `;
        }).join('');
        list.querySelectorAll('[data-collab-action]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const action = btn.dataset.collabAction;
                const id = parseInt(btn.dataset.collabId);
                try {
                    if (action === 'resubmit') {
                        const result = await API.resubmitReviewRequest(id);
                        App._showToast('已重新提交，进入第 ' + result.current_round + ' 轮');
                        this._loadCollabRequests(this.currentProjectId);
                    } else if (action === 'detail') {
                        this._showCollabDetail(id);
                    }
                } catch (e) {
                    App._showToast('操作失败: ' + (e.message || ''));
                }
            });
        });
    },

    _showCollabDetail(requestId) {
        API.getReviewRequest(requestId).then(req => {
            API.listReviewRounds(requestId).then(rounds => {
                API.listReviewParticipants(requestId).then(participants => {
                    const roundsHtml = (rounds || []).map(r => `
                        <div style="padding:8px 12px;background:var(--gray-1);border-radius:8px;margin-bottom:6px">
                            <span style="font-weight:600">第 ${r.round_no} 轮</span>
                            <span style="color:var(--color-text-muted);font-size:12px;margin-left:8px">${r.decision || '待决策'}</span>
                            ${r.decision_comment ? `<span style="font-size:12px;color:var(--color-text-secondary);margin-left:8px">${this._esc(r.decision_comment)}</span>` : ''}
                        </div>
                    `).join('');
                    const participantsHtml = (participants || []).map(p => `
                        <span style="display:inline-flex;padding:2px 8px;border-radius:12px;background:var(--gray-2);font-size:12px;margin-right:4px">${p.role} #${p.user_id}</span>
                    `).join('');
                    Admin.showModal(`
                        <h3>协作审查详情</h3>
                        <div style="margin-top:12px">
                            <p style="font-size:13px"><strong>目标:</strong> ${this._esc(req.goal || '')}</p>
                            <p style="font-size:13px;margin-top:4px"><strong>状态:</strong> ${req.status} · 第 ${req.current_round} 轮</p>
                        </div>
                        <div style="margin-top:16px">
                            <h4 style="font-size:14px;font-weight:600">参与者</h4>
                            <div style="margin-top:6px">${participantsHtml || '<span style="color:var(--color-text-muted)">暂无</span>'}</div>
                        </div>
                        <div style="margin-top:16px">
                            <h4 style="font-size:14px;font-weight:600">审查轮次</h4>
                            <div style="margin-top:6px">${roundsHtml || '<span style="color:var(--color-text-muted)">暂无轮次</span>'}</div>
                        </div>
                        <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
                            <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">关闭</button>
                        </div>
                    `);
                });
            });
        }).catch(e => App._showToast('加载失败: ' + (e.message || '')));
    },

    _showInitiateCollabDialog() {
        if (!this.currentProjectId) {
            App._showToast('请先选择项目');
            return;
        }
        Admin.showModal(`
            <h3>发起协作审查</h3>
            <div class="field">
                <label style="font-size:13px;font-weight:600;margin-bottom:4px;display:block">审查目标</label>
                <input id="collab-goal-input" type="text" style="width:100%;height:36px;padding:0 12px;border:1px solid var(--color-border);border-radius:8px;font-size:14px" placeholder="请输入本次协作审查的目标">
            </div>
            <div id="collab-create-error" class="field-error"></div>
            <div class="btn-row" style="margin-top:16px">
                <button class="btn btn-ghost btn-sm" onclick="Admin.closeModal()">取消</button>
                <button class="btn btn-primary btn-sm" onclick="Review._createCollabSubmit()">发起</button>
            </div>
        `);
    },

    async _createCollabSubmit() {
        const goal = document.getElementById('collab-goal-input').value.trim();
        const errEl = document.getElementById('collab-create-error');
        if (!goal) {
            errEl.textContent = '请输入审查目标';
            return;
        }
        try {
            await API.createReviewRequest({
                project_id: this.currentProjectId,
                goal,
            });
            Admin.closeModal();
            App._showToast('协作审查已发起');
            this._loadCollabRequests(this.currentProjectId);
        } catch (e) {
            errEl.textContent = e.message || '发起失败';
        }
    },

    _showCollabRequest(requestId) {
        this._showCollabDetail(requestId);
    },

    _showArtifactDetail(artifactId) {
        API.getArtifact(artifactId).then(artifact => {
            this._showArtifactContent(artifact);
        }).catch(e => App._showToast('加载物料失败: ' + (e.message || '')));
    },

    /* ── P4.D.6: 评论组件 ── */

    async _loadComments(objectType, objectId) {
        this._currentCommentObjectType = objectType;
        this._currentCommentObjectId = objectId;
        try {
            const comments = await API.listComments(objectType, objectId);
            this._renderComments(comments);
            const section = document.getElementById('review-comment-section');
            if (section) section.style.display = '';
            const countEl = document.getElementById('comment-count');
            if (countEl) countEl.textContent = `${comments.length} 条`;
        } catch (e) {
            console.warn('加载评论失败:', e);
        }
    },

    _renderComments(comments) {
        const list = document.getElementById('comment-list');
        if (!list) return;
        if (!comments.length) {
            list.innerHTML = '<div class="empty-state"><p>暂无评论</p></div>';
            return;
        }
        // 分组顶级评论和回复
        const topLevel = comments.filter(c => c.parent_id === null);
        const replies = comments.filter(c => c.parent_id !== null);
        const replyMap = {};
        replies.forEach(r => {
            if (!replyMap[r.parent_id]) replyMap[r.parent_id] = [];
            replyMap[r.parent_id].push(r);
        });
        list.innerHTML = topLevel.map(c => {
            const commentReplies = (replyMap[c.id] || []).map(r => `
                <div class="comment-item reply" data-comment-id="${r.id}">
                    <div class="comment-item-head">
                        <span class="comment-item-author">${this._esc('用户 #' + r.author_id)}</span>
                        <span class="comment-item-time">${this._formatCommentTime(r.created_at)}</span>
                    </div>
                    <div class="comment-item-body">${this._renderCommentBody(r.body)}</div>
                    <div class="comment-item-actions">
                        <button class="comment-item-action" data-comment-action="delete" data-comment-id="${r.id}">删除</button>
                    </div>
                </div>
            `).join('');
            return `
                <div class="comment-item" data-comment-id="${c.id}">
                    <div class="comment-item-head">
                        <span class="comment-item-author">${this._esc('用户 #' + c.author_id)}</span>
                        <span class="comment-item-time">${this._formatCommentTime(c.created_at)}</span>
                    </div>
                    <div class="comment-item-body">${this._renderCommentBody(c.body)}</div>
                    <div class="comment-item-actions">
                        <button class="comment-item-action" data-comment-action="reply" data-comment-id="${c.id}">回复</button>
                        <button class="comment-item-action" data-comment-action="delete" data-comment-id="${c.id}">删除</button>
                    </div>
                    ${commentReplies}
                </div>
            `;
        }).join('');
        list.querySelectorAll('[data-comment-action]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const action = btn.dataset.commentAction;
                const id = parseInt(btn.dataset.commentId);
                if (action === 'reply') {
                    this._replyToComment(id);
                } else if (action === 'delete') {
                    if (!confirm('确定删除此评论？')) return;
                    try {
                        await API.deleteComment(id);
                        App._showToast('评论已删除');
                        this._loadComments(this._currentCommentObjectType, this._currentCommentObjectId);
                    } catch (e) {
                        App._showToast('删除失败: ' + (e.message || ''));
                    }
                }
            });
        });
    },

    _renderCommentBody(body) {
        if (!body) return '';
        // 替换 @username 为 mention 样式
        const rendered = this._esc(body).replace(/@(\S+)/g, '<span class="mention-tag">@${1}</span>');
        return rendered;
    },

    _formatCommentTime(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(d);
    },

    async _submitComment() {
        const input = document.getElementById('comment-input');
        const body = input.value.trim();
        if (!body) {
            App._showToast('请输入评论内容');
            return;
        }
        if (!this._currentCommentObjectType || !this._currentCommentObjectId) {
            App._showToast('请先加载审查内容');
            return;
        }
        try {
            await API.createComment({
                object_type: this._currentCommentObjectType,
                object_id: this._currentCommentObjectId,
                body,
            });
            input.value = '';
            App._showToast('评论已发表');
            this._loadComments(this._currentCommentObjectType, this._currentCommentObjectId);
        } catch (e) {
            App._showToast('发表失败: ' + (e.message || ''));
        }
    },

    _replyToComment(parentId) {
        const input = document.getElementById('comment-input');
        input.value = `回复 #${parentId}: `;
        input.focus();
        // 临时标记为回复模式
        this._replyParentId = parentId;
    },

    /* ── P4: 结果区显示后触发 P4 面板 ── */

    _hideP4Panels() {
        const ids = ['review-presentation-entry', 'review-artifact-section', 'review-collab-section', 'review-comment-section'];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
    },

    _showP4PanelsAfterResult() {
        const projectId = this.currentProjectId;
        if (!projectId) return;

        // P4.B.5: 显示讲解准备入口（审查完成后）
        const presentationEntry = document.getElementById('review-presentation-entry');
        const taskInfo = this._getTaskInfo();
        const isCompleted = taskInfo && ['completed', 'completed_with_warnings'].includes(taskInfo.status);
        if (presentationEntry) {
            presentationEntry.style.display = isCompleted ? '' : 'none';
        }

        // P4.A.4: 加载协作审查列表
        this._loadCollabRequests(projectId);

        // P4.D.6: 加载评论（基于当前审查任务）
        const objectType = 'review_request';
        // 使用项目 id 查找关联的 review request
        API.listReviewRequests(projectId).then(requests => {
            if (requests.length > 0) {
                const requestId = requests[0].id;
                this._loadComments(objectType, requestId);
                this._loadArtifacts(objectType, requestId);
            } else {
                // 无协作审查请求时，评论基于项目
                this._loadComments('review_request', 0);
                const collabSection = document.getElementById('review-collab-section');
                if (collabSection) collabSection.style.display = 'none';
                const commentSection = document.getElementById('review-comment-section');
                if (commentSection) commentSection.style.display = 'none';
                const artifactSection = document.getElementById('review-artifact-section');
                if (artifactSection) artifactSection.style.display = 'none';
            }
        });
    },
};

window.Review = Review;
