import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import L from 'leaflet';
import { maplibreGL } from '@maplibre/maplibre-gl-leaflet';
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
setWorkerUrl(workerUrl);
import 'leaflet/dist/leaflet.css';
import './style.css';
import { createSimulation } from './simulation.js';
import { HeatLayer } from './heat-layer.js';
import CollectionClock from './CollectionClock.jsx';
import { METRICS, metricRows } from './metrics.js';
const demo = createSimulation();
import { decodeModelResponse } from './model-adapter.js';

function App() {
  const host = useRef(null), map = useRef(null), samples = useRef(null), location = useRef(null), request = useRef(0);
  const [status, setStatus] = useState('Location is off. Explore the map or locate your device.');
  const [busy, setBusy] = useState(false), [position, setPosition] = useState(null);
  const [rows, setRows] = useState(demo.areas), [source, setSource] = useState('Demo data');
  const [summary, setSummary] = useState(demo.summary);
  const [selected, setSelected] = useState(['connection']);
  const [visible, setVisible] = useState(true), [opacity, setOpacity] = useState(70);
  const [tileError, setTileError] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    const m = L.map(host.current, { zoomControl:false, minZoom:2, maxZoom:19 }).setView([32.7157,-117.1611],13);
    map.current = m;
    L.control.zoom({ position:'bottomright' }).addTo(m);
    L.control.scale({ position:'bottomleft' }).addTo(m);
    try {
      const basemap = maplibreGL({style:'/basemap-style.json', attribution:'© Esri, HERE, Garmin, OpenStreetMap contributors, GIS User Community'}).addTo(m);
      basemap.getMaplibreMap().on('error', () => setTileError(true));
    } catch {
      setTileError(true);
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {maxZoom:19, attribution:'Tiles © Esri and contributors'}).addTo(m);
    }
    samples.current = L.layerGroup().addTo(m);
    location.current = L.layerGroup().addTo(m);
    return () => { request.current++; m.remove(); map.current=null; };
  }, []);
  useEffect(() => {
    samples.current.clearLayers();
    if (!visible) return;
    for (const metric of METRICS) {
      if(selected.includes(metric.id)) new HeatLayer(metricRows(rows,metric),opacity,metric.colors).addTo(samples.current);
    }
    rows.forEach(row => {
      if (row.intensity <= 0) return;
      const text = document.createElement('div');
      text.textContent = `${row.explanation} · ${Object.entries(row.metrics || {}).map(([key,value])=>key+': '+Math.round(value*100)/100).join(' · ')} · Radius ${row.radiusMeters} m`;
      L.circle([row.latitude,row.longitude], { radius:row.radiusMeters, stroke:false, fillOpacity:0 }).bindPopup(text).addTo(samples.current);
    });
  }, [rows, visible, opacity, source, selected]);
  function locate() {
    if (!window.isSecureContext) { setStatus('Location requires HTTPS or localhost. Start the app with npm run dev.'); return; }
    if (!navigator.geolocation) { setStatus('This browser does not support location. You can still explore and import model JSON.'); return; }
    const id = ++request.current;
    setBusy(true); setStatus('Waiting for location permission and a device position…');
    navigator.geolocation.getCurrentPosition(p => {
      if (id !== request.current || !map.current) return;
      const { latitude, longitude, accuracy } = p.coords;
      setPosition({ latitude, longitude, accuracy }); setBusy(false);
      setStatus('Location found. The blue circle shows reported positioning accuracy.');
      location.current.clearLayers();
      const circle = L.circle([latitude,longitude], {radius:Math.max(accuracy,5),color:'#286ec7',weight:1,fillOpacity:0.09}).addTo(location.current);
      L.circleMarker([latitude,longitude], {radius:7,color:'#fff',weight:3,fillColor:'#286ec7',fillOpacity:1}).bindPopup('Your device location').addTo(location.current);
      map.current.fitBounds(circle.getBounds(), {padding:[60,60],maxZoom:17});
    }, e => {
      if (id !== request.current) return;
      setBusy(false);
      setStatus(({1:'Location access was denied. Allow location in your browser’s site settings, then try again.',2:'Your device could not determine its location. Check OS location services and try again.',3:'Location lookup timed out. Try again or continue exploring manually.'})[e.code] || 'Could not get your location.');
    }, {enableHighAccuracy:true,timeout:15000,maximumAge:0});
  }
  function fit(data) {
    if (data.length) map.current.fitBounds(L.latLngBounds(data.map(r => [r.latitude,r.longitude])), {padding:[55,55],maxZoom:16});
  }
  async function importFile(e) {
    const file=e.target.files?.[0]; e.target.value=''; if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('Choose a JSON file smaller than 5 MB.');
      const next = decodeModelResponse(await file.text());
      setRows(next.areas); setSelected(next.areas.some(r=>r.metrics)?['connection']:['modelIntensity']); setSummary(next.summary); setSource('Model response'); setError(''); fit(next.areas);
    } catch (err) { setError(err instanceof SyntaxError ? 'That file is not valid JSON.' : err.message); }
  }
  return <div className="app">
    <header><a className="brand" href="/" aria-label="Field home"><span className="brandmark">◉</span> field<span className="slash">/</span></a><span className="header-label">WI-FI EXPLORER</span><span className="local-badge">● Local session</span></header>
    <main><aside>
      <div className="eyebrow">CONNECTION, IN CONTEXT</div><h1>Explore your<br/>connection.</h1><p className="intro">Explore location-based Wi-Fi insights from your model.</p>
      <section><div className="section-title"><span>01</span><h2>Your location</h2></div><p>Allow location to center the map on your device. Coordinates stay in this session; the map provider receives requests for the area you view.</p><button className="primary" onClick={locate} disabled={busy}>{busy ? 'Locating…' : position ? 'Locate me again ↗' : 'Use my location ↗'}</button><p className="status" role="status">{status}</p>{position && <div className="coordinates">{position.latitude.toFixed(5)}, {position.longitude.toFixed(5)}<span>Accuracy ±{Math.round(position.accuracy)} m</span></div>}</section>
      <section><div className="section-title"><span>02</span><h2>Heatmap overlay</h2></div><div className="control-row"><label htmlFor="layer">Show heatmap</label><input id="layer" type="checkbox" checked={visible} onChange={e=>setVisible(e.target.checked)}/></div><label className="range-label" htmlFor="opacity">Overlay opacity <span>{opacity}%</span></label><input id="opacity" type="range" min="10" max="100" value={opacity} onChange={e=>setOpacity(Number(e.target.value))}/><div className="metric-list">{METRICS.filter(metric=>metric.id!=='modelIntensity'||rows.some(row=>!row.metrics)).map(metric=>{const available=metricRows(rows,metric).length>0;return <div key={metric.id}><label className="metric-option"><span><i style={{background:'rgb('+metric.colors[1].join(',')+')'}}/>{metric.label}{!available&&<small> · No data</small>}</span><input type="checkbox" checked={selected.includes(metric.id)} disabled={!available} onChange={e=>setSelected(current=>e.target.checked?[...current,metric.id]:current.filter(id=>id!==metric.id))}/></label>{selected.includes(metric.id)&&available&&<div className="metric-legend"><div style={{background:'linear-gradient(90deg,rgb('+metric.colors[0].join(',')+'),rgb('+metric.colors[1].join(',')+'))'}}/><span>{metric.low}</span><span>{metric.high}</span></div>}</div>;})}</div><p>Choose one or several layers. Overlapping colors blend; use one layer for the clearest reading. Darker latency means slower response. Unmeasured areas stay transparent.</p></section>
      <section><div className="section-title"><span>03</span><h2>Model insights</h2></div><div className="data-summary"><strong>{rows.length}</strong><span>{source}</span></div><label className="upload">Import model JSON<input type="file" accept=".json,application/json" onChange={importFile}/></label><div className="actions"><button onClick={()=>{setSelected(['connection']);setRows(demo.areas);setSummary(demo.summary);setSource('Demo data');setError('');fit(demo.areas);}}>Simulate heatmap</button><button disabled={!rows.length} onClick={()=>{setRows([]);setSummary('');setSource('No model response');setError('');}}>Clear</button></div>{summary && <p className="model-summary">{summary}</p>}{error && <p className="error" role="alert">{error}</p>}<p>Import a structured model response to preview it on the map. Live model connection is not configured.</p></section>
    <CollectionClock/></aside><div className="map-wrap"><div ref={host} className="map" aria-label="Interactive Wi-Fi measurement map"/><div className="map-tag">{source==='Demo data'?'SIMULATION · MADE-UP DATA':rows.length?'MODEL RESPONSE':'EXPLORE THE MAP'}</div>{tileError && <div className="tile-error" role="alert">Some map tiles could not load. Check your connection, then <button onClick={()=>window.location.reload()}>reload</button>.</div>}<div className="map-caption">{rows.length ? `${rows.length} model areas` : 'No model response yet — import JSON or try the demo.'}</div></div></main>
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
