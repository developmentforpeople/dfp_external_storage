
import os
import re
import io
import mimetypes
import typing as t
from datetime import timedelta
from urllib.parse import unquote
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file
from functools import cached_property
from minio import Minio
import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.core.doctype.file.file import URL_PREFIXES
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password


DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX = "external_storage_public_file:"

# http://[host:port]/<file>/[File:name]/[File:file_name]
# http://myhost.localhost:8000/file/c7baa5b2ff/my-image.png
DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD = "file"


DFP_EXTERNAL_STORAGE_CONNECTION_FIELDS = [
	"type", "endpoint", "secure", "bucket_name", "region", "access_key", "secret_key"]
DFP_EXTERNAL_STORAGE_CRITICAL_FIELDS = [
	"type", "endpoint", "secure", "bucket_name", "region", "access_key", "secret_key", "folders"]


def _remove_local_file(local_file, file_url=None):
	try:
		if file_url and frappe.db.exists("File", {"file_url": file_url}):
			return
		if local_file and os.path.exists(local_file):
			os.remove(local_file)
	except Exception:
		frappe.log_error(
			title="DFP External Storage local-file cleanup failed",
			message=f"Could not remove {local_file}",
		)


def _remove_remote_object(storage_doc, key, file_name):
	try:
		storage_doc.client.remove_object(
			bucket_name=storage_doc.bucket_name,
			object_name=key,
		)
	except Exception:
		frappe.log_error(
			title="DFP External Storage object cleanup failed",
			message=f"Could not remove {key} for {file_name}",
		)


def _remote_object_has_other_references(storage_name, key, file_name):
	return bool(frappe.get_all(
		"File",
		filters={
			"dfp_external_storage": storage_name,
			"dfp_external_storage_s3_key": key,
			"name": ["!=", file_name],
		},
		limit=1,
	))


class S3FileProxy:

	def __init__(self, readFn, object_size):
		self.readFn = readFn
		self.object_size = object_size
		# self.size = object_size # DEPRECATED! size is deprecated tell to Khoran, must be replaced by object_size
		self.offset = 0

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		pass

	def seek(self, offset, whence=0):
		if whence == io.SEEK_SET:
			self.offset = offset
		elif whence == io.SEEK_CUR:
			self.offset = self.offset + offset
		elif whence == io.SEEK_END:
			self.offset = self.object_size + offset

	def seekable(self):
		return True

	def tell(self):
		return self.offset

	def read(self, size=0):
		content = self.readFn(self.offset, size)
		self.offset = self.offset + len(content)
		return content


class DFPExternalStorage(Document):

	def validate(self):
		def has_changed(doc_a:Document, doc_b:Document, fields:list):
			for param in fields:
				value_a = getattr(doc_a, param)
				value_b = getattr(doc_b, param)
				if type(value_a) == list:
					if not [i.name for i in value_a] == [i.name for i in value_b]:
						return True
				elif value_a != value_b:
					return True
			return False

		if self.stream_buffer_size < 8192:
			frappe.msgprint(_("Stream buffer size must be at least of 8192 bytes."))
			self.stream_buffer_size = 8192

		# Recheck S3 connection if needed
		previous = self.get_doc_before_save()
		if previous:
			if self.files_within and has_changed(self, previous, DFP_EXTERNAL_STORAGE_CRITICAL_FIELDS):
				frappe.msgprint(_("There are {} files using this bucket. The field you just updated is critical, be careful!").format(self.files_within))
		if not previous or has_changed(self, previous, DFP_EXTERNAL_STORAGE_CONNECTION_FIELDS):
			self.validate_bucket()

	def on_trash(self):
		if self.files_within:
			frappe.throw(_("Can not be deleted. There are {} files using this bucket.")
				.format(self.files_within))

	@cached_property
	def setting_stream_buffer_size(self):
		return self.stream_buffer_size if self.stream_buffer_size >= 8192 else 8192

	@cached_property
	def setting_cache_files_smaller_than(self):
		"Default: 5Mb"
		return self.cache_files_smaller_than if self.cache_files_smaller_than >= 0 else 5000000

	@cached_property
	def setting_cache_expiration_secs(self):
		"Default: 1 day"
		return self.cache_expiration_secs if self.cache_expiration_secs >= 0 else 60 * 60 * 24

	@cached_property
	def setting_presigned_url_expiration(self):
		"Default: 3 hours"
		return self.presigned_url_expiration if self.presigned_url_expiration > 0 else 60 * 60 * 3

	@cached_property
	def files_within(self):
		return frappe.db.count("File", filters={"dfp_external_storage": self.name})

	def validate_bucket(self):
		if not self.client:
			frappe.throw(_("S3 endpoint and credentials are required."))
		self.client.validate_bucket(self.bucket_name)

	@cached_property
	def client(self):
		# Allow access_key/secret_key to be optional: if not provided in this DocType,
		# fallback to environment variables.
		if self.endpoint and self.region:
			try:
				# Resolve access key
				access_key = self.access_key or \
					os.getenv("AWS_ACCESS_KEY_ID") or \
					os.getenv("MINIO_ACCESS_KEY") or \
					os.getenv("MINIO_ROOT_USER")

				# Resolve secret key
				if self.is_new() and self.secret_key:
					key_secret = self.secret_key
				elif self.secret_key:
					key_secret = get_decrypted_password("DFP External Storage", self.name, "secret_key") if self.name else None
				else:
					key_secret = None

				secret_key = key_secret or \
					os.getenv("AWS_SECRET_ACCESS_KEY") or \
					os.getenv("MINIO_SECRET_KEY") or \
					os.getenv("MINIO_ROOT_PASSWORD")

				if access_key and secret_key:
					return MinioConnection(
						endpoint=self.endpoint,
						access_key=access_key,
						secret_key=secret_key,
						region=self.region,
						secure=self.secure,
					)
			except Exception:
				pass

	def remote_files_list(self):
		return self.client.list_objects(self.bucket_name, recursive=True)


class MinioConnection:
	def __init__(self, endpoint:str, access_key:str, secret_key:str, region:str, secure:bool):
		self.client = Minio(
			endpoint=endpoint,
			access_key=access_key,
			secret_key=secret_key,
			region=region,
			secure=secure,
		)

	def validate_bucket(self, bucket_name:str):
		try:
			bucket_exists = self.client.bucket_exists(bucket_name)
		except Exception as e:
			frappe.throw(_("Error when looking for bucket: {0}").format(str(e)))
		if not bucket_exists:
			frappe.throw(_("Bucket not found"))
		frappe.msgprint(_("Bucket is accessible."), indicator="green", alert=True)
		return True

	def remove_object(self, bucket_name:str, object_name:str):
		"""
		Minio params:
		:param bucket_name: Name of the bucket.
		:param object_name: Object name in the bucket.
		:param version_id: Version ID of the object.
		"""
		return self.client.remove_object(bucket_name=bucket_name, object_name=object_name)

	def stat_object(self, bucket_name:str, object_name:str):
		"""
		Minio params:
		:param bucket_name: Name of the bucket.
		:param object_name: Object name in the bucket.
		:param version_id: Version ID of the object.
		"""
		return self.client.stat_object(bucket_name=bucket_name, object_name=object_name)

	def get_object(self, bucket_name:str, object_name:str, offset:int=0, length:int=0):
		"""
		Minio params:
		:param bucket_name: Name of the bucket.
		:param object_name: Object name in the bucket.
		:param offset: Start byte position of object data.
		:param length: Number of bytes of object data from offset.
		:param request_headers: Any additional headers to be added with GET request.
		:param ssec: Server-side encryption customer key.
		:param version_id: Version-ID of the object.
		:param extra_query_params: Extra query parameters for advanced usage.
		:return: :class:`urllib3.response.HTTPResponse` object.
		"""
		return self.client.get_object(bucket_name=bucket_name, object_name=object_name, offset=offset, length=length)

	def fget_object(self, bucket_name:str, object_name:str,file_path:str):
		"""
		Minio params:
		:param bucket_name: Name of the bucket.
		:param object_name: Object name in the bucket.
		:param file_path: Name of file to download
		:param request_headers: Any additional headers to be added with GET request.
		:param ssec: Server-side encryption customer key.
		:param version_id: Version-ID of the object.
		:param extra_query_params: Extra query parameters for advanced usage.
		:param temp_file_path: Path to a temporary file
		:return: :class:`urllib3.response.HTTPResponse` object.
		"""
		return self.client.fget_object(bucket_name=bucket_name, object_name=object_name,file_path=file_path)

	def presigned_get_object(self, bucket_name:str, object_name:str, expires:int=timedelta(hours=3)):
		"""
		Minio params:
		Get presigned URL of an object to download its data with expiry time
		and custom request parameters.

		:param bucket_name: Name of the bucket.
		:param object_name: Object name in the bucket.
		:param expires: Expiry in seconds; defaults to 7 days.
		:param response_headers: Optional response_headers argument to
								specify response fields like date, size,
								type of file, data about server, etc.
		:param request_date: Optional request_date argument to
							specify a different request date. Default is
							current date.
		:param version_id: Version ID of the object.
		:param extra_query_params: Extra query parameters for advanced usage.
		:return: URL string.

		Example::
			# Get presigned URL string to download 'my-object' in
			# 'my-bucket' with default expiry (i.e. 7 days).
			url = client.presigned_get_object("my-bucket", "my-object")
			print(url)

			# Get presigned URL string to download 'my-object' in
			# 'my-bucket' with two hours expiry.
			url = client.presigned_get_object("my-bucket", "my-object", expires=timedelta(hours=2))
			print(url)
		"""
		if type(expires) == int:
			expires = timedelta(seconds=expires)
		return self.client.presigned_get_object(bucket_name=bucket_name, object_name=object_name, expires=expires)

	def put_object(self, bucket_name, object_name, data, metadata=None, length=-1):
		"""
		Minio params:
		:param bucket_name: Name of the bucket.
		:param object_name: Object name in the bucket.
		:param data: An object having callable read() returning bytes object.
		:param length: Data size; -1 for unknown size and set valid part_size.
		:param content_type: Content type of the object.
		:param metadata: Any additional metadata to be uploaded along
			with your PUT request.
		:param sse: Server-side encryption.
		:param progress: A progress object;
		:param part_size: Multipart part size.
		:param num_parallel_uploads: Number of parallel uploads.
		:param tags: :class:`Tags` for the object.
		:param retention: :class:`Retention` configuration object.
		:param legal_hold: Flag to set legal hold for the object.
		"""
		return self.client.put_object(bucket_name=bucket_name,
 object_name=object_name, data=data, metadata=metadata, length=length)

	def list_objects(self, bucket_name:str, recursive=True):
		"""
		Minio params:
		:param bucket_name: Name of the bucket.
		# :param prefix: Object name starts with prefix.
		# :param recursive: List recursively than directory structure emulation.
		# :param start_after: List objects after this key name.
		# :param include_user_meta: MinIO specific flag to control to include
		# 						user metadata.
		# :param include_version: Flag to control whether include object
		# 						versions.
		# :param use_api_v1: Flag to control to use ListObjectV1 S3 API or not.
		# :param use_url_encoding_type: Flag to control whether URL encoding type
		# 							to be used or not.
		:return: Iterator of :class:`Object <Object>`.
		"""
		return self.client.list_objects(bucket_name=bucket_name, recursive=recursive)


class DFPExternalStorageFile(File):
	def __init__(self, *args, **kwargs):
		super(DFPExternalStorageFile, self).__init__(*args, **kwargs)

	def before_validate(self):
		self.dfp_file_url_is_s3_location_check_if_s3_data_is_not_defined()

	@property
	def is_remote_file(self):
		return True if self.dfp_external_storage_s3_key else super(DFPExternalStorageFile, self).is_remote_file

	@property
	def dfp_external_storage_doc(self):
		dfp_ext_strg_doc = None
		# 1. Use defined
		if self.dfp_external_storage:
			try:
				dfp_ext_strg_doc = frappe.get_doc("DFP External Storage", self.dfp_external_storage)
			except:
				pass
		if not dfp_ext_strg_doc:
			# 2. Specific folder connection
			dfp_ext_strg_name = frappe.db.get_value(
				"DFP External Storage by Folder",
				fieldname="parent",
				filters={ "folder": self.folder }
			)
			# 3. Default connection (Home folder)
			if not dfp_ext_strg_name:
				dfp_ext_strg_name = frappe.db.get_value(
					"DFP External Storage by Folder",
					fieldname="parent",
					filters={ "folder": "Home" }
				)
			if dfp_ext_strg_name:
				dfp_ext_strg_doc = frappe.get_doc("DFP External Storage", dfp_ext_strg_name)
		return dfp_ext_strg_doc

	def dfp_is_s3_remote_file(self):
		if self.dfp_external_storage_s3_key and self.dfp_external_storage_doc:
			return True

	def dfp_is_cacheable(self):
		return not self.is_private and self.dfp_external_storage_doc.setting_cache_files_smaller_than and self.dfp_file_size != 0 and self.dfp_file_size < self.dfp_external_storage_doc.setting_cache_files_smaller_than

	@cached_property
	def dfp_file_size(self) -> int:
		if self.dfp_is_s3_remote_file() and self.dfp_external_storage_doc.remote_size_enabled:
			try:
				object_info = self.dfp_external_storage_doc.client.stat_object(
					bucket_name=self.dfp_external_storage_doc.bucket_name,
					object_name=self.dfp_external_storage_s3_key)
				return object_info.size
			except:
				frappe.log_error(title=f"Error getting remote file size: {self.dfp_external_storage_s3_key}")
		return self.file_size

	@property
	def dfp_external_storage_client(self):
		if self.dfp_external_storage_doc:
			return self.dfp_external_storage_doc.client

	def dfp_external_storage_ignored_doctypes(self):
		"Do not apply for files attached to specified doctypes"
		if self.attached_to_doctype and self.dfp_external_storage_doc and self.attached_to_doctype in [i.doctype_to_ignore for i in self.dfp_external_storage_doc.doctypes_ignored]:
			frappe.msgprint(_("""This doctype does not allow remote files attached to it. Check "DFP External Storage" advanced settings for more details."""))
			return True

	def dfp_external_storage_upload_file(self, local_file=None):
		"""
		Critical fields: "dfp_external_storage_s3_key", "dfp_external_storage" and "file_url"
		:param local_file: if given, file path for reading the content. If not given, the content field of this File is used
		"""
		if self.dfp_file_url_is_s3_location_check_if_s3_data_is_not_defined():
			return False
		if self.dfp_external_storage_ignored_doctypes():
			self.dfp_external_storage = ""
			return False
		if not self.dfp_external_storage_doc or not self.dfp_external_storage_doc.enabled:
			return False
		if self.is_folder:
			return False
		if self.dfp_external_storage_s3_key:
			# File already on S3
			return False
		if self.file_url and self.file_url.startswith(URL_PREFIXES):
			# frappe.throw(_("Not implemented save http(s)://file(s) to local."))
			raise NotImplementedError("http(s)://file(s) not ready to be saved to local or external storage(s).")

		original_file_url = self.file_url
		storage_doc = self.dfp_external_storage_doc

		# Define S3 key
		# key = f"{frappe.local.site}/{self.file_name}" # << Before 2024.03.03
		base, extension = os.path.splitext(self.file_name)
		key = f"{frappe.local.site}/{base}-{self.name}{extension}"

		if not local_file:
			local_file = self.get_full_path()

		try:
			if not os.path.exists(local_file):
				frappe.throw(_("Local file not found"))
			with open(local_file, "rb") as file_handle:
				storage_doc.client.put_object(
					bucket_name=storage_doc.bucket_name,
					object_name=key,
					data=file_handle,
					length=os.path.getsize(local_file),
				)

			self.dfp_external_storage_s3_key = key
			self.dfp_external_storage = storage_doc.name
			self.file_url = self._remote_file_local_path_get()

			frappe.db.after_rollback.add(
				lambda: _remove_remote_object(storage_doc, key, self.file_name)
			)
			if not self.get_doc_before_save():
				frappe.db.after_rollback.add(lambda: _remove_local_file(local_file))
			frappe.db.after_commit.add(
				lambda: _remove_local_file(local_file, original_file_url)
			)
		except Exception as e:
			error_msg = _("Error saving file in remote folder: {}").format(str(e))
			frappe.log_error(f"{error_msg}: {self.file_name}", message=e)
			frappe.throw(error_msg)

	def dfp_external_storage_delete_file(self):
		if not self.dfp_is_s3_remote_file():
			return
		if _remote_object_has_other_references(
			self.dfp_external_storage,
			self.dfp_external_storage_s3_key,
			self.name,
		):
			return
		error_msg = _("Error deleting file in remote folder.")
		if not self.dfp_external_storage_doc:
			frappe.throw(error_msg)
		if not self.dfp_external_storage_doc.enabled:
			error_extra = _("Write disabled for connection <strong>{}</strong>").format(self.dfp_external_storage_doc.title)
			frappe.throw(f"{error_msg} {error_extra}")
		storage_doc = self.dfp_external_storage_doc
		key = self.dfp_external_storage_s3_key
		frappe.db.after_commit.add(
			lambda: _remove_remote_object(storage_doc, key, self.file_name)
		)

	def dfp_external_storage_download_to_file(self, local_file):
		"""
		Stream file from S3 directly to local_file. This avoids reading the whole file into memory at any point
		:param local_file: path to a local file to stream content to
		"""
		if not self.dfp_is_s3_remote_file():
			# frappe.msgprint(_("S3 key not found: ") + self.file_name,
			# 	indicator="red", title=_("Error processing File"), alert=True)
			return
		try:
			key = self.dfp_external_storage_s3_key

			self.dfp_external_storage_client.fget_object(
				bucket_name=self.dfp_external_storage_doc.bucket_name,
				object_name=key,
				file_path=local_file)
		except Exception as e:
			error_msg = _("Error downloading to file from remote folder. Check Error Log for more information.")
			frappe.log_error(title=f"{error_msg}: {self.file_name}", message=e)
			frappe.throw(error_msg)

	def dfp_external_storage_file_proxy(self):
		"""
		Get a read-only context manager file-like object that will read requested bytes directly from S3. This allows you to avoid downloading the whole file when only parts or chunks of it will be read from.
		"""
		if not self.dfp_is_s3_remote_file():
			return

		def read_chunks(offset=0, size=0):
			with self.dfp_external_storage_client.get_object(
				bucket_name=self.dfp_external_storage_doc.bucket_name,
				object_name=self.dfp_external_storage_s3_key,
				offset=offset,
				length=size) as response:
				content = response.read()
			return content

		return S3FileProxy(readFn=read_chunks, object_size=self.dfp_file_size)

	def dfp_external_storage_download_file(self) -> bytes:
		content = b""
		if not self.dfp_is_s3_remote_file():
			return content
		try:
			with self.dfp_external_storage_client.get_object(
				bucket_name=self.dfp_external_storage_doc.bucket_name,
				object_name=self.dfp_external_storage_s3_key) as response:
				content = response.read()
			return content
		except:
			error_msg = _("Error downloading file from remote folder")
			frappe.log_error(title=f"{error_msg}: {self.file_name}")
			frappe.throw(error_msg)
		return content

	def dfp_external_storage_stream_file(self) -> t.Iterable[bytes]:
		return wrap_file(environ=frappe.local.request.environ,
			file=self.dfp_external_storage_file_proxy(),
				buffer_size=self.dfp_external_storage_doc.setting_stream_buffer_size)

	def download_to_local_and_remove_remote(self, target_doc=None):
		"""Stage a remote file locally and remove S3 only after the DB commit."""
		target_doc = target_doc or self
		storage_doc = self.dfp_external_storage_doc
		storage_name = self.dfp_external_storage
		key = self.dfp_external_storage_s3_key
		try:
			with storage_doc.client.get_object(
				bucket_name=storage_doc.bucket_name,
				object_name=key,
			) as response:
				content = response.read()

			target_doc.dfp_external_storage_s3_key = ""
			target_doc.dfp_external_storage = ""
			target_doc.file_url = ""
			target_doc.content = content
			target_doc._content = content
			target_doc.save_file_on_filesystem()
			local_file = target_doc.get_full_path()

			frappe.db.after_rollback.add(lambda: _remove_local_file(local_file))
			if not _remote_object_has_other_references(storage_name, key, self.name):
				frappe.db.after_commit.add(
					lambda: _remove_remote_object(storage_doc, key, self.file_name)
				)
		except Exception:
			error_msg = _("Error downloading and removing file from remote folder.")
			frappe.log_error(title=f"{error_msg}: {self.file_name}")
			frappe.throw(error_msg)

	def validate_file_on_disk(self):
		self.dfp_file_url_is_s3_location_check_if_s3_data_is_not_defined()
		# The storage field is temporarily blank while moving an S3 object back
		# to local storage. Its persisted key remains authoritative until the
		# before-save lifecycle hook completes that move.
		return True if self.dfp_external_storage_s3_key else super(DFPExternalStorageFile, self).validate_file_on_disk()

	def exists_on_disk(self):
		return False if self.dfp_external_storage_s3_key else super(DFPExternalStorageFile, self).exists_on_disk()

	@frappe.whitelist()
	def optimize_file(self):
		if self.dfp_is_s3_remote_file():
			raise NotImplementedError("Only local image files can be optimized")
		super(DFPExternalStorageFile, self).optimize_file()

	def _remote_file_local_path_get(self):
		return f"/{DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD}/{self.name}/{self.file_name}"

	def dfp_file_url_is_s3_location_check_if_s3_data_is_not_defined(self):
		"""
		Set `dfp_external_storage_s3_key` if `file_url` exists and can be rendered.
		Sometimes, when a file is copied (for example, when amending a sales invoice), we have the `file_url` but not the `key` (refer to the method `copy_attachments_from_amended_from` in `document.py`).
		"""
		if not self.file_url or self.dfp_external_storage_s3_key:
			return False

		renderer = DFPExternalStorageFileRenderer(path=self.file_url)
		if not renderer.can_render():
			return False
		source_name = renderer.file_id_get()
		if not source_name or source_name == self.name:
			return False

		try:
			source = frappe.get_doc("File", source_name)
		except frappe.DoesNotExistError:
			return False
		if (
			not source.dfp_is_s3_remote_file()
			or source.file_name != renderer.file_name_get()
		):
			return False

		self.dfp_external_storage = source.dfp_external_storage
		self.dfp_external_storage_s3_key = source.dfp_external_storage_s3_key
		self.content_hash = source.content_hash
		self.file_size = source.file_size
		self.is_private = source.is_private
		self.file_url = self._remote_file_local_path_get()
		self.flags.ignore_duplicate_entry_error = True
		return True

	def get_content(self, encodings=None) -> bytes | str:
		self.dfp_file_url_is_s3_location_check_if_s3_data_is_not_defined()
		if not self.dfp_is_s3_remote_file():
			return super(DFPExternalStorageFile, self).get_content(encodings=encodings)
		try:
			if not self.is_downloadable():
				raise frappe.PermissionError()
			return self.dfp_external_storage_download_file()
		except Exception:
			raise frappe.PageDoesNotExistError() from None

	@cached_property
	def dfp_mime_type_guess_by_file_name(self):
		content_type, _= mimetypes.guess_type(self.file_name)
		if content_type:
			return content_type

	def dfp_presigned_url_get(self):
		if not self.dfp_is_s3_remote_file() or not self.dfp_external_storage_doc.presigned_urls:
			return
		if self.dfp_external_storage_doc.presigned_mimetypes_starting and self.dfp_mime_type_guess_by_file_name:
			# get list exploding by new line, removing empty lines and cleaning starting and ending spaces
			presigned_mimetypes_starting = [i.strip() for i in self.dfp_external_storage_doc.presigned_mimetypes_starting.split("\n") if i.strip()]
			if not any(self.dfp_mime_type_guess_by_file_name.startswith(i) for i in presigned_mimetypes_starting):
				return
		return self.dfp_external_storage_client.presigned_get_object(bucket_name=self.dfp_external_storage_doc.bucket_name, object_name=self.dfp_external_storage_s3_key, expires=self.dfp_external_storage_doc.setting_presigned_url_expiration)


def hook_file_before_save(doc, method):
	"""
	This method is called before the document is saved to DB (insert or update row)
	Critical fields: dfp_external_storage_s3_key, dfp_external_storage and file_url
	"""
	previous = doc.get_doc_before_save()

	if not previous:
		doc.dfp_external_storage_upload_file()
	elif not doc.dfp_external_storage_s3_key and doc.dfp_external_storage and not previous.dfp_external_storage:
		doc.dfp_external_storage_upload_file()
	elif previous.dfp_external_storage and not doc.dfp_external_storage:
		previous.download_to_local_and_remove_remote(target_doc=doc)
	elif previous.dfp_external_storage and doc.dfp_external_storage and previous.dfp_external_storage != doc.dfp_external_storage:
		old_storage = previous.dfp_external_storage_doc
		new_storage = doc.dfp_external_storage_doc
		key = previous.dfp_external_storage_s3_key
		try:
			if not new_storage or not new_storage.enabled:
				frappe.throw(_("Destination external storage is not write enabled."))

			same_location = (
				old_storage.endpoint == new_storage.endpoint
				and old_storage.bucket_name == new_storage.bucket_name
				and old_storage.secure == new_storage.secure
			)
			if not same_location:
				with previous.dfp_external_storage_file_proxy() as response:
					new_storage.client.put_object(
						bucket_name=new_storage.bucket_name,
						object_name=doc.dfp_external_storage_s3_key,
						data=response,
						length=response.object_size,
					)
				frappe.db.after_rollback.add(
					lambda: _remove_remote_object(new_storage, key, doc.file_name)
				)
				if not _remote_object_has_other_references(previous.dfp_external_storage, key, previous.name):
					frappe.db.after_commit.add(
						lambda: _remove_remote_object(old_storage, key, previous.file_name)
					)
		except Exception:
			error_msg = _("Error putting file from one remote to another.")
			frappe.log_error(f"{error_msg}: {doc.file_name}")
			frappe.throw(error_msg)

	if bool(doc.dfp_external_storage) != bool(doc.dfp_external_storage_s3_key):
		frappe.throw(_("External storage and S3 key must either both be set or both be empty."))

	if doc.dfp_external_storage_s3_key:
		cache_key = f"{DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX}{doc.name}"
		frappe.cache().delete_value(cache_key)
		doc.file_url = doc._remote_file_local_path_get()


def hook_file_on_update(doc, method):
	"""DEPRECATED! Remove method after 2025.01.01 ("/dfp_external_storage/dfp_external_storage/hooks.py" too)"""
	pass


def hook_delete_file_data_content(doc, only_thumbnail=False):
	if doc.dfp_is_s3_remote_file():
		doc.dfp_external_storage_delete_file()
		doc.delete_file_from_filesystem(only_thumbnail=True)
		return
	doc.delete_file_from_filesystem(only_thumbnail=only_thumbnail)


class DFPExternalStorageFileRenderer:
	def __init__(self, path, status_code=None):
		self.path = path
		self.status_code = status_code
		self._regex = None

	def _regexed_path(self):
		segment = re.escape(DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD)
		self._regex = re.match(
			fr"^/?{segment}/(?P<file_id>[^/]+)/(?P<file_name>[^/]+)$",
			self.path,
		)

	def file_id_get(self):
		if self.can_render():
			return self._regex.group("file_id")

	def file_name_get(self):
		if self.can_render():
			return unquote(self._regex.group("file_name"))

	def can_render(self):
		if not self._regex:
			self._regexed_path()
		if self._regex:
			return True

	def render(self):
		if not self.can_render():
			raise frappe.PageDoesNotExistError()
		return file(name=self.file_id_get(), file=self.file_name_get())


def file(name:str, file:str):
	if not name or not file:
		raise frappe.PageDoesNotExistError()

	cache_key = f"{DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX}{name}"

	response_values = frappe.cache().get_value(cache_key)
	if not response_values:
		try:
			doc = frappe.get_doc("File", name)
		except frappe.DoesNotExistError:
			raise frappe.PageDoesNotExistError()

		if doc.file_name != file:
			raise frappe.PageDoesNotExistError()

		if not doc.is_downloadable():
			raise frappe.PermissionError()

		response_values = {}
		response_values["headers"] = []

		try:
			presigned_url = doc.dfp_presigned_url_get()
			if presigned_url:
				frappe.flags.redirect_location = presigned_url
				raise frappe.Redirect
			# Do not stream file if cacheable or smaller than stream buffer chunks size
			if doc.dfp_is_cacheable() or doc.dfp_file_size < doc.dfp_external_storage_doc.setting_stream_buffer_size:
				response_values["response"] = doc.dfp_external_storage_download_file()
			else:
				response_values["response"] = doc.dfp_external_storage_stream_file()
				response_values["headers"].append(("Content-Length", doc.dfp_file_size))
		except frappe.Redirect:
			raise
		except:
			frappe.log_error(f"Error obtaining remote file content: {name}/{file}")

		if "response" not in response_values or not response_values["response"]:
			raise frappe.PageDoesNotExistError()

		if doc.dfp_mime_type_guess_by_file_name:
			response_values["mimetype"] = doc.dfp_mime_type_guess_by_file_name
		response_values["status"] = 200

		if doc.dfp_is_cacheable():
			frappe.cache().set_value(key=cache_key,
				val=response_values,
				expires_in_sec=doc.dfp_external_storage_doc.setting_cache_expiration_secs)

	if "status" in response_values and response_values["status"] == 200:
		return Response(**response_values)

	raise frappe.PageDoesNotExistError()
