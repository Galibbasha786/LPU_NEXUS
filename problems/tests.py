from datetime import datetime
from unittest.mock import patch

from bson import ObjectId
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

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
        self.assertEqual(result["image_url"], "")
        self.assertEqual(result["image_public_id"], "")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["created_at"], timestamp)
        history_collection.return_value.insert_one.assert_called_once()

    @patch("problems.services.problem_history")
    @patch("problems.services.student_profiles")
    @patch("problems.services.problems")
    @patch("problems.services.now")
    def test_create_problem_persists_uploaded_image_reference(
        self, now, problem_collection, profile_collection, history_collection,
    ):
        reporter_id = ObjectId()
        image = {
            "url": "https://res.cloudinary.com/test/report.png",
            "public_id": "lpu_nexus/problem_reports/report",
        }
        now.return_value = datetime(2026, 1, 1)
        profile_collection.return_value.find_one.return_value = {}
        problem_collection.return_value.insert_one.return_value.inserted_id = ObjectId()

        services.create_problem(
            {"id": str(reporter_id)}, "Broken light", "Light is out.",
            "facilities", "Block 1", "normal", image=image,
        )

        saved = problem_collection.return_value.insert_one.call_args.args[0]
        self.assertEqual(saved["image_url"], image["url"])
        self.assertEqual(saved["image_public_id"], image["public_id"])


class ProblemReportImageViewTests(TestCase):
    @patch("accounts.notification_services.notify_roles")
    @patch("problems.views.save_problem_image", return_value={
        "url": "https://res.cloudinary.com/test/report.png",
        "public_id": "lpu_nexus/problem_reports/report",
    })
    @patch("problems.views.services.create_problem")
    @patch("problems.views.get_current_user")
    def test_student_report_uploads_image_and_saves_public_reference(
        self, get_user, create_problem, save_image, notify_roles,
    ):
        user = {
            "id": str(ObjectId()),
            "role": "student",
            "full_name": "Student Example",
            "email": "student@example.edu",
        }
        get_user.return_value = user
        create_problem.return_value = {"_id": ObjectId()}
        session = self.client.session
        session["lpu_user_id"] = user["id"]
        session["lpu_user_role"] = "student"
        session.save()

        response = self.client.post("/problems/report/", {
            "title": "Broken light",
            "description": "Light is out in the hall.",
            "category": "facilities",
            "priority": "normal",
            "location": "Block 1",
            "image": SimpleUploadedFile(
                "report.png", b"image-data", content_type="image/png",
            ),
        })

        self.assertRedirects(
            response, "/problems/my-reports/", fetch_redirect_response=False,
        )
        save_image.assert_called_once()
        create_problem.assert_called_once_with(
            user, "Broken light", "Light is out in the hall.",
            "facilities", "Block 1", "normal",
            image=save_image.return_value,
        )
        notify_roles.assert_called_once()

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
