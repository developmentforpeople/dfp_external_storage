from datetime import timedelta
import frappe
from frappe import _


@frappe.whitelist()
def generate_presigned_url(file_name, file_path="Record"):
    storage_doc = _get_storage()
    if not storage_doc or not storage_doc.enabled:
        frappe.throw(_("Write disabled for connection"))
    
    if not storage_doc.allow_direct_upload:
        frappe.throw(_("Direct Upload must be enabled before you can use this feature."))

    s3_key = f"uploads/{file_path}/{file_name}"
    put_url = storage_doc.client.presigned_put_object(
        bucket_name=storage_doc.bucket_name,
        object_name=s3_key,
        expires=timedelta(minutes=15),
    )

    protocol = "https" if storage_doc.secure else "http"
    get_url = f"{protocol}://{storage_doc.endpoint}/{storage_doc.bucket_name}/{s3_key}"

    return {
        "put_url": put_url,
        "get_url": get_url,
        "s3_key": s3_key,
    }

@frappe.whitelist()
def create_file_record(
    file_name,
    file_size,
    s3_key,
    attached_to_doctype=None,
    attached_to_name=None,
    attached_to_field=None,
    is_private=1,
    folder="Home",
    **kwargs,
):
    storage_name = _get_storage().name
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "file_size": file_size,
            "dfp_external_storage": storage_name,
            "dfp_external_storage_s3_key": s3_key,
            "attached_to_doctype": attached_to_doctype,
            "attached_to_name": attached_to_name,
            "attached_to_field": attached_to_field,
            "folder": folder,
            "is_private": is_private,
            **kwargs,
        }
    )

    file_doc.insert(ignore_permissions=True)

    file_url = f"/file/{file_doc.name}/{file_name}"
    file_doc.update({"file_url": file_url})
    file_doc.save(ignore_permissions=True)

    if attached_to_doctype and attached_to_name and attached_to_field:
        parent_doc = frappe.get_doc(attached_to_doctype, attached_to_name)
        parent_doc.update({attached_to_field: file_url})
        parent_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"file_doc": file_doc, "file_url": file_url}


def _get_storage():
    storage_docs = frappe.db.get_all("DFP External Storage", filters={
			"allow_direct_upload": True,
		})
    if not storage_docs:
        frappe.throw(_("No Bucket With Direct Upload Found"))
    elif len(storage_docs) > 1:
        frappe.throw(_("More than One Bucket With Direct Upload Found"))
    else:
        return frappe.get_doc("DFP External Storage", storage_docs[0])