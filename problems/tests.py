from datetime import datetime
from unittest.mock import patch

from bson import ObjectId
from django.test import SimpleTestCase

from . import services


class ProblemServiceTests(SimpleTestCase):
    @patch("problems.services.problem_history")
    @patch("problems.services.student_profiles")
    @patch("problems.services.problems")
    @patch("problems.services.now")
    def test_create_problem_records_reporter_and_starts_in_queue(
        self, now, problem_collection, profile_collection, history_collection,
    ):
        timestamp = datetime(2026, 1, 1)
        reporter_id = ObjectId()
        problem_id = ObjectId()
        now.return_value = timestamp
        profile_collection.return_value.find_one.return_value = {
            "registration_number": "12345678",
        }
        problem_collection.return_value.insert_one.return_value.inserted_id = problem_id
        reporter = {
            "id": str(reporter_id),
            "full_name": "Student Example",
            "email": "student@example.edu",
        }

        result = services.create_problem(
            reporter, "Wi-Fi down", "No connection in the library.",
            "wifi", "Library, floor 2", "high",
        )

        self.assertEqual(result["_id"], problem_id)
        self.assertEqual(result["reported_by"], reporter_id)
        self.assertEqual(result["registration_number"], "12345678")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["created_at"], timestamp)
        history_collection.return_value.insert_one.assert_called_once()

    @patch("problems.services.problem_history")
    @patch("problems.services.problems")
    @patch("problems.services.now")
    def test_update_problem_records_status_priority_and_assignment(
        self, now, problem_collection, history_collection,
    ):
        timestamp = datetime(2026, 1, 2)
        problem_id = ObjectId()
        actor_id = ObjectId()
        staff_id = ObjectId()
        now.return_value = timestamp
        problem_collection.return_value.update_one.return_value.matched_count = 1

        updated = services.update_problem(
            str(problem_id),
            {"id": str(actor_id)},
            status="in_progress",
            priority="urgent",
            assignee=str(staff_id),
        )

        self.assertTrue(updated)
        query, operation = problem_collection.return_value.update_one.call_args.args
        self.assertEqual(query, {"_id": problem_id})
        self.assertEqual(operation["$set"]["status"], "in_progress")
        self.assertEqual(operation["$set"]["priority"], "urgent")
        self.assertEqual(operation["$set"]["assigned_to"], staff_id)
        self.assertEqual(history_collection.return_value.insert_one.call_count, 3)
