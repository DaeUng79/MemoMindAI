"""TinyDB persistence boundary for memo records."""

import datetime as dt
from pathlib import Path
from typing import Callable, Iterable

from tinydb import TinyDB, where


DEFAULT_MEMO = (
    "메모마인드(MemoMind) 사용 설명서\r\n\n"
    "1. 새로운 메모 등록하기\n\n"
    "AI가 답변할 때 참고할 수 있도록 프로젝트별 데이터를 등록하는 과정입니다.\r\n"
    "메인 화면에서 [메모관리] 버튼을 클릭합니다.\r\n"
    "프로젝트명 입력창: 해당 메모가 속할 분류나 프로젝트 이름을 입력합니다. (예: 인사 규정, 연말정산)\r\n"
    "메모내용 입력창: AI가 기억해야 할 구체적인 정보와 관련 사이트 링크예시 "
    "(https://m.site.naver.com/1H68i) 입력합니다.\r\n"
    "작성이 완료되면 저장 버튼을 눌러 등록을 마칩니다.\r\n\n"
    "2. AI에게 질문하기\r\n\n"
    "등록된 정보를 바탕으로 AI와 대화할 수 있습니다. \r\n"
    "질문방법은 '프로젝트명 질문내용' 형식으로 물어보세요\r\n"
    "예시 '메모마인드 사용방법을 알려줘'\r\n"
    "내부에 설치된 AI가 외부에 정보 유출 없이 등록된 메모 데이터를 바탕으로 정확한 답변을 제공합니다.\r\n\n"
    "3. 보안 및 특이사항\r\n\n"
    "완벽한 보안: 등록된 메모는 사용자 PC나 내부 서버에서만 처리됩니다.\r\n"
    "정확도 향상: 질문과 관련된 내용을 프로젝트별로 상세히 기록할수록 AI의 답변이 더욱 정교해집니다."
)


class MemoRepository:
    """Own TinyDB lifecycle and expose memo-oriented operations."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(db_path, ensure_ascii=False, encoding="utf-8", indent=4)

    def initialize_default(self) -> None:
        if len(self._db) == 0:
            self.insert("메모마인드", DEFAULT_MEMO)

    def all(self) -> list:
        return self._db.all()

    def search(self, condition: Callable) -> list:
        return self._db.search(condition)

    def find_by_type(self, document_type: str) -> list:
        """Return records whose document type exactly matches the given value."""
        return self._db.search(where("document_type") == document_type)

    def contains(self, condition: Callable) -> bool:
        return self._db.contains(condition)

    def insert(self, document_type: str, assistant: str, timestamp: str | None = None, **extra) -> int:
        record = {
            "document_type": document_type,
            "assistant": assistant,
            "timestamp": timestamp or str(dt.datetime.now()),
            **extra,
        }
        return self._db.insert(record)

    def update_content(self, doc_id: int, content: str) -> None:
        self._db.update({"assistant": content}, doc_ids=[doc_id])

    def remove(self, doc_id: int) -> None:
        self._db.remove(doc_ids=[doc_id])

    def types(self) -> list[str]:
        return sorted(
            {
                str(doc.get("document_type", "")).strip()
                for doc in self._db.all()
                if str(doc.get("document_type", "")).strip()
            }
        )

    def close(self) -> None:
        self._db.close()
