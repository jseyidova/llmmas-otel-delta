from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llmmas_otel.hook_timeline_store import (
    enable_hook_timeline,
    disable_hook_timeline,
    find_fault_hook_index,
    load_timeline,
    suggest_replay_until_hook_index,
    write_hook,
)
from llmmas_otel import message_store


class TestHookTimelineStore(unittest.TestCase):
    def tearDown(self) -> None:
        disable_hook_timeline()
        message_store.disable_message_store()

    def test_find_fault_and_suggest_replay_until(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "timeline.jsonl"
            enable_hook_timeline(str(path))
            with message_store.session_context("S1"):
                with message_store.segment_context("Coding", 1):
                    write_hook(
                        hook_type="llm_call",
                        hook_index=10,
                        hook_type_index=1,
                        model="qwen",
                    )
                    write_hook(
                        hook_type="a2a_receive",
                        hook_index=11,
                        hook_type_index=1,
                        direction="receive",
                        edge_id="Chief Technology Officer->Programmer",
                        source_agent_id="Chief Technology Officer",
                        target_agent_id="Programmer",
                    )
                    write_hook(
                        hook_type="llm_call",
                        hook_index=12,
                        hook_type_index=2,
                        model="qwen",
                    )
            disable_hook_timeline()

            timeline = load_timeline(str(path))
            fault_spec = {
                "selector": {
                    "segment_name": "Coding",
                    "edge_id": "Chief Technology Officer->Programmer",
                    "direction": "receive",
                    "occurrence": 0,
                }
            }
            fault_hook = find_fault_hook_index(timeline, fault_spec)
            self.assertEqual(fault_hook, 11)
            self.assertEqual(suggest_replay_until_hook_index(fault_hook, timeline), 12)

            rows = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 3)
            self.assertEqual(json.loads(rows[1])["hook_index"], 11)
