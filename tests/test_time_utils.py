"""北京时间时间工具与模型默认时间回归测试。"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.models.review import DocAnalysis, ReviewContext, ReviewDocument, ReviewProject, ReviewPrompt, ReviewTask, SystemReview
from app.models.user import Conversation, Message, ModelConfig, PromptTemplate, User
from app.utils import now_cn


def test_now_cn_returns_utc_plus_8():
    cn_now = now_cn()
    expected = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)

    assert abs((cn_now - expected).total_seconds()) < 5


def test_models_use_now_cn_for_created_at_defaults():
    created_models = [
        User,
        Conversation,
        Message,
        PromptTemplate,
        ModelConfig,
        ReviewProject,
        ReviewDocument,
        ReviewTask,
        DocAnalysis,
        SystemReview,
        ReviewPrompt,
    ]

    for model in created_models:
        column = model.__mapper__.columns["created_at"]
        assert column.default.arg.__name__ == now_cn.__name__, model.__name__
        assert column.default.arg.__module__ == now_cn.__module__, model.__name__

    for model in [Conversation, ModelConfig, ReviewProject, ReviewContext]:
        column = model.__mapper__.columns["updated_at"]
        assert column.default.arg.__name__ == now_cn.__name__, model.__name__
        assert column.default.arg.__module__ == now_cn.__module__, model.__name__

    for model in [Conversation, ModelConfig, ReviewProject]:
        column = model.__mapper__.columns["updated_at"]
        assert column.onupdate.arg.__name__ == now_cn.__name__, model.__name__
        assert column.onupdate.arg.__module__ == now_cn.__module__, model.__name__