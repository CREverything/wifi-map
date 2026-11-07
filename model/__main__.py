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
    firestore_train = commands.add_parser("firestore-train", help="Read collector measurements from Firestore")
    firestore_train.add_argument("artifact")
    firestore_train.add_argument("--collection", default="measurements")
    firestore_train.add_argument("--env-file", default=".env")
    firestore_predict = commands.add_parser("firestore-predict", help="Predict and write a new predictions document")
    firestore_predict.add_argument("artifact")
    firestore_predict.add_argument("request", help="Canonical or collector-style JSON object")
    firestore_predict.add_argument("--method", choices=["baseline", "random_forest"], default="baseline")
    firestore_predict.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    if args.command in ("firestore-train", "firestore-predict"):
        from .firestore_io import create_client, train_from_firestore, predict_to_firestore
        client = create_client(args.env_file)
        if args.command == "firestore-train":
            result = train_from_firestore(client, args.artifact, args.collection)
        else:
            result = predict_to_firestore(client, Predictor.load(args.artifact),
                json.loads(args.request), args.method, model_id=Path(args.artifact).name)
    elif args.command == "demo":
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
