import spin

with spin.define.vm("ubuntu", "focal") as vm:
    vm.cloud_init = {
        "users": [
            "default",
            {
                "name": "ubuntu",
                # In this case, *you* will need to supply your SSH key, since
                # the library does not know where you got the public key
                # comes from.
                "ssh_authorized_keys": [spin.content("./tests/data/key.pub")],
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
            },
        ]
    }

    vm.options.wait_for_ssh = False
