"""Shared feature names and conservative coverage defaults."""
TARGETS = ("download_mbps", "upload_mbps", "rssi_dbm")
NUMERIC = ("latitude", "longitude", "hour_sin", "hour_cos")
CATEGORICAL = ("device_type",)
MAX_DISTANCE_M = 500.0
MIN_NEIGHBORS = 3
SPATIAL_BLOCK_M = 1000.0

# Group measurements per network (BSSID/network_id) and band. Off for now because
# collectors can't always report a BSSID: all measurements share one pool and
# estimates depend on location (plus time and device type) only.
GROUP_BY_NETWORK = False
ALL_NETWORKS = "all"
