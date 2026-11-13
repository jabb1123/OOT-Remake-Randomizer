"""Tests for the little-endian SARC reader/writer."""

import struct
import unittest
from pathlib import Path

from oot_randomizer.sarc import (
    SarcError,
    read_sarc,
    sarc_name_hash,
    write_sarc,
)

SAMPLE_DIR = Path(
    r"C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405"
    r"\files\sarc_samples"
)


def _sfat(data: bytes) -> list[tuple[int, int, int, int]]:
    count, key = struct.unpack_from("<HI", data, 0x14 + 6)
    return [struct.unpack_from("<IIII", data, 0x20 + i * 16) for i in range(count)]


class SarcRoundTripTests(unittest.TestCase):
    FILES = {
        "Component/ModelInfo/X.game__component__ModelInfo.bgyml": b"YB\x07\x00" + b"\x01" * 61,
        "AI/X.root.ainb": b"AIB " + bytes(range(37)),
        "a": b"",
        "Long/Name/With/Several/Parts.bin": b"\xff" * 100,
        "zz.txt": b"hello",
    }

    def test_round_trip_preserves_content(self):
        packed = write_sarc(self.FILES)
        self.assertEqual(read_sarc(packed), self.FILES)
        self.assertEqual(write_sarc(read_sarc(packed)), packed)

    def test_header_fields(self):
        packed = write_sarc(self.FILES)
        magic, hlen, bom, size, data_off, version = struct.unpack_from("<4sHHIIH", packed, 0)
        self.assertEqual((magic, hlen, bom, size, version), (b"SARC", 0x14, 0xFEFF, len(packed), 0x100))
        self.assertEqual(data_off % 8, 0)
        sfat_magic, sfat_len, count, key = struct.unpack_from("<4sHHI", packed, 0x14)
        self.assertEqual((sfat_magic, sfat_len, count, key), (b"SFAT", 0x0C, len(self.FILES), 0x65))

    def test_sfat_sorted_by_hash_with_name_attributes(self):
        packed = write_sarc(self.FILES)
        nodes = _sfat(packed)
        hashes = [n[0] for n in nodes]
        self.assertEqual(hashes, sorted(hashes))
        names = list(read_sarc(packed))
        self.assertEqual(hashes, [sarc_name_hash(n) for n in names])
        names_base = 0x20 + len(nodes) * 16 + 8
        for (h, attr, start, end), name in zip(nodes, names):
            self.assertEqual(attr >> 24, 1)
            off = names_base + (attr & 0xFFFF) * 4
            self.assertEqual(packed[off:off + len(name) + 1], name.encode() + b"\x00")
            self.assertEqual(start % 8, 0)

    def test_order_independent_of_input_order(self):
        reversed_files = dict(reversed(list(self.FILES.items())))
        self.assertEqual(write_sarc(reversed_files), write_sarc(self.FILES))

    def test_nx_header_alignment_respected(self):
        bfsha = b"FSHA    " + b"\x01\x01\x09\x00" + b"\xff\xfe\x0c\x00" + b"\x00" * 32
        packed = write_sarc({"a.bgyml": b"YB" * 5, "Shader.bfsha": bfsha})
        data_off = struct.unpack_from("<I", packed, 12)[0]
        self.assertEqual(data_off % 0x1000, 0)
        for h, attr, start, end in _sfat(packed):
            if end - start == len(bfsha):
                self.assertEqual((data_off + start) % 0x1000, 0)

    def test_hash_matches_known_value(self):
        # h = h * 0x65 + c over the name bytes
        h = 0
        for c in b"ab":
            h = (h * 0x65 + c) & 0xFFFFFFFF
        self.assertEqual(sarc_name_hash("ab"), h)

    def test_rejects_non_sarc(self):
        with self.assertRaises(SarcError):
            read_sarc(b"Yaz0" + b"\x00" * 32)


class RealPackRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.samples = sorted(SAMPLE_DIR.glob("*.pack")) if SAMPLE_DIR.is_dir() else []
        if not self.samples:
            self.skipTest("sample packs not present")

    def test_rewrite_is_byte_identical(self):
        for path in self.samples:
            with self.subTest(pack=path.name):
                data = path.read_bytes()
                self.assertEqual(write_sarc(read_sarc(data)), data)

    def test_read_keeps_sfat_order(self):
        for path in self.samples:
            with self.subTest(pack=path.name):
                names = list(read_sarc(path.read_bytes()))
                self.assertEqual([sarc_name_hash(n) for n in names],
                                 sorted(sarc_name_hash(n) for n in names))


if __name__ == "__main__":
    unittest.main()
