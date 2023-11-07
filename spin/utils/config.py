"""Stores library-wide configuration
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, Optional, Type

from pydantic import BaseModel, BaseSettings
from xdg import BaseDirectory

import spin.utils.ui
from spin.backend.base import Backend
from spin.errors import TODO
from spin.utils import constants
from spin.utils.sizes import Size

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def load_from_toml(settings: Type[BaseSettings]) -> dict[str, Any]:
    """Load a TOML file as a dictionary

    Args:
        settings: Provided by pydantic.

    Returns:
        The content of the TOML file, in a Python dictionary.
    """
    location: Optional[pathlib.Path] = getattr(settings.__config__, "toml_conf", None)
    if location is None or not location.exists():
        return {}
    return tomllib.loads(pathlib.Path(location).read_text("utf-8"))


class BackendCommonSettings(BaseModel):
    """Common settings to all backends"""

    pool: Optional[str]


class PluginsSettings(BaseModel):
    """Stores all built-in plugin config. types.

    The class is empty by default, attributes are added dynamically
    through the plugin API.
    """


class MachineDefaults(BaseModel):
    """Default values for the machine parameters"""

    backend: str = "auto"
    cpus: int = 2
    memory: Size = Size("2GiB")
    disk_size: Size = Size("10GiB")
    pool: str = "spin"


class SharedFolders(BaseModel):
    """Values for mounting shared folders"""

    extra_fstab_o: Optional[str] = None


class Settings(BaseSettings):
    """Groups library-wide configuration parameters"""

    defaults: MachineDefaults = MachineDefaults()
    shared_folder: SharedFolders = SharedFolders()
    plugins: PluginsSettings = PluginsSettings()
    default_ssh_key: Optional[str] = None

    machine_folder_mode: int = 0o700
    """Mode for the *new* machine folders created."""

    orphan_folder_mode: int = 0o700
    """Mode for the *new* folders created in the orphan directory."""

    class Config:  # pylint: disable=missing-class-docstring
        load_toml: bool = True

        # FIXME: the XDG library will create the path; we do not want that here
        toml_conf: pathlib.Path

        @classmethod
        def customise_sources(  # pylint: disable=missing-function-docstring
            cls,
            init_settings,
            env_settings,
            file_secret_settings,
        ):
            cls.toml_conf = (
                pathlib.Path(BaseDirectory.save_config_path("spin")) / "conf.toml"
            )
            if not cls.load_toml:
                return init_settings, env_settings, file_secret_settings
            return init_settings, env_settings, load_from_toml, file_secret_settings


class Configuration:
    """
    Examples:

        Change the configuration folder for the current execution::

            from spin.utils.config import configuration as cfg
            print(cfg.config_folder)
    """

    def __init__(self, home: None | pathlib.Path = None) -> None:
        """
        Args:
            home: The home directory, from this point all the configuration
                folders and files will be created. The library follows
                XDG convention, if no home path is given, the library will
                store files in the corresponding XDG directories.

                If a path is given, a XDG style tree structure will be created,
                in particular ``.share/spin`` and ``.config/spin``.
        """

        self.settings: Settings
        """User customizable settings"""

        self.home: None | pathlib.Path
        """Root directory for all the configuration and state sub-folders.
        """

        self.reset(home)

    def reset(self, new_home: None | pathlib.Path) -> None:
        """Reset this object, pointing to the new home"""
        self.home = new_home
        self.load_settings()

    def load_settings(self, user_conf: bool = True) -> None:
        """Load user settings (`Settings`)"""
        old = Settings.Config.load_toml
        Settings.Config.load_toml = user_conf
        self.settings = Settings()
        Settings.Config.load_toml = old

    @property
    def config_folder(self) -> pathlib.Path:
        """The library-wide configuration folder.

        Contains user set configuration.
        """
        if self.home is None:
            return pathlib.Path(BaseDirectory.xdg_config_home) / "spin"
        return self.home / ".config" / "spin"

    @property
    def data_folder(self) -> pathlib.Path:
        """Folder for storage of user data files.

        The folder contains data generated by the application.
        """
        if self.home is None:
            return pathlib.Path(BaseDirectory.xdg_data_home) / "spin"
        return self.home / ".local" / "share" / "spin"

    @property
    def database_folder(self) -> pathlib.Path:
        """Folder for the local Image database.

        Stores all the image information, including image files.
        """
        return self.data_folder / "images"

    @property
    def database_file(self) -> pathlib.Path:
        """JSON file containing image information."""
        return self.data_folder / "images.json"

    @property
    def definitions_file(self) -> pathlib.Path:
        """SQLite file containing definitions."""
        return self.data_folder / "image_definitions.sqlite"

    @property
    def networks_file(self) -> pathlib.Path:
        """JSON file containing networks"""
        return self.data_folder / "networks.json"

    @property
    def groups_file(self) -> pathlib.Path:
        """JSON file containing groups"""
        return self.data_folder / "groups.json"

    @property
    def orphanage(self) -> pathlib.Path:
        """Folder (or symlink) containing machines created without spinfiles

        Machines created without a ``spinfile`` are stored here, each one in
        their individual folder.
        """
        return self.data_folder / "orphanage"

    @property
    def pools(self) -> pathlib.Path:
        """Folder containing storage *pools*.

        Some backends store all the disk files in a single directory,
        normally called a 'storage pool'. This directory stores all
        the spin pools.
        """
        return self.data_folder / "pools"

    @property
    def keys_folder(self) -> pathlib.Path:
        """Folder (or symlink) containing keys generated for specific machines."""
        return self.data_folder / "keys"

    @property
    def default_machine_folder(self) -> pathlib.Path:
        """Folder --relative to spinfile-- where the metadata about a machine is
        stored.

        For machine with no spinfile, the folder is *probably* created in
        :py:attr:`orphanage`.
        """
        return pathlib.Path(".spin")

    @property
    def default_machine_file(self) -> pathlib.Path:
        """File where the metadata about one or more machines is stored.

        The file is relative to :py:attr:`default_machine_filder`, and contains
        a list of serialized :py:class:`Machine` objects.
        """
        return pathlib.Path("machines.json")

    @property
    def tracker_file(self) -> pathlib.Path:
        """File containing all the tracked machines.

        For more information see :py:class:`Tracker`.
        """
        return self.data_folder / "tracker.json"

    def make_base_folders(self, *, dry_run: bool = False) -> None:
        """Make the parent folders, normally responsibility of the OS.

        This function creates the base 'spin' folder for data and configuration,
        if possible by calling XDG.
        """
        if self.home is None:
            if dry_run:
                return
            BaseDirectory.save_config_path("spin")
            BaseDirectory.save_data_path("spin")
        else:
            if dry_run:
                return
            self.config_folder.mkdir(exist_ok=True)
            self.data_folder.mkdir(exist_ok=True)

    def init_conf(self, dry_run: bool = False) -> int:
        """Initialize the configuration in the specified folder.

        Args:
            dry_run: If set to ``True`` do not create any file or folder

        Raises:
            Exception: If some of the folders or files exist.
        """

        dir_modes = {
            self.orphanage: 0o770,
            self.pools: 0o770,
            self.database_folder: 0o740,
            self.keys_folder: 0o700,
        }
        file_modes = {
            self.tracker_file: 0o600,
            self.database_file: 0o600,
            self.networks_file: 0o600,
            self.groups_file: 0o600,
        }

        init_content = {
            self.tracker_file: "{}",
            self.database_file: json.dumps({"images": {}}),
            self.networks_file: json.dumps({}),
            self.groups_file: json.dumps({}),
        }

        if not self.data_folder.exists():
            self.make_base_folders(dry_run=dry_run)

        exist = [f for f in {*dir_modes.keys(), *file_modes.keys()} if f.exists()]
        if len(exist) != 0:
            raise Exception(
                (
                    "Cannot initialize configuration."
                    f"Folders already present: {[str(f) for f in exist]}"
                )
            )

        for dirpath, mode in dir_modes.items():
            spin.utils.ui.instance().notice(f"Creating folder {str(dirpath)}")
            if dry_run:
                continue
            dirpath.mkdir(mode=mode)

        for filepath, mode in file_modes.items():
            spin.utils.ui.instance().notice(f"Creating file {str(filepath)}")
            if dry_run:
                continue
            filepath.touch(mode=mode)
            if filepath in init_content:
                with open(filepath, "w", encoding="utf8") as file:
                    file.write(init_content[filepath])

        return 0

    def default_backend(self) -> Type[Backend]:
        """Return the default backend for new machines"""
        import spin.plugin.api

        if self.settings.defaults.backend != "auto":
            # TODO: Implement backend loading
            raise TODO
        mod_path = {b.__module__: b for b in spin.plugin.api.register.backends}
        for back in constants.BUILTIN_PREFERED_BACKEND:
            if back in mod_path:
                return mod_path[back]
        return mod_path.popitem()[1]


def load_config(
    file: pathlib.Path,
    into: Configuration,
) -> None:
    """Load configuration from a file into a config. object.

    Args:
        data: dictionary compatible with :py:class:`ConfigFileElements`.
        dest: Configuration destination; typically the global configuration
            object.

    Raise:
        ValidationError: If the data provided is invalid.
    """

    # NOTE: We cannot use from_typeddict because it fails in Python <=3.8
    # class ModelConfig(BaseModel):
    #     config: ConfigFileElements
    #     extra = Extra.forbid

    with open(file, "rb") as file_stream:
        data = tomllib.load(file_stream)
    Settings(**data)


conf: Configuration
