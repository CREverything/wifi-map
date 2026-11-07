"""Firestore boundary: collector documents in, separate estimate documents out."""
import os
from datetime import datetime, timezone
from pathlib import Path
from .config import TARGETS
from .preprocessing import normalize
from .training import train


def create_client(env_file=".env"):
    from dotenv import load_dotenv
    from google.cloud import firestore
    load_dotenv(env_file, override=False)
    return firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                            database=os.getenv("FIRESTORE_DATABASE", "(default)"))


def network_identity(document):
    # Neither a device ID nor an SSID alone reliably identifies an access point.
    explicit = document.get("network_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    bssid = document.get("bssid")
    if isinstance(bssid, str) and bssid.strip():
        return "bssid:" + bssid.strip().lower()
    raise ValueError("missing_network_identity: collect bssid or a stable network_id")


def band_name(value):
    text = str(value).strip().lower().replace("ghz", "").strip()
    aliases = {"2.4": "2.4GHz", "5": "5GHz", "5.0": "5GHz", "6": "6GHz", "6.0": "6GHz"}
    if text not in aliases:
        raise ValueError("band_ghz must be 2.4, 5, or 6")
    return aliases[text]


def convert_document(document):
    device = document.get("device") or {}
    row = {"latitude": document.get("latitude"), "longitude": document.get("longitude"),
           "network_id": network_identity(document),
           "wifi_band": band_name(document.get("band_ghz")),
           "timestamp": document.get("measured_at"),
           "device_type": device.get("os_name"),
           "data_source": document.get("data_source", "real"),
           "latency_ms": document.get("latency_ms"),
           "measurement_id": document.get("measurement_id")}
    if document.get("session_id") is not None:
        row["session_id"] = document["session_id"]
    loss = document.get("packet_loss_pct")
    if loss is not None:
        loss = float(loss)
        if not 0 <= loss <= 100:
            raise ValueError("packet_loss_pct must be between 0 and 100")
        row["packet_loss"] = loss / 100
    for target in TARGETS:
        row[target] = document.get(target)
    # Validate without discarding optional context; training re-normalizes this row.
    normalize(row, training=True)
    return row


def read_measurements(client, collection="measurements"):
    rows, skipped = [], []
    for snapshot in client.collection(collection).stream():
        try:
            row = convert_document(snapshot.to_dict())
            row["measurement_id"] = row.get("measurement_id") or snapshot.id
            rows.append(row)
        except (ValueError, TypeError, KeyError) as exc:
            skipped.append({"document_id": snapshot.id, "reason": str(exc)})
    return rows, skipped


def train_from_firestore(client, output, collection="measurements"):
    rows, skipped = read_measurements(client, collection)
    if not rows:
        raise ValueError(f"No usable measurements; {len(skipped)} skipped. "
                         "Collect bssid/network_id, band, and valid coordinates. "
                         f"Details: {skipped}")
    artifact = train(rows)
    artifact["firestore_training"] = {"collection": collection,
        "trained_at": datetime.now(timezone.utc).isoformat(), "row_count": len(rows)}
    import joblib
    joblib.dump(artifact, output)
    return {"artifact": str(output), "accepted_count": len(rows), "skipped": skipped,
            "data_sources": artifact["data_sources"], "trained_target_models": len(artifact["models"])}


def predict_to_firestore(client, predictor, request, method="baseline", model_id=None):
    """Accept canonical request JSON OR collector-style location/network fields."""
    if "wifi_band" in request:
        canonical = dict(request)
        canonical["network_id"] = network_identity(request)
    else:
        canonical = convert_document(request)
    result = predictor.predict(canonical, method)
    # Store a new document, never replace collected measurements.
    document = {**result, "latitude": canonical["latitude"], "longitude": canonical["longitude"],
                "network_id": canonical["network_id"], "wifi_band": canonical["wifi_band"],
                "requested_hour": canonical.get("hour"),
                "requested_timestamp": canonical.get("timestamp"),
                "model_id": model_id, "training": predictor.artifact.get("firestore_training"),
                "created_at": datetime.now(timezone.utc)}
    reference = client.collection("predictions").document()
    reference.set(document)
    return {**result, "prediction_id": reference.id}
