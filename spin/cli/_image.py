"""Module containing all the CLI/high level interface"""

from __future__ import annotations

import argparse

import spin.utils.config
from spin.cli._register import CallSignature, Return, cli_command
from spin.utils import ui


@cli_command(
    "update-database", help="Update (or initialize) the image definition database"
)
def cmd(parser: argparse.ArgumentParser) -> CallSignature:
    parser.add_argument(
        "--init",
        help="create the database if doesn't exist",
        action="store_true",
    )

    def callback(args: argparse.Namespace) -> Return:
        import spin.plugin.api.register
        from spin.image.database import DefinitionDatabase

        defdb = DefinitionDatabase(
            "sqlite:///" + str(spin.utils.config.conf.definitions_file.absolute())
        )

        if not defdb.exists():
            if not args.init:
                ui.instance().fatal("Database not present, use --init to create")
                return Return(-1)
            defdb.initdb()

        spin.plugin.api.register.global_register.populate_image_database(
            defdb, ui=ui.instance()
        )

        return Return(0)

    return callback


@cli_command("list-definitions", help="List available image definitions")
def list_defs(parser: argparse.ArgumentParser) -> CallSignature:
    parser.add_argument("--name", help="Show only images matching NAME")
    parser.add_argument("--tag", help="Show only images matching TAG")
    parser.add_argument("--digest", help="Show only the image matching DIGEST")
    parser.add_argument("--source", help="Show only images created by SOURCE")

    def callback(args: argparse.Namespace) -> Return:
        import spin.plugin.api.register
        from spin.image.database import DefinitionDatabase

        defdb = DefinitionDatabase(
            "sqlite:///" + str(spin.utils.config.conf.definitions_file.absolute())
        )

        if not defdb.exists():
            ui.instance().fatal(
                "Database not present, use update-database --init to create"
            )
            return Return(-1)

        matching = defdb.query(
            name=args.name, tag=args.tag, digest=args.digest, module=args.source
        )

        class NoSource:
            pass

        ui.instance().tabulate(
            [
                (
                    img.name,
                    img.tag,
                    img.props.origin_time,
                    img.digest,
                    (img.module or NoSource).__name__,
                )
                for img in matching
            ],
            headers=["name", "tag", "date", "digest", "source"],
        )

        return Return(0)

    return callback
