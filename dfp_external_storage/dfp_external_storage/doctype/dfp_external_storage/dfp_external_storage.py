
import os
import re
import io
import mimetypes
import typing as t
from datetime import timedelta
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
		if self.client:
			self.client.validate_bucket(self.bucket_name)

	@cached_property
	def client(self):
		if self.endpoint and self.access_key and self.secret_key and self.region:
			try:
				if self.is_new() and self.secret_key:
					key_secret = self.secret_key
				else:
					key_secret = get_decrypted_password("DFP External Storage", self.name, "secret_key")
				if key_secret:
					return MinioConnection(
						endpoint=self.endpoint,
						access_key=self.access_key,
						secret_key=key_secret,
						region=self.region,
						secure=self.secure,
					)
			except:
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
			if self.client.bucket_exists(bucket_name):
				frappe.msgprint(_("Great! Bucket is accesible ;)"), indicator="green", alert=True)
				return True
			else:
				frappe.throw(_("Bucket not found"))
		except Exception as e:
			if hasattr(e, "message"):
				frappe.throw(_("Error when looking for bucket: {}".format(e.message)))
			elif hasattr(e, "reason"):
				frappe.throw(str(e))
		return False

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

	@property
	def is_remote_file(self):
		return True if self.dfp_external_storage_s3_key else super(DFPExternalStorageFile, self).is_remote_file

	@cached_property
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

	def will_be_remote(self):
		return self.dfp_external_storage_doc != None

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

	@cached_property
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

		if not self.name:
			self.save()

		# Define S3 key
		# key = f"{frappe.local.site}/{self.file_name}" # << Before 2024.03.03
		base, extension = os.path.splitext(self.file_name)
		key = f"{frappe.local.site}/{base}-{self.name}{extension}"

		is_public = "/public" if not self.is_private else ""
		if not local_file:
			if not self.file_url:
				frappe.throw("dfp_external_storage_upload_file: cannot upload file, file_url is not set and local_file not given")
			local_file = "./" + frappe.local.site + is_public + self.file_url

		try:
			if not os.path.exists(local_file):
				frappe.throw(_("Local file not found"))
			with open(local_file, "rb") as f:
				self.dfp_external_storage_client.put_object(
					bucket_name=self.dfp_external_storage_doc.bucket_name,
					object_name=key,
					data=f,
					length=os.path.getsize(local_file),
					# Meta removed because same s3 file can be used within different File docs
					# metadata={"frappe_file_id": self.name}
				)

			self.dfp_external_storage_s3_key = key
			self.dfp_external_storage = self.dfp_external_storage_doc.name
			self.file_url = f"/{DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD}/{self.name}/{self.file_name}"

			os.remove(local_file)
		except Exception as e:
			error_msg = _("Error saving file in remote folder: {}").format(str(e))
			frappe.log_error(f"{error_msg}: {self.file_name}", message=e)
			# If file is new we upload to local filesystem
			if not self.get_doc_before_save():
				error_extra = _("File saved in local filesystem.")
				frappe.log_error(f"{error_msg} {error_extra}: {self.file_name}")
				self.dfp_external_storage_s3_key = ""
				self.dfp_external_storage = ""
				self.file_url = original_file_url
			# If modifing existent file throw error
			else:
				frappe.throw(error_msg)

	def dfp_external_storage_delete_file(self):
		if not self.dfp_is_s3_remote_file():
			return
		# Do not delete if other file docs are using same dfp_external_storage
		# and dfp_external_storage_s3_key
		files_using_s3_key = frappe.get_all("File", filters={
			"dfp_external_storage_s3_key": self.dfp_external_storage_s3_key,
			"dfp_external_storage": self.dfp_external_storage
		})
		if len(files_using_s3_key):
			return
		error_msg = _("Error deleting file in remote folder.")
		# Only delete if connection is enabled
		if not self.dfp_external_storage_doc or not self.dfp_external_storage_doc.enabled:
			error_extra = _("Write disabled for connection <strong>{}</strong>").format(
				self.dfp_external_storage_doc.title)
			frappe.throw(f"{error_msg} {error_extra}")
		try:
			self.dfp_external_storage_client.remove_object(
				bucket_name=self.dfp_external_storage_doc.bucket_name,
				object_name=self.dfp_external_storage_s3_key)
		except Exception as e:
			frappe.log_error(f"{error_msg}: {self.file_name}", message=e)
			frappe.throw(f"{error_msg} {str(e)}")

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

	def download_to_local_and_remove_remote(self):
		try:
			bucket = self.dfp_external_storage_doc.bucket_name
			key = self.dfp_external_storage_s3_key

			self.dfp_external_storage_s3_key = ""
			self.dfp_external_storage = ""

			with self.dfp_external_storage_client.get_object(bucket_name=bucket, object_name=key) as response:
				self._content = response.read()
			self.save_file_on_filesystem()

			self.dfp_external_storage_client.remove_object(bucket_name=bucket, object_name=key)
		except:
			error_msg = _("Error downloading and removing file from remote folder.")
			frappe.log_error(title=f"{error_msg}: {self.file_name}")
			frappe.throw(error_msg)

	def validate_file_on_disk(self):
		if self.dfp_is_s3_remote_file() or self.will_be_remote():
			return True

		super(DFPExternalStorageFile, self).validate_file_on_disk()

	def exists_on_disk(self):
		return False if self.dfp_is_s3_remote_file() else super(DFPExternalStorageFile, self).exists_on_disk()

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
		if not self.file_url or self.is_remote_file or self.dfp_external_storage_s3_key:
			return
		try:
			dfp_es_file_renderer = DFPExternalStorageFileRenderer(path=self.file_url)
			if not dfp_es_file_renderer.can_render():
				return
			s3_data = frappe.get_value("File", dfp_es_file_renderer.file_id_get(), fieldname="*")
			if s3_data:
				self.dfp_external_storage = s3_data["dfp_external_storage"]
				self.dfp_external_storage_s3_key = s3_data["dfp_external_storage_s3_key"]
				self.content_hash = s3_data["content_hash"]
				self.file_size = s3_data["file_size"]
				# It is "duplicated" within Frappe but not in S3 😏
				self.flags.ignore_duplicate_entry_error = True
		except:
			pass

	def get_content(self) -> bytes:
		self.dfp_file_url_is_s3_location_check_if_s3_data_is_not_defined()
		if not self.dfp_is_s3_remote_file():
			return super(DFPExternalStorageFile, self).get_content()
		try:
			if not self.is_downloadable():
				raise Exception("File not available")
			return self.dfp_external_storage_download_file()
		except Exception:
			# If no document, no read permissions, etc. For security reasons do not give any information, so just raise a 404 error
			raise frappe.PageDoesNotExistError()

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

		# NEW "File": Case 1a: remote selected and have file => upload to remote and continue "File" flow
		if doc.file_url:
			doc.dfp_external_storage_upload_file()

		# NEW "File": Case 1b: remote selected and no local file (file_url) to upload => do nothing for now
		return

	# MODIFY "File"

	# MODIFY "File": Case 1: Existent local file + new storage selected => upload to remote
	if not doc.dfp_external_storage_s3_key and doc.dfp_external_storage and not previous.dfp_external_storage:
		doc.dfp_external_storage_upload_file()

	# MODIFY "File": Case 2: Existent remote file + no storage selected => download to local + remove from remote
	elif previous.dfp_external_storage and not doc.dfp_external_storage:
		previous.download_to_local_and_remove_remote()
		doc.file_url = previous.file_url # << contains local file path downloaded
		doc.dfp_external_storage_s3_key = ""

	# MODIFY "File": Case 3: Existent remote file + new remote selected => stream from old to new remote + delete from old remote
	elif previous.dfp_external_storage and doc.dfp_external_storage and previous.dfp_external_storage != doc.dfp_external_storage:
		try:
			# MODIFY "File": Case 3.1.: new remote + not allowed doctype => download to local + remove old remote
			# TODO: Maybe we should left in old remote?? and we should check if old remote allows the doctype??
			if doc.dfp_external_storage_ignored_doctypes():
				previous.download_to_local_and_remove_remote()
				doc.file_url = previous.file_url # << contains local file path downloaded
				doc.dfp_external_storage_s3_key = ""
				doc.dfp_external_storage = ""
			# MODIFY "File": Case 3.2.: new remote + allowed doctype => stream from old to new remote + delete from old remote
			else:
				# Get file from previous remote in chunks of 10MB (not loading it fully in memory)
				with previous.dfp_external_storage_file_proxy() as response:
					doc.dfp_external_storage_client.put_object(
						bucket_name=doc.dfp_external_storage_doc.bucket_name,
						object_name=doc.dfp_external_storage_s3_key,
						data=response,
						length=response.object_size,
						# Meta removed because same s3 file can be used within different File docs
						# metadata={"frappe_file_id": self.name}
					)
				# New s3 key => update "file_url"
				doc.file_url = doc._remote_file_local_path_get()
				# Remove file from previous remote
				previous.dfp_external_storage_client.remove_object(
					bucket_name=previous.dfp_external_storage_doc.bucket_name,
					object_name=previous.dfp_external_storage_s3_key)
		except:
			error_msg = _("Error putting file from one remote to another.")
			frappe.log_error(f"{error_msg}: {doc.file_name}")
			frappe.throw(error_msg)

	# Clean cache when updating "File"
	if doc.dfp_external_storage_s3_key:
		cache_key = f"{DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX}{doc.name}"
		frappe.cache().delete_value(cache_key)


def hook_file_on_update(doc, method):
	"""DEPRECATED! Remove method after 2025.01.01 ("/dfp_external_storage/dfp_external_storage/hooks.py" too)"""
	pass


def hook_file_after_delete(doc, method):
	"Called after a document is deleted"
	doc.dfp_external_storage_delete_file()


class DFPExternalStorageFileRenderer:
	def __init__(self, path, status_code=None):
		self.path = path
		self.status_code = status_code
		self._regex = None

	def _regexed_path(self):
		self._regex = re.search(fr"{DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD}\/(.+)\/(.+\.\w+)$", self.path)

	def file_id_get(self):
		if self.can_render():
			return self._regex[1]

	def can_render(self):
		if not self._regex:
			self._regexed_path()
		if self._regex:
			return True

	def render(self):
		file_id = self._regex[1]
		file_name = self._regex[2] if len(self._regex.regs) == 3 else ""
		return file(name=file_id, file=file_name)


def file(name:str, file:str):
	print(f"downloading name: {name}, file: {file}")

	if not name or not file:
		frappe.log_error("Page not found",f"name ({name}) or file ({file}) not given")
		raise frappe.PageDoesNotExistError()

	cache_key = f"{DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX}{name}"

	response_values = frappe.cache().get_value(cache_key)
	if not response_values:
		try:
			doc = frappe.get_doc("File", name)
			if not doc or not doc.is_downloadable() or doc.file_name != file:
				raise Exception("File not available")
		except Exception:
			# If no document, no read permissions, etc. For security reasons do not give any information, so just raise a 404 error
			frappe.logger().exception(f"Page not found, either no File found {doc}, could not be downloaded, or file_name {doc and doc.file_name} does equal given name {file}")
			frappe.log_error("Page not found",f"either no File found {doc}, could not be downloaded, or file_name {doc and doc.file_name} does equal given name {file}")
			raise frappe.PageDoesNotExistError()

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
			frappe.logger().exception(f"Error obtaining remote file content: {name}/{file}")
			frappe.log_error(f"Error obtaining remote file content: {name}/{file}")

		if "response" not in response_values or not response_values["response"]:
			frappe.log_error("Page not found",f"no reponse defined. response_values: {response_values}")
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

	frappe.log_error("Page not found",f"unknown reason. response so far: {response_values}")
	raise frappe.PageDoesNotExistError()
