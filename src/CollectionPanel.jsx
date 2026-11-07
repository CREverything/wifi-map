import React, { useEffect, useRef, useState } from 'react';
import { nextCollectionTime } from './schedule.js';

const LOCATION_OPTIONS = { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 };
const REQUEST_TIMEOUT_MS = 250000;

function requestLocation() {
  return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, LOCATION_OPTIONS));
}

function collectionMessage(response, uploadRequested) {
  const warnings = response.record.errors ?? [];
  const saved = `Measurement saved locally${response.firestore_uploaded ? ' and uploaded to Firebase' : ''}.`;
  const detail = warnings.length ? `${warnings.length} metric warning(s): ${warnings.join('; ')}` : 'Collection complete.';
  const uploadFailed = uploadRequested && !response.firestore_uploaded ? ' Firebase upload failed; local backup retained.' : '';
  return `${saved} ${detail}${uploadFailed}`;
}

/** Runs the laptop extractor through the dev server, on demand or every five minutes. */
export default function CollectionPanel() {
  const [now, setNow] = useState(Date.now());
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [nextRunAt, setNextRunAt] = useState(null);
  const [status, setStatus] = useState('Collection is stopped.');
  const [lastMeasuredAt, setLastMeasuredAt] = useState(null);
  const [includeSpeedtest, setIncludeSpeedtest] = useState(false);
  const [uploadToFirestore, setUploadToFirestore] = useState(false);

  const collectingRef = useRef(false);
  const generationRef = useRef(0); // bumped on stop/unmount so stale runs don't update the panel
  const nextRunAtRef = useRef(null);
  const optionsRef = useRef(null);
  optionsRef.current = { speedtest: includeSpeedtest, firestore: uploadToFirestore };

  useEffect(() => {
    const ticker = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(ticker);
      generationRef.current++;
    };
  }, []);

  async function collectNow() {
    if (collectingRef.current) return;
    collectingRef.current = true;
    setCollecting(true);
    const generation = generationRef.current;
    const options = optionsRef.current;
    try {
      if (!window.isSecureContext || !navigator.geolocation) {
        throw new Error('Location requires localhost/HTTPS and browser geolocation.');
      }
      setStatus('Requesting fresh location…');
      const position = await requestLocation();
      if (generation !== generationRef.current) return;

      setStatus('Running the laptop extractor…');
      const httpResponse = await fetch('/api/collect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_m: position.coords.accuracy,
          ...options,
        }),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      const response = await httpResponse.json();
      if (!httpResponse.ok) throw new Error(response.error || 'Collection failed.');
      if (generation !== generationRef.current) return;

      setLastMeasuredAt(response.record.measured_at);
      setStatus(collectionMessage(response, options.firestore));
    } catch (error) {
      if (generation !== generationRef.current) return;
      setStatus(error.code === 1 ? 'Location permission denied. No measurement taken.' : error.message || 'Could not collect a measurement.');
    } finally {
      collectingRef.current = false;
      setCollecting(false);
    }
  }

  useEffect(() => {
    if (!scheduleEnabled || now < nextRunAtRef.current) return;
    nextRunAtRef.current = nextCollectionTime(now);
    setNextRunAt(nextRunAtRef.current);
    // One run after a suspended tab resumes; never replay missed intervals.
    if (!collectingRef.current) collectNow();
  }, [now, scheduleEnabled]);

  function toggleSchedule() {
    if (scheduleEnabled) {
      generationRef.current++;
      setScheduleEnabled(false);
      setNextRunAt(null);
      setStatus('Schedule stopped. A measurement already submitted may finish locally.');
    } else {
      nextRunAtRef.current = nextCollectionTime(Date.now());
      setNextRunAt(nextRunAtRef.current);
      setScheduleEnabled(true);
      setStatus('Scheduled for the next five-minute clock boundary. Keep this app open.');
    }
  }

  return (
    <section className="collection">
      <div className="section-title"><span>04</span><h2>Live collection</h2></div>
      <time className="live-clock" dateTime={new Date(now).toISOString()}>{new Date(now).toLocaleTimeString()}</time>
      <div className="clock-zone">{Intl.DateTimeFormat().resolvedOptions().timeZone}</div>
      <p>Runs this laptop’s extractor at :00, :05, :10… while this app is open. Each run asks for a fresh location and saves locally.</p>

      <label className="control-row">
        Include download/upload test
        <input type="checkbox" checked={includeSpeedtest} onChange={(event) => setIncludeSpeedtest(event.target.checked)} />
      </label>
      <p>Speed tests use substantial bandwidth. Off by default.</p>

      <label className="control-row">
        Upload to Firebase
        <input type="checkbox" checked={uploadToFirestore} onChange={(event) => setUploadToFirestore(event.target.checked)} />
      </label>
      <p>Requires local Firebase credentials. No keys go in the browser.</p>

      <div className="actions">
        <button onClick={toggleSchedule}>{scheduleEnabled ? 'Stop schedule' : 'Start 5-minute schedule'}</button>
        <button onClick={collectNow} disabled={collecting}>{collecting ? 'Collecting…' : 'Collect now'}</button>
      </div>
      {nextRunAt && <p>Next: {new Date(nextRunAt).toLocaleTimeString()} · {Math.max(0, Math.ceil((nextRunAt - now) / 1000))}s</p>}
      <p role="status">{status}</p>
      {lastMeasuredAt && <p>Last collected: {new Date(lastMeasuredAt).toLocaleTimeString()}</p>}
      <p>Measurements feed the model; the map shows the model’s predictions, not raw readings.</p>
    </section>
  );
}
