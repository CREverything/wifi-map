import { RESPONSE_VERSION, validateModelResponse } from './model-response.js';

// Converts Firestore `predictions` documents (written by model/firestore_io.py
// prediction_document) into the map data format.

/** Model outputs carried into the heatmap. Predictions have no latency estimate. */
export const PREDICTION_TARGETS = ['download_mbps', 'upload_mbps', 'rssi_dbm'];

/**
 * Display radius around each prediction point. A prediction is an estimate *at*
 * its coordinates (built from measurements within the model's 500 m radius), so
 * this only sets how far its colour spreads on the map.
 */
export const PREDICTION_RADIUS_M = 150;

const timestamp = (prediction) => Date.parse(prediction.predicted_at) || 0;

/** Same place (to ~1 m), network, and band: a newer prediction supersedes an older one. */
const locationKey = (prediction) =>
  [prediction.latitude.toFixed(5), prediction.longitude.toFixed(5), prediction.network_id ?? '', prediction.band_ghz ?? ''].join('|');

function explanation(prediction, metrics) {
  const estimate = prediction.status === 'available' ? 'Estimate' : 'Partial estimate';
  const nearby = PREDICTION_TARGETS
    .filter((target) => target in metrics)
    .map((target) => `${target} from ${prediction.targets?.[target]?.nearby_count ?? '?'} nearby`)
    .join(', ');
  const parts = [
    `${estimate} (${prediction.method ?? 'unknown method'}, ${prediction.reliability ?? 'unknown'} reliability)`,
    nearby && `measurements: ${nearby}`,
    prediction.band_ghz && `${prediction.band_ghz} GHz`,
    prediction.predicted_at && `predicted ${new Date(prediction.predicted_at).toLocaleString()}`,
    prediction.synthetic_data_used && 'trained partly on SYNTHETIC data',
  ];
  return parts.filter(Boolean).join(' · ');
}

/** One map area, or null when the prediction has no usable estimate. */
export function predictionToArea(prediction) {
  const metrics = {};
  for (const target of PREDICTION_TARGETS) {
    if (Number.isFinite(prediction[target])) metrics[target] = prediction[target];
  }
  const estimateCount = Object.keys(metrics).length;
  if (!estimateCount) return null;
  return {
    latitude: prediction.latitude,
    longitude: prediction.longitude,
    radius_m: PREDICTION_RADIUS_M,
    intensity: estimateCount / PREDICTION_TARGETS.length, // share of targets the model could estimate
    explanation: explanation(prediction, metrics),
    metrics,
  };
}

/**
 * Map response from prediction documents: newest prediction per location, without
 * unavailable estimates. Returns the validated response plus counts for the UI.
 */
export function predictionsToResponse(predictions) {
  const latest = new Map();
  let invalid = 0;
  for (const prediction of predictions) {
    if (!Number.isFinite(prediction?.latitude) || !Number.isFinite(prediction?.longitude)) {
      invalid++;
      continue;
    }
    const key = locationKey(prediction);
    const current = latest.get(key);
    if (!current || timestamp(prediction) > timestamp(current)) latest.set(key, prediction);
  }
  const newest = [...latest.values()];
  const areas = newest.map(predictionToArea).filter(Boolean);
  const counts = {
    documents: predictions.length,
    shown: areas.length,
    unavailable: newest.length - areas.length,
    superseded: predictions.length - invalid - newest.length,
    invalid,
  };
  const hidden = [
    counts.unavailable && `${counts.unavailable} unavailable (fewer than 3 measurements within 500 m)`,
    counts.superseded && `${counts.superseded} older at the same spot`,
    counts.invalid && `${counts.invalid} without valid coordinates`,
  ].filter(Boolean);
  const summary = `Live model estimates from Firestore: ${counts.shown} location(s) shown` +
    (hidden.length ? `; hidden: ${hidden.join(', ')}` : '') +
    '. Every estimate has low reliability: it averages nearby measurements and is not a guarantee.';
  return { response: validateModelResponse({ version: RESPONSE_VERSION, summary, areas }), counts };
}

/** Fetch predictions through the dev-server endpoint (server/predictions-plugin.js). */
export async function fetchPredictions(signal) {
  const httpResponse = await fetch('/api/predictions', { signal });
  const body = await httpResponse.json().catch(() => ({}));
  if (!httpResponse.ok) throw new Error(body.error || 'Could not load predictions.');
  return predictionsToResponse(body.predictions ?? []);
}
