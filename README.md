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

## Tests

```sh
python -m unittest discover -s extractor/tests
python -m unittest discover -s model/tests
```
