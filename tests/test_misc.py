from __future__ import annotations

import pathlib
from unittest.mock import Mock, patch

import pytest

import spin.locks
import spin.machine.tracker
import spin.plugin.api.load


class TestPluginLoad:
    """Test the plugin loading submodule"""

    @patch("spin.plugin.api.load.modules", new=[])
    @patch("spin.plugin.api.load.importlib", autospec=True)
    def test_single_load(self, import_mock: Mock) -> None:
        assert len(spin.plugin.api.load.modules) == 0

        plugin = Mock()
        import_mock.import_module.return_value = Mock()

        spin.plugin.api.load.load_plugin(plugin)

        import_mock.import_module.assert_called_once_with(plugin)
        assert spin.plugin.api.load.modules == [import_mock.import_module.return_value]

    @pytest.mark.parametrize("extra", [[], [Mock(str) for _ in range(3)]])
    @patch("spin.plugin.api.load.importlib", autospec=True)
    def test_core(self, importlib_mock: Mock, extra: list[str]) -> None:
        """Test the basic full-plugin load"""
        importlib_mock.import_module.side_effect = lambda m: m
        with patch("spin.plugin.api.load.modules", new=[]):
            assert len(spin.plugin.api.load.modules) == 0

            spin.plugin.api.load.load_plugins(extra)

            assert (
                spin.plugin.api.load.modules
                == spin.plugin.api.load.BUILTIN_PLUGINS + extra
            )


class TestExitProcedure:
    @patch("spin.exit_procedure_called", new=False)
    def test_exit_procedure(self) -> None:
        callback_mock = Mock()
        spin.locks.exit_callbacks.append(callback_mock)

        spin.exit_procedure()

        callback_mock.assert_called_once_with()

        spin.exit_procedure()

        callback_mock.assert_called_once_with()


def test_new_home(configured_home: pathlib.Path) -> None:
    """Test the `configured_home` fixture is working properly."""
    assert spin.machine.tracker.conf.home == configured_home


def test_no_jsondump() -> None:
    """
    json.dump(stream, obj) results in a broken stream if the serialization
    fails. json.dumps(obj) and a later stream.write() is preferred."""

    def check_file(path: pathlib.Path) -> list[int]:
        ret: list[int] = []
        lines = path.read_text().splitlines()
        for line in lines:
            if "json.dump(" in line:
                ret.append(lines.index(line))
        return ret

    def traverse_dir(path: pathlib.Path) -> list[str]:
        bad_lines: list[str] = []
        for elem in path.iterdir():
            if elem.is_dir():
                bad_lines.extend(traverse_dir(elem))
            elif elem.is_file() and elem.suffix == ".py":
                bad_lines.extend(f"{str(elem)}:{line}" for line in check_file(elem))
        return bad_lines

    spin_folder = pathlib.Path(__file__).parent.parent / "spin"
    bad_lines = traverse_dir(spin_folder)
    for line in bad_lines:
        print(line)
    assert len(bad_lines) == 0
