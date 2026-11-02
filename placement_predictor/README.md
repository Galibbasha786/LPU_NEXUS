# Placement predictor

The project dataset is stored at `ml-data/student_placement_career_success_dataset_2026.csv`.
The training script predicts `Placement_Status`; it excludes `Salary_LPA` to avoid target leakage.

From the repository's `lpu_nexus/` directory:

```bash
python -m pip install -r requirements.txt
python scripts/train_placement_model.py
python manage.py apply_placement_validator
python manage.py runserver
```

Visit `/placement-predictor/`. The trained artifact is `placement_predictor/placement_model.joblib` and is intentionally git-ignored; retrain it in each deployment environment. Each successful prediction stores the prediction, confidence, model version, input values, optional session student ID, and timestamp in MongoDB collection `placement_predictions`.

MongoDB validator can also be applied directly from `mongosh`:

```javascript
db.runCommand({
  collMod: "placement_predictions",
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["prediction", "confidence", "model_version", "created_at", "input"],
      properties: {
        student_id: { bsonType: ["string", "null"] },
        prediction: { bsonType: "string" },
        confidence: { bsonType: "double", minimum: 0, maximum: 1 },
        model_version: { bsonType: "string" },
        created_at: { bsonType: "date" },
        input: { bsonType: "object" }
      }
    }
  },
  validationLevel: "strict",
  validationAction: "error"
})
```

For the first run, create the collection with the same validator instead of `collMod`:
`db.createCollection("placement_predictions", {validator: <same validator>, validationLevel: "strict", validationAction: "error"})`.
