# wifi-map

MLH project: map campus Wi-Fi quality. Laptops collect real measurements into Firestore, and a model estimates download/upload speed and RSSI for nearby locations.

| Folder | Purpose |
| --- | --- |
| `extractor/` | macOS/Windows collector: RSSI, speed test, ping, location → Firestore `measurements` ([details](extractor/README.md)) |
| `model/` | Trains on `measurements`, writes estimates to Firestore `predictions` ([details](model/README.md)) |

## Setup

Python 3.10+. One virtual environment at the repo root covers everything:

```sh
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Firestore access uses a service-account key kept in the gitignored `secrets/` folder. Put its path in a root `.env`:

```sh
GOOGLE_APPLICATION_CREDENTIALS=secrets/serviceAccountKey.json
GOOGLE_CLOUD_PROJECT=<firebase-project-id>
```

Never commit `.env` or anything in `secrets/`.

## Usage

Run from the repo root:

```sh
# Collect one measurement and upload it
python extractor/collect.py --browser-location --firestore --no-local

# Train on Firestore measurements, then write a prediction
python -m model firestore-train model/firestore.joblib
python -m model firestore-predict model/firestore.joblib '{"latitude":32.884,"longitude":-117.233,"bssid":"aa:bb:cc:dd:ee:ff","band_ghz":"5"}'
```

## Demo orchestrator

One command runs continuous collection and model updates until you press **Ctrl+C**:

```sh
python3 demo_runner.py --browser-location        # browser asks for location once
python3 demo_runner.py --lat 32.88 --lon -117.23 # or give coordinates manually
```

- Location is resolved once at startup and reused for every measurement.
- A measurement (RSSI, ping) is uploaded to `measurements` about every **10 s**; a full speed test runs about every **5 min** (that sample takes up to a minute).
- The model retrains from Firestore and writes a prediction for your location to `predictions` at startup and about every **5 min**.
- Tune with `--extract-interval`, `--speedtest-interval` (0 disables), `--ml-interval` (seconds), and `--method`.

Every console line is timestamped. Success looks like `Measurement uploaded: <id>` and `ML update completed: prediction <id> status=...`; problems print as `Extraction failed: ...`, `Extraction warning: ...`, or `ML update failed: ...` and the task retries on its next run. Failed uploads are saved to `extractor/data/` as a backup. A prediction stays `status=unavailable` until at least 3 measurements exist within 500 m.

## Tests

```sh
python -m unittest discover -s extractor/tests
python -m unittest discover -s model/tests
python -m unittest discover -s tests
```
