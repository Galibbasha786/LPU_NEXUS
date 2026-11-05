from django.test import TestCase

# Create your tests here.
from unittest.mock import patch

from bson import ObjectId
from django.test import TestCase


class IncidentMediaAccessTests(TestCase):
    def setUp(self):
        self.owner_id = ObjectId()
        self.other_user_id = ObjectId()
        self.incident_id = str(ObjectId())
        session = self.client.session
        session['lpu_user_id'] = str(self.owner_id)
        session['lpu_user_role'] = 'student'
        session['lpu_id_verification_status'] = 'verified'
        session.save()

    @patch(
        'crisis.views.incident_media_download_url',
        return_value='https://cloudinary.example/temporary',
    )
    @patch('crisis.views.services.get_incident')
    @patch('crisis.views.get_current_user')
    def test_reporter_gets_short_lived_cloudinary_media_url(
        self, get_current_user, get_incident, download_url,
    ):
        get_current_user.return_value = {'id': str(self.owner_id)}
        get_incident.return_value = {
            'reported_by': self.owner_id,
            'media_path': {
                'public_id': 'lpu_nexus/incidents/images/evidence',
                'resource_type': 'image', 'format': 'png',
                'delivery_type': 'authenticated',
            },
        }

        response = self.client.get(
            f'/crisis/incident/{self.incident_id}/media/',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://cloudinary.example/temporary')
        download_url.assert_called_once_with(get_incident.return_value['media_path'])

    @patch('crisis.views.incident_media_download_url')
    @patch('crisis.views.services.get_incident')
    @patch('crisis.views.get_current_user')
    def test_other_students_cannot_access_report_media(
        self, get_current_user, get_incident, download_url,
    ):
        session = self.client.session
        session['lpu_user_id'] = str(self.other_user_id)
        session.save()
        get_current_user.return_value = {'id': str(self.other_user_id)}
        get_incident.return_value = {
            'reported_by': self.owner_id,
            'media_path': {'public_id': 'private-evidence', 'format': 'png'},
        }

        response = self.client.get(
            f'/crisis/incident/{self.incident_id}/media/',
        )

        self.assertEqual(response.status_code, 403)
        download_url.assert_not_called()
