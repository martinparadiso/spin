"""Byte transfer wrapper, with callback functionality
"""

from __future__ import annotations

import datetime
import re
import urllib.error
import urllib.request
from typing import Any, BinaryIO, Callable


class NetworkTransfer:
    """Takes two context manager, and transfers from one to the other

    The class main goal is to simplify transfer of network resources while
    providing a callback for progress.
    """

    def __init__(
        self,
        source: str,
        destination: None | BinaryIO,
        chunksize: int = 4 * 1024 * 1024,
    ):
        """
        Args:
            source: an URL to pull the resource from. Anything supported by `urllib`
                is accepted.
            destination: destination stream of the content, can be omitted during
                object creation, but *must* be supplied before download().
            chunksize: bytes to transfer in each iteration.
        """
        self.requested_url: str = source
        """The remote content retrieval URL."""

        self.destination: None | BinaryIO = destination
        """A writeable byte buffer, such as a binary file, to put the downloaded content"""

        self.chunksize: int = chunksize
        """Amount of bytes to retrieve at a time."""

        self._remote = None

        self.url: Any
        """Actual URL after resolution and redirection"""

        self.size: None | int = None
        """Size informed by remote"""

        self.filename: None | str = None
        """Output filename"""

        self.time: None | datetime.timedelta = None
        """Time it took to download the data"""

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()

    def open(self) -> NetworkTransfer:
        """Open the communication with remote."""
        problem = True
        try:
            self._remote = urllib.request.urlopen(self.requested_url)
            if self._remote is None:
                raise ValueError("Could not connect")
            self.url = self._remote.url
            self.size = int(self._remote.headers["Content-Length"])
            expected_filename = re.match("^.+/(.+)$", self.url)
            if expected_filename is not None:
                self.filename = expected_filename.group(1)
            else:
                self.filename = "spin-image.img"
            problem = False
            return self
        finally:
            if problem and self._remote is not None:
                self._remote.close()

    def close(self):
        """Close the communication with remote"""
        if self._remote is not None:
            self._remote.close()

    def redirected(self) -> bool:
        """Check if the server redirected the URL

        Returns:
            bool: True if redirected, false if not
        """
        return self.requested_url != self.url

    def download(self, callback: None | Callable[[int, int], None] = None):
        """Download the content, call callback periodically

        Args:
            callback: A callable, which has to accept two arguments: current
                transferred and expected transfer. Will be called periodically.
        """
        if self._remote is None or self.size is None:
            raise ValueError("You must call open() before download.")

        if self.destination is None:
            raise ValueError("Destination resource cannot be None")

        with self._remote as source, self.destination as dest:
            start = datetime.datetime.now()
            finish = False
            transfer = 0
            while not finish:
                tmp = source.read(self.chunksize)
                transfer += len(tmp)
                finish = len(tmp) < self.chunksize
                if callback is not None:
                    callback(transfer, self.size)
                dest.write(tmp)
            self.time = datetime.datetime.now() - start
