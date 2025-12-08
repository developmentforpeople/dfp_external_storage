from datetime import timedelta
import frappe
from frappe import _


@frappe.whitelist()
def generate_presigned_url(storage_name, file_name, file_path="Record"):
    storage_doc = frappe.get_doc("DFP External Storage", storage_name)
    if not storage_doc or not storage_doc.enabled:
        frappe.throw(_("Write disabled for connection"))
    
    if not storage_doc.allow_direct_upload:
        frappe.throw(_("Direct Upload must be enabled before you can use this feature."))

    s3_key = f"uploads/{file_path}/{file_name}"

    put_url = storage_doc.client.client.presigned_put_object(
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
