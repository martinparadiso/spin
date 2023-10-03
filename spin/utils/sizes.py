"""Convert bytes to KB, MB, etc
"""

from __future__ import annotations

import re
from itertools import chain

from typing_extensions import Literal


class Size:
    """Digital sizes in bytes

    Args:
        bytes: The bytes to store. Either the number of bytes, or a string to
            parse
        mode: The output format, 'si' or 'binary' for 1000 and 1024 respectively
        length: The unit length: short for K, M... or long for Kilo, Mega...
    """

    _regex: re.Pattern[str]

    suffix_map = {
        "si": {
            "short": ["", "K", "M", "G", "T", "P", "E", "Z", "Y"],
            "long": [
                "",
                "Kilo",
                "Mega",
                "Giga",
                "Tera",
                "Peta",
                "Exa",
                "Zetta",
                "Yotta",
            ],
        },
        "binary": {
            "short": ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi", "Yi"],
            "long": [
                "",
                "Kibi",
                "Mebi",
                "Gibi",
                "Tebi",
                "Pebi",
                "Exbi",
                "Zebi",
                "Yobi",
            ],
        },
    }

    suffix_suffix_map = {"short": "B", "long": "Bytes"}

    @classmethod
    def regex(cls):
        """Return the regex to match any size"""

        if getattr(cls, "_regex", None) is not None:
            return cls._regex

        first_suffix = "|".join(
            chain(
                cls.suffix_map["si"]["short"],
                cls.suffix_map["si"]["long"],
                cls.suffix_map["binary"]["short"],
                cls.suffix_map["binary"]["long"],
            )
        )

        second_suffix = "|".join(
            [cls.suffix_suffix_map["short"], cls.suffix_suffix_map["long"]]
        )

        cls._regex = re.compile(
            f"^(?P<size>[0-9]+)(?P<suffix>{first_suffix})?(?P<ssuffix>{second_suffix})?$"
        )

        return cls._regex

    def __init__(
        self,
        size: int | str,
        fmt: Literal["binary", "si"] = "binary",
        length: Literal["long", "short"] = "short",
    ):
        self.bytes: int
        if isinstance(size, int):
            if size < 0:
                raise ValueError("Size must be positive")
            self.bytes = size
        else:
            as_str = self.regex().match(size)
            if as_str is None:
                raise ValueError(f"{size} does not look like a size")

            suffix = as_str["suffix"] if as_str["suffix"] is not None else ""
            if (
                suffix in self.suffix_map["si"]["short"]
                or suffix in self.suffix_map["si"]["long"]
            ):
                base = 10
                if suffix in self.suffix_map["si"]["short"]:
                    power = 3 * self.suffix_map["si"]["short"].index(suffix)
                else:
                    power = 3 * self.suffix_map["si"]["long"].index(suffix)
            elif (
                suffix in self.suffix_map["binary"]["short"]
                or suffix in self.suffix_map["binary"]["long"]
            ):
                base = 2
                if suffix in self.suffix_map["binary"]["short"]:
                    power = 10 * self.suffix_map["binary"]["short"].index(suffix)
                else:
                    power = 10 * self.suffix_map["binary"]["long"].index(suffix)
            else:
                raise ValueError(f"Unknown suffix {suffix}")

            if int(as_str["size"]) < 0:
                raise ValueError("Size must be positive")
            self.bytes = int(as_str["size"]) * pow(base, power)
        self.format = fmt
        self.length = length

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(size={self.bytes})"

    def __str__(self) -> str:
        div = 1024 if self.format == "binary" else 1000
        size = float(self.bytes)
        i = 0
        while size > div:
            size /= div
            i += 1

        return (
            f"{size:.2f}{self.suffix_map[self.format][self.length][i]}"
            f"{self.suffix_suffix_map[self.length]}"
        )

    def __eq__(self, __o: object) -> bool:
        return self.bytes == getattr(__o, "bytes", None)

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(
            pattern=cls.regex().pattern, examples=["512MiB", "4GB", "1TiB"]
        )

    @classmethod
    def validate(cls, v) -> Size:
        """Raise an exception if the value supplied is not the correct type"""
        if not isinstance(v, (str, int)):
            raise TypeError("String or int required")
        return cls(v)
