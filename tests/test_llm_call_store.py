from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llmmas_otel import llm_call_store, message_store


class TestLlmCallStore(unittest.TestCase):
    def tearDown(self) -> None:
        llm_call_store.disable_llm_call_store()
        message_store.disable_message_store()

    def test_write_call_appends_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "llm-calls.jsonl"
            llm_call_store.enable_llm_call_store(str(path))
            with message_store.session_context("S1"):
                with message_store.segment_context("Coding", 1):
                    llm_call_store.write_call(
                        hook_index=5,
                        hook_type_index=2,
                        provider_name="ollama",
                        model="qwen",
                        operation_name="chat.completions",
                        request_id="r1",
                        input_text='[{"role":"user","content":"hi"}]',
                        output_text="hello",
                        replay_used=False,
                    )

            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["kind"], "llm_call")
            self.assertEqual(row["hook_index"], 5)
            self.assertEqual(row["output"], "hello")
            self.assertFalse(row["replay_used"])
