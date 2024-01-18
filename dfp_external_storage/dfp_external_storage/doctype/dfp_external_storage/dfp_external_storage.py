
import os
import re
import io
import mimetypes
from werkzeug.wrappers import Response
from functools import cached_property
from minio import Minio
import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.core.doctype.file.file import URL_PREFIXES
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password


# 5Mb but set to 0 to disable
DFP_EXTERNAL_STORAGE_CACHE_PUBLIC_FILES_SMALLER_THAN_X_MB = 5
DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX = "external_storage_public_file:"
DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_EXPIRATION_IN_SECS = 60 * 60 * 24

# http://[host:port]/<file>/[File:name]/[File:file_name]
# http://myhost.localhost:8000/file/c7baa5b2ff/my-image.png
DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD = "file"


DFP_EXTERNAL_STORAGE_CONNECTION_FIELDS = [
	"type", "endpoint", "secure", "bucket_name", "region", "access_key", "secret_key"]
DFP_EXTERNAL_STORAGE_CRITICAL_FIELDS = [
	"type", "endpoint", "secure", "bucket_name", "region", "access_key", "secret_key", "folders"]

DFP_EXTERNAL_STORAGE_IGNORE_S3_UPLOAD_FOR_DOCTYPES = [] #["Data Import", "Prepared Report"]


class S3FileProxy:

	def __init__(self, readFn, object_size):
		self.readFn = readFn
		self.object_size = object_size
		self.size = object_size # DEPRECATED! size is deprecated tell to Khoran, must be replaced by object_size
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

	def get_object(self, bucket_name:str, object_name:str,offset:int = 0,length:int = 0):
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
		return self.client.get_object(bucket_name=bucket_name, object_name=object_name,offset=offset,length=length)

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


	def put_object(self, bucket_name, object_name, data, metadata=None, length=-1, part_size=10 * 1024 * 1024):
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
 object_name=object_name, data=data, metadata=metadata, length=length, part_size=part_size)

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

	@cached_property
	def dfp_external_storage_client(self):
		if self.dfp_external_storage_doc:
			return self.dfp_external_storage_doc.client

	def dfp_external_storage_upload_file(self, local_file=None, delete_file=True):
		"""
		:param local_file: if given, the path to a file to read the content from. If not given, the content field of this File is used
		:param delete_file: when local_file is given and delete_file is True, than delete local_file after a successful upload. Otherwise does nothing.
		"""
		# Do not apply for files attached to some doctypes
		if self.attached_to_doctype and self.attached_to_doctype in DFP_EXTERNAL_STORAGE_IGNORE_S3_UPLOAD_FOR_DOCTYPES:
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

		# TODO: MOSTRAR MENSAJE DE SUBIENDO ARCHIVO Y CERRARLO O MOSTRAR ARCHIVO SUBIDO AL FINAL DE ESTE MÉTODO

		key = f"{frappe.local.site}/{self.file_name}"
		is_public = "/public" if not self.is_private else ""
		if not local_file:
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
					part_size=10 * 1024 * 1024,
					# Meta removed because same s3 file can be used within different File docs
					# metadata={"frappe_file_id": self.name}
				)

			self.dfp_external_storage_s3_key = key
			self.dfp_external_storage = self.dfp_external_storage_doc.name
			self.file_url = f"/{DFP_EXTERNAL_STORAGE_URL_SEGMENT_FOR_FILE_LOAD}/{self.name}/{self.file_name}"

			if delete_file:
				os.remove(local_file)
			self.save()
		except Exception as e:
			error_msg = _("Error saving file in remote folder: {}").format(str(e))
			frappe.log_error(f"{error_msg}: {self.file_name}", message=e)
			# If file is new we upload to local filesystem
			if not self.get_doc_before_save():
				error_extra = _("File saved in local filesystem.")
				# TODO: ver por qué este mensaje no se pinta!
				frappe.log_error(f"{error_msg} {error_extra}: {self.file_name}")
				frappe.msgprint(f"{error_msg} {error_extra}", alert=True, indicator="orange")
				self.dfp_external_storage_s3_key = ""
				self.dfp_external_storage = ""
				self.save()
			# If modifing existent file throw error
			else:
				frappe.throw(error_msg)

	def dfp_external_storage_delete_file(self):
		if not self.dfp_external_storage_s3_key or not self.dfp_external_storage_doc:
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
		# TODO: this check must be done when moving too!!!
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
		if not self.dfp_external_storage_s3_key:
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
		if not self.dfp_external_storage_s3_key:
			return

		object_info = self.dfp_external_storage_client.stat_object(
			bucket_name=self.dfp_external_storage_doc.bucket_name,
			object_name=self.dfp_external_storage_s3_key)

		def read_chunks(offset=0, size=0):
			with self.dfp_external_storage_client.get_object(
				bucket_name=self.dfp_external_storage_doc.bucket_name,
				object_name=self.dfp_external_storage_s3_key,
				offset=offset,
				length=size) as response:
				content = response.read()
			return content

		return S3FileProxy(readFn=read_chunks, object_size=object_info.size)

	def dfp_external_storage_download_file(self) -> bytes:
		content = b""
		if not self.dfp_external_storage_s3_key:
			# frappe.msgprint(_("S3 key not found: ") + self.file_name,
			# 	indicator="red", title=_("Error processing File"), alert=True)
			return content
		try:
			key = self.dfp_external_storage_s3_key
			with self.dfp_external_storage_client.get_object(
				bucket_name=self.dfp_external_storage_doc.bucket_name,
				object_name=key) as response:
				content = response.read()
			return content
		except:
			error_msg = _("Error downloading file from remote folder")
			frappe.log_error(title=f"{error_msg}: {self.file_name}")
			frappe.throw(error_msg)
		return content

	def download_to_local_and_remove_remote(self):
		try:
			bucket = self.dfp_external_storage_doc.bucket_name
			key = self.dfp_external_storage_s3_key

			self.dfp_external_storage_s3_key = ""
			self.dfp_external_storage = ""

			with self.dfp_external_storage_client.get_object(bucket_name=bucket, object_name=key) as response:
				self._content = response.read()
			self.save_file_on_filesystem()

			self.dfp_external_storage_client.remove_object(
				bucket_name=bucket, object_name=key)
		except:
			error_msg = _("Error downloading and removing file from remote folder.")
			frappe.log_error(title=f"{error_msg}: {self.file_name}")
			frappe.throw(error_msg)

	def validate_file_on_disk(self):
		return True if self.dfp_external_storage_s3_key else super(DFPExternalStorageFile, self).validate_file_on_disk()

	def exists_on_disk(self):
		return False if self.dfp_external_storage_s3_key else super(DFPExternalStorageFile, self).exists_on_disk()

	@frappe.whitelist()
	def optimize_file(self):
		if self.dfp_external_storage_s3_key:
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
		if not self.dfp_external_storage_s3_key:
			return super(DFPExternalStorageFile, self).get_content()
		try:
			if not self.is_downloadable():
				raise Exception("File not available")
			return self.dfp_external_storage_download_file()
		except Exception:
			# If no document, no read permissions, etc. For security reasons do not give any information, so just raise a 404 error
			raise frappe.PageDoesNotExistError()


def hook_file_before_save(doc, method):
	"This method is called before the document is saved"
	previous = doc.get_doc_before_save()
	# TODO: test uploading same file when existe in remote
	cache_key = f"{DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX}{doc.name}"
	# Existent remote file but saved without remote location: download to local and remove remote
	if previous and previous.dfp_external_storage and not doc.dfp_external_storage:
		previous.download_to_local_and_remove_remote()
		doc.file_url = previous.file_url
	# Existent remote file but saved with different remote location: put file to new remote
	elif (previous and previous.dfp_external_storage and doc.dfp_external_storage
		and previous.dfp_external_storage != doc.dfp_external_storage):
		try:
			# Get file from previous remote in chunks of 10MB (not loading it fully in memory)
			with previous.dfp_external_storage_file_proxy() as response:
				doc.dfp_external_storage_client.put_object(
					bucket_name=doc.dfp_external_storage_doc.bucket_name,
					object_name=doc.dfp_external_storage_s3_key,
					data=response,
					length=response.object_size,
					part_size=10 * 1024 * 1024, # 5MB is the minimum allowed by Minio (== 5 * 1024 * 1024)
					# Meta removed because same s3 file can be used within different File docs
					# metadata={"frappe_file_id": self.name}
				)
			# Remove file from previous remote
			previous.dfp_external_storage_client.remove_object(
				bucket_name=previous.dfp_external_storage_doc.bucket_name,
				object_name=previous.dfp_external_storage_s3_key)
		except:
			error_msg = _("Error putting file from one remote to another.")
			frappe.log_error(f"{error_msg}: {doc.file_name}")
			frappe.throw(error_msg)

	# Both are mandatory
	if bool(doc.dfp_external_storage) != bool(doc.dfp_external_storage_s3_key):
		doc.dfp_external_storage = ""
		doc.dfp_external_storage_s3_key = ""

	if doc.dfp_external_storage_s3_key:
		frappe.cache().delete_value(cache_key)
		if doc.file_url != doc._remote_file_local_path_get():
			# When same remote s3 key is used for different files
			doc.file_url = doc._remote_file_local_path_get()


def hook_file_on_update(doc, method):
	"This is called when values of an existing document is updated"
	previous = doc.get_doc_before_save()
	if not previous:
		# New remote file: upload to remote
		doc.dfp_external_storage_upload_file()
	else:
		# Existent local file, but new storage selected: upload to remote
		if not doc.dfp_external_storage_s3_key and doc.dfp_external_storage and not previous.dfp_external_storage:
			doc.dfp_external_storage_upload_file()
	cache_key = f"{DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_PREFIX}{doc.name}"
	frappe.cache().delete_key(cache_key)



def hook_file_after_delete(doc, method):
	"This is called after a document has been deleted"
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
	# TODO: For videos enable direct stream from S3
	# TODO: Implement direct download from S3 bucket with signed url (videos & streaming ;)
	if not name or not file:
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
			raise frappe.PageDoesNotExistError()

		response_values = {}
		content_type, encoding = mimetypes.guess_type(doc.file_name)
		if content_type:
			response_values["mimetype"] = content_type
			if encoding:
				response_values["charset"] = encoding

		try:
			presigned_url = doc.dfp_presigned_url_get()
			if presigned_url:
				frappe.flags.redirect_location = presigned_url
				raise frappe.Redirect
			# Do not stream file if cacheable or smaller than stream buffer chunks size
			if doc.dfp_is_cacheable() or doc.file_size < doc.dfp_external_storage_doc.setting_stream_buffer_size:
				response_values["response"] = doc.dfp_external_storage_download_file()
			else:
				response_values["response"] = doc.dfp_external_storage_stream_file()
				response_values["headers"].append(("Content-Length", int(doc.file_size)))
		except frappe.Redirect:
			raise
		except Exception as e:
			print(f"failed to get file content: {e}")
			pass

		if "response" not in response_values or not response_values["response"]:
			print(f"no 'response' found in response_values: {response_values}")
			raise frappe.PageDoesNotExistError()

			# Do not cache if file is private or bigger than defined MB
			if DFP_EXTERNAL_STORAGE_CACHE_PUBLIC_FILES_SMALLER_THAN_X_MB and not doc.is_private and len(filecontent) < 1024 * 1024 * DFP_EXTERNAL_STORAGE_CACHE_PUBLIC_FILES_SMALLER_THAN_X_MB:
				frappe.cache().set_value(key=cache_key, val=response_values, expires_in_sec=DFP_EXTERNAL_STORAGE_PUBLIC_CACHE_EXPIRATION_IN_SECS)

	if "status" in response_values and response_values["status"] == 200:
		return Response(**response_values)

	raise frappe.PageDoesNotExistError()
