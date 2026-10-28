import struct

from nmssave import MAGIC, decompress, lz4_block


def test_literals_only():
    assert lz4_block(b"\x50hello", 5) == b"hello"


def test_overlapping_match():
    # литерал "ab", затем повтор с off=2 длиной 6 → "abababab"
    assert lz4_block(b"\x22ab\x02\x00", 8) == b"abababab"


def test_chunks():
    block = b"\x50hello"
    chunk = struct.pack("<4I", MAGIC, len(block), 5, 0) + block
    assert decompress(chunk * 2) == b"hellohello"
