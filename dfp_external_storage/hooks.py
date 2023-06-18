from . import __version__ as app_version

app_name = "dfp_external_storage"
app_title = "DFP External Storage"
app_publisher = "DFP"
app_description = "S3 compatible external storage for Frappe and ERPNext"
app_email = "developmentforpeople@gmail.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_js = "dfp_external_storage.app.bundle.js"
app_include_css = "dfp_external_storage.app.bundle.css"

# include js, css files in header of web template
# web_include_css = "/assets/dfp_external_storage/css/dfp_external_storage.css"
# web_include_js = "/assets/dfp_external_storage/js/dfp_external_storage.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "dfp_external_storage/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "dfp_external_storage.utils.jinja_methods",
# 	"filters": "dfp_external_storage.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "dfp_external_storage.install.before_install"
# after_install = "dfp_external_storage.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "dfp_external_storage.uninstall.before_uninstall"
# after_uninstall = "dfp_external_storage.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "dfp_external_storage.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }
override_doctype_class = {
	"File": "dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage.DFPExternalStorageFile",
}

page_renderer = [
	"dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage.DFPExternalStorageFileRenderer",
]

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
#	}
# }

# DFP: More info about doc event hooks: https://frappeframework.com/docs/v13/user/en/basics/doctypes/controllers
doc_events = {
	"File": {
		"on_update": "dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage.hook_file_on_update",
		"before_save": "dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage.hook_file_before_save",
		"after_delete": "dfp_external_storage.dfp_external_storage.doctype.dfp_external_storage.dfp_external_storage.hook_file_after_delete",
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"dfp_external_storage.tasks.all"
# 	],
# 	"daily": [
# 		"dfp_external_storage.tasks.daily"
# 	],
# 	"hourly": [
# 		"dfp_external_storage.tasks.hourly"
# 	],
# 	"weekly": [
# 		"dfp_external_storage.tasks.weekly"
# 	],
# 	"monthly": [
# 		"dfp_external_storage.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "dfp_external_storage.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "dfp_external_storage.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "dfp_external_storage.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]


# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"dfp_external_storage.auth.validate"
# ]

# Translation
# --------------------------------

# Make link fields search translated document names for these DocTypes
# Recommended only for DocTypes which have limited documents with untranslated names
# For example: Role, Gender, etc.
# translated_search_doctypes = []
