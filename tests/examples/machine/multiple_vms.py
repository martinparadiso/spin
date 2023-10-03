# spinfile
import spin

with spin.define.vm("ubuntu", "focal") as first:
    first.name = "first"
    first.options.wait_for_network = False

with spin.define.vm("ubuntu", "focal") as second:
    second.name = "second"
    second.options.wait_for_network = False
