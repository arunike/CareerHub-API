from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import Company, Document


class DocumentStorageFlowTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="document-user@example.com",
            email="document-user@example.com",
            password="StrongPassw0rd!",
        )
        self.client.force_authenticate(self.user)

    @staticmethod
    def _pdf_file(name="resume.pdf", content=b"%PDF-1.4 test document\n"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    @patch("career.views.documents.store_document_file")
    def test_create_document_uses_storage_service_and_returns_download_url(self, mock_store_document_file):
        mock_store_document_file.return_value = "blob:documents/user-1/root-1/v1/resume.pdf"

        response = self.client.post(
            "/api/career/documents/",
            {
                "title": "Resume",
                "document_type": "RESUME",
                "file": self._pdf_file(),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        document = Document.objects.get()
        self.assertEqual(document.file, "blob:documents/user-1/root-1/v1/resume.pdf")
        self.assertEqual(response.data["file_name"], "resume.pdf")
        self.assertEqual(
            response.data["file"],
            f"http://testserver/api/career/documents/{document.id}/download/",
        )
        mock_store_document_file.assert_called_once()

    @patch("career.views.documents.store_document_file")
    def test_add_version_marks_previous_version_not_current(self, mock_store_document_file):
        root_document = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v1/resume.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=True,
        )
        mock_store_document_file.return_value = "blob:documents/user-1/root-1/v2/resume-v2.pdf"

        response = self.client.post(
            f"/api/career/documents/{root_document.id}/add_version/",
            {
                "title": "Resume",
                "document_type": "RESUME",
                "file": self._pdf_file("resume-v2.pdf"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        root_document.refresh_from_db()
        new_version = Document.objects.get(id=response.data["id"])
        self.assertFalse(root_document.is_current)
        self.assertTrue(new_version.is_current)
        self.assertEqual(new_version.root_document_id, root_document.id)
        self.assertEqual(new_version.version_number, 2)
        self.assertEqual(response.data["file_name"], "resume-v2.pdf")

    @patch("career.views.documents.read_document_bytes")
    def test_download_streams_document_content(self, mock_read_document_bytes):
        mock_read_document_bytes.return_value = b"document-bytes"
        document = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v1/resume.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=True,
        )

        response = self.client.get(f"/api/career/documents/{document.id}/download/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), b"document-bytes")
        self.assertIn('filename="resume.pdf"', response["Content-Disposition"])
        self.assertEqual(response["Content-Length"], str(len(b"document-bytes")))

    @patch("career.signals.delete_document_asset")
    def test_delete_current_document_removes_entire_version_chain(self, mock_delete_document_asset):
        root_document = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v1/resume.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=False,
        )
        current_version = Document.objects.create(
            user=self.user,
            title="Resume",
            file="blob:documents/user-1/root-1/v2/resume-v2.pdf",
            document_type="RESUME",
            root_document=root_document,
            version_number=2,
            is_current=True,
        )

        response = self.client.delete(f"/api/career/documents/{current_version.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(mock_delete_document_asset.call_count, 2)

    @patch("career.signals.delete_document_asset")
    def test_delete_all_skips_locked_version_chains(self, mock_delete_document_asset):
        unlocked_root = Document.objects.create(
            user=self.user,
            title="Unlocked Resume",
            file="blob:documents/user-1/root-1/v1/unlocked.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=False,
        )
        Document.objects.create(
            user=self.user,
            title="Unlocked Resume",
            file="blob:documents/user-1/root-1/v2/unlocked-v2.pdf",
            document_type="RESUME",
            root_document=unlocked_root,
            version_number=2,
            is_current=True,
        )
        locked_root = Document.objects.create(
            user=self.user,
            title="Locked Resume",
            file="blob:documents/user-1/root-2/v1/locked.pdf",
            document_type="RESUME",
            version_number=1,
            is_current=False,
        )
        Document.objects.create(
            user=self.user,
            title="Locked Resume",
            file="blob:documents/user-1/root-2/v2/locked-v2.pdf",
            document_type="RESUME",
            root_document=locked_root,
            version_number=2,
            is_current=True,
            is_locked=True,
        )

        response = self.client.delete("/api/career/documents/delete_all/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        remaining_titles = set(Document.objects.values_list("title", flat=True))
        self.assertEqual(remaining_titles, {"Locked Resume"})
        self.assertEqual(mock_delete_document_asset.call_count, 2)

    def test_document_list_supports_server_side_pagination_and_filters(self):
        Company.objects.create(user=self.user, name="Unrelated Co")
        Document.objects.create(
            user=self.user,
            title="Backend Resume",
            file="blob:documents/user-1/root-1/v1/backend-resume.pdf",
            document_type="RESUME",
        )
        Document.objects.create(
            user=self.user,
            title="Frontend Resume",
            file="blob:documents/user-1/root-2/v1/frontend-resume.pdf",
            document_type="RESUME",
        )
        Document.objects.create(
            user=self.user,
            title="Cover Letter",
            file="blob:documents/user-1/root-3/v1/cover-letter.pdf",
            document_type="COVER_LETTER",
        )

        response = self.client.get(
            "/api/career/documents/",
            {
                "page": 1,
                "page_size": 1,
                "search": "resume",
                "document_type": "RESUME",
                "year": str(timezone.now().year),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["document_type"], "RESUME")
