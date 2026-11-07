"""Cross-platform laptop Wi-Fi survey collector (macOS + Windows).

Collects measurements from the *currently connected* Wi-Fi interface. Values
blocked by OS permissions are saved as null; they are not estimated.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
ENV_FILE = REPO_ROOT / ".env"
DATA_DIR = ROOT / "data"
COLLECTOR_VERSION = "1.0.0"
FIRESTORE_COLLECTION = "measurements"

_firestore_client: Any = None


def load_environment(env_file: Path = ENV_FILE) -> None:
    """Load the repo-root .env and make GOOGLE_APPLICATION_CREDENTIALS absolute.

    A relative credentials path is resolved against the .env file's directory,
    so the collector works no matter which directory it is launched from.
    Variables already set in the shell take precedence over .env values.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        if env_file.exists():
            print("WARNING: python-dotenv not installed; .env was not loaded. "
                  "Run: pip install -r requirements.txt", file=sys.stderr)
    else:
        load_dotenv(env_file, override=False)

    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds:
        path = Path(creds).expanduser()
        if not path.is_absolute():
            path = (env_file.parent / path).resolve()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)


def command_output(args: list[str], timeout: int = 12) -> str:
    """Run a read-only system tool, tolerating OS-specific output encodings."""
    completed = subprocess.run(
        args, capture_output=True, text=True, errors="replace", timeout=timeout,
        check=False,
    )
    output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    if completed.returncode and not completed.stdout:
        raise RuntimeError(output.strip() or f"Command failed: {args[0]}")
    return output


def normalize_band(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"(2[.,]4|5|6)\s*(?:g(?:hz)?)?", str(value), re.I)
    return match.group(1).replace(",", ".") if match else None


def empty_wifi() -> dict[str, Any]:
    return {
        "ssid": None, "bssid": None, "rssi_dbm": None,
        "signal_percent": None, "channel": None, "band_ghz": None,
        "wifi_source": None,
    }


def parse_windows_wifi(output: str) -> dict[str, Any]:
    """Parse `netsh wlan show interfaces` for the *connected* network."""
    data = empty_wifi()
    # Some computers have multiple WLAN adapters. Select the first connected
    # interface instead of accidentally reading a disconnected one.
    blocks = re.split(r"(?=^\s*(?:Name|Nombre|Nom)\s*:\s*.+$)", output, flags=re.M | re.I)
    selected = next((block for block in blocks if re.search(
        r"^\s*(?:State|Estado|Etat|État)\s*:\s*(?:connected|conectado|connecté)",
        block, flags=re.M | re.I)), None)
    if selected is None:
        selected = output
    fields: dict[str, str] = {}
    for line in selected.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        fields[key] = value.strip()

    data["ssid"] = fields.get("ssid") or None
    # Newer Windows 11 builds label this field "AP BSSID".
    data["bssid"] = fields.get("bssid") or fields.get("ap bssid") or None
    rssi = fields.get("rssi")
    if rssi:
        m = re.search(r"-?\d+", rssi)
        if m:
            data["rssi_dbm"] = int(m.group(0))
    signal = fields.get("signal") or fields.get("señal")
    if signal:
        m = re.search(r"\d+", signal)
        if m:
            data["signal_percent"] = min(100, max(0, int(m.group(0))))
    channel = fields.get("channel") or fields.get("canal")
    if channel:
        m = re.search(r"\d+", channel)
        if m:
            data["channel"] = int(m.group(0))
    band = fields.get("band") or fields.get("banda") or fields.get("bande")
    data["band_ghz"] = normalize_band(band)
    data["wifi_source"] = "netsh"
    return data


def windows_wifi() -> dict[str, Any]:
    return parse_windows_wifi(command_output(["netsh", "wlan", "show", "interfaces"]))


def parse_airport_info(text: str) -> dict[str, Any]:
    data = empty_wifi()
    props: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([^:]+):\s*(.*)$", line)
        if m:
            props[m.group(1).strip().lower()] = m.group(2).strip()
    data["ssid"] = props.get("ssid")
    data["bssid"] = props.get("bssid")
    for prop, field in (("agrctlrssi", "rssi_dbm"), ("channel", "channel")):
        val = props.get(prop, "")
        m = re.search(r"-?\d+", val)
        if m:
            data[field] = int(m.group(0))
    data["band_ghz"] = normalize_band(props.get("channel", "")) if "ghz" in props.get("channel", "").lower() else None
    data["wifi_source"] = "airport"
    return data


def parse_macwifi_cli(text: str) -> dict[str, Any]:
    obj = json.loads(text)
    data = empty_wifi()
    if not isinstance(obj, dict) or obj.get("connected") is False:
        return data
    data["ssid"] = obj.get("ssid")
    data["bssid"] = obj.get("bssid")
    rssi = obj.get("rssi")
    if isinstance(rssi, (int, float)) and rssi < 0:
        data["rssi_dbm"] = int(rssi)
    channel = obj.get("channel")
    if isinstance(channel, (int, float)) and channel > 0:
        data["channel"] = int(channel)
    data["band_ghz"] = normalize_band(obj.get("band"))
    data["wifi_source"] = "macwifi-cli"
    return data


def mac_wifi() -> dict[str, Any]:
    data = empty_wifi()
    sources = []
    # Preferred: available on recent macOS without admin permissions.
    try:
        import macos  # Provided by pymacos on macOS
        signal = macos.network.wifi_signal()
        if signal is not None:
            data.update({
                "rssi_dbm": signal.rssi,
                "channel": signal.channel,
                "band_ghz": normalize_band(signal.band),
            })
            sources.append("pymacos/CoreWLAN")
    except (ImportError, Exception):
        # Optional diagnostic library, or Wi-Fi denied/off; keep going.
        pass

    # Optional: a user-installed, Location-Services-authorized app can get
    # SSID/BSSID, which macOS intentionally hides from ordinary scripts.
    if shutil.which("macwifi-cli"):
        try:
            details = parse_macwifi_cli(command_output(
                ["macwifi-cli", "info", "--json"], timeout=20))
            for key in ("ssid", "bssid", "rssi_dbm", "channel", "band_ghz"):
                if details.get(key) is not None and data[key] is None:
                    data[key] = details[key]
            sources.append("macwifi-cli")
        except (ValueError, RuntimeError, subprocess.TimeoutExpired):
            pass

    # Best effort for SSID from the OS; macOS may redact it.
    try:
        ports = command_output(["networksetup", "-listallhardwareports"])
        match = re.search(r"Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\S+)", ports, re.I)
        if match:
            interface = match.group(1)
            network = command_output(["networksetup", "-getairportnetwork", interface])
            if "Current Wi-Fi Network:" in network:
                ssid = network.split("Current Wi-Fi Network:", 1)[1].strip()
                if ssid and ssid.lower() not in ("<redacted>", "<unknown>"):
                    data["ssid"] = data["ssid"] or ssid
            summary = command_output(["ipconfig", "getsummary", interface])
            bssid = re.search(r"(?im)^\s*BSSID\s*:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s*$", summary)
            if bssid:
                data["bssid"] = data["bssid"] or bssid.group(1).lower()
            sources.append("networksetup")
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Legacy Macs only: airport was removed in macOS 14.4.
    if data["rssi_dbm"] is None:
        legacy = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
        if Path(legacy).exists():
            try:
                old = parse_airport_info(command_output([legacy, "-I"]))
                for key in ("ssid", "bssid", "rssi_dbm", "channel", "band_ghz"):
                    if data[key] is None:
                        data[key] = old[key]
                sources.append("airport")
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
    data["wifi_source"] = "+".join(sources) or None
    return data


def measure_ping(target: str, packets: int) -> dict[str, float | None]:
    is_windows = platform.system() == "Windows"
    args = (["ping", "-n", str(packets), "-w", "1000", target] if is_windows
            else ["ping", "-c", str(packets), target])
    try:
        output = command_output(args, timeout=packets * 3 + 7)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"latency_ms": None, "packet_loss_pct": None, "ping_error": str(exc)}
    return parse_ping(output, packets)


def parse_ping(output: str, packets: int) -> dict[str, Any]:
    """Cross-platform ping parse, with unparseable stats left as null."""
    times = [float(m.replace(",", ".")) for m in re.findall(
        r"\btime\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms\b", output, re.I)]
    result: dict[str, Any] = {
        "latency_ms": round(sum(times) / len(times), 2) if times else None,
        "packet_loss_pct": None,
    }
    # Prefer ping's actual packet summary over counting parsed reply lines.
    mac = re.search(r"(\d+)\s+packets? transmitted,\s*(\d+)\s+packets? received", output, re.I)
    win = re.search(r"Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+)", output, re.I)
    summary = mac or win
    if summary:
        sent, received = (int(summary.group(1)), int(summary.group(2)))
        if sent:
            result["packet_loss_pct"] = round(100 * (sent - received) / sent, 2)
    elif times:
        result["packet_loss_pct"] = round(100 * (packets - min(packets, len(times))) / packets, 2)
    else:
        result["ping_error"] = "Could not parse ping response; ICMP might be blocked"
    return result


def measure_speed() -> dict[str, Any]:
    """speedtest-cli library uses internet test servers, not the Wi-Fi PHY rate."""
    try:
        import speedtest
    except ImportError:
        return {"download_mbps": None, "upload_mbps": None,
                "speedtest_ping_ms": None,
                "speedtest_error": "Install dependencies: pip install -r requirements.txt"}
    try:
        tester = speedtest.Speedtest(secure=True, timeout=10)
        server = tester.get_best_server()
        down = tester.download() / 1_000_000
        up = tester.upload(pre_allocate=False) / 1_000_000
        return {
            "download_mbps": round(down, 2), "upload_mbps": round(up, 2),
            "speedtest_ping_ms": round(float(tester.results.ping), 2),
            "speedtest_server": server.get("name"),
        }
    except Exception as exc:
        return {"download_mbps": None, "upload_mbps": None,
                "speedtest_ping_ms": None, "speedtest_error": str(exc)}


def get_browser_location(timeout: int = 90) -> tuple[float, float, float | None]:
    """Ask the user's browser for location, with explicit browser permission."""
    received: dict[str, float] = {}
    done = threading.Event()
    html = """<!doctype html><html lang='en'><meta charset='utf-8'>
<title>Wi-Fi survey location</title>
<body style='font:16px system-ui;max-width:560px;margin:70px auto;padding:20px'>
<h2>Use this laptop's current location?</h2>
<p>The browser will ask permission. The coordinates go only to the Python collector
running on your laptop. Indoor accuracy can be poor; check the result.</p>
<button id='go'>Share location with collector</button><p id='message'></p>
<script>
const output=document.getElementById('message');
document.getElementById('go').onclick=()=>{
 output.textContent='Requesting browser permission...';
 if (!navigator.geolocation){output.textContent='Browser geolocation unavailable';return;}
 navigator.geolocation.getCurrentPosition(async p=>{
  try {
   const r=await fetch('/location', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({latitude:p.coords.latitude,longitude:p.coords.longitude,
      accuracy_m:p.coords.accuracy})});
   output.textContent=r.ok?'Location received. Return to your terminal.':'Location was not accepted.';
  }catch(e){output.textContent='Could not contact the local collector.'}
 }, e=>output.textContent='Location error: '+e.message,
 {enableHighAccuracy:true,timeout:20000,maximumAge:0});
};
</script></body></html>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            payload = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if self.path != "/location":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 1024:
                    raise ValueError("Invalid request size")
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                lat, lon = float(obj["latitude"]), float(obj["longitude"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("Out-of-range coordinates")
                accuracy = obj.get("accuracy_m")
                received.update(latitude=lat, longitude=lon)
                if accuracy is not None:
                    received["accuracy_m"] = float(accuracy)
                self.send_response(204)
                self.end_headers()
                done.set()
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                self.send_error(400)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    print(f"Open {url} and click 'Share location with collector'.")
    webbrowser.open(url)
    try:
        if not done.wait(timeout):
            raise TimeoutError("No browser location received. Use --lat and --lon instead.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return received["latitude"], received["longitude"], received.get("accuracy_m")


def device_metadata() -> dict[str, str]:
    """No personal hostname, serial number, or machine MAC address."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    device_id_file = DATA_DIR / ".device_id"
    if device_id_file.exists():
        device_id = device_id_file.read_text(encoding="utf-8").strip()
    else:
        device_id = uuid.uuid4().hex
        device_id_file.write_text(device_id + "\n", encoding="utf-8")
    return {
        "device_id": device_id,
        "os_name": platform.system(), "os_version": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
    }


def collect_once(args: argparse.Namespace, coords: tuple[float, float, float | None]) -> dict[str, Any]:
    lat, lon, accuracy = coords
    record: dict[str, Any] = {
        "measurement_id": uuid.uuid4().hex,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latitude": lat, "longitude": lon,
        "location_accuracy_m": accuracy,
        "location_method": "browser" if args.browser_location else "manual",
        "location_label": args.location_label,
        "cell_id": args.cell_id,
        "measurement_source": "laptop_collector_v1",
        "device": device_metadata(),
    }
    errors = []
    system = platform.system()
    try:
        if system == "Windows":
            wifi = windows_wifi()
        elif system == "Darwin":
            wifi = mac_wifi()
        else:
            raise RuntimeError(f"Unsupported platform: {system}; use macOS or Windows")
        record.update(wifi)
        if wifi.get("rssi_dbm") is None and wifi.get("signal_percent") is None:
            errors.append("Signal strength unavailable (disconnected Wi-Fi or OS permissions)")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        record.update(empty_wifi())
        errors.append("Wi-Fi metadata: " + str(exc))

    if args.skip_ping:
        record.update({"latency_ms": None, "packet_loss_pct": None, "ping_target": None})
    else:
        ping = measure_ping(args.ping_host, args.packets)
        record.update({"latency_ms": ping["latency_ms"], "packet_loss_pct": ping["packet_loss_pct"],
                       "ping_target": args.ping_host})
        if ping.get("ping_error"):
            errors.append("Ping: " + ping["ping_error"])

    # Every record carries the same keys, so Firestore documents share a shape.
    if args.skip_speedtest:
        record.update({"download_mbps": None, "upload_mbps": None,
                       "speedtest_ping_ms": None, "speedtest_server": None})
    else:
        speed = measure_speed()
        record.update({k: speed.get(k) for k in (
            "download_mbps", "upload_mbps", "speedtest_ping_ms", "speedtest_server")})
        if speed.get("speedtest_error"):
            errors.append("Speedtest: " + speed["speedtest_error"])
    record["errors"] = errors
    return record


def write_local(record: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    # CSV is also convenient for the ML teammate. Flatten nested device fields.
    csv_path = output.with_suffix(".csv")
    flat = {key: value for key, value in record.items() if key not in ("device", "errors")}
    flat.update({"device_" + k: v for k, v in record["device"].items()})
    flat["errors"] = "; ".join(record["errors"])
    fields = ["measurement_id", "measured_at", "latitude", "longitude", "location_accuracy_m",
              "location_method", "location_label", "cell_id",
              "download_mbps", "upload_mbps", "rssi_dbm", "signal_percent",
              "latency_ms", "packet_loss_pct", "ssid", "bssid", "channel",
              "band_ghz", "ping_target", "speedtest_ping_ms", "speedtest_server",
              "wifi_source", "measurement_source", "device_device_id",
              "device_os_name", "device_os_version", "device_architecture",
              "device_python_version", "errors"]
    exists = csv_path.exists() and csv_path.stat().st_size > 0
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(flat)


def get_firestore_client() -> Any:
    """Initialize the Firebase Admin SDK once and reuse its Firestore client.

    Uses Admin SDK credentials, so production-mode security rules can stay closed.
    """
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as exc:
        raise RuntimeError("Install firebase-admin: pip install -r requirements.txt") from exc

    try:
        app = firebase_admin.get_app()
    except ValueError:
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path:
            if not Path(creds_path).is_file():
                raise RuntimeError(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {creds_path}")
            cred = credentials.Certificate(creds_path)
        else:
            # Falls back to gcloud Application Default Credentials, if configured.
            cred = credentials.ApplicationDefault()
        app = firebase_admin.initialize_app(cred)
    _firestore_client = firestore.client(app)
    return _firestore_client


def firestore_document(record: dict[str, Any]) -> dict[str, Any]:
    """Copy of the record with measured_at as a timezone-aware datetime.

    The Admin SDK stores aware datetimes as native Firestore Timestamps.
    """
    document = dict(record)
    measured_at = datetime.fromisoformat(record["measured_at"])
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    document["measured_at"] = measured_at
    return document


def write_firestore(record: dict[str, Any]) -> str:
    """Upload to `measurements`, keyed by measurement_id so retries are idempotent."""
    document_id = record["measurement_id"]
    get_firestore_client().collection(FIRESTORE_COLLECTION).document(document_id).set(
        firestore_document(record))
    return document_id


def store_record(record: dict[str, Any], args: argparse.Namespace) -> bool:
    """Save one record: Firestore first when enabled, local files as backup.

    Returns False if the Firestore upload failed (the record is then saved locally).
    """
    if not args.firestore:
        write_local(record, args.output)
        return True
    try:
        doc_id = write_firestore(record)
    except Exception as exc:
        write_local(record, args.output)
        print(f"ERROR: Firestore upload failed: {exc}\n"
              f"Measurement saved locally as backup: {args.output.resolve()}", file=sys.stderr)
        return False
    print(f"Uploaded to Firestore {FIRESTORE_COLLECTION}/{doc_id}")
    if not args.no_local:
        write_local(record, args.output)
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mac/Windows Wi-Fi survey, one observation per run by default")
    location = parser.add_argument_group("location")
    location.add_argument("--lat", type=float, help="Latitude of laptop measurement site (manual)")
    location.add_argument("--lon", type=float, help="Longitude of laptop measurement site (manual)")
    location.add_argument("--browser-location", action="store_true",
                          help="Ask browser for user-approved coordinates (requires permission)")
    location.add_argument("--location-label", help="e.g. Geisel Library (user-provided)")
    location.add_argument("--cell-id", help="Optional stable grid ID for model grouping")
    parser.add_argument("--ping-host", default="1.1.1.1", help="ICMP destination (default: 1.1.1.1)")
    parser.add_argument("--packets", type=int, default=5, help="Ping packets per run (default: 5)")
    parser.add_argument("--skip-speedtest", action="store_true", help="Avoid expensive download/upload test")
    parser.add_argument("--skip-ping", action="store_true")
    parser.add_argument("--count", type=int, default=1, help="Number of samples (default: 1)")
    parser.add_argument("--interval", type=float, default=30, help="Delay between samples, seconds")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "measurements.jsonl")
    parser.add_argument("--firestore", action="store_true",
                        help="Upload to the Firestore measurements collection (primary storage)")
    parser.add_argument("--no-local", action="store_true",
                        help="With --firestore, skip CSV/JSONL output (still saved locally if upload fails)")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_environment()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.count < 1 or args.packets < 1 or args.interval < 0:
        parser.error("--count and --packets must be positive; --interval must be nonnegative")
    if args.no_local and not args.firestore:
        parser.error("--no-local requires --firestore")
    if platform.system() not in ("Darwin", "Windows"):
        parser.error("This laptop collector supports macOS and Windows")
    if args.browser_location:
        if args.lat is not None or args.lon is not None:
            parser.error("Use either --browser-location or --lat/--lon, not both")
        try:
            coords = get_browser_location()
        except TimeoutError as exc:
            parser.error(str(exc))
    else:
        if args.lat is None or args.lon is None:
            parser.error("Provide BOTH --lat and --lon, or use --browser-location")
        if not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
            parser.error("Latitude must be -90..90 and longitude -180..180")
        coords = (args.lat, args.lon, None)

    if args.firestore:
        # Fail fast on bad credentials, before spending time on measurements.
        try:
            get_firestore_client()
        except Exception as exc:
            print(f"WARNING: Firestore unavailable ({exc}); measurements will be saved locally.",
                  file=sys.stderr)

    print("Collecting connected Wi-Fi details, ping, and speed measurements...")
    print("Note: speed tests may transfer substantial data; use --skip-speedtest for frequent scans.")
    upload_failures = 0
    for n in range(args.count):
        if n:
            time.sleep(args.interval)
        record = collect_once(args, coords)
        if not store_record(record, args):
            upload_failures += 1
        print(f"\nSample {n + 1}/{args.count}: " + json.dumps({
            k: record.get(k) for k in (
                "measured_at", "latitude", "longitude", "ssid", "bssid",
                "band_ghz", "rssi_dbm", "signal_percent", "download_mbps",
                "upload_mbps", "latency_ms", "packet_loss_pct")}, indent=2))
        if record["errors"]:
            print("Warnings: " + "; ".join(record["errors"]))
    if upload_failures or not (args.firestore and args.no_local):
        print(f"\nSaved JSONL: {args.output.resolve()}")
        print(f"Saved CSV:   {args.output.with_suffix('.csv').resolve()}")
    if upload_failures:
        print(f"ERROR: {upload_failures}/{args.count} Firestore upload(s) failed; "
              "see local backup above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
