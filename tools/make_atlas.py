# -*- coding: utf-8 -*-
"""Cuts the letter pictures used by qtext.py out of Amiri (SIL OFL 1.1).

Every Arabic letter is drawn in each joined form it can take, with every haraka combination that
appears in the bundled Quran / tafsir text (plus the common ones), by HarfBuzz (Pillow + raqm), so
the harakat sit exactly where the font designer put them.  Output: qtext/atlas<px>.bin =
zlib( json header + NUL + 8-bit alpha pixels )."""
import glob
import gzip
import importlib.util
import json
import os
import sys
import types
import zlib

from PIL import Image, ImageDraw, ImageFont, features

assert features.check("raqm"), "Pillow needs libraqm"
PLUG = "/home/claude/quranhub/usr/lib/enigma2/python/Plugins/Extensions/SaadQuranHub/"
FONT = "/tmp/claude-0/fonts/az/Amiri-1.000/Amiri-Regular.ttf"
OUT = PLUG + "qtext/"
SIZES = [int(x) for x in (sys.argv[1:] or "30 36 44 52 62 74 88".split())]

# import the plugin's own extras + qtext (so the keys are exactly the ones the receiver asks for)
pkg = types.ModuleType("sqh")
pkg.__path__ = [PLUG]
sys.modules["sqh"] = pkg
for name in ("data", "extras", "qtext"):
    spec = importlib.util.spec_from_file_location("sqh." + name, PLUG + name + ".py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["sqh." + name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as e:
        if name != "data":
            raise
        print("data import:", e)
qtext = sys.modules["sqh.qtext"]
extras = sys.modules["sqh.extras"]

# ---------------------------------------------------------------- inventory of keys
keys = set()
corpus = []
q = json.load(gzip.open(PLUG + "qdata/quran.json.gz"))
for v in q.values():
    corpus.extend(v)
for f in glob.glob(PLUG + "qdata/taf_*/*.json.gz"):
    corpus.append(gzip.open(f).read().decode("utf-8"))
for f in glob.glob(PLUG + "qdata/*.json.gz"):
    corpus.append(gzip.open(f).read().decode("utf-8"))
for t in corpus:
    for kind, key, _c, _i in qtext.tokens(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)):
        if kind == "g":
            keys.add(key)
print("keys from the text:", len(keys))

F, D, K, S = 0x064E, 0x064F, 0x0650, 0x0652
COMBOS = [[], [F], [D], [K], [S], [0x064B], [0x064C], [0x064D], [0x0651], [0x0670], [0x0653],
          [0x0651, F], [0x0651, D], [0x0651, K], [0x0651, 0x064B], [0x0651, 0x064C], [0x0651, 0x064D],
          [0x0651, 0x0670], [F, 0x0670]]
for cp, fm in extras._FORMS.items():
    if cp > 0x06FF:
        continue
    for i, form in enumerate("nfim"):
        if fm[i] is None:
            continue
        for c in COMBOS:
            keys.add("%04X%s%s" % (cp, form, qtext._hx(c)))
for form in "nfim":
    keys.add("0640" + form)
for al in extras._LAM_ALEF:
    for form in "nf":
        for c in COMBOS:
            for am in ([], [0x064B], [S]):
                keys.add("L%04X%s%s.%s" % (al, form, qtext._hx(c), qtext._hx(am)))
singles = list(range(0x21, 0x7F)) + list(range(0xA1, 0x100)) + [0x060C, 0x061B, 0x061F, 0x066A, 0x066B,
          0x066C, 0x06D4, 0x06DD, 0x06DE, 0x06E9, 0xFD3E, 0xFD3F, 0xFDFA, 0xFDFB, 0xFDF2, 0x2013, 0x2014,
          0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026, 0x25CF, 0x2605, 0x2606, 0x25B6, 0x25C0] + \
    list(range(0x0660, 0x066A)) + list(range(0x06F0, 0x06FA)) + list(range(0x0621, 0x064B)) + [0x0671]
for cp in singles:
    keys.add("c%04X" % cp)
print("keys total:", len(keys))


def key_text(key):
    z = u"‍"
    if key[0] == "c":
        return chr(int(key[1:5], 16))
    if key[0] == "L":
        al, form = int(key[1:5], 16), key[5]
        lm, am = key[6:].split(".")
        m = lambda h: u"".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
        return (z if form == "f" else u"") + u"ل" + m(lm) + chr(al) + m(am)
    cp, form, mk = int(key[:4], 16), key[4], key[5:]
    marks = u"".join(chr(int(mk[i:i + 4], 16)) for i in range(0, len(mk), 4))
    return (z if form in "fm" else u"") + chr(cp) + marks + (z if form in "im" else u"")


def build(px):
    font = ImageFont.truetype(FONT, px, layout_engine=ImageFont.Layout.RAQM)
    m = px * 2
    asc_ink, desc_ink = 0, 0
    entries, blob = {}, bytearray()
    for key in sorted(keys):
        s = key_text(key)
        direction = "ltr" if (key[0] == "c" and qtext._strong(s) != "R") else "rtl"
        adv = int(round(font.getlength(s, direction=direction)))
        W, H = adv + 2 * m, px * 4
        base = px * 2
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((m, base), s, font=font, fill=255, anchor="ls", direction=direction)
        bb = im.getbbox()
        if not bb:
            entries[key] = [adv, 0, 0, 0, 0, len(blob)]
            continue
        crop = im.crop(bb)
        gx, gy = bb[0] - m, bb[1] - base
        entries[key] = [adv, gx, gy, crop.width, crop.height, len(blob)]
        blob += crop.tobytes()
        if key[0] != "c" or 0x0600 <= ord(s) <= 0x06FF:
            asc_ink = max(asc_ink, -gy)
            desc_ink = max(desc_ink, gy + crop.height)
    space = int(round(font.getlength(u" ")))
    head = {"px": px, "asc": int(asc_ink), "desc": int(desc_ink), "space": space, "g": entries,
            "font": "Amiri 1.000 (SIL OFL 1.1)"}
    data = json.dumps(head, separators=(",", ":")).encode("utf-8") + b"\0" + bytes(blob)
    os.makedirs(OUT, exist_ok=True)
    with open(OUT + "atlas%d.bin" % px, "wb") as f:
        f.write(zlib.compress(data, 9))
    print(px, "glyphs", len(entries), "asc", asc_ink, "desc", desc_ink, "bytes",
          os.path.getsize(OUT + "atlas%d.bin" % px))


for px in SIZES:
    build(px)
