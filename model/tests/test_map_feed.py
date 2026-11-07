from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import MagicMock
from model.map_feed import MAP_FIELDS, read_predictions


def snapshot(doc_id, document):
    snap = MagicMock()
    snap.id = doc_id
    snap.to_dict.return_value = document
    return snap


class MapFeedTests(TestCase):
    def test_reads_newest_predictions_as_json_safe_map_fields(self):
        stamp = datetime(2026, 11, 7, 22, tzinfo=timezone.utc)
        document = {"prediction_id": "p1", "predicted_at": stamp, "latitude": 32.88, "longitude": -117.23,
                    "download_mbps": 51.5, "rssi_dbm": -56, "status": "partial",
                    "targets": {"rssi_dbm": {"nearby_count": 3}},
                    "training": {"trained_at": stamp}, "model_id": "firestore.joblib"}
        client = MagicMock()
        query = client.collection.return_value.order_by.return_value.limit.return_value
        query.stream.return_value = [snapshot("p1", document), snapshot("auto-id", {"latitude": 1})]

        predictions = read_predictions(client, limit=5)

        client.collection.assert_called_with("predictions")
        self.assertEqual(client.collection.return_value.order_by.call_args.args[0], "predicted_at")
        client.collection.return_value.order_by.return_value.limit.assert_called_with(5)
        self.assertEqual(set(predictions[0]), set(MAP_FIELDS))
        self.assertEqual(predictions[0]["predicted_at"], "2026-11-07T22:00:00+00:00")
        self.assertIsNone(predictions[0]["upload_mbps"])  # missing stays null
        self.assertNotIn("training", predictions[0])
        self.assertEqual(predictions[1]["prediction_id"], "auto-id")
