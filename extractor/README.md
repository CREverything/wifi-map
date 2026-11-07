# Wi-Fi map: laptop data collector

Python 3.10+ on **macOS or Windows**. Measures the *currently connected* Wi-Fi interface, internet download/upload speed, ICMP ping latency and packet loss, and user-approved location. Saves JSON Lines and CSV locally; Firestore upload is opt-in.

## 1. Install

From the `wifi-map` repository root (one environment for the collector and the model):

**macOS** (Terminal):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Windows** (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use `.venv\Scripts\python.exe` instead of `python` in the commands below if the Windows virtual environment isn't activated. Commands below assume you are in `extractor/`; from the root, use `python extractor/collect.py ...`.

## 2. Collect a measurement

Provide GPS coordinates for the exact place you're standing. These are EXAMPLE coordinates; **replace them** before collecting actual UCSD data:

```bash
python collect.py --lat 32.8801 --lon -117.2340 --location-label "sample site"
```

Alternatively, let your browser ask permission for approximate location:

```bash
python collect.py --browser-location --location-label "sample site"
```

Browser location is generally an approximation derived from nearby networks or IP and may be wrong indoors. If no location can be obtained, use `--lat` and `--lon`. Browsers typically treat `http://127.0.0.1` as a secure context for geolocation.

For **fast, frequent signal/ping samples** (no bandwidth-heavy speed test):

```bash
python collect.py --lat 32.8801 --lon -117.2340 --skip-speedtest --count 5 --interval 10
```

Files are appended to `extractor/data/measurements.jsonl` and `extractor/data/measurements.csv` (both gitignored). Missing metrics are `null`/empty, never invented. Each record includes a random persistent device ID and basic OS metadata; no hostname, serial, device MAC address, or public IP is saved by default.

### Field definitions

| Field | Units / description |
| --- | --- |
| `measurement_id` | Random unique ID, used for idempotent Firestore writes |
| `download_mbps`, `upload_mbps` | Internet throughput (Mbit/s) from speedtest-cli |
| `rssi_dbm` | Received Signal Strength Indicator, dBm; **not the same** as Windows signal % |
| `signal_percent` | OS-reported Windows signal quality percent, where available |
| `latency_ms` | Average ICMP round-trip time to `ping_target` (default: 1.1.1.1) |
| `packet_loss_pct` | ICMP packet loss rate, percent |
| `speedtest_ping_ms` | Speedtest server's latency (different endpoint/method from ICMP ping) |
| `ssid`, `bssid` | Wi-Fi network name and connected access point ID, subject to OS privacy restrictions |
| `channel`, `band_ghz` | Connected wireless channel and 2.4/5/6 GHz band, when reported |
| `latitude`, `longitude` | User-supplied or browser-approved location in WGS84 decimal degrees |
| `location_accuracy_m`, `location_method` | Browser accuracy estimate and location source |
| `measured_at` | UTC ISO 8601 timestamp of measurement start; Firestore Timestamp on upload |
| `device` | Random persistent `device_id`, OS name/version, architecture, Python version |
| `errors` | Warnings for unavailable fields, missing dependencies, denied permissions, or network errors |

### Important platform differences

- **Windows:** `netsh wlan show interfaces` provides connected Wi-Fi metadata. Some Windows 11 versions require Location Services enabled for Wi-Fi network details. RSSI in dBm is only recorded if returned directly; the collector **does not invent an RSSI value from signal %**. `netsh` output localization may require parser customization.
- **macOS:** `pymacos` reads signal RSSI, channel, band using CoreWLAN. Current Wi-Fi **SSID/BSSID may be withheld** because of Location Services privacy rules. If you need the connected AP ID on modern macOS and want to grant permission, you can optionally install a third-party signed helper (e.g. `macwifi-cli`); the collector detects it automatically. `airport` is a fallback only on older macOS releases. Without access, SSID/BSSID are `null`.
- **Location:** Laptops do not generally provide precise GPS automatically. Your coordinates must describe the actual physical sampling location. Browser-provided coordinates can be inaccurate indoors.
- **Packet loss:** Some campus networks block ICMP echo; in that case ping metrics may be unavailable or show all packets lost, which does not necessarily imply Internet service is unusable.
- **Network speed:** `speedtest-cli` relies on external Speedtest servers. It can fail when their APIs change or the network blocks tests. Throughput depends on server choice and other traffic, not just Wi-Fi strength. Bandwidth tests can transfer hundreds of megabytes; do not run frequently.
- **Multiple adapters:** The collector reads the connected Wi-Fi interface, not all nearby APs or Ethernet. If a VPN or Ethernet connection is active, internet throughput may not reflect the measured Wi-Fi link.

## 3. Optional Firestore upload

1. Use the already-created **production-mode** Firestore database.
2. In Firebase Console > Project settings > Service accounts, generate a service account key for a trusted machine; grant only necessary IAM privileges. **Never commit this key**.
3. Set the environment variable to its location:

macOS:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/secure/firebase-service-account.json"
```

Windows PowerShell:
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\secure\firebase-service-account.json"
```

4. Run with `--firestore`:

```bash
python collect.py --lat 32.8801 --lon -117.2340 --firestore
```

Firestore automatically creates `measurements` upon the first successful write. No Firebase Console collection setup or fixed database schema is needed. Cloud Firestore production security rules can remain closed when using a properly authenticated Admin SDK client.

## Team integration

The ML team can load `data/measurements.csv` with pandas. The frontend should read model output from a *separate* `predictions` Firestore collection. Keep `rssi_dbm` and `signal_percent` distinct: don't mix the scales in training.

## Tests

```bash
python -m unittest discover -s tests -v
```
