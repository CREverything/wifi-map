# wifi-map

MLH project: map campus Wi-Fi quality. Laptops collect real measurements into Firestore, a model estimates download/upload speed and RSSI for nearby locations, and a web map shows the results.

| Folder | Purpose |
| --- | --- |
| `extractor/` | macOS/Windows collector: RSSI, speed test, ping, location → Firestore `measurements` ([details](extractor/README.md)) |
| `model/` | Trains on `measurements`, writes estimates to Firestore `predictions` ([details](model/README.md)) |
| `src/`, `server/`, `public/` | React + Leaflet map frontend (Vite), with a dev-only bridge to the local collector |

**Naming:** data fields use the backend's snake_case names everywhere (`latitude`, `longitude`, `download_mbps`, `upload_mbps`, `latency_ms`, `rssi_dbm`, `radius_m`, `accuracy_m`); JavaScript variables use camelCase.

## Setup

Python 3.10+. One virtual environment at the repo root covers the collector and model:

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

Frontend: Node.js 22.12+ (24 LTS recommended), then `npm install`.

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
- The model retrains from Firestore at startup and about every **5 min**, then writes a prediction to `predictions` for your location and for every other place with measurements (to ~11 m, up to 200 places per update). Nothing is predicted where nobody measured.
- Tune with `--extract-interval`, `--speedtest-interval` (0 disables), `--ml-interval` (seconds), and `--method`.

Every console line is timestamped. Success looks like `Measurement uploaded: <id>` and `ML update completed: N prediction(s) written (… available/partial)`; problems print as `Extraction failed: ...`, `Extraction warning: ...`, or `ML update failed: ...` and the task retries on its next run. Failed uploads are saved to `extractor/data/` as a backup. A prediction stays `status=unavailable` until at least 3 measurements exist within 500 m, and each target needs its own 3: RSSI fills in after ~30 s, but download/upload need 3 speed tests nearby.

### Running a live demo

1. Terminal 1: `python3 demo_runner.py --browser-location --ml-interval 60` (add `--speedtest-interval 60` for a few minutes to fill the download/upload layers quickly; speed tests use a lot of bandwidth).
2. Terminal 2: `npm run dev`, then open the printed URL. The map syncs with Firestore every minute; the tag reads **LIVE PREDICTIONS · FIRESTORE**.
3. To map another spot, stop the runner (Ctrl+C), move, and start it again; earlier spots stay on the map.

## Map frontend

```sh
npm run dev
```

Open the printed localhost URL (not `index.html` directly). The local collector bridge only works with `npm run dev`.

- **Your location** asks browser permission and fits the map to the reported accuracy. Laptop location can be approximate, especially indoors.
- **Heatmap overlay:** RSSI (purple, −90 to −30 dBm), download (blue, 0–200+ Mbps), upload (pink, 0–100+ Mbps), latency (gray, 0–200+ ms). Areas without metrics use a separate red model-intensity layer. Missing values are never invented.
- **Model insights:** the map shows the Firestore `predictions` collection and re-syncs every minute (including while it's still empty), so new predictions from `demo_runner.py` appear within about a minute; *Sync now* forces a read. *Import model JSON* previews a file and pauses the sync until *Back to live predictions*. There is no simulated data.
- **Live collection:** *Collect now* or *Start 5-minute schedule* (at :00, :05, …) runs `extractor/bridge.py` through the dev server with a fresh browser location. Speed tests and Firebase upload are opt-in toggles; credentials stay on the laptop and never reach the browser. Keep the tab open and the laptop awake.
- The basemap uses Esri vector tiles (`public/basemap-style.json`) and falls back to raster tiles if WebGL fails.

### Map data format

```json
{
  "version": 1,
  "summary": "Explanation of the model output",
  "areas": [{
    "latitude": 32.7157,
    "longitude": -117.1611,
    "radius_m": 150,
    "intensity": 0.8,
    "explanation": "Why this area is highlighted",
    "metrics": { "rssi_dbm": -58, "download_mbps": 120, "upload_mbps": 35, "latency_ms": 28 }
  }]
}
```

Validated by `src/model-response.js` (`decodeModelResponse`). Limits: 5 MB file, 10,000 areas, 4,000-character summary, 2,000-character explanations, finite coordinates, `0 < radius_m ≤ 100000`, `intensity` 0–1. Metrics are optional: `rssi_dbm` −150 to 0, others nonnegative. Text is rendered as plain text, and an invalid import keeps the previous map.

### Live predictions

`GET /api/predictions` (dev server, `server/predictions-plugin.js`) runs `python -m model.map_feed`, which reads the newest 1,000 `predictions` documents with the laptop's Admin credentials. Firestore rules stay closed and no key or Firebase config reaches the browser. `src/predictions.js` converts each document to an area:

| Prediction field | Map area |
| --- | --- |
| `latitude`, `longitude` | Same |
| `download_mbps`, `upload_mbps`, `rssi_dbm` | `metrics` (null estimates are left out) |
| — | `latency_ms`: none; the model doesn't predict it, so that layer shows "No data" |
| — | `radius_m`: 150 m display spread (`PREDICTION_RADIUS_M`) |
| Share of the 3 targets estimated | `intensity` |
| `status`, `method`, `reliability`, `targets.*.nearby_count`, `band_ghz`, `predicted_at`, `synthetic_data_used` | Popup text |

Only the newest prediction per location (≈1 m), network, and band is shown; `unavailable` predictions are hidden and counted in the summary.

### How the heatmap works

Each selected layer is drawn by `src/heat-layer.js` onto a canvas at one-third screen resolution:

1. Each area's value is placed on the layer's scale (e.g. RSSI −90 → 0, −30 → 1; values beyond are clamped).
2. Around each area, pixels within `radius_m` get a weight that falls smoothly from 1 at the centre to 0 at the edge (`e^(−4d²)·(1−d²)`, d = distance / radius).
3. Where areas overlap, a pixel's colour is the **weighted average** of their values, so nearby estimates blend instead of stacking up; colour runs between the layer's light (low) and dark (high) shade.
4. Opacity follows the total weight, so colour fades out at the edges and places with no nearby area stay transparent; nothing is extrapolated.
5. The image is pinned to geographic bounds and redrawn after every pan, zoom, or resize, so it stays attached to the map.

Selecting several layers overlays them and their colours mix; one layer at a time is easiest to read.

## Tests

```sh
python -m unittest discover -s extractor/tests
python -m unittest discover -s model/tests
python -m unittest discover -s tests
npm test
npm run build
```
