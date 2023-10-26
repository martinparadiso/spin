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

global_wakeups: set[Event] = set()
"""Collection of Events that need waking up in case of emergency.

For instance: a thread is reading from a console port/tty file, and
the user sends CTRL-C/SIGINT; the thread *must* leave an Event in this
pool to wake him up to signal the end of the processing.
"""


def signal_stop(signum=None, frame=None) -> None:
    """Upon call, :py:attr:`process_stop` is set.

    This function can be used to stop all threads of execution upon failure.
    """
    process_stop.set()
    for wakeup in global_wakeups:
        wakeup.set()


for s in [signal.SIGINT]:
    signal.signal(s, signal_stop)


exit_callbacks: list[Callable[[], None]] = []
"""List of functions to call before exiting.

Normally contains ports and connections that must be manually 
closed. Anyone can insert callbacks in here.
"""
