# -*- coding: utf-8 -*-
"""3.0: the pictures of the new look - rounded cards, pills, circles, avatars, the waveform, the
geometric art of the home screen.  Enigma2 cannot round a corner or draw a circle, so they are drawn
here once as small PNG files (anti-aliased) and kept in /tmp/sqh_ui (a few hundred KB).

Everything is drawn row by row (straight runs are copied, only the curved edges are computed), so a
full panel takes a few milliseconds even on a small receiver."""
import hashlib
import math
import os
import threading
import struct
import zlib

CACHE = "/tmp/sqh_ui"


def rgba(c, a=255):
    """'#rrggbb' / '#aarrggbb' (enigma2 style: aa = transparency) / 0xrrggbb -> (r, g, b, a)."""
    if isinstance(c, tuple):
        return c if len(c) == 4 else c + (a,)
    if isinstance(c, int):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255, a)
    h = c.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) == 8:                         # enigma2: first byte is the transparency
        return (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), 255 - int(h[0:2], 16))
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


class Canvas(object):
    def __init__(self, w, h, bg=None):
        self.w, self.h = int(w), int(h)
        px = bytes(rgba(bg)) if bg else b"\x00\x00\x00\x00"
        self.buf = bytearray(px * (self.w * self.h))

    # -- pixels -----------------------------------------------------------------------------------
    def blend(self, x, y, col, cov):
        """Draw one pixel of col with coverage cov (0..1) over what is there."""
        if cov <= 0 or x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        i = (y * self.w + x) * 4
        r, g, b, a = col
        sa = a * min(1.0, cov) / 255.0
        if sa >= 0.999:
            self.buf[i:i + 4] = bytes((r, g, b, 255))
            return
        dr, dg, db, da = self.buf[i], self.buf[i + 1], self.buf[i + 2], self.buf[i + 3] / 255.0
        oa = sa + da * (1 - sa)
        if oa <= 0:
            return
        self.buf[i] = int((r * sa + dr * da * (1 - sa)) / oa + 0.5)
        self.buf[i + 1] = int((g * sa + dg * da * (1 - sa)) / oa + 0.5)
        self.buf[i + 2] = int((b * sa + db * da * (1 - sa)) / oa + 0.5)
        self.buf[i + 3] = int(oa * 255 + 0.5)

    def span(self, y, x0, x1, col):
        """Fill [x0, x1) of row y (floats: the two edge pixels get their coverage)."""
        if y < 0 or y >= self.h or x1 <= x0:
            return
        x0, x1 = max(0.0, x0), min(float(self.w), x1)
        a, b = int(math.ceil(x0)), int(math.floor(x1))
        if a > b:                                   # inside one pixel
            self.blend(int(x0), y, col, x1 - x0)
            return
        if a - x0 > 0:
            self.blend(a - 1, y, col, a - x0)
        if x1 - b > 0:
            self.blend(b, y, col, x1 - b)
        if b > a:
            if col[3] >= 255:
                i = (y * self.w + a) * 4
                self.buf[i:i + (b - a) * 4] = bytes(col) * (b - a)
            else:
                for x in range(a, b):
                    self.blend(x, y, col, 1.0)

    # -- shapes -----------------------------------------------------------------------------------
    @staticmethod
    def _inset(r, yy, top, bottom):
        """How far a rounded corner pushes row yy (pixel centre) in."""
        if yy < top + r:
            d = top + r - yy
        elif yy > bottom - r:
            d = yy - (bottom - r)
        else:
            return 0.0
        if d >= r:
            return r
        return r - math.sqrt(r * r - d * d)

    def row_cov(self, py, lefts, rights, col, sub):
        """One row of a convex shape: lefts / rights = edge positions of each sub-row (None = outside).
        Full pixels are copied in one go; only the edge pixels are computed."""
        ins = [(l, r_) for l, r_ in zip(lefts, rights) if l is not None]
        if not ins:
            return
        frac = len(ins) / float(sub)
        lmax = max(l for l, _r in ins)
        rmin = min(r_ for _l, r_ in ins)
        lmin = min(l for l, _r in ins)
        rmax = max(r_ for _l, r_ in ins)
        a = int(math.ceil(lmax))
        b = int(math.floor(rmin))
        inner = col[:3] + (int(col[3] * frac),)
        if b > a:
            self.span(py, a, b, inner)
        for px in list(range(int(math.floor(lmin)), min(a, b) if b > a else a)) + \
                list(range(max(b, a) if b > a else int(math.floor(lmin)), int(math.ceil(rmax)))):
            if b > a and a <= px < b:
                continue
            cov = 0.0
            for l, r_ in ins:
                cov += max(0.0, min(px + 1.0, r_) - max(float(px), l))
            self.blend(px, py, col, cov / sub)

    def rrect(self, x, y, w, h, r, col, sub=4):
        """Filled rounded rectangle, anti-aliased."""
        col = rgba(col)
        r = max(0.0, min(r, w / 2.0, h / 2.0))
        top, bottom = float(y), float(y + h)
        for py in range(max(0, int(y)), min(self.h, int(math.ceil(y + h)))):
            cy = py + 0.5
            if top + r <= cy - 0.5 and cy + 0.5 <= bottom - r:
                self.span(py, x, x + w, col)              # straight part of the shape
                continue
            ls, rs = [], []
            for s_ in range(sub):
                yy = py + (s_ + 0.5) / sub
                if yy < top or yy > bottom:
                    ls.append(None)
                    rs.append(None)
                    continue
                ins = self._inset(r, yy, top, bottom)
                ls.append(x + ins)
                rs.append(x + w - ins)
            self.row_cov(py, ls, rs, col, sub)

    def rrect_stroke(self, x, y, w, h, r, t, col, sub=4):
        """Rounded outline of thickness t, row by row (outer shape minus inner shape)."""
        col = rgba(col)
        r = max(0.0, min(r, w / 2.0, h / 2.0))
        ri = max(0.0, r - t)
        top, bottom = float(y), float(y + h)
        itop, ibot = top + t, bottom - t
        for py in range(max(0, int(y)), min(self.h, int(math.ceil(y + h)))):
            cy = py + 0.5
            straight = top + r <= cy - 0.5 and cy + 0.5 <= bottom - r and itop + ri <= cy - 0.5 and cy + 0.5 <= ibot - ri
            if straight:
                self.span(py, x, x + t, col)
                self.span(py, x + w - t, x + w, col)
                continue
            acc = {}
            for s_ in range(sub):
                yy = py + (s_ + 0.5) / sub
                if yy < top or yy > bottom:
                    continue
                io_ = self._inset(r, yy, top, bottom)
                if itop < yy < ibot:
                    ii = self._inset(ri, yy, itop, ibot) + t
                    segs = ((round(x + io_, 3), round(x + ii, 3)), (round(x + w - ii, 3), round(x + w - io_, 3)))
                else:
                    segs = ((round(x + io_, 3), round(x + w - io_, 3)),)
                acc[segs] = acc.get(segs, 0) + 1
            for segs, n in acc.items():
                c2 = col[:3] + (int(col[3] * n / float(sub)),)
                for a_, b_ in segs:
                    self.span(py, a_, b_, c2)

    def circle(self, cx, cy, R, col, sub=4):
        col = rgba(col)
        for py in range(max(0, int(cy - R)), min(self.h, int(math.ceil(cy + R)) + 1)):
            ls, rs = [], []
            for s_ in range(sub):
                yy = py + (s_ + 0.5) / sub - cy
                if abs(yy) >= R:
                    ls.append(None)
                    rs.append(None)
                    continue
                hw = math.sqrt(R * R - yy * yy)
                ls.append(cx - hw)
                rs.append(cx + hw)
            self.row_cov(py, ls, rs, col, sub)

    def ring(self, cx, cy, R, t, col, sub=4):
        """Circle outline of thickness t, row by row."""
        col = rgba(col)
        Ri = max(0.0, R - t)
        for py in range(max(0, int(cy - R)), min(self.h, int(math.ceil(cy + R)) + 1)):
            acc = {}
            for s_ in range(sub):
                yy = py + (s_ + 0.5) / sub - cy
                if abs(yy) >= R:
                    continue
                ho = math.sqrt(R * R - yy * yy)
                if abs(yy) < Ri:
                    hi = math.sqrt(Ri * Ri - yy * yy)
                    segs = ((round(cx - ho, 3), round(cx - hi, 3)), (round(cx + hi, 3), round(cx + ho, 3)))
                else:
                    segs = ((round(cx - ho, 3), round(cx + ho, 3)),)
                acc[segs] = acc.get(segs, 0) + 1
            for segs, n in acc.items():
                c2 = col[:3] + (int(col[3] * n / float(sub)),)
                for a_, b_ in segs:
                    self.span(py, a_, b_, c2)

    def line(self, x0, y0, x1, y1, t, col):
        """Anti-aliased straight line of thickness t."""
        col = rgba(col)
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        steep = abs(dy) > abs(dx)
        if steep:
            for y in range(int(min(y0, y1)), int(math.ceil(max(y0, y1))) + 1):
                xc = x0 + dx * ((y + 0.5 - y0) / dy if dy else 0) - 0.5
                half = t / 2.0 / max(1e-6, abs(nx))
                self.span(y, xc - half + 0.5, xc + half + 0.5, col)
        else:
            for x in range(int(min(x0, x1)), int(math.ceil(max(x0, x1))) + 1):
                yc = y0 + dy * ((x + 0.5 - x0) / dx if dx else 0)
                half = t / 2.0 / max(1e-6, abs(ny))
                for y in range(int(yc - half - 1), int(yc + half + 2)):
                    cov = min(1.0, max(0.0, min(y + 1, yc + half) - max(y, yc - half)))
                    self.blend(x, y, col, cov)

    def polygon_stroke(self, pts, t, col):
        for i in range(len(pts)):
            (a, b), (c, d) = pts[i], pts[(i + 1) % len(pts)]
            self.line(a, b, c, d, t, col)

    def mask(self, x, y, w, h, alpha, col):
        """Draw a coverage mask (e.g. letters from qtext) in one colour."""
        col = rgba(col)
        for j in range(h):
            row = j * w
            for i in range(w):
                a = alpha[row + i]
                if a:
                    self.blend(x + i, y + j, col, a / 255.0)

    def paste(self, other):
        for py in range(self.h):
            base = py * self.w * 4
            ob = other.buf
            for i in range(base + 3, base + self.w * 4, 4):
                if ob[i]:
                    px = (i - base) // 4
                    self.blend(px, py, (ob[i - 3], ob[i - 2], ob[i - 1], 255), ob[i] / 255.0)

    # -- output -----------------------------------------------------------------------------------
    def png(self):
        raw = bytearray()
        stride = self.w * 4
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(t, d):
            c = struct.pack(">I", len(d)) + t + d
            return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))

    def save(self, path):
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path + ".tmp", "wb") as f:
            f.write(self.png())
        os.rename(path + ".tmp", path)
        return path


def cached(kind, *args):
    """-> path of a picture made by the drawing function `kind` (made once)."""
    key = hashlib.md5(repr((kind.__name__, args)).encode("utf-8")).hexdigest()[:16]
    path = os.path.join(CACHE, "%s_%s.png" % (kind.__name__, key))
    if not os.path.exists(path):
        tmp = "%s.%d.tmp" % (path, threading.current_thread().ident or 0)
        kind(*args).save(tmp)
        os.rename(tmp, path)
    return path


# ------------------------------------------------------------------ the pieces of the new look
def card(w, h, r, fill, border=None, bw=1):
    c = Canvas(w, h)
    c.rrect(0, 0, w, h, r, fill)
    if border:
        c.rrect_stroke(0, 0, w, h, r, bw, border)
    return c


def card2(w, h, r, fill, border, inner, gap):
    """A card with a second thin frame inside (the light mushaf card)."""
    c = card(w, h, r, fill, border, 2)
    c.rrect_stroke(gap, gap, w - 2 * gap, h - 2 * gap, max(2, r - gap), 1, inner)
    return c


def dot(d, col):
    c = Canvas(d, d)
    c.circle(d / 2.0, d / 2.0, d / 2.0, col)
    return c


def dash(w, h, col):
    c = Canvas(w, h)
    c.rrect(0, 0, w, h, h / 2.0, col)
    return c


def disc(d, fill, ring_col=None, rw=0, glyph=None, gcol="#111111"):
    """A round button: fill, optional ring, optional glyph ('pause', 'play', 'prev', 'next', 'back')."""
    c = Canvas(d, d)
    R = d / 2.0
    if ring_col:
        c.circle(R, R, R, ring_col)
        c.circle(R, R, R - rw, (0, 0, 0, 255))
        c.circle(R, R, R - rw - max(1, rw * 0.6), fill)
    else:
        c.circle(R, R, R, fill)
    s = d * 0.16
    if glyph == "pause":
        bw = d * 0.09
        c.rrect(R - s - bw * 0.2, R - s * 1.15, bw, s * 2.3, bw * 0.25, gcol)
        c.rrect(R + s * 0.2 + bw * 0.2, R - s * 1.15, bw, s * 2.3, bw * 0.25, gcol)
    elif glyph in ("play", "prev", "next", "back"):
        tri(c, R, R, s * 1.25, glyph, gcol)
    return c


def tri(c, cx, cy, s, kind, col):
    """A small solid triangle drawn with spans (play / prev / next / back chevrons)."""
    col = rgba(col)
    if kind == "play":                      # pointing left (RTL players point to the reading direction)
        for y in range(int(cy - s), int(cy + s) + 1):
            k = 1 - abs(y + 0.5 - cy) / s
            if k > 0:
                c.span(y, cx - s * 0.8, cx - s * 0.8 + 1.7 * s * k, col)
    elif kind in ("prev", "next"):
        d = 1 if kind == "next" else -1
        for y in range(int(cy - s * 0.8), int(cy + s * 0.8) + 1):
            k = 1 - abs(y + 0.5 - cy) / (s * 0.8)
            if k > 0:
                if d > 0:
                    c.span(y, cx - s * 0.6, cx - s * 0.6 + 1.2 * s * k, col)
                else:
                    c.span(y, cx + s * 0.6 - 1.2 * s * k, cx + s * 0.6, col)
        bar_x = cx + s * 0.6 if d > 0 else cx - s * 0.6 - s * 0.22
        c.rrect(bar_x, cy - s * 0.8, s * 0.22, s * 1.6, 1, col)
    elif kind == "back":                    # ">" chevron
        c.line(cx - s * 0.35, cy - s * 0.7, cx + s * 0.35, cy, s * 0.28, col)
        c.line(cx + s * 0.35, cy, cx - s * 0.35, cy + s * 0.7, s * 0.28, col)


def ringdisc(d, fill, col, t):
    """A filled circle with a thin outline (ayah numbers)."""
    c = Canvas(d, d)
    c.circle(d / 2.0, d / 2.0, d / 2.0, col)
    c.circle(d / 2.0, d / 2.0, d / 2.0 - t, fill)
    return c


def chevron_tile(d, fill, col):
    c = card(d, d, d * 0.28, fill)
    tri(c, d / 2.0, d / 2.0, d * 0.3, "back", col)
    return c


def gear_tile(d, fill, border, col):
    """The settings tile of the header: a cog drawn with lines and circles."""
    c = card(d, d, d * 0.26, fill, border, max(1, d // 40))
    R = d / 2.0
    for k in range(8):
        a = k * math.pi / 4
        c.line(R + math.cos(a) * d * 0.17, R + math.sin(a) * d * 0.17,
               R + math.cos(a) * d * 0.3, R + math.sin(a) * d * 0.3, d * 0.09, col)
    c.ring(R, R, d * 0.22, d * 0.06, col)
    c.ring(R, R, d * 0.1, d * 0.045, col)
    return c


def search_icon(d, col):
    c = Canvas(d, d)
    c.ring(d * 0.44, d * 0.44, d * 0.3, max(1.2, d * 0.09), col)
    c.line(d * 0.66, d * 0.66, d * 0.88, d * 0.88, max(1.4, d * 0.11), col)
    return c


def letters_mask(text, px):
    """Arabic letters as a coverage mask (qtext joins and shapes them)."""
    from . import qtext
    if not qtext.available():
        return None
    w, h, alpha, _cb, _pal = qtext.compose(text, px, int(px * 1.85))
    return w, h, alpha


def avatar(d, fill, text, tcol, square=False, ring_col=None, rw=0):
    """A round (or rounded-square) badge with the first letters of a name."""
    c = Canvas(d, d)
    if ring_col:
        c.circle(d / 2.0, d / 2.0, d / 2.0, ring_col)
        c.circle(d / 2.0, d / 2.0, d / 2.0 - rw, fill)
    elif square:
        c.rrect(0, 0, d, d, d * 0.24, fill)
    else:
        c.circle(d / 2.0, d / 2.0, d / 2.0, fill)
    m = letters_mask(text, int(d * 0.36)) if text else None
    if m:
        w, h, alpha = m
        x = int((d - w) / 2)
        y = int((d - h) / 2 + d * 0.03)
        if w <= d:
            c.mask(x, y, w, h, alpha, tcol)
    return c


def initials(name):
    """'إبراهيم الأخضر' -> 'إ أ' (the first letter of the first two words, like the mock-ups)."""
    skip = (u"الشيخ", u"القارئ", u"المقرئ", u"الشيخ:", u"د.")
    ws = [w for w in name.replace(u"-", u" ").split() if w and w not in skip]
    if not ws:
        return u"؟"
    if len(ws) == 1:
        return ws[0][:1]
    a, b = ws[0], ws[1]
    if b.startswith(u"ال") and len(b) > 2:
        b = b[2:]
    return u"%s %s" % (a[:1], b[:1])


def waveform(w, h, n, pct, on, off, seed=7):
    """Bars like the player mock-up: the played part in gold, the rest dim."""
    c = Canvas(w, h)
    gap = w / float(n)
    bw = max(2.0, gap * 0.55)
    import random
    rnd = random.Random(seed)
    for i in range(n):
        k = 0.25 + 0.75 * abs(math.sin(i * 0.55 + rnd.random() * 0.8)) * (0.6 + 0.4 * rnd.random())
        bh = max(bw, h * k)
        x = w - (i + 1) * gap + (gap - bw) / 2.0            # right to left: played bars start at the right
        col = on if (i + 0.5) / n <= pct else off
        c.rrect(x, (h - bh) / 2.0, bw, bh, bw / 2.0, col)
    return c


def bar(w, h, pct, track, fill):
    """A thin progress bar (played part from the right, like the mock-ups)."""
    c = Canvas(w, h)
    c.rrect(0, 0, w, h, h / 2.0, track)
    fw = w * max(0.0, min(1.0, pct))
    if fw >= 1:
        c.rrect(w - fw, 0, fw, h, h / 2.0, fill)
    return c


def art(d, col, inner_fill, text, tcol):
    """The geometric picture of the home screen: a circle, two squares, two diamonds and the letters."""
    c = Canvas(d, d)
    R = d / 2.0
    t = max(1.2, d / 220.0)
    c.ring(R, R, d * 0.47, t, col)
    for k in (0.33, 0.21):
        s = d * k
        c.polygon_stroke([(R - s, R - s), (R + s, R - s), (R + s, R + s), (R - s, R + s)], t, col)
        q = s * 1.42
        c.polygon_stroke([(R, R - q), (R + q, R), (R, R + q), (R - q, R)], t, col)
    c.circle(R, R, d * 0.2, col)
    c.circle(R, R, d * 0.2 - max(2, d * 0.008), inner_fill)
    m = letters_mask(text, int(d * 0.13)) if text else None
    if m:
        w, h, alpha = m
        if w <= d:
            c.mask(int((d - w) / 2), int((d - h) / 2 + d * 0.01), w, h, alpha, tcol)
    return c


def numbox(d, border, fill=None):
    """The rounded square behind a surah number (the number itself is text on top)."""
    c = Canvas(d, d)
    if fill:
        c.rrect(0, 0, d, d, d * 0.24, fill)
    c.rrect_stroke(0, 0, d, d, d * 0.24, max(1, d // 26), border)
    return c


PALETTE = ["#5bd6a0", "#f2c86b", "#8fb4ff", "#f28ca8", "#b9a2ff", "#f2b36b", "#6ec8f0"]


def palette_for(name):
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)
    return PALETTE[h % len(PALETTE)]
