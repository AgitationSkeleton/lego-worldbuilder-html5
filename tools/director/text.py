"""Text cast members (Text Asset Xtra, 'XMED' media).

The media is a header followed by numbered sections, each introduced by 0x03, a
four-digit hex tag, an eight-digit length and an eight-digit item count.  Inside, a
section is a stream of values:

    0x01 hex   a 16-bit value          0x81      the last 16-bit value again
    0x02 hex   a 32-bit value          0x82      the last 32-bit value again
    0x00 n,..  n bytes                 0xC1 n    n 16-bit zeros
                                       0xC2 n    n 32-bit zeros

The sections this port reads (worked out against Director's own RTF exports):

    0002  the text (Mac Roman, paragraphs separated by CR)
    0004  character runs: (offset, style index) pairs
    0005  paragraph runs: (offset, paragraph style index) pairs
    0006  character styles: one 16-bit value, then 77 values per style:
            [0] font index into 0008, [3] ascent, [4] descent, [5] leading,
            [9..11] colour (16 bits a channel), [18] size, [23] letter spacing
            (both 16.16 fixed point)
    0007  paragraph styles, 54 values each: [0] alignment (0 left, 1 centre,
            2 right, 3 justified), [8] fixed line height (0 for automatic),
            [10] space before, [11] space after
    0008  the font names, 64-byte Pascal strings
    0009  the member's rectangle: top, left, bottom, right
"""

import re

HEX = set(b'0123456789ABCDEFabcdef-')


def _values(x, pos, end):
    out = []
    last = {1: 0, 2: 0}
    while pos < end:
        b = x[pos]
        if b in (1, 2):
            j = pos + 1
            while j < end and x[j] in HEX:
                j += 1
            v = int(x[pos + 1:j].decode(), 16) if j > pos + 1 else 0
            out.append(v)
            last[b] = v
            pos = j
        elif b == 0:
            j = x.index(b',', pos + 1)
            n = int(x[pos + 1:j].decode(), 16)
            out.append(bytes(x[j + 1:j + 1 + n]))
            pos = j + 1 + n
        elif b in (0x81, 0x82):
            out.append(last[b & 3])
            pos += 1
        elif b in (0xC1, 0xC2):
            out += [0] * x[pos + 1]
            last[b & 3] = 0
            pos += 2
        else:
            pos += 1
    return out


def sections(x):
    marks = [m.start() for m in re.finditer(rb'\x03[0-9A-F]{20}', x)]
    secs = {}
    texts = []
    for i, pos in enumerate(marks):
        tag = x[pos + 1:pos + 5].decode()
        cnt = int(x[pos + 13:pos + 21], 16)
        start = pos + 21
        end = marks[i + 1] if i + 1 < len(marks) else len(x)
        if tag == '0002':
            # Long text comes in pieces, each with its offset in the count field.
            texts.append((cnt, x[start:end]))
        if tag not in secs:
            secs[tag] = (cnt, _values(x, start, end), x[start:end])
    secs['text pieces'] = sorted(texts, key=lambda t: t[0])
    return secs


def _pairs(vals):
    vals = [v for v in vals if isinstance(v, int)]
    return [[vals[i], vals[i + 1]] for i in range(0, len(vals) - 1, 2)]


def parse_text_member(x):
    secs = sections(x)
    text = ''
    for _, raw in secs['text pieces']:
        if raw[:1] == b'\x00':
            j = raw.index(b',')
            n = int(raw[1:j].decode(), 16)
            text += raw[j + 1:j + 1 + n].decode('mac_roman')
    fonts = []
    if '0008' in secs:
        for v in secs['0008'][1]:
            if isinstance(v, bytes) and v[:1] != b'\x00':
                fonts.append(v[1:1 + v[0]].decode('mac_roman'))
    styles = []
    if '0006' in secs:
        cnt, vals, _ = secs['0006']
        vals = [v if isinstance(v, int) else 0 for v in vals]
        for i in range(cnt):
            r = vals[1 + i * 77:1 + (i + 1) * 77]
            if len(r) < 77:
                break
            styles.append(dict(
                font=fonts[r[0]] if r[0] < len(fonts) else (fonts[0] if fonts else 'Arial'),
                ascent=r[3], descent=r[4], leading=r[5],
                color=[r[9] >> 8, r[10] >> 8, r[11] >> 8],
                size=r[18] / 65536, spacing=_signed(r[23]) / 65536))
    paras = []
    if '0007' in secs:
        cnt, vals, _ = secs['0007']
        vals = [v if isinstance(v, int) else 0 for v in vals]
        n = len(vals) // cnt if cnt else 0
        for i in range(cnt):
            r = vals[i * n:(i + 1) * n]
            paras.append(dict(align=['left', 'center', 'right', 'justify'][r[0]] if 0 <= r[0] < 4 else 'left',
                              lineHeight=r[8], spaceBefore=r[10], spaceAfter=r[11]))
    runs = _pairs(secs['0004'][1]) if '0004' in secs else []
    pruns = _pairs(secs['0005'][1]) if '0005' in secs else []
    rect = None
    if '0009' in secs:
        v = [a for a in secs['0009'][1] if isinstance(a, int)]
        if len(v) >= 4:
            rect = dict(top=v[0], left=v[1], bottom=v[2], right=v[3])
    return dict(text=text, fonts=fonts, styles=styles, paras=paras, runs=runs, paraRuns=pruns, rect=rect)


def _signed(v):
    return v - (1 << 32) if v >= 1 << 31 else v
