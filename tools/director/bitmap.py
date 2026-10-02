"""Bitmap cast members: their header, and their pixels from BITD (run-length rows), or from
a JPEG in ediM with an optional ALFA alpha channel, as Shockwave's image compression
stores them."""

import io
import json
import os
import struct

from PIL import Image

from .dirfile import Reader

_BUILTIN = json.load(open(os.path.join(os.path.dirname(__file__), 'builtin_palettes.json')))
# Built-in palettes by Director's numbering (castLib -1).
BUILTIN_PALETTES = {
    -1: _BUILTIN['macPalette'], -2: _BUILTIN['rainbowPalette'], -3: _BUILTIN['grayscalePalette'],
    -4: _BUILTIN['pastelsPalette'], -5: _BUILTIN['vividPalette'], -6: _BUILTIN['ntscPalette'],
    -7: _BUILTIN['metallicPalette'], -101: _BUILTIN['winPalette'], -102: _BUILTIN['winD5Palette'],
}
# Windows' sky blue, as Director itself shows it.
BUILTIN_PALETTES[-102][246 * 3:246 * 3 + 3] = [166, 202, 240]
GRAY4 = [255, 255, 255, 170, 170, 170, 85, 85, 85, 0, 0, 0]


def nearest(pal, rgb):
    best, bd = 0, 1 << 30
    for i in range(len(pal) // 3):
        dr, dg, db = pal[i * 3] - rgb[0], pal[i * 3 + 1] - rgb[1], pal[i * 3 + 2] - rgb[2]
        dd = dr * dr + dg * dg + db * db
        if dd < bd:
            bd, best = dd, i
    return tuple(pal[best * 3:best * 3 + 3])


def system_mapped(pal, bpp):
    """A 2- or 4-bit bitmap's colours as Director shows them: its palette's entries (or, for a
    built-in palette, evenly spaced greys) moved to the nearest colour of the system palette."""
    n = 1 << bpp
    if pal is None:
        step = 255 // (n - 1)
        pal = []
        for i in range(n):
            v = 255 - i * step
            pal += [v, v, v]
    out = []
    for i in range(n):
        c = pal[i * 3:i * 3 + 3] if i * 3 + 2 < len(pal) else [0, 0, 0]
        out += list(nearest(BUILTIN_PALETTES[-102], c))
    return out


def parse_bitmap_header(spec):
    r = Reader(spec, True)
    pitch = r.u16()
    top, left, bottom, right = r.i16(), r.i16(), r.i16(), r.i16()
    h = dict(top=top, left=left, width=right - left, height=bottom - top)
    if r.left() < 14:
        # A short header: a 1-bit bitmap with nothing more to say.
        h.update(pitch=pitch & 0x3fff, regX=(right - left) // 2, regY=(bottom - top) // 2,
                 bitDepth=1, paletteLib=-1, palette=-1, updateFlags=0, alphaThreshold=0)
        if r.left() >= 12:
            r.pos = 18
            h['regY'], h['regX'] = r.i16() - top, r.i16() - left
        return h
    h['alphaThreshold'] = r.u8()
    r.u8()
    r.u16()  # edit version
    r.i16(); r.i16()  # scroll point
    reg_y, reg_x = r.i16(), r.i16()
    h['regX'] = reg_x - left
    h['regY'] = reg_y - top
    h['updateFlags'] = r.u8() if r.left() else 0
    if pitch & 0x8000:
        h['pitch'] = pitch & 0x3fff
        h['bitDepth'] = r.u8()
        h['paletteLib'] = r.i16()
        clut = r.i16()
        # Built-in palettes are stored one below Director's own numbering.
        h['palette'] = clut - 1 if clut <= 0 else clut
        if clut <= 0:
            h['paletteLib'] = -1
    else:
        h['pitch'] = pitch & 0x3fff
        h['bitDepth'] = 1
        h['paletteLib'] = -1
        h['palette'] = -1
    return h


def unpack_rle(data, need):
    out = bytearray()
    i = 0
    n = len(data)
    while i < n and len(out) < need:
        c = data[i]
        i += 1
        if c & 0x80:
            ln = 257 - c
            if i >= n:
                break
            out += bytes([data[i]]) * ln
            i += 1
        else:
            ln = c + 1
            out += data[i:i + ln]
            i += ln
    if len(out) < need:
        out += bytes(need - len(out))
    return bytes(out[:need])


def palette_rgb(clut_data):
    """A CLUT chunk: 16-bit R, G, B per entry; the top byte of each is the colour."""
    pal = []
    for i in range(0, len(clut_data) - 5, 6):
        r, g, b = struct.unpack_from('>HHH', clut_data, i)
        pal += [r >> 8, g >> 8, b >> 8]
    return pal


def decode_bitd(data, h, palette):
    """Pixels as an RGBA PIL image (and the raw palette indices for indexed depths)."""
    w, ht, bpp = h['width'], h['height'], h['bitDepth']
    if w <= 0 or ht <= 0:
        return None, None
    if bpp == 32:
        row = w * 4
    elif bpp == 16:
        row = w * 2
        if row % 2:
            row += 1
    else:
        row = h['pitch'] or ((w * bpp + 15) // 16 * 2)
    need = row * ht
    packed = len(data) != need
    raw = unpack_rle(data, need) if packed else data
    img = Image.new('RGBA', (w, ht))
    px = img.load()
    indices = None
    if bpp == 32:
        use_alpha = bool(h['updateFlags'] & 0x10)
        for y in range(ht):
            o = y * row
            if packed:
                # Compressed rows hold each channel in turn: alpha, red, green, blue.
                a = raw[o:o + w]
                rr = raw[o + w:o + 2 * w]
                gg = raw[o + 2 * w:o + 3 * w]
                bb = raw[o + 3 * w:o + 4 * w]
            else:
                a, rr, gg, bb = raw[o:o + row:4], raw[o + 1:o + row:4], raw[o + 2:o + row:4], raw[o + 3:o + row:4]
            for x in range(w):
                px[x, y] = (rr[x], gg[x], bb[x], a[x] if use_alpha else 255)
    elif bpp == 16:
        for y in range(ht):
            o = y * row
            for x in range(w):
                c = ((raw[o + x] << 8) | raw[o + w + x]) if packed else ((raw[o + 2 * x] << 8) | raw[o + 2 * x + 1])
                r5, g5, b5 = (c >> 10) & 31, (c >> 5) & 31, c & 31
                px[x, y] = ((r5 << 3) | (r5 >> 2), (g5 << 3) | (g5 >> 2), (b5 << 3) | (b5 >> 2), 255)
    else:
        indices = bytearray(w * ht)
        per = 8 // bpp
        mask = (1 << bpp) - 1
        for y in range(ht):
            o = y * row
            for x in range(w):
                byte = raw[o + x // per]
                shift = (per - 1 - x % per) * bpp
                v = (byte >> shift) & mask
                indices[y * w + x] = v
        if bpp == 2:
            palette = system_mapped(palette, bpp)
        for y in range(ht):
            for x in range(w):
                v = indices[y * w + x]
                if bpp == 1:
                    c = (0, 0, 0) if v else (255, 255, 255)
                else:
                    c = tuple(palette[v * 3:v * 3 + 3]) if v * 3 + 2 < len(palette) else (0, 0, 0)
                px[x, y] = c + (255,)
    return img, indices


def decode_jpeg(jpeg, alfa, h):
    img = Image.open(io.BytesIO(jpeg)).convert('RGBA')
    w, ht = h['width'], h['height']
    if img.size != (w, ht):
        canvas = Image.new('RGBA', (w, ht), (255, 255, 255, 255))
        canvas.paste(img, (0, 0))
        img = canvas
    if alfa:
        scan = w + (w & 1)
        a = unpack_rle(alfa, scan * ht) if len(alfa) != scan * ht else alfa
        alpha = Image.frombytes('L', (scan, ht), a).crop((0, 0, w, ht))
        img.putalpha(alpha)
    return img
