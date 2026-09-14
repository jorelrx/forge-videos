from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(ValueError):
    pass


def parse_range(value: str, size: int) -> ByteRange:
    if size <= 0 or not value.startswith("bytes=") or "," in value:
        raise RangeNotSatisfiable(value)
    spec = value.removeprefix("bytes=")
    if "-" not in spec:
        raise RangeNotSatisfiable(value)
    start_text, end_text = spec.split("-", 1)
    if not start_text:
        if not end_text.isdecimal() or int(end_text) <= 0:
            raise RangeNotSatisfiable(value)
        length = min(int(end_text), size)
        return ByteRange(start=size - length, end=size - 1)
    if not start_text.isdecimal() or (end_text and not end_text.isdecimal()):
        raise RangeNotSatisfiable(value)
    start = int(start_text)
    end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or end < start:
        raise RangeNotSatisfiable(value)
    return ByteRange(start=start, end=end)


def iter_file_range(path: Path, selected: ByteRange, chunk_size: int = 64 * 1024):
    with path.open("rb") as source:
        source.seek(selected.start)
        remaining = selected.length
        while remaining > 0:
            chunk = source.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
