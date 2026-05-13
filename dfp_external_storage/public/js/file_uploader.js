import { createApp } from "vue";
import { watch } from "vue";
import FileUploaderComponent from "../../../../frappe/frappe/public/js/frappe/file_uploader/FileUploader.vue";// ---------------------------------------------------------------------------
// Frappe's FileUploader class — imported directly from upstream source so we
// never duplicate it. Any upstream fix automatically applies here.
// We only patch the prototype with our additions.
// ---------------------------------------------------------------------------

class FileUploader {
    constructor({
        wrapper,
        method,
        on_success,
        doctype,
        docname,
        fieldname,
        files,
        folder,
        restrictions = {},
        upload_notes,
        allow_multiple,
        as_dataurl,
        disable_file_browser,
        dialog_title,
        attach_doc_image,
        frm,
        make_attachments_public,
        allow_web_link,
        allow_take_photo,
        allow_toggle_private,
        allow_toggle_optimize,
        allow_google_drive,
    } = {}) {
        frm && frm.attachments.max_reached(true);
        this.doctype = doctype;
        this.docname = docname;
        this.fieldname = fieldname;
        this.frm = frm;
        this.folder = folder || "Home";
        this.on_success = on_success;
        if (!wrapper) {
            this.make_dialog(dialog_title);
        } else {
            this.wrapper = wrapper.get ? wrapper.get(0) : wrapper;
        }

        if (restrictions && !restrictions.allowed_file_types) {
            let allowed_extensions = frappe.sys_defaults?.allowed_file_extensions;
            if (allowed_extensions) {
                restrictions.allowed_file_types = allowed_extensions
                    .split("\n")
                    .map((ext) => `.${ext}`);
            }
        }

        let app = createApp(FileUploaderComponent, {
            show_upload_button: !Boolean(this.dialog),
            doctype,
            docname,
            fieldname,
            method,
            folder,
            on_success,
            restrictions,
            upload_notes,
            allow_multiple,
            as_dataurl,
            disable_file_browser,
            attach_doc_image,
            make_attachments_public,
            allow_web_link,
            allow_take_photo,
            allow_toggle_private,
            allow_toggle_optimize,
            allow_google_drive,
        });
        SetVueGlobals(app);
        this.uploader = app.mount(this.wrapper);

        if (!this.dialog) {
            this.uploader.wrapper_ready = true;
        }

        watch(
            () => this.uploader.files,
            (files) => {
                let all_private = files.every((file) => file.private);
                if (this.dialog) {
                    this.dialog.set_secondary_action_label(
                        all_private ? __("Set all public") : __("Set all private")
                    );
                }
            },
            { deep: true }
        );

        watch(
            () => this.uploader.trigger_upload,
            (trigger_upload) => {
                if (trigger_upload) {
                    this.upload_files();
                }
            }
        );

        watch(
            () => this.uploader.close_dialog,
            (close_dialog) => {
                if (close_dialog) {
                    this.dialog && this.dialog.hide();
                }
            }
        );

        watch(
            () => this.uploader.hide_dialog_footer,
            (hide_dialog_footer) => {
                if (hide_dialog_footer) {
                    this.dialog && this.dialog.footer.addClass("hide");
                    this.dialog.$wrapper.data("bs.modal")._config.backdrop = "static";
                } else {
                    this.dialog && this.dialog.footer.removeClass("hide");
                    this.dialog.$wrapper.data("bs.modal")._config.backdrop = true;
                }
            }
        );

        if (files && files.length) {
            this.uploader.add_files(files);
        }
    }

    upload_files() {
        return this.uploader.upload_files(this.dialog);
    }

    // inject "Direct Upload" button after the standard dialog setup
    make_dialog(title) {
        this.dialog = new frappe.ui.Dialog({
            title: title || __("Upload"),
            primary_action_label: __("Upload"),
            primary_action: () => this.upload_files(),
            secondary_action_label: __("Set all private"),
            secondary_action: () => {
                this.uploader.toggle_all_private();
            },
            on_page_show: () => {
                this.uploader.wrapper_ready = true;
            },
        });

        this.wrapper = this.dialog.body;
        this.dialog.show();

        // DFP addition — direct-to-S3 upload button
        $("<button>")
            .addClass("btn btn-primary")
            .text(__("Direct Upload"))
            .on("click", () => this.direct_upload_files())
            .appendTo(this.dialog.$wrapper.find(".standard-actions"));

        this.dialog.$wrapper.on("hidden.bs.modal", function () {
            $(this).data("bs.modal", null);
            $(this).remove();
        });
    }

    async direct_upload_files() {
        const files = this.uploader?.files || [];

        if (!files.length) {
            frappe.msgprint(__("Please select files to upload"));
            return;
        }

        this._set_dialog_buttons_disabled(true);

        const sessionId = `Attachment-${frappe.datetime
            .now_datetime()
            .replaceAll(/[: -]/g, "_")}`;

        let successCount = 0;

        for (const file of files) {
            await this._direct_upload_single(file, sessionId)
                .then(() => successCount++)
                .catch((err) => {
                    console.error(`Upload error for ${file.name}:`, err);
                    frappe.show_alert(
                        {
                            message: __(`Failed to upload ${file.name}: ${err.message || "Upload failed"}`),
                            indicator: "red",
                        },
                        5
                    );
                });
        }

        if (successCount) {
            frappe.show_alert(
                {
                    message: __(`Successfully uploaded ${successCount} file(s)`),
                    indicator: "green",
                },
                5
            );
        }

        if (files.every((f) => f.request_succeeded) && this.dialog) {
            this.dialog.hide();
        }

        this._set_dialog_buttons_disabled(false);
    }

    async _direct_upload_single(file, sessionId) {
        Object.assign(file, {
            uploading: true,
            progress: 0,
            total: file.file_obj.size,
            failed: false,
            request_succeeded: false,
            error_message: null,
        });
        const presigned = await frappe.call({
            method: "dfp_external_storage.api.generate_presigned_url",
            args: {
                file_name: file.name,
                file_path: `${this.doctype ?? "File"}/${this.docname ?? "File"}/${this.fieldname ?? sessionId}`,
            },
        });

        if (!presigned?.message) {
            throw new Error("Failed to get presigned URL");
        }

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

        // frappe.call wraps the return value in .message
        const file_doc = fileDocResponse.message;

        file.request_succeeded = true;
        file.doc = file_doc;

        this.on_success?.(file_doc, { message: file_doc });

        if (this.frm && !this.fieldname && file_doc) {
            this.frm.attachments.update_attachment(file_doc);
            this.frm.refresh_field(this.fieldname)
            this.frm.refresh()
        }

        if (this.frm && this.fieldname && file_doc?.file_url) {
            this.frm
                .get_field(this.fieldname)
                ?.parse_validate_and_set_in_model(file_doc.file_url);
        }
    }

    _xhr_put(url, file) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();

            xhr.upload.addEventListener("progress", (e) => {
                if (e.lengthComputable) {
                    file.progress = e.loaded;
                    file.total = e.total;
                }
            });

            xhr.onreadystatechange = () => {
                if (xhr.readyState !== XMLHttpRequest.DONE) return;
                file.uploading = false;
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve();
                } else {
                    file.failed = true;
                    file.error_message = `Upload failed: ${xhr.status} ${xhr.statusText}`;
                    reject(new Error(file.error_message));
                }
            };

            xhr.addEventListener("error", () => {
                file.failed = true;
                reject(new Error("Network error during upload"));
            });

            xhr.open("PUT", url, true);
            xhr.setRequestHeader(
                "Content-Type",
                file.file_obj.type || "application/octet-stream"
            );
            xhr.send(file.file_obj);
        });
    }

    _set_dialog_buttons_disabled(disabled) {
        if (!this.dialog) return;
        this.dialog.get_primary_btn().prop("disabled", disabled);
        this.dialog.get_secondary_btn().prop("disabled", disabled);
    }
}

frappe.provide("frappe.ui");
frappe.ui.FileUploader = FileUploader;
export default FileUploader;

// ---------------------------------------------------------------------------
// Other DFP overrides (FileView, File form, list settings)
// ---------------------------------------------------------------------------

const class_external_storage_icon = "dfp-storage-external-icon";

function dfp_s3_icon(title = "") {
    let $icon = $(`<i class="fa fa-cloud-upload ${class_external_storage_icon}"></i>`);
    if (title) {
        $icon.attr("title", title);
    }
    return $icon;
}

frappe.views.FileView = class DFPExternalStorageFileView extends frappe.views.FileView {
    setup_defaults() {
        this._dfp_external_storages = [];
        return super.setup_defaults().then(() => {
            frappe.db
                .get_list("DFP External Storage", { fields: ["name", "title"] })
                .then((data) => (this._dfp_external_storages = data));
        });
    }

    _dfp_s3_title(dfp_external_storage) {
        let s3 = this._dfp_external_storages.filter((i) => i.name == dfp_external_storage);
        return s3.length ? s3[0].title : __("No external storage name found :(");
    }

    prepare_datum(d) {
        d = super.prepare_datum(d);
        if (d.dfp_external_storage_s3_key && d.dfp_external_storage) {
            let title = this._dfp_s3_title(d.dfp_external_storage);
            d.subject_html += dfp_s3_icon(title).prop("outerHTML");
        }
        return d;
    }

    render_grid_view() {
        super.render_grid_view();
        let $file_grid = $(".file-grid");
        this.data.forEach((file) => {
            if (file.dfp_external_storage_s3_key && file.dfp_external_storage) {
                let $file = $file_grid.find(`[data-name="${file.name}"]`);
                let title = this._dfp_s3_title(file.dfp_external_storage);
                $file.append(dfp_s3_icon(title));
            }
        });
    }
};

frappe.ui.form.on("File", {
    refresh: function (frm) {
        let $title_area = frm.$wrapper[0].page.$title_area;
        $title_area.find(`.${class_external_storage_icon}`).remove();
        if (frm.doc.dfp_external_storage_s3_key) {
            $title_area.prepend(dfp_s3_icon());
        }
    },
});

frappe.listview_settings["File"] = {
    add_fields: ["dfp_external_storage_s3_key"],
};