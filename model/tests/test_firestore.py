from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path
from model.firestore_io import convert_document, read_measurements, train_from_firestore, predict_to_firestore
from model.training import train
from model.prediction import Predictor
from fixtures import sample_rows


def collector():
    return dict(latitude=32.88, longitude=-117.23, band_ghz="5", bssid="AA:BB:CC:DD:EE:FF",
                measured_at=datetime(2026, 11, 7, 22, tzinfo=timezone.utc),
                device={"os_name": "Darwin"}, download_mbps=51.5, upload_mbps=26.8,
                rssi_dbm=-56, packet_loss_pct=2, latency_ms=7.49)


class FirestoreTests(TestCase):
    def test_conversion(self):
        row = convert_document(collector())
        self.assertEqual(row["wifi_band"], "all")
        self.assertEqual(row["network_id"], "all")
        self.assertEqual(row["packet_loss"], .02)
        self.assertEqual(row["device_type"], "Darwin")
        self.assertEqual(row["data_source"], "real")
        self.assertEqual(convert_document({**collector(), "rssi_dbm": None})["rssi_dbm"], None)

    def test_location_only_accepts_missing_bssid_and_band(self):
        row = convert_document({**collector(), "bssid": None, "band_ghz": None})
        self.assertEqual(row["network_id"], "all")

    @patch("model.config.GROUP_BY_NETWORK", True)
    def test_grouped_conversion(self):
        row = convert_document(collector())
        self.assertEqual(row["wifi_band"], "5GHz")
        self.assertEqual(row["network_id"], "bssid:aa:bb:cc:dd:ee:ff")

    @patch("model.config.GROUP_BY_NETWORK", True)
    def test_missing_identity_is_not_device_or_ssid(self):
        with self.assertRaisesRegex(ValueError, "missing_network_identity"):
            convert_document({**collector(), "bssid": None, "ssid": "public", "device": {"device_id": "abc"}})

    def test_read_reports_skipped(self):
        good, bad = MagicMock(), MagicMock()
        good.id, bad.id = "good", "bad"
        good.to_dict.return_value = collector()
        bad.to_dict.return_value = {**collector(), "latitude": 999}
        client = MagicMock()
        client.collection.return_value.stream.return_value = [good, bad]
        rows, skipped = read_measurements(client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped[0]["document_id"], "bad")
        self.assertEqual(rows[0]["measurement_id"], "good")

    def test_train_and_write_separate_collection(self):
        client = MagicMock()
        snapshots = []
        for i in range(3):
            snap = MagicMock()
            snap.id = str(i)
            snap.to_dict.return_value = collector()
            snapshots.append(snap)
        client.collection.return_value.stream.return_value = snapshots
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "real.joblib"
            report = train_from_firestore(client, path)
            self.assertEqual(report["accepted_count"], 3)
            predictor = Predictor.load(path)
            result = predict_to_firestore(client, predictor, collector(), "random_forest", "test")
            self.assertEqual(result["status"], "available")
        client.collection.assert_called_with("predictions")
        document = client.collection.return_value.document.return_value.set.call_args.args[0]
        self.assertEqual(document["data_sources"], ["real"])
        self.assertTrue(document["is_estimate"])
        self.assertEqual(document["training"]["row_count"], 3)
        self.assertIsInstance(document["training"]["trained_at"], datetime)

    def test_prediction_fields_match_collector_naming(self):
        client = MagicMock()
        predictor = Predictor(train([{**r, "network_id": "bssid:aa:bb:cc:dd:ee:ff"} for r in sample_rows(10)]))
        result = predict_to_firestore(client, predictor, {**collector(), "measured_at": "2026-11-07T22:00:00Z"})
        reference = client.collection.return_value.document
        reference.assert_called_with(result["prediction_id"])
        document = reference.return_value.set.call_args.args[0]
        self.assertEqual(document["prediction_id"], result["prediction_id"])
        self.assertEqual(document["bssid"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(document["band_ghz"], "5")
        self.assertNotIn("wifi_band", document)
        self.assertEqual(document["requested_at"], datetime(2026, 11, 7, 22, tzinfo=timezone.utc))
        self.assertEqual(document["predicted_at"].tzinfo, timezone.utc)
        for target in ("download_mbps", "upload_mbps", "rssi_dbm"):
            self.assertIn(target, document)

    def test_unavailable_prediction_written_without_invented_values(self):
        client = MagicMock()
        predictor = Predictor(train(sample_rows(10)))
        result = predict_to_firestore(client, predictor, {**collector(), "latitude": 33.5})
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["download_mbps"])

    def test_no_usable_rows_does_not_save(self):
        client = MagicMock()
        client.collection.return_value.stream.return_value = []
        with self.assertRaisesRegex(ValueError, "No usable measurements"):
            train_from_firestore(client, "unused.joblib")
