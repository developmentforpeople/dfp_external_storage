# DFP External Storage

Simplest cloud file management for Frappe / ERPNext. S3 compatible external bucket can be assigned per Frappe folder, allowing you to fine-tune the location of your Frappe / ERPNext "File"s: within local filesystem or to exteral S3 bucket.

[![Frappe files within S3 buckets](/dfp_external_storage/public/image/demo.png)](https://www.youtube.com/embed/2uTnWZxhtug)


## Examples / Use cases

### All Frappe / ERPNext files into external S3 compatible bucket

[upload_frappe_erpnext_files_s3_compatible_bucket.webm](https://github.com/developmentforpeople/dfp_external_storage/assets/47140294/68592d26-4391-45fc-bd75-d4d5f06ce899)

### Move files / objects from S3 compatible bucket to another S3 compatible bucket (between buckets in same or different connection)

[move_objects_from_one_s3_compatible_bucket_to_another.webm](https://github.com/developmentforpeople/dfp_external_storage/assets/47140294/9c4d7197-d19e-422e-85a9-8af7725014f0)

### Move files / objects from S3 compatible bucket to local file system

[move_objects_from_s3_compatible_to_local_filesystem.webm](https://github.com/developmentforpeople/dfp_external_storage/assets/47140294/2d4eccf1-f7e2-4c89-9694-95ec36b6856d)

### Move files in local filesystem to S3 compatible bucket

[move_local_files_to_s3_compatible_bucket.webm](https://github.com/developmentforpeople/dfp_external_storage/assets/47140294/6a19d3b6-48c6-46a1-a08d-29d3555b4419)

### Per file examples

[move_file_from_s3_compatible_bucket_to_different_one_then_to_local_file.webm](https://github.com/developmentforpeople/dfp_external_storage/assets/47140294/1a4f216a-a6b4-4728-a27e-efdf4cbcf983)

### List all remote files in bucket

Shows all files in bucket, even the ones not in Frappe File doctype.

[list_files_in_remote_s3_bucket.webm](https://github.com/developmentforpeople/dfp_external_storage/assets/47140294/fbd38418-686e-45b4-b23b-048bed4d1143)


## Requirements

- Frappe version >= 14


## Functionalities

- S3 bucket can be defined per folder/s. If "Home" folder defined, all Frappe / ERPNext files will use that S3 bucket.
- Files accesible with custom URLs: /file/[File ID]/[file name.extension]
- Frappe / ERPNext private/public functionality is preserved for external files. If an external private file is loaded not having access a not found page will be showed.
- External Storages can be write disabled, but files will be visible yet.
- Bulk file relocation (upload and download). You can filter by local S3 bucket/local filesystem and then change all those files to a different S3 bucket or to local filesystem. All files are "moved" without load them fully in memory optimizing large ones transfer.
- Small icon allows you visualize if file is within an S3 bucket.
- Same file upload (same file hash) will reuse existent S3 key and is not reuploaded. Same functionality as Frappe has with local files.
- Choosed S3 bucket file listing tool.
- S3 bucket can not be deleted if has "File"s assigned / within it.
- If bucket is not accesible file will be uploaded to local filesystem.
- Stream data in chunks to and from S3 without reading whole files into memory (thanks to [Khoran](https://github.com/khoran)
- List all remote objects in bucket (includes too the ones not uploaded trough Frappe)
- Support for S3 / Minio presigned urls: allowing video streaming capabilities and other S3 functionalities.
- Presigned url can be used for all files in defined folders but defined by mimetype.
- Files are now streamed by default.
- Extended settings per External Storage doc:
	- Cache only files smaller than
	- Cache for x seconds
	- Stream buffer size
	- Presigned url activation
	- Presigned url only for mimetypes defined
	- Presigned url expiration
- ... maybe I am forgetting something ;)


### Flow options

- No S3 external storages defined
- or S3 external storages defined but not assigned to folders:
	- All uploaded files are saved in local filesystem
- One S3 external storage assigned to "Attachments" folder:
	- Only files uploaded to that folder will be use that S3 bucket
- One S3 external storage assigned to "Home" folder:
	- All files uploaded to Frappe will be located within that bucket. Except the files uploaded to "Attachments" that will use the above defined bucket


### File actions available

- If a "File" has an "DFP External Storage" assigned.
	- If changed to a different "DFP External Storage" file will be:
		- "downloaded" from previous bucket > "uploaded" to new bucket > "deleted" from previous bucket.
	- If leaved empty, file will be "downloaded" to local filesystem > "deleted" from bucket.
- If a "File" has no "DFP External Storage" assigned, so it is in local filesystem:
	- If assigned a "DFP External Storage", file will be:
		- "uploaded" to that bucket > "deleted" from filesystem


## Setup or try it locally

### Install Frappe 14
Follow all steps for your OS within official guide: [https://frappeframework.com/docs/v14/user/en/installation](https://frappeframework.com/docs/v14/user/en/installation).


### Create your personal "frappe-bench" environment (customizable folder name)

Into your home folder:

```
cd ~
bench init frappe-bench
```


### Install "dfp_external_storage" app

```
cd ~/frappe-bench
bench get-app git@github.com:developmentforpeople/dfp_external_storage.git
```


### Create a new site with "dfp_external_storage" app installed on it

```
cd ~/frappe-bench
bench new-site dfp_external_storage_site.localhost --install-app dfp_external_storage
```


### Initialize servers to get site running

```
cd ~/frappe-bench
bench start
```

### Create one or more "DFP External Storage"s

Add one or more S3 bucket and, this is the most important step, assign "Home" folder to it. This makes all files uploaded to Frappe / ERPNext being uploaded to that bucket.

You can select a different folder and only those files will be uploaded, or select different buckets for different folders, your imagination is your limit!! :D

### Stream data to and from S3 without reading whole files into memory

Option is valuable when working with large files.

For uploading content from a local file, usage would look like:
```
file_doc = frappe.get_doc({
    "doctype":"File",
    "is_private":True,
    "file_name": "file name here"
})
file_doc.dfp_external_storage_upload_file(filepath)
file_doc.save()
```

To download content to a local file:
```
file_doc = frappe.get_doc("File",doc_name)
file_doc.dfp-external_storage_download_to_file("/path/to/local/file")
```

To read remote file directly via a proxy object:
```
file_doc = frappe.get_doc("File",doc_name)

#read zip file table of contents without downloading the whole zip file
with zipfile.ZipFile(file_doc.dfp_external_storage_file_proxy()) as z:
  for zipinfo in z.infolist():
     print(f"{zipinfo.filename}")

```

## Pending

- Make tests:
	- Create DFP External Storage
	- Upload file to bucket
	- Read bucket file
	- Relocate bucket file
	- Delete bucket file


## Contributing

1. [Code of Conduct](CODE_OF_CONDUCT.md)


## Attributions

- cloud storage by Iconstock from [Noun Project](https://thenounproject.com/browse/icons/term/cloud-storage/)


#### License

MIT