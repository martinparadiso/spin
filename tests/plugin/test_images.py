"""Test builtin image definition"""

from __future__ import annotations

import datetime
import http.server
import json
import pathlib
import socketserver
from threading import Thread
from unittest.mock import patch

import pytest

import spin.plugin.images
from spin.build.image_definition import RemoteImage


class FileServer:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.thread: Thread
        self.httpd: socketserver.TCPServer

    def _serve(self) -> None:
        def _build_handle(*args, **kwargs):
            kwargs["directory"] = self.path
            return http.server.SimpleHTTPRequestHandler(*args, **kwargs)

        with socketserver.TCPServer(("", 9921), _build_handle) as httpd:
            self.httpd = httpd
            self.httpd.serve_forever(poll_interval=0.05)

    def __enter__(self) -> FileServer:
        self.thread = Thread(target=self._serve)
        self.thread.start()
        return self

    def __exit__(self, *_):
        if hasattr(self, "httpd") and self.thread.is_alive():
            self.httpd.shutdown()
            self.thread.join()


@patch("spin.plugin.images.UBUNTU_REMOTE", new="localhost:9921")
def test_ubuntu_retrieval() -> None:
    with FileServer(
        pathlib.Path(__file__).parent.parent / "data" / "cloud-images.ubuntu.com/"
    ):
        images = spin.plugin.images.ubuntu_images()
        assert len(images) == 621


def test_ubuntu_single_extraction() -> None:
    getter = spin.plugin.images.UbuntuGetter("")
    with pytest.raises(KeyError):
        getter._parse_one_entry({})

    datafile = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "cloud-images.ubuntu.com"
        / "releases"
        / "streams"
        / "v1"
        / "com.ubuntu.cloud:released:download.json"
    )

    with open(datafile) as f:
        sample = json.load(f)["products"]["com.ubuntu.cloud:server:23.04:amd64"]

    result = getter._parse_one_entry(sample)

    assert len(result) == 14
    assert [i.props.origin_time for i in result] == [
        datetime.datetime(2023, 4, 20, 0, 0),
        datetime.datetime(2023, 5, 2, 0, 0),
        datetime.datetime(2023, 6, 2, 0, 0),
        datetime.datetime(2023, 6, 21, 0, 0),
        datetime.datetime(2023, 6, 30, 0, 0),
        datetime.datetime(2023, 7, 11, 0, 0),
        datetime.datetime(2023, 7, 14, 0, 0),
        datetime.datetime(2023, 7, 29, 0, 0),
        datetime.datetime(2023, 8, 10, 0, 0),
        datetime.datetime(2023, 8, 29, 0, 0),
        datetime.datetime(2023, 9, 13, 0, 0),
        datetime.datetime(2023, 9, 26, 0, 0),
        datetime.datetime(2023, 10, 3, 0, 0),
        datetime.datetime(2023, 10, 5, 0, 0),
    ]
    assert [
        i.retrieve_from.url("amd64")[len(getter.proto + "://" + getter.url) :]
        for i in result
        if isinstance(i.retrieve_from, RemoteImage)
    ] == [
        "server/releases/lunar/release-20230420/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230502/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230602/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230621/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230630/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230711/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230714/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230729/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230810/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230829/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230913/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20230926/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20231003/ubuntu-23.04-server-cloudimg-amd64.img",
        "server/releases/lunar/release-20231005/ubuntu-23.04-server-cloudimg-amd64.img",
    ]
