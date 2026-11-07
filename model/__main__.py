"""Run from repository root: python -m model --help."""
import argparse
import json
from pathlib import Path
from .training import train
from .prediction import Predictor
from .synthetic import generate
from .evaluation import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Synthetic development example only")
    fit = commands.add_parser("train")
    fit.add_argument("data", help="JSON array of canonical measurements")
    fit.add_argument("artifact")
    predict = commands.add_parser("predict")
    predict.add_argument("artifact")
    predict.add_argument("request", help="JSON object")
    predict.add_argument("--method", choices=["baseline", "random_forest"], default="baseline")
    score = commands.add_parser("evaluate")
    score.add_argument("data")
    score.add_argument("--method", choices=["baseline", "random_forest"], default="random_forest")
    args = parser.parse_args()
    if args.command == "demo":
        predictor = Predictor(train(generate()))
        request = dict(latitude=32.88, longitude=-117.23, network_id="synthetic-demo-network", wifi_band="5GHz", hour=14)
        result = {"warning": "SYNTHETIC DEVELOPMENT DATA ONLY; not verified real-world results",
                  **{method: predictor.predict(request, method) for method in ("baseline", "random_forest")}}
    elif args.command == "train":
        artifact = train(json.loads(Path(args.data).read_text()), args.artifact)
        result = {"artifact": args.artifact, "data_sources": artifact["data_sources"]}
    elif args.command == "evaluate":
        result = evaluate(json.loads(Path(args.data).read_text()), args.method)
    else:
        result = Predictor.load(args.artifact).predict(json.loads(args.request), args.method)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
