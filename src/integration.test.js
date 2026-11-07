import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { nextCollectionTime, COLLECTION_PERIOD_MS } from './schedule.js';
import { METRICS, METRIC_KEYS, areasForMetric } from './metrics.js';
import { validateModelResponse } from './model-response.js';
import { isValidCollectRequest } from '../server/collector-plugin.js';

const AREA = {
  latitude: 32.88, longitude: -117.23, radius_m: 150, intensity: 1, explanation: 'Test area',
  metrics: { rssi_dbm: -58, download_mbps: 120, upload_mbps: 35, latency_ms: 28 },
};
const response = (areas) => ({ version: 1, summary: 'Test', areas });

test('schedule aligns to wall clock, including boundaries and resume', () => {
  const period = COLLECTION_PERIOD_MS;
  assert.equal(nextCollectionTime(0), period);
  assert.equal(nextCollectionTime(period - 1), period);
  assert.equal(nextCollectionTime(period), 2 * period);
  assert.equal(nextCollectionTime(17 * period + 123), 18 * period);
});

test('every metric survives response validation', () => {
  const validated = validateModelResponse(response([AREA, { ...AREA, latitude: 32.89 }]));
  for (const metric of METRICS.filter((metric) => METRIC_KEYS.includes(metric.id))) {
    assert.equal(areasForMetric(validated.areas, metric).length, 2);
  }
});

test('missing metrics remain absent rather than invented', () => {
  assert.equal(areasForMetric([{ intensity: 0.5 }], METRICS[1]).length, 0);
});

test('metric keys use the backend snake_case field names', () => {
  assert.deepEqual(METRIC_KEYS, ['rssi_dbm', 'download_mbps', 'upload_mbps', 'latency_ms']);
  const example = JSON.parse(readFileSync(new URL('../public/example-model-response.json', import.meta.url)));
  assert.equal(validateModelResponse(example).areas.length, 3);
});

test('invalid metric values and malformed trigger requests are rejected', () => {
  for (const bad of [{ latency_ms: -1 }, { rssi_dbm: 5 }, { download_mbps: NaN }]) {
    assert.throws(() => validateModelResponse(response([{ ...AREA, metrics: { ...AREA.metrics, ...bad } }])));
  }
  const request = { latitude: 32, longitude: -117, accuracy_m: 10, speedtest: false, firestore: false };
  assert.ok(isValidCollectRequest(request));
  for (const bad of [{ latitude: NaN }, { longitude: 181 }, { accuracy_m: -1 }, { speedtest: 'yes' }]) {
    assert.ok(!isValidCollectRequest({ ...request, ...bad }));
  }
});
