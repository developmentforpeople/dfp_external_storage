# Copyright (c) 2023, DFP and Contributors
# See license.txt

import inspect
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from minio import Minio
from minio.error import S3Error

from dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage import (
	DFPExternalStorageFile,
	DFPExternalStorageFileRenderer,
	MinioConnection,
	file as serve_external_file,
)


class TestDFPV16Compatibility(FrappeTestCase):
	def test_get_content_accepts_encodings(self):
		parameters = inspect.signature(DFPExternalStorageFile.get_content).parameters
		self.assertIn("encodings", parameters)

	def test_renderer_accepts_extensionless_file_names(self):
		renderer = DFPExternalStorageFileRenderer("/file/abc123/README")
		self.assertTrue(renderer.can_render())
		self.assertEqual(renderer.file_id_get(), "abc123")
		self.assertEqual(renderer.file_name_get(), "README")


@unittest.skipUnless(
	os.getenv("DFP_TEST_S3_ENDPOINT"),
	"DFP_TEST_S3_ENDPOINT is required for S3 lifecycle tests",
)
class TestDFPExternalStorageLifecycle(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.endpoint = os.environ["DFP_TEST_S3_ENDPOINT"]
		cls.access_key = os.environ["DFP_TEST_S3_ACCESS_KEY"]
		cls.secret_key = os.environ["DFP_TEST_S3_SECRET_KEY"]
		cls.secure = os.getenv("DFP_TEST_S3_SECURE", "0") == "1"
		cls.client = Minio(
			cls.endpoint,
			access_key=cls.access_key,
			secret_key=cls.secret_key,
			secure=cls.secure,
			region="us-east-1",
		)
		cls.run_id = uuid4().hex[:12]
		cls.bucket_names = [
			f"dfp-v16-a-{cls.run_id}",
			f"dfp-v16-b-{cls.run_id}",
		]
		for bucket_name in cls.bucket_names:
			cls.client.make_bucket(bucket_name)
		cls.storage_names = [cls._create_storage(bucket_name) for bucket_name in cls.bucket_names]
		cls.file_names = set()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for file_name in tuple(getattr(cls, "file_names", set())):
			if frappe.db.exists("File", file_name):
				frappe.get_doc("File", file_name).delete(ignore_permissions=True)
		frappe.db.commit()

		for storage_name in getattr(cls, "storage_names", []):
			if frappe.db.exists("DFP External Storage", storage_name):
				frappe.delete_doc("DFP External Storage", storage_name, force=True)
		frappe.db.commit()

		for bucket_name in getattr(cls, "bucket_names", []):
			for item in cls.client.list_objects(bucket_name, recursive=True):
				cls.client.remove_object(bucket_name, item.object_name)
			cls.client.remove_bucket(bucket_name)
		super().tearDownClass()

	@classmethod
	def _create_storage(cls, bucket_name):
		storage = frappe.get_doc({
			"doctype": "DFP External Storage",
			"enabled": 1,
			"title": f"Lifecycle {bucket_name}",
			"type": "S3 Compatible",
			"endpoint": cls.endpoint,
			"secure": cls.secure,
			"bucket_name": bucket_name,
			"region": "us-east-1",
			"access_key": cls.access_key,
			"secret_key": cls.secret_key,
			"presigned_urls": 0,
			"cache_files_smaller_than": 0,
		})
		storage.insert(ignore_permissions=True)
		return storage.name

	def _new_remote_file(self, content, *, is_private=0, storage_index=0, file_name="lifecycle.txt"):
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": is_private,
			"dfp_external_storage": self.storage_names[storage_index],
		})
		file_doc.insert(ignore_permissions=True)
		self.file_names.add(file_doc.name)
		frappe.db.commit()
		return frappe.get_doc("File", file_doc.name)

	def _delete_file(self, file_doc):
		file_doc.delete(ignore_permissions=True)
		self.file_names.discard(file_doc.name)
		frappe.db.commit()

	def _object_exists(self, bucket_name, key):
		try:
			self.client.stat_object(bucket_name, key)
			return True
		except S3Error as error:
			if error.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
				return False
			raise

	def test_upload_read_rename_privacy_and_delete(self):
		content = b"Frappe public lifecycle"
		file_doc = self._new_remote_file(content)
		key = file_doc.dfp_external_storage_s3_key

		self.assertTrue(self._object_exists(self.bucket_names[0], key))
		self.assertEqual(file_doc.get_content(encodings=[]), content)
		self.assertFalse(os.path.exists(frappe.get_site_path("public", "files", file_doc.file_name)))

		file_doc.file_name = "renamed-lifecycle.txt"
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()
		file_doc.reload()
		self.assertEqual(file_doc.file_url, f"/file/{file_doc.name}/renamed-lifecycle.txt")
		self.assertEqual(file_doc.get_content(encodings=[]), content)

		file_doc.is_private = 1
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()
		file_doc.reload()
		self.assertEqual(file_doc.is_private, 1)
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				serve_external_file(file_doc.name, file_doc.file_name)
			with self.assertRaises(frappe.PageDoesNotExistError):
				file_doc.get_content(encodings=[])
		finally:
			frappe.set_user("Administrator")

		self._delete_file(file_doc)
		self.assertFalse(self._object_exists(self.bucket_names[0], key))

	def test_amendment_style_copy_preserves_private_shared_object(self):
		content = b"Frappe private amendment"
		source = self._new_remote_file(content, is_private=1, file_name="amendment.txt")
		key = source.dfp_external_storage_s3_key

		copy_doc = frappe.get_doc({
			"doctype": "File",
			"file_url": source.file_url,
			"file_name": source.file_name,
			"attached_to_doctype": "ToDo",
			"attached_to_name": f"amended-{self.run_id}",
			"folder": "Home/Attachments",
			"is_private": 0,
		})
		copy_doc.insert(ignore_permissions=True)
		self.file_names.add(copy_doc.name)
		frappe.db.commit()
		copy_doc.reload()

		self.assertEqual(copy_doc.dfp_external_storage, source.dfp_external_storage)
		self.assertEqual(copy_doc.dfp_external_storage_s3_key, key)
		self.assertEqual(copy_doc.is_private, 1)
		self.assertEqual(copy_doc.file_url, f"/file/{copy_doc.name}/{copy_doc.file_name}")

		self._delete_file(source)
		self.assertTrue(self._object_exists(self.bucket_names[0], key))
		self.assertEqual(copy_doc.get_content(encodings=[]), content)
		self._delete_file(copy_doc)
		self.assertFalse(self._object_exists(self.bucket_names[0], key))

	def test_local_remote_move_and_return_to_local(self):
		content = b"Frappe storage relocation"
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "relocation.bin",
			"content": content,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		self.file_names.add(file_doc.name)
		frappe.db.commit()
		local_path = file_doc.get_full_path()
		self.assertTrue(os.path.exists(local_path))

		file_doc.dfp_external_storage = self.storage_names[0]
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()
		file_doc.reload()
		key = file_doc.dfp_external_storage_s3_key
		self.assertFalse(os.path.exists(local_path))
		self.assertTrue(self._object_exists(self.bucket_names[0], key))
		self.assertEqual(file_doc.get_content(encodings=[]), content)

		file_doc.dfp_external_storage = self.storage_names[1]
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()
		file_doc.reload()
		self.assertFalse(self._object_exists(self.bucket_names[0], key))
		self.assertTrue(self._object_exists(self.bucket_names[1], key))
		self.assertEqual(file_doc.get_content(encodings=[]), content)

		file_doc.dfp_external_storage = ""
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()
		file_doc.reload()
		self.assertFalse(file_doc.dfp_external_storage_s3_key)
		self.assertFalse(self._object_exists(self.bucket_names[1], key))
		self.assertTrue(os.path.exists(file_doc.get_full_path()))
		self.assertEqual(file_doc.get_content(encodings=[]), content)
		self._delete_file(file_doc)

	def test_s3_write_failure_does_not_fall_back_to_local(self):
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "fail-closed.txt",
			"content": b"must not fall back",
			"is_private": 1,
			"dfp_external_storage": self.storage_names[0],
		})
		with patch.object(MinioConnection, "put_object", side_effect=OSError("test S3 outage")):
			with self.assertRaises(frappe.ValidationError):
				file_doc.insert(ignore_permissions=True)
		local_path = file_doc.get_full_path()
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("File", file_doc.name))
		self.assertFalse(os.path.exists(local_path))

	def test_insert_rollback_removes_local_and_remote_bytes(self):
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "rollback.txt",
			"content": b"rollback lifecycle",
			"is_private": 1,
			"dfp_external_storage": self.storage_names[0],
		}).insert(ignore_permissions=True)
		key = file_doc.dfp_external_storage_s3_key
		local_path = frappe.get_site_path("private", "files", file_doc.file_name)
		self.assertTrue(self._object_exists(self.bucket_names[0], key))
		self.assertTrue(os.path.exists(local_path))

		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("File", file_doc.name))
		self.assertFalse(self._object_exists(self.bucket_names[0], key))
		self.assertFalse(os.path.exists(local_path))
