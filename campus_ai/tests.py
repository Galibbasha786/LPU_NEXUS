from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings

from . import services


class CampusAiServiceTests(SimpleTestCase):
    def test_redacts_emails_phone_numbers_and_long_identifiers(self):
        safe_text = services.redact_personal_identifiers(
            "Email student@lpu.in, call +91 98765 43210, UID 12345678."
        )

        self.assertNotIn("student@lpu.in", safe_text)
        self.assertNotIn("98765 43210", safe_text)
        self.assertNotIn("12345678", safe_text)
        self.assertIn("[email removed]", safe_text)
        self.assertIn("[phone removed]", safe_text)
        self.assertIn("[identifier removed]", safe_text)

    def test_retrieval_only_returns_location_matches_and_curated_features(self):
        context = services.retrieve_campus_context("Where is the Central Library?")

        self.assertIn("LPU Nexus features", [title for title, _ in context])
        self.assertIn("Campus map locations", [title for title, _ in context])
        location_context = dict(context)["Campus map locations"]
        self.assertIn("Central Library (Block 37)", location_context)

    def test_emergency_signals_are_detected_without_calling_a_model(self):
        self.assertTrue(services.contains_emergency_signal("There is smoke in the hostel."))
        self.assertTrue(services.contains_emergency_signal("A student was injured."))
        self.assertFalse(services.contains_emergency_signal("The Wi-Fi is not working."))

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-test")
    @patch("campus_ai.services.requests.post")
    def test_question_sends_only_redacted_question_and_curated_context(self, post):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "The campus map lists the Central Library."}]}
            }]
        }

        answer = services.answer_campus_question(
            "Where is the library? My email is student@lpu.in"
        )

        self.assertIn("Central Library", answer)
        request = post.call_args.kwargs
        self.assertEqual(request["headers"]["x-goog-api-key"], "test-key")
        prompt = request["json"]["contents"][0]["parts"][0]["text"]
        self.assertNotIn("student@lpu.in", prompt)
        self.assertIn("[email removed]", prompt)
        self.assertIn("Central Library (Block 37)", prompt)

    @override_settings(GEMINI_API_KEY="")
    def test_missing_api_key_fails_explicitly(self):
        with self.assertRaisesRegex(services.GeminiServiceError, "GEMINI_API_KEY"):
            services.answer_campus_question("Where is the library?")

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("campus_ai.services.requests.post")
    def test_http_auth_error_is_not_reported_as_network_failure(self, post):
        response = type("Response", (), {"status_code": 403})()
        post.return_value.raise_for_status.side_effect = requests.HTTPError(
            response=response
        )

        with self.assertRaisesRegex(services.GeminiServiceError, "denied access"):
            services.answer_campus_question("How do I use reports?")

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("campus_ai.services.requests.post")
    def test_http_quota_error_has_actionable_message(self, post):
        response = type("Response", (), {"status_code": 429})()
        post.return_value.raise_for_status.side_effect = requests.HTTPError(
            response=response
        )

        with self.assertRaisesRegex(services.GeminiServiceError, "quota or rate limit"):
            services.answer_campus_question("How do I use reports?")

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("campus_ai.services.requests.post")
    def test_http_model_not_found_has_configuration_message(self, post):
        response = type("Response", (), {"status_code": 404})()
        post.return_value.raise_for_status.side_effect = requests.HTTPError(
            response=response
        )

        with self.assertRaisesRegex(services.GeminiServiceError, "GEMINI_MODEL"):
            services.answer_campus_question("How do I use reports?")

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("campus_ai.services.requests.post")
    def test_triage_rejects_values_outside_allowed_choices(self, post):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {
            "candidates": [{
                "content": {"parts": [{
                    "text": (
                        '{"category":"unknown","priority":"urgent","summary":"test",'
                        '"reason":"test","suggested_team":"Facilities"}'
                    )
                }]}
            }]
        }

        with self.assertRaisesRegex(services.GeminiServiceError, "invalid triage"):
            services.triage_problem("Leaking pipe", "Water by the dorm.", "water")

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("campus_ai.services.requests.post")
    def test_triage_returns_validated_suggestion_and_redacts_identifiers(self, post):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {
            "candidates": [{
                "content": {"parts": [{
                    "text": (
                        '{"category":"water","priority":"high","summary":"Pipe leak",'
                        '"reason":"Water may damage the area.","suggested_team":"Facilities and plumbing"}'
                    )
                }]}
            }]
        }

        suggestion = services.triage_problem(
            "Leak in room 12345678",
            "Contact me at student@lpu.in about the leaking pipe.",
            "other",
        )

        self.assertEqual(suggestion["category"], "water")
        self.assertEqual(suggestion["priority"], "high")
        prompt = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertNotIn("student@lpu.in", prompt)
        self.assertNotIn("12345678", prompt)
        self.assertIn("[email removed]", prompt)


class CampusAiViewTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["lpu_user_id"] = "507f1f77bcf86cd799439011"
        session["lpu_user_role"] = "student"
        session.save()

    @patch("campus_ai.views.get_current_user")
    @patch("campus_ai.views.answer_campus_question", return_value="Verified answer.")
    def test_question_requires_privacy_opt_in(self, answer, get_user):
        get_user.return_value = {"id": "507f1f77bcf86cd799439011", "role": "student"}

        response = self.client.post("/campus-ai/ask/", {"question": "Where is the library?"})

        self.assertEqual(response.status_code, 400)
        answer.assert_not_called()

    @patch("campus_ai.views.get_current_user")
    @patch("campus_ai.views.answer_campus_question", return_value="Verified answer.")
    def test_question_with_opt_in_returns_answer(self, answer, get_user):
        get_user.return_value = {"id": "507f1f77bcf86cd799439011", "role": "student"}

        response = self.client.post("/campus-ai/ask/", {
            "question": "Where is the library?",
            "consent": "on",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"answer": "Verified answer."})
        answer.assert_called_once_with("Where is the library?")

    @patch("campus_ai.views.get_current_user")
    @patch("campus_ai.views.answer_campus_question", return_value="Reports are available from the student dashboard.")
    def test_normal_question_is_not_rejected_by_length_validation(self, answer, get_user):
        get_user.return_value = {"id": "507f1f77bcf86cd799439011", "role": "student"}

        response = self.client.post("/campus-ai/ask/", {
            "question": "how to use reports",
            "consent": "on",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["answer"],
            "Reports are available from the student dashboard.",
        )
        answer.assert_called_once_with("how to use reports")

    @patch("campus_ai.views.get_current_user")
    @patch("campus_ai.views.answer_campus_question")
    def test_question_over_limit_gets_a_specific_length_error(self, answer, get_user):
        get_user.return_value = {"id": "507f1f77bcf86cd799439011", "role": "student"}

        response = self.client.post("/campus-ai/ask/", {
            "question": "a" * 4001,
            "consent": "on",
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Questions can be up to 4,000 characters.",
        )
        answer.assert_not_called()

    @patch("campus_ai.views.get_current_user")
    @patch("campus_ai.views.create_triage_suggestion")
    def test_triage_requires_privacy_opt_in(self, triage, get_user):
        get_user.return_value = {"id": "507f1f77bcf86cd799439011", "role": "student"}

        response = self.client.post("/campus-ai/triage-problem/", {
            "title": "Water leak",
            "description": "Water is leaking.",
            "category": "water",
        })

        self.assertEqual(response.status_code, 400)
        triage.assert_not_called()

    @patch("campus_ai.views.create_triage_suggestion")
    def test_emergency_triage_is_blocked_before_model_call(self, triage):
        response = self.client.post("/campus-ai/triage-problem/", {
            "title": "Smoke in the hostel",
            "description": "There is a fire.",
            "category": "safety",
            "consent": "on",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not handle emergencies", response.json()["error"])
        triage.assert_not_called()

    @patch("campus_ai.views.problems")
    @patch("campus_ai.views.get_current_user")
    @patch("campus_ai.views.create_triage_suggestion")
    def test_triage_returns_model_suggestion_and_local_similarity_count(
        self, triage, get_user, problem_collection,
    ):
        get_user.return_value = {"id": "507f1f77bcf86cd799439011", "role": "student"}
        triage.return_value = {
            "category": "water",
            "priority": "high",
            "summary": "Pipe leak",
            "reason": "Water is spreading.",
            "suggested_team": "Facilities and plumbing",
        }
        problem_collection.return_value.count_documents.return_value = 4

        response = self.client.post("/campus-ai/triage-problem/", {
            "title": "Leaking pipe",
            "description": "Water is leaking near the washroom.",
            "category": "water",
            "consent": "on",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestion"]["similar_open_reports"], 4)
        triage.assert_called_once_with(
            "Leaking pipe", "Water is leaking near the washroom.", "water",
        )
