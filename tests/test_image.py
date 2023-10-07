import pathlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from spin.image.image import Image

EXPECTED_SCRIPT = {
    "on_creation": [],
    "on_start": [],
    "on_install": [
        {"action": "wait", "time": 15},
        {"action": "type", "stream": "root"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 2},
        {"action": "type", "stream": "setup-alpine -c ANSWER_FILE"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {
            "action": "type",
            "stream": "sed 's/DISKOPTS=none/DISKOPTS=\"-m sys \\/dev\\/vda\"/' -i ANSWER_FILE",
        },
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "cat ANSWER_FILE"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "setup-alpine -e -f ANSWER_FILE"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "y"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "poweroff"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "wait", "time": 30},
        {"action": "eject-cdrom", "regex": ".+alpine.+"},
        {"action": "boot"},
        {"action": "wait", "time": 30},
        {"action": "type", "stream": ""},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "root"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 2},
        {
            "action": "type",
            "stream": "sed -E 's/#(.+\\/v.+\\/community)/\\1/' -i /etc/apk/repositories",
        },
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "cat /etc/apk/repositories"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "apk update"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "apk add cloud-init"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "setup-cloud-init"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
        {"action": "type", "stream": "reboot"},
        {"action": "type", "stream": "{enter}"},
        {"action": "wait", "time": 0.25},
    ],
}


class TestProperties:
    def test_origin_time(self, tmp_path: pathlib.Path) -> None:
        file = tmp_path / "file.img"
        file.touch()
        image = Image(file=file)
        assert "origin_time" in image.dict()

        now = datetime.now()
        image.props.origin_time = now

        image = Image(**image.dict())
        assert image.props.origin_time == now


class TestImageDefinition:
    @pytest.mark.parametrize("name", [None, "linux-distro", "custom"])
    @pytest.mark.parametrize("tag", [None, "8", "2022"])
    def test_minimal(self, name, tag):
        import spin.define

        with spin.define.image(name, tag) as img:
            pass

        assert img.name == name
        assert img.tag == tag
        assert img.props.requires_install is None
        assert img.props.cloud_init is None
        assert img.props.type is None
        assert img.on_install is not None
