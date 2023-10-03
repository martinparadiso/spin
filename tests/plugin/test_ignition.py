"""Test the ignition plugin"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from spin.plugin import ignition

MINIMAL_IGNITION = {
    "ignition": {"version": "3.1.0"},
    "passwd": {"users": [{"name": "root"}]},
}


def test_ssh_key_add() -> None:
    under_test = ignition.AddSSHKeyToIgnition

    credential = Mock(login="some")
    machine = Mock(ignition=MINIMAL_IGNITION)
    task = Mock(machine=machine, credential=credential)

    with pytest.raises(ValueError) as exce:
        under_test(MagicMock()).solve(task)
    exce.match(".*already has an username.*")

    task.credential.login = None
    under_test(MagicMock()).solve(task)
    assert (
        task.credential.pubkey
        in task.machine.ignition["passwd"]["users"][0]["sshAuthorizedKeys"]
    )

    credential2 = Mock(login=None)
    task2 = Mock(
        **{"machine.ignition": task.machine.ignition, "credential": credential2}
    )
    under_test(MagicMock()).solve(task2)
    assert (
        task.credential.pubkey
        in task2.machine.ignition["passwd"]["users"][0]["sshAuthorizedKeys"]
    )
    assert (
        task2.credential.pubkey
        in task2.machine.ignition["passwd"]["users"][0]["sshAuthorizedKeys"]
    )
    assert len(task.machine.ignition["passwd"]["users"][0]["sshAuthorizedKeys"]) == 2
