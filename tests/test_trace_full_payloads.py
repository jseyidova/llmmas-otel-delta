from __future__ import annotations

import os
import unittest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from llmmas_otel import semconv
from llmmas_otel.span_factory import SpanFactory, trace_full_payloads_enabled


class TraceFullPayloadsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(cls.exporter))
        trace.set_tracer_provider(provider)
        cls.factory = SpanFactory(tracer_name="test-full-payloads")

    def setUp(self) -> None:
        self._old = os.environ.get("LLMMAS_TRACE_FULL_PAYLOADS")
        self.exporter.clear()

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("LLMMAS_TRACE_FULL_PAYLOADS", None)
        else:
            os.environ["LLMMAS_TRACE_FULL_PAYLOADS"] = self._old

    def test_disabled_by_default(self) -> None:
        os.environ.pop("LLMMAS_TRACE_FULL_PAYLOADS", None)
        self.assertFalse(trace_full_payloads_enabled())
        with self.factory.a2a_send(
            source_agent_id="A",
            target_agent_id="B",
            edge_id="A->B",
            message_id="m1",
            message_body="x" * 300,
        ):
            pass
        attrs = dict(self.exporter.get_finished_spans()[0].attributes)
        self.assertIn(semconv.ATTR_MESSAGE_PREVIEW, attrs)
        self.assertNotIn(semconv.ATTR_MESSAGE_BODY, attrs)
        self.assertEqual(len(attrs[semconv.ATTR_MESSAGE_PREVIEW]), 200)

    def test_full_body_when_enabled(self) -> None:
        os.environ["LLMMAS_TRACE_FULL_PAYLOADS"] = "1"
        body = "full message " * 40
        with self.factory.a2a_send(
            source_agent_id="A",
            target_agent_id="B",
            edge_id="A->B",
            message_id="m2",
            message_body=body,
        ):
            pass
        attrs = dict(self.exporter.get_finished_spans()[0].attributes)
        self.assertEqual(attrs[semconv.ATTR_MESSAGE_BODY], body)


if __name__ == "__main__":
    unittest.main()
