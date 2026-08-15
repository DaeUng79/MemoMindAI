import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memomind.context_service import ContextService  # noqa: E402
from memomind.handover import build_payload, extract_memos  # noqa: E402
from memomind.llm_client import extract_json_object  # noqa: E402
from memomind.logging_utils import EventLogger  # noqa: E402
from memomind.repository import MemoRepository  # noqa: E402


class FakeLLM:
    def __init__(self):
        self.call_count = 0

    async def complete(self, prompt):
        self.call_count += 1
        return '{"type": "인사", "confidence": 92}'


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = MemoRepository(Path(self.temp_dir.name) / "memo.json")

    def tearDown(self):
        self.repository.close()
        self.temp_dir.cleanup()

    def test_repository_crud_and_types(self):
        doc_id = self.repository.insert("인사", "휴가 규정", timestamp="2026-01-01 10:00:00")
        self.assertEqual(self.repository.types(), ["인사"])
        self.repository.update_content(doc_id, "수정된 휴가 규정")
        self.assertEqual(self.repository.all()[0]["assistant"], "수정된 휴가 규정")
        self.repository.remove(doc_id)
        self.assertEqual(self.repository.all(), [])

    def test_handover_round_trip(self):
        self.repository.insert("인사", "휴가 규정", timestamp="2026-01-01 10:00:00")
        self.repository.insert("예산", "집행 절차", timestamp="2026-01-02 10:00:00")
        payload = build_payload(self.repository.all())
        restored = extract_memos(json.loads(json.dumps(payload, ensure_ascii=False)))
        self.assertEqual(payload["count"], 2)
        self.assertEqual({item["document_type"] for item in restored}, {"인사", "예산"})

    def test_extract_json_object_handles_fenced_response(self):
        parsed = extract_json_object('```json\n{"type": "인사", "confidence": 90}\n```')
        self.assertEqual(parsed["type"], "인사")

    def test_context_service_uses_ai_for_indirect_match(self):
        self.repository.insert("인사", "휴가 규정", timestamp="2026-01-01 10:00:00")
        llm = FakeLLM()
        result = asyncio.run(
            ContextService(self.repository, llm, EventLogger()).search("휴가를 알려줘", turn_id=1)
        )
        self.assertEqual(result.selected_type, "인사")
        self.assertEqual(result.result_count, 1)
        self.assertIn("휴가 규정", result.context)
        self.assertEqual(llm.call_count, 1)

    def test_direct_type_match_skips_llm_classification(self):
        self.repository.insert("인공지능서버", "GPU 서버 정보", timestamp="2026-01-01 10:00:00")
        llm = FakeLLM()
        result = asyncio.run(
            ContextService(self.repository, llm, EventLogger()).search(
                "인공지능서버 메모를 알려줘", turn_id=2
            )
        )
        self.assertEqual(result.selected_type, "인공지능서버")
        self.assertEqual(result.result_count, 1)
        self.assertIn("GPU 서버 정보", result.context)
        self.assertEqual(llm.call_count, 0)


if __name__ == "__main__":
    unittest.main()
