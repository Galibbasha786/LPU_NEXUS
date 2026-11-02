from django.core.management.base import BaseCommand, CommandError
from pymongo.errors import OperationFailure

from core.mongo import get_db


class Command(BaseCommand):
    help = "Create or update MongoDB schema validation for placement_predictions."

    def handle(self, *args, **options):
        db = get_db()
        validator = {"$jsonSchema": {
            "bsonType": "object",
            "required": ["prediction", "confidence", "model_version", "created_at", "input"],
            "properties": {
                "student_id": {"bsonType": ["string", "null"]},
                "prediction": {"bsonType": "string"},
                "confidence": {"bsonType": "double", "minimum": 0, "maximum": 1},
                "model_version": {"bsonType": "string"},
                "created_at": {"bsonType": "date"},
                "input": {"bsonType": "object"},
            },
        }}
        try:
            if "placement_predictions" not in db.list_collection_names():
                db.create_collection("placement_predictions", validator=validator,
                                     validationLevel="strict", validationAction="error")
            else:
                db.command({"collMod": "placement_predictions", "validator": validator,
                            "validationLevel": "strict", "validationAction": "error"})
        except OperationFailure as error:
            raise CommandError(f"Could not apply MongoDB validator: {error}") from error
        self.stdout.write(self.style.SUCCESS("Validator applied to placement_predictions."))
