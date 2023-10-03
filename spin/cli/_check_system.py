"""Perform checks on the platform/system/host OS to determine capabilities"""

from __future__ import annotations

import pathlib
from typing import Callable

from spin.utils import ui

_check_list: list[Callable[[], tuple[bool, str]]] = []


def add_check(f: Callable[[], tuple[bool, str]]) -> Callable[[], tuple[bool, str]]:
    """Register a check to run later, upon user request."""
    _check_list.append(f)
    return f


def check_system(print_: bool = False) -> list[tuple[bool, str]]:
    """Run all the registered checks.

    Args:
        print_: If set to ``True``, print the results.
    """
    results = [c() for c in _check_list]
    if print_:
        items = [("OK" if ok else "!!", msg) for ok, msg in results]
        ui.instance().items(*items)
    return results


@add_check
def cpu_virt_instructions() -> tuple[bool, str]:
    """Check if the CPU has virtualization instructions.

    The function searches for ``vmx`` and ``svm`` instructions.
    """
    with open("/proc/cpuinfo", "r", encoding="ascii") as cpuinfo:
        flag_lines = [line for line in cpuinfo if line.startswith("flags")]

    all_vmx = all("vmx" in line for line in flag_lines)
    some_vmx = any("vmx" in line for line in flag_lines)
    all_svm = all("svm" in line for line in flag_lines)
    some_svm = any("svm" in line for line in flag_lines)

    msg = "Processor has "
    if some_vmx:
        msg += "Intel VT extensions"
        if not all_vmx:
            msg += ", but not in all cores."
        return True, msg
    if some_svm:
        msg += "AMD-V extensions"
        if not all_svm:
            msg += ", but not in all cores."
        return True, msg

    return False, "Could not find Intel VT or AMD-V extensions"


@add_check
def kvm_file() -> tuple[bool, str]:
    """Check if ``/dev/kvm`` is present"""
    present = pathlib.Path("/dev/kvm").is_char_device()
    if present:
        msg = "/dev/kvm is present; OS provides hardware virtualization"
    else:
        msg = "/dev/kvm is not present"
    return present, msg
