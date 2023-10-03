import spin
import spin.plugin.cloud_init

with spin.define.vm("ubuntu", "focal") as vm:
    vm.plugins = [spin.plugin.cloud_init]
    vm.on_creation <<= r"""
        lsb_release -a
        cat /proc/cpuinfo
        uname -a
    """
