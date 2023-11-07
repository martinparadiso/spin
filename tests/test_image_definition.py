"""Test the ImageDefinition class and related functionality, such
as serialization.
"""

from __future__ import annotations

import datetime
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from spin.build.image_definition import ImageDefinition
from spin.image.database import (
    Base,
    Database,
    DefinitionDatabase,
    ImageDefinitionModel,
    SourceModel,
    from_sql,
    to_sql,
)
from spin.machine.connection import ShellAction


def test_basic_sql() -> None:
    image_def = ImageDefinition()
    image_def.name = "image-name"
    image_def.tag = "image-tag"
    sql_obj = to_sql(image_def)
    assert sql_obj is not None

    with Session(create_engine("sqlite+pysqlite:///:memory:")) as session:
        Base.metadata.create_all(session.connection())
        session.add(sql_obj)
        session.flush()

        assert sql_obj.props.id == 1
        assert sql_obj.id == 1

        retrieved = session.get(ImageDefinitionModel, 1)
        session.flush()

        assert retrieved is not None
        assert retrieved == sql_obj

        image_def_from_sql = from_sql(retrieved)

        assert vars(image_def_from_sql) == vars(image_def)

        query = select(ImageDefinitionModel).where(
            ImageDefinitionModel.name == "image-name",
            ImageDefinitionModel.tag == "image-tag",
        )

        query_result = session.execute(query)
        assert query_result.scalar_one_or_none() == sql_obj

        session.commit()


class TestDefinitionToSQL:
    """Test to-sql conversion of an image definition"""

    def test_with_logic(self) -> None:
        """Should fail if an image with logic/actions is given"""
        img_def = ImageDefinition()
        img_def.on_install.append(ShellAction("date"))
        with pytest.raises(ValueError) as exce_info:
            to_sql(img_def)

        assert exce_info.match(".*contains.*logic.*")

    def test_attr_mutability(self) -> None:
        img_def = ImageDefinition()
        original_time = datetime.datetime.now()

        name_mock = img_def.name = MagicMock(name="name")
        img_def.tag = MagicMock(name="tag")
        img_def.props.origin_time = original_time

        as_sql = to_sql(img_def)

        assert as_sql.name is img_def.name
        assert as_sql.tag is img_def.tag
        assert as_sql.props.origin_time == original_time

        new_name = img_def.name = MagicMock(name="another-name")

        assert as_sql.name is name_mock
        assert img_def.name is new_name

        img_def.props.origin_time += datetime.timedelta(days=1)

        assert img_def.props.origin_time == original_time + datetime.timedelta(days=1)
        assert as_sql.props.origin_time == original_time

        img_def.props.usernames.append("user")

        assert len(img_def.props.usernames) == 1
        assert as_sql.props.usernames is None

    def test_invalid_username(self) -> None:
        img_def = ImageDefinition()
        img_def.props.usernames = ["root", "user,0"]
        with pytest.raises(ValueError) as exce_info:
            to_sql(img_def)

        assert exce_info.match(".*contains.*invalid.*character.*")

    def test_username_serialization(self) -> None:
        img_def = ImageDefinition()
        img_def.props.usernames = ["root", "user0"]

        img_sql = to_sql(img_def)

        assert img_sql.props.usernames is not None
        assert img_sql.props.usernames == "root,user0"

        img_def_from_sql = from_sql(img_sql)

        assert img_def_from_sql.props.usernames == img_def.props.usernames


class TestSource:
    """Test if the image source is properly set"""

    def test_empty(self) -> None:
        img_def = ImageDefinition()

        with DefinitionDatabase("sqlite+pysqlite:///:memory:") as db:
            db.initdb()
            db.add(img_def)
            found = db.query()
            assert len(found) == 1

            out = next(iter(found))
            assert out.module is None

    def test_query(self) -> None:
        """Query all the images provided by a given module"""
        img_a, img_b, img_c = (ImageDefinition() for _ in range(3))

        fake_module = ModuleType("fake-module")
        img_a.module = img_b.module = fake_module

        with DefinitionDatabase("sqlite+pysqlite:///:memory:") as db:
            db.initdb()
            db.add(img_a)
            db.add(img_b)
            db.add(img_c)

            with patch("spin.image.database.importlib") as import_patch:
                import_patch.import_module.return_value = fake_module
                found = db.query()
            assert len(found) == 3

            with patch("spin.image.database.importlib") as import_patch:
                import_patch.import_module.return_value = fake_module
                found = db.query(module="fake-module")
            assert len(found) == 2
            assert img_a.__dict__ in [i.__dict__ for i in found]
            assert img_b.__dict__ in [i.__dict__ for i in found]

    def test_with_module(self) -> None:
        img_a = ImageDefinition()
        img_a.module = ModuleType("fake-module")
        img_b = ImageDefinition()
        img_b.module = ModuleType("fake-module")

        with DefinitionDatabase("sqlite+pysqlite:///:memory:") as db:
            db.initdb()
            db.add(img_a)
            with patch("spin.image.database.importlib") as import_patch:
                import_patch.import_module.return_value = ModuleType("fake-module")
                found = db.query()
            assert len(found) == 1

            out = next(iter(found))
            assert out.module is not None
            assert out.module.__name__ == "fake-module"

            with Session(db._engine) as session:
                sources = session.query(SourceModel)
                assert len(sources.all()) == 1

            db.add(img_b)
            with patch("spin.image.database.importlib") as import_patch:
                import_patch.import_module.return_value = ModuleType("fake-module")
                found = db.query()
            assert len(found) == 2
            with Session(db._engine) as session:
                sources = session.query(SourceModel)
                assert len(sources.all()) == 1


class TestDuplicateInsertion:
    """Test the insertion of duplicate images"""

    def test_same_digest(self):
        """Image *should* fail directly if same digest already exists"""
        img_a, img_b = ImageDefinition(), ImageDefinition()
        img_a.digest = "".join(str(i) for i in range(24))

        img_a.name = "another-image-name"
        img_a.tag = "another-image-tag"
        img_b.digest = "".join(str(i) for i in range(24))

        with DefinitionDatabase("sqlite+pysqlite:///:memory:") as db:
            db.initdb()
            db.add(img_a)
            assert len(db.query(digest=img_a.digest)) == 1
            with pytest.raises(ValueError) as exce_info:
                db.add(img_b)
            assert exce_info.match(".*digest.*already.*in.*database")
            assert len(db.query(digest=img_a.digest)) == 1
