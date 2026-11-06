from datetime import datetime, timedelta
from unittest.mock import patch

from bson import ObjectId
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

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
        self.assertEqual(result["media_url"], "")

    @patch("ideas.services.ideas")
    @patch("ideas.services.now")
    def test_create_idea_persists_uploaded_media_reference(self, now, idea_collection):
        idea_id = ObjectId()
        media = {
            "url": "https://res.cloudinary.com/test/idea.mp4",
            "public_id": "lpu_nexus/idea_media/idea-id",
            "media_type": "video",
        }
        now.return_value = datetime(2026, 1, 1)
        idea_collection.return_value.insert_one.return_value.inserted_id = idea_id

        services.create_idea(
            {"id": str(ObjectId())}, "Study spaces", "Open more rooms.", "campus",
            media=media,
        )

        saved = idea_collection.return_value.insert_one.call_args.args[0]
        self.assertEqual(saved["media_url"], media["url"])
        self.assertEqual(saved["media_public_id"], media["public_id"])
        self.assertEqual(saved["media_type"], "video")


class IdeaMediaUploadViewTests(TestCase):
    @patch("ideas.views.services.create_idea")
    @patch("ideas.views.save_idea_media", return_value={
        "url": "https://res.cloudinary.com/test/idea.mp4",
        "public_id": "lpu_nexus/idea_media/idea-id",
        "media_type": "video",
    })
    @patch("ideas.views.get_current_user")
    def test_student_can_publish_an_idea_without_media(
        self, get_user, save_media, create_idea,
    ):
        user = {
            "id": str(ObjectId()),
            "role": "student",
            "full_name": "Student Example",
        }
        get_user.return_value = user
        session = self.client.session
        session["lpu_user_id"] = user["id"]
        session["lpu_user_role"] = "student"
        session.save()

        response = self.client.post("/ideas/", {
            "title": "More study spaces",
            "description": "Open unused rooms.",
            "category": "campus",
        })

        self.assertRedirects(response, "/ideas/", fetch_redirect_response=False)
        save_media.assert_called_once_with(None)
        create_idea.assert_called_once_with(
            user, "More study spaces", "Open unused rooms.", "campus",
            media=save_media.return_value,
        )

    @patch("ideas.views.services.create_idea")
    @patch("ideas.views.save_idea_media", return_value={
        "url": "https://res.cloudinary.com/test/idea.mp4",
        "public_id": "lpu_nexus/idea_media/idea-id",
        "media_type": "video",
    })
    @patch("ideas.views.get_current_user")
    def test_student_can_attach_media_when_publishing(
        self, get_user, save_media, create_idea,
    ):
        user = {
            "id": str(ObjectId()),
            "role": "student",
            "full_name": "Student Example",
        }
        get_user.return_value = user
        session = self.client.session
        session["lpu_user_id"] = user["id"]
        session["lpu_user_role"] = "student"
        session.save()

        response = self.client.post("/ideas/", {
            "title": "More study spaces",
            "description": "Open unused rooms.",
            "category": "campus",
            "media": SimpleUploadedFile("idea.mp4", b"video-data"),
        })

        self.assertRedirects(response, "/ideas/", fetch_redirect_response=False)
        self.assertEqual(save_media.call_args.args[0].name, "idea.mp4")
        create_idea.assert_called_once_with(
            user, "More study spaces", "Open unused rooms.", "campus",
            media=save_media.return_value,
        )

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


class IdeaReviewQueueViewTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["lpu_user_id"] = str(ObjectId())
        session["lpu_user_role"] = "admin"
        session.save()

    @patch("ideas.views.student_profiles")
    @patch("ideas.views.services.vote_totals")
    @patch("ideas.views.services.list_ideas")
    def test_admin_queue_shows_open_polls_and_ideas_ready_for_review(
        self, list_ideas, vote_totals, student_profiles,
    ):
        open_idea_id = ObjectId()
        review_idea_id = ObjectId()
        already_reviewed_id = ObjectId()
        list_ideas.return_value = [
            {
                "_id": open_idea_id,
                "author_id": ObjectId(),
                "author_name": "Student One",
                "author_email": "student1@example.edu",
                "title": "More study spaces",
                "description": "Open unused rooms for quiet study.",
                "status": "poll_open",
                "poll_ends_at": datetime(2026, 11, 2),
                "comments": [],
            },
            {
                "_id": review_idea_id,
                "author_id": ObjectId(),
                "author_name": "Student Two",
                "author_email": "student2@example.edu",
                "title": "Extend library hours",
                "description": "Keep the library open later.",
                "status": "pending_review",
                "comments": [],
            },
            {
                "_id": already_reviewed_id,
                "author_id": ObjectId(),
                "author_name": "Student Three",
                "author_email": "student3@example.edu",
                "title": "Previously reviewed idea",
                "description": "Already decided.",
                "status": "accepted",
                "comments": [],
            },
        ]
        vote_totals.return_value = {"support": 2, "against": 0, "total": 2}
        student_profiles.return_value.find_one.return_value = None

        response = self.client.get("/ideas/admin/review/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [idea["status"] for idea in response.context["ideas"]],
            ["poll_open", "pending_review"],
        )
        self.assertContains(response, "Student ideas and review queue")
        self.assertContains(response, "Poll in progress")
        self.assertContains(response, "Ready for review")
        self.assertNotContains(response, "Previously reviewed idea")
        student_profiles.return_value.find_one.assert_called()
        self.assertEqual(vote_totals.call_count, 2)
