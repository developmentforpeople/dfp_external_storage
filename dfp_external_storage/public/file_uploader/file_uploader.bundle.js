import { createApp } from "vue";
import FileUploaderComponent from "./FileUploader.vue";
import { watch } from "vue";


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
		this.fieldname = fieldname;
		this.doctype = doctype;
		this.docname = docname;
		this.frm = frm;
		this.on_success = on_success;
		this.folder = folder || "Home";
		this.make_attachments_public = make_attachments_public;

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

	async direct_upload_files() {
		try {
			const files = this.uploader?.files || [];

			if (files.length === 0) {
				frappe.msgprint(__("Please select files to upload"));
				return;
			}

			if (this.dialog) {
				this.dialog.get_primary_btn().prop("disabled", true);
				this.dialog.get_secondary_btn().prop("disabled", true);
			}

			const timestamp = frappe.datetime.now_datetime().replaceAll(/[: -]/g, "_");
			const sessionId = `Attachment-${timestamp}`;

			const initialFormData = this.frm ? { ...this.frm.doc } : null;

			for (let i = 0; i < files.length; i++) {
				const file = files[i];

				try {
					file.uploading = true;
					file.progress = 0;
					file.total = file.file_obj.size;
					file.failed = false;
					file.request_succeeded = false;
					file.error_message = null;
					
					const presigned = await frappe.call({
						method: "dfp_external_storage.api.generate_presigned_url",
						args: {
							file_name: file.name,
							file_path: `${this.doctype ?? "File"}/${this.docname ?? "File"}/${this.fieldname ?? sessionId}`
						}
					});

					if (!presigned?.message) {
						throw new Error("Failed to get presigned URL");
					}

					const { put_url, s3_key } = presigned.message;

					await new Promise((resolve, reject) => {
						const xhr = new XMLHttpRequest();

						xhr.upload.addEventListener('loadstart', () => {
							file.uploading = true;
						});

						xhr.upload.addEventListener('progress', (e) => {
							if (e.lengthComputable) {
								file.progress = e.loaded;
								file.total = e.total;
							}
						});

						xhr.upload.addEventListener('load', () => {
							file.uploading = false;
							resolve();
						});

						xhr.addEventListener('error', () => {
							file.failed = true;
							reject(new Error('Network error during upload'));
						});

						xhr.onreadystatechange = () => {
							if (xhr.readyState === XMLHttpRequest.DONE) {
								if (xhr.status >= 200 && xhr.status < 300) {
									file.uploading = false;
									resolve();
								} else {
									file.failed = true;
									file.error_message = `Upload failed: ${xhr.status} ${xhr.statusText}`;
									reject(new Error(file.error_message));
								}
							}
						};

						xhr.open('PUT', put_url, true);
						xhr.setRequestHeader('Content-Type', file.file_obj.type || 'application/octet-stream');
						xhr.send(file.file_obj);
					});

					const fileDocResponse = await frappe.call({
						method: "dfp_external_storage.api.create_file_record",
						args: {
							file_name: file.name,
							file_size: file.file_obj.size,
							s3_key: s3_key,
							content_type: file.file_obj.type || "application/octet-stream",
							attached_to_doctype: this.doctype,
							attached_to_name: this.docname,
							attached_to_field: this.fieldname,
							folder: this.folder,
							is_private: file.private ? 1 : 0
						}
					});

					file.request_succeeded = true;
					file.doc = fileDocResponse.message;

					if (this.on_success) {
						this.on_success(fileDocResponse.message, { message: fileDocResponse.message });
					}

					if (this.frm && !this.fieldname && fileDocResponse?.message) {
						this.frm.attachments.update_attachment(fileDocResponse.message);
					}

					// For table fields and regular fields, trigger form field update
					if (this.frm && this.fieldname && fileDocResponse?.message?.file_url) {
						const field = this.frm.get_field(this.fieldname);
						if (field) {
							// If it's a table field or attach field, this will trigger the proper update
							field.parse_validate_and_set_in_model(fileDocResponse.message.file_url);
						}
					}

				} catch (error) {
					console.error(`Upload error for ${file.name}:`, error);
					file.uploading = false;
					file.failed = true;
					file.error_message = error.message || "Upload failed";

					frappe.show_alert({
						message: __(`Failed to upload ${file.name}: ${file.error_message}`),
						indicator: 'red'
					}, 5);
				}
			}
			const allSuccessful = files.every(f => f.request_succeeded);
			const anySuccessful = files.some(f => f.request_succeeded);

			if (anySuccessful) {
				const successCount = files.filter(f => f.request_succeeded).length;
				frappe.show_alert({
					message: __(`Successfully uploaded ${successCount} file(s)`),
					indicator: 'green'
				}, 5);
			}

			if (allSuccessful && this.dialog) {
				this.dialog.hide();
			}

		} catch (error) {
			frappe.msgprint({
				title: __('Upload Failed'),
				message: error.message || __('An error occurred during upload'),
				indicator: 'red'
			});
			console.error('Direct upload error:', error);
		} finally {
			if (this.dialog) {
				this.dialog.get_primary_btn().prop("disabled", false);
				this.dialog.get_secondary_btn().prop("disabled", false);
			}
		}
	}

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

		const $custom_button = $('<button>')
			.addClass('btn btn-primary')
			.text(__('Direct Upload'))
			.on('click', () => {
				this.direct_upload_files();
			});

		this.dialog.$wrapper.find('.standard-actions').append($custom_button);

		this.dialog.$wrapper.on("hidden.bs.modal", function () {
			$(this).data("bs.modal", null);
			$(this).remove();
		});
	}
}

frappe.provide("frappe.ui");
frappe.ui.FileUploader = FileUploader;
export default FileUploader;