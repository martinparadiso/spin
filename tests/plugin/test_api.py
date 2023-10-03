"""Test the plugin API"""

from __future__ import annotations

import pytest

import spin.plugin.api.register
from spin.backend.base import Backend


def test_add_backend() -> None:
    reg = spin.plugin.api.register.PluginRegister()

    @reg.backend
    class FakeBackend(Backend):
        pass

    assert len(reg.backends) == 1
    assert FakeBackend in reg.backends
