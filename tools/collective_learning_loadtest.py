#!/usr/bin/env python3
"""Acceptance load for the collective learning service (requirement T03/T04).

Starts the HTTP service in a separate OS process on 127.0.0.1 with a fresh
database, registers N device credentials, and has N client threads each deliver M
synthetic events in batches, with a share of redeliveries of already-sent events
mixed in.  Then it checks the database holds exactly N*M unique events and that
every redelivery was acknowledged as DUPLICATE.

This is a measurement, not a performance promise: the report records the hardware,
data size, concurrency, throughput, batch latency percentiles, error rate and peak
memory of both processes so a target can be set from a baseline.

    python tools/collective_learning_loadtest.py --clients 100 --events 1000 \
        --duplicate-ratio 0.2 --batch-size 100 --out report.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import resource
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.collective_learning import contracts as c  # noqa: E402
from tools.collective_learning import service as svc_mod  # noqa: E402
from tools.collective_learning import sync_client as sc  # noqa: E402


def _memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def _maxrss_bytes(usage: resource.struct_rusage) -> int:
    # macOS reports bytes, Linux reports kilobytes
    return int(usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[index]


def plan_deliveries(events: list[dict], ratio: float, batch_size: int, rng: random.Random) -> list[list[dict]]:
    """Batches of originals with exactly int(len*ratio) redeliveries of EARLIER batches mixed in."""
    dup_total = int(len(events) * ratio)
    originals_per_batch = max(1, batch_size - int(round(batch_size * ratio / (1 + ratio))))
    batches: list[list[dict]] = []
    sent: list[dict] = []
    dups_left = dup_total
    for start in range(0, len(events), originals_per_batch):
        chunk = list(events[start:start + originals_per_batch])
        room = batch_size - len(chunk)
        if sent and dups_left and room > 0:
            take = min(room, dups_left)
            chunk += rng.sample(sent, min(take, len(sent)))
            dups_left -= min(take, len(sent))
        rng.shuffle(chunk)
        batches.append(chunk)
        sent.extend(events[start:start + originals_per_batch])
    while dups_left > 0:  # tail: any redeliveries that did not fit
        take = min(batch_size, dups_left)
        batches.append(rng.sample(sent, take))
        dups_left -= take
    return batches


def run(clients: int, per_client: int, ratio: float, batch_size: int, max_batch: int, seed: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="collective-load-"))
    db = tmp / "svc.sqlite"
    svc = svc_mod.Service(db, max_batch=max_batch)
    admin = svc.authenticate(svc.bootstrap_tenant("load")["token"])
    tokens = {f"dev-{i:03d}": svc.register_principal(admin, principal_id=f"dev-{i:03d}", role="device_writer",
                                                     line_ids=[f"line-{i % 10:02d}"])["token"]
              for i in range(clients)}
    svc.close()

    ready = tmp / "port"
    server = subprocess.Popen([sys.executable, "-m", "tools.collective_learning.http_api", "serve", "--db", str(db),
                               "--port", "0", "--max-batch", str(max_batch), "--ready-file", str(ready)],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while not ready.is_file() and time.time() < deadline:
        time.sleep(0.05)
    if not ready.is_file():
        server.kill()
        raise SystemExit(f"server did not start: {server.stderr.read().decode()[-2000:]}")
    base = f"http://127.0.0.1:{ready.read_text().strip()}"

    build_started = time.monotonic()
    plans: dict[str, list[list[dict]]] = {}
    payload_bytes = 0
    for index, device in enumerate(sorted(tokens)):
        rng = random.Random(seed + index)
        line = f"line-{index % 10:02d}"
        events = [c.make_observation(tenant_id="load", line_id=line, device_id=device, run_id=f"run-{index}",
                                     episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY",
                                     symptom=f"synthetic load event {n}", evidence={"n": n, "detector": "load"},
                                     detected_by="loadtest", producer_sequence=n + 1, visibility="LINE")
                  for n in range(per_client)]
        plans[device] = plan_deliveries(events, ratio, batch_size, rng)
        payload_bytes += sum(len(json.dumps({"events": b})) for b in plans[device])
    build_seconds = time.monotonic() - build_started

    latencies: list[float] = []
    statuses = {"CREATED": 0, "DUPLICATE": 0, "CONFLICT": 0, "REJECTED": 0}
    errors: list[str] = []
    retries = 0
    lock = threading.Lock()

    def client(device: str) -> None:
        nonlocal retries
        transport = sc.HttpTransport(base, tokens[device], timeout=120)
        local_lat, local_status, local_err, local_retry = [], dict.fromkeys(statuses, 0), [], 0
        for batch in plans[device]:
            for attempt in range(6):
                started = time.perf_counter()
                try:
                    code, body, _ = transport.request("POST", "/v1/events:batch", {"events": batch})
                except sc.TransportError as exc:
                    local_err.append(f"TRANSPORT:{exc}")
                    local_retry += 1
                    time.sleep(random.uniform(0, min(5.0, 0.1 * 2 ** attempt)))
                    continue
                local_lat.append(time.perf_counter() - started)
                if code != 200:
                    local_err.append(f"HTTP_{code}")
                    local_retry += 1
                    time.sleep(random.uniform(0, min(5.0, 0.1 * 2 ** attempt)))
                    continue
                for result in body["results"]:
                    local_status[result["status"]] = local_status.get(result["status"], 0) + 1
                break
            else:
                local_err.append("BATCH_ABANDONED_AFTER_RETRIES")
        with lock:
            latencies.extend(local_lat)
            for key, value in local_status.items():
                statuses[key] = statuses.get(key, 0) + value
            errors.extend(local_err)
            retries += local_retry

    threads = [threading.Thread(target=client, args=(device,)) for device in sorted(tokens)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - started

    server.terminate()
    server.wait(timeout=30)
    server_rss = _maxrss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN))
    client_rss = _maxrss_bytes(resource.getrusage(resource.RUSAGE_SELF))

    con = sqlite3.connect(db)
    unique = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    deliveries = con.execute("SELECT COUNT(*) FROM delivery_log WHERE item_kind='EVENT'").fetchone()[0]
    dup_logged = con.execute("SELECT COUNT(*) FROM delivery_log WHERE status='DUPLICATE'").fetchone()[0]
    con.close()
    db_bytes = sum(p.stat().st_size for p in tmp.glob("svc.sqlite*"))
    expected_unique = clients * per_client
    expected_dups = clients * int(per_client * ratio)
    batches = sum(len(p) for p in plans.values())
    return {
        "schema": "qingshan.collective.loadtest_report.v1",
        "measured_at": c.now_iso(),
        "status": "PASS" if (unique == expected_unique and dup_logged == expected_dups
                             and statuses["CONFLICT"] == 0 and statuses["REJECTED"] == 0) else "FAIL",
        "note": "baseline measurement on one machine with server and clients on loopback; not a capacity promise",
        "hardware": {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
                     "cpu_count": os.cpu_count(), "memory_bytes": _memory_bytes(),
                     "python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
        "workload": {"clients": clients, "events_per_client": per_client, "duplicate_ratio": ratio,
                     "batch_size": batch_size, "server_max_batch": max_batch, "batches_sent": batches,
                     "deliveries_planned": expected_unique + expected_dups, "request_payload_bytes": payload_bytes,
                     "event_build_seconds_excluded": round(build_seconds, 2),
                     "server": "separate process, ThreadingHTTPServer + SQLite WAL synchronous=FULL",
                     "durability": "every batch is one committed transaction (fsync) before its ack"},
        "results": {"wall_seconds": round(wall, 2),
                    "unique_events_per_second": round(expected_unique / wall, 1),
                    "deliveries_per_second": round((expected_unique + expected_dups) / wall, 1),
                    "batch_latency_seconds": {"p50": round(_percentile(latencies, 50), 4),
                                              "p95": round(_percentile(latencies, 95), 4),
                                              "p99": round(_percentile(latencies, 99), 4),
                                              "max": round(max(latencies) if latencies else 0, 4),
                                              "mean": round(statistics.fmean(latencies), 4) if latencies else 0},
                    "acks": statuses, "errors": len(errors), "error_samples": errors[:5], "retries": retries,
                    "error_rate": round(len(errors) / max(1, batches), 6),
                    "server_peak_rss_bytes": server_rss, "client_process_peak_rss_bytes": client_rss,
                    "database_bytes": db_bytes},
        "verification": {"unique_events_in_db": unique, "expected_unique": expected_unique,
                         "duplicate_deliveries_logged": dup_logged, "expected_duplicates": expected_dups,
                         "deliveries_logged": deliveries},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--events", type=int, default=1000, help="events per client")
    parser.add_argument("--duplicate-ratio", type=float, default=0.2)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-batch", type=int, default=500)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = run(args.clients, args.events, args.duplicate_ratio, args.batch_size, args.max_batch, args.seed)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
