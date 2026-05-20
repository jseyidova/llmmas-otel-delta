import copy
import unittest

from llmmas_otel.injection.a2a_fault import A2AFaultInjector


def _msg(**overrides) -> dict:
    base = {
        "session_id": "programdev::MonopolyGo",
        "segment": {"name": "Coding", "order": 3},
        "direction": "receive",
        "message_id": "m-1",
        "source_agent_id": "Chief Technology Officer",
        "target_agent_id": "Programmer",
        "edge_id": "Chief Technology Officer->Programmer",
        "body": (
            "Implement the board. Players roll dice, move, buy properties, "
            "buying them, collecting rent, and handle chance cards."
        ),
    }
    base.update(overrides)
    return base


class TestA2AFaultInjector(unittest.TestCase):
    def test_no_op_when_disabled(self) -> None:
        injector = A2AFaultInjector.disabled()
        original = _msg()
        result = injector.inject(original)
        self.assertEqual(result["body"], original["body"])
        self.assertIsNot(result, original)
        original["body"] = "mutated"
        self.assertNotEqual(result["body"], "mutated")

    def test_no_op_when_selector_does_not_match(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "fault_type": "truncate_message",
                "selector": {
                    "segment_name": "DemandAnalysis",
                    "edge_id": "Chief Technology Officer->Programmer",
                    "direction": "receive",
                    "occurrence": 0,
                },
                "truncate": {"mode": "max_chars", "max_chars": 10},
            }
        )
        result = injector.inject(_msg())
        self.assertEqual(result["body"], _msg()["body"])

    def test_matching_by_segment_and_edge(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "selector": {
                    "segment_name": "Coding",
                    "edge_id": "Chief Technology Officer->Programmer",
                    "direction": "receive",
                    "occurrence": 0,
                },
                "truncate": {"mode": "max_chars", "max_chars": 20},
            }
        )
        result = injector.inject(_msg())
        self.assertEqual(len(result["body"]), 20)
        self.assertTrue(result.get("fault_injected"))

    def test_occurrence_counting(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "selector": {
                    "segment_name": "Coding",
                    "direction": "receive",
                    "occurrence": 1,
                },
                "truncate": {"mode": "max_chars", "max_chars": 5},
            }
        )
        first = injector.inject(_msg(message_id="m-1"))
        self.assertEqual(first["body"], _msg()["body"])

        second = injector.inject(_msg(message_id="m-2"))
        self.assertEqual(second["body"], _msg()["body"][:5])

    def test_cut_after_text_truncation(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
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
        )
        original = _msg()
        result = injector.inject(original)
        self.assertTrue(result["body"].endswith("buying them, collecting rent,"))
        self.assertNotIn("handle chance", result["body"])
        self.assertLess(len(result["body"]), len(original["body"]))

    def test_max_chars_truncation(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "selector": {"direction": "receive", "occurrence": 0},
                "truncate": {"mode": "max_chars", "max_chars": 12},
            }
        )
        result = injector.inject(_msg())
        self.assertEqual(result["body"], _msg()["body"][:12])

    def test_cut_after_text_not_found_raises(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "selector": {"direction": "receive", "occurrence": 0},
                "truncate": {
                    "mode": "cut_after_text",
                    "cut_after_text": "this phrase is not in the body",
                },
            }
        )
        with self.assertRaises(ValueError):
            injector.inject(_msg())

    def test_cut_after_text_not_found_warns(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "on_missing_cut_text": "warn",
                "selector": {"direction": "receive", "occurrence": 0},
                "truncate": {
                    "mode": "cut_after_text",
                    "cut_after_text": "missing phrase",
                },
            }
        )
        original = _msg()
        result = injector.inject(original)
        self.assertEqual(result["body"], original["body"])
        self.assertFalse(result.get("fault_injected"))

    def test_does_not_mutate_input(self) -> None:
        injector = A2AFaultInjector.from_dict(
            {
                "enabled": True,
                "selector": {"direction": "receive", "occurrence": 0},
                "truncate": {"mode": "max_chars", "max_chars": 3},
            }
        )
        original = _msg()
        snapshot = copy.deepcopy(original)
        injector.inject(original)
        self.assertEqual(original, snapshot)


if __name__ == "__main__":
    unittest.main()
