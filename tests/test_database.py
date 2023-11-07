"""Local database of images"""

import datetime
import pathlib
import string
from unittest.mock import Mock, PropertyMock, patch

import pytest

import spin.image.database
from spin.build.image_definition import ImageDefinition
from spin.image.database import Database
from spin.image.image import Image


@patch(
    "spin.image.database.DefinitionDatabase",
    autospec=True,
)
class TestDatabase:
    DATABASE_FOLDER = "image-db"
    NULLIMG_1024_DIGEST = (
        "5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef"
    )
    NULLIMG_2048_DIGEST = (
        "e5a00aa9991ac8a5ee3109844d84a55583bd20572ad3ffcd42792f3c36b183ad"
    )

    dbfolder: pathlib.Path
    dbfile: pathlib.Path

    def test_init(self, defmock: Mock, tmp_path) -> None:
        self.__class__.dbfolder = tmp_path
        (self.__class__.dbfolder / "images").mkdir()
        self.__class__.dbfile = self.__class__.dbfolder / "images.json"
        self.__class__.dbfile.write_text('{"images": {}}')

    def init(self, db: Database) -> None:
        db.local.image_folder = self.dbfolder / "images"
        db.local.db_file = self.dbfile

    def test_add_image(self, defmock: Mock, tmp_path):
        from pathlib import Path

        db = Database()
        self.init(db)

        img_file = Path(tmp_path) / "fake_image.img"
        with open(img_file, "wb") as img:
            img.write(bytes(1024))

        image = Image()
        image.file = img_file
        db.add(image)
        assert image.hexdigest() == self.__class__.NULLIMG_1024_DIGEST
        assert (
            image.file == self.__class__.dbfolder / "images" / self.NULLIMG_1024_DIGEST
        )
        assert image.file.exists()
        assert image.file.is_file()

    def test_existing_image(self, defmock: Mock):
        db = Database()
        self.init(db)

        images = db.images()
        assert len(images) == 1
        assert self.__class__.NULLIMG_1024_DIGEST in [
            str(i.hexdigest()) for i in images if isinstance(i, Image)
        ]

        img = db.get(self.__class__.NULLIMG_1024_DIGEST)
        assert img is not None
        assert img.hexdigest() == self.__class__.NULLIMG_1024_DIGEST
        assert img.name is None
        assert img.tag is None

        imgs = db.get((None, None))
        assert len(imgs) == 1
        for img_ in imgs:
            assert isinstance(img_, Image)
            assert img_.hexdigest() == self.__class__.NULLIMG_1024_DIGEST
            assert img_.name is None
            assert img_.tag is None

    def test_add_another_img(self, defmock: Mock, tmp_path):
        from pathlib import Path

        db = Database()
        self.init(db)

        image_path = Path(tmp_path) / "fake_image.img"
        with open(image_path, "wb") as img:
            img.write(bytes(2048))

        image = Image()
        image.file = image_path
        db.add(image)

        assert image.hexdigest() == self.__class__.NULLIMG_2048_DIGEST
        assert (
            image.file == self.__class__.dbfolder / "images" / self.NULLIMG_2048_DIGEST
        )
        assert image.file.exists()
        assert image.file.is_file()

    def test_existing_images(self, defmock: Mock):
        db = Database()
        self.init(db)

        images = db.images()
        assert len(images) == 2
        assert self.__class__.NULLIMG_1024_DIGEST in [
            str(i.hexdigest()) for i in images if isinstance(i, Image)
        ]
        assert self.__class__.NULLIMG_2048_DIGEST in [
            str(i.hexdigest()) for i in images if isinstance(i, Image)
        ]

        img = db.get(self.__class__.NULLIMG_1024_DIGEST)

        assert isinstance(img, Image)
        assert img.hexdigest() == self.__class__.NULLIMG_1024_DIGEST
        assert img.name is None
        assert img.tag is None

        imgs = db.get((None, None))
        assert len(imgs) == 2
        for img_ in imgs:
            assert isinstance(img_, Image)
            assert (
                img.hexdigest() == self.__class__.NULLIMG_1024_DIGEST
                or img.hexdigest() == self.__class__.NULLIMG_2048_DIGEST
            )
            assert img.name is None
            assert img.tag is None


@patch(
    "spin.image.database.DefinitionDatabase",
    autospec=True,
)
@patch("spin.image.local_database.Image", autospec=True)
def test_return_priority(
    ImageMock: Mock,
    defdb_mock: Mock,
    tmp_path: pathlib.Path,
) -> None:
    """The database must prioritize Images over ImageDefinitions"""

    def image_generator(*args, **kwargs):
        image = Mock(Image)
        image.configure_mock(**kwargs)
        return image

    image_defs = []
    for i in range(5):
        imgdef = Mock(ImageDefinition)
        imgdef.configure_mock(name="name_" + string.ascii_lowercase[i])
        imgdef.configure_mock(tag="tag_a")
        imgdef.configure_mock(usable=False)
        image_defs.append(imgdef)

    def query_mock(name=None, tag=None, digest=None):
        return [i for i in image_defs if i.name == name and i.tag == tag]

    ImageMock.configure_mock(side_effect=image_generator)
    defdb_mock.return_value.query.side_effect = query_mock
    tmp_dbfile = tmp_path / "tmp_db"
    with open(tmp_dbfile, "w", encoding="utf8") as data:
        data.write(
            """{"images": {
                "a": {"name": "name_a", "tag": "tag_a"}, 
                "b": {"name": "name_a", "tag": "tag_b"}
            }}"""
        )

    imagedb = Database()
    imagedb.local.db_file = tmp_dbfile
    rets = imagedb.get(("name_a", "tag_a"))
    assert len(rets) == 2
    assert rets[0].usable
    assert not rets[1].usable
    assert isinstance(rets[0], Image)
    assert isinstance(rets[1], ImageDefinition)


def test_best_selection() -> None:
    assert spin.image.database.best("monkey", None, []) is None

    image = Mock(spec=["name", "tag", "usable", "props"])
    image.configure_mock(
        **{
            "name": "monkey",
            "tag": None,
            "usable": True,
            "props.origin_time": None,
        }
    )
    image = Mock(Image())
    image.configure_mock(
        **{
            "name": "monkey",
            "tag": None,
            "usable": True,
            "props.origin_time": None,
        }
    )
    image_def = Mock(ImageDefinition())
    image_def.configure_mock(
        **{
            "name": "monkey",
            "tag": None,
            "usable": False,
            "props.origin_time": datetime.datetime.now(),
        }
    )
    pick_local_ret = spin.image.database.best("monkey", None, [image, image_def])
    assert pick_local_ret is not None
    assert pick_local_ret.local == image
    assert pick_local_ret.all == image_def

    newer = Mock(ImageDefinition())
    newer.configure_mock(
        **{
            "name": "monkey",
            "tag": None,
            "usable": False,
            "props.origin_time": datetime.datetime.now() + datetime.timedelta(days=1),
        }
    )
    pick_local_ret = spin.image.database.best("monkey", None, [image, image_def, newer])
    assert pick_local_ret is not None
    assert pick_local_ret.local == image
    assert pick_local_ret.all == newer

    pick_newer = spin.image.database.best("monkey", None, [image_def, newer])
    assert pick_newer is not None
    assert pick_newer.local is None
    assert pick_newer.all == newer
