# spinfile
import spin

with spin.define.vm("ubuntu", "focal") as vm:
    vm.ssh = [
        spin.SSHCredential(spin.content("tests/data/key.pub")),
        spin.read_key("tests/data/key.pub"),
        spin.gen_ssh_keys(),
    ]
    vm.options.wait_for_network = False
