"""Minimal file-based model registry (swap for MLflow/SageMaker Model Registry in production)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib

import sentinel_ml

MODEL_NAMES = ("outbreak_classifier", "anomaly_ensemble", "forecaster_xgboost", "forecaster_naive")


def save_model(obj, name: str, directory: str | Path, metadata: dict | None = None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.joblib"
    joblib.dump(obj, path, compress=3)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "name": name,
        "file": path.name,
        "sha256": digest,
        "library_version": sentinel_ml.__version__,
        "created_at": datetime.now(UTC).isoformat(),
        **(metadata or {}),
    }
    (directory / f"{name}.json").write_text(json.dumps(manifest, indent=2, default=str))
    return path


def load_model(name: str, directory: str | Path, verify: bool = True):
    directory = Path(directory)
    path = directory / f"{name}.joblib"
    if not path.exists():
        return None
    if verify:
        manifest_path = directory / f"{name}.json"
        if manifest_path.exists():
            expected = json.loads(manifest_path.read_text())["sha256"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"checksum mismatch for model artifact {path}")
    return joblib.load(path)
