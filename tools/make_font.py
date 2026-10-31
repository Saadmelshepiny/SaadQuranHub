# Builds the two reading fonts shipped with the plugin from Amiri (SIL OFL 1.1, renamed as the
# licence requires):  A = harakat drawn over the glyph on their LEFT (renderers that put a mark
# after its letter), B = Amiri's own placement (renderers that put a mark before its letter).
import sys
from fontTools.ttLib import TTFont
from fontTools import subset
SRC = "/tmp/claude-0/fonts/az/Amiri-1.000/Amiri-Regular.ttf"
OUT = "/home/claude/quranhub/usr/lib/enigma2/python/Plugins/Extensions/SaadQuranHub/fonts/"
UNI = list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + list(range(0x600, 0x700)) + \
    list(range(0x2000, 0x2070)) + list(range(0xFB50, 0xFE00)) + list(range(0xFE70, 0xFEFF)) + [0x25CC]


def is_mark(cp):
    return (0x0610 <= cp <= 0x061A or 0x064B <= cp <= 0x065F or cp == 0x0670 or 0x06D6 <= cp <= 0x06ED)


def build(variant):
    opts = subset.Options()
    opts.layout_features = []
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.hinting = False
    opts.drop_tables += ["GSUB", "GPOS", "GDEF", "JSTF", "MATH"]
    f = TTFont(SRC)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=UNI)
    sub.subset(f)
    cmap = f.getBestCmap()
    glyf, hmtx = f["glyf"], f["hmtx"]
    if variant == "A":
        done = set()
        for cp, gname in cmap.items():
            if not is_mark(cp) or gname in done:
                continue
            done.add(gname)
            g = glyf[gname]
            if g.numberOfContours == 0:
                continue
            g.recalcBounds(glyf)
            center = (g.xMin + g.xMax) / 2.0
            dx = int(round(-230 - center))
            if g.isComposite():
                for c in g.components:
                    c.x += dx
            else:
                g.coordinates.translate((dx, 0))
            g.recalcBounds(glyf)
            adv, _lsb = hmtx[gname]
            hmtx[gname] = (0, g.xMin)
    fam = "SaadQuran " + variant
    for rec in f["name"].names:
        if rec.nameID in (1, 4, 16, 18, 21):
            rec.string = fam
        elif rec.nameID == 6:
            rec.string = "SaadQuran-" + variant
        elif rec.nameID == 3:
            rec.string = "SaadQuran-%s-1.0" % variant
    f.save(OUT + "SaadQuran%s.ttf" % variant)


import os
os.makedirs(OUT, exist_ok=True)
build("A")
build("B")
import shutil
shutil.copy("/tmp/claude-0/fonts/az/Amiri-1.000/OFL.txt" if os.path.exists("/tmp/claude-0/fonts/az/Amiri-1.000/OFL.txt") else
            "/tmp/claude-0/fonts/amiri/OFL.txt", OUT + "OFL.txt")
print(sorted((n, os.path.getsize(OUT + n)) for n in os.listdir(OUT)))
