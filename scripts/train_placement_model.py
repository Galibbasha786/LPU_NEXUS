"""Train and save the campus placement classifier."""
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "ml-data" / "student_placement_career_success_dataset_2026.csv"
OUTPUT_PATH = ROOT / "placement_predictor" / "placement_model.joblib"
TARGET = "Placement_Status"
FEATURES = [
    "Age", "Gender", "College_Tier", "Specialization", "CGPA", "DSA_Problems_Solved",
    "Internships", "Certifications", "Projects_Count", "Communication_Skills",
    "Aptitude_Test_Score", "LeetCode_Rating", "GitHub_Contributions",
    "Hackathons_Participated", "AI_ML_Skill_Level", "System_Design_Knowledge",
    "Resume_Score", "Mock_Interview_Score",
]
CATEGORICAL = ["Gender", "College_Tier", "Specialization"]
NUMERIC = [name for name in FEATURES if name not in CATEGORICAL]


def main():
    df = pd.read_csv(DATA_PATH)
    missing = sorted(set(FEATURES + [TARGET]) - set(df.columns))
    if missing:
        raise ValueError(f"Dataset is missing required columns: {', '.join(missing)}")
    df = df[FEATURES + [TARGET]].dropna(subset=[TARGET])
    x, y = df[FEATURES], df[TARGET]
    preprocess = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median"), NUMERIC),
        ("categorical", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]), CATEGORICAL),
    ])
    model = Pipeline([
        ("preprocess", preprocess),
        ("classifier", RandomForestClassifier(n_estimators=400, class_weight="balanced", random_state=42, n_jobs=-1)),
    ])
    model.fit(x, y)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    target_distribution = {str(label): int(count) for label, count in y.value_counts().items()}
    joblib.dump({
        "model": model,
        "feature_names": FEATURES,
        "target": TARGET,
        "target_distribution": target_distribution,
        "version": "2",
    }, OUTPUT_PATH)
    print(f"Saved model trained on {len(df):,} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
