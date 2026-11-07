import { METRIC_KEYS } from './metrics.js';

// Map data contract. Field names match the backend's snake_case naming.
export const RESPONSE_VERSION = 1;
export const MAX_AREAS = 10000;
export const MAX_SUMMARY_CHARS = 4000;
export const MAX_EXPLANATION_CHARS = 2000;
export const MAX_RADIUS_M = 100000;

function validateArea(area, index) {
  const label = `Area ${index + 1}`;
  if (!area || typeof area !== 'object') throw new Error(`${label} must be an object.`);
  const { latitude, longitude, radius_m, intensity, explanation } = area;
  if (
    ![latitude, longitude, radius_m, intensity].every(Number.isFinite) ||
    Math.abs(latitude) > 90 || Math.abs(longitude) > 180 ||
    radius_m <= 0 || radius_m > MAX_RADIUS_M ||
    intensity < 0 || intensity > 1
  ) {
    throw new Error(`${label}: invalid coordinates, radius_m (0–100,000 m), or intensity (0–1).`);
  }
  if (typeof explanation !== 'string' || explanation.length > MAX_EXPLANATION_CHARS) {
    throw new Error(`${label}: explanation must be text of at most 2,000 characters.`);
  }
  const validated = { latitude, longitude, radius_m, intensity, explanation };
  if (area.metrics === undefined) return validated;

  if (!area.metrics || typeof area.metrics !== 'object' || Array.isArray(area.metrics)) {
    throw new Error('metrics must be an object.');
  }
  const metrics = {};
  for (const key of METRIC_KEYS) {
    const value = area.metrics[key];
    if (value == null) continue;
    // RSSI uses the backend's accepted range; every other metric is nonnegative.
    const valid = key === 'rssi_dbm' ? value >= -150 && value <= 0 : value >= 0;
    if (!Number.isFinite(value) || !valid) {
      throw new Error(`Invalid ${key} metric.`);
    }
    metrics[key] = value;
  }
  return { ...validated, metrics };
}

/** Validate a parsed model response; throws an Error with a user-facing message. */
export function validateModelResponse(response) {
  if (!response || response.version !== RESPONSE_VERSION || !Array.isArray(response.areas) || response.areas.length > MAX_AREAS) {
    throw new Error('Expected version: 1 and an areas array (maximum 10,000 areas).');
  }
  if (typeof response.summary !== 'string' || response.summary.length > MAX_SUMMARY_CHARS) {
    throw new Error('summary must be text of at most 4,000 characters.');
  }
  return { version: RESPONSE_VERSION, summary: response.summary, areas: response.areas.map(validateArea) };
}

/** Accepts a JSON string or an already-parsed object. */
export function decodeModelResponse(payload) {
  return validateModelResponse(typeof payload === 'string' ? JSON.parse(payload) : payload);
}

export const EXAMPLE_RESPONSE = {
  version: RESPONSE_VERSION,
  summary: 'Illustrative model response only. These areas are synthetic, not live Wi-Fi findings. Red intensity is supplied by the model; its meaning will be defined with your backend.',
  areas: [
    { latitude: 32.7157, longitude: -117.1611, radius_m: 150, intensity: 0.9, explanation: 'Example area with high overlay intensity.' },
    { latitude: 32.7181, longitude: -117.1642, radius_m: 100, intensity: 0.5, explanation: 'Example area with medium overlay intensity.' },
    { latitude: 32.7129, longitude: -117.1576, radius_m: 120, intensity: 0.2, explanation: 'Example area with low overlay intensity.' },
  ],
};
