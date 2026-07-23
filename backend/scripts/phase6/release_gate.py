"""汇总 Locust 与数据一致性报告，生成可审计的发布门禁结论。"""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path


def _read_locust_aggregate(path: Path) -> dict[str, float]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    aggregate = next((row for row in rows if row.get("Name") == "Aggregated"), None)
    if aggregate is None:
        raise ValueError("Locust 统计文件缺少 Aggregated 行")
    requests = float(aggregate.get("Request Count") or 0)
    failures = float(aggregate.get("Failure Count") or 0)
    return {
        "requests": requests,
        "failures": failures,
        "error_rate": failures / requests if requests else 1.0,
        "p95_ms": float(aggregate.get("95%") or 0),
    }


def _read_integrity(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return bool(payload.get("passed"))


def _read_json_load(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "requests": float(payload.get("requests") or 0),
        "failures": float(payload.get("failures") or 0),
        "error_rate": float(payload.get("error_rate") or 0),
        "p95_ms": float(payload.get("p95_ms") or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--locust-stats", type=Path)
    source.add_argument("--load-report", type=Path)
    parser.add_argument("--integrity-report", type=Path, required=True)
    parser.add_argument("--minimum-requests", type=int, default=1_000)
    parser.add_argument("--max-error-rate", type=float, default=0.005)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    load = _read_locust_aggregate(args.locust_stats) if args.locust_stats else _read_json_load(args.load_report)
    gates = {
        "minimum_requests": load["requests"] >= args.minimum_requests,
        "error_rate": load["error_rate"] <= args.max_error_rate,
        "p95_latency": load["p95_ms"] <= args.max_p95_ms,
        "data_integrity": _read_integrity(args.integrity_report),
    }
    report = {
        "passed": all(gates.values()),
        "generated_at": datetime.now(UTC).isoformat(),
        "thresholds": {
            "minimum_requests": args.minimum_requests,
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
        },
        "load": load,
        "gates": gates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
