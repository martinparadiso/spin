import pathlib
import subprocess

import pytest

REMOTE = "http://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"


@pytest.mark.slow
@pytest.mark.super_slow
def test_image_open(tmp_path: pathlib.Path, test_proxy):
    """Fully test the viewing and editing of an image

    NOTE: you *may* want to put a proxy-cache in front of this
    to avoid re-downloading the image constantly. If you have a local
    cache you can put it in os.environ['http_proxy'] and it should work.
    """

    from hashlib import sha256

    from spin.image.edit import open_image

    env = {}
    if test_proxy:
        env["http_proxy"] = test_proxy
    subprocess.run(
        ["curl", REMOTE, "-o", "jammy.img"],
        env=env,
        cwd=tmp_path,
        check=True,
    )

    image_path = tmp_path / "jammy.img"

    def image_sum():
        hash_function = sha256()
        with open(image_path, "rb") as f:
            while True:
                data = f.read(4 * 1024 * 1024)
                if not data:
                    break
                hash_function.update(data)
        return hash

    pre_open_hash = image_sum()

    with open_image(image_path, read_only=True) as image:
        assert len(image.disks) == 1
        assert len(image.partitions) == 3
        assert image.disks == ["/dev/sda"]
        assert sorted(image.partitions) == ["/dev/sda1", "/dev/sda14", "/dev/sda15"]

        data = image.inspect()

        for k, v in data.items():
            print(f"{k} = {v}")

        assert len(data) != 0
        assert data["arch"] == "x86_64"
        assert data["os"] == ("linux", "ubuntu")
        assert data["version"] == (22, 4)
        assert data["package_manager"] == "apt"
        assert data["hostname"] == "ubuntu"

    post_open_hash = image_sum()

    assert pre_open_hash == post_open_hash

    with open_image(image_path, read_only=False) as image:
        assert len(image.disks) == 1
        assert len(image.partitions) == 3
        assert image.disks == ["/dev/sda"]
        assert sorted(image.partitions) == ["/dev/sda1", "/dev/sda14", "/dev/sda15"]

        data = image.inspect()

        for k, v in data.items():
            print(f"{k} = {v}")

        assert len(data) != 0
        assert data["arch"] == "x86_64"
        assert data["os"] == ("linux", "ubuntu")
        assert data["version"] == (22, 4)
        assert data["package_manager"] == "apt"
        assert data["hostname"] == "ubuntu"

        lines = image.read_lines("/etc/fstab")
        for line in lines:
            print(f"[/etc/fstab]: {line}")

        newl = [
            "",
            "### BEGIN SPIN MOUNTS ###",
            "some-stuff\t/mnt/\tauto\t0\t0",
            "### END SPIN MOUNTS ###",
        ]
        lines.extend(newl)

        print("\n\n")

        image.write("/etc/fstab", "\n".join(lines))

        lines = image.read_lines("/etc/fstab")
        for line in lines:
            print(f"[/etc/fstab]: {line}")

    with open_image(image_path, read_only=True) as image:
        cmp_lines = image.read_lines("/etc/fstab")
        assert lines == cmp_lines
