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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import platform
import sys
import threading
import time
from typing import Any, Callable
import webbrowser

# The collector starts ping/networksetup subprocesses while Firestore's gRPC threads
# are active; gRPC's fork handlers aren't needed for fork+exec and only log noise.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extractor import collect  # noqa: E402
from model import Predictor  # noqa: E402
from model.firestore_io import create_client, predict_to_firestore, train_from_firestore  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
MODEL_ARTIFACT = REPO_ROOT / "model" / "firestore.joblib"
SHUTDOWN_TIMEOUT_S = 15
LOCATION_DECIMALS = 4  # ~11 m: measurements closer than this share one prediction
MAX_PREDICTION_LOCATIONS = 200  # Firestore writes per model update
FIRST_FIX_TIMEOUT_S = 90
LOCATION_STALE_S = 120  # warn when the browser hasn't sent a position for this long
LOG_MOVE_M = 15  # log a location update once you've moved at least this far

Coords = tuple[float, float, "float | None"]

_print_lock = threading.Lock()


def log(message: str, error: bool = False) -> None:
    with _print_lock:
        print(f"[{datetime.now():%H:%M:%S}] {message}",
              file=sys.stderr if error else sys.stdout, flush=True)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Approximate ground distance; accurate to well under 1% at campus scale."""
    mean_latitude = math.radians((a[0] + b[0]) / 2)
    dx = math.radians(b[1] - a[1]) * math.cos(mean_latitude)
    dy = math.radians(b[0] - a[0])
    return 6371000 * math.hypot(dx, dy)


TRACKER_PAGE = """<!doctype html><html lang='en'><meta charset='utf-8'>
<title>Wi-Fi survey location</title>
<body style='font:16px system-ui;max-width:560px;margin:70px auto;padding:20px'>
<h2>Share this laptop's location while you collect</h2>
<p>The browser asks permission once, then keeps sending your position to the collector on
this laptop as you move. <strong>Keep this tab open</strong> until you stop the collector.
Indoor accuracy can be poor.</p>
<button id='go'>Start sharing location</button><p id='message'></p>
<script>
const output = document.getElementById('message');
document.getElementById('go').onclick = () => {
  if (!navigator.geolocation) { output.textContent = 'Browser geolocation unavailable'; return; }
  output.textContent = 'Requesting browser permission...';
  navigator.geolocation.watchPosition(async (p) => {
    try {
      const r = await fetch('/location', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy_m: p.coords.accuracy})});
      output.textContent = r.ok
        ? `Sharing. Last update ${new Date().toLocaleTimeString()}: ${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)} (±${Math.round(p.coords.accuracy)} m)`
        : 'Location was not accepted.';
    } catch (e) { output.textContent = 'Collector stopped; you can close this tab.'; }
  }, (e) => { output.textContent = 'Location error: ' + e.message; },
  {enableHighAccuracy: true, maximumAge: 0, timeout: 30000});
};
</script></body></html>"""


class LocationTracker:
    """Follows the laptop's position from one browser tab (one permission prompt).

    The tab uses navigator.geolocation.watchPosition and posts every update to a
    small server on 127.0.0.1; current() returns the latest position.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._latest: Coords | None = None
        self._updated_at = 0.0
        self._last_logged: tuple[float, float] | None = None
        self._first_fix = threading.Event()
        self._server: ThreadingHTTPServer | None = None

    def update(self, latitude: float, longitude: float, accuracy_m: float | None) -> None:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Out-of-range coordinates")
        with self._lock:
            self._latest = (latitude, longitude, accuracy_m)
            self._updated_at = self.clock()
            moved = self._last_logged is None or distance_m(self._last_logged, (latitude, longitude)) >= LOG_MOVE_M
            if moved:
                self._last_logged = (latitude, longitude)
        self._first_fix.set()
        if moved:
            accuracy = f" (±{accuracy_m:.0f} m)" if accuracy_m is not None else ""
            log(f"Location updated: {latitude:.5f}, {longitude:.5f}{accuracy}")

    def current(self) -> tuple[Coords, float]:
        """Latest position and its age in seconds."""
        with self._lock:
            if self._latest is None:
                raise RuntimeError("No location received yet")
            return self._latest, self.clock() - self._updated_at

    def wait_for_first_fix(self, timeout: float = FIRST_FIX_TIMEOUT_S) -> Coords:
        if not self._first_fix.wait(timeout):
            raise TimeoutError("No browser location received. Use --lat and --lon instead.")
        return self.current()[0]

    def start(self) -> str:
        tracker = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/":
                    self.send_error(404)
                    return
                payload = TRACKER_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                if self.path != "/location":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length < 1024:
                        raise ValueError("Invalid request size")
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    accuracy = body.get("accuracy_m")
                    tracker.update(float(body["latitude"]), float(body["longitude"]),
                                   float(accuracy) if accuracy is not None else None)
                    self.send_response(204)
                    self.end_headers()
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    self.send_error(400)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self._server.server_address[1]}/"
        log(f"Open {url} and click 'Start sharing location'. Keep that tab open.")
        webbrowser.open(url)
        return url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class FixedLocation:
    """Manual --lat/--lon: the same position for every measurement."""

    def __init__(self, coords: Coords):
        self.coords = coords

    def current(self) -> tuple[Coords, float]:
        return self.coords, 0.0

    def stop(self) -> None:
        pass


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
    """One collection per call at the current position: ping/RSSI every time, a speed test when due."""

    def __init__(self, base_args: argparse.Namespace, location: Any,
                 speedtest_interval: float, clock: Callable[[], float] = time.monotonic):
        self.base_args = base_args
        self.location = location
        self.speedtest_interval = speedtest_interval
        self.clock = clock
        self.last_speedtest: float | None = None
        self.warned_stale = False

    def current_coords(self) -> Coords:
        coords, age = self.location.current()
        if age > LOCATION_STALE_S and not self.warned_stale:
            log(f"Location hasn't updated for {age:.0f} s; measurements use the last known position. "
                "Is the location tab still open?", error=True)
        self.warned_stale = age > LOCATION_STALE_S
        return coords

    def speedtest_due(self) -> bool:
        if self.speedtest_interval <= 0:
            return False
        return self.last_speedtest is None or self.clock() - self.last_speedtest >= self.speedtest_interval

    def __call__(self) -> None:
        full = self.speedtest_due()
        if full:
            self.last_speedtest = self.clock()
            log("Running full speed test (can take up to a minute)")
        coords = self.current_coords()
        args = argparse.Namespace(**{**vars(self.base_args), "skip_speedtest": not full,
                                     "lat": coords[0], "lon": coords[1]})
        record = collect.collect_once(args, coords)
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


def prediction_locations(predictor: Any, coords: Coords) -> list[tuple[float, float]]:
    """The current location plus every distinct measured location (to ~11 m), capped.

    Predicting where measurements exist covers everywhere data was collected
    without extrapolating to places nobody measured.
    """
    measurements = predictor.artifact["measurements"]
    candidates = [(coords[0], coords[1]), *zip(measurements["latitude"], measurements["longitude"])]
    locations: dict[tuple[float, float], tuple[float, float]] = {}
    for latitude, longitude in candidates:
        locations.setdefault((round(latitude, LOCATION_DECIMALS), round(longitude, LOCATION_DECIMALS)),
                             (float(latitude), float(longitude)))
    return list(locations.values())[:MAX_PREDICTION_LOCATIONS]


class ModelUpdate:
    """Retrain from Firestore measurements, then write predictions for every measured place."""

    def __init__(self, location: Any, method: str, artifact: Path = MODEL_ARTIFACT):
        self.location = location
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
        predictor = Predictor.load(self.artifact)
        predicted_at = datetime.now(timezone.utc)
        statuses: dict[str, int] = {}
        for latitude, longitude in prediction_locations(predictor, self.location.current()[0]):
            request = {"latitude": latitude, "longitude": longitude, "measured_at": predicted_at}
            result = predict_to_firestore(self.client, predictor, request, self.method,
                                          model_id=self.artifact.name)
            statuses[result["status"]] = statuses.get(result["status"], 0) + 1
        breakdown = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items()))
        log(f"ML update completed: {sum(statuses.values())} prediction(s) written ({breakdown})")


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
                        help="Track location from a browser tab (one permission prompt; follows you as you move)")
    parser.add_argument("--location-label", help="e.g. Geisel Library")
    parser.add_argument("--extract-interval", type=float, default=10, help="Seconds between measurements (default: 10)")
    parser.add_argument("--speedtest-interval", type=float, default=300,
                        help="Seconds between full speed tests; 0 disables (default: 300)")
    parser.add_argument("--ml-interval", type=float, default=300, help="Seconds between model updates (default: 300)")
    parser.add_argument("--method", choices=["baseline", "random_forest"], default="baseline",
                        help="Prediction method (default: baseline)")
    return parser


def resolve_location(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Any:
    """A LocationTracker (browser) or FixedLocation (manual) with a first position."""
    if args.browser_location:
        if args.lat is not None or args.lon is not None:
            parser.error("Use either --browser-location or --lat/--lon, not both")
        tracker = LocationTracker()
        tracker.start()
        try:
            tracker.wait_for_first_fix()
        except TimeoutError as exc:
            tracker.stop()
            parser.error(str(exc))
        return tracker
    if args.lat is None or args.lon is None:
        parser.error("Provide BOTH --lat and --lon, or use --browser-location")
    if not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        parser.error("Latitude must be -90..90 and longitude -180..180")
    return FixedLocation((args.lat, args.lon, None))


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

    location = resolve_location(args, parser)
    if isinstance(location, FixedLocation):
        log(f"Using fixed location: {location.coords[0]:.5f}, {location.coords[1]:.5f}")

    # Reuse the collector's own defaults (ping host, packet count, output path).
    base_args = collect.build_parser().parse_args([])
    base_args.browser_location = args.browser_location
    base_args.location_label = args.location_label

    stop = threading.Event()
    workers = [
        threading.Thread(target=run_periodic, name="extraction", daemon=True, args=(
            "Extraction", args.extract_interval,
            Extraction(base_args, location, args.speedtest_interval), stop)),
        threading.Thread(target=run_periodic, name="ML update", daemon=True, args=(
            "ML update", args.ml_interval, ModelUpdate(location, args.method), stop),
            kwargs={"announce": True}),
    ]
    for worker in workers:
        worker.start()
    log(f"Extractor started: every {args.extract_interval:g} s, full speed test every "
        f"{args.speedtest_interval:g} s" if args.speedtest_interval else
        f"Extractor started: every {args.extract_interval:g} s, speed tests disabled")
    log(f"ML updates every {args.ml_interval:g} s. Press Ctrl+C to stop.")
    try:
        supervise(workers, stop)
    finally:
        location.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
