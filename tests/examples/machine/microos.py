"""Create a machine with the builtin MicroOS image"""

from __future__ import annotations

import spin
import spin.cli
import spin.machine.start_steps
import spin.plugin.ignition
from spin.utils import init_ui, ui

if __name__ == "__main__":
    init_ui("log", ui.DEBUG)

    with spin.define.vm("opensuse", "microos") as vm:
        vm.name = "test-microos"
        vm.plugins = [spin.plugin.ignition]

    spin.cli.up(vm)
    spin.cli.down(vm)
    spin.cli.destroy(vm, remove_disk=True)
