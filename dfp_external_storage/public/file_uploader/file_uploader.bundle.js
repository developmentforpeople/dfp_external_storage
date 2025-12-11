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
			// apply global allow list if present
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
		this.fieldname = fieldname
		this.doctype = doctype
		this.docname = docname
		this.frm = frm
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
			.text(__('Direct upload'))
			.on('click', async () => {
				try {
					const filesProxy = this.uploader?.files || this.files || [];
					const files = Array.from(filesProxy);

					if (files.length === 0) {
						frappe.msgprint(__("Please select files to upload"));
						return;
					}

					const timestamp = frappe.datetime.get_today();
					const sessionId = `Attachment-${timestamp}`;

					const results = [];

					for (let i = 0; i < files.length; i++) {
						const file = files[i];

						try {
							file.uploading = true;
							file.progress = 0;
							file.total = 0;
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

							if (!presigned?.message) throw new Error("Failed to get presigned URL");

							const { put_url, s3_key } = presigned.message;

							await new Promise((resolve, reject) => {
								const xhr = new XMLHttpRequest();

								xhr.upload.addEventListener('loadstart', () => {
									file.uploading = true;
									file.progress = 0;
									file.total = file.file_obj.size;
								});

								xhr.upload.addEventListener('progress', (e) => {
									if (e.lengthComputable) {
										file.progress = e.loaded;
										file.total = e.total;
									}
								});

								xhr.addEventListener('error', () => {
									reject(new Error('Network error during uploading'));
								});

								xhr.onreadystatechange = () => {
									if (xhr.readyState === XMLHttpRequest.DONE) {
										if (xhr.status >= 200 && xhr.status < 300) {
											resolve();
										} else {
											reject(new Error(`upload failed: ${xhr.status} ${xhr.statusText}`));
										}
									}
								};

								xhr.open('PUT', put_url, true);
								xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
								xhr.send(file.file_obj);
							});

							const fileDoc = await frappe.call({
								method: "dfp_external_storage.api.create_file_record",
								args: {
									file_name: file.name,
									file_size: file.file_obj.size,
									s3_key: s3_key,
									content_type: file.type || "application/octet-stream",
									attached_to_doctype: this.doctype,
									attached_to_name: this.docname,
									attached_to_field: this.fieldname,
									folder: "Home"
								}
							});
// Mark as complete
							file.uploading = false;
							file.request_succeeded = true;
							file.doc = fileDoc.message;

							results.push({ success: true, name: file.name, file_doc: fileDoc.message });

							if (this.frm && !this.fieldname && fileDoc?.message?.file_url) {
								// if no field name specified then its an attachment
								this.frm.attachments.update_attachment(fileDoc.message.file_doc);
							}
						} catch (error) {
							console.error(`Upload error for ${file.name}:`, error);
							file.uploading = false;
							file.failed = true;
							file.error_message = error.message;
							results.push({ success: false, name: file.name, error: error.message });
						}
					}

					const successful = results.filter(r => r.success);
					const failed = results.filter(r => !r.success);

					if (successful.length > 0) {
						frappe.show_alert({
							message: __(`Successfully uploaded ${successful.length} file(s)`),
							indicator: 'green'
						}, 5);

						if (this.uploader.on_success) {
							successful.forEach(r => this.uploader.on_success(r.file_doc));
						}
					}

					if (failed.length > 0) {
						frappe.msgprint({
							title: __('Upload Errors'),
							message: failed.map(f => `${f.name}: ${f.error}`).join('<br>'),
							indicator: 'red'
						});
					}

					if (failed.length === 0 && this.dialog) {
						this.dialog.hide();
					}

				} catch (error) {
					frappe.msgprint({
						title: __('Upload Failed'),
						message: error.message || __('An error occurred during upload'),
						indicator: 'red'
					});
					console.error('Direct upload error:', error);
				}
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