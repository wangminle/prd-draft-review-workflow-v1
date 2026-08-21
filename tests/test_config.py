"""测试配置模块 (app.config)"""

import os
import tempfile

import pytest
import yaml


def test_load_config_default_path():
    """默认路径加载 config.yaml"""
    from app.config import load_config

    config = load_config()
    assert config is not None
    assert "database" in config
    assert "auth" in config
    assert "models" in config
    # OPT-001: 监听地址只由 start.sh 的 SERVER_HOST/SERVER_PORT 决定，yaml 不再放死配置
    assert "server" not in config


def test_load_config_resolves_env_vars():
    """${VAR} 占位符应从环境变量解析"""
    os.environ["TEST_DB_PATH"] = "/tmp/test.db"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"database": {"path": "${TEST_DB_PATH}"}}, f)
        path = f.name

    try:
        from app.config import load_config

        config = load_config(path)
        assert config["database"]["path"] == "/tmp/test.db"
    finally:
        os.unlink(path)
        del os.environ["TEST_DB_PATH"]


def test_load_config_missing_env_var_returns_empty():
    """未设置的 ${VAR} 应返回空字符串"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"key": "${NONEXISTENT_VAR_12345}"}, f)
        path = f.name

    try:
        from app.config import load_config

        config = load_config(path)
        assert config["key"] == ""
    finally:
        os.unlink(path)


def test_load_config_file_not_found():
    """不存在的路径应抛出 FileNotFoundError"""
    from app.config import load_config

    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")


def test_get_settings_singleton():
    """get_settings 应返回单例"""
    from app.config import get_settings

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
