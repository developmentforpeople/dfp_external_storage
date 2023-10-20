
frappe.ui.form.on('DFP External Storage', {

	setup: frm => {
		frm.button_remote_files_list = null
	},

	refresh: function(frm) {
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

		frappe.db.get_list(
			'DFP External Storage by Folder',
			{fields: ['name','folder']}
		).then(data => {
			if (data && data.length) {
				let folders_name_not_assigned = data
					.filter(d => d.name != frm.doc.name ? d : null)
					.map(d => d.folder)
				frm.set_query('folders', function () {
					return {
						filters: {
							is_folder: 1,
							name: ['not in', folders_name_not_assigned],
						},
					}
				})

			}
		})

	},

})
