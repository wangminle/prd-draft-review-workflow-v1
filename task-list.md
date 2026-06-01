# Task List

## 2026-06-01

- [x] **项目运行方式检查** - 确认项目结构和启动流程
  - FastAPI + SQLite + 原生 JS SPA，端口 17957
  - 启动：`./start.sh`（含 start/stop/restart/status）
  - 依赖：`requirements.txt`，尚未创建 `.venv`

- [x] **敏感信息排查** - 全量搜索海尔/haier/王敏乐/wangminle 等具体企业和个人信息
  - docs/、skills/、src/、tests/ 全目录搜索 → 未找到
  - git 历史搜索 → 未找到

- [x] **开源合规匿名化** - docs/ 文档模糊化
  - `3-design/需求审查工作流平台-需求说明书.md` — UI mockup 示例产品名和文档名替换（分布式唤醒→产品需求A、全屋智能→产品需求B、云端判定→智能判定、设备预约→示例需求、埋点→数据采集/校验需求等）
  - `2-archive/20260515-业务逻辑层整合技术方案.md` — 移除内部目录名 "20260511-简单局域网内网站的建立"
  - `2-archive/三栏式UI界面设计指南.md` — 设备预约需求A→产品需求A、设备预约历史PRD→示例历史PRD
  - `4-deployment/2026-05-22-ubuntu-nginx-systemd-security-plan.md` — 服务名 ai-review→prd-review、内部目录名移除、配置路径更新
  - `1-discussion/Skill-as-a-Service人机协同工具开发范式.md` — 基于描述泛化、LLM 选型改为"配置示例"

- [x] **开源合规匿名化** - skills/ Prompt 和模板模糊化
  - `prd-overview-classify/` — SKILL.md、classify.md、version-chain.md、category-examples.md、usage-guide.md（云端策略→核心策略、分布式唤醒→智能联动、唤醒体验→交互体验、设备预约→功能预约、埋点→数据追踪、动态时延→响应时延）
  - `prd-per-analysis/` — SKILL.md、per-doc-analysis.md、resolution-tracking.md、usage-guide.md（云端策略→核心策略、云端判定→智能判定、唤醒应答→交互应答）
  - `system-review/` — SKILL.md、pm-assessment.md、industry-smart-home.json、pm-scoring-rubric.json（分布式唤醒→智能联动、设备预约→服务预约、埋点→数据采集/效果追踪、全屋智能→智能场景、语音唤醒→交互触发）
  - `requirement-insights/` — SKILL.md、evolution-match.md、feature-extraction.md、usage-guide.md（动态时延→响应时延、埋点方案→数据采集方案、唤醒判定→联动判定、唤醒应答→交互应答）
  - `report-generator/` — SKILL.md（分布式唤醒→智能联动）

- [x] **开源合规匿名化** - tests/ 测试数据模糊化
  - test_review_backend_contract.py、test_review_report_contract.py — "有埋点"→"有数据采集"（3处）

- [x] **运行时兼容性验证** - 确认匿名化修改不破坏现有数据结构和运行逻辑
  - 数据库 models：category/title 等字段为自由文本，不依赖硬编码枚举 → 安全
  - SkillRunner：分类关键词通过 {{category_keywords}} 动态注入，prompt 示例仅为输出格式说明 → 安全
  - industry-smart-home.json：运行时加载的竞争分析模板，已完成全部匿名化 → 安全
  - default-categories.json：空列表，用户自行配置 → 安全
  - 全量回归：pytest 344 通过，两次验证均无破坏