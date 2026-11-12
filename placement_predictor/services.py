from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from django.conf import settings
from django.utils import timezone

from core.mongo import get_db


MODEL_PATH = Path(settings.BASE_DIR) / "placement_predictor" / "placement_model.joblib"
COLLECTION_NAME = "placement_predictions"


class PlacementModelError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_artifact():
    if not MODEL_PATH.exists():
        raise PlacementModelError("Placement model not found. Run scripts/train_placement_model.py first.")
    return joblib.load(MODEL_PATH)


def predict_placement(student_data, student_id=None):
    artifact = _load_artifact()
    # A single-row DataFrame preserves both the 2D shape and the named columns
    # expected by the fitted ColumnTransformer pipeline.
    row = pd.DataFrame(
        [{name: student_data[name] for name in artifact["feature_names"]}],
        columns=artifact["feature_names"],
    )
    model = artifact["model"]
    prediction = str(model.predict(row)[0])
    probabilities = model.predict_proba(row)[0]
    confidence = float(max(probabilities))
    classes = [str(value) for value in model.classes_]
    placed_probability = next(
        (float(probability) for label, probability in zip(classes, probabilities)
         if label.strip().casefold() in {'1', 'placed', 'yes', 'true'}),
        0.0,
    )
    # Keep the target label's observed training distribution in the artifact;
    # older artifacts can still be served with no distribution metadata.
    target_distribution = artifact.get("target_distribution", {})
    class_count = len(target_distribution) or len(classes)
    result = {
        "student_id": student_id,
        "prediction": prediction,
        "confidence": round(confidence, 4),
        "placed_probability": round(placed_probability, 4),
        "model_version": artifact.get("version", "1"),
        "class_count": class_count,
        "created_at": timezone.now(),
    }
    get_db()[COLLECTION_NAME].insert_one({**result, "input": student_data})
    return result
