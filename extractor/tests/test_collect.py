import os
import sys
import tempfile
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect
from collect import (parse_windows_wifi, parse_ping, parse_airport_info, parse_macwifi_cli,
                     write_local, load_environment, firestore_document, store_record)


class CollectorParserTests(TestCase):
    def test_windows_wifi_with_rssi(self):
        out = '''
    Name                   : Wi-Fi
    Description            : Intel Wi-Fi 6E
    State                  : connected
    SSID                   : eduroam
    BSSID                  : aa:bb:cc:dd:ee:ff
    Network type           : Infrastructure
    Radio type             : 802.11ax
    Band                   : 5 GHz
    Channel                : 44
    Signal                 : 88%
    RSSI                   : -54
'''
        result = parse_windows_wifi(out)
        self.assertEqual(result['rssi_dbm'], -54)
        self.assertEqual(result['band_ghz'], '5')
        self.assertEqual(result['ssid'], 'eduroam')
        self.assertEqual(result['signal_percent'], 88)
        self.assertEqual(result['channel'], 44)

    def test_windows_without_rssi(self):
        result = parse_windows_wifi('SSID : x\nSignal : 75%\nChannel : 11')
        self.assertIsNone(result['rssi_dbm'])
        self.assertEqual(result['signal_percent'], 75)

    def test_mac_ping(self):
        result = parse_ping('''5 packets transmitted, 4 packets received, 20.0% packet loss
64 bytes from 1.1.1.1: icmp_seq=0 ttl=58 time=6.30 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=8.30 ms''', 5)
        self.assertEqual(result['packet_loss_pct'], 20)
        self.assertEqual(result['latency_ms'], 7.3)

    def test_windows_ping(self):
        out = '''Reply from 1.1.1.1: bytes=32 time=9ms TTL=50
Reply from 1.1.1.1: bytes=32 time<1ms TTL=50
Packets: Sent = 5, Received = 2, Lost = 3 (60% loss)'''
        result = parse_ping(out, 5)
        self.assertEqual(result['packet_loss_pct'], 60)
        self.assertEqual(result['latency_ms'], 5)

    def test_legacy_airport(self):
        result = parse_airport_info('''     agrCtlRSSI: -61
          SSID: eduroam
          BSSID: 12:34:56:78:9a:bc
          channel: 36,80''')
        self.assertEqual(result['rssi_dbm'], -61)
        self.assertEqual(result['channel'], 36)

    def test_macwifi_json(self):
        result = parse_macwifi_cli('{"ssid":"eduroam", "bssid":"01:02:03:04:05:06", "rssi":-50, "channel":149, "band":"5GHz"}')
        self.assertEqual(result['band_ghz'], '5')
        self.assertEqual(result['rssi_dbm'], -50)

    def test_local_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            outfile = Path(tmp) / 'measurements.jsonl'
            sample = {'measured_at':'2026-11-07T20:00:00+00:00', 'device':{'device_id':'test'}, 'errors':[]}
            write_local(sample, outfile)
            self.assertTrue(outfile.exists())
            self.assertTrue(outfile.with_suffix('.csv').exists())

    def test_windows_ap_bssid(self):
        result = parse_windows_wifi('SSID : x\nAP BSSID : aa:bb:cc:dd:ee:ff')
        self.assertEqual(result['bssid'], 'aa:bb:cc:dd:ee:ff')


SAMPLE = {'measurement_id': 'abc123', 'measured_at': '2026-11-07T20:00:00+00:00',
          'device': {'device_id': 'test'}, 'errors': []}


class FirestoreTests(TestCase):
    def test_relative_credentials_resolved_against_env_dir(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / 'settings'
            env_file.write_text('GOOGLE_APPLICATION_CREDENTIALS=keys/sa.json\n')
            load_environment(env_file)
            self.assertEqual(os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
                             str((Path(tmp) / 'keys/sa.json').resolve()))

    def test_measured_at_becomes_aware_datetime(self):
        doc = firestore_document(SAMPLE)
        self.assertEqual(doc['measured_at'], datetime(2026, 11, 7, 20, tzinfo=timezone.utc))
        self.assertEqual(SAMPLE['measured_at'], '2026-11-07T20:00:00+00:00')

    def test_upload_failure_saves_local_backup(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(collect, 'write_firestore', side_effect=RuntimeError('denied')):
            args = Namespace(firestore=True, no_local=True, output=Path(tmp) / 'm.jsonl')
            self.assertFalse(store_record(dict(SAMPLE), args))
            self.assertTrue(args.output.exists())

    def test_no_local_skips_files_on_success(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(collect, 'write_firestore', return_value='abc123'):
            args = Namespace(firestore=True, no_local=True, output=Path(tmp) / 'm.jsonl')
            self.assertTrue(store_record(dict(SAMPLE), args))
            self.assertFalse(args.output.exists())
