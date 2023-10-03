"""Global locks and syncrhonization.

The module contains process-wide synchronization, such as:

- Signal capture and processing
- Global stop event
"""
from __future__ import annotations

import signal
from threading import Event
from typing import Callable

process_stop = Event()
"""Indicates the stop of all threads of execution.

The variable *must* be used by all threads, tasks and concurrent
execution functions to avoid handling resources.
"""


def signal_stop(signum=None, frame=None) -> None:
    """Upon call, :py:attr:`process_stop` is set.

    This function can be used to stop all threads of execution upon failure.
    """
    process_stop.set()


for s in [signal.SIGINT]:
    signal.signal(s, signal_stop)


exit_callbacks: list[Callable[[], None]] = []
"""List of functions to call before exiting.

Normally contains ports and connections that must be manually 
closed. Anyone can insert callbacks in here.
"""
