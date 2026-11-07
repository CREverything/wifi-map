import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from model import Predictor
from model.training import train
from model.evaluation import evaluate
from model.preprocessing import normalize
from fixtures import NETWORK, sample_rows


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = sample_rows(60)
        cls.artifact = train(cls.rows)
        cls.query = dict(latitude=32.88, longitude=-117.23, network_id=NETWORK, wifi_band="5GHz")

    def test_both_methods_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            train(self.rows, path)
            predictor = Predictor.load(path)
            for method in ("baseline", "random_forest"):
                result = predictor.predict(self.query, method)
                self.assertEqual(result["status"], "available")
                self.assertFalse(result["synthetic_data_used"])
                json.dumps(result, allow_nan=False)

    def test_location_only_pools_networks_but_not_distance(self):
        predictor = Predictor(self.artifact)
        for method in ("baseline", "random_forest"):
            self.assertEqual(predictor.predict(dict(latitude=32.88, longitude=-117.23), method)["status"], "available")
            self.assertEqual(predictor.predict({**self.query, "network_id": "other"}, method)["status"], "available")
            self.assertEqual(predictor.predict({**self.query, "latitude": 33.5}, method)["status"], "unavailable")

    def test_no_cross_network_band_or_distant_estimates_when_grouped(self):
        with mock.patch("model.config.GROUP_BY_NETWORK", True):
            predictor = Predictor(train(self.rows))
            for changes in ({"network_id": "unknown"}, {"wifi_band": "2.4GHz"}, {"latitude": 33.5}):
                for method in ("baseline", "random_forest"):
                    self.assertEqual(predictor.predict({**self.query, **changes}, method)["status"], "unavailable")

    def test_missing_targets_and_context(self):
        rows = [{k: v for k, v in row.items() if k not in ("rssi_dbm", "hour", "device_type")} for row in self.rows]
        result = Predictor(train(rows)).predict(self.query, "random_forest")
        self.assertIsNone(result["rssi_dbm"])
        self.assertIsNotNone(result["download_mbps"])

    def test_baseline_exact_value_and_sparse_target(self):
        rows = [{**r, "download_mbps": 42, "rssi_dbm": None} for r in self.rows[:3]]
        result = Predictor(train(rows)).predict(self.query)
        self.assertAlmostEqual(result["download_mbps"], 42)
        self.assertIsNone(result["rssi_dbm"])
        self.assertEqual(Predictor(train(rows[:2])).predict(self.query)["status"], "unavailable")

    def test_target_leakage(self):
        predictor = Predictor(self.artifact)
        for method in ("baseline", "random_forest"):
            before = predictor.predict(self.query, method)
            after = predictor.predict({**self.query, "download_mbps": 9999, "upload_mbps": 9999, "rssi_dbm": -1, "latency_ms": 999}, method)
            for target in ("download_mbps", "upload_mbps", "rssi_dbm"):
                self.assertAlmostEqual(before[target], after[target], places=10)

    def test_validation_and_timezone(self):
        with self.assertRaises(ValueError):
            normalize({**self.query, "latitude": float("nan")})
        with self.assertRaises(ValueError):
            normalize({**self.query, "timestamp": "2026-01-01T12:00:00"})
        row = normalize({**self.query, "timestamp": "2026-01-01T22:00:00Z"})
        self.assertAlmostEqual(row["hour_sin"], -.5)

    def test_evaluation(self):
        with self.assertRaises(ValueError):
            evaluate([{**r, "data_source": "synthetic"} for r in self.rows])
        report = evaluate(self.rows)  # exercises code only, not empirical validation
        for stats in report["targets"].values():
            self.assertIsNotNone(stats["mae"])
            self.assertGreaterEqual(stats["rmse"], stats["mae"] - 1e-9)


if __name__ == "__main__":
    unittest.main()
