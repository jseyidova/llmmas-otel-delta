from llmmas_otel.jaeger_client import default_trace_output_path, pick_latest_trace


def test_pick_latest_trace_by_start_time():
    traces = [
        {"traceID": "a", "spans": [{"startTime": 100}]},
        {"traceID": "b", "spans": [{"startTime": 500}]},
        {"traceID": "c", "spans": [{"startTime": 300}]},
    ]
    latest = pick_latest_trace(traces)
    assert latest is not None
    assert latest["traceID"] == "b"


def test_pick_latest_trace_respects_min_start():
    traces = [
        {"traceID": "old", "spans": [{"startTime": 100}]},
        {"traceID": "new", "spans": [{"startTime": 5000}]},
    ]
    latest = pick_latest_trace(traces, min_start_micros=1000)
    assert latest is not None
    assert latest["traceID"] == "new"


def test_default_trace_output_path_calculator_ui():
    assert default_trace_output_path("CalculatorUI") == __import__("pathlib").Path(
        "out/calculator/latest-jaeger-trace.json"
    )
