# Field — Wi-Fi map interface

React, Vite, Leaflet, and MapLibre frontend with simulated metric heatmaps, browser location, and an optional local Python collector. The Firebase → LLM → live map prediction pipeline still needs the team's endpoint; it is not simulated as a working live connection.

## Run

Install Node.js 22.12+ (24 LTS recommended):

```sh
npm install
npm run dev
```

Open the localhost URL, not index.html directly. Restart Vite after changing environment variables. Use HTTPS for a deployed frontend. The local collector bridge works only with `npm run dev`, not static hosting or `npm run preview`.

## Map and heatmaps

- Use my location asks browser permission and fits the map to the reported accuracy bounds. Laptop location can be approximate, especially indoors.
- 200 fictional San Diego points are displayed initially and clearly marked SIMULATION. Simulate heatmap restores them; Clear removes them.
- Checkbox layers: connection (purple, 0–1), download (blue, 0–200+ Mbps), upload (pink, 0–100+ Mbps), latency (gray, 0–200+ ms). Darker latency means a slower response. Multiple layers blend colors; one selected layer is easiest to interpret.
- Geographic image bounds keep overlays attached to the map during pan and animated zoom. Blurred kernels use weighted averages; their edges fade to transparent. This is illustrative interpolation, not validated coverage prediction.
- Imported legacy areas without metrics have a separate red Model intensity layer. Missing metric values are never invented.
- Custom vector colors in public/basemap-style.json use Esri data, fonts, sprites, and tiles—not Google Maps. Internet and WebGL are required. Initial WebGL failure falls back to raster tiles.

## Provisional LLM response contract

```json
{
  "version": 1,
  "summary": "Explanation of the model output",
  "areas": [{
    "latitude": 32.7157,
    "longitude": -117.1611,
    "radiusMeters": 150,
    "intensity": 0.8,
    "explanation": "Why this area is highlighted",
    "metrics": {
      "connection": 0.8,
      "downloadMbps": 120,
      "uploadMbps": 35,
      "latencyMs": 28
    }
  }]
}
```

Import model JSON previews this contract. `src/model-adapter.js` exposes `decodeModelResponse(payload)` for a future API handler. Keep model keys on your backend. No prediction endpoint or automatic LLM polling is configured. Model text is rendered as plain text. File limit: 5 MB; maximum 10,000 areas; summary 4,000 characters; explanations 2,000 characters; valid finite coordinates; radius >0 and ≤100,000 m. Metrics are optional; connection is 0–1, other metrics nonnegative. Invalid imports preserve the prior map layer.

## Local collector and five-minute schedule

The unchanged extractor source and requirements were copied from the repository's backend branch, commit cf09e59df4adf268bc0a4f0d0275d12c949ba095. `extractor/bridge.py` integrates that collector with the local Vite endpoint. The bridge takes a fresh browser-approved location and never executes browser-supplied commands.

Install Python 3.10+ and dependencies:

Windows:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS:
```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The bridge prefers .venv; `PYTHON_EXECUTABLE` can override its executable. This laptop's environment was prepared locally; it is ignored by Git and must be recreated on other machines.

In Live collection, click Start 5-minute schedule. It triggers at :00, :05, :10, etc. The clock uses your device's local timezone. Collect now runs separately. Each run requests fresh location; denial skips the run. One run at a time, with a four-minute timeout. Browser sleep/throttling may delay execution; resuming causes at most one catch-up attempt. Keep the browser and Vite process open and the laptop awake. Stop prevents future submissions; already submitted collection may finish. This is not an OS/background scheduler.

Signal/ping collection is the default. Download/upload testing is an explicit toggle because it can use substantial bandwidth. JSONL/CSV files are saved in extractor/data (ignored by Git). Firebase upload is opt-in; set GOOGLE_APPLICATION_CREDENTIALS locally or in the gitignored root .env. Upload failure retains local data. Service-account credentials never go into frontend code. No live collection is started automatically on page load.

Collected data is distinct from predictions: collection → Firebase → your team's LLM → validated map response. The interface does not turn local readings into fake model output.

## Privacy and validation

Map location and imported model responses stay in browser memory unless you explicitly start collection. Collection saves fresh location and network metadata locally and uploads only when enabled. Esri receives tile requests for the area viewed; Google Fonts serves the font. Browser geolocation uses the OS/browser location provider.

`npm test` checks model validation, simulation metrics, schedule boundaries, and bridge input validation. `npm run build` produces dist/. The Python bridge was smoke-tested with mocked measurements and storage; no real location, bandwidth test, or Firebase upload was used for validation. Browser rendering remains to be verified on the laptop. Test panning/zooming, layer checkboxes, permission denial, and collection in the local app.
