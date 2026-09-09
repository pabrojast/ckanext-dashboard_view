from setuptools import find_packages, setup

setup(
    name="ckanext-dashboard_view",
    version="0.1.0",
    description="Manually authored, embeddable Chart.js dashboards for CKAN tabular resources",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    license="AGPL-3.0-or-later",
    python_requires=">=3.10",
    packages=find_packages(),
    namespace_packages=["ckanext"],
    include_package_data=True,
    zip_safe=False,
    install_requires=["duckdb==1.5.5", "openpyxl==3.1.5", "defusedxml>=0.7.1,<1", "requests>=2.31,<3", "setuptools>=68,<81"],
    extras_require={"test": ["pytest>=7.4,<9", "build>=1,<2", "Flask-WTF>=1.0,<2"],
                    "demo": ["Flask>=2.2,<3", "Werkzeug<3"]},
    entry_points={"ckan.plugins": ["dashboard_view=ckanext.dashboard_view.plugin:DashboardViewPlugin"]},
)
