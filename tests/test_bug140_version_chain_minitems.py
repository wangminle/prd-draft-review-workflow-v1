"""BUG-140: version-chain schema minItems 过严导致单篇 quick 审查永远失败。

问题：output-schema.version-chain.json 要求 versions.minItems: 2，
但 quick/review/pm/insight/full 模式不处理历史文档，只有 requirement 文档
参与版本链分析。当项目只有 1 篇 requirement 文档时，版本链必然只有 1 个
版本，不满足 minItems: 2，导致 classify_version_chain skill 3 次重试
全部失败，管线中止。

修复：minItems 从 2 放宽到 1。单篇文档本身就是一个合法的版本链。
"""

import json
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    PROJECT_ROOT
    / "skills"
    / "prd-overview-classify"
    / "templates"
    / "output-schema.version-chain.json"
)


class TestVersionChainSchemaMinItems:
    """验证 version-chain schema 允许单版本链。"""

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists(), f"Schema file not found: {SCHEMA_PATH}"

    def test_min_items_is_one(self):
        """minItems 必须为 1，不能为 2（否则单篇 quick 审查永远失败）。"""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        versions_prop = (
            schema["properties"]["chains"]["items"]["properties"]["versions"]
        )
        assert versions_prop.get("minItems") == 1, (
            f"versions.minItems 应为 1（允许单篇文档），"
            f"实际为 {versions_prop.get('minItems')}"
        )

    def test_single_version_chain_passes_validation(self):
        """单版本链应通过 schema 校验。"""
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        single_chain_data = {
            "chains": [
                {
                    "chain_name": "设备预约",
                    "category": "核心策略",
                    "versions": [
                        {
                            "version": "V2.7.7",
                            "doc_id": "54",
                            "title": "设备预约V2.7.7",
                        }
                    ],
                }
            ],
            "dependencies": [],
        }
        # 不应抛异常
        jsonschema.validate(single_chain_data, schema)

    def test_two_version_chain_still_passes(self):
        """多版本链仍应通过校验（回归保护）。"""
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        multi_chain_data = {
            "chains": [
                {
                    "chain_name": "设备预约",
                    "versions": [
                        {"version": "V2.7.0", "doc_id": "1", "title": "旧版"},
                        {"version": "V2.7.7", "doc_id": "2", "title": "新版"},
                    ],
                }
            ],
            "dependencies": [
                {"from_doc_id": "1", "to_doc_id": "2", "relation": "version_successor"}
            ],
        }
        jsonschema.validate(multi_chain_data, schema)

    def test_empty_versions_still_rejected(self):
        """空版本数组仍应被拒绝（versions 至少 1 项）。"""
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        empty_chain_data = {
            "chains": [
                {
                    "chain_name": "空链",
                    "versions": [],
                }
            ],
            "dependencies": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(empty_chain_data, schema)
