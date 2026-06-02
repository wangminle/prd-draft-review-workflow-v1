"""AuditLogReader — 审计日志查询。

职责边界：
- 管理后台最近访问统计结果不变
- 日志读取和日志写入不强行塞进同一个接口
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path

from app.logging_config import get_logs_dir


@dataclass
class AccessRecord:
    timestamp: str
    username: str
    action: str
    method: str
    path: str
    client_ip: str
    result: str


def _parse_log_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from app.utils import _CN_TZ
        return parsed.replace(tzinfo=_CN_TZ)
    return parsed.astimezone(timezone.utc)


class AuditLogReader:
    def list_recent_access_records(
        self, *, days: int = 7, limit: int = 50, logs_dir: str | Path | None = None, now: datetime | None = None
    ) -> list[AccessRecord]:
        log_dir = Path(logs_dir) if logs_dir is not None else get_logs_dir()
        audit_file = log_dir / "audit.jsonl"
        if not audit_file.exists():
            return []

        from app.utils import _CN_TZ
        current = now or datetime.now(_CN_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=_CN_TZ)
        cutoff = current - timedelta(days=days)

        records = []
        with audit_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = _parse_log_timestamp(entry.get("timestamp"))
                if ts is None or ts < cutoff:
                    continue

                request = entry.get("request") or {}
                actor = entry.get("actor") or {}
                records.append(AccessRecord(
                    timestamp=ts.isoformat(),
                    username=actor.get("username") or "-",
                    action=entry.get("action") or "-",
                    method=request.get("method") or "-",
                    path=request.get("path") or "-",
                    client_ip=request.get("client_ip") or "-",
                    result=entry.get("result") or "-",
                ))

        records.sort(key=lambda item: item.timestamp, reverse=True)
        return records[:limit]