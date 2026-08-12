"""Tests for context_window field and proactive context compression.

Covers:
- estimate_tokens() basic behavior
- compress_messages_to_budget() truncation logic
- build_messages() with context_window parameter
- ModelConfigCreate/Update validation for context_window
"""

from __future__ import annotations

import pytest

from app.services.llm import (
    ChatMessage,
    PromptTemplate,
    build_messages,
    compress_messages_to_budget,
    estimate_tokens,
)


# ── estimate_tokens ──────────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_text(self):
        assert estimate_tokens("hello") >= 1

    def test_long_text_proportional(self):
        short = estimate_tokens("a" * 30)
        long = estimate_tokens("a" * 300)
        assert long > short > 0

    def test_chinese_text(self):
        # Chinese characters are counted the same way (char-based estimation)
        assert estimate_tokens("你好世界") >= 1


# ── compress_messages_to_budget ──────────────────────────────────────────────

class TestCompressMessagesToBudget:
    def test_no_compression_when_context_window_zero(self):
        """context_window=0 means compression disabled."""
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "question"},
        ]
        result = compress_messages_to_budget(msgs, context_window=0, max_tokens=4096)
        assert result == msgs

    def test_no_compression_when_within_budget(self):
        """Messages within budget should be returned unchanged."""
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
        ]
        result = compress_messages_to_budget(msgs, context_window=200000, max_tokens=4096)
        assert result == msgs

    def test_truncation_when_exceeding_budget(self):
        """When total tokens exceed budget, older history should be truncated."""
        # Build a large conversation that exceeds the context window
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            msgs.append({"role": role, "content": f"Message number {i} " * 50})
        msgs.append({"role": "user", "content": "final question"})

        # context_window=10000, max_tokens=1000 → budget = 10000 - 1000 - 512 = 8488
        # Each history msg is ~950 chars ≈ 317 tokens + 4 overhead = ~321 tokens
        # 20 history msgs ≈ 6420 tokens total, plus system and user
        # Use a smaller context_window to force truncation
        result = compress_messages_to_budget(msgs, context_window=3000, max_tokens=500)

        # System message should be preserved
        assert result[0]["role"] == "system"
        # Last user message should be preserved
        assert result[-1]["content"] == "final question"
        # Result should be shorter than original
        assert len(result) < len(msgs)

    def test_compression_notice_inserted(self):
        """When history is truncated, a compression notice should be inserted."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old message " * 100},
            {"role": "assistant", "content": "old reply " * 100},
            {"role": "user", "content": "new question"},
        ]
        # budget = 2000 - 100 - 512 = 1388
        # old message ≈ 1200/3 + 4 = 404, old reply ≈ 1000/3 + 4 = 337
        # total ≈ 4+2 + 404 + 337 + 4+5 = 756 -> need smaller budget
        result = compress_messages_to_budget(msgs, context_window=800, max_tokens=100)

        # Should have a compression notice
        notices = [m for m in result if "省略" in m.get("content", "")]
        assert len(notices) >= 1

    def test_system_and_last_user_always_preserved(self):
        """System prompt and last user message must always survive compression."""
        msgs = [
            {"role": "system", "content": "important system prompt"},
            {"role": "user", "content": "msg 1 " * 200},
            {"role": "assistant", "content": "reply 1 " * 200},
            {"role": "user", "content": "msg 2 " * 200},
            {"role": "assistant", "content": "reply 2 " * 200},
            {"role": "user", "content": "final question"},
        ]
        result = compress_messages_to_budget(msgs, context_window=400, max_tokens=50)

        assert result[0]["content"] == "important system prompt"
        assert result[-1]["content"] == "final question"

    def test_budget_too_small_preserves_system_and_user(self):
        """When budget is too small for any history, only system + user remain."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old history " * 50},
            {"role": "assistant", "content": "old reply " * 50},
            {"role": "user", "content": "current question"},
        ]
        # budget = 600 - 50 - 512 = 38 tokens -> barely enough for system + user
        result = compress_messages_to_budget(msgs, context_window=600, max_tokens=50)

        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "current question"
        # No history messages should survive
        assert len(result) <= 3  # system + maybe notice + user

    def test_empty_messages(self):
        result = compress_messages_to_budget([], context_window=200000, max_tokens=4096)
        assert result == []

    def test_no_truncation_no_notice(self):
        """When no truncation happens, no compression notice should be added."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "question"},
        ]
        result = compress_messages_to_budget(msgs, context_window=200000, max_tokens=4096)
        notices = [m for m in result if "省略" in m.get("content", "")]
        assert len(notices) == 0

    def test_keeps_most_recent_history(self):
        """When truncating, the most recent history messages should be kept."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "oldest message " * 30},
            {"role": "assistant", "content": "oldest reply " * 30},
            {"role": "user", "content": "recent message " * 30},
            {"role": "assistant", "content": "recent reply " * 30},
            {"role": "user", "content": "final question"},
        ]
        # budget = 1000 - 50 - 512 = 438
        # System(5) + final_user(9) + notice(~34) = ~48
        # History budget = 438 - 48 = 390
        # "recent reply"(134) + "recent message"(154) = 288 -> fits
        # "oldest reply"(134) -> 288+134=422 > 390 -> doesn't fit
        result = compress_messages_to_budget(msgs, context_window=1000, max_tokens=50)

        # The "recent reply" should be in the result (most recent assistant)
        contents = [m["content"] for m in result]
        assert any("recent reply" in c for c in contents)
        # The "oldest message" should NOT be in the result
        assert not any("oldest message" in c for c in contents)


# ── build_messages with context_window ───────────────────────────────────────

class TestBuildMessagesWithContextWindow:
    def test_build_messages_no_context_window(self):
        """Without context_window, behaves as before (no compression)."""
        template = PromptTemplate(
            name="test",
            description="test",
            system_prompt="You are helpful.",
            user_prompt_template=None,
        )
        history = [
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="assistant", content="hi"),
        ]
        msgs = build_messages(template, history, "question", context_window=0)
        assert len(msgs) == 4  # system + 2 history + user
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "question"

    def test_build_messages_with_context_window_compression(self):
        """With a small context_window, history should be compressed."""
        template = PromptTemplate(
            name="test",
            description="test",
            system_prompt="You are helpful.",
            user_prompt_template=None,
        )
        history = [
            ChatMessage(role="user", content=f"old message {i} " * 50)
            for i in range(10)
        ]
        history.extend([
            ChatMessage(role="assistant", content=f"old reply {i} " * 50)
            for i in range(10)
        ])
        # budget = 3000 - 50 - 512 = 2438
        # Each history msg ≈ (18*50)/3 + 4 = 304 tokens
        # 20 msgs ≈ 6080 tokens -> exceeds budget, will be truncated
        msgs = build_messages(
            template, history, "final question",
            context_window=3000, max_tokens=50,
        )
        # Should be compressed (fewer than 1 system + 20 history + 1 user = 22)
        assert len(msgs) < 22
        # System and final user should still be present
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["content"] == "final question"

    def test_build_messages_with_context_no_compression_needed(self):
        """With a large context_window, no compression should happen."""
        template = PromptTemplate(
            name="test",
            description="test",
            system_prompt="sys",
            user_prompt_template=None,
        )
        history = [ChatMessage(role="user", content="hello")]
        msgs = build_messages(
            template, history, "question",
            context_window=200000, max_tokens=4096,
        )
        assert len(msgs) == 3  # system + 1 history + user
        # No compression notice
        notices = [m for m in msgs if "省略" in m.get("content", "")]
        assert len(notices) == 0


# ── ModelConfigCreate/Update validation ──────────────────────────────────────

class TestModelConfigValidation:
    def test_create_context_window_default_zero(self):
        from app.routers.admin import ModelConfigCreate
        mc = ModelConfigCreate(
            model_id="test", name="test", api_base="http://x", llm_model="m",
        )
        assert mc.context_window == 0

    def test_create_context_window_positive(self):
        from app.routers.admin import ModelConfigCreate
        mc = ModelConfigCreate(
            model_id="test", name="test", api_base="http://x", llm_model="m",
            context_window=200000,
        )
        assert mc.context_window == 200000

    def test_create_context_window_negative_rejected(self):
        from app.routers.admin import ModelConfigCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ModelConfigCreate(
                model_id="test", name="test", api_base="http://x", llm_model="m",
                context_window=-1,
            )

    def test_update_context_window_negative_rejected(self):
        from app.routers.admin import ModelConfigUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ModelConfigUpdate(context_window=-100)

    def test_update_context_window_zero_ok(self):
        from app.routers.admin import ModelConfigUpdate
        mc = ModelConfigUpdate(context_window=0)
        assert mc.context_window == 0

    def test_update_context_window_none_ok(self):
        from app.routers.admin import ModelConfigUpdate
        mc = ModelConfigUpdate()
        assert mc.context_window is None
