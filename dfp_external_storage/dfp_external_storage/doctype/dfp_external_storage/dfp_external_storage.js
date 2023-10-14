
frappe.ui.form.on('DFP External Storage', {

	setup: frm => {
		frm.button_remote_files_list = null
	},

	refresh: function(frm) {
		console.log('refresh!')
		frm.button_remote_files_list = frm.add_custom_button(
			__('All files in remote bucket'),
			() => {
				frm.call({ method: 'remote_files_list', doc: frm.doc, freeze: true })
				.then(r => {
					console.log('r', r)
					console.log('json:', JSON.stringify(r.message))
					frappe.msgprint(r.message)
				})
			},
			// __('Emails')
		)
		// frm.button_remote_files_list.addClass('disabled')

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
				console.log('folders_name_not_assigned: ', folders_name_not_assigned)
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
