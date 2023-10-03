# spinfile
import spin

with spin.define.vm('ubuntu', 'jammy') as vm:
    
    vm.hardware.cpus = 4
    vm.hardware.memory = '4GiB'
    vm.hardware.disk = spin.hardware.Disk(size='20G')