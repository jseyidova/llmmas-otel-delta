from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llmmas_otel.jaeger_trace import build_replay_artifacts, configure_replay_from_jaeger_trace, load_spans
from llmmas_otel.injection import a2a_replay
from llmmas_otel import replay_store


def _tag(key: str, value: object) -> dict:
    return {"key": key, "value": value, "type": "string"}


class TestJaegerTrace(unittest.TestCase):
    def tearDown(self) -> None:
        a2a_replay.disable()
        replay_store.disable_prefix_replay()

    def _sample_trace(self) -> dict:
        spans = [
            {
                "traceID": "t1",
                "spanID": "s0",
                "operationName": "llmmas.session",
                "startTime": 1000,
                "tags": [_tag("llmmas.session.id", "programdev::MonopolyGo")],
            },
            {
                "traceID": "t1",
                "spanID": "s1",
                "operationName": "send A->B",
                "startTime": 2000,
                "tags": [
                    _tag("llmmas.hook.index", 1),
                    _tag("llmmas.hook.type_index", 1),
                    _tag("llmmas.source_agent.id", "A"),
                    _tag("llmmas.target_agent.id", "B"),
                    _tag("llmmas.edge.id", "A->B"),
                    _tag("llmmas.message.id", "m1"),
                    _tag("llmmas.message.direction", "send"),
                    _tag("llmmas.message.body", "hello"),
                    _tag("llmmas.message.sha256", "abc"),
                    _tag("llmmas.segment.name", "Coding"),
                    _tag("llmmas.segment.order", 1),
                ],
            },
            {
                "traceID": "t1",
                "spanID": "s2",
                "operationName": "chat.completions qwen",
                "startTime": 3000,
                "tags": [
                    _tag("llmmas.hook.index", 2),
                    _tag("llmmas.hook.type_index", 1),
                    _tag("gen_ai.operation.name", "chat.completions"),
                    _tag("gen_ai.request.model", "qwen"),
                    _tag("llmmas.llm.input", '[{"role":"user","content":"hi"}]'),
                    _tag("llmmas.llm.input.sha256", "deadbeef"),
                    _tag("llmmas.llm.output", "world"),
                    _tag("llmmas.llm.output.sha256", "cafebabe"),
                ],
            },
        ]
        return {"data": [{"traceID": "t1", "spans": spans}]}

    def test_build_replay_artifacts(self) -> None:
        spans = load_spans(self._sample_trace())
        llm, a2a, events = build_replay_artifacts(spans)
        self.assertEqual(len(llm), 1)
        self.assertEqual(llm[0]["hook_index"], 2)
        self.assertEqual(len(a2a), 1)
        self.assertEqual(a2a[0]["hook_index"], 1)
        self.assertEqual(len(events), 2)

    def test_configure_replay_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jaeger.json"
            path.write_text(json.dumps(self._sample_trace()), encoding="utf-8")
            info = configure_replay_from_jaeger_trace(
                path,
                replay_until_hook_index=3,
            )
            self.assertEqual(info["llm_record_count"], 1)
            self.assertTrue(replay_store.is_prefix_replay_enabled())
            self.assertTrue(a2a_replay.is_enabled())


if __name__ == "__main__":
    unittest.main()
