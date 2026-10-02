// Drawing the stage: the sprites in locZ order, with Director's inks.
//
// The stage is drawn straight at the window's resolution (scaled to fit, letterboxed),
// so text is laid out at the movie's size but drawn sharp.

import { BitmapMember, TextMember, ShapeMember, ButtonMember } from './members.js';

const INK_COPY = 0, INK_MATTE = 8, INK_BLEND = 32, INK_BG_TRANSPARENT = 36;

export class Renderer {
  constructor(runtime, canvas) {
    this.runtime = runtime;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.scale = 1;
    this.ox = 0;
    this.oy = 0;
    this.dpr = 1;
    this.textCache = new WeakMap();
    this.order = [];
  }
  resize() {
    const st = this.runtime.stage;
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.dpr = dpr;
    this.scale = Math.min(w / st.width, h / st.height);
    this.ox = Math.round((w - st.width * this.scale) / 2);
    this.oy = Math.round((h - st.height * this.scale) / 2);
  }
  // Stage coordinates of a point on the page.
  toStage(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const x = ((clientX - r.left) * this.dpr - this.ox) / this.scale;
    const y = ((clientY - r.top) * this.dpr - this.oy) / this.scale;
    return [Math.floor(x), Math.floor(y)];
  }
  sorted() {
    const rt = this.runtime;
    const list = [];
    for (const s of rt.sprites) if (s && s.member && s.visible) list.push(s);
    list.sort((a, b) => (a.locZ - b.locZ) || (a.channel - b.channel));
    return list;
  }
  draw() {
    const rt = this.runtime;
    const ctx = this.ctx;
    const st = rt.stage;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.setTransform(this.scale, 0, 0, this.scale, this.ox, this.oy);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, st.width, st.height);
    ctx.clip();
    ctx.fillStyle = 'rgb(' + st.color.join(',') + ')';
    ctx.fillRect(0, 0, st.width, st.height);
    ctx.imageSmoothingEnabled = this.scale !== Math.round(this.scale);
    ctx.imageSmoothingQuality = 'high';
    const list = this.sorted();
    this.order = list;
    for (const s of list) this.drawSprite(ctx, s);
    ctx.restore();
  }
  drawSprite(ctx, s) {
    const m = s.member;
    const alpha = s.blend / 100;
    if (alpha <= 0) return;
    ctx.globalAlpha = alpha;
    if (m instanceof BitmapMember) {
      const src = this.inked(m, s);
      if (!src) return;
      const w = s.width, h = s.height;
      if (w <= 0 || h <= 0) return;
      const x = s.left, y = s.top;
      if (s.flipH || s.flipV) {
        ctx.save();
        ctx.translate(x + (s.flipH ? w : 0), y + (s.flipV ? h : 0));
        ctx.scale(s.flipH ? -1 : 1, s.flipV ? -1 : 1);
        ctx.drawImage(src, 0, 0, w, h);
        ctx.restore();
      } else {
        ctx.drawImage(src, x, y, w, h);
      }
    } else if (m instanceof TextMember) {
      this.drawText(ctx, s, m);
    } else if (m instanceof ShapeMember) {
      this.drawShape(ctx, s, m);
    }
    ctx.globalAlpha = 1;
  }
  spriteRGB(s, fore) {
    if (fore && s.foreRGB) return s.foreRGB;
    if (!fore && s.backRGB) return s.backRGB;
    return this.runtime.paletteRGB(fore ? s.foreColor : s.backColor);
  }
  drawShape(ctx, s, m) {
    const rgb = this.spriteRGB(s, true);
    const x = s.left, y = s.top, w = s.width, h = s.height;
    const r = m.rec;
    ctx.fillStyle = ctx.strokeStyle = 'rgb(' + rgb.join(',') + ')';
    if (r.shapeType === 'oval') {
      ctx.beginPath();
      ctx.ellipse(x + w / 2, y + h / 2, Math.max(0, w / 2), Math.max(0, h / 2), 0, 0, Math.PI * 2);
      if (r.filled) ctx.fill(); else if (r.lineSize) { ctx.lineWidth = r.lineSize; ctx.stroke(); }
      return;
    }
    if (r.shapeType === 'line') {
      ctx.lineWidth = Math.max(1, r.lineSize);
      ctx.beginPath();
      if (r.lineDirection === 6) { ctx.moveTo(x, y + h); ctx.lineTo(x + w, y); } else { ctx.moveTo(x, y); ctx.lineTo(x + w, y + h); }
      ctx.stroke();
      return;
    }
    if (r.filled) {
      if (s.ink !== INK_BG_TRANSPARENT || rgb.join() !== this.spriteRGB(s, false).join()) ctx.fillRect(x, y, w, h);
    } else if (r.lineSize > 0) {
      const lw = r.lineSize;
      ctx.fillRect(x, y, w, lw);
      ctx.fillRect(x, y + h - lw, w, lw);
      ctx.fillRect(x, y, lw, h);
      ctx.fillRect(x + w - lw, y, lw, h);
    }
  }
  drawText(ctx, s, m) {
    const layout = m.layout();
    const w = m.width, h = layout.height;
    const x = s.locH, y = s.locV;
    if (s.ink === INK_COPY) {
      ctx.fillStyle = 'rgb(' + this.spriteRGB(s, false).join(',') + ')';
      ctx.fillRect(x, y, w, h);
    }
    const scale = this.scale;
    let entry = this.textCache.get(m);
    if (!entry || entry.version !== m.version || entry.scale !== scale) {
      const c = entry && entry.canvas ? entry.canvas : document.createElement('canvas');
      c.width = Math.max(1, Math.ceil(w * scale) + 2);
      c.height = Math.max(1, Math.ceil(h * scale) + 2);
      const tctx = c.getContext('2d');
      tctx.setTransform(scale, 0, 0, scale, 0, 0);
      tctx.textBaseline = 'alphabetic';
      layout.draw(tctx, this.runtime.textMeasure);
      entry = { canvas: c, version: m.version, scale };
      this.textCache.set(m, entry);
    }
    ctx.drawImage(entry.canvas, x, y, entry.canvas.width / scale, entry.canvas.height / scale);
  }
  // A bitmap with the sprite's ink applied, kept for the next time.
  inked(m, s) {
    const ink = s.ink;
    if (ink !== INK_MATTE && ink !== INK_BG_TRANSPARENT) return m.drawable();
    const bg = ink === INK_BG_TRANSPARENT ? this.spriteRGB(s, false) : [255, 255, 255];
    const key = ink + ':' + bg.join(',');
    let c = m.inkCache.get(key);
    if (c) return c;
    c = makeInked(m, ink, bg);
    m.inkCache.set(key, c);
    return c;
  }
  // Is a stage point on a sprite?  Matte sprites only where they are not transparent.
  hit(s, x, y) {
    const m = s.member;
    if (!m || !s.visible) return false;
    const l = s.left, t = s.top, w = s.width, h = s.height;
    if (m instanceof TextMember) {
      return x >= s.locH && y >= s.locV && x < s.locH + m.width && y < s.locV + m.height;
    }
    if (x < l || y < t || x >= l + w || y >= t + h) return false;
    if (m instanceof BitmapMember && s.ink === INK_MATTE) {
      const c = this.inked(m, s);
      let mask = c._mask;
      if (!mask) {
        const cc = c.getContext ? c : null;
        if (!cc) return true;
        mask = c._mask = cc.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      }
      let px = Math.floor((x - l) * m.width / w), py = Math.floor((y - t) * m.height / h);
      if (s.flipH) px = m.width - 1 - px;
      if (s.flipV) py = m.height - 1 - py;
      return mask[(py * c.width + px) * 4 + 3] > 0;
    }
    return true;
  }
}

function makeInked(m, ink, bg) {
  const src = m.canvas();
  const w = src.width, h = src.height;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(src, 0, 0);
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const [br, bgG, bb] = bg;
  if (ink === INK_BG_TRANSPARENT) {
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] === br && d[i + 1] === bgG && d[i + 2] === bb) d[i + 3] = 0;
    }
  } else {
    // Matte: the white that reaches the edges of the bitmap is taken away.
    const seen = new Uint8Array(w * h);
    const stack = [];
    const isBg = (p) => d[p * 4] === 255 && d[p * 4 + 1] === 255 && d[p * 4 + 2] === 255;
    const push = (p) => { if (!seen[p] && isBg(p)) { seen[p] = 1; stack.push(p); } };
    for (let x = 0; x < w; x++) { push(x); push((h - 1) * w + x); }
    for (let y = 0; y < h; y++) { push(y * w); push(y * w + w - 1); }
    while (stack.length) {
      const p = stack.pop();
      d[p * 4 + 3] = 0;
      const x = p % w, y = (p - x) / w;
      if (x > 0) push(p - 1);
      if (x < w - 1) push(p + 1);
      if (y > 0) push(p - w);
      if (y < h - 1) push(p + w);
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}
