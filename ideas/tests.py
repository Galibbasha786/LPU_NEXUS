from datetime import datetime, timedelta
from unittest.mock import patch

from bson import ObjectId
from django.test import SimpleTestCase

from . import services


class IdeaPollServiceTests(SimpleTestCase):
    @patch("ideas.services.ideas")
    @patch("ideas.services.now")
    def test_new_idea_poll_expires_exactly_seven_days_after_creation(
        self, now, idea_collection,
    ):
        created_at = datetime(2026, 1, 1)
        author_id = ObjectId()
        idea_id = ObjectId()
        now.return_value = created_at
        idea_collection.return_value.insert_one.return_value.inserted_id = idea_id

        result = services.create_idea(
            {"id": str(author_id), "full_name": "Student", "email": "student@example.edu"},
            "Add more study spaces",
            "Open unused rooms as quiet study spaces.",
            "campus",
        )

        self.assertEqual(result["status"], "poll_open")
        self.assertEqual(result["poll_ends_at"], created_at + timedelta(days=7))
        self.assertEqual(result["author_id"], author_id)

    @patch("ideas.services.idea_votes")
    @patch("ideas.services.get_idea")
    @patch("ideas.services.now")
    def test_student_vote_is_saved_once_per_idea_and_can_be_changed(
        self, now, get_idea, votes,
    ):
        idea_id = ObjectId()
        student_id = ObjectId()
        now.return_value = datetime(2026, 1, 2)
        get_idea.return_value = {
            "_id": idea_id,
            "author_id": ObjectId(),
            "status": "poll_open",
            "poll_ends_at": datetime(2026, 1, 8),
        }

        success, error = services.add_vote(str(idea_id), str(student_id), True)

        self.assertTrue(success)
        self.assertIsNone(error)
        query, operation = votes.return_value.update_one.call_args.args[:2]
        self.assertEqual(query, {"idea_id": idea_id, "user_id": student_id})
        self.assertTrue(operation["$set"]["support"])
        self.assertTrue(votes.return_value.update_one.call_args.kwargs["upsert"])

    @patch("ideas.services.idea_votes")
    @patch("ideas.services.get_idea")
    @patch("ideas.services.now")
    def test_idea_author_cannot_vote_on_own_poll(self, now, get_idea, votes):
        idea_id = ObjectId()
        author_id = ObjectId()
        now.return_value = datetime(2026, 1, 2)
        get_idea.return_value = {
            "author_id": author_id,
            "status": "poll_open",
            "poll_ends_at": datetime(2026, 1, 8),
        }

        success, error = services.add_vote(str(idea_id), str(author_id), True)

        self.assertFalse(success)
        self.assertIn("own idea", error)
        votes.return_value.update_one.assert_not_called()

    @patch("ideas.services.ideas")
    @patch("ideas.services.now")
    def test_expired_polls_move_to_admin_review(self, now, idea_collection):
        timestamp = datetime(2026, 1, 8)
        now.return_value = timestamp

        services.close_expired_polls()

        query, operation = idea_collection.return_value.update_many.call_args.args
        self.assertEqual(query["status"], "poll_open")
        self.assertEqual(query["poll_ends_at"], {"$lte": timestamp})
        self.assertEqual(operation["$set"]["status"], "pending_review")
