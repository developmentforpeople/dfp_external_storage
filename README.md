# DFP External Storage

Simlest cloud file management for Frappe / ERPNext. S3 compatible external storages (or S3 bucket(s)) per folder that allows you to fine-tune the location of your Frappe / ERPNext "File"s per folder: local or specific S3 bucket.


# Requirements

- Frappe version >= 14


## Functionalities

- S3 bucket for all Frappe/ERPNext files (public and private).
- S3 bucket can be defined per folder. If "Home" folder defined, all files will use that S3 bucket.
- Files accesible with custom URLs: /file/[File ID]/[file name.extension]
- Private/Public preserved. If a private file not logged a 404 not found page will be showed.
- External Storages can be write disabled.
- Bulk file relocation (upload and download). You can filter by local S3 bucket/local filesystem and then change all those files to a different S3 bucket/local filesystem.
- Small icon allows you visualize if file is within an S3 bucket.
- Same file upload reuse existent S3 key and is not reuploaded.
- S3 bucket can not be deleted if has "File"s assigned
- ...


### Flow options

- No S3 external storages defined:
	- All uploaded files are saved in local filesystem
- S3 external storages defined but not assigned to folders:
	- All files are saved in local filesystem
- One S3 external storage assigned to "Attachments" folder:
	- All files uploaded to that folder are placed inside that S3 bucket
- One S3 external storage assigned to "Home" folder:
	- All files uploaded to Frappe are uploaded to assigned bucket. Except the files uploaded to "Attachments" that will use the above defined bucket


### File actions available

- If a "File" has an "DFP External Storage" assigned.
	- If changed to a different "DFP External Storage" file will be:
		- "downloaded" from previous bucket > "uploaded" to new bucket > "deleted" from previous bucket.
	- If leaved empty, file will be "downloaded" to local filesystem > "deleted" from bucket.
- If a "File" has no "DFP External Storage" assigned, so it is in local filesystem:
	- If assigned a "DFP External Storage", file will be:
		- "uploaded" to that bucket > "deleted" from filesystem


## Pending

- Make tests
- ...


## Contributing

1. [Code of Conduct](CODE_OF_CONDUCT.md)


## Attributions

- cloud storage by Iconstock from [Noun Project](https://thenounproject.com/browse/icons/term/cloud-storage/)


#### License

MIT