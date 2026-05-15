function patch_file_uploader(FileUploaderClass) {
    const original_make_dialog = FileUploaderClass.prototype.make_dialog;

    const PatchedClass = function (options = {}) {
        const instance = Reflect.construct(FileUploaderClass, [options], PatchedClass);
        instance.doctype = options.doctype;
        instance.docname = options.docname;
        instance.fieldname = options.fieldname;
        instance.frm = options.frm;
        instance.folder = options.folder || "Home";
        instance.on_success = options.on_success;
        return instance;
    };
    PatchedClass.prototype = Object.create(FileUploaderClass.prototype);
    PatchedClass.prototype.constructor = PatchedClass;

    PatchedClass.prototype.make_dialog = function (title) {
        original_make_dialog.call(this, title);
        $("<button>")
            .addClass("btn btn-primary btn-sm")
            .text("Direct Upload")
            .on("click", () => this.direct_upload_files())
            .appendTo(this.dialog.footer.find(".standard-actions"));
    };

    PatchedClass.prototype.direct_upload_files = async function () {
        const files = this.uploader?.files || [];
        if (!files.length) { frappe.msgprint(__("Please select files to upload")); return; }

        this._set_dialog_buttons_disabled(true);
        const sessionId = `Attachment-${frappe.datetime.now_datetime().replaceAll(/[: -]/g, "_")}`;
        let successCount = 0;

        for (const file of files) {
            try {
                await this._direct_upload_single(file, sessionId);
                successCount++;
            } catch (err) {
                console.error(`Upload error for ${file.name}:`, err);
                frappe.show_alert({ message: __(`Failed to upload ${file.name}: ${err.message}`), indicator: "red" }, 5);
            }
        }

        if (successCount) frappe.show_alert({ message: __(`Successfully uploaded ${successCount} file(s)`), indicator: "green" }, 5);
        if (files.every(f => f.request_succeeded) && this.dialog) this.dialog.hide();
        this._set_dialog_buttons_disabled(false);
    };

    PatchedClass.prototype._direct_upload_single = async function (file, sessionId) {
        Object.assign(file, { uploading: true, progress: 0, total: file.file_obj.size, failed: false, request_succeeded: false, error_message: null });

        const presigned = await frappe.call({
            method: "dfp_external_storage.api.generate_presigned_url",
            args: {
                file_name: file.name,
                file_path: `${this.doctype ?? "File"}/${this.docname ?? "File"}/${this.fieldname ?? sessionId}`,
            },
        });

        if (!presigned?.message) throw new Error("Failed to get presigned URL");
        const { put_url, s3_key } = presigned.message;
        await this._xhr_put(put_url, file);

        const fileDocResponse = await frappe.call({
            method: "dfp_external_storage.api.create_file_record",
            args: {
                file_name: file.name,
                file_size: file.file_obj.size,
                s3_key,
                attached_to_doctype: this.doctype,
                attached_to_name: this.docname,
                attached_to_field: this.fieldname,
                folder: this.folder,
                is_private: file.private ? 1 : 0,
            },
        });

        const file_doc = fileDocResponse.message;
        file.request_succeeded = true;
        file.doc = file_doc;

        this.on_success?.(file_doc, { message: file_doc });

        if (this.frm && !this.fieldname && file_doc) {
            this.frm.attachments.update_attachment(file_doc);
            this.frm.refresh_field(this.fieldname);
            this.frm.refresh();
        }

        if (this.frm && this.fieldname && file_doc?.file_url) {
            this.frm.get_field(this.fieldname)?.parse_validate_and_set_in_model(file_doc.file_url);
        }
    };

    PatchedClass.prototype._xhr_put = function (url, file) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.upload.addEventListener("progress", (e) => { if (e.lengthComputable) { file.progress = e.loaded; file.total = e.total; } });
            xhr.onreadystatechange = () => {
                if (xhr.readyState !== XMLHttpRequest.DONE) return;
                file.uploading = false;
                if (xhr.status >= 200 && xhr.status < 300) resolve();
                else { file.failed = true; file.error_message = `Upload failed: ${xhr.status}`; reject(new Error(file.error_message)); }
            };
            xhr.addEventListener("error", () => { file.failed = true; reject(new Error("Network error")); });
            xhr.open("PUT", url, true);
            xhr.setRequestHeader("Content-Type", file.file_obj.type || "application/octet-stream");
            xhr.send(file.file_obj);
        });
    };

    PatchedClass.prototype._set_dialog_buttons_disabled = function (disabled) {
        if (!this.dialog) return;
        this.dialog.get_primary_btn().prop("disabled", disabled);
        this.dialog.get_secondary_btn().prop("disabled", disabled);
    };

    return PatchedClass;
}

frappe.provide("frappe.ui");
let _fileUploaderValue = frappe.ui.FileUploader;

Object.defineProperty(frappe.ui, "FileUploader", {
    get() { return _fileUploaderValue; },
    set(cls) {
        if (cls) {
            _fileUploaderValue = patch_file_uploader(cls);
        }
    },
    configurable: true,
});