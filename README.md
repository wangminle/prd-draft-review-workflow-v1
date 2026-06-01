# PRD Draft Review Workflow V1

AI-powered Product Requirements Document (PRD) review and collaboration platform.

## Overview

This platform provides an intranet-deployable web application for teams to:
- Upload PRD documents (DOCX format)
- Run AI-powered multi-dimension reviews
- Track requirement evolution across versions
- Generate review reports and PRD drafts

The system uses a **Skill-as-a-Service** architecture with 6 specialized AI skills orchestrated by a SkillRunner pipeline.

## Skills Pipeline

| Order | Skill | Purpose |
|-------|-------|---------|
| 1 | docx-to-markdown | Convert Word documents to Markdown |
| 2 | prd-overview-classify | Classify documents and build version chains |
| 3 | prd-per-analysis | 6-dimension per-document analysis |
| 4 | system-review | 7-dimension system-level review |
| 5 | requirement-insights | Evolution tracking and gap analysis |
| 6 | report-generator | Generate reports and PRD drafts |

## Review Modes

- `quick` — Fast single-document review
- `review` — Standard review pipeline
- `pm` — PM capability assessment focus
- `insight` — Include evolution and gap insights
- `full` — Complete analysis pipeline
- `draft` — Generate PRD draft from analysis

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy (async) + SQLite
- **Frontend**: Vanilla JS SPA + CSS
- **Authentication**: JWT + bcrypt
- **LLM**: OpenAI-compatible API (DeepSeek, Qwen, GLM, etc.)
- **Document Processing**: python-docx, mammoth

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys and JWT_SECRET

# 4. Start server
./start.sh
```

Server runs on port **17957** by default.

## Project Structure

```
prd-draft-review-workflow-v1/
├── src/                    # Application source
│   ├── main.py             # FastAPI entry point
│   ├── config.yaml         # Application configuration
│   ├── app/                # Backend modules
│   │   ├── middleware/     # Auth middleware
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── routers/        # API route handlers
│   │   ├── schemas/        # Pydantic validation schemas
│   │   └── services/       # Business logic services
│   └── static/             # Frontend SPA
│       ├── index.html
│       ├── css/main.css
│       └── js/             # Modular JS
├── skills/                 # AI skill modules
├── tests/                  # Test suite
├── docs/                   # Documentation
├── runtime/                # Runtime data (git-ignored)
│   ├── data/               # Database and converted docs
│   ├── uploads/            # User uploads
│   ├── logs/               # Application logs
│   └── results/            # Review results
├── start.sh                # Startup script
├── requirements.txt        # Python dependencies
├── pyproject.toml          # Test configuration
└── .env.example            # Environment template
```

## Data & Code Separation

Runtime data (database, uploads, logs, results) is stored in `runtime/` which is git-ignored. This ensures:
- Clean git history without binary data
- Easy deployment by mounting a separate data volume
- Safe open-source distribution without leaking user data

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.