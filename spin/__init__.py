"""Library entry point.

Contains logic that *must* be exeuted under any invocation method.
The library executes --under any circunstances--, the following
sequence of actions:

- Load the configuration and settings.
- Setup global objects
- Load the builtin plugins.
- Load external plugins.
- Reload settings to populate plugin settings
- Setup the exit procedure.
- Import common utilities for defining spinfiles.
"""
from __future__ import annotations

import atexit
import importlib
import os
import pathlib
import sys
import tempfile
import threading

import spin.locks
import spin.plugin.api.load
import spin.utils
import spin.utils.config


def initlib(home: None | pathlib.Path = None, user_conf: bool = True) -> None:
    """Initialize the library.

    Can be called again to re-initialize in another point; for instance
    when running tests.
    """
    # Initialize config and globals ------------------------------------------------
    if not hasattr(spin.utils.config, "conf"):
        spin.utils.config.conf = spin.utils.config.Configuration(home=home)
    else:
        spin.utils.config.conf.reset(home)
    spin.utils.init_ui("auto")

    # Load builtin plugins and reload settings -------------------------------------
    spin.plugin.api.load.load_plugins()
    spin.utils.config.conf.load_settings(user_conf=user_conf)


initlib()

# Setup exit callback ----------------------------------------------------------
exit_procedure_called = False


def exit_procedure() -> None:
    """Some threads run until the program exists. For instance, those
    printing console port outputs. This function is in charge of joining
    all remaining threads"""
    if spin.exit_procedure_called:
        return
    spin.exit_procedure_called = True
    ui = spin.utils.ui.instance()

    for wakeups in spin.locks.global_wakeups:
        wakeups.set()

    for cb in spin.locks.exit_callbacks:
        cb()

    threads = threading.enumerate()
    if len(threads) > 1:
        ui.debug(f"Found threads: {[t.name for t in threads]}")
        for thread in threading.enumerate():
            if thread == threading.current_thread():
                continue
            ui.debug(f"Joining {thread.name}")
            thread.join(timeout=10)
            if thread.is_alive():
                ui.error(f"Thread {thread.name} still running")


atexit.register(exit_procedure)

# Load utilities for spinfiles -------------------------------------------------
from spin import define
from spin.image.local_database import LocalDatabase
from spin.machine.credentials import SSHCredential
from spin.machine.hardware import CDROM, Disk, SharedFolder
from spin.utils import content
from spin.utils.sizes import Size
from spin.utils.spinfile import gen_ssh_keys, read_key
