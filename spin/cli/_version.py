"""Returns version information"""


import sys

import yaml


def version() -> dict:
    """Returns a dictionary with several version information."""
    import pkg_resources

    from spin.plugin.api import register

    return {
        "spin": {
            "version": pkg_resources.get_distribution("spin").version,
            "commit": "Unknown",
        },
        "backends": ["libvirt"],
        "plugins": [
            *register.plugins,
        ],
    }


def print_version() -> None:
    class IndentTables(yaml.Dumper):
        def increase_indent(self, flow=False, *, indentless=None):
            return super().increase_indent(flow, False)

    print("spin — An underperforming VM manager\n")
    yaml.dump(version(), sys.stdout, indent=2, Dumper=IndentTables, sort_keys=False)
