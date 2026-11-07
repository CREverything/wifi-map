// Heatmap layers. Each id is the field name inside an area's `metrics`, using the
// same snake_case names as the Firestore measurement/prediction fields. The
// `intensity` layer instead shows the model's own score for areas without metrics.
// Values are drawn on a min–max scale; anything outside it is clamped to the ends.
export const INTENSITY_METRIC_ID = 'intensity';

export const METRICS = [
  { id: 'rssi_dbm', label: 'Signal strength (RSSI)', lowLabel: '−90 dBm', highLabel: '−30 dBm', colors: [[239, 220, 250], [107, 35, 146]], min: -90, max: -30 },
  { id: 'download_mbps', label: 'Download speed', lowLabel: '0 Mbps', highLabel: '200+ Mbps', colors: [[215, 242, 249], [20, 91, 146]], min: 0, max: 200 },
  { id: 'upload_mbps', label: 'Upload speed', lowLabel: '0 Mbps', highLabel: '100+ Mbps', colors: [[255, 229, 237], [226, 58, 111]], min: 0, max: 100 },
  { id: 'latency_ms', label: 'Latency', lowLabel: '0 ms', highLabel: '200+ ms', colors: [[231, 235, 237], [46, 52, 58]], min: 0, max: 200 },
  { id: INTENSITY_METRIC_ID, label: 'Model intensity', lowLabel: 'Low', highLabel: 'High', colors: [[255, 225, 220], [185, 30, 52]], min: 0, max: 1 },
];

export const METRIC_KEYS = METRICS.map((metric) => metric.id).filter((id) => id !== INTENSITY_METRIC_ID);
export const DEFAULT_METRIC_ID = 'rssi_dbm';

/** Position of `value` on the metric's scale, clamped to 0–1. */
export function scaleValue(metric, value) {
  return Math.min(1, Math.max(0, (value - metric.min) / (metric.max - metric.min)));
}

/**
 * Areas that have a value for `metric`, each with `value` scaled to 0–1 for drawing.
 * Areas missing the metric are left out, never filled in.
 */
export function areasForMetric(areas, metric) {
  if (metric.id === INTENSITY_METRIC_ID) {
    return areas.filter((area) => !area.metrics).map((area) => ({ ...area, value: area.intensity }));
  }
  return areas
    .filter((area) => Number.isFinite(area.metrics?.[metric.id]))
    .map((area) => ({ ...area, value: scaleValue(metric, area.metrics[metric.id]) }));
}

export const rgb = (color) => `rgb(${color.join(',')})`;
