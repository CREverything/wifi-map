"""Small deterministic measurement set for unit tests; not real-world data."""

NETWORK = "test-network"


def sample_rows(count=60):
    """Rows spread within ~400 m of (32.88, -117.23) on one network and band."""
    rows = []
    for i in range(count):
        dlat = ((i * 7) % 13 - 6) / 2000
        dlon = ((i * 11) % 17 - 8) / 2667
        falloff = (dlat ** 2 + dlon ** 2) ** .5 / .004
        rows.append(dict(latitude=32.88 + dlat, longitude=-117.23 + dlon, hour=i % 24,
            network_id=NETWORK, wifi_band="5GHz", device_type="Darwin",
            download_mbps=150 - 80 * falloff, upload_mbps=50 - 25 * falloff,
            rssi_dbm=-35 - 40 * falloff, latency_ms=10 + 20 * falloff, packet_loss=0,
            data_source="real", session_id=f"session-{i // 30}"))
    return rows
