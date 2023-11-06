"""Test build procedure"""
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

import spin.build.builder
from spin.build.image_definition import ImageDefinition
from spin.image.image import Image


def test_parted_parser() -> None:
    INPUT = b"""BYT;
/dev/sda:480113590272B:scsi:512:512:gpt:ATA WDC WDS480G2G0A-:;
1:17408B:16777215B:16759808B::Microsoft reserved partition:msftres;
2:16777216B:68736253951B:68719476736B:ntfs:Basic data partition:msftdata;
3:68736253952B:206173110271B:137436856320B:ext4::;
4:206173110272B:411184398335B:205011288064B:ext4:SSD Data:;
7:411184398336B:479903875071B:68719476736B:ext4::;
6:479903875072B:480112541695B:208666624B:fat32::boot, esp;
    """

    result = spin.build.builder._extract_parted(INPUT)
    assert len(result) == 6


@patch("spin.build.builder.Database", autospec=True)
def test_mocked_build(
    db_mock: Mock,
    configured_home: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    fake_image_path = tmp_path / "fake_image.img"
    fake_image_path.touch()
    image_def = MagicMock(ImageDefinition())
    image_def.retrieve_from = str(fake_image_path)
    image_def.base = None
    db_mock.return_value.get.return_value = None

    POSSIBLE_COMBINTIONS = (
        [
            spin.build.builder.StartImage,
            spin.build.builder.LocalImage,
            spin.build.builder.ImageMetadata,
            spin.build.builder.SaveImage,
        ],
        [
            spin.build.builder.StartImage,
            spin.build.builder.ImageMetadata,
            spin.build.builder.LocalImage,
            spin.build.builder.SaveImage,
        ],
    )

    under_test = spin.build.builder.SingleBuilder(image_def)
    under_test.prepare()
    result = under_test.build()

    assert under_test.steps is not None
    assert [type(s) for s in under_test.steps] in POSSIBLE_COMBINTIONS
    assert result.success is True
    assert result.image is not None
    db_mock.return_value.get.assert_called_once()
    db_mock.return_value.add.assert_called_once()


@pytest.mark.parametrize("fail_index", [i for i in range(5)])
@pytest.mark.slow
@pytest.mark.requires_backend
def test_failure_during_build(
    fail_index: int,
    configured_home: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """Test the rollback-avility of the build procedure"""
    under_test = spin.build.builder.SingleBuilder(MagicMock(ImageDefinition()))
    under_test.image_definition.retrieve_from = str(tmp_path / "fake.img")
    (tmp_path / "fake.img").touch()

    steps = [MagicMock(spin.build.builder.BuildStep) for _ in range(5)]
    for i in range(5):
        steps[i].configure_mock(name=str(i))
    exception_obj = Exception()
    steps[fail_index].process.side_effect = exception_obj
    under_test.steps = steps  # type: ignore[assignment]
    result = under_test.build()

    assert result.image is None
    assert result.exception is not None
    assert result.exception is exception_obj

    for step in steps[: fail_index + 1]:
        step.process.assert_called_once()

    for rollback_expected in steps[:fail_index]:
        rollback_expected.rollback.assert_called_once()


class TestLocalImage:
    """Test machine image generation from local image"""

    @pytest.mark.parametrize(
        "in_out",
        [
            (None, False),
            ("./disk.img", True),
            ("", True),
        ],
    )
    def test_acceptance(self, in_out: tuple[Any, bool]) -> None:
        image_def = MagicMock(ImageDefinition())
        image_def.retrieve_from = in_out[0]
        builder = MagicMock(spin.build.builder.SingleBuilder(image_def))
        builder.image_definition.retrieve_from = in_out[0]
        under_test_cls = spin.build.builder.LocalImage

        assert under_test_cls.accepts(builder) is in_out[1]

    @patch("spin.build.builder.Database", autospec=True)
    def test_output(self, db_mock: MagicMock) -> None:
        """Make sure the image is added to the output"""
        retrieve_from = "/some/file/somewhere"
        image_def = MagicMock(ImageDefinition())
        image_def.retrieve_from = retrieve_from
        builder = MagicMock(spin.build.builder.SingleBuilder(image_def))
        builder.image_definition.retrieve_from = retrieve_from

        under_test = spin.build.builder.LocalImage(builder)
        under_test.process(builder)

        db_mock.assert_not_called()
        assert builder.image.file == pathlib.Path(image_def.retrieve_from)


class TestMetadataInheritance:
    """Test the inheritance of metadata from a base image to the new definition"""

    def test_acceptance(self) -> None:
        img_def = Mock(ImageDefinition())
        img_def.base = Mock(name="base_image")
        builder = Mock(name="builder", image_definition=img_def)
        assert spin.build.builder.InheritMetadata.accepts(builder) is True

        img_def.base = None
        assert spin.build.builder.InheritMetadata.accepts(builder) is False

    def test_inheritance(self) -> None:
        aa, ba, ca = Mock(), Mock(), Mock()

        class SourceClass:
            a = aa
            b = ba
            c = ca

        bb = Mock()

        class DestinationClass:
            b = bb

        cls = spin.build.builder.InheritMetadata
        obj = cls(MagicMock(spin.build.builder.SingleBuilder))

        obj.process(Mock(image=DestinationClass, base_image=SourceClass))

        assert getattr(DestinationClass, "a") == aa
        assert getattr(DestinationClass, "b") == bb
        assert getattr(DestinationClass, "c") == ca


class TestHelper:
    """Test the helper machine used for 'complex' builds"""

    @patch("spin.cli.down", autospec=True)
    @patch("spin.cli.destroy", autospec=True)
    @pytest.mark.parametrize("down_side_effect", [None, Exception])
    @pytest.mark.parametrize("destroy_side_effect", [None, Exception])
    def test_rollback(
        self,
        down_mock: Mock,
        destroy_mock: Mock,
        down_side_effect,
        destroy_side_effect,
    ) -> None:
        """Make sure the guest is destroyed on failure, even when `down()` and
        `destroy` raise some exception."""
        image_def = MagicMock(ImageDefinition())
        builder = MagicMock(spin.build.builder.SingleBuilder(image_def))

        down_mock.side_effect = down_side_effect
        destroy_mock.side_effect = destroy_side_effect

        under_testing = spin.build.builder.BootHelper(builder)

        if down_side_effect is None and destroy_side_effect is None:
            under_testing.rollback()
        else:
            with pytest.raises(Exception):
                under_testing.rollback()

        down_mock.assert_called_once_with(builder.helper, remove_disk=True)
        destroy_mock.assert_called_once_with(builder.helper)


@patch("spin.build.builder.generate_steps", new=lambda _: [])
class TestBaseImage:
    """Test the dependency-resolving capabilities of the builder"""

    def test_no_base(self) -> None:
        image_definition = MagicMock(ImageDefinition())
        image_definition.base = None

        under_test = spin.build.builder.Builder(image_definition)
        under_test.prepare()
        assert under_test.images == [image_definition]

    @patch("spin.build.builder.Database", autospec=True)
    def test_one_base(self, db_mock: MagicMock) -> None:
        image_definition = MagicMock(ImageDefinition())
        base = MagicMock(ImageDefinition(), base=None)
        image_definition.base = MagicMock()

        db_mock.return_value.get.return_value = base

        under_test = spin.build.builder.Builder(image_definition)
        under_test.prepare()
        assert under_test.images == [base, image_definition]

        db_mock.return_value.get.assert_called_with(image_definition.base)

    @patch("spin.build.builder.Database", autospec=True)
    def test_base_with_base(self, db_mock: MagicMock) -> None:
        grandparent = MagicMock(ImageDefinition(), base=None)
        parent = MagicMock(ImageDefinition())
        image_definition = MagicMock(ImageDefinition())

        def get_mock(request):
            if request == image_definition.base:
                return parent
            if request == parent.base:
                return grandparent
            raise ValueError

        db_mock.return_value.get.side_effect = get_mock

        under_test = spin.build.builder.Builder(image_definition)
        under_test.prepare()
        assert under_test.images == [grandparent, parent, image_definition]
        assert db_mock.return_value.get.call_count == 2

    @patch("spin.build.builder.Database", autospec=True)
    def test_base_with_existing_base(self, db_mock: MagicMock) -> None:
        grandparent = MagicMock(Image())
        parent = MagicMock(ImageDefinition())
        image_definition = MagicMock(ImageDefinition())

        def get_mock(request):
            if request == image_definition.base:
                return parent
            if request == parent.base:
                return grandparent
            raise ValueError

        db_mock.return_value.get.side_effect = get_mock

        under_test = spin.build.builder.Builder(image_definition)
        under_test.prepare()
        assert under_test.images == [parent, image_definition]
        assert db_mock.return_value.get.call_count == 2
