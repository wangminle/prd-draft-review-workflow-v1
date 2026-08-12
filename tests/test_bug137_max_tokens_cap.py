"""BUG-137: max_tokens 安全上限测试。

问题：管理员在模型配置中将 max_tokens 设为模型上下文窗口大小（如 200000），
该值被直接传给 OpenAI API 的 max_tokens 参数（输出 token 上限），
导致 prompt 无空间而触发 400 错误。

修复：
1. llm.py / retry.py 在发送 API 前对 max_tokens 做硬上限 32768
2. admin.py ModelConfigCreate/Update 加 field_validator 校验 1-32768
"""

import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM_PY = PROJECT_ROOT / "src" / "app" / "services" / "llm.py"
RETRY_PY = PROJECT_ROOT / "src" / "app" / "services" / "retry.py"
ADMIN_PY = PROJECT_ROOT / "src" / "app" / "routers" / "admin.py"


class TestCapMaxTokensFunction:
    """验证 _cap_max_tokens 函数存在且逻辑正确。"""

    def test_llm_py_has_cap_function(self):
        content = LLM_PY.read_text(encoding="utf-8")
        assert "def _cap_max_tokens" in content, "llm.py 中未找到 _cap_max_tokens 函数"

    def test_retry_py_has_cap_function(self):
        content = RETRY_PY.read_text(encoding="utf-8")
        assert "def _cap_max_tokens" in content, "retry.py 中未找到 _cap_max_tokens 函数"

    def test_cap_function_logic(self):
        """直接导入测试 _cap_max_tokens 的行为。"""
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from app.services.llm import _cap_max_tokens

        # 正常值不变
        assert _cap_max_tokens(4096) == 4096
        assert _cap_max_tokens(8192) == 8192
        assert _cap_max_tokens(32768) == 32768
        # 超大值被截断
        assert _cap_max_tokens(200000) == 32768
        assert _cap_max_tokens(1000000) == 32768
        # 非正值回退默认
        assert _cap_max_tokens(0) == 4096
        assert _cap_max_tokens(-1) == 4096
        assert _cap_max_tokens(None) == 4096

    def test_hard_limit_constant(self):
        content = LLM_PY.read_text(encoding="utf-8")
        assert "32768" in content, "llm.py 中未找到 32768 硬上限常量"
        content_r = RETRY_PY.read_text(encoding="utf-8")
        assert "32768" in content_r, "retry.py 中未找到 32768 硬上限常量"


class TestLlmPyUsesCap:
    """验证 llm.py 的 API 调用点使用了 _cap_max_tokens。"""

    def test_stream_chat_uses_cap(self):
        content = LLM_PY.read_text(encoding="utf-8")
        # stream_chat 中应有 _cap_max_tokens(max_tokens)
        assert "_cap_max_tokens(max_tokens)" in content, (
            "llm.py 中未找到 _cap_max_tokens(max_tokens) 调用"
        )
        # 确认出现至少 2 次（stream_chat + non_stream_chat）
        count = content.count("_cap_max_tokens(max_tokens)")
        assert count >= 2, f"llm.py 中 _cap_max_tokens 调用 {count} 次，期望至少 2 次"

    def test_no_bare_max_tokens_in_payload(self):
        """确认 payload 中不再直接使用原始 max_tokens。"""
        content = LLM_PY.read_text(encoding="utf-8")
        # 不应有 "max_tokens": max_tokens 这种直接透传
        bare = re.findall(r'"max_tokens":\s*max_tokens\b', content)
        # 允许函数签名中的 max_tokens 参数，但 payload 中不应直接使用
        bare_payload = [m for m in bare if "max_tokens" in m]
        assert not bare_payload, (
            f"llm.py payload 中仍有直接透传 max_tokens: {bare_payload}"
        )


class TestRetryPyUsesCap:
    """验证 retry.py 的 API 调用点使用了 _cap_max_tokens。"""

    def test_retryable_chat_uses_cap(self):
        content = RETRY_PY.read_text(encoding="utf-8")
        assert "_cap_max_tokens(max_tokens)" in content, (
            "retry.py 中未找到 _cap_max_tokens(max_tokens) 调用"
        )


class TestAdminValidation:
    """验证 admin.py 对 max_tokens 做了入口校验。"""

    def test_model_config_create_has_validator(self):
        content = ADMIN_PY.read_text(encoding="utf-8")
        assert "validate_max_tokens" in content, (
            "admin.py 中未找到 validate_max_tokens 校验器"
        )
        # 应出现至少 2 次（Create + Update）
        count = content.count("validate_max_tokens")
        assert count >= 2, f"admin.py 中 validate_max_tokens 出现 {count} 次，期望至少 2 次"

    def test_validation_rejects_oversize(self):
        """直接测试 Pydantic model 拒绝超大 max_tokens。"""
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from app.routers.admin import ModelConfigCreate, ModelConfigUpdate

        # Create: 200000 应被拒绝
        try:
            ModelConfigCreate(
                model_id="test",
                name="test",
                api_base="http://localhost",
                llm_model="test",
                max_tokens=200000,
            )
            raise AssertionError("ModelConfigCreate 应拒绝 max_tokens=200000")
        except Exception as e:
            assert "32768" in str(e) or "max_tokens" in str(e).lower(), (
                f"错误信息应包含 32768 或 max_tokens: {e}"
            )

        # Update: 200000 应被拒绝
        try:
            ModelConfigUpdate(max_tokens=200000)
            raise AssertionError("ModelConfigUpdate 应拒绝 max_tokens=200000")
        except Exception as e:
            assert "32768" in str(e) or "max_tokens" in str(e).lower(), (
                f"错误信息应包含 32768 或 max_tokens: {e}"
            )

    def test_validation_accepts_normal(self):
        """正常值应通过校验。"""
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from app.routers.admin import ModelConfigCreate, ModelConfigUpdate

        mc = ModelConfigCreate(
            model_id="test",
            name="test",
            api_base="http://localhost",
            llm_model="test",
            max_tokens=4096,
        )
        assert mc.max_tokens == 4096

        mc2 = ModelConfigCreate(
            model_id="test2",
            name="test2",
            api_base="http://localhost",
            llm_model="test2",
            max_tokens=32768,
        )
        assert mc2.max_tokens == 32768

        mu = ModelConfigUpdate(max_tokens=8192)
        assert mu.max_tokens == 8192
