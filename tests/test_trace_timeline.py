from __future__ import annotations

import json
import unittest
from pathlib import Path

from llmmas_otel.injection.trace_timeline import (
    build_timeline,
    format_message_content_block,
    format_timeline,
)

FIXTURE = Path(__file__).parent / "fixtures" / "jaeger_minimal_a2a.json"


class TraceTimelineTest(unittest.TestCase):
    def test_build_timeline_hook_numbers(self) -> None:
        entries = build_timeline(FIXTURE)
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0].hook_number, 1)
        self.assertEqual(entries[0].hook_type, "a2a_send")
        self.assertEqual(entries[0].message, "SEND_BODY_1")
        self.assertEqual(entries[3].hook_number, 4)

    def test_format_text_contains_phase_and_agents(self) -> None:
        text = format_timeline(FIXTURE, output_format="text", max_message_chars=500)
        self.assertIn("Hook #1", text)
        self.assertIn("Planner", text)
        self.assertIn("SEND_BODY_1", text)

    def test_format_message_content_block(self) -> None:
        block = format_message_content_block("line one\nline two")
        self.assertIn("message_content: {", block)
        self.assertIn("\t\t\tline one", block)
        self.assertIn("\t}", block)
        self.assertNotIn("```", block)

    def test_format_md_uses_message_block_not_fences(self) -> None:
        md = format_timeline(FIXTURE, output_format="md", max_message_chars=500)
        self.assertIn("message_content: {", md)
        self.assertNotIn("```", md)

    def test_format_json(self) -> None:
        raw = format_timeline(FIXTURE, output_format="json")
        data = json.loads(raw)
        self.assertEqual(data["hook_count"], 4)
        self.assertEqual(data["hooks"][0]["hook_number"], 1)


if __name__ == "__main__":
    unittest.main()
