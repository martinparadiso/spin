import pathlib
from unittest.mock import patch

from spin.utils._ui_fancy import FancyUI


def test_progress_bar():
    stdout_buffer = []

    def _collect(*args, sep: str = " ", end="\n"):
        nonlocal stdout_buffer
        stdout_buffer.append(sep.join(args) + end)

    ui = FancyUI(0)
    with patch("spin.utils._ui_fancy.print", new=_collect):
        with ui.section("Trying to nest here"):
            for p in range(0, 100, 1):
                with ui.progress("hmm", "This is the footer") as progress:
                    progress.update(p / 100)

    unified = "".join(stdout_buffer).replace("\r\n", "\n")
    expected = (pathlib.Path(__file__).parent / "data" / "progress.out").read_text()

    assert unified == expected


if __name__ == "__main__":
    test_progress_bar()
