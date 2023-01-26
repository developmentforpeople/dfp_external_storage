
frappe.ui.form.on('DFP External Storage', {
	onload: function(frm) {
		console.log('onload')
	},

	validate: function(frm) {
		console.log('validate')
		// // clear linked customer / supplier / sales partner on saving...
		// if (frm.doc.links) {
		// 	frm.doc.links.forEach(function (d) {
		// 		frappe.model.remove_from_locals(d.link_doctype, d.link_name);
		// 	});
		// }
	},

	after_save: function(frm) {
		console.log('after save')
	},

	refresh: function(frm) {
		console.log('refresh')

		frm.set_query('folders', function () {
			return {
				filters: {
					is_folder: 1,
				},
			}
		})

		const field_folders = frm.get_field('folders')
		console.log('field_folders', field_folders)
		field_folders.df.onchange = () => {
			console.log('cambia!')
			let value = field_folders.get_value('folders')
			console.log('value: ', value)
		}

		// frappe.db.get_list(
		// 	'File',
		// 	{filters: {is_folder:1}}
		// ).then(data => {
		// 	if (data && data.length) {
		// 		console.log('data: ', data)
		// 	}
		// })

		frappe.db.get_list(
			'DFP External Storage by Folder',
			{fields: ['name','folder']}
		).then(data => {
			if (data && data.length) {
				let folders_name_not_assigned = data
					// .filter(d => {
					// 	if (d.name != frm.doc.name) {
					// 		return d
					// 	}
					// })
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
		// debugger
		console.log('frm.doc.name: ', frm.doc.name)
		// console.log('folders: ', folders)
		// console.log('folders_assigned: ', folders_assigned)

		// let folders_name_not_assigned = folders_assigned
		// .filter(d => {
		// 	debugger
		// 	if (d.name != frm.doc.name) {
		// 		return d.name
		// 	}
		// })
		// .map(r => {
		// 	debugger
		// 	return __(toTitle(frappe.unscrub(r)));
		// })

		// frm.set_query('folders', function () {
		// 	return {
		// 		filters: {
		// 			is_folder: 1,
		// 			name: ['in', folders_name_not_assigned],
		// 		},
		// 	}
		// })

	},

})
