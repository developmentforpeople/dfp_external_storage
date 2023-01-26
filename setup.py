from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in dfp_external_storage/__init__.py
from dfp_external_storage import __version__ as version

setup(
	name="dfp_external_storage",
	version=version,
	description="S3 compatible external storage for Frappe and ERPNext",
	author="DFP",
	author_email="developmentforpeople@gmail.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
