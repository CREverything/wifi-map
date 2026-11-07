# WiFi Map prediction model

Python estimates for download Mbps, upload Mbps, and RSSI dBm. Run commands below from the repository root. No database or frontend setup is required.

## Setup and demo

Python 3.10+ is required.

```sh
python3 -m venv model/.venv
source model/.venv/bin/activate
pip install -r model/requirements.txt
# To reproduce the tested Python 3.13 environment exactly:
# pip install -r model/requirements-lock.txt
python -m unittest discover -s model/tests -v
python -m model demo
```

The demo generates **synthetic development data only**, trains in memory, and prints both prediction methods. It does not establish real-world accuracy. No real measurements or verified accuracy are included in this repository.

## Files and algorithms

- `config.py`: feature names and coverage thresholds.
- `preprocessing.py`: validation, time encoding, and geographic distances.
- `training.py`: separate scikit-learn random forests for each network, band, and target; save with joblib.
- `prediction.py`: load artifacts and return JSON-compatible estimates.
- `evaluation.py`: held-out session or spatial-block evaluation.
- `synthetic.py`: reproducible artificial data.
- `__main__.py`: train, predict, evaluate, and demo commands.
- `tests/test_model.py`: automated behavior checks.

The default baseline averages measurements within 500 meters on the exact same network and band, weighted by inverse squared distance (with a one-meter floor). Each target requires at least three measured values nearby; otherwise that target is null. Missing targets do not discard other usable measurements.

Random forests learn latitude, longitude, cyclic time of day, and device type independently for each network/band/target. They use the same nearby-data gate as the baseline. Missing numeric context is imputed; absent device types become `unknown`, and unseen device types are supported. Target speeds, RSSI, latency, and loss are never input features. Latency and loss can be stored as optional context but are deliberately excluded because they often won't exist at prediction time.

## Measurement format

Train on a JSON array of rows such as:

```json
[{
  "latitude": 32.88,
  "longitude": -117.23,
  "timestamp": "2026-11-07T22:00:00Z",
  "network_id": "stable-access-point-id",
  "wifi_band": "5GHz",
  "device_type": "android-phone",
  "download_mbps": 80.5,
  "upload_mbps": 22.1,
  "rssi_dbm": -62,
  "latency_ms": 18,
  "packet_loss": 0.01,
  "session_id": "collection-run-001",
  "data_source": "real"
}]
```

Latitude, longitude, network_id, wifi_band, and data_source are required for training. Targets and optional context may be omitted or null. Use `data_source: synthetic` for artificial measurements. Supply local `hour` in [0,24), or an ISO timestamp including timezone; timestamps are converted to San Diego time. Explicit hour takes priority. Unknown time is supported. Use consistent band identifiers such as `2.4GHz`, `5GHz`, `6GHz`.

Collect repeated GPS measurements, timezone-aware timestamps, stable AP identifiers (ideally a privacy-preserving BSSID hash), frequency band, device type, and collection session IDs across locations and times. An SSID shared across unrelated APs is not sufficient isolation. Avoid rotating identifiers that make the same AP appear new. Collect RSSI using the device's WiFi APIs; speed tests alone do not supply it. Account for GPS errors, permissions, and access-point movement.

Map speedtest-cli JSON `download` and `upload` from bits/second to Mbps by dividing by 1,000,000; map `ping` to latency_ms. LibreSpeed formats vary: map its documented download/upload units to Mbps explicitly. Add GPS/AP/band/RSSI from the collecting device. Store packet_loss as a fraction from 0 to 1. Missing RSSI must stay null; never derive it from speed. The canonical JSON format is the collector integration boundary; raw tool output is not automatically interpreted.

## Training and prediction

```sh
python -m model train measurements.json model/local.joblib
python -m model predict model/local.joblib '{"latitude":32.88,"longitude":-117.23,"network_id":"stable-access-point-id","wifi_band":"5GHz","hour":14}'
python -m model predict model/local.joblib '{"latitude":32.88,"longitude":-117.23,"network_id":"stable-access-point-id","wifi_band":"5GHz","hour":14}' --method random_forest
python -m model evaluate measurements.json --method baseline
python -m model evaluate measurements.json --method random_forest
```

Use real-only datasets for evaluation. Reports include MAE and RMSE for every target (Mbps for speeds, dBm for RSSI), predicted/eligible counts, and coverage. Null metrics mean no evaluable predictions. All rows in a collection session remain on the same side of the split. When session IDs are incomplete, use fixed approximately 1-km spatial blocks. Training happens only after splitting. Spatial splits may yield low coverage: this honestly reflects the refusal to extrapolate. Sessions at identical locations can still give optimistic geographic accuracy; use spatial evaluation or independently collected regions for that question. More diverse data and repeated group splits are needed before making accuracy claims.

## FastAPI integration

Install FastAPI separately in the backend environment. Load once at startup, using only a trusted joblib artifact (pickle files can execute code).

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from model import Predictor

app = FastAPI()
predictor = Predictor.load("model/local.joblib")

class PredictionRequest(BaseModel):
    latitude: float
    longitude: float
    network_id: str
    wifi_band: str
    hour: float | None = None
    timestamp: str | None = None
    device_type: str | None = None

@app.post("/predict")
def predict(request: PredictionRequest):
    try:
        return predictor.predict(request.model_dump(), method="baseline")
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

`Predictor(train(rows)).predict(request)` also works without disk storage. Return values include `download_mbps`, `upload_mbps`, `rssi_dbm`, `method`, `is_estimate`, `status`, `reliability`, `data_sources`, `synthetic_data_used`, and per-target coverage details. Null targets mean unavailable; the frontend should leave those map cells empty. Use the same Python environment and pinned dependency versions when sharing artifacts; retrain after dependency upgrades.

## Limits and reliability

Reliability is deliberately `low` for every available estimate, and `unavailable` otherwise. This is a coverage heuristic, not a calibrated probability or confidence interval. Three neighboring records may be correlated or repeated at one location. Radius/count thresholds are configurable on Predictor; defaults require three neighbors within 500m. Neither method models walls, building floors, congestion, device differences comprehensively, nor measurement age. Forests can smooth or memorize local patterns and cannot justify predictions for new networks. Refresh measurements and retrain when conditions change. The artifact records all source types conservatively: if any training data is synthetic, every response flags that fact. Never present synthetic estimates as verified real-world performance.

## Firestore collector integration

`firestore_io.py` reads the existing `measurements` collection and writes new documents only to `predictions`. No database migration is needed. Existing JSON commands still work.

```sh
pip install -r model/requirements-firestore.txt
cp model/.env.example .env
# Edit .env with your real project ID and service-account file path.
python -m model firestore-train model/firestore.joblib
python -m model firestore-predict model/firestore.joblib '{"latitude":32.88415,"longitude":-117.23310,"bssid":"aa:bb:cc:dd:ee:ff","band_ghz":"5","measured_at":"2026-11-07T22:22:42Z"}' --method random_forest
```

Credentials are loaded using Google Application Default Credentials and `GOOGLE_APPLICATION_CREDENTIALS`. `.env` is loaded explicitly without overriding existing environment variables. Keep the service-account JSON in the ignored `secrets/` folder. No credentials are included here. `--env-file` selects another .env path; `FIRESTORE_DATABASE` defaults to `(default)`. Use the Firebase **project ID**, which may differ from its display name. The separate Firestore requirements file adds optional dependencies; the existing lock file covers the core model only.

Collector mappings:

| Firestore field | Model field |
|---|---|
| `network_id`, or nonempty `bssid` | Network identity; BSSIDs become lowercase `bssid:<value>` |
| `band_ghz` (`"5"`, `5`, `"2.4"`, `"6"`) | `wifi_band` (`5GHz`, `2.4GHz`, `6GHz`) |
| `measured_at` (Firestore datetime or timezone-aware ISO string) | `timestamp` |
| `device.os_name` | `device_type` |
| `download_mbps`, `upload_mbps`, `rssi_dbm`, `latency_ms` | Same names and units |
| `packet_loss_pct` | `packet_loss` divided by 100 |
| `session_id`, when collected | Held-out evaluation grouping |

Documents from this collector default to `data_source: real`; explicitly label any synthetic database records `synthetic`. Targets may be null. Additional fields such as channel, location accuracy, speedtest server, errors, and device ID are not prediction features. The adapter uses `latency_ms`, not `speedtest_ping_ms`; neither is currently an input feature.

**The supplied example has null BSSID and no network_id, so it is skipped.** Update the collector to provide a stable AP identity, or add an explicit network_id only when you know records belong to the same network. Do not substitute device_id, SSID, cell_id, or a global `unknown` identity. Training reports document IDs/reasons for skipped records and fails without saving when all records are unusable. Three usable nearby measurements per target are still required. One database document is insufficient.

Prediction requests may use collector-style fields (as above) or the original canonical request JSON. Use the same identity convention as training: a BSSID request resolves to `bssid:<lowercase BSSID>`. `firestore-predict` loads an existing model; it does not retrain or continuously watch the database. Run `firestore-train` again after collecting more data.

Each prediction document includes flat download/upload/RSSI estimates, status, method, per-target nearby counts, reliability, synthetic flags, location, network, band, request time, creation time, model filename, and Firestore training provenance. Unavailable results are stored with null targets. A new prediction document ID is returned on each call. A prediction at a training location demonstrates integration, not held-out accuracy.

For backend code:

```python
from model import Predictor
from model.firestore_io import create_client, predict_to_firestore

client = create_client()
predictor = Predictor.load("model/firestore.joblib")
# Call inside your backend endpoint; request is a JSON-compatible dictionary.
result = predict_to_firestore(client, predictor, request, method="random_forest",
                              model_id="firestore.joblib")
```

Firestore tests use mocked clients and never access a live project. To evaluate real collector records separately, call `rows, skipped = read_measurements(client)` and then `evaluate(rows)`. Collect session_id for meaningful session splits, or enough spatial blocks for the spatial fallback.
