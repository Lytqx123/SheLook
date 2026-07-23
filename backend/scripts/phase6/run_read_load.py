"""无额外依赖的只读并发压测，用于本地/CI 冒烟门禁。"""

import argparse
import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean
from urllib.parse import urlsplit

DEFAULT_PATHS = (
    "/api/health/live",
    "/api/dashboard/summary",
    "/api/products?page=1&page_size=20",
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def run_load(
    *,
    base_url: str,
    paths: tuple[str, ...],
    concurrency: int,
    duration_seconds: int,
    timeout_seconds: float,
    tenant_id: str | None,
    token: str | None,
) -> dict[str, object]:
    stop_at = time.monotonic() + duration_seconds
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.hostname:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    lock = threading.Lock()
    durations: list[float] = []
    failures: list[str] = []
    requests = 0

    headers = {"Accept": "application/json"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def worker(worker_index: int) -> None:
        nonlocal requests
        index = worker_index
        connection: http.client.HTTPConnection | None = None
        connection_type = (
            http.client.HTTPSConnection if parsed_base_url.scheme == "https" else http.client.HTTPConnection
        )
        try:
            while time.monotonic() < stop_at:
                path = paths[index % len(paths)]
                index += 1
                request_path = f"{parsed_base_url.path.rstrip('/')}{path}"
                started = time.perf_counter()
                error: str | None = None
                try:
                    if connection is None:
                        connection = connection_type(
                            parsed_base_url.hostname,
                            parsed_base_url.port,
                            timeout=timeout_seconds,
                        )
                    connection.request("GET", request_path, headers=headers)
                    response = connection.getresponse()
                    response.read()
                    if response.status != 200:
                        error = f"{path}: HTTP {response.status}"
                except (OSError, TimeoutError, http.client.HTTPException) as exc:
                    error = f"{path}: {type(exc).__name__}"
                    if connection is not None:
                        connection.close()
                        connection = None
                elapsed_ms = (time.perf_counter() - started) * 1000
                with lock:
                    requests += 1
                    durations.append(elapsed_ms)
                    if error:
                        failures.append(error)
        finally:
            if connection is not None:
                connection.close()

    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(executor.map(worker, range(concurrency)))
    elapsed_seconds = max(time.monotonic() - started_at, 0.001)
    return {
        "requests": requests,
        "failures": len(failures),
        "error_rate": len(failures) / requests if requests else 1.0,
        "average_ms": round(mean(durations), 2) if durations else 0.0,
        "p95_ms": round(_percentile(durations, 0.95), 2),
        "p99_ms": round(_percentile(durations, 0.99), 2),
        "requests_per_second": round(requests / elapsed_seconds, 2),
        "concurrency": concurrency,
        "duration_seconds": duration_seconds,
        "paths": list(paths),
        "failure_examples": failures[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--duration-seconds", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--tenant-id")
    parser.add_argument("--token")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.concurrency < 1 or args.duration_seconds < 1 or args.timeout_seconds <= 0:
        raise SystemExit("并发、持续时间和超时必须为正数")
    report = run_load(
        base_url=args.base_url,
        paths=tuple(args.paths or DEFAULT_PATHS),
        concurrency=args.concurrency,
        duration_seconds=args.duration_seconds,
        timeout_seconds=args.timeout_seconds,
        tenant_id=args.tenant_id,
        token=args.token,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
