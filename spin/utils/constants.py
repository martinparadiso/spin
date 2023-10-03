"""Collection of global constants and useful definitions"""
from __future__ import annotations

from typing import NamedTuple, Optional, Tuple, Union

from typing_extensions import Literal, TypeAlias, get_args

SPIN_ARCHITECTURE_CODES_LITERAL: TypeAlias = Literal["x86_64"]

ARCHITECTURE_CODES_LITERAL: TypeAlias = Literal[
    "AMD64",
    "amd64",
    "x86_64",
]
"""List of all *known* CPU architecture names"""

ARCHITECTURE_CODES: list[SPIN_ARCHITECTURE_CODES_LITERAL] = [
    *get_args(SPIN_ARCHITECTURE_CODES_LITERAL)
]
"""Currently supported architectures

The dictionary is a map of ``main-code -> known-aliases``; this allows for 
checking against other tools using different conventions.
"""


NORMALIZE_ARCHITECTURE_CODE: dict[
    ARCHITECTURE_CODES_LITERAL, SPIN_ARCHITECTURE_CODES_LITERAL
] = {
    "AMD64": "x86_64",
    "amd64": "x86_64",
    "x86_64": "x86_64",
}
"""Maps common aliases to spin internal preferred code"""

MACHINE_STATE_LITERAL = Literal[
    "DEFINED", "CREATED", "SHUTOFF", "RUNNING", "PAUSED", "UNKNOWN", "ERRORED"
]
"""States a guest machine can be in.

- ``DEFINED``: There is a Python object --probably in a `spinfile.py`--
  containing the guest definition. There is no `.spin` folder with metadata,
  no file in the host system indicating it's existence.
- ``CREATED``: A `.spin` folder exists, containing information about the
  machine and auxiliary files such as CDROM ISO(s). The disk file is present
  somewhere in the host system. The machine is not present in the backend.
- ``SHUTOFF``: Similar to ``CREATED``, but the machine is present in the
  backend; it will be listed by the backend tools.
- ``RUNNING``: The machine has been created, added to the backend and started.
- ``PAUSED``: Special functionality provided by the backend(s), where a machine
  processor is halted during execution. The guest is *mostly* unaware of the
  pause. Some backends can put a guest in a *paused* state automatically if
  they encounter an error. E. g. libvirt pauses a guest if a dynamically
  allocated disk image is full and the guest tries to write to it.
- ``UNKNOWN``: The library could not determined the state of the guest, for
  instance if the folder could not be found.
- ``ERRORED``: The backend reports an error in the guest.

A *simple* diagram of the situation::

    ┌─────────┐
    │ DEFINED │
    └────┰────┘
         ┃┌─────────┐
         ┗┥ CREATED │
          └────┰────┘
               ┃┌─────────┐
               ┗┥ SHUTOFF │
                └────┰────┘
                     ┃┌─────────┐    ┌╌╌╌╌╌╌╌╌┐
                     ┗┥ RUNNING ┝┅┅┅┅┥ PAUSED ╎
                      └─────────┘    └╌╌╌╌╌╌╌╌┘
"""


class OS:
    """Stores OS version information."""

    FamilyLiteral = Literal["posix", "windows"]

    SubfamilyLiteral = Literal["linux", "windows"]

    Distribution: TypeAlias = str
    """OS distribution"""

    Family = get_args(FamilyLiteral)
    """Broad OS family"""

    SubFamily = get_args(SubfamilyLiteral)
    """Specific OS family"""

    Version = Union[str, int, Tuple[int, ...]]

    class Identification(NamedTuple):
        """OS version structure."""

        family: Optional[OS.FamilyLiteral] = None
        subfamily: Optional[OS.SubfamilyLiteral] = None
        distribution: Optional[OS.Distribution] = None
        version: Optional[OS.Version] = None


SERIALIZABLE_TYPES = Union[None, str, int, float, bool, list, dict]

FeatureLiteral = Literal["prefer", "force", "no"]
"""Options available to features that may not be present.

Normally defaults to ``"prefer"`` so the guest can run, probably
with reduced performance or features.
"""

FEATURE_OPTIONS = get_args(FeatureLiteral)


BUILTIN_PREFERED_BACKEND = ["spin.plugin.libvirt.core.LibvirtBackend"]
"""Ordered list of preferred backends.

When setting up a new machine with no defined backend, the
library will choose according to this list; with descending
preference.
"""
