"""Reader for unprotected Director movies (.dir, RIFX/XFIR), as ProjectorRays writes them.

The container is a list of chunks found through the memory map ('mmap'); the key table
('KEY*') says which chunk belongs to which cast member or cast library; each cast library
('CAS*') lists its members' 'CASt' chunks in member-number order.  Container structures
follow the file's byte order; most chunk contents are big-endian whatever the container.
"""

import struct


class Reader:
    def __init__(self, data, big=True, pos=0):
        self.data = data
        self.big = big
        self.pos = pos

    def _u(self, fmt, n):
        v = struct.unpack_from(('>' if self.big else '<') + fmt, self.data, self.pos)[0]
        self.pos += n
        return v

    def u8(self): return self._u('B', 1)
    def i8(self): return self._u('b', 1)
    def u16(self): return self._u('H', 2)
    def i16(self): return self._u('h', 2)
    def u32(self): return self._u('I', 4)
    def i32(self): return self._u('i', 4)

    def bytes(self, n):
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def left(self):
        return len(self.data) - self.pos

    def eof(self):
        return self.pos >= len(self.data)


def fourcc(b, big):
    s = b.decode('latin-1')
    return s if big else s[::-1]


class ListChunk:
    """The offset-table list used by cast info, the cast list and others."""

    def __init__(self, data, header):
        r = Reader(data, True)
        self.header = header(r)
        data_offset = self.header['dataOffset']
        r.pos = data_offset
        n = r.u16()
        offsets = [r.u32() for _ in range(n)]
        items_len = r.u32()
        base = r.pos
        self.items = []
        for i, off in enumerate(offsets):
            end = offsets[i + 1] if i + 1 < n else items_len
            self.items.append(data[base + off:base + end])

    def string(self, i):
        if i >= len(self.items):
            return ''
        return self.items[i].decode('mac_roman')

    def pascal(self, i):
        if i >= len(self.items) or not self.items[i]:
            return ''
        b = self.items[i]
        return b[1:1 + b[0]].decode('mac_roman')

    def raw(self, i):
        return self.items[i] if i < len(self.items) else b''


MEMBER_TYPES = {
    0: 'null', 1: 'bitmap', 2: 'filmLoop', 3: 'field', 4: 'palette', 5: 'picture',
    6: 'sound', 7: 'button', 8: 'shape', 9: 'movie', 10: 'digitalVideo', 11: 'script',
    12: 'richText', 13: 'OLE', 14: 'transition', 15: 'xtra',
}


class DirFile:
    def __init__(self, path):
        self.data = open(path, 'rb').read()
        magic = self.data[:4]
        if magic == b'RIFX':
            self.big = True
        elif magic == b'XFIR':
            self.big = False
        else:
            raise ValueError('not a Director movie: %r' % magic)
        r = Reader(self.data, self.big, 12)
        # imap
        assert fourcc(r.bytes(4), self.big) == 'imap'
        r.u32()
        r.u32()  # version
        mmap_offset = r.u32()
        self.dir_version = r.u32()
        r.pos = mmap_offset
        assert fourcc(r.bytes(4), self.big) == 'mmap'
        r.u32()
        r.i16(); r.i16()
        r.i32()
        used = r.i32()
        r.i32(); r.i32(); r.i32()
        self.chunks = []  # index -> (fourcc, offset, length)
        for _ in range(used):
            fc = fourcc(r.bytes(4), self.big)
            ln = r.u32()
            off = r.u32()
            r.i16(); r.i16(); r.i32()
            self.chunks.append((fc, off, ln))
        self.by_type = {}
        for i, (fc, off, ln) in enumerate(self.chunks):
            if fc in ('free', 'junk'):
                continue
            self.by_type.setdefault(fc, []).append(i)
        self._read_key_table()
        self._read_config()
        self._read_casts()

    def chunk(self, i):
        fc, off, ln = self.chunks[i]
        return self.data[off + 8:off + 8 + ln]

    def first(self, fc):
        ids = self.by_type.get(fc)
        return self.chunk(ids[0]) if ids else None

    def _read_key_table(self):
        data = self.first('KEY*')
        r = Reader(data, self.big)
        r.u16(); r.u16()
        count = r.u32()
        used = r.u32()
        self.owned = {}  # owner id -> {fourcc: section id}
        for _ in range(count):
            sid = r.i32()
            owner = r.i32()
            fc = fourcc(r.bytes(4), self.big)
            if sid <= 0:
                continue
            self.owned.setdefault(owner, {}).setdefault(fc, sid)

    def _read_config(self):
        d = self.first('DRCF') or self.first('VWCF')
        r = Reader(d, True)
        r.u16()  # len
        self.file_version = r.u16()
        top, left, bottom, right = r.i16(), r.i16(), r.i16(), r.i16()
        self.stage = dict(left=left, top=top, right=right, bottom=bottom,
                          width=right - left, height=bottom - top)
        # D7+ keeps the stage colour as RGB, split across offsets 18, 19 and 27.
        g, b = d[18], d[19]
        is_rgb, rr = d[26], d[27]
        self.stage_color = (rr, g, b) if is_rgb else None
        self.bit_depth = struct.unpack_from('>h', d, 28)[0]
        self.director_version = struct.unpack_from('>h', d, 36)[0]
        self.frame_rate = struct.unpack_from('>h', d, 54)[0]
        self.platform = struct.unpack_from('>h', d, 56)[0]

    def _read_casts(self):
        data = self.first('MCsL')
        lst = ListChunk(data, lambda r: dict(dataOffset=r.u32(), unk0=r.u16(), castCount=r.u16(),
                                              itemsPerCast=r.u16(), unk1=r.u16()))
        h = lst.header
        self.casts = []
        for i in range(h['castCount']):
            ipc = h['itemsPerCast']
            name = lst.pascal(i * ipc + 1)
            path = lst.pascal(i * ipc + 2)
            item = Reader(lst.raw(i * ipc + 4), True)
            mn, mx, cid = item.u16(), item.u16(), item.i32()
            cast = dict(number=i + 1, name=name, path=path, min=mn, max=mx, id=cid, members={})
            cas = self.owned.get(cid, {}).get('CAS*')
            if cas is not None:
                cr = Reader(self.chunk(cas), True)
                n = 0
                while not cr.eof():
                    sid = cr.i32()
                    num = mn + n
                    n += 1
                    if sid <= 0:
                        continue
                    m = self._read_member(sid)
                    m['number'] = num
                    m['section'] = sid
                    cast['members'][num] = m
                lctx = self.owned.get(cid, {}).get('Lctx')
                cast['lctx'] = lctx
            self.casts.append(cast)

    def _read_member(self, sid):
        data = self.chunk(sid)
        r = Reader(data, True)
        mtype = r.u32()
        info_len = r.u32()
        spec_len = r.u32()
        info = data[12:12 + info_len]
        spec = data[12 + info_len:12 + info_len + spec_len]
        m = dict(type=MEMBER_TYPES.get(mtype, str(mtype)), typeId=mtype, spec=spec, name='',
                 scriptId=0, scriptText='', infoItems=[], flags=0)
        if info_len:
            lst = ListChunk(info, lambda r: dict(dataOffset=r.u32(), unk1=r.u32(), unk2=r.u32(),
                                                  flags=r.u32(), scriptId=r.u32()))
            m['scriptId'] = lst.header['scriptId']
            m['flags'] = lst.header['flags']
            m['scriptText'] = lst.string(0)
            m['name'] = lst.pascal(1)
            m['infoItems'] = lst.items
        m['children'] = self.owned.get(sid, {})
        return m

    # ----- score -----

    def score(self):
        data = self.first('VWSC')
        return parse_score(data)

    def labels(self):
        data = self.first('VWLB')
        if not data:
            return []
        r = Reader(data, True)
        count = r.u16() + 1
        base = count * 4 + 2
        entries = [(r.u16(), r.u16()) for _ in range(count)]
        out = []
        for i in range(count - 1):
            frame, sp = entries[i]
            _, np_ = entries[i + 1]
            raw = data[base + sp:base + np_]
            name = raw.split(b'\r')[0].decode('mac_roman')
            out.append(dict(frame=frame, name=name))
        return out


MAIN_SIZE = 288
SPRITE_SIZE = 48


def parse_score(data):
    """The D7+ score: per-frame deltas of a channel buffer, plus the sprite details list."""
    r = Reader(data, True)
    total = r.u32()
    ver = r.i32()
    list_start = r.u32()
    r.pos = list_start
    num_entries = r.i32()
    list_size = r.i32()
    r.i32()
    index_start = list_start + 12
    frame_data_offset = index_start + list_size * 4
    offs = [r.u32() for _ in range(num_entries)]

    def detail(i):
        if i <= 0 or i + 1 >= len(offs) + 1:
            return None
        a = frame_data_offset + offs[i]
        b = frame_data_offset + offs[i + 1] if i + 1 < len(offs) else None
        return data[a:b]

    head = data[frame_data_offset + offs[0]:frame_data_offset + offs[1]]
    hr = Reader(head, True)
    frames_size = hr.u32()
    frame1_off = hr.u32()
    num_frames = hr.u32()
    frames_version = hr.u16()
    sprite_record = hr.u16()
    num_channels = hr.u16()
    displayed = hr.u16()
    assert sprite_record == SPRITE_SIZE, sprite_record
    buf = bytearray(MAIN_SIZE + SPRITE_SIZE * num_channels)
    pos = 20
    frames = []
    end = len(head)
    while pos < end:
        fsize = struct.unpack_from('>H', head, pos)[0]
        if fsize == 0:
            break
        p = pos + 2
        stop = pos + fsize
        while p < stop:
            csize, coff = struct.unpack_from('>HH', head, p)
            p += 4
            buf[coff:coff + csize] = head[p:p + csize]
            p += csize
        pos = stop
        frames.append(bytes(buf))

    def sprite_info(idx):
        d = detail(idx)
        if not d:
            return None
        rr = Reader(d, True)
        info = dict(startFrame=rr.i32(), endFrame=rr.i32(), xtraInfo=rr.i32(), flags=rr.i32(),
                    channelNum=rr.i32())
        return info

    def behaviors(idx):
        d = detail(idx + 1)
        out = []
        if not d:
            return out
        rr = Reader(d, True)
        while rr.left() >= 8:
            cl = rr.i16()
            mem = rr.i16()
            init = rr.i32()
            params = ''
            if init:
                pd = detail(init)
                if pd:
                    params = pd.decode('mac_roman')
            out.append(dict(castLib=cl, member=mem, params=params))
        return out

    result = []
    for fi, fb in enumerate(frames):
        mr = Reader(fb, True)
        main = {}
        main['script'] = (struct.unpack_from('>H', fb, 0)[0], struct.unpack_from('>H', fb, 2)[0])
        script_idx = struct.unpack_from('>I', fb, 4)[0]
        main['scriptBehaviors'] = behaviors(script_idx) if script_idx else []
        main['tempo'] = fb[48 + 6]
        main['transition'] = (struct.unpack_from('>H', fb, 96)[0], struct.unpack_from('>H', fb, 98)[0])
        main['sound2'] = (struct.unpack_from('>H', fb, 144)[0], struct.unpack_from('>H', fb, 146)[0])
        main['sound1'] = (struct.unpack_from('>H', fb, 192)[0], struct.unpack_from('>H', fb, 194)[0])
        main['palette'] = (struct.unpack_from('>h', fb, 240)[0], struct.unpack_from('>h', fb, 242)[0])
        sprites = {}
        for ch in range(num_channels):
            o = MAIN_SIZE + ch * SPRITE_SIZE
            s = fb[o:o + SPRITE_SIZE]
            stype = s[0]
            cast_lib, member = struct.unpack_from('>hH', s, 4)
            list_idx = struct.unpack_from('>I', s, 8)[0]
            if stype == 0 and member == 0 and list_idx == 0:
                continue
            ink = s[1]
            y, x, h, w = struct.unpack_from('>hhhh', s, 12)
            sp = dict(type=stype, ink=ink & 0x3f, trails=bool(ink & 0x40), stretch=bool(ink & 0x80),
                      foreColor=s[2], backColor=s[3], castLib=cast_lib, member=member,
                      locV=y, locH=x, height=h, width=w, colorcode=s[20], blend=s[21],
                      thickness=s[22], flags=s[23],
                      fgG=s[24], bgG=s[25], fgB=s[26], bgB=s[27],
                      rotation=struct.unpack_from('>i', s, 28)[0],
                      skew=struct.unpack_from('>i', s, 32)[0])
            if list_idx:
                sp['info'] = sprite_info(list_idx)
                sp['behaviors'] = behaviors(list_idx)
            sprites[ch + 1] = sp
        result.append(dict(frame=fi + 1, main=main, sprites=sprites))
    return dict(numChannels=num_channels, displayed=displayed, framesVersion=frames_version,
                frames=result)
