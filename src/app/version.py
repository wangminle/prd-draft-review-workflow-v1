"""版本号读取器。唯一事实来源为项目根目录的 VERSION 纯文本文件。"""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"
APP_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip()
