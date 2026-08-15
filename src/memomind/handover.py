"""Pure JSON export/import helpers for memo handover."""

import datetime as dt
import json
from pathlib import Path
import re


def memo_to_json_item(item) -> dict:
    return {
        "id": getattr(item, "doc_id", item.get("id")),
        "document_type": item.get("document_type", ""),
        "assistant": item.get("assistant", ""),
        "timestamp": item.get("timestamp", ""),
    }


def build_payload(items: list, selected_type: str | None = None) -> dict:
    sorted_items = sorted(items, key=lambda item: item.get("timestamp", ""), reverse=True)
    now = dt.datetime.now().isoformat(timespec="seconds")
    if selected_type:
        filtered = [item for item in sorted_items if item.get("document_type") == selected_type]
        return {
            "export_type": "document_type",
            "document_type": selected_type,
            "business_type_name": selected_type,
            "exported_at": now,
            "count": len(filtered),
            "memos": [memo_to_json_item(item) for item in filtered],
        }

    grouped: dict[str, list[dict]] = {}
    for item in sorted_items:
        doc_type = item.get("document_type", "") or "미분류"
        grouped.setdefault(doc_type, []).append(memo_to_json_item(item))
    return {
        "export_type": "all_by_document_type",
        "business_type_name": "전체",
        "business_type_names": sorted(grouped),
        "exported_at": now,
        "count": len(sorted_items),
        "document_types": grouped,
    }


def payload_to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def save_payload(payload: dict, memo_dir: Path, prefix: str) -> Path:
    safe_prefix = re.sub(r'[\\/:*?"<>|]+', "_", prefix).strip() or "memo_export"
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = memo_dir / f"{safe_prefix}_{timestamp}.json"
    export_path.write_text(payload_to_json(payload), encoding="utf-8")
    return export_path


def extract_memos(payload) -> list[dict]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise ValueError("JSON 형식이 올바르지 않습니다.")
    if isinstance(payload.get("memos"), list):
        default_type = str(payload.get("document_type") or payload.get("business_type_name") or "").strip()
        memos = []
        for source in payload["memos"]:
            if isinstance(source, dict):
                memo = dict(source)
                if default_type and default_type != "전체":
                    memo.setdefault("document_type", default_type)
                memos.append(memo)
        return memos
    if isinstance(payload.get("document_types"), dict):
        memos = []
        for doc_type, type_memos in payload["document_types"].items():
            if not isinstance(type_memos, list):
                continue
            for source in type_memos:
                if isinstance(source, dict):
                    memo = dict(source)
                    memo.setdefault("document_type", doc_type)
                    memos.append(memo)
        return memos
    if payload.get("document_type") and payload.get("assistant"):
        return [dict(payload)]
    raise ValueError("등록할 메모 목록을 찾을 수 없습니다.")


def decode_json_data(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949")
