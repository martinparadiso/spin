# spinfile
import spin
import spin.plugin.cloud_init

with spin.define.vm("ubuntu", "jammy") as vm:
    vm.plugins = [spin.plugin.cloud_init]
