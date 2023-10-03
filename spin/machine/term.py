"""Terminal output manipulation capabilities"""
from __future__ import annotations

import dataclasses
import re
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Match, Optional, Tuple, TypeVar

from typing_extensions import Protocol


@dataclass
class State:
    """Store stateful information about the term"""

    cursor_stack: list[Tuple[int, int]] = dataclasses.field(default_factory=list)
    cursor_loc: int = 0


SequenceProcessorSignature = Callable[[Match[bytes], List[str], State], None]
sequence_processors: dict[re.Pattern[bytes], SequenceProcessorSignature] = {}
"""Stores all the escape sequence processor in the form of pattern -> function"""

F = TypeVar("F", bound=SequenceProcessorSignature)


def accept(*pattern: bytes) -> Callable[[F], F]:
    """Register a function as a escape sequence processor"""

    def inner(func: F) -> F:
        for pat in pattern:
            sequence_processors[re.compile(pat)] = func
        return func

    return inner


@dataclass
class Sequence:
    """Escape sequences used by xterm.

    Regex capture group names and nemonics are extracted from the document
    below.

    See:
        - https://www.x.org/docs/xterm/ctlseqs.pdf
    """

    ESC = b"\x1B"
    CSI = b"\x1B\\["

    Ps = b"(?P<Ps>[0-9]*)"  # As defined by xterm ctrseqs.pdf
    Pm = b"([0-9]*)(;[0-9]*)*"

    CR = b"\r"
    ICH = CSI + Ps + b"@"
    CUU = CSI + Ps + b"A"
    CUD = CSI + Ps + b"B"
    CUF = CSI + Ps + b"C"
    CUB = CSI + Ps + b"D"
    "CUrsor Back -- move cursor back *Ps* times."
    CUP = CSI + Pm + b"H"
    "CUrsor Position -- position the cursor in the given coord."
    EL = CSI + Ps + b"K"
    "Erase in Line -- Erase from left, right or whole line"
    DECSC = ESC + b"7"
    "Save Cursor"
    DECRC = ESC + b"8"
    "Restore Cursor"


@accept(Sequence.CUB)
def cub_repl(ctrlseq: Match[bytes], lines: list[str], state: State) -> None:
    """Replace CUB sequence by creating a new line with the same content, and put
    the cursor in the value set by CUB
    """
    n = int(str(ctrlseq["Ps"], "utf8") or "1")
    lines.append(lines[-1])
    state.cursor_loc -= n


@accept(Sequence.DECSC, Sequence.DECRC)
def dec(ctrlseq: Match[bytes], lines: list[str], state: State):
    """Transform save and restore cursor"""

    x: None | int
    y: None | int

    if ctrlseq.re.pattern == Sequence.DECSC:
        try:
            x = state.cursor_loc
            y = len(lines) - 1
            state.cursor_stack.append((x, y))
        except IndexError:  # In case there are not lines
            pass
        return

    if ctrlseq.re.pattern == Sequence.DECRC:
        x, y = state.cursor_stack.pop()
        lines.extend(lines[y:])
        state.cursor_loc = x
        return
    raise ValueError("Cannot process sequence")


@accept(Sequence.EL)
def el(ctrlseq: Match[bytes], lines: list[str], state: State):
    """
    *Erase in line* removes characters from the current working line; it
    is typically used for animations, progress bars, etc. Consdiering that,
    the best approach for loggifing the sequence is duplicate the current line,
    and remove characters.
    """
    n = int(str(ctrlseq["Ps"], "utf8") or "0")

    if n == 0:
        lines[-1] = lines[-1][: state.cursor_loc]
    elif n == 1:
        lines[-1] = " " * state.cursor_loc + lines[-1][state.cursor_loc :]
    elif n == 2:
        lines[-1] = " " * len(lines[-1])
    else:
        raise ValueError("Ps can only be 0, 1, 2")


@accept(Sequence.CUF, Sequence.ICH)
def move_cursor(ctrlseq: Match[bytes], lines: list[str], state: State) -> None:
    """Move the cursor forward N places"""
    n = int(str(ctrlseq["Ps"], "utf8") or "1")
    state.cursor_loc += n
    if len(lines[-1]) < state.cursor_loc:
        # If the cursor is beyond the end, extend with spaces
        extra = " " * (state.cursor_loc - len(lines[-1]))
        lines[-1] += extra


class StreamProcessor(Protocol):
    def __init__(self, loggifier: Loggifier) -> None:
        ...

    @classmethod
    def accepts(cls, data: Deque[int]) -> bool:
        """Returns ``True`` if the class can process the given bytes"""
        ...

    def process(self, data: Deque[int]) -> bool:
        """Process all the bytes in *data*.

        Returns:
            ``True`` if the processor can keep processing data; ``False``
            if the processor has completed their corresponding sequence.
        """
        ...


def make_stream_processor(
    loggifier: Loggifier, data: Optional[Deque[int]] = None
) -> StreamProcessor:
    return make_stream_processor_impl(loggifier, data)


class Loggifier:
    def __init__(self) -> None:
        self.lines: list[str] = [""]
        self.state: State = State()
        self.processor: StreamProcessor = make_stream_processor(self)
        self.raw: list[int] = []

    def add(self, data: bytes) -> list[str]:
        """Add new bytes sent by the guest. Return the new lines.

        Args:
            data: The new bytes sent by the guest machine.

        Returns:
            The new lines found in the bytes sent by the guest.
        """

        before = len(self.lines) - 1
        self.raw.extend(data)
        dequed_data = deque(data)
        while len(dequed_data) != 0:
            keep_going = self.processor.process(dequed_data)
            if not keep_going:
                if len(dequed_data) == 0:
                    self.processor = make_stream_processor(self)
                else:
                    self.processor = make_stream_processor(self, dequed_data)
        # Here -1 means do not print the current end line
        return self.lines[before:-1]


class StandardProcessor(StreamProcessor):
    """Process standard *Unicode* characters (i.e. no escape sequences)"""

    LINETERMINATION = {b"\n"[0], b"\r"[0]}
    REMOVE_CHARS = set(range(31)) - LINETERMINATION - {Sequence.ESC[0], b"\t"[0]}

    def __init__(self, loggifier: Loggifier) -> None:
        self.log = loggifier
        self.unicode_buf: list[int] = []
        self.prev_was_cr = False
        "Previous character was CR. Prevents double newline with CRLF"

    @classmethod
    def accepts(cls, data: Deque[int]) -> bool:
        return data[0] != Sequence.ESC[0]

    def process(self, data: Deque[int]) -> bool:
        while len(data) > 0:
            curr_byte = data[0]

            if curr_byte in self.LINETERMINATION:
                data.popleft()
                if not (curr_byte == ord("\n") and self.prev_was_cr):
                    self.log.lines.append("")
                self.log.state.cursor_loc = 0
                self.prev_was_cr = curr_byte == ord("\r")
                continue

            if curr_byte in self.REMOVE_CHARS:
                data.popleft()
                continue

            if curr_byte == Sequence.ESC[0]:
                return False

            char: None | bytes = None
            if curr_byte & 0b1000_0000 != 0 or len(self.unicode_buf) != 0:
                # Multi-byte unicode character, ignore the ugliness
                # of the ifs
                self.unicode_buf.append(data.popleft())

                byte1 = self.unicode_buf[0]

                if byte1 & 0b1110_0000 == 0b1100_0000:
                    if len(self.unicode_buf) == 2:
                        char = bytes(self.unicode_buf)
                        self.unicode_buf.clear()

                elif byte1 & 0b1111_0000 == 0b1110_0000:
                    if len(self.unicode_buf) == 3:
                        char = bytes(self.unicode_buf)
                        self.unicode_buf.clear()
                elif byte1 & 0b1111_1000 == 0b1111_0000:
                    if len(self.unicode_buf) == 4:
                        char = bytes(self.unicode_buf)
                        self.unicode_buf.clear()
            else:
                char = bytes([data.popleft()])

            if char is not None:
                cursor = self.log.state.cursor_loc
                self.log.lines[-1] = (
                    self.log.lines[-1][:cursor]
                    + str(char, encoding="utf8")  # HACK: Get encoding
                    + self.log.lines[-1][cursor + 1 :]
                )
                self.log.state.cursor_loc += 1

        return True


class CtrlSeqProc(StreamProcessor):
    """Control sequence processor"""

    def __init__(self, loggifier: Loggifier) -> None:
        self.log = loggifier
        self.seq_buffer: list[int] = []

    @classmethod
    def accepts(cls, data: Deque[int]) -> bool:
        return data[0] == Sequence.ESC[0]

    def is_complete(self) -> bool:
        """Evaluate a byte sequence

        Returns:
            True if the sequence is complete, False if needs more bytes.
        """
        seq = self.seq_buffer
        if len(seq) <= 1:
            return False

        if len(seq) == 2 and seq[0] == 0x1B:
            if 0x30 <= seq[1] <= 0x3F:
                # Private sequence
                return True

            return False

        if len(seq) > 2 and seq[0:2] == list(bytes("\x1B[", encoding="utf8")):
            return 0x40 <= seq[-1] <= 0x7E
        return False

    def process(self, data: Deque[int]) -> bool:
        while len(data) > 0:
            byte = data.popleft()

            self.seq_buffer.append(byte)

            if self.is_complete():
                sequence = bytes(self.seq_buffer)
                for pattern, action in sequence_processors.items():
                    res = pattern.match(sequence)

                    if res is not None:
                        action(res, self.log.lines, self.log.state)
                        return False
                # Fallback: do nothing
                return False
        return True


def make_stream_processor_impl(
    loggifier: Loggifier, data: Optional[Deque[int]] = None
) -> StreamProcessor:
    """Return a stream processor for the given byte sequence"""
    if data is None:
        return StandardProcessor(loggifier)
    order = [StandardProcessor, CtrlSeqProc]
    for proc in order:
        if proc.accepts(data):
            return proc(loggifier)
    raise ValueError("No stream processor for the given data")
