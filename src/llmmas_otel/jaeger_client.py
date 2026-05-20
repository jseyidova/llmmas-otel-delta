from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


def fetch_traces(
    *,
    base_url: str = "http://localhost:16686",
    service: str,
    limit: int = 20,
    lookback: str = "2h",
) -> dict[str, Any]:
    """Call Jaeger ``GET /api/traces`` and return the raw JSON response."""
    params = urllib.parse.urlencode(
        {"service": service, "limit": str(limit), "lookback": lookback}
    )
    url = f"{base_url.rstrip('/')}/api/traces?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Failed to fetch traces from Jaeger at {url}. "
            "Is Jaeger running (docker compose up)?"
        ) from exc


def pick_trace(
    payload: dict[str, Any],
    *,
    session_contains: Optional[str] = None,
) -> dict[str, Any]:
    """
    Choose one trace from a Jaeger API response (latest by max span startTime).
    """
    traces = payload.get("data")
    if not isinstance(traces, list) or not traces:
        raise ValueError("Jaeger returned no traces for the query")

    candidates = traces
    if session_contains:
        filtered: list[dict[str, Any]] = []
        for trace in traces:
            for span in trace.get("spans") or []:
                tags = {t.get("key"): t.get("value") for t in (span.get("tags") or [])}
                sid = str(tags.get("llmmas.session.id") or "")
                if session_contains in sid:
                    filtered.append(trace)
                    break
        if filtered:
            candidates = filtered

    def trace_start(trace: dict[str, Any]) -> int:
        return max((int(s.get("startTime") or 0) for s in trace.get("spans") or []), default=0)

    return max(candidates, key=trace_start)


def fetch_and_save_trace(
    out_path: str,
    *,
    base_url: str = "http://localhost:16686",
    service: str = "chatdev-programdev",
    limit: int = 20,
    lookback: str = "2h",
    session_contains: Optional[str] = None,
    save_all_candidates: bool = False,
) -> dict[str, Any]:
    """
    Fetch traces from Jaeger and write JSON to ``out_path``.

    By default saves ``{"data": [<single chosen trace>]}`` (same shape as the API).
    Set ``save_all_candidates=True`` to persist the full API response.
    """
    from pathlib import Path

    payload = fetch_traces(
        base_url=base_url,
        service=service,
        limit=limit,
        lookback=lookback,
    )
    if save_all_candidates:
        out = payload
        chosen = None
    else:
        chosen = pick_trace(payload, session_contains=session_contains)
        out = {"data": [chosen]}

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    span_count = len((chosen or {}).get("spans") or []) if chosen else sum(
        len(t.get("spans") or []) for t in (payload.get("data") or [])
    )
    return {
        "path": str(path.resolve()),
        "trace_id": (chosen or {}).get("traceID"),
        "span_count": span_count,
        "trace_count": len(payload.get("data") or []),
    }
