"""Misceallaneous checks used by libvirt"""

from __future__ import annotations

import subprocess


def accept_ra_configured() -> bool:
    """Check if ``accept_ra`` is set to 2"""
    try:
        ps = subprocess.run(
            ["sysctl", "-n", "net.ipv6.conf.all.accept_ra"],
            capture_output=True,
            check=False,
        )
        return ps.stdout.decode().strip() == "2"
    except FileNotFoundError:
        return False
