# 快速开始 / Getting Started

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

<a id="中文"></a>

## 中文

本文档帮助你从零开始,在本机跑通「AI 需求评审工作流平台」:克隆代码到完成第一次 AI 评审,大约 10 分钟。

平台把 PM 写 PRD → 邮件/飞书群发 → 评审人各自读 → 线下开会的传统线下流程,重构为上传 DOCX 即自动触发 AI 评审、生成结构化报告的工作流。技术栈:FastAPI + SQLAlchemy Async + SQLite + 原生 JS SPA。默认端口 17957。

### 环境要求

- **Python 3.10+**(必需)
- 若要使用 **Pi Agent**(自主工具调用对话)功能:还需 **Node.js 18+ 和 npm**。不用 Agent 可不装 Node,主应用照常运行。
- Python 依赖见 [`requirements.txt`](../requirements.txt)。

### 1. 克隆项目

```bash
git clone <项目仓库地址>
cd prd-draft-review-workflow-v1
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Windows PowerShell 用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。

### 3. 准备配置文件

```bash
cp .env.example .env
```

编辑 `.env`,**至少填入以下两项**:

- **至少一个 LLM API Key**(四选一或多选):`DEEPSEEK_API_KEY`、`QWEN_API_KEY`、`GLM_API_KEY`、`OPENAI_API_KEY`。
- **`JWT_SECRET`(必填)**:至少 32 字符的随机串。生成方式:

  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```

  说明:`start.sh` 在 `JWT_SECRET` 为空时会自动生成一个**临时 session 密钥**(仅适合本机开发试用);但**生产环境必须显式配置**一个固定值。服务层 `jwt_secret.py` 会拒绝以下情况并阻止启动:空值、已知不安全占位值(如 `change-me-in-production`、`secret` 等)、长度不足 32 字符。

**最小可运行 `.env` 示例:**

```dotenv
DEEPSEEK_API_KEY=sk-your-key-here
JWT_SECRET=<至少32字符随机串>
```

可选:`ADMIN_INITIAL_PASSWORD` 覆盖首个 admin 账号的初始密码;不设则使用代码内置默认口令 `admin@2026`(启动日志会打印 `[SECURITY]` 警告,要求尽快修改)。

### 4. 启动服务

```bash
./start.sh
```

默认前台启动(等价于 `./start.sh start`)。脚本会:加载 `.env` → 检测可选的 Node/pi CLI → 启动 uvicorn → 自动执行健康检查。

启动成功后访问:**http://localhost:17957**

### 5. 首次登录

服务启动时会自动确保 `admin` 账号存在。默认口令 `admin@2026`;若设置了 `ADMIN_INITIAL_PASSWORD` 则用该值登录。**强烈建议登录后立即修改密码**(默认口令会在日志持续输出 `[SECURITY]` 警告)。

### 6. 验证跑通

1. 登录后**创建一个评审项目**。
2. **上传一份 DOCX** 需求文档。
3. 选择 **quick 模式**(最快,约 2 分钟)并运行。
4. 在报告页查看 AI 生成的结构化评审结果。

### 7. 健康检查

服务暴露健康检查端点,可随时验证是否在线:

```bash
curl http://localhost:17957/api/health
# 预期返回: {"status":"ok","version":"0.3.9"}
```

### 常用启停命令

```bash
./start.sh start     # 启动
./start.sh stop      # 停止
./start.sh restart   # 重启
./start.sh status    # 查看状态与健康检查
```

### 排错小提示

- **启动即退出**:大概率是 `JWT_SECRET` 未配置或过短。按上面方法生成并填入 `.env` 后重启。
- **健康检查失败**:确认 17957 端口未被占用,查看 `runtime/logs/app.log`。
- **Agent 功能不可用**:日志出现 `pi CLI not found` 时,运行 `npm install` 安装 Pi Agent,并确保 Node.js 18+ 已安装。

## 下一步

跑通后,推荐继续阅读:

- [configuration.md](configuration.md) — 完整配置项说明(模型、Prompt、品牌、端口、反代等)
- [user-guide.md](user-guide.md) — 完整功能使用指南(评审模式、协作审查、团队空间、Agent)
- [packaging-and-deployment.md](packaging-and-deployment.md) — 生产环境打包与部署

---

<a id="english"></a>

## English

This guide takes you from zero to your first AI-driven requirement review in about 10 minutes, running the **AI Requirement Review Workflow Platform** on your local machine.

The platform replaces the traditional offline flow (PM writes a PRD → mass-emails / Feishu groups → reviewers read separately → an in-person meeting) with an automated workflow: upload a DOCX and AI review runs automatically, producing a structured report. Stack: FastAPI + SQLAlchemy Async + SQLite + vanilla JS SPA. Default port: 17957.

### Prerequisites

- **Python 3.10+** (required)
- To use the **Pi Agent** (autonomous tool-calling conversation) feature you also need **Node.js 18+ and npm**. If you don't use the Agent, Node is not required; the main app runs fine without it.
- Python dependencies are listed in [`requirements.txt`](../requirements.txt).

### 1. Clone the project

```bash
git clone <repository-url>
cd prd-draft-review-workflow-v1
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

### 3. Prepare configuration

```bash
cp .env.example .env
```

Edit `.env` and **fill in at least the following two items**:

- **At least one LLM API key** (pick one or more): `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `GLM_API_KEY`, `OPENAI_API_KEY`.
- **`JWT_SECRET` (required)**: a random string of at least 32 characters. Generate one with:

  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```

  Note: `start.sh` will auto-generate a **temporary session secret** when `JWT_SECRET` is empty (fine for local trial only); **production must set an explicit, fixed value**. The service layer `jwt_secret.py` refuses to start in these cases: empty value, known insecure placeholders (e.g. `change-me-in-production`, `secret`), or length below 32 characters.

**Minimal runnable `.env` example:**

```dotenv
DEEPSEEK_API_KEY=sk-your-key-here
JWT_SECRET=<at-least-32-char-random-string>
```

Optional: `ADMIN_INITIAL_PASSWORD` overrides the initial password of the first admin account; if unset, the built-in default `admin@2026` is used (startup logs print a `[SECURITY]` warning urging an immediate change).

### 4. Start the service

```bash
./start.sh
```

This runs in the foreground by default (equivalent to `./start.sh start`). The script will: load `.env` → detect optional Node/pi CLI → start uvicorn → run a health check automatically.

Once started, open: **http://localhost:17957**

### 5. First login

On startup the service ensures an `admin` account exists. The default password is `admin@2026`; use the value of `ADMIN_INITIAL_PASSWORD` if you set it. **It is strongly recommended to change the password immediately after logging in** (the default password triggers a persistent `[SECURITY]` warning in logs).

### 6. Verify it works

1. After login, **create a review project**.
2. **Upload a DOCX** requirement document.
3. Choose **quick mode** (fastest, about 2 minutes) and run it.
4. View the AI-generated structured review report.

### 7. Health check

A health endpoint is exposed to verify the service is up at any time:

```bash
curl http://localhost:17957/api/health
# Expected: {"status":"ok","version":"0.3.9"}
```

### Common start / stop commands

```bash
./start.sh start     # start
./start.sh stop      # stop
./start.sh restart   # restart
./start.sh status    # show status and run health check
```

### Troubleshooting tips

- **Service exits immediately**: most likely `JWT_SECRET` is unset or too short. Generate one as shown above, put it in `.env`, and restart.
- **Health check failed**: make sure port 17957 is free, and inspect `runtime/logs/app.log`.
- **Agent features unavailable**: if logs show `pi CLI not found`, run `npm install` to install Pi Agent and ensure Node.js 18+ is installed.

## Next steps

Once it's running, continue with:

- [configuration.md](configuration.md) — full configuration reference (models, prompts, branding, ports, reverse proxy, etc.)
- [user-guide.md](user-guide.md) — complete feature guide (review modes, collaborative review, team workspace, Agent)
- [packaging-and-deployment.md](packaging-and-deployment.md) — production packaging and deployment
