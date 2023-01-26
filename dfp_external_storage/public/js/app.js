
const class_external_storage_icon = 'dfp-storage-external-icon'

function dfp_s3_icon(title='') {
	let $icon = $(`<i class="fa fa-cloud-upload ${class_external_storage_icon}"></i>`)
	if (title) {
		$icon.attr('title', title)
	}
	return $icon
}

// Overrides for view FileView (Frappe file browser)
frappe.views.FileView = class DFPExternalStorageFileView extends frappe.views.FileView {

	setup_defaults() {
		this._dfp_external_storages = []
		return super.setup_defaults().then(() => {
			frappe.db.get_list('DFP External Storage', {fields: ['name', 'title']})
			.then(data => this._dfp_external_storages = data)
		})
	}

	_dfp_s3_title(dfp_external_storage) {
		let s3 = this._dfp_external_storages.filter(i => i.name == dfp_external_storage)
		return s3.length ? s3[0].title : __('No external storage name found :(')
	}

	prepare_datum(d) {
		d = super.prepare_datum(d)
		if (d.dfp_external_storage_s3_key && d.dfp_external_storage) {
			let title = this._dfp_s3_title(d.dfp_external_storage)
			d.subject_html += dfp_s3_icon(title).prop('outerHTML')
		}
		return d
	}

	render_grid_view() {
		super.render_grid_view()
		let $file_grid = $('.file-grid')
		this.data.forEach(file => {
			if (file.dfp_external_storage_s3_key && file.dfp_external_storage) {
				let $file = $file_grid.find(`[data-name="${file.name}"]`)
				let title = this._dfp_s3_title(file.dfp_external_storage)
				$file.append(dfp_s3_icon(title))
			}
		})
	}

}


// File doc override
frappe.ui.form.on('File', {

	refresh: function (frm) {
		let $title_area = frm.$wrapper[0].page.$title_area
		$title_area.find(`.${class_external_storage_icon}`).remove()
		if (frm.doc.dfp_external_storage_s3_key) {
			$title_area.prepend(dfp_s3_icon())
		}
	},

})


// Listing files overrides
frappe.listview_settings['File'] = {

	add_fields: ['dfp_external_storage_s3_key'],

	// onload: function (me) {
	// 	console.log('File:list:onload ', me)
	// },

	// get_indicator: function(doc) {
	// 	var colors = {
	// 		'Remote file': 'green',
	// 	}
	// 	let status = null
	// 	if (doc.dfp_external_storage_s3_key) {
	// 		status = 'Remote file'
	// 	}
	// 	return status ? [__(status), colors[status]] : []
	// },

	// button: {
	// 	// show: function (doc) {
	// 	// 	return doc.reference_name;
	// 	// },
	// 	// get_label: function () {
	// 	// 	return __("Open", null, "Access");
	// 	// },
	// 	// get_description: function (doc) {
	// 	// 	return __("Open {0}", [`${__(doc.reference_type)}: ${doc.reference_name}`]);
	// 	// },
	// 	// action: function (doc) {
	// 	// 	frappe.set_route("Form", doc.reference_type, doc.reference_name);
	// 	// },
	// },

	// refresh: function (me) {
	// 	console.log('File:list:refresh ', me)
	// },

}
