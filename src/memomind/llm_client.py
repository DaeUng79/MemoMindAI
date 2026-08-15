"""OpenAI-compatible llama.cpp HTTP client."""

import json
import re
from collections.abc import AsyncIterator

import httpx


def extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except (TypeError, ValueError):
            return {}


class LLMClient:
    CONNECT_TIMEOUT_SECONDS = 5.0
    READ_TIMEOUT_SECONDS = 180.0

    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url
        self.model_name = model_name
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=self.CONNECT_TIMEOUT_SECONDS,
                read=self.READ_TIMEOUT_SECONDS,
                write=30.0,
                pool=10.0,
            )
        )

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def complete(self, prompt: str, temperature: float = 0.1, max_tokens: int = 100) -> str:
        response = await self._client.post(
            self.api_url,
            json={
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        body = response.json()
        return body.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def stream(self, prompt: str, temperature: float = 0.2) -> AsyncIterator[str]:
        async with self._client.stream(
            "POST",
            self.api_url,
            json={
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "temperature": temperature,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                    chunk = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                except (TypeError, ValueError):
                    chunk = ""
                if chunk:
                    yield chunk

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()
