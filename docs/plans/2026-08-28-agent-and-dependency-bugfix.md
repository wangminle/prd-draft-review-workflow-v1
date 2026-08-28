# Agent Authorization and Dependency Bugfix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 Agent workspace 授权越权、个人配置误覆盖、策略无法清空及部署依赖与锁文件不一致问题。

**Architecture:** 在授权创建与 RAG 使用两层实施 workspace 成员/状态校验；将个人 Agent 弹窗区分关键配置和辅助列表加载状态，并按受控字段合并工具白名单。依赖和锁文件通过契约测试保持单一来源一致。

**Tech Stack:** FastAPI、SQLAlchemy async、原生 JavaScript、pytest、Playwright、npm lockfile v3。

---

### Task 1: Workspace 授权纵深校验

**Files:**
- Modify: `src/app/routers/agent.py`
- Test: `tests/test_agent_p3.py`

**Step 1: Write the failing tests**

新增集成测试：非成员不能创建 workspace 授权、归档 workspace 不能授权、active 成员可以授权；已有授权在成员被移除后不能用于 RAG。

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest -q tests/test_agent_p3.py -k "authorization or membership"`

Expected: 非成员/归档空间用例当前返回 200，测试失败。

**Step 3: Write minimal implementation**

在 `agent.py` 增加 workspace 授权访问校验辅助函数。创建授权前调用；RAG workspace 分支在授权 ID 校验后再次查询目标 workspace 和当前 run 用户成员关系。

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest -q tests/test_agent_p3.py -k "authorization or membership"`

Expected: PASS。

### Task 2: 个人 Agent 弹窗防误覆盖

**Files:**
- Modify: `src/static/js/app.js`
- Modify: `tools/verify_account_menu_browser.py`
- Test: `tests/test_personal_agent_ia.py`

**Step 1: Write the failing browser checks**

新增浏览器桩场景：授权加载失败时不出现保存按钮；profile 中存在未展示工具时保存后仍保留；清空 System Policy 时 payload 为 `""`。

**Step 2: Run checks to verify they fail**

Run: `python3 tools/verify_account_menu_browser.py --json`

Expected: 新增配置场景失败。

**Step 3: Write minimal implementation**

关键请求不再吞错；辅助请求用带状态的结果呈现；保存时将未知工具与选中的受控工具合并；System Policy 原样提交字符串。

**Step 4: Run checks to verify they pass**

Run: `python3 tools/verify_account_menu_browser.py --json`

Expected: PASS。

### Task 3: 依赖、锁文件和格式一致性

**Files:**
- Modify: `requirements.txt`
- Modify: `package-lock.json`
- Modify: `tests/test_version_single_source.py`
- Modify: `tests/test_admin_frontend_contract.py`

**Step 1: Write failing contract tests**

断言根依赖包含 `openpyxl`，并断言 `package.json` 与 `package-lock.json` 根 engines.node 完全一致。

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest -q tests/test_version_single_source.py`

Expected: 两个契约断言失败。

**Step 3: Write minimal implementation**

根依赖增加 `openpyxl>=3.1.0`；运行 `npm install --package-lock-only --ignore-scripts` 同步锁文件；删除测试文件末尾多余空行。

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest -q tests/test_version_single_source.py && git diff --check`

Expected: PASS 且无 diff 格式错误。

### Task 4: 完整验证和复核

**Files:**
- Review all modified and untracked files.

**Step 1: Run focused regression tests**

Run: `python3 -m pytest -q tests/test_agent_p3.py tests/test_personal_agent_ia.py tests/test_version_single_source.py tests/test_docx_on_limit.py tests/test_docx_excel_tables.py`

**Step 2: Run full validation**

Run: `python3 -m pytest -q`

Run: `python3 -m ruff check .`

Run: `node --check src/static/js/app.js && node --check src/static/js/admin.js && node --check src/static/js/notification.js`

Run: `python3 tools/verify_account_menu_browser.py --json && python3 tools/verify_admin_nav_groups_browser.py --json`

Run: `npm ls --depth=0 && npm run pi:version && git diff --check`

**Step 3: Request independent review**

独立审查本次修复 diff，处理所有 Critical 和 Important 反馈后重复完整验证。
