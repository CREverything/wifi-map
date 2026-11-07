"""Artificial San Diego-area measurements; NEVER real-world validation."""
import numpy as np


def generate(count=180, seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(count):
        lat, lon = 32.88 + rng.uniform(-.003, .003), -117.23 + rng.uniform(-.003, .003)
        attenuation = ((lat - 32.88) ** 2 + (lon + 117.23) ** 2) ** .5 / .004
        rows.append(dict(latitude=lat, longitude=lon, hour=i % 24,
            network_id="synthetic-demo-network", wifi_band="5GHz", device_type="synthetic-device",
            download_mbps=max(1, 150 - 80 * attenuation + rng.normal(0, 3)),
            upload_mbps=max(1, 50 - 25 * attenuation + rng.normal(0, 1)),
            rssi_dbm=-35 - 40 * attenuation + rng.normal(0, 2),
            latency_ms=10 + 20 * attenuation, packet_loss=0,
            data_source="synthetic", session_id=f"synthetic-session-{i // 30}"))
    return rows
