"""Orchestrator tests. Firestore, Wi-Fi tools, and speed tests are all mocked."""
import argparse
import json
import sys
import urllib.error
import urllib.request
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo_runner  # noqa: E402

COORDS = (32.88, -117.23, None)
FIXED = demo_runner.FixedLocation(COORDS)


class FakeClock:
    """Manual clock; FakeStop.wait advances it instead of sleeping."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeStop:
    def __init__(self, clock, max_waits):
        self.clock, self.max_waits, self.waits = clock, max_waits, []

    def is_set(self):
        return len(self.waits) >= self.max_waits

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.now += seconds


def record(errors=()):
    return {"measurement_id": "abc123", "rssi_dbm": -56, "latency_ms": 7.5,
            "download_mbps": None, "upload_mbps": None, "device": {"device_id": "test"},
            "errors": list(errors)}


@mock.patch.object(demo_runner, "log")
class SchedulingTests(TestCase):
    def test_waits_use_elapsed_time(self, _log):
        clock = FakeClock()
        stop = FakeStop(clock, max_waits=3)
        durations = iter([3, 12, 0])  # normal run, overrun, instant run

        def task():
            clock.now += next(durations)

        demo_runner.run_periodic("ML update", 10, task, stop, clock=clock)
        # 10 - 3 = 7; overrun starts the next run immediately; then a full slot.
        self.assertEqual(stop.waits, [7, 0, 10])

    def test_five_minute_schedule(self, _log):
        clock = FakeClock()
        stop = FakeStop(clock, max_waits=3)
        starts = []
        demo_runner.run_periodic("ML update", 300, lambda: starts.append(clock.now), stop, clock=clock)
        self.assertEqual(starts, [0, 300, 600])

    def test_failure_is_logged_and_schedule_continues(self, log):
        clock = FakeClock()
        stop = FakeStop(clock, max_waits=3)
        calls = []

        def task():
            calls.append(clock.now)
            if len(calls) == 1:
                raise RuntimeError("boom")

        demo_runner.run_periodic("ML update", 300, task, stop, clock=clock)
        self.assertEqual(len(calls), 3)
        log.assert_any_call("ML update failed: boom", error=True)

    def test_runs_never_overlap(self, _log):
        stop = threading.Event()
        active, peak = [0], [0]

        def slow_task():
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.03)  # longer than the interval
            active[0] -= 1

        worker = threading.Thread(target=demo_runner.run_periodic, args=("x", 0.01, slow_task, stop))
        worker.start()
        time.sleep(0.15)
        stop.set()
        worker.join(1)
        self.assertEqual(peak[0], 1)


@mock.patch.object(demo_runner, "log")
class ExtractionTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = argparse.Namespace(output=Path(self.tmp.name) / "m.jsonl", skip_speedtest=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_speedtest_every_five_minutes_only(self, _log):
        clock = FakeClock()
        extraction = demo_runner.Extraction(self.base, FIXED, speedtest_interval=300, clock=clock)
        skipped = []
        with mock.patch.object(demo_runner.collect, "collect_once",
                               side_effect=lambda args, coords: skipped.append(args.skip_speedtest) or record()), \
                mock.patch.object(demo_runner.collect, "write_firestore", return_value="abc123"):
            for t in range(0, 610, 10):
                clock.now = t
                extraction()
        full_runs = [t for t, skip in zip(range(0, 610, 10), skipped) if not skip]
        self.assertEqual(full_runs, [0, 300, 600])

    def test_fixed_location_used_every_time(self, _log):
        extraction = demo_runner.Extraction(self.base, FIXED, speedtest_interval=0)
        with mock.patch.object(demo_runner.collect, "collect_once", return_value=record()) as collect_once, \
                mock.patch.object(demo_runner.collect, "write_firestore", return_value="abc123"):
            extraction()
            extraction()
        self.assertEqual([c.args[1] for c in collect_once.call_args_list], [COORDS, COORDS])

    def test_each_measurement_uses_latest_tracked_position(self, _log):
        tracker = demo_runner.LocationTracker()
        tracker.update(32.8800, -117.2300, 35.0)
        extraction = demo_runner.Extraction(self.base, tracker, speedtest_interval=0)
        with mock.patch.object(demo_runner.collect, "collect_once", return_value=record()) as collect_once, \
                mock.patch.object(demo_runner.collect, "write_firestore", return_value="abc123"):
            extraction()
            tracker.update(32.8850, -117.2400, 20.0)  # walked ~1 km
            extraction()
        self.assertEqual([c.args[1] for c in collect_once.call_args_list],
                         [(32.8800, -117.2300, 35.0), (32.8850, -117.2400, 20.0)])
        self.assertEqual(collect_once.call_args.args[0].lat, 32.8850)

    def test_stale_location_warns_once(self, log):
        clock = FakeClock()
        tracker = demo_runner.LocationTracker(clock=clock)
        tracker.update(32.88, -117.23, 35.0)
        extraction = demo_runner.Extraction(self.base, tracker, speedtest_interval=0)
        clock.now = demo_runner.LOCATION_STALE_S + 1
        extraction.current_coords()
        extraction.current_coords()
        stale = [c for c in log.call_args_list if "hasn't updated" in c.args[0]]
        self.assertEqual(len(stale), 1)

    def test_upload_logged_with_document_id(self, log):
        extraction = demo_runner.Extraction(self.base, FIXED, speedtest_interval=0)
        with mock.patch.object(demo_runner.collect, "collect_once", return_value=record()), \
                mock.patch.object(demo_runner.collect, "write_firestore", return_value="abc123"):
            extraction()
        self.assertIn("Measurement uploaded: abc123", log.call_args.args[0])

    def test_upload_failure_saves_backup_and_raises(self, _log):
        extraction = demo_runner.Extraction(self.base, FIXED, speedtest_interval=0)
        with mock.patch.object(demo_runner.collect, "collect_once", return_value=record()), \
                mock.patch.object(demo_runner.collect, "write_firestore", side_effect=RuntimeError("denied")):
            with self.assertRaisesRegex(RuntimeError, "denied"):
                extraction()
        self.assertTrue(self.base.output.exists())


@mock.patch.object(demo_runner, "log")
class ModelUpdateTests(TestCase):
    def test_trains_then_predicts_at_every_measured_location(self, log):
        update = demo_runner.ModelUpdate(FIXED, "baseline", artifact=Path("unused.joblib"))
        result = {"prediction_id": "p1", "status": "available"}
        predictor = mock.Mock(artifact={"measurements": {
            # Second point is ~1 m from the first, so they share one prediction.
            "latitude": [32.8900, 32.89001, 32.8800],
            "longitude": [-117.2400, -117.24001, -117.2300],
        }})
        with mock.patch.object(demo_runner, "create_client") as create_client, \
                mock.patch.object(demo_runner, "train_from_firestore",
                                  return_value={"accepted_count": 3, "skipped": []}) as train, \
                mock.patch.object(demo_runner.Predictor, "load", return_value=predictor), \
                mock.patch.object(demo_runner, "predict_to_firestore", return_value=result) as predict:
            update()
            update()
        create_client.assert_called_once()  # client reused across updates
        self.assertEqual(train.call_count, 2)
        first_update = [(c.args[2]["latitude"], c.args[2]["longitude"]) for c in predict.call_args_list[:2]]
        # Demo location (32.88, -117.23) and the measured cluster; the duplicate point is dropped.
        self.assertEqual(first_update, [COORDS[:2], (32.89, -117.24)])
        self.assertEqual(predict.call_count, 4)
        log.assert_any_call("ML update completed: 2 prediction(s) written (2 available)")

    def test_training_failure_propagates_to_scheduler(self, _log):
        update = demo_runner.ModelUpdate(FIXED, "baseline")
        with mock.patch.object(demo_runner, "create_client"), \
                mock.patch.object(demo_runner, "train_from_firestore", side_effect=ValueError("No usable measurements")), \
                mock.patch.object(demo_runner, "predict_to_firestore") as predict:
            with self.assertRaises(ValueError):
                update()
        predict.assert_not_called()


@mock.patch.object(demo_runner, "log")
class ConcurrencyTests(TestCase):
    def test_tasks_run_independently_when_one_fails(self, _log):
        stop = threading.Event()
        counts = {"extraction": 0, "ml": 0}

        def extraction():
            counts["extraction"] += 1

        def broken_ml():
            counts["ml"] += 1
            raise RuntimeError("model down")

        workers = [threading.Thread(target=demo_runner.run_periodic, args=("Extraction", 0.01, extraction, stop)),
                   threading.Thread(target=demo_runner.run_periodic, args=("ML update", 0.01, broken_ml, stop))]
        for worker in workers:
            worker.start()
        time.sleep(0.15)
        self.assertTrue(all(worker.is_alive() for worker in workers))
        stop.set()
        for worker in workers:
            worker.join(1)
        self.assertGreater(counts["extraction"], 3)
        self.assertGreater(counts["ml"], 3)

    def test_ctrl_c_stops_workers_gracefully(self, log):
        stop = threading.Event()
        workers = [threading.Thread(target=demo_runner.run_periodic, args=(name, 60, lambda: None, stop))
                   for name in ("Extraction", "ML update")]
        for worker in workers:
            worker.start()

        def ctrl_c(_seconds):
            raise KeyboardInterrupt

        started = time.monotonic()
        demo_runner.supervise(workers, stop, wait=ctrl_c)
        self.assertTrue(stop.is_set())
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertLess(time.monotonic() - started, 2)  # did not wait out the 60 s interval
        log.assert_any_call("Demo pipeline stopped")


class CliTests(TestCase):
    def test_manual_location_validated(self):
        parser = demo_runner.build_parser()
        args = parser.parse_args(["--lat", "32.88", "--lon", "-117.23"])
        self.assertEqual(demo_runner.resolve_location(args, parser).current()[0], COORDS)
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            demo_runner.resolve_location(parser.parse_args(["--lat", "32.88"]), parser)

    @mock.patch.object(demo_runner, "log")
    def test_browser_tracker_receives_positions_over_http(self, _log):
        def post(url, body):
            request = urllib.request.Request(url + "location", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
            return urllib.request.urlopen(request, timeout=5).status

        opened = []

        def fake_browser(url):  # stands in for the tab: one page open, then position updates
            opened.append(url)
            threading.Thread(target=post, args=(url, {"latitude": 32.88, "longitude": -117.23, "accuracy_m": 35})).start()

        parser = demo_runner.build_parser()
        with mock.patch.object(demo_runner.webbrowser, "open", side_effect=fake_browser):
            tracker = demo_runner.resolve_location(parser.parse_args(["--browser-location"]), parser)
        try:
            self.assertEqual(len(opened), 1)  # one tab, one permission prompt
            self.assertEqual(tracker.current()[0], (32.88, -117.23, 35.0))
            self.assertEqual(post(opened[0], {"latitude": 32.89, "longitude": -117.24, "accuracy_m": 20}), 204)
            self.assertEqual(tracker.current()[0], (32.89, -117.24, 20.0))
            with self.assertRaises(urllib.error.HTTPError):
                post(opened[0], {"latitude": 999, "longitude": 0})
        finally:
            tracker.stop()
