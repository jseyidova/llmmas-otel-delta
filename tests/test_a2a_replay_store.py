import json
import tempfile
import unittest
from pathlib import Path

from llmmas_otel.injection import a2a_replay


class TestA2AReplay(unittest.TestCase):
    def setUp(self) -> None:
        a2a_replay.disable()

    def tearDown(self) -> None:
        a2a_replay.disable()

    def test_replay_applies_truncation_and_updates_message(self) -> None:
        record = {
            "segment": {"name": "Coding", "order": 1},
            "direction": "receive",
            "message_id": "mid-1",
            "source_agent_id": "Chief Technology Officer",
            "target_agent_id": "Programmer",
            "edge_id": "Chief Technology Officer->Programmer",
            "body": "alpha buying them, collecting rent, omega",
        }
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "a2a.jsonl"
            trace.write_text(json.dumps(record) + "\n", encoding="utf-8")

            fault = {
                "enabled": True,
                "fault_type": "truncate_message",
                "selector": {
                    "segment_name": "Coding",
                    "edge_id": "Chief Technology Officer->Programmer",
                    "direction": "receive",
                    "occurrence": 0,
                },
                "truncate": {
                    "mode": "cut_after_text",
                    "cut_after_text": "buying them, collecting rent,",
                },
            }
            a2a_replay.enable(str(trace), fault_spec=fault)

            applied: list[str] = []

            body = a2a_replay.apply_body(
                session_id="s1",
                direction="receive",
                segment_name="Coding",
                segment_order=1,
                source_agent_id="Chief Technology Officer",
                target_agent_id="Programmer",
                edge_id="Chief Technology Officer->Programmer",
                message_id="mid-1",
                live_body="live body should be replaced",
                apply_to_message=applied.append,
            )

            self.assertEqual(body, "alpha buying them, collecting rent,")
            self.assertEqual(applied, ["alpha buying them, collecting rent,"])
            inj = a2a_replay.last_injection()
            self.assertIsNotNone(inj)
            assert inj is not None
            self.assertTrue(inj.injected)

    def test_replay_allows_missing_segment_on_baseline_record(self) -> None:
        record = {
            "segment": None,
            "direction": "receive",
            "message_id": "mid-1",
            "source_agent_id": "Chief Executive Officer",
            "target_agent_id": "Chief Product Officer",
            "edge_id": "Chief Executive Officer->Chief Product Officer",
            "body": "baseline body",
        }
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "a2a.jsonl"
            trace.write_text(json.dumps(record) + "\n", encoding="utf-8")
            a2a_replay.enable(str(trace), strict=True)

            body = a2a_replay.apply_body(
                session_id="s1",
                direction="receive",
                segment_name="DemandAnalysis",
                segment_order=0,
                source_agent_id="Chief Executive Officer",
                target_agent_id="Chief Product Officer",
                edge_id="Chief Executive Officer->Chief Product Officer",
                message_id="msg-live",
                live_body="ignored",
            )
            self.assertEqual(body, "baseline body")

    def test_replay_stops_after_fault_so_later_hooks_are_live(self) -> None:
        records = [
            {
                "segment": {"name": "Coding", "order": 1},
                "direction": "send",
                "message_id": "mid-1",
                "source_agent_id": "A",
                "target_agent_id": "B",
                "edge_id": "A->B",
                "body": "first send",
            },
            {
                "segment": {"name": "Coding", "order": 1},
                "direction": "receive",
                "message_id": "mid-2",
                "source_agent_id": "Chief Technology Officer",
                "target_agent_id": "Programmer",
                "edge_id": "Chief Technology Officer->Programmer",
                "body": "alpha buying them, collecting rent, omega",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "a2a.jsonl"
            trace.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
            fault = {
                "enabled": True,
                "fault_type": "truncate_message",
                "selector": {
                    "segment_name": "Coding",
                    "edge_id": "Chief Technology Officer->Programmer",
                    "direction": "receive",
                    "occurrence": 0,
                },
                "truncate": {
                    "mode": "cut_after_text",
                    "cut_after_text": "buying them, collecting rent,",
                },
            }
            a2a_replay.enable(str(trace), fault_spec=fault)

            a2a_replay.apply_body(
                session_id="s1",
                direction="send",
                segment_name="Coding",
                segment_order=1,
                source_agent_id="A",
                target_agent_id="B",
                edge_id="A->B",
                message_id="mid-1",
                live_body="ignored",
            )
            fault_body = a2a_replay.apply_body(
                session_id="s1",
                direction="receive",
                segment_name="Coding",
                segment_order=1,
                source_agent_id="Chief Technology Officer",
                target_agent_id="Programmer",
                edge_id="Chief Technology Officer->Programmer",
                message_id="mid-2",
                live_body="ignored",
            )
            self.assertEqual(fault_body, "alpha buying them, collecting rent,")
            self.assertFalse(a2a_replay.is_replaying())

            live = a2a_replay.apply_body(
                session_id="s1",
                direction="send",
                segment_name="Coding",
                segment_order=1,
                source_agent_id="A",
                target_agent_id="B",
                edge_id="A->B",
                message_id="mid-3",
                live_body="live after fault",
            )
            self.assertIsNone(live)


if __name__ == "__main__":
    unittest.main()
