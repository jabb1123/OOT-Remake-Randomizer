"""BYML v7 parser and serializer for Nintendo Switch (OoT Remake) game files.

Supports both big-endian ('BY', e.g. GameDataList) and little-endian ('YB', e.g.
bcett placement files) variants of the BYML v7 format.

Node type codes (confirmed against actual game files):
  0xC0  Array   — type_per_element bytes (padded) + 4-byte value slots
  0xC1  Hash    — 8-byte entries: key_index(3B) + type(1B) + value(4B)
  0xC2  StringArray — count+1 offsets (relative to node) + null-terminated strings
  0xA0  String  — u32 index into string table
  0xA1  Binary  — u32 offset to: u32 size + data
  0xA2  Binary with parameter — u32 offset to: u32 size + u32 param + data
        (layout taken from format docs; not present in the sampled game files)
  0xD0  Bool    — u32 (0 or 1)
  0xD1  Int32   — i32
  0xD2  Float32 — f32
  0xD3  UInt32  — u32
  0xD4  Int64   — u32 offset to an 8-byte i64
  0xD5  UInt64  — u32 offset to an 8-byte u64
  0xD6  Float64 — u32 offset to an 8-byte f64
  0xFF  Null

A table offset of 0 in the header means the table is absent (empty).

API:
  parse_byml7(data)        -> plain dict/list/str/int/float/bool/bytes/None
  parse_byml7_typed(data)  -> like parse_byml7 but non-default scalar types are
                              wrapped (U32, I64, U64, F64, BinaryParam) so that
                              dump_byml7() reproduces the exact node types.
  dump_byml7(obj, ...)     -> BYML v7 bytes
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class BymlError(ValueError):
    pass


# ----------------------------------------------------------------------
# Node type codes
# ----------------------------------------------------------------------

T_STRING = 0xA0
T_BINARY = 0xA1
T_BINARY_PARAM = 0xA2
T_ARRAY = 0xC0
T_HASH = 0xC1
T_STRING_TABLE = 0xC2
T_BOOL = 0xD0
T_I32 = 0xD1
T_F32 = 0xD2
T_U32 = 0xD3
T_I64 = 0xD4
T_U64 = 0xD5
T_F64 = 0xD6
T_NULL = 0xFF

_CONTAINER_TYPES = (T_ARRAY, T_HASH)
_BIG_TYPES = (T_I64, T_U64, T_F64, T_BINARY, T_BINARY_PARAM)


# ----------------------------------------------------------------------
# Typed wrappers for non-default scalar node types
# ----------------------------------------------------------------------

class U32(int):
    """BYML 0xD3 unsigned 32-bit integer."""

    __slots__ = ()

    def __new__(cls, value: int = 0) -> "U32":
        v = int.__new__(cls, value)
        if not 0 <= v <= 0xFFFFFFFF:
            raise BymlError(f"U32 out of range: {int(v)}")
        return v

    def __repr__(self) -> str:
        return f"U32({int(self)})"


class I64(int):
    """BYML 0xD4 signed 64-bit integer."""

    __slots__ = ()

    def __new__(cls, value: int = 0) -> "I64":
        v = int.__new__(cls, value)
        if not -(1 << 63) <= v < (1 << 63):
            raise BymlError(f"I64 out of range: {int(v)}")
        return v

    def __repr__(self) -> str:
        return f"I64({int(self)})"


class U64(int):
    """BYML 0xD5 unsigned 64-bit integer."""

    __slots__ = ()

    def __new__(cls, value: int = 0) -> "U64":
        v = int.__new__(cls, value)
        if not 0 <= v < (1 << 64):
            raise BymlError(f"U64 out of range: {int(v)}")
        return v

    def __repr__(self) -> str:
        return f"U64({int(self)})"


class F64(float):
    """BYML 0xD6 double-precision float."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"F64({float(self)!r})"


class BinaryParam(bytes):
    """BYML 0xA2 binary blob with an extra u32 parameter (e.g. alignment).

    Plain ``bytes`` values map to 0xA1 binary nodes.
    """

    def __new__(cls, data: bytes = b"", param: int = 0) -> "BinaryParam":
        obj = bytes.__new__(cls, data)
        obj.param = int(param)
        return obj

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BinaryParam):
            return bytes(self) == bytes(other) and self.param == other.param
        return NotImplemented if not isinstance(other, bytes) else False

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __hash__(self) -> int:
        return hash((bytes(self), self.param))

    def __repr__(self) -> str:
        return f"BinaryParam({bytes(self)!r}, param={self.param})"


# ----------------------------------------------------------------------
# Reader
# ----------------------------------------------------------------------

class Byml7:
    """BYML v7 parser.

    ``parse()`` returns native Python objects (backward compatible API);
    ``parse_typed()`` additionally preserves exact node types.
    """

    def __init__(self, data: bytes) -> None:
        if len(data) < 16:
            raise BymlError("File too short to be a BYML v7 file.")
        magic = data[:2]
        if magic not in (b"BY", b"YB"):
            raise BymlError(f"Unexpected BYML magic: {magic!r}")
        self._data = bytes(data)
        self._le = magic == b"YB"
        self._e = "<" if self._le else ">"
        self._version = self._u16(2)
        self._hk_off = self._u32(4)
        self._st_off = self._u32(8)
        self._root_off = self._u32(12)
        self._hash_keys_raw = self._read_str_arr_raw(self._hk_off)
        self._str_table_raw = self._read_str_arr_raw(self._st_off)
        self._hash_keys = [s.decode(errors="replace") for s in self._hash_keys_raw]
        self._str_table = [s.decode(errors="replace") for s in self._str_table_raw]
        self._typed = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def version(self) -> int:
        return self._version

    @property
    def is_little_endian(self) -> bool:
        return self._le

    def parse(self) -> Any:
        self._typed = False
        if self._root_off == 0:
            return None
        return self._walk(self._root_off)

    def parse_typed(self) -> Any:
        """Parse preserving node types; raises BymlError on malformed data."""
        self._typed = True
        try:
            self._keys_t = [s.decode("utf-8", "surrogateescape") for s in self._hash_keys_raw]
            self._strs_t = [s.decode("utf-8", "surrogateescape") for s in self._str_table_raw]
            if self._root_off == 0:
                return None
            root_type = self._u8(self._root_off)
            if root_type not in _CONTAINER_TYPES:
                raise BymlError(f"Unsupported root node type {root_type:#x}")
            return self._walk(self._root_off)
        finally:
            self._typed = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _u8(self, off: int) -> int:
        return self._data[off] if 0 <= off < len(self._data) else 0

    def _unpack(self, fmt: str, off: int, size: int, default: Any) -> Any:
        if 0 <= off and off + size <= len(self._data):
            return struct.unpack_from(self._e + fmt, self._data, off)[0]
        if self._typed:
            raise BymlError(f"Read past end of data at {off:#x}")
        return default

    def _u16(self, off: int) -> int:
        return self._unpack("H", off, 2, 0)

    def _u24(self, off: int) -> int:
        return int.from_bytes(self._data[off:off+3], "little" if self._le else "big")

    def _u32(self, off: int) -> int:
        return self._unpack("I", off, 4, 0)

    def _i32(self, off: int) -> int:
        return self._unpack("i", off, 4, 0)

    def _f32(self, off: int) -> float:
        return self._unpack("f", off, 4, 0.0)

    def _read_str_arr_raw(self, table_off: int) -> list[bytes]:
        if (table_off == 0 or table_off >= len(self._data)
                or self._data[table_off] != T_STRING_TABLE):
            return []
        count = self._u24(table_off + 1)
        result = []
        for i in range(count):
            rel = self._u32(table_off + 4 + i * 4)
            abs_ = table_off + rel
            if abs_ < len(self._data):
                end = self._data.find(b"\x00", abs_)
                if end < 0:
                    end = len(self._data)
                result.append(self._data[abs_:end])
        return result

    def _read_str_arr(self, table_off: int) -> list[str]:
        return [s.decode(errors="replace") for s in self._read_str_arr_raw(table_off)]

    def _read_big(self, off: int, ntype: int) -> Any:
        ptr = self._u32(off)
        if ntype == T_I64:
            v = self._unpack("q", ptr, 8, 0)
            return I64(v) if self._typed else v
        if ntype == T_U64:
            v = self._unpack("Q", ptr, 8, 0)
            return U64(v) if self._typed else v
        if ntype == T_F64:
            v = self._unpack("d", ptr, 8, 0.0)
            return F64(v) if self._typed else v
        if ntype == T_BINARY:
            size = self._u32(ptr)
            if self._typed and ptr + 4 + size > len(self._data):
                raise BymlError(f"Binary node at {ptr:#x} overruns data")
            return self._data[ptr + 4:ptr + 4 + size]
        # T_BINARY_PARAM
        size = self._u32(ptr)
        param = self._u32(ptr + 4)
        if self._typed and ptr + 8 + size > len(self._data):
            raise BymlError(f"Binary node at {ptr:#x} overruns data")
        blob = self._data[ptr + 8:ptr + 8 + size]
        return BinaryParam(blob, param) if self._typed else blob

    def _parse_value(self, off: int, ntype: int) -> Any:
        if self._typed:
            return self._parse_value_inner(off, ntype)
        try:
            return self._parse_value_inner(off, ntype)
        except Exception as e:
            return f"<parse_error:{e}>"

    def _parse_value_inner(self, off: int, ntype: int) -> Any:
        if ntype == T_STRING:
            idx = self._u32(off)
            table = self._strs_t if self._typed else self._str_table
            if idx < len(table):
                return table[idx]
            if self._typed:
                raise BymlError(f"String index {idx} out of range")
            return f"<str:{idx}>"
        if ntype == T_BOOL: return bool(self._u32(off))
        if ntype == T_I32: return self._i32(off)
        if ntype == T_F32: return self._f32(off)
        if ntype == T_U32:
            v = self._u32(off)
            return U32(v) if self._typed else v
        if ntype in _BIG_TYPES: return self._read_big(off, ntype)
        if ntype in _CONTAINER_TYPES: return self._walk(self._u32(off))
        if ntype == T_NULL: return None
        if self._typed:
            raise BymlError(f"Unsupported node type {ntype:#x} at {off:#x}")
        return f"<type:{hex(ntype)} @{hex(self._u32(off))}>"

    def _walk(self, off: int) -> Any:
        if off >= len(self._data):
            if self._typed:
                raise BymlError(f"Node offset {off:#x} past end of data")
            return None
        t = self._u8(off)
        count = self._u24(off + 1)
        if t == T_HASH:  # key_idx(3) + type(1) + value(4) per entry
            keys = self._keys_t if self._typed else self._hash_keys
            result: dict[str, Any] = {}
            entry_off = off + 4
            for _ in range(count):
                if entry_off + 8 > len(self._data):
                    if self._typed:
                        raise BymlError(f"Hash node at {off:#x} overruns data")
                    break
                ki = self._u24(entry_off)
                vt = self._u8(entry_off + 3)
                if ki < len(keys):
                    key = keys[ki]
                elif self._typed:
                    raise BymlError(f"Hash key index {ki} out of range")
                else:
                    key = f"<k:{ki}>"
                result[key] = self._parse_value(entry_off + 4, vt)
                entry_off += 8
            return result
        elif t == T_ARRAY:  # type bytes (padded) then 4-byte values
            types_off = off + 4
            vals_start = (types_off + count + 3) & ~3
            return [self._parse_value(vals_start + i * 4, self._u8(types_off + i))
                    for i in range(count)]
        elif t == T_STRING_TABLE and not self._typed:
            return self._read_str_arr(off)
        if self._typed:
            raise BymlError(f"Unsupported container node type {t:#x} at {off:#x}")
        return f"<unknown_node:{hex(t)}>"


def parse_byml7(data: bytes) -> Any:
    """Parse BYML v7 data and return a native Python object."""
    return Byml7(data).parse()


def parse_byml7_file(path: str | Path) -> Any:
    return parse_byml7(Path(path).read_bytes())


def parse_byml7_typed(data: bytes) -> Any:
    """Parse BYML v7 data preserving exact node types.

    Mapping: dict=Hash, list=Array, str=String, bool=Bool, int=Int32,
    float=Float32, U32/I64/U64/F64 wrappers, bytes=Binary, BinaryParam,
    None=Null.  The result can be fed back into :func:`dump_byml7`.
    """
    return Byml7(data).parse_typed()


# ----------------------------------------------------------------------
# Writer
# ----------------------------------------------------------------------

def _node_type(obj: Any) -> int:
    if obj is None:
        return T_NULL
    if isinstance(obj, bool):
        return T_BOOL
    if isinstance(obj, U32):
        return T_U32
    if isinstance(obj, I64):
        return T_I64
    if isinstance(obj, U64):
        return T_U64
    if isinstance(obj, int):
        # Plain ints default to Int32; promote when the value does not fit so
        # output of the plain parser can still be serialized.
        if -(1 << 31) <= obj < (1 << 31):
            return T_I32
        if 0 <= obj <= 0xFFFFFFFF:
            return T_U32
        if -(1 << 63) <= obj < (1 << 63):
            return T_I64
        if 0 <= obj < (1 << 64):
            return T_U64
        raise BymlError(f"Integer out of range for BYML: {obj}")
    if isinstance(obj, F64):
        return T_F64
    if isinstance(obj, float):
        return T_F32
    if isinstance(obj, str):
        return T_STRING
    if isinstance(obj, BinaryParam):
        return T_BINARY_PARAM
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return T_BINARY
    if isinstance(obj, Mapping):
        return T_HASH
    if isinstance(obj, (list, tuple)):
        return T_ARRAY
    raise BymlError(f"Cannot serialize {type(obj).__name__} to BYML")


def _utf8(s: str) -> bytes:
    return s.encode("utf-8", "surrogateescape")


class _Writer:
    def __init__(self, big_endian: bool, version: int, dedupe: bool) -> None:
        self._be = big_endian
        self._e = ">" if big_endian else "<"
        self._version = version
        self._dedupe = dedupe
        self._buf = bytearray()
        self._keys: dict[str, int] = {}
        self._strings: dict[str, int] = {}
        # Structural de-duplication state.
        self._intern: dict[tuple, int] = {}
        self._skey_memo: dict[int, int] = {}
        self._container_offsets: dict[int, int] = {}
        self._big_offsets: dict[tuple, int] = {}
        self._in_progress: set[int] = set()

    # -- helpers -------------------------------------------------------

    def _u24(self, v: int) -> bytes:
        if not 0 <= v <= 0xFFFFFF:
            raise BymlError(f"Value does not fit in 24 bits: {v}")
        return v.to_bytes(3, "big" if self._be else "little")

    def _align(self, n: int) -> None:
        pad = (-len(self._buf)) % n
        if pad:
            self._buf += b"\x00" * pad

    def _pack(self, fmt: str, *vals: Any) -> bytes:
        return struct.pack(self._e + fmt, *vals)

    # -- pass 1: collect keys and strings -------------------------------

    def _collect(self, root: Any) -> None:
        keys: set[str] = set()
        strings: set[str] = set()
        seen: set[int] = set()
        stack = [root]
        while stack:
            obj = stack.pop()
            if isinstance(obj, str):
                strings.add(obj)
                continue
            t = _node_type(obj)
            if t not in _CONTAINER_TYPES or id(obj) in seen:
                continue
            seen.add(id(obj))
            if t == T_HASH:
                for k, v in obj.items():
                    if not isinstance(k, str):
                        raise BymlError(f"Hash keys must be str, got {type(k).__name__}")
                    keys.add(k)
                    stack.append(v)
            else:
                stack.extend(obj)
        for i, k in enumerate(sorted(keys, key=_utf8)):
            self._keys[k] = i
        for i, s in enumerate(sorted(strings, key=_utf8)):
            self._strings[s] = i
        if len(self._keys) > 0xFFFFFF or len(self._strings) > 0xFFFFFF:
            raise BymlError("Too many keys/strings for BYML")

    # -- payload encoding ----------------------------------------------

    def _inline_slot(self, t: int, v: Any) -> bytes:
        if t == T_STRING:
            return self._pack("I", self._strings[v])
        if t == T_BOOL:
            return self._pack("I", 1 if v else 0)
        if t == T_I32:
            return self._pack("i", int(v))
        if t == T_F32:
            return self._pack("f", float(v))
        if t == T_U32:
            return self._pack("I", int(v))
        if t == T_NULL:
            return b"\x00\x00\x00\x00"
        raise BymlError(f"Not an inline type: {t:#x}")

    def _big_payload(self, t: int, v: Any) -> bytes:
        if t == T_I64:
            return self._pack("q", int(v))
        if t == T_U64:
            return self._pack("Q", int(v))
        if t == T_F64:
            return self._pack("d", float(v))
        if t == T_BINARY:
            data = bytes(v)
            return self._pack("I", len(data)) + data
        if t == T_BINARY_PARAM:
            data = bytes(v)
            return self._pack("II", len(data), v.param) + data
        raise BymlError(f"Not an out-of-line scalar type: {t:#x}")

    def _skey(self, obj: Any) -> int:
        """Return an interned id identifying the structure of a container."""
        oid = id(obj)
        got = self._skey_memo.get(oid)
        if got is not None:
            return got
        if oid in self._in_progress:
            raise BymlError("Cyclic reference in BYML data")
        self._in_progress.add(oid)
        if isinstance(obj, Mapping):
            key: tuple = (T_HASH, tuple(sorted(
                (self._keys[k], self._vkey(v)) for k, v in obj.items())))
        else:
            key = (T_ARRAY, tuple(self._vkey(v) for v in obj))
        self._in_progress.discard(oid)
        sid = self._intern.setdefault(key, len(self._intern))
        self._skey_memo[oid] = sid
        return sid

    def _vkey(self, v: Any) -> tuple:
        t = _node_type(v)
        if t in _CONTAINER_TYPES:
            return (t, self._skey(v))
        if t in _BIG_TYPES:
            return (t, self._big_payload(t, v))
        return (t, self._inline_slot(t, v))

    # -- pass 2: emit ----------------------------------------------------

    def _write_string_table(self, strings: dict[str, int]) -> int:
        if not strings:
            return 0
        self._align(4)
        off = len(self._buf)
        encoded = [_utf8(s) for s in sorted(strings, key=strings.__getitem__)]
        n = len(encoded)
        self._buf += bytes([T_STRING_TABLE]) + self._u24(n)
        rel = 4 + 4 * (n + 1)
        offsets = []
        for e in encoded:
            offsets.append(rel)
            rel += len(e) + 1
        offsets.append(rel)
        self._buf += b"".join(self._pack("I", o) for o in offsets)
        for e in encoded:
            self._buf += e + b"\x00"
        self._align(4)
        return off

    def _write_big(self, t: int, v: Any) -> int:
        payload = self._big_payload(t, v)
        cache_key = (t, payload)
        if self._dedupe and cache_key in self._big_offsets:
            return self._big_offsets[cache_key]
        self._align(8 if t in (T_I64, T_U64, T_F64) else 4)
        off = len(self._buf)
        self._buf += payload
        self._align(4)
        self._big_offsets[cache_key] = off
        return off

    def _value(self, v: Any) -> tuple[int, bytes]:
        t = _node_type(v)
        if t in _CONTAINER_TYPES:
            return t, self._pack("I", self._write_container(v))
        if t in _BIG_TYPES:
            return t, self._pack("I", self._write_big(t, v))
        return t, self._inline_slot(t, v)

    def _write_container(self, obj: Any) -> int:
        sid = self._skey(obj) if self._dedupe else None
        if sid is not None and sid in self._container_offsets:
            return self._container_offsets[sid]
        oid = id(obj)
        if oid in self._in_progress:
            raise BymlError("Cyclic reference in BYML data")
        self._in_progress.add(oid)

        self._align(4)
        off = len(self._buf)
        if isinstance(obj, Mapping):
            items = sorted(((self._keys[k], v) for k, v in obj.items()),
                           key=lambda kv: kv[0])
            n = len(items)
            self._buf += bytes([T_HASH]) + self._u24(n)
            self._buf += b"\x00" * (8 * n)
            for i, (ki, v) in enumerate(items):
                vt, slot = self._value(v)
                pos = off + 4 + 8 * i
                self._buf[pos:pos + 8] = self._u24(ki) + bytes([vt]) + slot
        else:
            items = list(obj)
            n = len(items)
            self._buf += bytes([T_ARRAY]) + self._u24(n)
            types_off = off + 4
            slots_off = (types_off + n + 3) & ~3
            self._buf += b"\x00" * (slots_off - types_off + 4 * n)
            for i, v in enumerate(items):
                vt, slot = self._value(v)
                self._buf[types_off + i] = vt
                pos = slots_off + 4 * i
                self._buf[pos:pos + 4] = slot

        self._in_progress.discard(oid)
        if sid is not None:
            self._container_offsets[sid] = off
        return off

    def dump(self, root: Any) -> bytes:
        if _node_type(root) not in _CONTAINER_TYPES:
            raise BymlError("BYML root must be a dict (Hash) or list (Array)")
        self._collect(root)
        self._buf += b"\x00" * 16
        hk_off = self._write_string_table(self._keys)
        st_off = self._write_string_table(self._strings)
        root_off = self._write_container(root)
        self._align(4)
        magic = b"BY" if self._be else b"YB"
        self._buf[0:16] = magic + self._pack("HIII", self._version, hk_off, st_off, root_off)
        return bytes(self._buf)


def dump_byml7(obj: Any, *, big_endian: bool = False, version: int = 7,
               dedupe: bool = True) -> bytes:
    """Serialize ``obj`` to BYML v7 bytes.

    Accepts the output of :func:`parse_byml7_typed` (exact types preserved) or
    plain Python objects (int -> Int32, promoted to U32/I64/U64 when out of
    range; float -> Float32; bytes -> Binary).  Hash key and string tables are
    sorted by raw UTF-8 bytes.  With ``dedupe`` (default), structurally
    identical containers and 64-bit/binary values are written only once.
    """
    if not 0 <= version <= 0xFFFF:
        raise BymlError(f"Invalid BYML version: {version}")
    return _Writer(big_endian, version, dedupe).dump(obj)


def dump_byml7_file(path: str | Path, obj: Any, **kwargs: Any) -> None:
    Path(path).write_bytes(dump_byml7(obj, **kwargs))
