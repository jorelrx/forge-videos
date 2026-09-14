from forge.api.ranges import parse_range, ByteRange, RangeNotSatisfiable


def test_single_range_forms():
    assert parse_range("bytes=0-3", 10) == ByteRange(start=0, end=3)
    assert parse_range("bytes=4-", 10) == ByteRange(start=4, end=9)
    assert parse_range("bytes=-4", 10) == ByteRange(start=6, end=9)
