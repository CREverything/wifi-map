import React from 'react';
import { createRoot } from 'react-dom/client';
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
import 'leaflet/dist/leaflet.css';
import './style.css';
import App from './App.jsx';

setWorkerUrl(workerUrl);
createRoot(document.getElementById('root')).render(<App />);
