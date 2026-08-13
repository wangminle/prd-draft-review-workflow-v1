"""OPT-002: 根目录 .env 为唯一环境文件；空 JWT_SECRET 首次生成后写入该文件。"""

from pathlib import Path

from app.env_file import ensure_canonical_env, persist_jwt_secret


def test_persist_jwt_secret_creates_file(tmp_path):
    env_path = tmp_path / ".env"
    persist_jwt_secret(env_path, "a" * 64)
    assert env_path.read_text(encoding="utf-8") == "JWT_SECRET=" + "a" * 64 + "\n"


def test_persist_jwt_secret_replaces_empty_assignment(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=sk-test\nJWT_SECRET=\nSERVER_PORT=17957\n", encoding="utf-8")
    persist_jwt_secret(env_path, "b" * 64)
    text = env_path.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-test" in text
    assert "JWT_SECRET=" + "b" * 64 in text
    assert "SERVER_PORT=17957" in text
    assert "JWT_SECRET=\n" not in text.replace("JWT_SECRET=" + "b" * 64 + "\n", "")


def test_persist_jwt_secret_does_not_uncomment_placeholder(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# JWT_SECRET=\nDEEPSEEK_API_KEY=\n", encoding="utf-8")
    persist_jwt_secret(env_path, "c" * 64)
    text = env_path.read_text(encoding="utf-8")
    assert text.startswith("# JWT_SECRET=\n")
    assert "JWT_SECRET=" + "c" * 64 in text


def test_ensure_canonical_env_ignores_src_when_root_exists(tmp_path):
    (tmp_path / ".env").write_text("SERVER_PORT=17957\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / ".env").write_text("SERVER_PORT=8080\nJWT_SECRET=from-src\n", encoding="utf-8")

    path, warnings = ensure_canonical_env(tmp_path)

    assert path == tmp_path / ".env"
    assert path.read_text(encoding="utf-8") == "SERVER_PORT=17957\n"
    assert (src / ".env").read_text(encoding="utf-8") == "SERVER_PORT=8080\nJWT_SECRET=from-src\n"
    assert any("Ignoring" in w or "忽略" in w for w in warnings)


def test_ensure_canonical_env_migrates_src_when_root_missing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / ".env").write_text("JWT_SECRET=legacy-secret-value-32chars-min!!\n", encoding="utf-8")

    path, warnings = ensure_canonical_env(tmp_path)

    assert path == tmp_path / ".env"
    assert path.read_text(encoding="utf-8") == "JWT_SECRET=legacy-secret-value-32chars-min!!\n"
    assert any(
        "copied" in w.lower() or "migrat" in w.lower() or "迁移" in w or "复制" in w
        for w in warnings
    )
