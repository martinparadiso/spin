"""CLI interface for building images"""

from __future__ import annotations

import argparse
import pathlib

import spin.build.builder
import spin.utils.spinfile_loader
from spin.build.image_definition import ImageDefinition
from spin.cli._register import CallSignature, Return, cli_command


def build(
    file: pathlib.Path,
) -> list[spin.build.builder.BuildResult]:
    """Build the image(s) found in file.

    Returns:
        A list where each entry is a ``tuple`` containing the build
        result and the image (if available).
    """
    if not file.exists():
        raise FileNotFoundError(file)
    if file.exists() and not file.is_file():
        raise ValueError(f"{file} is not a regular file")
    found = spin.utils.spinfile_loader.spinfile(file, disable_definition=False)
    images = [i for i in found if isinstance(i, ImageDefinition)]

    results: list[spin.build.builder.BuildResult] = []
    for image in images:
        builder = spin.build.builder.Builder(image)
        builder.prepare()
        results.append(builder.build())
    return results


@cli_command("build", help="Build one or more images")
def register(parser: argparse.ArgumentParser) -> CallSignature:
    parser.add_argument(
        "image",
        type=pathlib.Path,
        help="file containing one or more image definition(s)",
    )

    def adapter(args: argparse.Namespace) -> Return:
        results = build(args.image)

        if all(r.success for r in results):
            return Return(0)
        return Return(1)

    return adapter
