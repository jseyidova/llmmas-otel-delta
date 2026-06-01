from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("llmmas.jaeger")

DEFAULT_JAEGER_QUERY_URL = "http://localhost:16686"


def _trace_start_micros(trace: dict[str, Any]) -> int:
    spans = trace.get("spans") or []
    if not spans:
        return 0
    return max(int(s.get("startTime") or 0) for s in spans)


def fetch_traces(
    *,
    service: str,
    base_url: str = DEFAULT_JAEGER_QUERY_URL,
    limit: int = 20,
    lookback: str = "2h",
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {"service": service, "limit": str(limit), "lookback": lookback}
    )
    url = f"{base_url.rstrip('/')}/api/traces?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict)]


def pick_latest_trace(
    traces: list[dict[str, Any]],
    *,
    min_start_micros: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    candidates = traces
    if min_start_micros is not None:
        candidates = [t for t in traces if _trace_start_micros(t) >= min_start_micros]
    if not candidates:
        return None
    return max(candidates, key=_trace_start_micros)


def fetch_latest_trace(
    *,
    service: str,
    base_url: str = DEFAULT_JAEGER_QUERY_URL,
    min_start_micros: Optional[int] = None,
    limit: int = 20,
    lookback: str = "2h",
) -> Optional[dict[str, Any]]:
    traces = fetch_traces(
        service=service,
        base_url=base_url,
        limit=limit,
        lookback=lookback,
    )
    return pick_latest_trace(traces, min_start_micros=min_start_micros)


def save_jaeger_trace(trace: dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return out


def fetch_and_save_latest_trace(
    *,
    service: str,
    output_path: str | Path,
    base_url: str = DEFAULT_JAEGER_QUERY_URL,
    min_start_micros: Optional[int] = None,
    retries: int = 8,
    retry_delay_seconds: float = 2.0,
) -> Path:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            trace = fetch_latest_trace(
                service=service,
                base_url=base_url,
                min_start_micros=min_start_micros,
            )
            if trace is not None:
                saved = save_jaeger_trace(trace, output_path)
                trace_id = trace.get("traceID", "?")
                logger.info(
                    "Saved Jaeger trace %s (%d spans) -> %s",
                    trace_id,
                    len(trace.get("spans") or []),
                    saved,
                )
                return saved
            last_error = RuntimeError(
                f"No Jaeger trace found for service={service!r} "
                f"(attempt {attempt}/{retries})"
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "Jaeger fetch attempt %d/%d failed: %s",
                attempt,
                retries,
                exc,
            )
        if attempt < retries:
            time.sleep(retry_delay_seconds)
    raise RuntimeError(
        f"Failed to fetch Jaeger trace for service={service!r} after {retries} attempts"
    ) from last_error


def default_trace_output_path(project_name: str) -> Path:
    slug = project_name.lower()
    if slug.endswith("ui") and len(slug) > 2:
        slug = slug[:-2]
    slug = slug.strip("_-") or "run"
    return Path("out") / slug / "latest-jaeger-trace.json"
