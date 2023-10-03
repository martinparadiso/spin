"""Simple demonstration on how to forward port(s) from the host to the guest

The `Machine` object has a convenience attribute/property
`network` to ease simple tasks on the default network
configuration.
"""
import spin

# Syntax to declare a port forwarding
with spin.define.vm("ubuntu", "focal") as vm:
    vm.network.port_forward(8080, 80, "tcp")
    vm.options.wait_for_network = False


# Since this is just Python; any trick can be used
# to pass the ports. For instance to declare
# multiple ports without duplicating code:
with spin.define.vm("ubuntu", "focal") as vm:
    vm.options.wait_for_network = False
    for host, guest in [(2222, 22), (8080, 80)]:
        vm.network.port_forward(host, guest, "tcp")
    vm.options.wait_for_network = False
