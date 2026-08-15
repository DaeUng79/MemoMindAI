"""Question classification and memo-context assembly."""

from dataclasses import dataclass

from .llm_client import LLMClient, extract_json_object
from .logging_utils import trim_text
from .repository import MemoRepository


@dataclass(frozen=True)
class SearchContext:
    context: str | None
    selected_type: str
    result_count: int


class ContextService:
    CONFIDENCE_THRESHOLD = 75

    def __init__(self, repository: MemoRepository, llm: LLMClient, logger):
        self.repository = repository
        self.llm = llm
        self.log = logger

    async def search(self, user_question: str, turn_id: int) -> SearchContext:
        existing_types = self.repository.types()
        self.log("CONTEXT", f"등록메모 {len(existing_types)}개", turn_id)
        self.log("QUESTION", trim_text(user_question, 160), turn_id)
        if not existing_types:
            return SearchContext(None, "일반답변", 0)

        normalized_question = " ".join(user_question.casefold().split())
        direct_matches = [
            item
            for item in existing_types
            if " ".join(item.casefold().split()) in normalized_question
        ]

        selected_type = "일반답변"
        confidence = 0
        if direct_matches:
            # A longer type wins when one registered type contains another.
            selected_type = max(direct_matches, key=len)
            confidence = 100
            self.log(
                "TYPE",
                f"직접일치={selected_type} / 신뢰도={confidence} / AI 분류 생략",
                turn_id,
            )
        else:
            prompt = f"""
당신의 역할은 사용자의 [질문]을 분석하여 가장 적절한 '타입' 하나를 선택하는 것입니다.

[분류 규칙]
1. [타입 목록] 중에서 질문의 의도와 가장 유사한 단어 하나를 선택하세요.
2. 적절한 타입을 찾기 어렵거나 목록에 없다면 "일반답변"을 선택하세요.
3. 애매하면 반드시 "일반답변"을 선택하세요. 억지 매칭 금지.

[데이터]
- 질문: {user_question}
- 타입 목록: {existing_types + ["일반답변"]}

[응답 양식]
반드시 JSON 객체 한 개만 출력하세요. 다른 텍스트는 출력하지 마세요.
confidence는 선택이 확실할수록 높은 0~100 사이의 정수입니다.
{{"type": "타입명", "confidence": 85}}
"""
            try:
                data = extract_json_object(await self.llm.complete(prompt))
                selected_type = str(data.get("type", "일반답변")).strip()
                confidence = max(0, min(100, int(data.get("confidence", 0) or 0)))
                self.log("TYPE", f"AI선택={selected_type} / 신뢰도={confidence}", turn_id)
            except Exception as error:
                self.log("TYPE", f"타입 추출 실패: {error}", turn_id)

        normalized = {item.casefold(): item for item in existing_types}
        normalized_selected = selected_type.casefold()
        if selected_type != "일반답변" and normalized_selected not in normalized:
            self.log("TYPE", f"목록 외 타입('{selected_type}') -> 일반답변으로 변경", turn_id)
            selected_type = "일반답변"
        elif selected_type != "일반답변":
            selected_type = normalized[normalized_selected]
            if confidence < self.CONFIDENCE_THRESHOLD:
                self.log("TYPE", f"신뢰도 {confidence} < {self.CONFIDENCE_THRESHOLD} -> 일반답변", turn_id)
                selected_type = "일반답변"

        if selected_type == "일반답변":
            return SearchContext(None, selected_type, 0)

        self.log("DB", f"'{selected_type}' 메모 조회 시작", turn_id)
        results = self.repository.find_by_type(selected_type)
        if not results:
            self.log("DB", "조회 결과 없음", turn_id)
            return SearchContext(None, selected_type, 0)

        context_parts = []
        for record in results:
            doc_type = record.get("document_type", "기타")
            timestamp = (record.get("timestamp", "") or "").split(".")[0]
            content = (record.get("assistant", "") or "").strip()
            context_parts.append(f"■ [{doc_type}] ({timestamp})\n{content}")
        context = "\n\n".join(context_parts)
        self.log("DB", f"조회 결과 {len(results)}건", turn_id)
        self.log("CONTEXT", f"컨텍스트 길이: {len(context)}자", turn_id)
        return SearchContext(context, selected_type, len(results))
