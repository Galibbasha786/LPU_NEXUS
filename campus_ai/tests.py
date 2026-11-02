from unittest.mock import Mock, patch

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

    def test_local_classifier_predicts_a_category_from_training_examples(self):
        suggestion = services.suggest_problem_category(
            "Leaking tap",
            "Water keeps dripping from the sink in the washroom.",
        )

        self.assertEqual(suggestion["category"], "water")
        self.assertEqual(suggestion["label"], "Water & plumbing")
        self.assertGreaterEqual(suggestion["confidence"], 0)
        self.assertLessEqual(suggestion["confidence"], 1)

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

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-3.6-flash")
    @patch("campus_ai.services.requests.post")
    def test_configured_current_model_is_used_in_gemini_request(self, post):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": "The Central Library is listed on the campus map."}]}
            }]
        }

        services.answer_campus_question("Where is the library?")

        self.assertEqual(
            post.call_args.args[0],
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.6-flash:generateContent",
        )

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

    @override_settings(
        GEMINI_API_KEY="test-key",
        GEMINI_MODEL="gemini-primary",
        GEMINI_FALLBACK_MODEL="gemini-fallback",
    )
    @patch("campus_ai.services.requests.post")
    def test_triage_retries_transient_server_errors_with_fallback_model(self, post):
        primary_response = Mock()
        primary_response.raise_for_status.side_effect = requests.HTTPError(
            response=Mock(status_code=503)
        )
        fallback_response = Mock()
        fallback_response.raise_for_status.return_value = None
        fallback_response.json.return_value = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{
                    "text": (
                        '{"category":"water","priority":"normal","summary":"Tap leak",'
                        '"reason":"The sink tap is leaking.","suggested_team":"Facilities and plumbing"}'
                    )
                }]},
            }],
        }
        post.side_effect = [primary_response, fallback_response]

        suggestion = services.triage_problem(
            "Leaking tap",
            "Water is dripping from the sink.",
            "water",
        )

        self.assertEqual(suggestion["category"], "water")
        self.assertEqual(post.call_count, 2)
        self.assertIn("/models/gemini-primary:generateContent", post.call_args_list[0].args[0])
        self.assertIn("/models/gemini-fallback:generateContent", post.call_args_list[1].args[0])
        self.assertEqual(
            post.call_args_list[1].kwargs["json"]["generationConfig"]["responseSchema"],
            post.call_args_list[0].kwargs["json"]["generationConfig"]["responseSchema"],
        )

    @override_settings(
        GEMINI_API_KEY="test-key",
        GEMINI_MODEL="gemini-primary",
        GEMINI_FALLBACK_MODEL="gemini-fallback",
    )
    @patch("campus_ai.services.requests.post")
    def test_reports_when_primary_and_fallback_models_are_unavailable(self, post):
        responses = []
        for status_code in (503, 503):
            response = Mock()
            response.raise_for_status.side_effect = requests.HTTPError(
                response=Mock(status_code=status_code)
            )
            responses.append(response)
        post.side_effect = responses

        with self.assertRaisesRegex(
            services.GeminiServiceError,
            "including the backup model",
        ):
            services.answer_campus_question("Where is the library?")

        self.assertEqual(post.call_count, 2)

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

        with self.assertRaisesRegex(services.GeminiServiceError, "allowed report categories"):
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
        response_schema = post.call_args.kwargs["json"]["generationConfig"]["responseSchema"]
        self.assertEqual(response_schema["type"], "OBJECT")
        self.assertEqual(
            response_schema["properties"]["category"]["enum"],
            list(dict(services.PROBLEM_CATEGORIES)),
        )
        self.assertEqual(
            response_schema["properties"]["priority"]["enum"],
            list(dict(services.PROBLEM_PRIORITIES)),
        )
        self.assertIn("suggested_team", response_schema["required"])

    @patch("campus_ai.services._generate", return_value={
        "promptFeedback": {"blockReason": "OTHER"},
        "candidates": [],
    })
    def test_triage_reports_when_gemini_blocks_a_suggestion(self, generate):
        with self.assertRaisesRegex(services.GeminiServiceError, "could not process this report"):
            services._generate_json("Report prompt")

    @patch("campus_ai.services._generate", return_value={
        "candidates": [{
            "finishReason": "MAX_TOKENS",
            "content": {"parts": [{"text": '{"category":"water"}'}]},
        }],
    })
    def test_triage_reports_incomplete_generation_separately(self, generate):
        with self.assertRaisesRegex(services.GeminiServiceError, "could not complete"):
            services._generate_json("Report prompt")

    @patch("campus_ai.services._generate", return_value={
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": "not json"}]},
        }],
    })
    def test_triage_reports_unreadable_json_separately(self, generate):
        with self.assertRaisesRegex(services.GeminiServiceError, "unreadable triage suggestion"):
            services._generate_json("Report prompt")


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

    @patch(
        "campus_ai.views.suggest_problem_category",
        return_value={
            "category": "water",
            "label": "Water & plumbing",
            "confidence": 0.87,
        },
    )
    def test_local_category_prediction_does_not_require_gemini_consent(self, predict):
        response = self.client.post("/campus-ai/predict-problem-category/", {
            "title": "Leaking tap",
            "description": "Water is dripping from the sink.",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestion"]["category"], "water")
        predict.assert_called_once_with(
            "Leaking tap",
            "Water is dripping from the sink.",
        )

    @patch("campus_ai.views.suggest_problem_category")
    def test_local_category_prediction_rejects_emergency_reports(self, predict):
        response = self.client.post("/campus-ai/predict-problem-category/", {
            "title": "Smoke in the hostel",
            "description": "There is a fire.",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not handle emergencies", response.json()["error"])
        predict.assert_not_called()

    @patch("campus_ai.views.suggest_problem_category")
    def test_local_category_prediction_validates_required_report_text(self, predict):
        response = self.client.post("/campus-ai/predict-problem-category/", {
            "title": "",
            "description": "A description without a title.",
        })

        self.assertEqual(response.status_code, 400)
        predict.assert_not_called()

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
