"""Minimal AINB (Nintendo logic module, magic "AIB ", version 0x408) reader and writer.

Supports the layout used by the logic modules shipped in the RomFS: no attachments, a
string pool, element records with parameter blocks, and six input/output kinds. The writer
regenerates every header offset from the section sizes, so unmodified input round-trips
byte for byte and a grown string pool is laid out correctly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

VERSION = 0x408
HDR = 0x74
EL = 0x3C
PARAM_HEAD = 0xA4
GROUPS = 10

# Per-kind record sizes for the property, input and output tables (s32, bool, f32, str, vec3, ptr).
PSZ = (12, 12, 12, 12, 20, 12)
INSZ = (16, 16, 16, 16, 24, 20)
OUTSZ = (4, 4, 4, 4, 4, 8)
VALSZ = (4, 4, 4, 4, 12, 0)

BOOL_KIND = 1
STR_KIND = 3

QUERY = 1
ROLE = 6
# Source field of an input that holds a constant rather than a link.
CONST_SRC = -1
CONST_FLAG = 0x180_0000
# Multi-link inputs reference entries as src = -100 - first, plug = count.
MULTI_BASE = -100


class AinbError(ValueError):
    """Raised when AINB bytes are malformed or an edit cannot be applied."""


def _u16(b: bytes | bytearray, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes | bytearray, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _i16(b: bytes | bytearray, o: int) -> int:
    return struct.unpack_from("<h", b, o)[0]


def _put(out: bytearray, o: int, v: int) -> None:
    out[o : o + 4] = struct.pack("<I", v)


class _Reader:
    """Bounds-checked view over the raw module bytes."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def raw(self, o: int, n: int) -> bytes:
        if o < 0 or n < 0 or o + n > len(self.data):
            raise AinbError("ainb: read past end")
        return self.data[o : o + n]

    def span(self, a: int, e: int) -> bytes:
        if e < a:
            raise AinbError("ainb: sections out of order")
        return self.raw(a, e - a)

    def u32(self, o: int) -> int:
        return _u32(self.raw(o, 4), 0)

    def ptr(self, o: int) -> int:
        return self.u32(o)


@dataclass
class Pool:
    """NUL-terminated string table referenced by offset from the rest of the module."""

    data: bytearray = field(default_factory=bytearray)

    def get(self, o: int) -> str | None:
        """Return the string starting at offset `o`, or None if it is not a valid string there."""
        if o < 0 or o >= len(self.data):
            return None
        e = self.data.find(b"\0", o)
        if e < 0:
            return None
        try:
            return self.data[o:e].decode("utf-8")
        except UnicodeDecodeError:
            return None

    def find(self, text: str) -> int | None:
        """Return the offset of `text` in the pool, or None if it is absent."""
        target = text.encode("utf-8")
        s = 0
        while s < len(self.data):
            e = self.data.find(b"\0", s)
            if e < 0:
                return None
            if self.data[s:e] == target:
                return s
            s = e + 1
        return None

    def add(self, text: str) -> int:
        """Return the offset of `text`, appending it NUL-terminated if it is not yet present."""
        existing = self.find(text)
        if existing is not None:
            return existing
        if self.data and self.data[-1] != 0:
            self.data.append(0)
        offset = len(self.data)
        self.data += text.encode("utf-8") + b"\0"
        return offset


@dataclass
class Plug:
    """A link entry inside an element's parameter block."""

    a: int
    b: int
    extra: bytes = b""


@dataclass
class Param:
    """Parameter block of one element: property and input ranges, plug groups and plugs."""

    pe: list[list[int]]
    ioe: list[list[int]]
    pl: list[list[int]]
    plugs: list[Plug]

    @classmethod
    def parse(cls, r: _Reader, s: int, e: int) -> Param:
        if e < s + PARAM_HEAD:
            raise AinbError("ainb: element parameters too short")
        pe = [[r.u32(s + 8 * k), r.u32(s + 8 * k + 4)] for k in range(6)]
        ioe = [[r.u32(s + 0x30 + 16 * k + 4 * j) for j in range(4)] for k in range(6)]
        pb = r.raw(s + 0x90, 2 * GROUPS)
        pl = [[pb[2 * k], pb[2 * k + 1]] for k in range(GROUPS)]
        n = sum(g[0] for g in pl)
        ptrs = [r.ptr(s + PARAM_HEAD + 4 * j) for j in range(n)]
        body = s + PARAM_HEAD + 4 * n
        if n == 0 and e != body:
            raise AinbError("ainb: stray bytes after element parameters")
        plugs: list[Plug] = []
        for j in range(n):
            at = ptrs[j]
            nx = ptrs[j + 1] if j + 1 < n else e
            if j == 0 and at != body:
                raise AinbError("ainb: plug data not contiguous")
            if nx < at + 8:
                raise AinbError("ainb: plug data too short")
            plugs.append(Plug(r.u32(at), r.u32(at + 4), r.raw(at + 8, nx - at - 8)))
        return cls(pe, ioe, pl, plugs)

    def size(self) -> int:
        return PARAM_HEAD + 4 * len(self.plugs) + sum(8 + len(p.extra) for p in self.plugs)

    def write(self, out: bytearray) -> None:
        start = len(out)
        for k in range(6):
            out += struct.pack("<II", *self.pe[k])
        for k in range(6):
            out += struct.pack("<4I", *self.ioe[k])
        for g in self.pl:
            out += bytes(g)
        at = start + PARAM_HEAD + 4 * len(self.plugs)
        for p in self.plugs:
            out += struct.pack("<I", at)
            at += 8 + len(p.extra)
        for p in self.plugs:
            out += struct.pack("<II", p.a, p.b) + p.extra

    def group(self, k: int) -> list[Plug]:
        """Return the plugs of plug group `k`."""
        b, n = self.pl[k][1], self.pl[k][0]
        return self.plugs[b : b + n]

    def remove_plug(self, k: int, pos: int) -> Plug:
        """Drop plug `pos` of group `k` and shift the later groups' start indices."""
        b, n = self.pl[k][1], self.pl[k][0]
        if pos >= n or b + pos >= len(self.plugs):
            raise AinbError("ainb: no plug there to remove")
        p = self.plugs.pop(b + pos)
        self.pl[k][0] -= 1
        for j in range(k + 1, GROUPS):
            self.pl[j][1] -= 1
        return p


@dataclass(frozen=True)
class Input:
    """One input record: a linked source (src, plug) or a constant value in `val`."""

    name: int
    src: int
    plug: int
    flags: int
    val: bytes


def _relocate(blob: bytes, old_at: int, new_at: int) -> bytes:
    """Shift the absolute offsets at the head of a blob that moved from `old_at` to `new_at`.

    The transition and multi sections open with a table of absolute file offsets to their own
    entries. Without this fix-up the moved graph points at stale data.
    """
    if not blob or old_at == new_at:
        return blob
    end = old_at + len(blob)
    out = bytearray(blob)
    i = 0
    while i + 4 <= len(blob):
        v = _u32(blob, i)
        if v < old_at + i + 4 or v >= end:
            break
        _put(out, i, v - old_at + new_at)
        i += 4
    return bytes(out)


@dataclass
class Ainb:
    """A parsed AINB module. Sections keep their raw bytes; `write()` rebuilds the layout."""

    hdr: bytearray
    cmds: bytes
    els: list[bytes]
    params: list[Param]
    bb: bytes
    props: list[bytes]
    ins: list[bytearray]
    outs: list[bytes]
    jump_first: bool
    jump: bytes
    multi: bytes
    h50: bytes
    qids: bytes
    exb: bytes | None
    modc: bytes
    ext: bytes
    mcl: bytes
    repl: bytes
    h6c: bytes
    enm: bytes
    pool: Pool

    def el_type(self, i: int) -> int:
        return _u16(self.els[i], 0)

    def el_name(self, i: int) -> str | None:
        return self.pool.get(_u32(self.els[i], 8))

    def find_els(self, name: str) -> list[int]:
        """Return the indices of type-0 elements whose name is `name`."""
        return [i for i in range(len(self.els)) if self.el_type(i) == 0 and self.el_name(i) == name]

    def input_ids(self, i: int, k: int) -> range:
        """Return the global input-record indices belonging to element `i` for kind `k`."""
        start, count = self.params[i].ioe[k][0], self.params[i].ioe[k][1]
        return range(start, start + count)

    def input(self, k: int, g: int) -> Input | None:
        """Return input record `g` of kind `k`, or None if it is out of range."""
        size = INSZ[k]
        o = g * size
        if g < 0 or o + size > len(self.ins[k]):
            return None
        e = bytes(self.ins[k][o : o + size])
        if k == 5:
            return Input(_u32(e, 0), _i16(e, 8), _i16(e, 10), _u32(e, 12), b"")
        return Input(_u32(e, 0), _i16(e, 4), _i16(e, 6), _u32(e, 8), e[12 : 12 + VALSZ[k]])

    def find_in(self, i: int, k: int, name: str) -> int | None:
        """Return the global index of element `i`'s kind-`k` input called `name`, if any."""
        if not 0 <= i < len(self.params):
            return None
        for g in self.input_ids(i, k):
            x = self.input(k, g)
            if x is not None and self.pool.get(x.name) == name:
                return g
        return None

    def in_str(self, i: int, name: str) -> str | None:
        """Return the string value of element `i`'s string input `name`."""
        g = self.find_in(i, STR_KIND, name)
        if g is None:
            return None
        x = self.input(STR_KIND, g)
        return self.pool.get(_u32(x.val, 0)) if x else None

    def set_str_input(self, i: int, name: str, value: str) -> None:
        """Point element `i`'s string input `name` at `value`, adding it to the pool if needed."""
        g = self.find_in(i, STR_KIND, name)
        if g is None:
            raise AinbError(f"ainb: element {i} has no string input {name!r}")
        self.set_in_val(STR_KIND, g, struct.pack("<I", self.pool.add(value)))

    def set_in_val(self, k: int, g: int, v: bytes) -> None:
        """Overwrite the constant value of input record `g` of kind `k`."""
        if k >= 5 or len(v) != VALSZ[k]:
            raise AinbError("ainb: bad input value")
        o = g * INSZ[k] + 12
        if g < 0 or o + len(v) > len(self.ins[k]):
            raise AinbError("ainb: input out of range")
        self.ins[k][o : o + len(v)] = v

    def prop_name(self, k: int, g: int) -> str | None:
        """Return the name of property record `g` of kind `k`."""
        e = self.props[k][g * PSZ[k] : (g + 1) * PSZ[k]]
        if g < 0 or len(e) != PSZ[k]:
            return None
        return self.pool.get(_u32(e, 0))

    def prop_str(self, i: int, name: str) -> str | None:
        """Return the string value of element `i`'s string property `name`."""
        if not 0 <= i < len(self.params):
            return None
        b, n = self.params[i].pe[STR_KIND]
        for g in range(b, b + n):
            if self.prop_name(STR_KIND, g) == name:
                e = self.props[STR_KIND][g * PSZ[STR_KIND] : (g + 1) * PSZ[STR_KIND]]
                return self.pool.get(_u32(e, 8))
        return None

    def multi_range(self, i: int) -> tuple[int, int] | None:
        """Return (first, count) of the multi-link entries that element `i` reads, or None."""
        g = self.find_in(i, BOOL_KIND, "BoolMulti")
        if g is None:
            return None
        x = self.input(BOOL_KIND, g)
        if x is None or x.src > MULTI_BASE or x.plug < 1:
            return None
        return (MULTI_BASE - x.src, x.plug)

    def multi_entry(self, j: int) -> tuple[int, int] | None:
        """Return (element, output index) of multi-link entry `j`, or None when it is out of range."""
        e = self.multi[8 * j : 8 * j + 4]
        if j < 0 or len(e) != 4:
            return None
        return struct.unpack("<HH", e)

    def copy_multi_entry(self, dst: int, src: int) -> None:
        """Make multi-link entry `dst` read what entry `src` reads. The entry's padding is kept."""
        if self.multi_entry(dst) is None or self.multi_entry(src) is None:
            raise AinbError("ainb: multi entry out of range")
        m = bytearray(self.multi)
        m[8 * dst : 8 * dst + 4] = m[8 * src : 8 * src + 4]
        self.multi = bytes(m)

    def force_bool(self, i: int, name: str, v: bool) -> bool:
        """Make bool input `name` of element `i` the constant `v`.

        A link feeding the input is cut: its plug is dropped from the element's plug list.
        Returns whether a link was cut.
        """
        g = self.find_in(i, BOOL_KIND, name)
        if g is None:
            raise AinbError(f"ainb: element {i} has no bool input {name!r}")
        x = self.input(BOOL_KIND, g)
        cut = False
        if x.src != CONST_SRC:
            hit: tuple[int, int] | None = None
            for k in range(GROUPS):
                for j, q in enumerate(self.params[i].group(k)):
                    if q.a == x.src and self.pool.get(q.b) == name:
                        hit = (k, j)
                        break
                if hit is not None:
                    break
            if hit is None:
                raise AinbError("ainb: the linked input has no matching plug")
            self.params[i].remove_plug(*hit)
            cut = True
        o = g * INSZ[BOOL_KIND]
        self.ins[BOOL_KIND][o + 4 : o + 16] = struct.pack("<hhII", CONST_SRC, 0, CONST_FLAG, int(v))
        return cut

    def write(self) -> bytes:
        """Serialize the module, recomputing all section offsets from their sizes."""
        if len(self.els) != len(self.params):
            raise AinbError("ainb: element and parameter counts differ")
        hdr = self.hdr
        eb = HDR + len(self.cmds)
        bbp = eb + EL * len(self.els)
        pos = bbp + len(self.bb)
        pps: list[int] = []
        for p in self.params:
            pps.append(pos)
            pos += p.size()
        prop = pos
        io = prop + 0x18 + sum(len(v) for v in self.props)
        ios = sum(len(v) for v in self.ins) + sum(len(v) for v in self.outs)
        after = io + 0x30 + ios

        a, c = (self.jump, self.multi) if self.jump_first else (self.multi, self.jump)
        a_old, c_old = (_u32(hdr, 0x30), _u32(hdr, 0x38)) if self.jump_first else (_u32(hdr, 0x38), _u32(hdr, 0x30))
        a2 = _relocate(a, a_old, after)
        c2 = _relocate(c, c_old, after + len(a))
        h2 = _relocate(self.h50, _u32(hdr, 0x50), after + len(a) + len(c))

        blobs: list[bytes] = [a2, c2, h2, self.qids]
        if self.exb is not None:
            blobs.append(self.exb)
        blobs += [self.modc, self.ext, self.mcl, self.repl, self.h6c, self.enm, bytes(self.pool.data)]
        at: list[int] = []
        q = after
        for x in blobs:
            at.append(q)
            q += len(x)

        has_exb = self.exb is not None
        w = 5 if has_exb else 4
        h = bytearray(hdr)
        _put(h, 0x10, len(self.els))
        _put(h, 0x14, sum(1 for e in self.els if e[ROLE] & QUERY))
        _put(h, 0x20, bbp)
        _put(h, 0x24, at[w + 6])
        _put(h, 0x28, at[w + 5])
        _put(h, 0x2C, prop)
        _put(h, 0x30, at[0] if self.jump_first else at[1])
        _put(h, 0x34, io)
        _put(h, 0x38, at[1] if self.jump_first else at[0])
        _put(h, 0x3C, prop)
        _put(h, 0x40, prop)
        _put(h, 0x44, at[4] if has_exb else 0)
        _put(h, 0x48, at[w + 3])
        _put(h, 0x4C, at[3])
        _put(h, 0x50, at[2])
        _put(h, 0x5C, at[w])
        _put(h, 0x68, at[w + 1])
        _put(h, 0x6C, at[w + 4])
        _put(h, 0x70, at[w + 2])

        out = bytearray(h)
        out += self.cmds
        for i, e in enumerate(self.els):
            rec = bytearray(e)
            _put(rec, 0x14, pps[i])
            out += rec
        out += self.bb
        for p in self.params:
            p.write(out)

        q2 = prop + 0x18
        for v in self.props:
            out += struct.pack("<I", q2)
            q2 += len(v)
        for v in self.props:
            out += v

        q3 = io + 0x30
        for k in range(6):
            out += struct.pack("<I", q3)
            q3 += len(self.ins[k])
            out += struct.pack("<I", q3)
            q3 += len(self.outs[k])
        for k in range(6):
            out += self.ins[k]
            out += self.outs[k]

        if len(out) != after:
            raise AinbError("ainb: layout mismatch")
        for x in blobs:
            out += x
        return bytes(out)


def parse(data: bytes) -> Ainb:
    """Parse an AINB module from raw bytes."""
    r = _Reader(data)
    if r.raw(0, 4) != b"AIB ":
        raise AinbError("ainb: bad magic")
    if r.u32(4) != VERSION:
        raise AinbError("ainb: unsupported version")
    if r.u32(0x18) != 0:
        raise AinbError("ainb: attachments are not supported")

    hdr = bytearray(r.raw(0, HDR))
    nc = r.ptr(0xC)
    ne = r.ptr(0x10)
    cmds = r.raw(HDR, 0x18 * nc)
    eb = HDR + 0x18 * nc
    els: list[bytes] = []
    pp: list[int] = []
    for i in range(ne):
        o = eb + EL * i
        els.append(r.raw(o, EL))
        pp.append(r.ptr(o + 0x14))
    bbp = r.ptr(0x20)
    if bbp != eb + EL * ne:
        raise AinbError("ainb: blackboard does not follow the elements")
    prop = r.ptr(0x2C)
    io = r.ptr(0x34)
    if r.ptr(0x3C) != prop or r.ptr(0x40) != prop:
        raise AinbError("ainb: unexpected attachment table position")
    bb = r.span(bbp, pp[0] if pp else prop)
    params = [Param.parse(r, pp[i], pp[i + 1] if i + 1 < ne else prop) for i in range(ne)]

    pt = [r.ptr(prop + 4 * k) for k in range(6)]
    if pt[0] != prop + 0x18:
        raise AinbError("ainb: property arrays do not follow the table")
    props: list[bytes] = []
    for k in range(6):
        d = r.span(pt[k], pt[k + 1] if k < 5 else io)
        if len(d) % PSZ[k] != 0:
            raise AinbError("ainb: property array size mismatch")
        props.append(d)

    jp = r.ptr(0x30)
    mp = r.ptr(0x38)
    slot_sum = sum(_u16(e, 0x1C) for e in els)
    jump_first = jp < mp or (jp == mp and slot_sum > 0)
    ex = r.ptr(0x44)
    order = [jp, mp] if jump_first else [mp, jp]
    order += [r.ptr(0x50), r.ptr(0x4C)]
    if ex != 0:
        order.append(ex)
    order += [r.ptr(o) for o in (0x5C, 0x68, 0x70, 0x48, 0x6C, 0x28, 0x24)]
    order.append(len(data))
    if order[0] < io:
        raise AinbError("ainb: sections overlap the input table")

    ip = [r.ptr(io + 4 * j) for j in range(12)]
    if ip[0] != io + 0x30:
        raise AinbError("ainb: input arrays do not follow the table")
    ins: list[bytearray] = [bytearray() for _ in range(6)]
    outs: list[bytes] = [b"" for _ in range(6)]
    for j in range(12):
        e = ip[j + 1] if j < 11 else order[0]
        d = r.span(ip[j], e)
        k = j // 2
        if j % 2 == 0:
            if len(d) % INSZ[k] != 0:
                raise AinbError("ainb: input array size mismatch")
            ins[k] = bytearray(d)
        else:
            if len(d) % OUTSZ[k] != 0:
                raise AinbError("ainb: output array size mismatch")
            outs[k] = d

    parts = [r.span(order[i], order[i + 1]) for i in range(len(order) - 1)]
    it = iter(parts)
    first, second, h50, qids = next(it), next(it), next(it), next(it)
    exb = next(it) if ex != 0 else None
    modc, ext, mcl, repl, h6c, enm, pool = (next(it) for _ in range(7))
    jump, multi = (first, second) if jump_first else (second, first)
    return Ainb(
        hdr=hdr,
        cmds=cmds,
        els=els,
        params=params,
        bb=bb,
        props=props,
        ins=ins,
        outs=outs,
        jump_first=jump_first,
        jump=jump,
        multi=multi,
        h50=h50,
        qids=qids,
        exb=exb,
        modc=modc,
        ext=ext,
        mcl=mcl,
        repl=repl,
        h6c=h6c,
        enm=enm,
        pool=Pool(bytearray(pool)),
    )


def _gaps(v: list[str], tag: str, k: int, want: list[tuple[int, int]], total: int) -> None:
    at = 0
    for i, (b, n) in enumerate(want):
        if b != at:
            v.append(f"{tag} {k} element {i} starts at {b}, expected {at}")
            return
        at += n
    if at != total:
        v.append(f"{tag} {k} covers {at} of {total} entries")


def audit(a: Ainb) -> list[str]:
    """Return layout problems in a parsed module: array coverage, plug groups and input names. Empty when clean."""
    v: list[str] = []
    for k in range(6):
        _gaps(v, "property array", k, [(p.pe[k][0], p.pe[k][1]) for p in a.params], len(a.props[k]) // PSZ[k])
        _gaps(v, "input array", k, [(p.ioe[k][0], p.ioe[k][1]) for p in a.params], len(a.ins[k]) // INSZ[k])
        _gaps(v, "output array", k, [(p.ioe[k][2], p.ioe[k][3]) for p in a.params], len(a.outs[k]) // OUTSZ[k])
    for i, p in enumerate(a.params):
        at = 0
        for g in p.pl:
            if g[1] != at:
                v.append(f"element {i} plug groups are not contiguous")
                break
            at += g[0]
        for k in range(6):
            for g in a.input_ids(i, k):
                x = a.input(k, g)
                if x is not None and a.pool.get(x.name) is None:
                    v.append(f"element {i} input {g} has a bad name offset")
    return v
