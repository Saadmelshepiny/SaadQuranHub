# -*- coding: utf-8 -*-
"""Saad Quran Hub - Arabic text drawn as pictures.

The receiver's own text engine gives every haraka a width of its own, which cuts the words apart.
Here the whole job is done in Python instead: every letter gets its joined form, its harakat are
already sitting on it (one ready-made picture per letter + harakat, cut from the Amiri font - SIL
OFL - by tools/make_atlas.py), the line is put in right-to-left order and saved as a PNG.  The
receiver only shows a picture, so nothing can come apart.

Pure Python (zlib + struct), no enigma2 imports, so it can be unit-tested."""
from __future__ import print_function

import hashlib
import json
import os
import struct
import threading
import zlib

from . import extras

ATLAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qtext")
CACHE_DIR = "/tmp/sqh_text"
_ATLAS = {}
_ORDER = []
_WW = {}                                 # px -> {word: width}  (kept across atlas reloads)
WW_FILE = None                           # set by the plugin to a file on the HDD/USB (never flash)
_WW_SAVED = [None]                       # None = not read yet, else words already on disk
_SIZES = None

ZWJ, ZWNJ = 0x200D, 0x200C
SHADDA = 0x0651
# harakat drawn on the letter (others are dropped: they are rare and not in the pictures)
MARKS = set(list(range(0x064B, 0x0653)) + [0x0670, 0x0653])
MARK_ALIAS = {0x06E1: 0x0652}            # small high dotless head of khah = sukun
IGNORE = set([0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069,
              0xFEFF, ZWJ, ZWNJ])
SPACES = set([0x20, 0xA0, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2009, 0x200A, 0x202F, 0x3000])
MIRROR = {u"(": u")", u")": u"(", u"[": u"]", u"]": u"[", u"{": u"}", u"}": u"{", u"<": u">", u">": u"<",
          u"«": u"»", u"»": u"«"}
FORM_CH = "nfim"                         # isolated, final, initial, medial


def _hx(seq):
    return "".join("%04X" % c for c in seq)


def _norm_marks(seq):
    out = []
    for m in seq:
        m = MARK_ALIAS.get(m, m)
        if m in MARKS and m not in out:
            out.append(m)
    if SHADDA in out:                    # shadda first, like the font builds it
        out.remove(SHADDA)
        out.insert(0, SHADDA)
    return out[:3]


def _strong(ch):
    """'R' Arabic, 'L' left-to-right (latin letters and every digit), 'N' neutral."""
    o = ord(ch)
    if 0x0600 <= o <= 0x06FF and not (0x0660 <= o <= 0x0669) and not (0x06F0 <= o <= 0x06F9):
        return "R"
    if 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
        return "R"
    if ch.isdigit() or ch.isalpha():
        return "L"
    return "N"


def tokens(text):
    """Logical-order text -> [(kind, key, char)]   kind: 'g' glyph picture, 's' space.
    Arabic letters carry their joined form and their harakat in the key."""
    idx = [k for k, c in enumerate(text) if ord(c) not in IGNORE]
    cps = [ord(text[k]) for k in idx]
    n = len(cps)
    out = []
    tr = extras._transparent

    def prev_letter(k):
        k -= 1
        while k >= 0 and tr(cps[k]):
            k -= 1
        return cps[k] if k >= 0 else None

    def next_index(k):
        k += 1
        while k < n and tr(cps[k]):
            k += 1
        return k

    i = 0
    while i < n:
        cp = cps[i]
        if cp in SPACES:
            out.append(("s", None, u" ", idx[i]))
            i += 1
            continue
        if cp not in extras._FORMS and cp != extras._TATWEEL:
            if tr(cp):                   # a stray haraka with no letter: skip it
                i += 1
                continue
            out.append(("g", "c%04X" % cp, chr_(cp), idx[i]))
            i += 1
            continue
        p = prev_letter(i)
        jb = p is not None and extras._joins_left(p) and extras._joins_right(cp)
        j = next_index(i)
        if cp == 0x0644 and j < n and cps[j] in extras._LAM_ALEF:
            k = next_index(j)
            key = "L%04X%s%s.%s" % (cps[j], "f" if jb else "n", _hx(_norm_marks(cps[i + 1:j])),
                                    _hx(_norm_marks(cps[j + 1:k])))
            out.append(("g", key, u"ل", idx[i]))
            i = k
            continue
        nx = cps[j] if j < n else None
        ja = nx is not None and extras._joins_left(cp) and extras._joins_right(nx) and \
            (nx in extras._FORMS or nx == extras._TATWEEL)
        if cp == extras._TATWEEL:
            form = "m" if (jb and ja) else ("f" if jb else ("i" if ja else "n"))
        else:
            iso, fin, ini, med = extras._FORMS[cp]
            if jb and ja and med:
                form = "m"
            elif jb and fin:
                form = "f"
            elif ja and ini:
                form = "i"
            else:
                form = "n"
        out.append(("g", "%04X%s%s" % (cp, form, _hx(_norm_marks(cps[i + 1:j]))), chr_(cp), idx[i]))
        i = j
    return out


def chr_(cp):
    try:
        return unichr(cp)                # noqa: F821 (python 2)
    except NameError:
        return chr(cp)


def visual(toks):
    """Put the tokens in display order (left to right) for a right-to-left paragraph:
    runs of latin letters / digits keep their own order, brackets in Arabic text are mirrored."""
    kinds = [_strong(t[2]) if t[0] == "g" else "N" for t in toks]
    n = len(toks)
    res = list(kinds)
    for i in range(n):
        if kinds[i] != "N":
            continue
        a = next((kinds[k] for k in range(i - 1, -1, -1) if kinds[k] != "N"), "R")
        b = next((kinds[k] for k in range(i + 1, n) if kinds[k] != "N"), "R")
        res[i] = "L" if (a == "L" and b == "L") else "R"
    out, run = [], []
    for i in range(n - 1, -1, -1):
        if res[i] == "L":
            run.append(toks[i])
            continue
        if run:
            out.extend(reversed(run))
            run = []
        t = toks[i]
        if t[0] == "g" and t[2] in MIRROR:
            m = MIRROR[t[2]]
            t = ("g", "c%04X" % ord(m), m, t[3])
        out.append(t)
    if run:
        out.extend(reversed(run))
    return out


# ------------------------------------------------------------------ the pictures (atlas)
EXTRA_DIRS = []                    # 2.1: packs on the HDD/USB (big and 4K letter pictures)
_PATHS = {}


def add_atlas_dir(d):
    global _SIZES
    if d and d not in EXTRA_DIRS:
        EXTRA_DIRS.append(d)
        _SIZES = None


def sizes():
    global _SIZES
    if _SIZES is None:
        found = {}
        for d in [ATLAS_DIR] + EXTRA_DIRS:
            try:
                for f in os.listdir(d):
                    if f.startswith("atlas") and f.endswith(".bin") and int(f[5:-4]) not in found:
                        found[int(f[5:-4])] = os.path.join(d, f)
            except Exception:
                pass
        _PATHS.clear()
        _PATHS.update(found)
        _SIZES = sorted(found)
    return _SIZES


def available():
    return bool(sizes())


def atlas(px):
    """The nearest atlas to a font size in pixels."""
    ss = sizes()
    if not ss:
        raise IOError("no text atlas")
    fit = [s for s in ss if s <= px]
    best = fit[-1] if fit else ss[0]
    if best not in _ATLAS and not _PATHS.get(best, ATLAS_DIR).startswith(ATLAS_DIR) and not AWAKE[0]():
        own = [s for s in fit if _PATHS.get(s, "").startswith(ATLAS_DIR)]   # a pack on a sleeping disk:
        if own:                                                             # the nearest built-in size
            best = own[-1]
    a = _ATLAS.get(best)
    if a is None:
        raw = zlib.decompress(open(_PATHS.get(best) or os.path.join(ATLAS_DIR, "atlas%d.bin" % best), "rb").read())
        cut = raw.index(b"\0")
        head = json.loads(raw[:cut].decode("utf-8"))
        a = {"g": head["g"], "asc": head["asc"], "desc": head["desc"], "space": head["space"],
             "px": best, "bits": raw[cut + 1:]}
        # keep the few sizes in use (reader + legend + cinema): no reloading when switching
        while _ATLAS and (len(_ATLAS) >= 3 or sum(len(x["bits"]) for x in _ATLAS.values()) > 24000000):
            _ATLAS.pop(_ORDER.pop(0), None)
        _ATLAS[best] = a
    if best in _ORDER:
        _ORDER.remove(best)
    _ORDER.append(best)
    return a


def _lookup(a, key):
    g = a["g"]
    if key in g:
        return g[key]
    if key[0] == "L":                    # lam-alef: drop harakat on the alef, then on the lam
        base, rest = key[:6], key[6:]
        lm, am = rest.split(".")
        for k in (base + lm + ".", base + lm[:4] + ".", base + "."):
            if k in g:
                return g[k]
        return g.get("c0644")
    if key[0] != "c":
        cp, form, mk = key[:4], key[4], key[5:]
        while mk:
            mk = mk[:-4]
            if cp + form + mk in g:
                return g[cp + form + mk]
        return g.get("c" + cp)
    return g.get("c003F") if key != "c003F" else None


_JL = _JR = None


def _adv_table(a):
    """(codepoint, form) -> advance; harakat do not change the width of a letter."""
    t = a.get("adv")
    if t is None:
        t = {}
        for k, e in a["g"].items():
            if k[0] == "c":
                t[("c", int(k[1:5], 16))] = e[0]
            elif k[0] == "L":
                if k[6:] == ".":
                    t[(0x0644, int(k[1:5], 16), k[5])] = e[0]
            elif len(k) == 5:
                t[(int(k[:4], 16), k[4])] = e[0]
        a["adv"] = t
    return t


def word_width(word, px):
    """Width of one word in pixels - fast and remembered (pagination measures every word)."""
    global _JL, _JR
    a = atlas(px)
    tab = _adv_table(a)
    if _WW_SAVED[0] is None and WW_FILE is None:
        _WW_SAVED[0] = 0                 # no disk: nothing to read (with one, the disk thread reads it)
    memo = _WW.get(a["px"])
    if memo is None:
        memo = _WW[a["px"]] = {}
    w = memo.get(word)
    if w is not None:
        return w
    if _JL is None:
        _JL = set(c for c, f in extras._FORMS.items() if f[2] is not None) | set([extras._TATWEEL])
        _JR = set(c for c, f in extras._FORMS.items() if f[1] is not None) | set([extras._TATWEEL])
    tr = extras._transparent
    cps = [ord(c) for c in word if ord(c) not in IGNORE and not tr(ord(c))]
    forms = extras._FORMS
    lam_alef = extras._LAM_ALEF
    w, i, n, prev = 0, 0, len(cps), None
    while i < n:
        cp = cps[i]
        if cp not in forms and cp != extras._TATWEEL:
            w += tab.get(("c", cp), 0) if cp not in SPACES else a["space"]
            prev = None
            i += 1
            continue
        jb = prev is not None and prev in _JL and cp in _JR
        if cp == 0x0644 and i + 1 < n and cps[i + 1] in lam_alef:
            w += tab.get((0x0644, cps[i + 1], "f" if jb else "n"), 0)
            prev = cps[i + 1]
            i += 2
            continue
        nx = cps[i + 1] if i + 1 < n else None
        ja = nx is not None and cp in _JL and nx in _JR
        if jb and ja:
            f = "m"
        elif jb:
            f = "f"
        elif ja:
            f = "i"
        else:
            f = "n"
        adv = tab.get((cp, f))
        if adv is None:
            adv = tab.get((cp, "f" if jb else "n"), tab.get((cp, "n"), 0))
        w += adv
        prev = cp
        i += 1
    if len(memo) > 60000:
        memo.clear()
    memo[word] = w
    return w


def line_width(text, px):
    a = atlas(px)
    words = text.split()
    return sum(word_width(x, px) for x in words) + a["space"] * max(0, len(words) - 1)


def wrap(text, px, width):
    """Word-wrap one paragraph to a pixel width (measured with the real letter widths)."""
    words = text.split()
    if not words:
        return [u""]
    a = atlas(px)
    sp = a["space"]
    out, cur, cw = [], [], 0
    for w in words:
        ww = word_width(w, px)
        if cur and cw + sp + ww > width:
            out.append(u" ".join(cur))
            cur, cw = [w], ww
        else:
            cw = cw + (sp if cur else 0) + ww
            cur.append(w)
    if cur:
        out.append(u" ".join(cur))
    return out


def _load_widths():
    """Word widths measured before the last reboot (saved on the HDD/USB)."""
    if _WW_SAVED[0] is not None or not WW_FILE:
        return
    _WW_SAVED[0] = 0
    try:
        import marshal
        with open(WW_FILE, "rb") as f:
            saved = marshal.load(f)
        for px_, d in saved.items():
            _WW.setdefault(px_, {}).update(d)
        _WW_SAVED[0] = sum(len(d) for d in _WW.values())
    except Exception:
        pass


def save_widths(force=False):
    """Write the measured widths when enough new words were met (on the disk thread when there is one)."""
    if not WW_FILE:
        return False
    n = sum(len(d) for d in _WW.values())
    if not force and n - (_WW_SAVED[0] or 0) < 2000:
        return False
    small = dict((px_, dict(list(m.items())[-40000:])) for px_, m in _WW.items())
    _WW_SAVED[0] = n
    path = WW_FILE

    def write():
        import marshal
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path + ".tmp", "wb") as f:
            marshal.dump(small, f)
        os.rename(path + ".tmp", path)
    if BG[0] is not None:
        BG[0](write)
        return True
    try:
        write()
        return True
    except Exception:
        return False


def word_spans(text, px):
    """[(offset from the right edge, width)] of every word of a line, in reading order."""
    a = atlas(px)
    out, x = [], 0
    for w in text.split():
        ww = word_width(w, px)
        out.append((x, ww))
        x += ww + a["space"]
    return out


def compose(text, px, height=None, colors=None, justify=None):
    """-> (width, height, alpha bytearray, colour-index bytearray or None, palette) of one line.
    colors: {char index in text: 0xRRGGBB} - tajweed colouring of single letters."""
    a = atlas(px)
    asc, desc = a["asc"], a["desc"]
    h = height or (asc + desc)
    base = int(h * 0.64) if height else asc
    vis = visual(tokens(text))
    placed, x = [], 0
    pal = [None]
    gaps = [0] * sum(1 for v in vis if v[0] == "s")
    if justify and gaps:                 # spread the line to the full width, like the printed mushaf
        extra = justify - line_width(text, px)
        if 0 < extra < justify * 0.25:
            q, r = divmod(int(extra), len(gaps))
            gaps = [q + (1 if i < r else 0) for i in range(len(gaps))]
    si = 0
    for kind, key, _c, ci in vis:
        if kind == "s":
            x += a["space"] + gaps[si]
            si += 1
            continue
        e = _lookup(a, key)
        if not e:
            continue
        col = colors.get(ci) if colors else None
        k = 0
        if col is not None:
            if col not in pal:
                pal.append(col)
            k = pal.index(col)
        placed.append((x, e, k))
        x += e[0]
    left = min([0] + [px_ + e[1] for px_, e, _k in placed])
    right = max([x] + [px_ + e[1] + e[3] for px_, e, _k in placed])
    w = max(1, right - left)
    buf = bytearray(w * h)
    cbuf = bytearray(w * h) if len(pal) > 1 else None
    bits = a["bits"]
    for px_, e, k in placed:
        _adv, gx, gy, gw, gh, off = e
        if not gw or not gh:
            continue
        x0 = px_ + gx - left
        y0 = base + gy
        for r in range(gh):
            y = y0 + r
            if y < 0 or y >= h:
                continue
            src = bits[off + r * gw: off + (r + 1) * gw]
            d0 = y * w + x0
            dst = buf[d0:d0 + gw]
            s = dst.rstrip(b"\0")
            if not s:
                buf[d0:d0 + gw] = src
            else:                        # letters touching: keep the darker pixel where they meet
                e_ = len(s)
                b_ = gw - len(dst.lstrip(b"\0"))
                buf[d0:d0 + gw] = src
                buf[d0 + b_:d0 + e_] = bytearray(map(max, dst[b_:e_], src[b_:e_]))
            if k:
                cbuf[d0:d0 + gw] = bytes(src).translate(_MASK[k])
    return w, h, buf, cbuf, pal


_MASK = dict((k, bytes(bytearray([k if v > 40 else 0 for v in range(256)]))) for k in range(1, 16))


def png_bytes(w, h, alpha, color, cbuf=None, pal=None):
    n = w * h
    rgba = bytearray(n * 4)
    if cbuf is None:
        r, g, b = (color >> 16) & 255, (color >> 8) & 255, color & 255
        rgba[0::4] = bytes(bytearray([r])) * n
        rgba[1::4] = bytes(bytearray([g])) * n
        rgba[2::4] = bytes(bytearray([b])) * n
    else:
        cols = [color] + list(pal[1:])
        for sh, ch in ((16, 0), (8, 1), (0, 2)):
            tab = bytearray(256)
            for k, c in enumerate(cols):
                tab[k] = (c >> sh) & 255
            rgba[ch::4] = bytes(cbuf).translate(bytes(tab))
    rgba[3::4] = bytes(alpha)
    stride = w * 4
    raw = b"".join(b"\0" + bytes(rgba[y * stride:(y + 1) * stride]) for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


DISK_DIR = [None]                        # second, big tier on the HDD/USB (kept across restarts)
AWAKE = [lambda: False]                  # set by the plugin: is the disk spinning right now?
BG = [None]                              # set by the plugin: run a job on the disk thread
RAM_KEEP = 400                           # /tmp keeps only the lines in use (a few MB)


def render(text, px, color=0xffffff, height=None, colors=None, justify=None):
    """-> (png path, width, height).  Two tiers: the lines in use in /tmp (instant, never waits for the
    disk), every line ever drawn on the HDD/USB, read only while the disk is spinning anyway."""
    ck = u",".join(u"%d:%x" % kv for kv in sorted(colors.items())) if colors else u""
    key = hashlib.md5((u"%s|%d|%x|%s|%s|%s" % (text, px, color, height, ck, justify)).encode("utf-8")).hexdigest()
    name = key + ".png"
    path = os.path.join(CACHE_DIR, name)
    meta = _META.get(path)
    if meta and os.path.exists(path):
        return path, meta[0], meta[1]
    dd = DISK_DIR[0]
    if dd and AWAKE[0]():                # drawn in an earlier session: take it from the disk
        dp = os.path.join(dd, name)
        try:
            with open(dp, "rb") as f:
                hd = f.read(24)
            if hd[12:16] == b"IHDR":
                w, h = struct.unpack(">II", hd[16:24])
                return dp, w, h
        except Exception:
            pass
    with _DRAW:                          # the GUI and the painter thread never draw at the same time
        meta = _META.get(path)
        if meta and os.path.exists(path):
            return path, meta[0], meta[1]
        return _draw(text, px, color, height, colors, justify, name, path, dd)


_DRAW = threading.RLock()


def is_ready(text, px, color=0xffffff, height=None, colors=None, justify=None):
    """Is this line already drawn in /tmp (then render() is instant)?"""
    ck = u",".join(u"%d:%x" % kv for kv in sorted(colors.items())) if colors else u""
    key = hashlib.md5((u"%s|%d|%x|%s|%s|%s" % (text, px, color, height, ck, justify)).encode("utf-8")).hexdigest()
    path = os.path.join(CACHE_DIR, key + ".png")
    return path in _META and os.path.exists(path)


def _draw(text, px, color, height, colors, justify, name, path, dd):
    w, h, alpha, cbuf, pal = compose(text, px, height, colors, justify)
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    raw = png_bytes(w, h, alpha, color, cbuf, pal)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.rename(tmp, path)
    _META[path] = (w, h)
    if dd and BG[0] is not None:
        BG[0](lambda: _to_disk(dd, name, raw))
    _trim_cache()
    return path, w, h


def _to_disk(dd, name, raw):
    """(disk thread) keep a copy of a drawn line on the HDD/USB."""
    dp = os.path.join(dd, name)
    if os.path.exists(dp):
        return
    with open(dp + ".tmp", "wb") as f:
        f.write(raw)
    os.rename(dp + ".tmp", dp)
    _COUNT[0] += 1
    if _COUNT[0] % 500 == 0:
        _trim_disk(dd, KEEP[0])


_META = {}
_COUNT = [0]
KEEP = [6000]


def _trim_disk(d, keep):
    try:
        fs = os.listdir(d)
        if len(fs) > keep + 500:
            fs = sorted((os.path.getmtime(os.path.join(d, f)), f) for f in fs)
            for _t, f in fs[:-keep]:
                os.remove(os.path.join(d, f))
    except Exception:
        pass


def set_cache(d, keep=6000, ram="/tmp/sqh_text"):
    """The HDD/USB keeps every drawn line; /tmp keeps the few hundred in use."""
    global CACHE_DIR
    CACHE_DIR = ram
    DISK_DIR[0] = d
    KEEP[0] = keep
    if BG[0] is not None:
        BG[0](lambda: _trim_disk(d, keep))


def _trim_cache(keep=None):
    keep = keep or RAM_KEEP
    if len(_META) < keep + 100:
        return
    try:
        fs = sorted((os.path.getmtime(os.path.join(CACHE_DIR, f)), f) for f in os.listdir(CACHE_DIR))
        for _t, f in fs[:-keep]:
            p_ = os.path.join(CACHE_DIR, f)
            os.remove(p_)
            _META.pop(p_, None)
    except Exception:
        pass
