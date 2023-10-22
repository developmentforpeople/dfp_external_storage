# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe


@frappe.whitelist()
def get_info(storage=None, template=None, file_type=None) -> list[dict]:
	files = []

	document = "DFP External Storage"

	dfp_external_storage_doc = None
	if storage:
		dfp_external_storage_doc = frappe.get_doc(document, storage)
	else:
		last_id = frappe.get_all(document, filters={ "enabled": 1 }, order_by="modified desc", limit=1)
		if last_id:
			dfp_external_storage_doc = frappe.get_doc(document, last_id[0].name if last_id else None)

	if dfp_external_storage_doc:
		# dfp_external_storage_doc.remote_files_list(template, file_type)
		objects = dfp_external_storage_doc.remote_files_list()
		for file in objects:
			files.append({
				"etag": file.etag,
				"is_dir": file.is_dir,
				"last_modified": file.last_modified,
				"metadata": file.metadata,
				"name": file.object_name,
				"size": file.size,
				"storage_class": file.storage_class,
			})

	return files
