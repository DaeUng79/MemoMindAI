"""Small application logger used by both UI and services."""

import datetime as dt


def trim_text(text: str | None, limit: int = 200) -> str:
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit] + "..."


class EventLogger:
    def __call__(self, stage: str, message: str = "", turn_id: int | None = None) -> None:
        turn_label = f"[CHAT#{turn_id:03d}]" if turn_id is not None else "[SYSTEM]"
        prefix = f"[{dt.datetime.now():%H:%M:%S}]{turn_label}[{stage}]"
        print(f"{prefix} {message}" if message else prefix)
