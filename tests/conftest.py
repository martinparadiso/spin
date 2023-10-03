import importlib
import os
import pathlib
import urllib.request

import pytest

import spin.define
import spin.utils.config
from spin.build.builder import Builder, RemoteImage
from spin.define.image import ManualInstall
from spin.image.image import Image


def pytest_addoption(parser):
    parser.addoption(
        "--requires-backend",
        action="store_true",
        default=False,
        help="run tests requiring a functional backend",
    )

    parser.addoption(
        "--super-slow",
        action="store_true",
        default=False,
        help="run tests that are *really* slow (several minutes)",
    )

    parser.addoption(
        "--proxy",
        default=None,
        type=str,
        help="indicate a proxy (probably with a cache for the tests to use) to cache downloads",
    )


def pytest_collection_modifyitems(config, items):
    run_requires_backend = config.getoption("--requires-backend")
    run_super_slow = config.getoption("--super-slow")
    # If both flags present, do nothing, all tests must run
    if run_requires_backend and run_super_slow:
        return
    skip_backend = pytest.mark.skip(reason="needs --requires-backend option to run")
    skip_slow = pytest.mark.skip(reason="needs --super-slow option to run")
    for item in items:
        if "requires_backend" in item.keywords and not run_requires_backend:
            item.add_marker(skip_backend)
        if "super_slow" in item.keywords and not run_super_slow:
            item.add_marker(skip_slow)


@pytest.fixture
def minimal_linux() -> Image:
    """Return a minimal image running Linux for testing.

    - The image has a password-less root, and
    - no SSH.

    Warning: The image may be retrieved from the internet and build, so the call
        is expected to be expensive.

    Returns:
        A small Linux image, and the root password.
    """
    with spin.define.image("alpine", "3.6") as alpine:
        alpine.retrieve_from = RemoteImage(
            "https://dl-cdn.alpinelinux.org/alpine/v3.16/releases/x86_64/alpine-virt-3.16.2-x86_64.iso",
        )
        alpine.props.architecture = "x86_64"
        alpine.props.type = "installation-media"

        with ManualInstall(alpine) as install:
            install.runs = "on_creation"
            install.connection = "serial"
            install.has_autologin = False

            with install.simulate_input() as si:
                si <<= r"""
                    root
                    setup-alpine -c ANSWER_FILE
                    sed 's/DISKOPTS=none/DISKOPTS=\"-m sys \\/dev\\/vda\"/' -i ANSWER_FILE
                    sed 's/USEROPTS.+/#USEROPTS=\"-m sys \\/dev\\/vda\"/' -i ANSWER_FILE
                    cat ANSWER_FILE
                    yes | setup-alpine -e -f ANSWER_FILE
                    poweroff
                """
                si.wait(10)
                si.eject_cdrom(regex=".+alpine.+")

    builder = Builder(alpine)
    builder.store_in_db = False
    builder.prepare()
    res = builder.build()

    if res.image is None:
        raise Exception(f"Build of test image failed: {res}")

    return res.image


@pytest.fixture
def test_proxy(pytestconfig):
    """Return a proxy URL, if the developer set one"""
    # NOTE: We *need* to force/reload urllib.requests; since it seems
    # environment variables are checked only once on import
    importlib.reload(urllib.request)
    KEY = "http_proxy"
    opt = pytestconfig.getoption("proxy")
    restore = os.environ.get(KEY, None)
    if opt:
        os.environ[KEY] = opt
    yield opt
    if restore is not None:
        os.environ[KEY] = restore
    elif KEY in os.environ:
        os.environ.pop(KEY)


@pytest.fixture
def configured_home(tmp_path: pathlib.Path):
    """Generate a functional spin configuration and environment to run tests"""

    assert tmp_path.is_dir()
    (tmp_path / ".config").mkdir()
    (tmp_path / ".local" / "state").mkdir(parents=True)
    (tmp_path / ".local" / "share").mkdir(parents=True)
    spin.initlib(home=tmp_path, user_conf=False)
    spin.utils.config.conf.init_conf()

    yield tmp_path
