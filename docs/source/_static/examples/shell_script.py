# spinfile
import spin

USER = 'ubuntu'

with spin.define.vm('ubuntu', 'jammy') as vm:

    # Multiline command -- multiline python raw string
    vm.add_shell_script(r"""
    apt update --yes
    apt upgrade --yes
    apt install --yes --no-install-recommends build-essential
    """, runs='on_creation')

    # Single line command -- python string
    vm.add_shell_script("apt update -y && apt-upgrade -y",
                        runs='on_update')

    # Single command -- array of strings
    vm.add_shell_script([f"cat /home/{USER}/.ssh/id_rsa.pub"],
                        runs='on_creation')
