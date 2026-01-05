
frappe.ui.form.on('DFP External Storage', {

	setup: frm => {
		frm.button_remote_files_list = null
	},

	refresh: function(frm) {
		if (frm.is_new() && !frm.doc.doctypes_ignored.length) {
			frm.doc.doctypes_ignored.push({doctype_to_ignore: 'Data Import'})
			frm.doc.doctypes_ignored.push({doctype_to_ignore: 'Prepared Report'})
			frm.refresh_field('doctypes_ignored')
		}

		if (frm.doc.enabled) {
			frm.button_remote_files_list = frm.add_custom_button(
				__('List files in bucket'),
				() => frappe.set_route('dfp-s3-bucket-list', frm.doc.name)
				// () => frappe.set_route('dfp-s3-bucket-list', { storage: frm.doc.name })
			)
		}

		frm.set_query('folders', function() {
			return {
				filters: {
					is_folder: 1,
				},
			}
		})

		// Fix: Query parent DocType instead of child table to get assigned folders
		// Child DocTypes (istable=1) cannot be queried directly via frappe.db.get_list
		frappe.call({
			method: 'dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage.get_assigned_folders',
			args: {
				exclude_storage: frm.doc.name || ''
			},
			callback: function(r) {
				if (r.message && r.message.length) {
					frm.set_query('folders', function () {
						return {
							filters: {
								is_folder: 1,
								name: ['not in', r.message],
							},
						}
					})
				}
			}
		})

	},

})
