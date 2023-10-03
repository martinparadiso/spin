"""Built-in plugin providing libvirt support"""

import spin.plugin.libvirt.steps
from spin.plugin.libvirt import checks
from spin.plugin.libvirt.core import *
from spin.plugin.libvirt.machine import MachineInterface as LibvirtMachine
