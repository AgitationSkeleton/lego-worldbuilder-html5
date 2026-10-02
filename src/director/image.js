// Lingo's image objects (imaging Lingo): a canvas, with its pixels kept in an ImageData
// while scripts work on them one at a time.

import { LColor, LRect, LPoint, LPropList, num, toInt, sym, str, LingoError } from './lingo.js';

export class LImage {
  constructor(w, h, depth) {
    this.width = Math.max(1, w | 0);
    this.height = Math.max(1, h | 0);
    this.depth = depth || 32;
    this.useAlpha = false;
    this._canvas = null;
    this._data = null;      // ImageData, when the pixels were last touched one at a time
    this.indices = null;    // palette indices, for indexed bitmaps read with getPixel
    this.palette = null;
    this.onChange = null;
  }
  static blank(w, h, depth) {
    const im = new LImage(w, h, depth);
    const c = im.ensureCanvas();
    const ctx = c.getContext('2d');
    // a new image is white, as Director makes them
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, im.width, im.height);
    return im;
  }
  static fromCanvas(src, depth, useAlpha) {
    const im = new LImage(src.width, src.height, depth);
    const c = im.ensureCanvas();
    c.getContext('2d').drawImage(src, 0, 0);
    im.useAlpha = !!useAlpha;
    return im;
  }
  ensureCanvas() {
    if (!this._canvas) {
      this._canvas = document.createElement('canvas');
      this._canvas.width = this.width;
      this._canvas.height = this.height;
    }
    return this._canvas;
  }
  get canvas() {
    const c = this.ensureCanvas();
    if (this._data && this._dataDirty) {
      c.getContext('2d').putImageData(this._data, 0, 0);
      this._dataDirty = false;
    }
    return c;
  }
  data() {
    if (!this._data) {
      this._data = this.ensureCanvas().getContext('2d', { willReadFrequently: true }).getImageData(0, 0, this.width, this.height);
      this._dataDirty = false;
    }
    return this._data;
  }
  // Drawing on the canvas makes the pixel copy stale.
  touchCanvas() {
    if (this._data && this._dataDirty) {
      this.ensureCanvas().getContext('2d').putImageData(this._data, 0, 0);
    }
    this._data = null;
    this._dataDirty = false;
    this.indices = null;
    this.changed();
  }
  changed() { if (this.onChange) this.onChange(); }
  duplicateImage() {
    const im = new LImage(this.width, this.height, this.depth);
    im.ensureCanvas().getContext('2d').drawImage(this.canvas, 0, 0);
    im.useAlpha = this.useAlpha;
    if (this.indices) { im.indices = this.indices.slice(); im.palette = this.palette; }
    return im;
  }
  getPixel(x, y) {
    x = x | 0; y = y | 0;
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return 0;
    if (this.indices && this.depth <= 8) return new LColor(0, 0, 0, this.indices[y * this.width + x]);
    const d = this.data().data;
    const o = (y * this.width + x) * 4;
    return new LColor(d[o], d[o + 1], d[o + 2]);
  }
  setPixel(x, y, c) {
    x = x | 0; y = y | 0;
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return 0;
    const rgb = this.rgbOf(c);
    const d = this.data().data;
    const o = (y * this.width + x) * 4;
    d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = 255;
    this._dataDirty = true;
    if (this.indices && c instanceof LColor && c.index !== undefined) this.indices[y * this.width + x] = c.index;
    this.changed();
    return 1;
  }
  rgbOf(c) {
    if (c instanceof LColor) {
      if (c.index !== undefined && c.r === undefined) return LImage.paletteRGB(c.index);
      return [c.r | 0, c.g | 0, c.b | 0];
    }
    if (typeof c === 'number') return LImage.paletteRGB(c);
    return [0, 0, 0];
  }
  fill(rect, c) {
    const rgb = this.rgbOf(c);
    const ctx = this.canvas.getContext('2d');
    ctx.fillStyle = 'rgb(' + rgb.join(',') + ')';
    ctx.fillRect(num(rect.l), num(rect.t), num(rect.r) - num(rect.l), num(rect.b) - num(rect.t));
    this.touchCanvas();
  }
  copyPixels(src, destRect, srcRect, params) {
    const s = src instanceof LImage ? src.canvas : null;
    if (!s) return;
    const ctx = this.canvas.getContext('2d');
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    let blend = 100;
    if (params instanceof LPropList) {
      const i = params.find(sym('blend'));
      if (i >= 0) blend = num(params.v[i]);
    }
    ctx.globalAlpha = blend / 100;
    let dl, dt, dw, dh;
    if (destRect instanceof LRect) {
      dl = num(destRect.l); dt = num(destRect.t); dw = num(destRect.r) - dl; dh = num(destRect.b) - dt;
    } else {
      dl = 0; dt = 0; dw = this.width; dh = this.height;
    }
    const sl = num(srcRect.l), st = num(srcRect.t), sw = num(srcRect.r) - sl, sh = num(srcRect.b) - st;
    if (sw > 0 && sh > 0 && dw > 0 && dh > 0) {
      // Copy ink replaces what is there, alpha and all, unless the source uses alpha.
      if (!src.useAlpha) ctx.clearRect(dl, dt, dw, dh);
      ctx.drawImage(s, sl, st, sw, sh, dl, dt, dw, dh);
    }
    ctx.restore();
    this.touchCanvas();
  }
  lgGet(name) {
    switch (name) {
      case 'width': return this.width;
      case 'height': return this.height;
      case 'rect': return new LRect(0, 0, this.width, this.height);
      case 'depth': return this.depth;
      case 'usealpha': return this.useAlpha ? 1 : 0;
      case 'ilk': return sym('image');
    }
    return undefined;
  }
  lgSet(name, v) {
    if (name === 'usealpha') { this.useAlpha = !!toInt(v); this.changed(); }
  }
  lgCall(name, args) {
    switch (name) {
      case 'getpixel': {
        if (args[0] instanceof LPoint) return this.getPixel(toInt(args[0].h), toInt(args[0].v));
        return this.getPixel(toInt(args[0]), toInt(args[1]));
      }
      case 'setpixel': {
        if (args[0] instanceof LPoint) return this.setPixel(toInt(args[0].h), toInt(args[0].v), args[1]);
        return this.setPixel(toInt(args[0]), toInt(args[1]), args[2]);
      }
      case 'copypixels': this.copyPixels(args[0], args[1], args[2], args[3]); return;
      case 'fill': {
        if (args[0] instanceof LRect) this.fill(args[0], args[1]);
        else this.fill(new LRect(args[0], args[1], args[2], args[3]), args[4]);
        return;
      }
      case 'duplicate': return this.duplicateImage();
      case 'crop': {
        const r = args[0];
        const im = LImage.blank(num(r.r) - num(r.l), num(r.b) - num(r.t), this.depth);
        im.canvas.getContext('2d').drawImage(this.canvas, -num(r.l), -num(r.t));
        im.touchCanvas();
        return im;
      }
    }
    throw new LingoError('image has no method ' + name);
  }
  lgIlk() { return 'image'; }
  lgRepr() { return '<image:' + this.width + 'x' + this.height + '>'; }
}

// The movie's palette, for colours given as palette indices.
LImage.palette = null;
LImage.paletteRGB = (i) => {
  const p = LImage.palette;
  i = i | 0;
  if (!p || i < 0 || i > 255) return [0, 0, 0];
  return [p[i * 3], p[i * 3 + 1], p[i * 3 + 2]];
};
