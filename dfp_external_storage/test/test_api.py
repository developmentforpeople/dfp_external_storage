import unittest
from unittest.mock import Mock, patch, MagicMock
from frappe.tests.utils import FrappeTestCase
from ..api import (
    generate_presigned_url,
    create_file_record,
)
import frappe
from ..dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage import DFPExternalStorage

class TestPresignedURLGeneration(FrappeTestCase):
    def setUp(self):
        """Set up test storage document"""
        self.file_name = "test_file.pdf"
        self.file_path = "Record"
    
    def _create_storage(self, name="_Test Storage", enabled=True, allow_direct_upload=True):
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
    
    def tearDown(self):
        frappe.db.rollback()

    def test_generate_presigned_url_success(self):
        """Test successful presigned URL generation"""
        storage = self._create_storage()
        result = generate_presigned_url(
            storage.name, self.file_name, self.file_path
        )
        self.assertIn("put_url", result)
        self.assertIn("get_url", result)
        self.assertIn("s3_key", result)
        self.assertEqual(result["s3_key"], f"uploads/{self.file_path}/{self.file_name}")
    
    def test_generate_presigned_url_fails_when_not_enabled(self):
        """Test successful presigned URL generation"""
        storage = self._create_storage(enabled=False)
       
        with self.assertRaises(frappe.exceptions.ValidationError):
            generate_presigned_url(
            storage.name, self.file_name, self.file_path
            )
     
    def test_generate_presigned_url_fails_when_not_allow_direct_upload(self):
        """Test successful presigned URL generation"""
        storage = self._create_storage(allow_direct_upload=False)
       
        with self.assertRaises(frappe.exceptions.ValidationError):
            generate_presigned_url(
            storage.name, self.file_name, self.file_path
            )
