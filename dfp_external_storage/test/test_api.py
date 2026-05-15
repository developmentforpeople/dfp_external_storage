from unittest.mock import MagicMock
from frappe.tests.utils import FrappeTestCase
from ..api import (
    generate_presigned_url,
    create_file_record,
)
import frappe
from frappe.utils import now
from ..dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage import DFPExternalStorage

class TestPresignedURLGeneration(FrappeTestCase):
    def setUp(self):
        """Set up test storage document"""
        self.file_name = "test_file.pdf"
        self.file_path = "Record"
        self.storage = _create_storage(name="_Test Storage normal")


    def tearDown(self):
        frappe.db.rollback()

    def test_generate_presigned_url_success(self):
        """Test successful presigned URL generation"""
        result = generate_presigned_url(
            self.file_name, self.file_path
        )
        self.assertIn("put_url", result)
        self.assertIn("get_url", result)
        self.assertIn("s3_key", result)
        self.assertEqual(result["s3_key"], f"uploads/{self.file_path}/{self.file_name}")

    def test_generate_presigned_url_fails_when_not_enabled(self):
        """Test successful presigned URL generation"""
        self.storage.enabled = False
        self.storage.save()
        with self.assertRaises(frappe.exceptions.ValidationError):
            generate_presigned_url(
            self.file_name, self.file_path
            )

    def test_generate_presigned_url_fails_when_not_allow_direct_upload(self):
        """Test successful presigned URL generation"""
        self.storage.allow_direct_upload = False
        self.storage.save()

        with self.assertRaises(frappe.exceptions.ValidationError):
            generate_presigned_url(
            self.file_name, self.file_path
            )

    def test_create_file_record_success(self):
        """Test successful file record creation"""
        self.storage.allow_direct_upload = True
        self.storage.save()
        file_data = {
            "file_name": "test_document.pdf",
            "file_size": 1024000,
            "s3_key": "uploads/Record/test_document.pdf",
            "attached_to_doctype": self.storage.doctype,
            "attached_to_name": self.storage.name,
            "attached_to_field": "attachment",
            "folder": "Home",
        }
        result = create_file_record(**file_data)
        self.assertIn("file_doc", result)
        self.assertIn("file_url", result)
        doc_name = getattr(result["file_doc"],'name', "Not A FIle")

        self.assertTrue(frappe.db.exists("File", doc_name), f"File {doc_name} wasn't created")

    def test_can_not_create_more_than_one_direct_upload_bucket(self):
        """Ensure only one bucket can have allow_direct_upload enabled"""
        with self.assertRaises(frappe.exceptions.ValidationError) as cx:
            _create_storage("_Test Storage Enabled two", allow_direct_upload=True)
        self.assertEqual(str(cx.exception), "You can't have more than one directupload bucket")

    def test_can_create_more_than_one_bucket_when_direct_upload_is_disabled(self):
        """Ensure bucket can be created when direct_upload isn't enabled"""
        for i in range(2):
            try:
                _create_storage(f"_Test Storage Enabled {i}", allow_direct_upload=False)
            except frappe.exceptions.ValidationError:
                self.fail()
    def test_can_create_more_than_one_bucket_when_direct_upload_is_disabled_or_doc_is_not_enabled(self):
        """Ensure bucket can be created when direct_upload or doc isn't enabled"""
        for i in range(2):
            try:
                _create_storage(f"_Test Storage Enabled {i}", allow_direct_upload=True, enabled=False)
            except frappe.exceptions.ValidationError:
                self.fail("Couldn't create more than one disabled bucket")


def _create_storage(name="_Test Storage", enabled=True, allow_direct_upload=True):
    if doc := frappe.db.exists("DFP External Storage", name):
        return frappe.get_doc("DFP External Storage", doc)
    else:
        doc = frappe.new_doc("DFP External Storage")
        doc.name = name
        doc.flags.name_set = True
        doc.title = name
        doc.bucket_name = "test-bucket"
        doc.endpoint = "test.bucket.endpoint"
        doc.access_key = "access_key"
        doc.secret_key = "secret_key"
        doc.enabled = enabled
        doc.allow_direct_upload = allow_direct_upload
        doc.validate_bucket = MagicMock()
        doc.insert()
        doc.client = MagicMock()
        return doc
