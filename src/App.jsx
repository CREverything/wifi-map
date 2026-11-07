import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { maplibreGL } from '@maplibre/maplibre-gl-leaflet';
import { HeatLayer } from './heat-layer.js';
import CollectionPanel from './CollectionPanel.jsx';
import { DEFAULT_METRIC_ID, INTENSITY_METRIC_ID, METRICS, areasForMetric, rgb } from './metrics.js';
import { decodeModelResponse } from './model-response.js';
import { fetchPredictions } from './predictions.js';

const DATA_SOURCE = { firestore: 'Firestore predictions', imported: 'Imported JSON' };
const DEFAULT_METRIC_IDS = [DEFAULT_METRIC_ID];
const PREDICTIONS_REFRESH_MS = 60 * 1000;
const MAP_CENTER = [32.8801, -117.234]; // UCSD
const MAX_IMPORT_BYTES = 5 * 1024 * 1024;
const BASEMAP_ATTRIBUTION = '© Esri, HERE, Garmin, OpenStreetMap contributors, GIS User Community';
const FALLBACK_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';
const LOCATION_ERRORS = {
  1: 'Location access was denied. Allow location in your browser’s site settings, then try again.',
  2: 'Your device could not determine its location. Check OS location services and try again.',
  3: 'Location lookup timed out. Try again or continue exploring manually.',
};

function areaPopupText(area) {
  const metrics = METRICS
    .filter((metric) => Number.isFinite(area.metrics?.[metric.id]))
    .map((metric) => `${metric.label}: ${Math.round(area.metrics[metric.id] * 100) / 100}`);
  return [area.explanation, ...metrics, `Radius ${Math.round(area.radius_m)} m`].join(' · ');
}

export default function App() {
  const mapElementRef = useRef(null);
  const mapRef = useRef(null);
  const heatmapLayerRef = useRef(null);
  const deviceLayerRef = useRef(null);
  const locateRequestRef = useRef(0); // ignores location answers that arrive after a newer request

  const [locationStatus, setLocationStatus] = useState('Location is off. Explore the map or locate your device.');
  const [locating, setLocating] = useState(false);
  const [devicePosition, setDevicePosition] = useState(null);
  const [areas, setAreas] = useState([]);
  const [dataSource, setDataSource] = useState(DATA_SOURCE.firestore);
  const [summary, setSummary] = useState('');
  const [selectedMetricIds, setSelectedMetricIds] = useState(DEFAULT_METRIC_IDS);
  const [heatmapVisible, setHeatmapVisible] = useState(true);
  const [heatmapOpacity, setHeatmapOpacity] = useState(70);
  const [tilesFailed, setTilesFailed] = useState(false);
  const [importError, setImportError] = useState('');
  const [predictionsStatus, setPredictionsStatus] = useState('Loading predictions from Firestore…');
  const [loadingPredictions, setLoadingPredictions] = useState(false);
  const loadingPredictionsRef = useRef(false); // prevents overlapping Firestore reads
  const fittedToPredictionsRef = useRef(false);
  const dataSourceRef = useRef(dataSource);
  dataSourceRef.current = dataSource;

  useEffect(() => {
    const map = L.map(mapElementRef.current, { zoomControl: false, minZoom: 2, maxZoom: 19 }).setView(MAP_CENTER, 13);
    mapRef.current = map;
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    L.control.scale({ position: 'bottomleft' }).addTo(map);
    try {
      const basemap = maplibreGL({ style: '/basemap-style.json', attribution: BASEMAP_ATTRIBUTION }).addTo(map);
      basemap.getMaplibreMap().on('error', () => setTilesFailed(true));
    } catch {
      // WebGL unavailable: fall back to raster tiles.
      setTilesFailed(true);
      L.tileLayer(FALLBACK_TILES, { maxZoom: 19, attribution: 'Tiles © Esri and contributors' }).addTo(map);
    }
    heatmapLayerRef.current = L.layerGroup().addTo(map);
    deviceLayerRef.current = L.layerGroup().addTo(map);
    return () => {
      locateRequestRef.current++;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const layer = heatmapLayerRef.current;
    layer.clearLayers();
    if (!heatmapVisible) return;
    for (const metric of METRICS) {
      if (selectedMetricIds.includes(metric.id)) {
        new HeatLayer(areasForMetric(areas, metric), heatmapOpacity, metric.colors).addTo(layer);
      }
    }
    for (const area of areas) {
      if (area.intensity <= 0) continue;
      const popup = document.createElement('div');
      popup.textContent = areaPopupText(area); // plain text: model output is never rendered as HTML
      L.circle([area.latitude, area.longitude], { radius: area.radius_m, stroke: false, fillOpacity: 0 })
        .bindPopup(popup)
        .addTo(layer);
    }
  }, [areas, heatmapVisible, heatmapOpacity, selectedMetricIds]);

  function locateDevice() {
    if (!window.isSecureContext) {
      setLocationStatus('Location requires HTTPS or localhost. Start the app with npm run dev.');
      return;
    }
    if (!navigator.geolocation) {
      setLocationStatus('This browser does not support location. You can still explore and import model JSON.');
      return;
    }
    const requestId = ++locateRequestRef.current;
    setLocating(true);
    setLocationStatus('Waiting for location permission and a device position…');
    navigator.geolocation.getCurrentPosition((position) => {
      if (requestId !== locateRequestRef.current || !mapRef.current) return;
      const { latitude, longitude, accuracy } = position.coords;
      setDevicePosition({ latitude, longitude, accuracy_m: accuracy });
      setLocating(false);
      setLocationStatus('Location found. The blue circle shows reported positioning accuracy.');
      deviceLayerRef.current.clearLayers();
      const accuracyCircle = L.circle([latitude, longitude], { radius: Math.max(accuracy, 5), color: '#286ec7', weight: 1, fillOpacity: 0.09 })
        .addTo(deviceLayerRef.current);
      L.circleMarker([latitude, longitude], { radius: 7, color: '#fff', weight: 3, fillColor: '#286ec7', fillOpacity: 1 })
        .bindPopup('Your device location')
        .addTo(deviceLayerRef.current);
      mapRef.current.fitBounds(accuracyCircle.getBounds(), { padding: [60, 60], maxZoom: 17 });
    }, (error) => {
      if (requestId !== locateRequestRef.current) return;
      setLocating(false);
      setLocationStatus(LOCATION_ERRORS[error.code] || 'Could not get your location.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  }

  function fitToAreas(nextAreas) {
    if (!nextAreas.length) return;
    mapRef.current.fitBounds(L.latLngBounds(nextAreas.map((area) => [area.latitude, area.longitude])), { padding: [55, 55], maxZoom: 16 });
  }

  function showResponse(response, source, metricIds, { fit = true } = {}) {
    setAreas(response.areas);
    setSummary(response.summary);
    setDataSource(source);
    if (metricIds) setSelectedMetricIds(metricIds);
    setImportError('');
    if (fit) fitToAreas(response.areas);
  }

  /**
   * Sync the map with Firestore `predictions`. The map always mirrors the latest
   * read, including empty results. Background polls are skipped while an imported
   * JSON file is shown; the map zooms to the predictions only the first time they appear.
   */
  async function loadPredictions({ background = false } = {}) {
    if (loadingPredictionsRef.current) return;
    if (background && dataSourceRef.current !== DATA_SOURCE.firestore) return;
    loadingPredictionsRef.current = true;
    setLoadingPredictions(true);
    if (!background) setPredictionsStatus('Loading predictions from Firestore…');
    try {
      const { response, counts } = await fetchPredictions(AbortSignal.timeout(PREDICTIONS_REFRESH_MS));
      if (background && dataSourceRef.current !== DATA_SOURCE.firestore) return;
      const firstPredictions = !fittedToPredictionsRef.current && counts.shown > 0;
      const returningFromImport = dataSourceRef.current !== DATA_SOURCE.firestore;
      showResponse(response, DATA_SOURCE.firestore, returningFromImport ? DEFAULT_METRIC_IDS : undefined,
        { fit: firstPredictions || (returningFromImport && counts.shown > 0) });
      if (firstPredictions) fittedToPredictionsRef.current = true;
      const checkedAt = new Date().toLocaleTimeString();
      setPredictionsStatus(counts.shown
        ? `Showing ${counts.shown} live prediction(s). Updated ${checkedAt}; syncs every minute.`
        : counts.documents
          ? `No usable predictions yet (${counts.documents} read, none with estimates). Checked ${checkedAt}; syncs every minute.`
          : `No predictions in Firestore yet. Run demo_runner.py to create some. Checked ${checkedAt}; syncs every minute.`);
    } catch (error) {
      setPredictionsStatus(`${error.message || 'Could not load predictions.'} Showing the last successful sync; retrying every minute.`);
    } finally {
      loadingPredictionsRef.current = false;
      setLoadingPredictions(false);
    }
  }

  useEffect(() => {
    loadPredictions();
    const poller = setInterval(() => loadPredictions({ background: true }), PREDICTIONS_REFRESH_MS);
    return () => clearInterval(poller);
  }, []);

  async function importModelFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      if (file.size > MAX_IMPORT_BYTES) throw new Error('Choose a JSON file smaller than 5 MB.');
      const response = decodeModelResponse(await file.text());
      const hasMetrics = response.areas.some((area) => area.metrics);
      showResponse(response, DATA_SOURCE.imported, hasMetrics ? DEFAULT_METRIC_IDS : [INTENSITY_METRIC_ID]);
      setPredictionsStatus('Showing an imported file; live sync is paused. Click “Back to live predictions” to resume.');
    } catch (error) {
      setImportError(error instanceof SyntaxError ? 'That file is not valid JSON.' : error.message);
    }
  }

  const isLive = dataSource === DATA_SOURCE.firestore;
  const mapTag = isLive ? 'LIVE PREDICTIONS · FIRESTORE' : 'IMPORTED MODEL RESPONSE';
  const mapCaption = areas.length
    ? `${areas.length} ${isLive ? 'predicted locations' : 'imported areas'}`
    : 'No predictions yet — run demo_runner.py to collect measurements; the map updates automatically.';

  return (
    <div className="app">
      <header>
        <a className="brand" href="/" aria-label="Field home"><span className="brandmark">◉</span> field<span className="slash">/</span></a>
        <span className="header-label">WI-FI EXPLORER</span>
        <span className="local-badge">● Local session</span>
      </header>
      <main>
        <aside>
          <div className="eyebrow">CONNECTION, IN CONTEXT</div>
          <h1>Explore your<br />connection.</h1>
          <p className="intro">Explore location-based Wi-Fi insights from your model.</p>
          <LocationPanel status={locationStatus} locating={locating} devicePosition={devicePosition} onLocate={locateDevice} />
          <HeatmapPanel
            areas={areas}
            visible={heatmapVisible}
            onVisibleChange={setHeatmapVisible}
            opacity={heatmapOpacity}
            onOpacityChange={setHeatmapOpacity}
            selectedMetricIds={selectedMetricIds}
            onSelectedMetricIdsChange={setSelectedMetricIds}
          />
          <ModelPanel
            areaCount={areas.length}
            dataSource={dataSource}
            isLive={isLive}
            summary={summary}
            importError={importError}
            predictionsStatus={predictionsStatus}
            loadingPredictions={loadingPredictions}
            onLoadPredictions={() => loadPredictions()}
            onImport={importModelFile}
          />
          <CollectionPanel />
        </aside>
        <div className="map-wrap">
          <div ref={mapElementRef} className="map" aria-label="Interactive Wi-Fi measurement map" />
          <div className="map-tag">{mapTag}</div>
          {tilesFailed && (
            <div className="tile-error" role="alert">
              Some map tiles could not load. Check your connection, then <button onClick={() => window.location.reload()}>reload</button>.
            </div>
          )}
          <div className="map-caption">{mapCaption}</div>
        </div>
      </main>
    </div>
  );
}

function LocationPanel({ status, locating, devicePosition, onLocate }) {
  return (
    <section>
      <div className="section-title"><span>01</span><h2>Your location</h2></div>
      <p>Allow location to center the map on your device. Coordinates stay in this session; the map provider receives requests for the area you view.</p>
      <button className="primary" onClick={onLocate} disabled={locating}>
        {locating ? 'Locating…' : devicePosition ? 'Locate me again ↗' : 'Use my location ↗'}
      </button>
      <p className="status" role="status">{status}</p>
      {devicePosition && (
        <div className="coordinates">
          {devicePosition.latitude.toFixed(5)}, {devicePosition.longitude.toFixed(5)}
          <span>Accuracy ±{Math.round(devicePosition.accuracy_m)} m</span>
        </div>
      )}
    </section>
  );
}

function HeatmapPanel({ areas, visible, onVisibleChange, opacity, onOpacityChange, selectedMetricIds, onSelectedMetricIdsChange }) {
  // The intensity layer only applies to areas without metrics, so hide it otherwise.
  const metrics = METRICS.filter((metric) => metric.id !== INTENSITY_METRIC_ID || areas.some((area) => !area.metrics));
  const toggleMetric = (metricId, checked) => onSelectedMetricIdsChange((current) =>
    checked ? [...current, metricId] : current.filter((id) => id !== metricId));

  return (
    <section>
      <div className="section-title"><span>02</span><h2>Heatmap overlay</h2></div>
      <div className="control-row">
        <label htmlFor="layer">Show heatmap</label>
        <input id="layer" type="checkbox" checked={visible} onChange={(event) => onVisibleChange(event.target.checked)} />
      </div>
      <label className="range-label" htmlFor="opacity">Overlay opacity <span>{opacity}%</span></label>
      <input id="opacity" type="range" min="10" max="100" value={opacity} onChange={(event) => onOpacityChange(Number(event.target.value))} />
      <div className="metric-list">
        {metrics.map((metric) => {
          const available = areasForMetric(areas, metric).length > 0;
          const selected = selectedMetricIds.includes(metric.id);
          const [lowColor, highColor] = metric.colors;
          return (
            <div key={metric.id}>
              <label className="metric-option">
                <span><i style={{ background: rgb(highColor) }} />{metric.label}{!available && <small> · No data</small>}</span>
                <input type="checkbox" checked={selected} disabled={!available} onChange={(event) => toggleMetric(metric.id, event.target.checked)} />
              </label>
              {selected && available && (
                <div className="metric-legend">
                  <div style={{ background: `linear-gradient(90deg,${rgb(lowColor)},${rgb(highColor)})` }} />
                  <span>{metric.lowLabel}</span>
                  <span>{metric.highLabel}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p>Choose one or several layers. Overlapping colors blend; use one layer for the clearest reading. Darker latency means slower response. Unmeasured areas stay transparent.</p>
    </section>
  );
}

function ModelPanel({ areaCount, dataSource, isLive, summary, importError, predictionsStatus, loadingPredictions, onLoadPredictions, onImport }) {
  return (
    <section>
      <div className="section-title"><span>03</span><h2>Model insights</h2></div>
      <div className="data-summary"><strong>{areaCount}</strong><span>{dataSource}</span></div>
      <button className="primary" onClick={onLoadPredictions} disabled={loadingPredictions}>
        {loadingPredictions ? 'Syncing with Firestore…' : isLive ? 'Sync now ↻' : 'Back to live predictions ↻'}
      </button>
      <p className="status" role="status">{predictionsStatus}</p>
      <label className="upload">Import model JSON<input type="file" accept=".json,application/json" onChange={onImport} /></label>
      {summary && <p className="model-summary">{summary}</p>}
      {importError && <p className="error" role="alert">{importError}</p>}
      <p>The map shows the Firestore <code>predictions</code> collection and syncs every minute through the local dev server; credentials never reach the browser. Importing a JSON file pauses the sync until you go back to live predictions.</p>
    </section>
  );
}
