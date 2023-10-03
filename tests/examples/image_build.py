"""Build an image starting from another image."""

import spin

with spin.define.image("ubuntu", "libvirt-focal") as image:
    # Inherits all the properties and metadata from the
    # base image
    image.base = ("ubuntu", "jammy")

    image.experimental.expand_root = spin.Size("4GiB")

    # Execute arbitrary script during the build procedure
    image.run(
        r"""
        export DEBIAN_FRONTEND=noninteractive
        apt-get update --yes
        apt-get upgrade --yes
        apt-get install --yes --no-install-recommends \
            build-essential genisoimage qemu-kvm cpu-checker \
            libvirt-daemon-system python-is-python3 python3-pip \
            python3-dev python3-venv libc-dev pkg-config dnsmasq \
            libguestfs-tools libguestfs-dev libvirt-dev
    """
    )
