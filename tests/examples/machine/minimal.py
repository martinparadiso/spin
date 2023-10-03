import spin

with spin.define.vm("ubuntu", "focal") as vm:
    vm.options.wait_for_network = False
    vm.options.wait_for_ssh = False
