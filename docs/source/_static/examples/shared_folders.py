# spinfile
import spin

with spin.define.vm('ubuntu', 'jammy') as vm:

    vm.shared_folders = [
        spin.SharedFolder('/var/lib/host', '/var/lib/guest')
    ]
