"""Fonts embedded in the movie (Font Asset Xtra members, PFR1 data in XMED) as OpenType.

PFR1 is decoded by LibreShockwave's parser (see tools/extract.py), which gives each glyph's
outline as moves, lines and cubic curves; those go into a CFF-flavoured OpenType font,
which keeps the curves as they are.
"""

import json

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen

MOVE, LINE, CURVE = 0, 1, 2


def build_otf(pfr_json_path, family, out_path):
    src = json.load(open(pfr_json_path))
    upem = src['outlineResolution']
    glyph_order = ['.notdef']
    cmap = {}
    charstrings = {}
    metrics = {}
    for g in src['glyphs']:
        code = g['code']
        name = '.notdef' if code == 0 else 'uni%04X' % code
        if code != 0:
            glyph_order.append(name)
            cmap[code] = name
        width = round(g['setWidth'])
        pen = T2CharStringPen(width, None)
        xmin = None
        for contour in g['contours']:
            open_path = False
            for cmd in contour:
                t, x, y, x1, y1, x2, y2 = cmd
                if t == MOVE:
                    if open_path:
                        pen.closePath()
                    pen.moveTo((x, y))
                    open_path = True
                elif t == LINE:
                    pen.lineTo((x, y))
                elif t == CURVE:
                    pen.curveTo((x1, y1), (x2, y2), (x, y))
                xs = [x] + ([x1, x2] if t == CURVE else [])
                lo = min(xs)
                xmin = lo if xmin is None else min(xmin, lo)
            if open_path:
                pen.closePath()
        charstrings[name] = pen.getCharString()
        metrics[name] = (width, round(xmin) if xmin is not None else 0)
    if '.notdef' not in charstrings:
        pen = T2CharStringPen(upem // 2, None)
        charstrings['.notdef'] = pen.getCharString()
        metrics['.notdef'] = (upem // 2, 0)
    fb = FontBuilder(upem, isTTF=False)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    ps_name = family.replace(' ', '') + '-Director'
    fb.setupCFF(ps_name, {'FullName': family}, charstrings, {})
    fb.setupHorizontalMetrics(metrics)
    asc = src['ascender']
    desc = src['descender']
    fb.setupHorizontalHeader(ascent=asc, descent=desc)
    fb.setupNameTable({'familyName': family, 'styleName': 'Regular'})
    fb.setupOS2(sTypoAscender=asc, sTypoDescender=desc, usWinAscent=asc, usWinDescent=-desc)
    fb.setupPost()
    fb.save(out_path)
