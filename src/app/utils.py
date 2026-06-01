"""统一时间工具 — 东八区（北京时间 UTC+8）"""
from datetime import datetime, timezone, timedelta

_CN_TZ = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    """返回当前北京时间（无时区信息的 naive datetime，与 SQLite 兼容）"""
    return datetime.now(_CN_TZ).replace(tzinfo=None)