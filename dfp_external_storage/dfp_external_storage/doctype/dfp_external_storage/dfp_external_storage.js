
frappe.ui.form.on('DFP External Storage', {

	refresh: function(frm) {

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
