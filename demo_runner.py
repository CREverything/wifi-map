#!/usr/bin/env python3
"""Demo orchestrator: continuous Wi-Fi extraction plus periodic model updates.

Run from anywhere; stop with Ctrl+C:
    python3 demo_runner.py --browser-location
    python3 demo_runner.py --lat 32.88 --lon -117.23

Both tasks call the existing extractor and model functions in-process, each on
its own thread, so location and Firebase are set up once. A failure in one
task is logged and retried on its next run; it never stops the other task.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import platform
import sys
import threading
import time
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extractor import collect  # noqa: E402
from model import Predictor  # noqa: E402
from model.firestore_io import create_client, predict_to_firestore, train_from_firestore  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
MODEL_ARTIFACT = REPO_ROOT / "model" / "firestore.joblib"
SHUTDOWN_TIMEOUT_S = 15

_print_lock = threading.Lock()


def log(message: str, error: bool = False) -> None:
    with _print_lock:
        print(f"[{datetime.now():%H:%M:%S}] {message}",
              file=sys.stderr if error else sys.stdout, flush=True)


def run_periodic(name: str, interval: float, task: Callable[[], Any], stop: Any,
                 clock: Callable[[], float] = time.monotonic, announce: bool = False) -> None:
    """Run `task` every `interval` seconds, measured start to start, until `stop` is set.

    Runs are sequential, so they never overlap. A run that overruns its slot is
    followed immediately by the next one (no back-to-back catch-up runs).
    Exceptions are logged and the schedule continues.
    """
    next_run = clock()
    while not stop.is_set():
        try:
            task()
        except Exception as exc:
            log(f"{name} failed: {exc}", error=True)
        now = clock()
        next_run = max(next_run + interval, now)
        if announce and not stop.is_set():
            log(f"Next {name} in approximately {round((next_run - now) / 60, 1):g} min")
        stop.wait(next_run - now)


class Extraction:
    """One collection per call: ping/RSSI every time, a full speed test when due."""

    def __init__(self, base_args: argparse.Namespace, coords: tuple[float, float, float | None],
                 speedtest_interval: float, clock: Callable[[], float] = time.monotonic):
        self.base_args = base_args
        self.coords = coords
        self.speedtest_interval = speedtest_interval
        self.clock = clock
        self.last_speedtest: float | None = None

    def speedtest_due(self) -> bool:
        if self.speedtest_interval <= 0:
            return False
        return self.last_speedtest is None or self.clock() - self.last_speedtest >= self.speedtest_interval

    def __call__(self) -> None:
        full = self.speedtest_due()
        if full:
            self.last_speedtest = self.clock()
            log("Running full speed test (can take up to a minute)")
        args = argparse.Namespace(**{**vars(self.base_args), "skip_speedtest": not full})
        record = collect.collect_once(args, self.coords)
        for warning in record["errors"]:
            log(f"Extraction warning: {warning}", error=True)
        try:
            doc_id = collect.write_firestore(record)
        except Exception as exc:
            # Same backup policy as collect.py --firestore: keep the measurement locally.
            collect.write_local(record, args.output)
            raise RuntimeError(f"upload failed ({exc}); saved locally to {args.output}") from exc
        details = ", ".join(f"{key}={record[key]}" for key in (
            "rssi_dbm", "latency_ms", "download_mbps", "upload_mbps") if record.get(key) is not None)
        log(f"Measurement uploaded: {doc_id}" + (f" ({details})" if details else ""))


class ModelUpdate:
    """Retrain from Firestore measurements, then write a prediction for the demo location."""

    def __init__(self, coords: tuple[float, float, float | None], method: str,
                 artifact: Path = MODEL_ARTIFACT):
        self.coords = coords
        self.method = method
        self.artifact = artifact
        self.client: Any = None

    def __call__(self) -> None:
        log("ML update started")
        if self.client is None:
            self.client = create_client()
        report = train_from_firestore(self.client, self.artifact)
        log(f"Model trained on {report['accepted_count']} measurement(s), "
            f"{len(report['skipped'])} skipped")
        latitude, longitude, _ = self.coords
        request = {"latitude": latitude, "longitude": longitude,
                   "measured_at": datetime.now(timezone.utc)}
        result = predict_to_firestore(self.client, Predictor.load(self.artifact), request,
                                      self.method, model_id=self.artifact.name)
        estimates = ", ".join(f"{key}={result[key]:.1f}" for key in (
            "download_mbps", "upload_mbps", "rssi_dbm") if result.get(key) is not None)
        log(f"ML update completed: prediction {result['prediction_id']} "
            f"status={result['status']}" + (f" ({estimates})" if estimates else ""))


def supervise(workers: list[threading.Thread], stop: threading.Event,
              wait: Callable[[float], None] = time.sleep) -> None:
    """Block until Ctrl+C, then stop workers and wait briefly for them to finish."""
    try:
        while any(worker.is_alive() for worker in workers):
            wait(0.5)  # short sleeps keep Ctrl+C responsive on Windows
    except KeyboardInterrupt:
        log("Ctrl+C received; stopping after current operations finish...")
    finally:
        stop.set()
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT_S
        try:
            for worker in workers:
                worker.join(max(0, deadline - time.monotonic()))
        except KeyboardInterrupt:
            pass
        busy = [worker.name for worker in workers if worker.is_alive()]
        if busy:
            log(f"Still busy ({', '.join(busy)}); exiting without waiting", error=True)
        log("Demo pipeline stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continuous Wi-Fi extraction plus periodic model updates")
    parser.add_argument("--lat", type=float, help="Latitude of the demo location")
    parser.add_argument("--lon", type=float, help="Longitude of the demo location")
    parser.add_argument("--browser-location", action="store_true",
                        help="Ask the browser for location once at startup")
    parser.add_argument("--location-label", help="e.g. Geisel Library")
    parser.add_argument("--extract-interval", type=float, default=10, help="Seconds between measurements (default: 10)")
    parser.add_argument("--speedtest-interval", type=float, default=300,
                        help="Seconds between full speed tests; 0 disables (default: 300)")
    parser.add_argument("--ml-interval", type=float, default=300, help="Seconds between model updates (default: 300)")
    parser.add_argument("--method", choices=["baseline", "random_forest"], default="baseline",
                        help="Prediction method (default: baseline)")
    return parser


def resolve_location(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[float, float, float | None]:
    if args.browser_location:
        if args.lat is not None or args.lon is not None:
            parser.error("Use either --browser-location or --lat/--lon, not both")
        try:
            return collect.get_browser_location()
        except TimeoutError as exc:
            parser.error(str(exc))
    if args.lat is None or args.lon is None:
        parser.error("Provide BOTH --lat and --lon, or use --browser-location")
    if not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        parser.error("Latitude must be -90..90 and longitude -180..180")
    return args.lat, args.lon, None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if min(args.extract_interval, args.ml_interval) <= 0 or args.speedtest_interval < 0:
        parser.error("Intervals must be positive (--speedtest-interval may be 0 to disable)")
    if platform.system() not in ("Darwin", "Windows"):
        parser.error("The Wi-Fi collector supports macOS and Windows")

    log("Demo pipeline started")
    collect.load_environment()
    try:
        collect.get_firestore_client()
        log("Firebase configured")
    except Exception as exc:
        log(f"Firebase unavailable ({exc}); measurements will be saved locally", error=True)

    coords = resolve_location(args, parser)
    accuracy = f" (±{coords[2]:.0f} m)" if coords[2] is not None else ""
    log(f"Location acquired: {coords[0]:.5f}, {coords[1]:.5f}{accuracy}")

    # Reuse the collector's own defaults (ping host, packet count, output path).
    base_args = collect.build_parser().parse_args([])
    base_args.lat, base_args.lon = coords[0], coords[1]
    base_args.browser_location = args.browser_location
    base_args.location_label = args.location_label

    stop = threading.Event()
    workers = [
        threading.Thread(target=run_periodic, name="extraction", daemon=True, args=(
            "Extraction", args.extract_interval,
            Extraction(base_args, coords, args.speedtest_interval), stop)),
        threading.Thread(target=run_periodic, name="ML update", daemon=True, args=(
            "ML update", args.ml_interval, ModelUpdate(coords, args.method), stop),
            kwargs={"announce": True}),
    ]
    for worker in workers:
        worker.start()
    log(f"Extractor started: every {args.extract_interval:g} s, full speed test every "
        f"{args.speedtest_interval:g} s" if args.speedtest_interval else
        f"Extractor started: every {args.extract_interval:g} s, speed tests disabled")
    log(f"ML updates every {args.ml_interval:g} s. Press Ctrl+C to stop.")
    supervise(workers, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
