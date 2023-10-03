"""Local database of images"""

import pathlib
import string
from unittest.mock import Mock, PropertyMock, patch

import pytest

from spin.build.image_definition import ImageDefinition
from spin.image.database import LocalDatabase
from spin.image.image import Image


class TestLocalDatabase:
    DATABASE_FOLDER = "image-db"
    NULLIMG_1024_DIGEST = (
        "5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef"
    )
    NULLIMG_2048_DIGEST = (
        "e5a00aa9991ac8a5ee3109844d84a55583bd20572ad3ffcd42792f3c36b183ad"
    )

    dbfolder: pathlib.Path
    dbfile: pathlib.Path

    def test_init(self, tmp_path) -> None:
        self.__class__.dbfolder = tmp_path
        (self.__class__.dbfolder / "images").mkdir()
        self.__class__.dbfile = self.__class__.dbfolder / "images.json"
        self.__class__.dbfile.write_text('{"images": {}}')

    def init(self, db: LocalDatabase) -> None:
        db.image_folder = self.dbfolder / "images"
        db.db_file = self.dbfile

    def test_add_image(self, tmp_path):
        from pathlib import Path

        from spin import LocalDatabase

        db = LocalDatabase()
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

    def test_existing_image(self):
        from spin import LocalDatabase

        db = LocalDatabase()
        self.init(db)

        images = db.images(local_only=True)
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

    def test_add_another_img(self, tmp_path):
        from pathlib import Path

        from spin import LocalDatabase

        db = LocalDatabase()
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

    def test_existing_images(self):
        from spin import LocalDatabase

        db = LocalDatabase()
        self.init(db)

        images = db.images(local_only=True)
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

    @patch("spin.plugin.api.register", autospec=True)
    @patch("spin.image.database.Image", autospec=True)
    def test_return_priority(
        self,
        ImageMock: Mock,
        register_mock: Mock,
        tmp_path: pathlib.Path,
    ) -> None:
        """The database must prioritize Images over ImageDefinitions"""
        ImageDefinitionMock = Mock(ImageDefinition)

        def image_generator(*args, **kwargs):
            image = Mock(Image)
            image.configure_mock(**kwargs)
            return image

        ImageMock.configure_mock(side_effect=image_generator)
        register_mock.image_providers = []
        for i in range(5):
            imgdef = Mock(ImageDefinition)
            imgdef.configure_mock(name="name_" + string.ascii_lowercase[i])
            imgdef.configure_mock(tag="tag_a")
            imgdef.configure_mock(usable=False)
            provider = Mock(return_value=[imgdef])
            register_mock.image_providers.append(provider)
        tmp_dbfile = tmp_path / "tmp_db"
        with open(tmp_dbfile, "w", encoding="utf8") as data:
            data.write(
                """{"images": {
                    "a": {"name": "name_a", "tag": "tag_a"}, 
                    "b": {"name": "name_a", "tag": "tag_b"}
                }}"""
            )

        with patch("spin.image.database.conf", database_file=tmp_dbfile):
            imagedb = LocalDatabase()
            rets = imagedb.get(("name_a", "tag_a"))
            assert len(imagedb.definitions) == 5
            assert len(rets) == 2
            assert rets[0].usable
            assert not rets[1].usable
            assert isinstance(rets[0], Image)
            assert isinstance(rets[1], ImageDefinition)
