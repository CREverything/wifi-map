"""One local measurement requested by the map UI; no browser or shell commands."""
import json
import sys
import collect

def main():
    payload = json.load(sys.stdin)
    collect.load_environment()
    args = collect.build_parser().parse_args([])
    args.browser_location = True
    args.skip_speedtest = not payload.get('speedtest', False)
    args.firestore = payload.get('firestore', False)
    record = collect.collect_once(args, (payload['latitude'], payload['longitude'], payload['accuracy']))
    stored = collect.store_record(record, args)
    print('BRIDGE_RESULT:' + json.dumps({'record':record, 'firestoreUploaded':bool(args.firestore and stored)}))

if __name__ == '__main__':
    main()
