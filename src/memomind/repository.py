# 메모마인드(MemoMind) 데이터를 컴퓨터에 저장하고 관리하는 파일입니다

import datetime as dt
from pathlib import Path
from typing import Callable, Iterable

# tinydb 라이브러리에서 필요한 기능들을 가져옵니다.
from tinydb import TinyDB, where

# 프로그램을 처음 켠 사람에게 보여줄 기본 사용 설명서 내용입니다.
DEFAULT_MEMO = (
    "메모마인드(MemoMind) 사용 설명서\r\n\n"
    "1. 새로운 메모 등록하기\n\n"
    "AI가 답변할 때 참고할 수 있도록 프로젝트별 데이터를 등록하는 과정입니다.\r\n"
    "메인 화면에서 [메모관리] 버튼을 클릭합니다.\r\n"
    "프로젝트명 입력창: 해당 메모가 속할 분류나 프로젝트 이름을 입력합니다. (예: 인사 규정, 연말정산)\r\n"
    "메모내용 입력창: AI가 기억해야 할 구체적인 정보와 관련 사이트 링크예시 "
    "https://google.com 입력합니다.\r\n"
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

    # 1. DB 초기화: 데이터베이스 파일을 열거나 새로 만듭니다.
    def __init__(self, db_path: Path):   
        # 저장할 폴더가 없으면 자동으로 만들어 줍니다.
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # TinyDB를 연결합니다. 한글 깨짐 방지(encoding/ensure_ascii)와 보기 편하게 줄바꿈(indent)을 설정했습니다.
        self._db = TinyDB(db_path, ensure_ascii=False, encoding="utf-8", indent=4)

    #2. 초기 세팅: DB가 완전히 비어있다면 사용 설명서를 자동으로 넣어줍니다.
    def initialize_default(self) -> None:    
        if len(self._db) == 0:
            self.insert("메모마인드", DEFAULT_MEMO)

    #3. 전체 조회: 저장된 모든 메모 데이터를 리스트로 가져옵니다.
    def all(self) -> list:
        return self._db.all()
    
    #4. 조건 검색: 사용자가 원하는 복잡한 조건으로 메모를 찾습니다.
    def search(self, condition: Callable) -> list:
        return self._db.search(condition)

    # 5. 종류별 검색: '인사 규정'이나 '연말정산'처럼 딱 맞는 프로젝트 메모만 찾습니다.
    def find_by_type(self, document_type: str) -> list:
        """Return records whose document type exactly matches the given value."""
        return self._db.search(where("document_type") == document_type)

    # 6. 존재 여부 확인: 조건에 맞는 메모가 DB에 있는지 True/False로 알려줍니다.
    def contains(self, condition: Callable) -> bool:
        return self._db.contains(condition)

    #7. 메모 추가: 새로운 메모를 DB에 저장합니다."""
    def insert(self, document_type: str, assistant: str, timestamp: str | None = None, **extra) -> int:
    # 저장할 데이터를 딕셔너리 형태로 예쁘게 정렬합니다.
        record = {
            "document_type": document_type,
            "assistant": assistant,
            "timestamp": timestamp or str(dt.datetime.now()), #컴퓨터의 현재 시간을 문자열로 넣습니다.
            **extra,
        }
        # DB에 저장하고 고유 번호(ID)를 반환합니다.
        return self._db.insert(record)
    
    #8. 메모 수정: 저장된 특정 메모의 내용을 새 내용으로 바꿉니다.
    def update_content(self, doc_id: int, content: str) -> None:
        self._db.update({"assistant": content}, doc_ids=[doc_id])

    #9. 메모 삭제: 쓸모없어진 메모를 고유 번호(ID)로 찾아서 지웁니다.
    def remove(self, doc_id: int) -> None:
        self._db.remove(doc_ids=[doc_id])

    #10. 카테고리 목록: 중복 없이 지금까지 등록된 프로젝트 이름만 가나다순으로 뽑아줍니다.
    def types(self) -> list[str]:
        return sorted(
            {
                str(doc.get("document_type", "")).strip()
                for doc in self._db.all()
                if str(doc.get("document_type", "")).strip()
            }
        )
    #11. DB 닫기: 안전하게 데이터베이스 연결을 종료합니다
    def close(self) -> None:
        self._db.close()
