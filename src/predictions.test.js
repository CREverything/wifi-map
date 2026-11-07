import test from 'node:test';
import assert from 'node:assert/strict';
import { PREDICTION_RADIUS_M, predictionToArea, predictionsToResponse } from './predictions.js';
import { METRICS, areasForMetric } from './metrics.js';

// Shaped like model/firestore_io.py prediction_document(), after model/map_feed.py.
function prediction(overrides = {}) {
  return {
    prediction_id: 'p1', predicted_at: '2026-11-07T22:00:00+00:00',
    latitude: 32.884, longitude: -117.233, bssid: null, network_id: 'all', band_ghz: '5',
    download_mbps: 51.5, upload_mbps: 26.8, rssi_dbm: -56,
    status: 'available', reliability: 'low', method: 'baseline', synthetic_data_used: false,
    targets: {
      download_mbps: { nearby_count: 4, nearest_distance_m: 3, reliability: 'low', reason: 'uncalibrated_estimate' },
      upload_mbps: { nearby_count: 4, nearest_distance_m: 3, reliability: 'low', reason: 'uncalibrated_estimate' },
      rssi_dbm: { nearby_count: 5, nearest_distance_m: 3, reliability: 'low', reason: 'uncalibrated_estimate' },
    },
    ...overrides,
  };
}

test('prediction fields map to area metrics without renaming or inventing values', () => {
  const area = predictionToArea(prediction());
  assert.deepEqual(area.metrics, { download_mbps: 51.5, upload_mbps: 26.8, rssi_dbm: -56 });
  assert.equal(area.latitude, 32.884);
  assert.equal(area.radius_m, PREDICTION_RADIUS_M);
  assert.equal(area.intensity, 1);
  assert.match(area.explanation, /baseline, low reliability/);
  assert.match(area.explanation, /rssi_dbm from 5 nearby/);
  assert.ok(!('latency_ms' in area.metrics)); // predictions have no latency estimate
});

test('partial predictions keep only the available targets', () => {
  const area = predictionToArea(prediction({ status: 'partial', rssi_dbm: null }));
  assert.deepEqual(Object.keys(area.metrics).sort(), ['download_mbps', 'upload_mbps']);
  assert.equal(area.intensity, 2 / 3);
  assert.match(area.explanation, /^Partial estimate/);
});

test('unavailable predictions are hidden and counted', () => {
  const unavailable = prediction({ prediction_id: 'p2', latitude: 32.9, status: 'unavailable', download_mbps: null, upload_mbps: null, rssi_dbm: null });
  const { response, counts } = predictionsToResponse([prediction(), unavailable]);
  assert.equal(response.areas.length, 1);
  assert.equal(counts.unavailable, 1);
  assert.match(response.summary, /1 unavailable/);
});

test('newest prediction per location wins', () => {
  const older = prediction({ prediction_id: 'old', predicted_at: '2026-11-07T21:00:00+00:00', download_mbps: 10 });
  const newer = prediction({ prediction_id: 'new', predicted_at: '2026-11-07T22:00:00+00:00', download_mbps: 90 });
  const { response, counts } = predictionsToResponse([older, newer]);
  assert.equal(response.areas.length, 1);
  assert.equal(response.areas[0].metrics.download_mbps, 90);
  assert.equal(counts.superseded, 1);
});

test('documents without valid coordinates are skipped', () => {
  const { response, counts } = predictionsToResponse([prediction({ latitude: null }), prediction()]);
  assert.equal(response.areas.length, 1);
  assert.equal(counts.invalid, 1);
});

test('RSSI is drawn on a -90..-30 dBm scale', () => {
  const rssi = METRICS.find((metric) => metric.id === 'rssi_dbm');
  const values = [-90, -60, -30, -100].map((rssi_dbm) =>
    areasForMetric([{ ...predictionToArea(prediction({ rssi_dbm })) }], rssi)[0].value);
  assert.deepEqual(values, [0, 0.5, 1, 0]);
});

test('synthetic training is flagged in the explanation', () => {
  assert.match(predictionToArea(prediction({ synthetic_data_used: true })).explanation, /SYNTHETIC/);
});
