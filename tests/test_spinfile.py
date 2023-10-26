"""Test the generation of a spinfile"""

import glob
import pathlib
import re
from unittest.mock import MagicMock, Mock, patch

import pytest
from conftest import python_examples

import spin.cli
import spin.utils.load
import spin.utils.spinfile_loader
from spin.image.image import Image
from spin.machine.machine import Machine
from spin.utils.load import Machinefile, Spinfolder

EXPECT_PYFILE = """# spinfile
import spin

with spin.define.vm("ubuntu", "jammy") as vm:
    pass
    # Change number of vCPUs
    # vm.hardware.cpus = 2

    # Change the ammunt of memory
    # vm.hardware.memory = spin.Size("2GiB")

    # Generate a cloud-init data source from the given YAML
    # For information on cloud-init visit:
    #   https://cloud-init.io/
    # vm.cloud_init = pathlib.Path("cloud.yaml")
    # or you can pass a dictionary following the
    # cloud-init structure:
    # vm.cloud_init = { 'users' : ['default'] }

    # Enable plugins
    # For instance to auto-generate cloud-init
    # vm.plugins = [spin.plugin.cloud_init]
"""


class TestSpinfileGeneration:
    """Test spinfile.py generation"""

    FILENAME = "spinfile.py"
    IMAGE = "ubuntu"
    TAG = "jammy"

    def test_basic_gen(self, tmp_path):
        tmp_folder = pathlib.Path(tmp_path)

        spin.cli.init(folder=tmp_folder, nametag=f"{self.IMAGE}:{self.TAG}")

        with open(tmp_folder / self.FILENAME, encoding="utf8") as spinfile:
            content = spinfile.read()

        assert content == EXPECT_PYFILE

    def test_no_folder(self, tmp_path):
        tmp_folder = pathlib.Path(tmp_path) / "i-dont-exist"

        with pytest.raises(Exception) as exce_info:
            spin.cli.init(folder=tmp_folder, nametag=f"{self.IMAGE}:{self.TAG}")

        assert (
            re.match(r"^Folder (.+) does not exist$", str(exce_info.value)) is not None
        )

    def test_existing_spinfile(self, tmp_path):
        tmp_folder = pathlib.Path(tmp_path)

        (tmp_folder / self.FILENAME).touch()

        with pytest.raises(Exception) as exce_info:
            spin.cli.init(folder=tmp_folder, nametag=f"{self.IMAGE}:{self.TAG}")

        assert (
            re.match(r"^There is already a file in (.+)$", str(exce_info.value))
            is not None
        )


class TestSpinfileLoad:
    @pytest.mark.parametrize("file", python_examples(spinfile_only=True))
    def test_load(self, file: str) -> None:
        found = spin.utils.spinfile_loader.spinfile(pathlib.Path(file), True)
        assert len(found) > 0

    @pytest.mark.parametrize("complete_def", [True, False])
    @patch(
        "spin.utils.spinfile_loader.importlib.util.spec_from_file_location",
        autospec=True,
    )
    def test_attribute_population(self, import_patch: Mock, complete_def: bool) -> None:
        """Check if the loading of the machine is done correctly"""
        fake_spinfile = MagicMock(pathlib.Path())
        fake_machine = MagicMock(Machine())
        fake_machine.hardware.disk.backing_image = None
        fake_image = MagicMock(Image())
        loader_under_testing = spin.utils.spinfile_loader.SpinfileLoader(
            fake_spinfile, complete_def
        )

        def mock_spin_define_vm(*args, **kwargs):
            loader_under_testing.start(fake_machine, fake_image)
            loader_under_testing.end(fake_machine)
            return MagicMock()

        import_patch.side_effect = mock_spin_define_vm
        loader_under_testing.load()

        import_patch.assert_called_once_with(fake_spinfile.name, fake_spinfile)
        assert loader_under_testing.call_count == 1
        assert fake_machine.spinfile == fake_spinfile


class TestMachinefile:
    @patch("spin.utils.load.open")
    @patch("spin.utils.load.json", autospec=True)
    @patch("spin.utils.load.Machinefile.load", autospec=True)
    def test_save_overwrite(
        self,
        load_patch: Mock,
        json_patch: MagicMock,
        open_patch: MagicMock,
        tmp_path: pathlib.Path,
    ) -> None:
        # NOTE: We copy the list to avoid mutations during save() call
        existing = [MagicMock(Machine(), uuid=i) for i in range(3)]
        load_patch.return_value = [*existing]
        to_save = MagicMock(Machine(), uuid=1)

        machinefile = Machinefile(tmp_path)
        machinefile.save(to_save, update=True)

        json_patch.dumps.assert_called_once()
        json_patch.dumps.assert_called_once_with(
            [vm.dict() for vm in [existing[0], existing[2], to_save]]
        )


class TestSpinfolder:
    def test_creation(self, tmp_path: pathlib.Path) -> None:
        spindir = tmp_path / ".spin"
        folder = Spinfolder(parent=tmp_path)

        assert len([*tmp_path.iterdir()]) == 0
        assert not folder.exists()

        folder.init()

        assert folder.location == spindir

        assert len([*tmp_path.iterdir()]) != 0
        assert folder.exists()
        assert spindir / "machines.json" in spindir.iterdir()

    def test_existig(self, tmp_path: pathlib.Path) -> None:
        folder = Spinfolder(parent=tmp_path)
        folder.init()
        assert folder.exists()

        folder = Spinfolder(parent=tmp_path)
        assert folder.exists()
