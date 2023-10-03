# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import pkg_resources

project = "spin"
copyright = "2022, Martín Paradiso"
author = "Martín Paradiso"

extra_vars = {
    "module_name": "spin",
    "min_python_version": "3.8",
    "project_url": "https://github.com/martinparadiso/spin",
    "pip_url": "``https://github.com/martinparadiso/spin``",
    "version": pkg_resources.get_distribution("spin").version,
    "version_output": f"``spin {pkg_resources.get_distribution('spin').version}``",
}

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.napoleon",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.todo",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for extensions
todo_include_todos = True
autosectionlabel_prefix_document = True

autoclass_content = "both"
autodoc_member_order = "bysource"

intersphinx_mapping = {"python": ("https://docs.python.org/3.10", None)}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

# -- Variables -----------------------------------------------------------------

rst_prolog = "\n".join([f".. |{k}| replace:: {v}" for k, v in extra_vars.items()])
