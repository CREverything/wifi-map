"""One local measurement requested by the map UI; no browser or shell commands.

Reads {latitude, longitude, accuracy_m, speedtest, firestore} as JSON on stdin and
prints one BRIDGE_RESULT line: {record, firestore_uploaded}.
"""
import json
import sys

import collect

RESULT_PREFIX = "BRIDGE_RESULT:"


def main():
    request = json.load(sys.stdin)
    collect.load_environment()
    args = collect.build_parser().parse_args([])
    args.browser_location = True
    args.skip_speedtest = not request.get("speedtest", False)
    args.firestore = request.get("firestore", False)
    coords = (request["latitude"], request["longitude"], request["accuracy_m"])
    record = collect.collect_once(args, coords)
    stored = collect.store_record(record, args)
    print(RESULT_PREFIX + json.dumps({"record": record, "firestore_uploaded": bool(args.firestore and stored)}))


if __name__ == "__main__":
    main()
