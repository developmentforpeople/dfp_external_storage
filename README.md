# DFP External Storage

Simplest cloud file management for Frappe / ERPNext. S3 compatible external bucket can be assigned per Frappe folder, allowing you to fine-tune the location of your Frappe / ERPNext "File"s: within local filesystem or to exteral S3 bucket.

[![Frappe files within S3 buckets](/dfp_external_storage/public/image/demo.png)](https://www.youtube.com/embed/2uTnWZxhtug)


## Requirements

- Frappe version >= 14


## Functionalities

- S3 bucket can be defined per folder/s. If "Home" folder defined, all Frappe / ERPNext files will use that S3 bucket.
- Files accesible with custom URLs: /file/[File ID]/[file name.extension]
- Frappe / ERPNext private/public functionality is preserved for external files. If an external private file is loaded not having access a not found page will be showed.
- External Storages can be write disabled, but files will be visible yet.
- Bulk file relocation (upload and download). You can filter by local S3 bucket/local filesystem and then change all those files to a different S3 bucket or to local filesystem.
- Small icon allows you visualize if file is within an S3 bucket.
- Same file upload (same file hash) will reuse existent S3 key and is not reuploaded. Same functionality as Frappe has with local files.
- S3 bucket can not be deleted if has "File"s assigned / within it.
- If bucket is not accesible file will be uploaded to local filesystem.
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