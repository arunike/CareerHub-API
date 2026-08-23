from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Experience
from ..serializers import ExperienceSerializer


class ExperienceLogoUploadTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="logo-user@example.com",
            email="logo-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)
        self.experience = Experience.objects.create(
            user=self.user,
            title="Software Engineer Intern",
            company="CareerHub",
            is_current=False,
        )

    @patch("career.views.experiences.store_logo_file")
    def test_upload_logo_uses_storage_service_and_persists_url(self, mock_store_logo_file):
        mock_store_logo_file.return_value = "https://blob.vercel-storage.com/experience-logos/test.png"
        buffer = BytesIO()
        Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buffer, format="PNG")
        logo_file = SimpleUploadedFile(
            "logo.png",
            buffer.getvalue(),
            content_type="image/png",
        )

        response = self.client.post(
            f"/api/career/experiences/{self.experience.id}/upload-logo/",
            {"logo": logo_file},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.experience.refresh_from_db()
        self.assertEqual(self.experience.logo, mock_store_logo_file.return_value)
        self.assertEqual(response.data["logo"], mock_store_logo_file.return_value)
        mock_store_logo_file.assert_called_once()

    @patch("career.views.experiences.delete_logo_asset")
    def test_remove_logo_deletes_asset_and_clears_url(self, mock_delete_logo_asset):
        self.experience.logo = "https://blob.vercel-storage.com/experience-logos/test.png"
        self.experience.save(update_fields=["logo"])

        response = self.client.delete(
            f"/api/career/experiences/{self.experience.id}/remove-logo/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.experience.refresh_from_db()
        self.assertIsNone(self.experience.logo)
        self.assertIsNone(response.data["logo"])
        mock_delete_logo_asset.assert_called_once_with(
            "https://blob.vercel-storage.com/experience-logos/test.png"
        )

    def test_serializer_normalizes_legacy_media_path(self):
        self.experience.logo = "experience_logos/legacy-logo.png"
        serializer = ExperienceSerializer(self.experience)

        self.assertEqual(serializer.data["logo"], "/media/experience_logos/legacy-logo.png")
