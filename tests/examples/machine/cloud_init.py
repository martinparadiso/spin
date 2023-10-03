import spin

with spin.define.vm("ubuntu", "focal") as vm:
    vm.cloud_init = {
        "users": [
            "default",
            {
                "name": "ubuntu",
                "ssh_authorized_keys": [spin.content("./tests/data/key.pub")],
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
            },
        ]
    }
