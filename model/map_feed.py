"""Read recent `predictions` documents for the map frontend.

Run from the repo root: python -m model.map_feed [--limit N]
Prints one MAP_FEED_RESULT line: {"predictions": [...]}, newest first, with only
the fields the map uses and timestamps as ISO 8601 strings. Read-only.
"""
import argparse
import json
from datetime import datetime

from .firestore_io import PREDICTIONS_COLLECTION, create_client

RESULT_PREFIX = "MAP_FEED_RESULT:"
DEFAULT_LIMIT = 1000

# Fields written by prediction_document() that the map needs.
MAP_FIELDS = ("prediction_id", "predicted_at", "latitude", "longitude", "bssid", "network_id",
              "band_ghz", "download_mbps", "upload_mbps", "rssi_dbm", "status", "reliability",
              "method", "targets", "synthetic_data_used")


def json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def read_predictions(client, limit=DEFAULT_LIMIT):
    """Newest `limit` predictions, as JSON-safe dicts limited to MAP_FIELDS."""
    from google.cloud import firestore
    query = (client.collection(PREDICTIONS_COLLECTION)
             .order_by("predicted_at", direction=firestore.Query.DESCENDING)
             .limit(limit))
    predictions = []
    for snapshot in query.stream():
        document = snapshot.to_dict()
        prediction = {field: json_safe(document.get(field)) for field in MAP_FIELDS}
        prediction["prediction_id"] = prediction["prediction_id"] or snapshot.id
        predictions.append(prediction)
    return predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    predictions = read_predictions(create_client(), args.limit)
    print(RESULT_PREFIX + json.dumps({"predictions": predictions}))


if __name__ == "__main__":
    main()
