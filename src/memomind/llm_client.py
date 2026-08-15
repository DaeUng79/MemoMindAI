# llama.cpp 서버와 통신하는 HTTP 클라이언트입니다

import json
import re
from collections.abc import AsyncIterator

import httpx


def extract_json_object(text: str) -> dict:
    """
    LLM이 반환한 문자열에서 JSON 객체를 찾아 Python dict로 변환합니다.

    LLM은 JSON만 반환하도록 요청해도 Markdown 코드 블록이나
    설명 문장을 함께 반환할 수 있기 때문에 여러 형태를 처리합니다.

    JSON을 찾지 못하거나 변환에 실패하면 빈 dict({})를 반환합니다.
    """

    # 입력값의 앞뒤 공백과 줄바꿈을 제거합니다.
    raw = (text or "").strip()

    # 빈 문자열이면 분석할 JSON이 없으므로 빈 dict를 반환합니다.
    if not raw:
        return {}

    # LLM이 JSON을 Markdown 코드 블록으로 감싸서 반환하는 경우를 처리합니다.
    if raw.startswith("```"):
        # 코드 블록을 감싸고 있는 ` 문자를 제거합니다.
        raw = raw.strip("`")

        # 시작 부분에 "json"이라는 언어 표시가 있으면 제거합니다.
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    # 정리된 문자열 전체가 정상적인 JSON인지 먼저 시도합니다.
    try:
        return json.loads(raw)

    # JSON 형식이 아니면 문자열 안에서 JSON 객체를 다시 찾아봅니다.
    except (TypeError, ValueError):
        # "결과는 다음과 같습니다: {\"name\": \"홍길동\"}"
        # 위 문자열에서 {"name": "홍길동"} 부분을 추출합니다.
        match = re.search(r"\{.*\}", raw, re.DOTALL)

        # JSON처럼 보이는 부분을 찾지 못하면 빈 dict를 반환합니다.
        if not match:
            return {}

        # 찾은 JSON 부분만 다시 JSON으로 변환합니다.
        try:
            return json.loads(match.group(0))

        # 찾은 내용도 올바른 JSON이 아니면 빈 dict를 반환합니다.
        except (TypeError, ValueError):
            return {}


class LLMClient:
    """
    llama.cpp 서버와 통신하기 위한 비동기 HTTP 클라이언트입니다.
    OpenAI API와 비슷한 방식으로 llama.cpp에 요청할 수 있습니다.
    주요 기능:
    - complete(): LLM의 전체 답변을 한 번에 받습니다.
    - stream(): LLM의 답변을 생성되는 즉시 조금씩 받습니다.
    - close(): HTTP 연결을 종료합니다.
    """

    # llama.cpp 서버에 연결을 시도할 때 최대 5초까지 기다립니다.
    CONNECT_TIMEOUT_SECONDS = 5.0

    # 서버에 연결된 후 LLM의 응답을 기다리는 최대 시간입니다.
    # LLM은 답변 생성에 시간이 걸릴 수 있기 때문에 180초로 설정합니다.
    READ_TIMEOUT_SECONDS = 180.0

    def __init__(self, api_url: str, model_name: str):
        """
        LLMClient를 생성합니다.
        api_url:
            llama.cpp의 OpenAI 호환 API 주소입니다.
            예: http://localhost:8080/v1/chat/completions
        model_name:
            llama.cpp 서버에서 사용할 모델 이름입니다.
        """

        self.api_url = api_url

        self.model_name = model_name

        # 비동기 HTTP 통신을 담당하는 httpx 클라이언트를 생성합니다.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                # 서버에 연결할 때 최대 5초까지 기다립니다.
                connect=self.CONNECT_TIMEOUT_SECONDS,

                # 서버가 LLM 응답을 보내기를 최대 180초까지 기다립니다.
                read=self.READ_TIMEOUT_SECONDS,

                # 서버로 요청 데이터를 전송할 때 최대 30초까지 기다립니다.
                write=30.0,

                # HTTP 연결 풀에서 연결을 사용할 수 있을 때까지 최대 10초까지 기다립니다.
                pool=10.0,
            )
        )

    @property
    def is_closed(self) -> bool:
        """
        HTTP 클라이언트 연결이 종료되었는지 확인합니다.

        True:
            HTTP 클라이언트가 이미 닫혀 있습니다.

        False:
            아직 사용할 수 있는 상태입니다.
        """

        # httpx 클라이언트의 현재 연결 상태를 그대로 반환합니다.
        return self._client.is_closed

    # 메모에 등록된 프로젝트을 판단하기위한 LLM 사용입니다. 프로젝트명만 추출하면 되기에 max_tokens를 100으로 제한했습니다.
    async def complete(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 100,
    ) -> str:

        # llama.cpp의 OpenAI 호환 API에 POST 요청을 보냅니다.
        response = await self._client.post(
            self.api_url,
            # OpenAI Chat Completions API와 호환되는 형식으로 데이터를 전달합니다.
            json={
                "model": self.model_name,

                # 사용자의 프롬프트를 user 메시지로 전달합니다.
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "stream": False,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )

        # HTTP 상태 코드가 오류라면 예외를 발생시킵니다. 예: 404, 500, 503 등의 서버 오류를 감지합니다.
        response.raise_for_status()

        # 서버에서 받은 JSON 응답을 Python 객체로 변환합니다.
        body = response.json()

        # OpenAI 호환 응답 구조에서 실제 LLM 답변 텍스트만 추출합니다.
        #
        # 일반적인 응답 구조:
        # {
        #     "choices": [
        #         {
        #             "message": {
        #                 "content": "LLM의 답변"
        #             }
        #         }
        #     ]
        # }
        #
        # 필요한 데이터가 없으면 오류 대신 빈 문자열을 반환합니다.
        return body.get("choices", [{}])[0].get("message", {}).get("content", "")
    
    #채팅 UI에서 ChatGPT처럼 답변이 실시간으로 나타나게 할 때 사용합니다.
    async def stream(
        self,
        prompt: str,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """
        채팅 UI에서 ChatGPT처럼 답변이 실시간으로 나타나게 할 때 사용합니다.
        """

        # HTTP 스트리밍 요청을 시작하고 서버가 데이터를 보내는 즉시 읽을 수 있습니다.
        async with self._client.stream(
            "POST",
            self.api_url,
            # OpenAI 호환 Chat Completions 요청 형식입니다.
            json={
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "stream": True,
                "temperature": temperature,
            },
        ) as response:

            # HTTP 오류가 발생했는지 확인합니다.
            response.raise_for_status()

            # 서버에서 전달되는 스트리밍 데이터를 한 줄씩 읽습니다.
            async for line in response.aiter_lines():

                # OpenAI 호환 SSE 응답에서 "data:"로 시작하는 줄만 처리합니다. 다른 종류의 줄은 무시합니다.
                if not line.startswith("data:"):
                    continue

                # "data:" 부분을 제거하고 실제 JSON 데이터만 가져옵니다.
                payload = line[len("data:") :].strip()

                # "[DONE]"은 서버가 스트리밍 응답을 모두 완료했다는 의미입니다.
                if payload == "[DONE]":
                    break

                # 각각의 스트리밍 데이터를 JSON으로 변환하고 새롭게 생성된 텍스트 조각을 추출합니다.
                try:
                    data = json.loads(payload)

                    # 스트리밍 응답에서 "delta.content"에 새로 생성된 텍스트가 들어 있습니다.
                    chunk = (
                        data.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )

                # 잘못된 JSON이 들어와도 전체 스트리밍을 중단하지 않고 해당 데이터만 빈 문자열로 처리합니다.
                except (TypeError, ValueError):
                    chunk = ""

                # 실제 텍스트가 있는 경우 호출한 쪽으로 즉시 전달합니다.
                if chunk:
                    yield chunk

    async def close(self) -> None:
        """
        HTTP 클라이언트를 안전하게 종료합니다.
        프로그램이 종료되거나 LLMClient를 더 이상 사용하지 않을 때
        호출하여 HTTP 연결과 관련된 리소스를 정리합니다.
        """

        # 아직 HTTP 클라이언트가 닫히지 않은 경우에만 종료합니다.
        if not self._client.is_closed:
            await self._client.aclose()
