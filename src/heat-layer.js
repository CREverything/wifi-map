import L from 'leaflet';

const PIXEL_SCALE = 3; // render at 1/3 resolution; the browser upscales the image
const METERS_PER_DEGREE = 111320;
const MAX_ALPHA = 220;

/**
 * Blurred heatmap for one metric. Each area needs latitude, longitude, radius_m,
 * and value (0–1). Overlapping kernels show a weighted average, and edges fade to
 * transparent. Leaflet owns the image's geographic bounds, so the overlay stays
 * attached to the map during pan and animated zoom.
 */
export const HeatLayer = L.Layer.extend({
  initialize(areas, opacityPercent, colors) {
    this.areas = areas;
    this.opacityPercent = opacityPercent;
    this.colors = colors;
  },

  onAdd(map) {
    this.map = map;
    map.on('moveend zoomend resize', this.draw, this);
    this.draw();
  },

  onRemove(map) {
    map.off('moveend zoomend resize', this.draw, this);
    if (this.image) map.removeLayer(this.image);
    this.image = null;
  },

  draw() {
    const map = this.map;
    const size = map.getSize();
    if (!size.x || !size.y) return;

    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(size.x / PIXEL_SCALE);
    canvas.height = Math.ceil(size.y / PIXEL_SCALE);
    const { width, height } = canvas;
    const weights = new Float32Array(width * height);
    const weightedValues = new Float32Array(width * height);

    for (const area of this.areas) {
      const center = map.latLngToContainerPoint([area.latitude, area.longitude]);
      const metersPerDegreeLongitude = METERS_PER_DEGREE * Math.max(0.01, Math.cos(area.latitude * Math.PI / 180));
      const east = map.latLngToContainerPoint([area.latitude, area.longitude + area.radius_m / metersPerDegreeLongitude]);
      const centerX = center.x / PIXEL_SCALE;
      const centerY = center.y / PIXEL_SCALE;
      const radius = Math.max(1, Math.abs(east.x - center.x) / PIXEL_SCALE);
      const xStart = Math.max(0, Math.floor(centerX - radius));
      const xEnd = Math.min(width - 1, Math.ceil(centerX + radius));
      const yStart = Math.max(0, Math.floor(centerY - radius));
      const yEnd = Math.min(height - 1, Math.ceil(centerY + radius));

      for (let y = yStart; y <= yEnd; y++) {
        for (let x = xStart; x <= xEnd; x++) {
          const distanceSquared = ((x - centerX) ** 2 + (y - centerY) ** 2) / (radius * radius);
          if (distanceSquared >= 1) continue;
          const weight = Math.exp(-4 * distanceSquared) * (1 - distanceSquared);
          const pixel = y * width + x;
          weights[pixel] += weight;
          weightedValues[pixel] += weight * area.value;
        }
      }
    }

    const context = canvas.getContext('2d');
    const image = context.createImageData(width, height);
    const [lowColor, highColor] = this.colors;
    for (let pixel = 0; pixel < weights.length; pixel++) {
      if (!weights[pixel]) continue;
      const value = weightedValues[pixel] / weights[pixel];
      const offset = pixel * 4;
      for (let channel = 0; channel < 3; channel++) {
        image.data[offset + channel] = lowColor[channel] + (highColor[channel] - lowColor[channel]) * value;
      }
      image.data[offset + 3] = Math.min(1, weights[pixel]) * this.opacityPercent / 100 * MAX_ALPHA;
    }
    context.putImageData(image, 0, 0);

    const bounds = L.latLngBounds(map.containerPointToLatLng([0, size.y]), map.containerPointToLatLng([size.x, 0]));
    const url = canvas.toDataURL();
    if (this.image) {
      this.image.setUrl(url);
      this.image.setBounds(bounds);
    } else {
      this.image = L.imageOverlay(url, bounds, { interactive: false, className: 'signal-heatmap', zIndex: 1 }).addTo(map);
    }
  },
});
