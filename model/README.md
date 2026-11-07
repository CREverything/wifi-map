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
