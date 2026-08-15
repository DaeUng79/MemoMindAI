"""사용자 질문을 분류하고 관련 메모를 AI 답변용 컨텍스트로 구성합니다."""

from dataclasses import dataclass

from .llm_client import LLMClient, extract_json_object
from .logging_utils import trim_text
from .repository import MemoRepository


@dataclass(frozen=True)
class SearchContext:
    """
    질문 검색 결과와 AI 답변에 사용할 컨텍스트 정보를 담는 데이터 구조입니다.

    context:
        선택된 문서 유형에 해당하는 메모 내용입니다.
        관련 메모가 없거나 일반답변인 경우 None입니다.

    selected_type:
        질문에 대해 최종적으로 선택된 문서 유형입니다.

    result_count:
        검색된 관련 메모의 개수입니다.
    """

    # AI에게 전달할 관련 메모 내용입니다.
    # 관련 메모가 없으면 None입니다.
    context: str | None

    # 질문에서 최종 선택된 문서 유형입니다.
    selected_type: str

    # 선택된 문서 유형으로 검색된 메모의 개수입니다.
    result_count: int


class ContextService:
    """
    사용자의 질문을 분석하여 관련 메모를 찾고
    AI가 답변할 때 사용할 컨텍스트를 구성하는 서비스입니다.

    전체적인 처리 흐름:

    1. 저장된 메모의 문서 유형을 확인합니다.
    2. 사용자의 질문에 문서 유형이 직접 포함되어 있는지 확인합니다.
    3. 직접 일치하지 않으면 LLM에게 적절한 문서 유형을 선택하도록 요청합니다.
    4. AI가 선택한 유형이 실제 등록된 유형인지 확인합니다.
    5. AI의 분류 신뢰도가 충분히 높은지 확인합니다.
    6. 최종 유형이 결정되면 해당 유형의 메모를 DB에서 조회합니다.
    7. 조회한 메모를 하나의 컨텍스트 문자열로 합칩니다.
    """

    # AI가 선택한 문서 유형을 사용할 최소 신뢰도입니다.
    # 75보다 낮으면 AI의 분류를 믿지 않고 일반답변으로 처리합니다.
    CONFIDENCE_THRESHOLD = 75

    def __init__(self, repository: MemoRepository, llm: LLMClient, logger):
        """
        ContextService에 필요한 외부 기능을 연결합니다.

        repository:
            저장된 메모를 조회하는 저장소입니다.

        llm:
            사용자의 질문을 분석하고 문서 유형을 분류할 LLM 클라이언트입니다.

        logger:
            실행 과정과 결과를 기록하는 로그 함수입니다.
        """

        # 메모 데이터 조회를 담당하는 Repository를 저장합니다.
        self.repository = repository

        # 질문 분류에 사용할 LLM 클라이언트를 저장합니다.
        self.llm = llm

        # 실행 과정의 로그를 기록할 함수를 저장합니다.
        self.log = logger

    async def search(self, user_question: str, turn_id: int) -> SearchContext:
        """
        사용자의 질문과 관련된 메모를 찾아 AI 답변용 컨텍스트를 생성합니다.

        질문과 등록된 문서 유형이 직접 일치하면
        LLM을 호출하지 않고 바로 해당 유형을 선택합니다.

        직접 일치하는 유형이 없으면 LLM에게 질문을 분류하도록 요청합니다.
        """

        # 현재 저장되어 있는 모든 문서 유형을 가져옵니다.
        # 예:
        # ["회의", "업무", "프로젝트", "개인"]
        existing_types = self.repository.types()

        # 현재 등록된 문서 유형의 개수를 로그에 기록합니다.
        self.log("CONTEXT", f"등록메모 {len(existing_types)}개", turn_id)

        # 사용자가 입력한 질문을 로그에 기록합니다.
        # 너무 긴 질문은 trim_text()를 이용해 160자로 제한합니다.
        self.log("QUESTION", trim_text(user_question, 160), turn_id)

        # 등록된 문서 유형이 하나도 없다면
        # 검색할 관련 메모가 없으므로 일반답변으로 처리합니다.
        if not existing_types:
            return SearchContext(None, "일반답변", 0)

        # 질문을 비교하기 쉽게 정규화합니다.
        #
        # casefold():
        # 대소문자 차이를 무시할 수 있도록 문자열을 정리합니다.
        #
        # split() + join():
        # 여러 개의 공백이나 줄바꿈을 하나의 공백으로 정리합니다.
        normalized_question = " ".join(user_question.casefold().split())

        # 등록된 문서 유형 중 질문 안에 직접 포함되어 있는 유형을 찾습니다.
        #
        # 예:
        # 등록 유형: ["회의", "업무", "프로젝트"]
        # 질문: "지난 회의 내용을 알려줘"
        #
        # -> direct_matches = ["회의"]
        direct_matches = [
            item
            for item in existing_types
            if " ".join(item.casefold().split()) in normalized_question
        ]

        # 기본값은 "일반답변"입니다.
        # 어떤 유형인지 확실하게 판단하지 못하면
        # 관련 메모를 검색하지 않고 일반적인 AI 답변을 하도록 합니다.
        selected_type = "일반답변"

        # AI 분류 신뢰도의 기본값입니다.
        confidence = 0

        # 질문에 등록된 문서 유형이 직접 포함되어 있는 경우입니다.
        if direct_matches:

            # 여러 유형이 동시에 일치할 경우 가장 긴 유형을 선택합니다.
            #
            # 예:
            # ["업무", "업무 회의"]
            #
            # 질문에 "업무 회의"가 포함되어 있다면
            # 더 구체적인 "업무 회의"를 선택합니다.
            selected_type = max(direct_matches, key=len)

            # 사용자가 유형명을 직접 언급했으므로
            # 분류 신뢰도를 100으로 설정합니다.
            confidence = 100

            # 직접 일치했기 때문에 LLM을 호출할 필요가 없다는 로그를 남깁니다.
            self.log(
                "TYPE",
                f"직접일치={selected_type} / 신뢰도={confidence} / AI 분류 생략",
                turn_id,
            )

        else:
            # 질문에 등록된 문서 유형이 직접 포함되어 있지 않은 경우
            # LLM을 이용해 가장 적절한 문서 유형을 판단합니다.
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

            # LLM 호출 과정에서 오류가 발생할 수 있으므로
            # 전체 검색 기능이 중단되지 않도록 예외 처리합니다.
            try:

                # LLM에게 질문 분류를 요청합니다.
                # LLM의 전체 답변을 한 번에 받습니다.
                # extract_json_object():
                # LLM이 반환한 문자열에서 JSON 객체를 추출합니다.
                data = extract_json_object(await self.llm.complete(prompt))

                # LLM이 선택한 문서 유형을 가져옵니다.
                # 값이 없으면 "일반답변"을 사용합니다.
                selected_type = str(
                    data.get("type", "일반답변")
                ).strip()

                # LLM이 반환한 신뢰도를 숫자로 변환합니다.
                # 따라서 최종 신뢰도는 항상 0~100 사이가 됩니다.
                confidence = max(
                    0,
                    min(
                        100,
                        int(data.get("confidence", 0) or 0),
                    ),
                )

                # LLM의 분류 결과를 로그에 기록합니다.
                self.log(
                    "TYPE",
                    f"AI선택={selected_type} / 신뢰도={confidence}",
                    turn_id,
                )

            # LLM 응답 오류, JSON 변환 오류 등의 문제가 발생하면
            # 오류 내용을 로그로 남기고 기본값을 유지합니다.
            except Exception as error:
                self.log("TYPE", f"타입 추출 실패: {error}", turn_id)

        # 실제 등록된 문서 유형을 대소문자 구분 없이 비교할 수 있도록 dictionary를 만듭니다.
        # ["회의", "업무"] -> {"회의": "회의", "업무": "업무"}
        normalized = {
            item.casefold(): item
            for item in existing_types
        }

        # LLM 또는 직접 검색으로 선택된 유형도 대소문자 구분 없이 비교할 수 있도록 정규화합니다.
        normalized_selected = selected_type.casefold()

        # 선택된 유형이 "일반답변"이면서 실제 등록된 문서 유형 목록에도 없는 경우입니다.
        if (
            selected_type != "일반답변"
            and normalized_selected not in normalized
        ):

            # 등록되지 않은 유형은 안전하게 "일반답변"으로 변경합니다.
            self.log(
                "TYPE",
                f"목록 외 타입('{selected_type}') -> 일반답변으로 변경",
                turn_id,
            )

            selected_type = "일반답변"

        # 선택된 유형이 실제 등록된 유형인 경우입니다.
        elif selected_type != "일반답변":

            # 저장된 실제 문서 유형 이름을 사용하게 됩니다.
            selected_type = normalized[normalized_selected]

            # AI의 분류 신뢰도가 기준값보다 낮으면 잘못된 메모를 검색하지 않도록 일반답변으로 변경합니다.
            if confidence < self.CONFIDENCE_THRESHOLD:
                self.log(
                    "TYPE",
                    f"신뢰도 {confidence} < {self.CONFIDENCE_THRESHOLD} -> 일반답변",
                    turn_id,
                )

                selected_type = "일반답변"

        # 최종적으로 일반답변으로 결정되었다면 메모 검색을 하지 않고 바로 반환합니다.
        if selected_type == "일반답변":
            return SearchContext(None, selected_type, 0)

        # 선택된 문서 유형에 해당하는 메모를 DB에서 조회하기 시작한다는 로그입니다.
        self.log(
            "DB",
            f"'{selected_type}' 메모 조회 시작",
            turn_id,
        )

        # Repository를 통해 선택된 문서 유형의 메모를 가져옵니다.
        results = self.repository.find_by_type(selected_type)

        # 해당 유형의 메모가 없다면 컨텍스트 없이 결과를 반환합니다.
        if not results:
            self.log("DB", "조회 결과 없음", turn_id)
            return SearchContext(None, selected_type, 0)

        # 여러 개의 메모 내용을 하나의 컨텍스트 문자열로 만들기 위한 임시 리스트입니다.
        context_parts = []

        # 조회된 메모를 하나씩 확인합니다.
        for record in results:

            # 메모의 문서 유형을 가져옵니다. 값이 없으면 "기타"를 사용합니다.
            doc_type = record.get("document_type", "기타")

            # 메모의 timestamp에서 소수점 이하 시간을 제거합니다.
            # 2026-08-15T13:30:25.123 -> 2026-08-15T13:30:25
            timestamp = (
                record.get("timestamp", "") or ""
            ).split(".")[0]

            # AI가 생성한 메모 내용을 가져옵니다. 앞뒤 공백을 제거합니다.
            content = (
                record.get("assistant", "") or ""
            ).strip()

            # 하나의 메모를 AI가 읽기 쉬운 형태로 구성합니다.
            # ■ [회의] (2026-08-15T13:30:25) 오늘 회의에서는 프로젝트 일정을 논의했다.
            context_parts.append(
                f"■ [{doc_type}] ({timestamp})\n{content}"
            )

        # 각각의 메모 사이에 빈 줄을 넣어 하나의 컨텍스트 문자열로 합칩니다.
        context = "\n\n".join(context_parts)

        # DB에서 몇 건의 메모를 가져왔는지 로그에 기록합니다.
        self.log(
            "DB",
            f"조회 결과 {len(results)}건",
            turn_id,
        )

        # 최종적으로 만들어진 컨텍스트의 문자 수를 로그에 기록합니다.
        self.log(
            "CONTEXT",
            f"컨텍스트 길이: {len(context)}자",
            turn_id,
        )

        # AI 답변에 사용할 최종 SearchContext를 반환합니다.
        #
        # context:
        #   관련 메모를 합친 문자열
        #
        # selected_type:
        #   선택된 문서 유형
        #
        # len(results):
        #   검색된 메모 개수
        return SearchContext(
            context,
            selected_type,
            len(results),
        )
