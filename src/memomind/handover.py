"""업무 인수인계 메모 전달을 위한 JSON 내보내기 및 가져오기 기능"""

import datetime as dt
import json
from pathlib import Path
import re


def memo_to_json_item(item) -> dict:
    """
    메모 하나를 JSON으로 저장하기 적합한 dictionary 형태로 변환합니다.
    메모 객체 또는 dictionary에서 필요한 정보만 추출하여
    내보내기(export)에 사용할 데이터 구조를 만듭니다.
    """

    # 메모의 ID를 가져옵니다.
    # 객체 형태라면 doc_id를 사용하고,
    # dictionary 형태라면 id 값을 사용합니다.
    return {
        "id": getattr(item, "doc_id", item.get("id")),

        # 메모의 문서 유형을 가져옵니다.
        "document_type": item.get("document_type", ""),

        # AI가 생성한 메모 내용을 가져옵니다.
        "assistant": item.get("assistant", ""),

        # 메모가 생성되거나 저장된 시간을 가져옵니다.
        "timestamp": item.get("timestamp", ""),
    }


def build_payload(items: list, selected_type: str | None = None) -> dict:
    """
    메모 목록을 JSON으로 내보내기 위한 최종 데이터 구조로 만듭니다.
    selected_type이 지정되면:
        해당 문서 유형의 메모만 내보냅니다.
    selected_type이 없으면:
        모든 메모를 문서 유형별로 그룹화하여 내보냅니다.
    """

    # 메모를 timestamp 기준으로 최신 항목이 먼저 오도록 정렬합니다.
    # reverse=True이므로 가장 최근 메모가 앞에 위치합니다.
    sorted_items = sorted(
        items,
        key=lambda item: item.get("timestamp", ""),
        reverse=True,
    )

    # JSON 파일을 생성한 현재 시간을 기록합니다.
    # 예: 2026-08-15T13:30:25
    now = dt.datetime.now().isoformat(timespec="seconds")

    # 특정 문서 유형만 선택해서 내보내는 경우입니다.
    if selected_type:
        # 선택한 document_type과 일치하는 메모만 필터링합니다.
        filtered = [
            item
            for item in sorted_items
            if item.get("document_type") == selected_type
        ]

        # 선택한 문서 유형의 메모만 포함하는 JSON 데이터 구조를 반환합니다.
        return {
            # 이번 내보내기가 특정 문서 유형을 대상으로 한다는 표시입니다.
            "export_type": "document_type",

            # 선택된 문서 유형입니다.
            "document_type": selected_type,

            # 문서 유형 이름을 별도로 저장합니다.
            "business_type_name": selected_type,

            # JSON 파일을 생성한 시간입니다.
            "exported_at": now,

            # 실제로 내보내는 메모의 개수입니다.
            "count": len(filtered),

            # 필터링된 메모들을 JSON용 dictionary로 변환합니다.
            "memos": [memo_to_json_item(item) for item in filtered],
        }

    # 특정 문서 유형을 선택하지 않은 경우,
    # 모든 메모를 문서 유형별로 그룹화합니다.
    # {
    #     "회의": [메모1, 메모2],
    #     "업무": [메모3, 메모4],
    #     "개인": [메모5]
    # }
    grouped: dict[str, list[dict]] = {}

    # 정렬된 모든 메모를 하나씩 확인합니다.
    for item in sorted_items:

        # 메모의 문서 유형을 가져옵니다.
        # document_type이 없거나 비어 있으면 "미분류"로 처리합니다.
        doc_type = item.get("document_type", "") or "미분류"

        # 해당 문서 유형의 목록이 없으면 새 목록을 만들고, 현재 메모를 해당 목록에 추가합니다.
        grouped.setdefault(doc_type, []).append(memo_to_json_item(item))

    # 모든 문서 유형의 메모를 포함하는 JSON 데이터 구조를 반환합니다.
    return {
        # 모든 문서 유형을 기준으로 내보냈다는 표시입니다.
        "export_type": "all_by_document_type",

        # 전체 내보내기임을 나타냅니다.
        "business_type_name": "전체",

        # 존재하는 문서 유형의 이름 목록입니다.
        "business_type_names": sorted(grouped),

        # JSON 파일을 생성한 시간입니다.
        "exported_at": now,

        # 전체 메모의 개수입니다.
        "count": len(sorted_items),

        # 문서 유형별로 그룹화된 전체 메모입니다.
        "document_types": grouped,
    }


def payload_to_json(payload: dict) -> str:
    """
    Python dictionary 형태의 데이터를 JSON 문자열로 변환합니다.
    """

    # ensure_ascii=False:
    # 한글을 유니코드 코드로 변환하지 않고 그대로 저장합니다.
    #
    # indent=2:
    # JSON 파일을 사람이 읽기 쉽도록 2칸 들여쓰기로 정리합니다.
    return json.dumps(payload, ensure_ascii=False, indent=2)


def save_payload(payload: dict, memo_dir: Path, prefix: str) -> Path:
    """
    JSON 데이터를 실제 파일로 저장하고 저장된 파일 경로를 반환합니다.
    """

    # 파일 이름에 사용할 prefix에서
    # Windows/Linux 등에서 파일 이름에 사용할 수 없는 문자를 "_"로 변경합니다.
    #
    # 예:
    # "회의/보고서" -> "회의_보고서"
    safe_prefix = re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        prefix,
    ).strip() or "memo_export"

    # 파일 이름에 사용할 현재 시간을 생성합니다.
    # 예: 20260815_133025
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    # memoAI/회의_보고서_20260815_133025.json
    export_path = memo_dir / f"{safe_prefix}_{timestamp}.json"

    # JSON 데이터를 UTF-8 인코딩으로 파일에 저장합니다.
    export_path.write_text(
        payload_to_json(payload),
        encoding="utf-8",
    )

    # 실제로 저장된 파일의 경로를 반환합니다.
    return export_path


def extract_memos(payload) -> list[dict]:
    """
    다양한 형태의 JSON 데이터에서 메모 목록만 추출합니다.

    내보내기 파일의 구조가 서로 달라도
    최종적으로는 list[dict] 형태의 메모 목록으로 통일합니다.
    """

    # JSON의 최상위 데이터가 리스트인 경우입니다.
    #
    # 예:
    # [
    #     {"id": 1, "assistant": "메모1"},
    #     {"id": 2, "assistant": "메모2"}
    # ]
    if isinstance(payload, list):

        # 리스트 안에서 dictionary 형태의 데이터만 골라냅니다.
        # 각 항목을 새로운 dictionary로 복사하여 반환합니다.
        return [
            dict(item)
            for item in payload
            if isinstance(item, dict)
        ]

    # 최상위 데이터가 dictionary도 아니고 list도 아니라면
    # 이 프로그램에서 지원하지 않는 JSON 구조입니다.
    if not isinstance(payload, dict):
        raise ValueError("JSON 형식이 올바르지 않습니다.")

    # "memos"라는 목록이 포함된 JSON인지 확인합니다.
    #
    # 예:
    # {
    #     "document_type": "회의",
    #     "memos": [...]
    # }
    if isinstance(payload.get("memos"), list):

        # JSON 전체에 기본 문서 유형이 지정되어 있는 경우 가져옵니다.
        #
        # document_type을 우선 확인하고,
        # 없으면 business_type_name을 확인합니다.
        default_type = str(
            payload.get("document_type")
            or payload.get("business_type_name")
            or ""
        ).strip()

        # 최종적으로 반환할 메모 목록입니다.
        memos = []

        # JSON의 "memos" 목록을 하나씩 확인합니다.
        for source in payload["memos"]:

            # 실제 메모 데이터가 dictionary 형태인 경우만 처리합니다.
            if isinstance(source, dict):

                # 원본 데이터를 복사하여 가져옵니다.
                memo = dict(source)

                # JSON 전체에 기본 문서 유형이 있고
                # "전체"가 아니라면 개별 메모에 document_type을 추가합니다.
                #
                # setdefault()를 사용하므로
                # 메모 자체에 document_type이 이미 있다면 기존 값을 유지합니다.
                if default_type and default_type != "전체":
                    memo.setdefault("document_type", default_type)

                # 완성된 메모를 결과 목록에 추가합니다.
                memos.append(memo)

        # 추출된 메모 목록을 반환합니다.
        return memos

    # 문서 유형별로 메모가 그룹화된 JSON인지 확인합니다.
    #
    # 예:
    # {
    #     "document_types": {
    #         "회의": [...],
    #         "업무": [...]
    #     }
    # }
    if isinstance(payload.get("document_types"), dict):

        # 최종적으로 반환할 메모 목록입니다.
        memos = []

        # 문서 유형과 해당 문서 유형의 메모 목록을 하나씩 확인합니다.
        for doc_type, type_memos in payload["document_types"].items():

            # 해당 문서 유형의 값이 리스트가 아니면 건너뜁니다.
            if not isinstance(type_memos, list):
                continue

            # 해당 문서 유형에 포함된 메모를 하나씩 확인합니다.
            for source in type_memos:

                # 메모가 dictionary 형태인 경우만 처리합니다.
                if isinstance(source, dict):

                    # 원본 데이터를 복사합니다.
                    memo = dict(source)

                    # 개별 메모에 document_type이 없다면
                    # 현재 그룹의 문서 유형을 기본값으로 넣습니다.
                    memo.setdefault("document_type", doc_type)

                    # 완성된 메모를 결과 목록에 추가합니다.
                    memos.append(memo)

        # 모든 문서 유형의 메모를 하나의 목록으로 합쳐 반환합니다.
        return memos

    # 하나의 메모 자체가 JSON의 최상위에 있는 경우입니다.
    #
    # 예:
    # {
    #     "document_type": "회의",
    #     "assistant": "회의 내용입니다."
    # }
    if payload.get("document_type") and payload.get("assistant"):
        return [dict(payload)]

    # 위에서 지원하는 어떤 JSON 구조에도 해당하지 않으면
    # 등록할 메모를 찾을 수 없다는 오류를 발생시킵니다.
    raise ValueError("등록할 메모 목록을 찾을 수 없습니다.")


def decode_json_data(data: bytes) -> str:
    """
    JSON 파일의 바이너리 데이터를 문자열로 변환합니다.

    먼저 UTF-8(BOM 포함)으로 읽고,
    UTF-8로 해석할 수 없는 경우 CP949로 다시 시도합니다.

    한국어 Windows 환경에서 만들어진 JSON 파일도
    읽을 수 있도록 대비한 함수입니다.
    """

    # 먼저 UTF-8-SIG 방식으로 디코딩합니다.
    # UTF-8-SIG는 일반 UTF-8뿐만 아니라 UTF-8 BOM도 처리할 수 있습니다.
    try:
        return data.decode("utf-8-sig")

    # UTF-8로 디코딩할 수 없는 경우 UnicodeDecodeError가 발생합니다.
    except UnicodeDecodeError:

        # 한국어 Windows 환경에서 흔히 사용하는 CP949 인코딩으로
        # 다시 디코딩합니다.
        return data.decode("cp949")
