# -*- coding: utf-8 -*-
"""Saad Quran Hub 1.0 - Quran reciters and radios for Enigma2 (OpenBlackHole).

Sources: mp3quran.net, quran.com, surahquran.com

Layout (right to left):   [ sections ] -> [ reciters / radios ] -> [ surahs ]
All attributes of the screen are prefixed with "qh" so they can never clash
with attributes that enigma2's Screen class already owns (e.g. `shown`).

Playback, the playlist, recording and the sleep timer live in the module-level
`BG` object, so closing/minimising the screen does not interrupt them.
"""
from __future__ import print_function

import json
import math
import os
import re
import threading
import time

try:
    import queue
except ImportError:  # python2
    import Queue as queue

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
try:
    from Components.MultiContent import MultiContentEntryPixmapAlphaBlend as _PixEntry
except ImportError:                                  # older images
    from Components.MultiContent import MultiContentEntryPixmapAlphaTest as _PixEntry
from Components.ProgressBar import ProgressBar
from Components.Pixmap import Pixmap
from enigma import (eTimer, eServiceReference, iPlayableService, getDesktop, eSize, ePoint,
                    eListboxPythonMultiContent, gFont,
                    RT_HALIGN_RIGHT, RT_HALIGN_CENTER, RT_VALIGN_CENTER)

try:
    from skin import parseColor
except Exception:  # pragma: no cover
    parseColor = None

from . import data
from . import timeshift
from . import extras
from . import remote
from . import diag
from . import studio
from . import qtext
from . import tajweed
from . import library
from . import tgbot
from . import localserve
from . import i18n
from . import hddcache
from . import dlna
from . import safeupdate

PLUGIN_VERSION = "1.3"
GITHUB_REPO = "Saadmelshepiny/SaadQuranHub"
GITHUB_INFO = "https://raw.githubusercontent.com/%s/main/version.json" % GITHUB_REPO


def vtuple(v):
    try:
        return [int(x) for x in str(v).strip().split(".")]
    except ValueError:
        return [0]


def private_edition():
    """The owner's own package carries bot.conf; the public one (GitHub) does not."""
    try:
        return bool(tgbot.default_token())
    except Exception:
        return False

PLUGIN_NAME = u"Saad Quran Hub"
SERVICE_TYPE = 4097  # GStreamer/ServiceMP3. Use 5002 for exteplayer3 images.

# (key, label, items header, has_subs)   has_subs None = decided per entry
SECTIONS = [
    ("fav", u"المفضلة", u"المفضلة", None),
    ("mp3q_reciters", u"مكتبة القراء الشاملة", u"القراء", True),
    ("mp3q_radios", u"إذاعات القرآن المباشرة", u"الإذاعات", False),
    ("qcom", u"تلاوات عالية الجودة", u"القراء", True),
    ("sq_reciters", u"قراء المصحف المرتّل", u"القراء", True),
    ("sq_radios", u"إذاعات القرآن العربية", u"الإذاعات", False),
    ("islam", u"صوتيات إسلام ويب", u"القراء", True),
    ("way_reciters", u"القراء بالروايات", u"القراء", True),
    ("way_iconic", u"تلاوات نادرة وأيقونية", u"المقاطع", False),
    ("pls", u"قوائمي", u"القوائم", True),
    ("hist", u"سجل الاستماع", u"السجل", False),
    ("most", u"الأكثر استماعاً", u"الأكثر", False),
    ("local", u"المحفوظات (HDD)", u"الملفات", False),
    ("srch", u"نتائج البحث", u"النتائج", None),
    ("qpedia", u"موسوعة المصاحف", u"المصاحف", True),
    ("tvq", u"مصاحف تلفزيون القرآن", u"القراء", True),
    ("assabile", u"قراء موقع السبيل", u"القراء", True),
    ("ourq", u"شيوخ موقع قرآننا", u"الشيوخ", True),
    ("sync", u"تلاوات بتزامن الآيات", u"القراء", True),
    ("acache", u"متاح بدون إنترنت (ما سمعته)", u"الملفات", False),
]
# the right column, organised in titled groups (CH+ / CH- jump from group to group)
GROUPS = [
    (u"المفضلة", ("fav",)),
    (u"القراء والمصاحف", ("mp3q_reciters", "sync", "qpedia", "tvq", "qcom", "sq_reciters", "way_reciters", "assabile",
                          "islam", "ourq")),
    (u"الإذاعات المباشرة", ("mp3q_radios", "sq_radios")),
    (u"تلاوات نادرة وتليجرام", ("way_iconic", "@tg")),
    (u"مكتبات القرص", ("@acache", "@dsk")),
]
# icon (icons/<size>/<name>.png) shown next to every source; Telegram channels use their own picture
SECTION_ICON = {"fav": "fav", "mp3q_reciters": "library", "mp3q_radios": "radio", "qcom": "hq",
                "sq_reciters": "mushaf", "sq_radios": "radio", "islam": "islamweb", "way_reciters": "riwayat",
                "way_iconic": "gem", "pls": "lists", "hist": "history", "most": "most", "local": "disk",
                "srch": "search", "acache": "disk", "qpedia": "pedia", "tvq": "tv", "assabile": "waves", "ourq": "mic2", "sync": "sync"}
ICON_PX = 54 if getDesktop(0).size().width() > 1500 else 36
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", str(ICON_PX))
_ICON_CACHE = {}
TG_PIX = {}               # channel -> decoded channel picture (ePixmap)


def icon_pixmap(name):
    if name in _ICON_CACHE:
        return _ICON_CACHE[name]
    pix = None
    try:
        from Tools.LoadPixmap import LoadPixmap
        pth = os.path.join(ICON_DIR, name + ".png")
        if os.path.exists(pth):
            pix = LoadPixmap(pth)
    except Exception as e:
        qlog("icon %s: %s" % (name, e))
    _ICON_CACHE[name] = pix
    return pix


def load_scaled(path, w, h):
    """Decode a jpg/png into a pixmap of w x h (keeps the aspect ratio)."""
    try:
        from enigma import ePicLoad
        pl = ePicLoad()
        pl.setPara((w, h, 1, 1, False, 1, "#00000000"))
        if pl.startDecode(path, 0, 0, False) == 0:
            return pl.getData()
    except Exception as e:
        qlog("picload %s: %s" % (path, e))
    return None


def section_pixmap(key):
    if key.startswith("tg:"):
        return TG_PIX.get(key[3:].lower()) or icon_pixmap("telegram")
    return icon_pixmap(SECTION_ICON.get(key, "library"))


def tg_channels(cfg):
    """[(user, arabic name)] - the default channels plus the ones added from the menu."""
    out, seen = [], set()
    removed = set(x.lower() for x in cfg.get("tg_removed", []))
    for u, n in list(data.TG_DEFAULT) + [tuple(x) for x in cfg.get("tg_channels", [])]:
        if u.lower() in seen or u.lower() in removed:
            continue
        seen.add(u.lower())
        out.append((u, n))
    return out


def sync_tg_sections(cfg):
    """Append a section for every Telegram channel (indexes of the existing sections never change)."""
    have = set(s[0] for s in SECTIONS)
    for u, n in tg_channels(cfg):
        key = "tg:" + u
        if key not in have:
            SECTIONS.append((key, n, u"المقاطع - تليجرام", False))
            have.add(key)
    for d in cfg.get("disk_srcs", []):
        key = "dsk:" + d["path"]
        if key not in have:
            SECTIONS.append((key, d["name"], u"القراء", True))     # reciters -> their surahs (3 columns)
            have.add(key)


# sections rebuilt every time they are opened (their content changes while you use the plugin)
VOLATILE = ("fav", "pls", "hist", "most", "local", "srch")      # + every "tg:" channel (new posts)
SEC_CACHE = {}        # loaded section lists, shared by every opening of the screen (instant re-open)
SUBS_CACHE = {}       # surah lists of network reciters (surahquran / islamweb / way2quran)

PLAY_OK_EVENTS = tuple(
    getattr(iPlayableService, n) for n in ("evUpdatedInfo", "evGstreamerPlayStarted")
    if hasattr(iPlayableService, n))


SLEEP_STEPS = [0, 15, 30, 60, 90, 120]

# TV picture presets: (label, x, y, w, h) as fractions of the screen
TV_SIZES = [(u"كامل", 0.0, 0.0, 1.0, 1.0), (u"كبير", 0.1, 0.1, 0.8, 0.8),
            (u"متوسط", 0.55, 0.05, 0.4, 0.4), (u"صغير", 0.7, 0.05, 0.27, 0.27)]

LOG_PATH = "/tmp/quranhub.log"          # without a disk; with one: <disk>/QuranHub/logs/quranhub.log
_LOG = ["", 0.0]


def log_path():
    now = time.time()
    if now - _LOG[1] > 60:
        _LOG[1] = now
        try:
            d = data.home_dir("logs")
        except Exception:
            d = None
        p = os.path.join(d, "quranhub.log") if d else "/tmp/quranhub.log"
        if p != _LOG[0]:
            _LOG[0] = p
            if d:                        # the old place still works (a link, no RAM used)
                try:
                    if os.path.islink("/tmp/quranhub.log") or os.path.exists("/tmp/quranhub.log"):
                        os.remove("/tmp/quranhub.log")
                    os.symlink(p, "/tmp/quranhub.log")
                except Exception:
                    pass
    return _LOG[0]


def qlog(msg):
    """Tiny event log (/tmp/quranhub.log) to understand 'sometimes it works'."""
    try:
        import os
        lp = log_path()
        if os.path.exists(lp) and os.path.getsize(lp) > (400000 if lp != LOG_PATH else 100000):
            try:
                os.rename(lp, lp + ".1")          # keep the previous log too (on the disk)
            except Exception:
                os.remove(lp)
        with open(lp, "ab") as f:
            f.write((u"%s %s\n" % (time.strftime("%H:%M:%S"), msg)).encode("utf-8"))
    except Exception:
        pass
    try:
        note_error(u"%s" % (msg,))
    except Exception:
        pass
    try:                                         # 2.0: inside an except block -> the full traceback
        import sys as _sys
        if _sys.exc_info()[0] is not None and data.home_dir():
            import traceback
            ep = os.path.join(data.home_dir("logs"), "errors.log")
            if os.path.exists(ep) and os.path.getsize(ep) > 300000:
                os.rename(ep, ep + ".1")
            with open(ep, "ab") as f:
                f.write((u"==== %s %s (%s)\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg, PLUGIN_VERSION)).encode("utf-8"))
                f.write(traceback.format_exc().encode("utf-8", "ignore"))
    except Exception:
        pass



NAMES = ["qh_sec", "qh_items", "qh_subs"]
HDRS = ["qh_h0", "qh_h1", "qh_h2"]


# ------------------------------------------------------------------ themes
# layout 0 = classic (opaque, the familiar look)
#        1 = glass side panel on the right (TV visible on the left)
#        2 = full-screen glass (translucent panels over the TV)
#        3 = bottom band (TV visible on top, lists in the lower half)
def _T(name, bg, bar, line, panel, head, sel, text, dim, btn2, gold, grey, btntxt="#eceff3", layout=0,
       accent=False):
    return {"name": name, "bg": bg, "bar": bar, "line": line, "panel": panel, "head": head,
            "sel": sel, "text": text, "dim": dim, "btn2": btn2, "gold": gold, "grey": grey,
            "btntxt": btntxt, "layout": layout, "accent": accent}


THEMES = [
    _T(u"زمردي ليلي", "#0e1116", "#0f5132", "#e0b95a", "#151b23", "#1f2933", "#1b7a4b",
       "#d7dde5", "#9aa5b1", "#2b3440", 0xffd166, 0x8b95a1),
    _T(u"دافئ (للعين)", "#15110e", "#4a3320", "#d9a441", "#1d1813", "#2c2319", "#8a5a1f",
       "#e6dccb", "#a89a84", "#3a2f23", 0xe8b85c, 0x9c8f7a),
    _T(u"أزرق هادئ", "#0d1520", "#16324f", "#7fb4e8", "#121e2c", "#1b2b3d", "#2b6a9e",
       "#d3dde8", "#93a4b8", "#243447", 0x9cc6f0, 0x8393a6),
    _T(u"بنفسجي ليلي", "#120f1a", "#3b2a63", "#b99cf0", "#1a1625", "#271f38", "#6a4bb0",
       "#ddd6ec", "#a198b8", "#2f2744", 0xcbb4f5, 0x978fab),
    _T(u"رمادي فحمي", "#121314", "#2c3136", "#c3c9cf", "#1a1c1e", "#25282b", "#4a5560",
       "#d4d7da", "#9a9fa4", "#2d3033", 0xd9dde1, 0x8b9096),
    _T(u"غابة هادئة", "#0f1511", "#24472f", "#a9c97b", "#161e18", "#212d24", "#3b7a4a",
       "#d5e0d2", "#9fb0a0", "#2a362c", 0xc2d98f, 0x8da08e),
    _T(u"فاتح رملي (نهاري)", "#efe8d8", "#2f6f4f", "#c9a24d", "#faf5e8", "#e2d8bf", "#2f7d57",
       "#2b2b26", "#5b5a52", "#cdbf9f", 0x8a6410, 0x6b6a60, btntxt="#23211a"),
    _T(u"أسود عميق (OLED)", "#050608", "#0b3a26", "#c9a24d", "#0a0c0f", "#14181d", "#17603b",
       "#cfd5dc", "#8a929b", "#1a1f26", 0xe0b95a, 0x7d8690),
    # ---- translucent / distinctive layouts
    _T(u"لوحة جانبية زمردية (شفافة)", "transparent", "#c0103a2a", "#3ad08f", "#a0101820", "#d0143a2a", "#c01b7a4b",
       "#e4ece8", "#a9b8b0", "#c0123026", 0x7ee0b0, 0x93a69c, layout=1),
    _T(u"لوحة جانبية زرقاء (شفافة)", "transparent", "#c0102a44", "#6fb4f0", "#a00c1622", "#d0163352", "#c02b6a9e",
       "#e1ebf5", "#a0b3c6", "#c0152638", 0xa8d2f7, 0x8497ab, layout=1),
    _T(u"لوحة جانبية ذهبية (شفافة)", "transparent", "#c03a2c12", "#e0b95a", "#a0181208", "#d03a2c12", "#c08a5a1f",
       "#efe6d3", "#b7a98e", "#c02a2010", 0xf0cd7a, 0xa09580, layout=1),
    _T(u"زجاج أسود (شفاف كامل)", "transparent", "#b0000000", "#d9b45a", "#90000000", "#c0101418", "#c01b7a4b",
       "#f0f0f0", "#b5bcc4", "#b0000000", 0xffd166, 0x9aa3ad, layout=2),
    _T(u"زجاج أزرق ليلي", "transparent", "#b0081a30", "#74b4ee", "#90081420", "#c0102840", "#c02b6a9e",
       "#e8f0f8", "#a9bad0", "#b0081a30", 0xa8d2f7, 0x8ea0b6, layout=2),
    _T(u"شريط سفلي زمردي", "transparent", "#b00f5132", "#e0b95a", "#b0101820", "#d01f3d33", "#d01b7a4b",
       "#e2ece7", "#a9b8b0", "#b01a2a26", 0xffd166, 0x90a398, layout=3),
    _T(u"شريط سفلي بنفسجي", "transparent", "#b02a1c4c", "#c8b0f5", "#b0140f22", "#d0271f38", "#d06a4bb0",
       "#ece6f7", "#b0a6c8", "#b01c1530", 0xd9c6fa, 0x9f97b3, layout=3),
    _T(u"ضباب فاتح (لوحة جانبية)", "transparent", "#c8e9efe9", "#1f7a50", "#c0f5f8f3", "#d0dfe9df", "#d02f7d57",
       "#1d2b24", "#4f6158", "#c0cfdccf", 0x7a5a0c, 0x55665c, btntxt="#16231c", layout=1),
    # ---- modern additions
    _T(u"لوحة يسارية زمردية", "transparent", "#c0103a2a", "#3ad08f", "#a0101820", "#d0143a2a", "#c01b7a4b",
       "#e4ece8", "#a9b8b0", "#c0123026", 0x7ee0b0, 0x93a69c, layout=4),
    _T(u"لوحة يسارية عنبرية", "transparent", "#c03a2412", "#f0a24a", "#a0180f08", "#d03a2412", "#c0a8581c",
       "#f1e5d3", "#bba98f", "#c02a1c0e", 0xf5c37a, 0xa39683, layout=4),
    _T(u"نافذة مركزية زجاجية", "transparent", "#b8101820", "#74c0e8", "#90081018", "#d0182838", "#c02b6a9e",
       "#eaf2f8", "#a9bccd", "#b8101c28", 0xa8d2f7, 0x8ea0b3, layout=5),
    _T(u"نافذة مركزية ذهبية", "transparent", "#b8181208", "#e0b95a", "#90100c06", "#d0302410", "#c08a5a1f",
       "#f2e9d6", "#b9ab90", "#b8201808", 0xf0cd7a, 0xa39880, layout=5),
    _T(u"نافذة مركزية OLED", "transparent", "#e0000000", "#2fd08a", "#a0000000", "#e00b1511", "#d01b7a4b",
       "#e8f2ec", "#9fb3a8", "#e0060a08", 0x7ee0b0, 0x8a9d92, layout=5),
    _T(u"شريط علوي زمردي", "transparent", "#c00f3a2a", "#e0b95a", "#a0101820", "#d01f3d33", "#d01b7a4b",
       "#e2ece7", "#a9b8b0", "#b01a2a26", 0xffd166, 0x90a398, layout=6),
    _T(u"شريط علوي أزرق ليلي", "transparent", "#c0081a30", "#74b4ee", "#a0081420", "#d0102840", "#d02b6a9e",
       "#e8f0f8", "#a9bad0", "#b0081a30", 0xa8d2f7, 0x8ea0b6, layout=6),
    _T(u"نيون سماوي", "#05080d", "#06222e", "#2fe0ff", "#0a1118", "#0e2a38", "#0f6f8a",
       "#d6eef5", "#7fa8b8", "#102431", 0x7ff0ff, 0x6f98a8),
    _T(u"عنبر ملكي", "#120a05", "#4a2208", "#ffb347", "#1a1008", "#2d1a0c", "#9a5a14",
       "#f1e1c9", "#b39a78", "#2e1c0d", 0xffc870, 0x9c8668),
    # ---- more modern looks (accent line under the headers)
    _T(u"ركن زمردي (نافذة صغيرة)", "transparent", "#c80e2e22", "#3ad08f", "#a0101820", "#d0143a2a", "#c01b7a4b",
       "#e4ece8", "#a9b8b0", "#c0123026", 0x7ee0b0, 0x93a69c, layout=7, accent=True),
    _T(u"ركن بنفسجي (نافذة صغيرة)", "transparent", "#c81a1230", "#b79cf5", "#a0120e1e", "#d0221a3a", "#c06a4bb0",
       "#ece6f7", "#aea4c6", "#c01a1430", 0xd0bcf8, 0x9d95b2, layout=7, accent=True),
    _T(u"ركن ذهبي (نافذة صغيرة)", "transparent", "#c8201608", "#e8b84e", "#a0140e06", "#d0302410", "#c08a5a1f",
       "#f2e9d6", "#b9ab90", "#c01c1408", 0xf5d27e, 0xa39880, layout=7, accent=True),
    _T(u"لوحة ياقوتية", "transparent", "#c0300e1a", "#ff7a98", "#a0180810", "#d0401428", "#c0a82a50",
       "#f6e4ea", "#c4a4ae", "#c0260c16", 0xffa8bd, 0xa88c95, layout=1, accent=True),
    _T(u"لوحة فيروزية", "transparent", "#c00a2e30", "#35e0d0", "#a0081a1c", "#d0103c40", "#c00f7f86",
       "#dff6f4", "#9fc4c2", "#c00a2426", 0x7ff2e6, 0x86adab, layout=1, accent=True),
    _T(u"لوحة يسارية بنفسجية", "transparent", "#c01e1440", "#b79cf5", "#a0100c22", "#d0261c48", "#c06a4bb0",
       "#ece6f7", "#aea4c6", "#c0181036", 0xd0bcf8, 0x9d95b2, layout=4, accent=True),
    _T(u"لوحة يسارية فيروزية", "transparent", "#c00a2e30", "#35e0d0", "#a0081a1c", "#d0103c40", "#c00f7f86",
       "#dff6f4", "#9fc4c2", "#c00a2426", 0x7ff2e6, 0x86adab, layout=4, accent=True),
    _T(u"نافذة مركزية بنفسجية", "transparent", "#b8140e28", "#b79cf5", "#900c0818", "#d01e1636", "#c06a4bb0",
       "#ece6f7", "#aea4c6", "#b8160f2c", 0xd0bcf8, 0x9d95b2, layout=5, accent=True),
    _T(u"نافذة مركزية ياقوتية", "transparent", "#b8240a14", "#ff7a98", "#90140610", "#d0381226", "#c0a82a50",
       "#f6e4ea", "#c4a4ae", "#b81a0810", 0xffa8bd, 0xa88c95, layout=5, accent=True),
    _T(u"شريط علوي ذهبي", "transparent", "#c0261a08", "#e8b84e", "#a0140e06", "#d0382a10", "#c08a5a1f",
       "#f2e9d6", "#b9ab90", "#b01c1408", 0xf5d27e, 0xa39880, layout=6, accent=True),
    _T(u"شريط علوي بنفسجي", "transparent", "#c0181030", "#b79cf5", "#a0100c22", "#d0261c48", "#d06a4bb0",
       "#ece6f7", "#aea4c6", "#b0181036", 0xd0bcf8, 0x9d95b2, layout=6, accent=True),
    _T(u"شريط سفلي أزرق", "transparent", "#b0081a30", "#74b4ee", "#a0081420", "#d0102840", "#d02b6a9e",
       "#e8f0f8", "#a9bad0", "#b0081a30", 0xa8d2f7, 0x8ea0b6, layout=3, accent=True),
    _T(u"ليلي ناعم (Slate)", "#0b0f14", "#141c26", "#5aa9ff", "#10161e", "#18222e", "#24508a",
       "#dbe4ee", "#8d9bab", "#1a2430", 0x8cc4ff, 0x7c8a99, accent=True),
    _T(u"كربون أخضر", "#08090a", "#0d1a12", "#39e58c", "#0e1210", "#15221a", "#127a48",
       "#d9efe3", "#8fb3a0", "#13201a", 0x7bf0b4, 0x7ea08f, accent=True),
]


# ------------------------------------------------------------------ geometry
def _scale():
    try:
        return getDesktop(0).size().width() / 1280.0
    except Exception:
        return 1.0


S = _scale()


def p(v):
    return int(round(v * S))


# geometry of the current layout (filled by _build_skin; read by the list rows)
GEO = {"col_w": [p(300), p(470), p(450)], "row_h": p(44), "font": p(25)}
ROW_H = GEO["row_h"]
COL_W = GEO["col_w"]


def _head(t=(770, 8, 500, 72, 44), n=(20, 8, 400, 72, 24), r=(430, 8, 330, 72, 21)):
    return (t, n, r)


def _layout_geo(layout):
    base = dict(hy=104, hh=44, ly=148, lh=396, row=44, font=25, btn_x0=10, btn_step=254, btn_w=244,
                btn_h=36, y1=612, y2=654, btn_font=20, sy=550, ny=580, sx=10, sw=1260, sf=21,
                cols=[(960, 300), (470, 470), (10, 450)], head=_head(),
                bars=[(0, 0, 1280, 88)], lines=[(0, 88, 1280, 3)], hfont=24)
    g = dict(base)
    if layout == 1:       # glass panel on the right
        g.update(cols=[(1086, 184), (806, 272), (546, 252)], hy=96, hh=40, ly=138, lh=426, font=21,
                 btn_x0=546, btn_step=148, btn_w=142, btn_h=34, y1=636, y2=678, btn_font=17,
                 sy=566, ny=596, sx=546, sw=724, sf=18, hfont=20,
                 bars=[(536, 0, 744, 720)], lines=[(536, 0, 3, 720)],
                 head=_head((880, 6, 380, 50, 36), (548, 6, 330, 40, 19), (548, 50, 330, 30, 18)))
    elif layout == 4:     # glass panel on the left
        g.update(cols=[(550, 184), (270, 272), (10, 252)], hy=96, hh=40, ly=138, lh=426, font=21,
                 btn_x0=10, btn_step=148, btn_w=142, btn_h=34, y1=636, y2=678, btn_font=17,
                 sy=566, ny=596, sx=10, sw=724, sf=18, hfont=20,
                 bars=[(0, 0, 744, 720)], lines=[(741, 0, 3, 720)],
                 head=_head((354, 6, 380, 50, 36), (12, 6, 330, 40, 19), (12, 50, 330, 30, 18)))
    elif layout == 3:     # bottom band
        g.update(hy=290, hh=44, ly=334, lh=210, row=42, font=23, sy=548, ny=578,
                 bars=[(0, 0, 1280, 88), (0, 546, 1280, 174)])
    elif layout == 5:     # centred window
        g.update(cols=[(910, 210), (570, 332), (160, 402)], hy=132, hh=38, ly=172, lh=330, font=22,
                 btn_x0=160, btn_step=194, btn_w=186, btn_h=34, y1=572, y2=614, btn_font=18,
                 sy=506, ny=534, sx=160, sw=960, sf=19, hfont=21,
                 bars=[(150, 50, 980, 620)], lines=[(150, 50, 980, 4)],
                 head=_head((700, 58, 420, 44, 34), (162, 58, 520, 40, 20), (162, 98, 520, 26, 17)))
    elif layout == 7:     # compact corner window (top-left)
        g.update(cols=[(630, 180), (360, 262), (30, 322)], hy=72, hh=36, ly=110, lh=330, font=20,
                 btn_x0=30, btn_step=156, btn_w=150, btn_h=32, y1=536, y2=574, btn_font=15,
                 sy=446, ny=474, sx=30, sw=780, sf=17, hfont=19,
                 bars=[(20, 20, 800, 600)], lines=[(20, 20, 800, 4)],
                 head=_head((520, 26, 290, 42, 30), (30, 26, 480, 42, 17), (30, 504, 480, 26, 15)))
    elif layout == 6:     # top band (picture stays visible below)
        g.update(hy=74, hh=40, ly=116, lh=210, row=42, font=23, sy=330, ny=358,
                 y1=392, y2=430, btn_h=34,
                 bars=[(0, 0, 1280, 470)], lines=[(0, 470, 1280, 3)],
                 head=_head((770, 6, 500, 62, 40), (20, 6, 400, 62, 22), (430, 6, 330, 62, 20)))
    return g


def _build_skin(theme=0):
    global ROW_H, COL_W
    th = THEMES[theme % len(THEMES)]
    g = _layout_geo(th["layout"])
    glass = th["bg"] == "transparent"
    GEO["col_w"] = [p(w) for _, w in g["cols"]]
    GEO["row_h"] = p(g["row"])
    GEO["font"] = p(g["font"])
    ROW_H, COL_W = GEO["row_h"], GEO["col_w"]
    W, H = p(1280), p(720)
    extra = u""
    for (x, y, w, h) in g["bars"]:
        extra += (u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="0" />\n'
                  % (p(x), p(y), p(w), p(h), th["bar"]))
    for (x, y, w, h) in g["lines"]:
        extra += (u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="1" />\n'
                  % (p(x), p(y), p(w), p(h), th["line"]))
    cols = u""
    for i in range(3):
        x, w = g["cols"][i]
        if not glass:
            cols += (u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="0" />\n'
                     % (p(x), p(g["hy"]), p(w), p(g["hh"] + g["lh"] + 4), th["panel"]))
        cols += (u'<widget name="%s" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" zPosition="2" />\n'
                 % (HDRS[i], p(x), p(g["hy"]), p(w), p(g["hh"]), p(g["hfont"]), th["text"], th["head"]))
        cols += (u'<widget name="%s" position="%d,%d" size="%d,%d" scrollbarMode="showNever" '
                 u'backgroundColor="%s" foregroundColor="%s" '
                 u'backgroundColorSelected="%s" foregroundColorSelected="#f2f4f7" zPosition="2" />\n'
                 % (NAMES[i], p(x), p(g["ly"]), p(w), p(g["lh"]), th["panel"], th["text"], th["sel"]))
    btn = u""
    row1 = (("qh_red", "#8f2a2a"), ("qh_green", "#2c6e2c"), ("qh_yellow", "#8c7a1e"),
            ("qh_blue", "#2a2a7a"), ("qh_recbtn", "#6e2222"))
    row2 = (("qh_tv", th["btn2"]), ("qh_fmt", th["btn2"]), ("qh_fav", th["btn2"]),
            ("qh_sleep", th["btn2"]), ("qh_theme", th["btn2"]))
    for r, row in enumerate((row1, row2)):
        y = g["y1"] if r == 0 else g["y2"]
        for i, (name, color) in enumerate(row):
            btn += (u'<widget name="%s" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                    u'backgroundColor="%s" foregroundColor="%s" zPosition="2" />\n'
                    % (name, p(g["btn_x0"] + i * g["btn_step"]), p(y), p(g["btn_w"]), p(g["btn_h"]),
                       p(g["btn_font"]), color, "#f4f4f4" if r == 0 else th["btntxt"]))
    if th.get("accent"):                     # thin accent line under every column header
        for i in range(3):
            x, w = g["cols"][i]
            cols += (u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="3" />\n'
                     % (p(x), p(g["hy"] + g["hh"]), p(w), max(2, p(3)), th["line"]))
    barbg = th["bar"]
    (tx, ty, tw, tH, tf), (nx, ny_, nw, nH, nf), (rx, ry, rw, rH, rf) = g["head"]
    head = (u'<widget name="qh_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />\n'
            u'<widget name="qh_now" position="%d,%d" size="%d,%d" font="Regular;%d" halign="left" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />\n'
            u'<widget name="qh_rec" position="%d,%d" size="%d,%d" font="Regular;%d" halign="left" valign="center" foregroundColor="#ff9c9c" backgroundColor="%s" transparent="1" zPosition="3" />\n'
            % (p(tx), p(ty), p(tw), p(tH), p(tf), th["text"] if th["layout"] else "#f2efe6", barbg,
               p(nx), p(ny_), p(nw), p(nH), p(nf), th["line"], barbg,
               p(rx), p(ry), p(rw), p(rH), p(rf), barbg))
    foot = (u'<widget name="qh_status" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />\n'
            u'<widget name="qh_net" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />\n'
            % (p(g["sx"]), p(g["sy"]), p(g["sw"]), p(28), p(g["sf"]), th["dim"], th["bar"],
               p(g["sx"]), p(g["ny"]), p(g["sw"]), p(28), p(g["sf"] - 1), th["text"], th["bar"]))
    return u"""<screen name="QuranHub" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s" title="القرآن الكريم">
%s%s%s%s%s</screen>""" % (W, H, th["bg"], extra, head, cols, foot, btn)


def _build_minibar_skin(theme=0):
    th = THEMES[theme % len(THEMES)]
    return u"""<screen name="QuranHubMini" position="%d,%d" size="%d,%d" flags="wfNoBorder" backgroundColor="#a0000000" title="QuranHub mini">
<widget name="qh_mb" position="%d,0" size="%d,%d" font="Regular;%d" halign="left" valign="center" foregroundColor="%s" backgroundColor="#a0000000" transparent="1" />
</screen>""" % (p(16), p(14), p(640), p(40), p(12), p(616), p(40), p(18), th["text"])


# ------------------------------------------------------------------ helpers
class Runner(object):
    """Run blocking functions in a thread; deliver results on the GUI thread."""

    def __init__(self):
        self.q = queue.Queue()
        self.pending = 0
        self.dead = False
        self.timer = eTimer()
        if hasattr(self.timer, "callback"):
            self.timer.callback.append(self._poll)
        else:
            self._conn = self.timer.timeout.connect(self._poll)

    def run(self, func, ok, err):
        self.pending += 1

        def job():
            try:
                self.q.put((ok, func(), None))
            except Exception as e:
                self.q.put((err, None, e))

        t = threading.Thread(target=job)
        t.daemon = True
        t.start()
        self.timer.start(200, False)

    def _poll(self):
        while True:
            try:
                cb, res, exc = self.q.get_nowait()
            except queue.Empty:
                break
            self.pending -= 1
            if self.dead:
                continue
            try:
                cb(exc if exc is not None else res)
            except Exception as e:
                print("[QuranHub] callback error: %s" % e)
        if self.pending <= 0:
            self.timer.stop()

    def close(self):
        self.dead = True
        self.timer.stop()


def make_timer(callback):
    t = eTimer()
    if hasattr(t, "callback"):
        t.callback.append(callback)
        return t, None
    return t, t.timeout.connect(callback)


class AudioOut(object):
    """A second, audio-only player. It leaves the main service (a TV channel)
    alone, so the channel keeps its picture while the Quran is heard."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.svc = None
        self.conn = None
        self.proc = None
        self.backend = None
        self.err = u""

    def alive(self):
        if self.backend == "gst":
            return self.proc is not None and self.proc.poll() is None
        return self.svc is not None

    def play(self, stype, url, title, backend):
        self.stop()
        self.backend, self.err = backend, u""
        ok = self._play_gst(url) if backend == "gst" else self._play_internal(stype, url, title)
        qlog("audio-out %s type=%s ok=%s err=%s" % (backend, stype, ok, self.err))
        return ok

    def _play_internal(self, stype, url, title):
        try:
            from enigma import eServiceCenter
            ref = eServiceReference(stype, 0, url)
            ref.setName(title or u"")
            svc = eServiceCenter.getInstance().play(ref)
            if svc is None:
                raise RuntimeError("eServiceCenter.play returned None")
            self.svc = svc
            try:
                self.conn = svc.connectEvent(self._ev)
            except Exception:
                self.conn = None
            res = svc.start()
            if res not in (None, 0):
                raise RuntimeError("start() -> %s" % res)
            return True
        except Exception as e:
            self.err = u"%s" % e
            self.svc = self.conn = None
            return False

    def _play_gst(self, url):
        gl = data.which("gst-launch-1.0")
        if not gl:
            self.err = u"gst-launch-1.0 غير موجود"
            return False
        try:
            import subprocess
            dn = open(os.devnull, "wb")
            self.proc = subprocess.Popen(
                [gl, "-q", "playbin", "uri=" + url, "video-sink=fakesink", "audio-sink=alsasink"],
                stdout=dn, stderr=dn, stdin=dn)
            return True
        except Exception as e:
            self.err = u"%s" % e
            self.proc = None
            return False

    def _ev(self, ev):
        try:
            self.on_event(ev)
        except Exception as e:
            qlog("audio event error: %s" % e)

    def stop(self):
        if self.svc is not None:
            try:
                self.svc.stop()
            except Exception:
                pass
            self.svc = self.conn = None
        if self.proc is not None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(2)
                except Exception:
                    self.proc.kill()
            except Exception:
                pass
            self.proc = None

    # -- position / seek / pause (internal service only) --------------------------------
    def _seek(self):
        return self.svc.seek() if self.svc is not None else None

    def position(self):
        """-> (pos_seconds, length_seconds) or None."""
        try:
            sk = self._seek()
            ln, ps = sk.getLength(), sk.getPlayPosition()
            if not ln[0] and not ps[0] and ln[1] > 0:
                return ps[1] / 90000.0, ln[1] / 90000.0
        except Exception:
            pass
        return None

    def seek_rel(self, secs):
        try:
            self._seek().seekRelative(1 if secs >= 0 else -1, int(abs(secs) * 90000))
            return True
        except Exception:
            return False

    def pause(self, flag):
        try:
            ps = self.svc.pause()
            ps.pause() if flag else ps.unpause()
            return True
        except Exception:
            return False


class Player(object):
    """Shared playback state.

    Two output modes:
      * main:    the stream replaces the main service (the TV channel); the
                 previous service is restored on stop.
      * overlay: `sink` (an AudioOut) plays the stream while the TV channel keeps
                 running on the main service, its own audio muted.

    NOTE: eServiceReference(type, flags, path) takes the URL *verbatim*.
    (Escaping ':' as %3a is only for the full string form of a reference.)
    If one engine fails the next attempt is tried automatically."""
    saved = None
    saved_ref = None
    active = False
    engine = SERVICE_TYPE
    attempts = []
    tries = 0
    cur_url = None          # the real stream (used for probing / recording)
    eng_url = None          # what the engine actually plays (maybe the time-shift proxy)
    cur_title = None
    sink = None
    started = False
    restoring = False       # True while we put the TV channel back (the zap hook must let it through)
    restore_hook = None     # BG.follow_restore -> the channel to go back to (the one in the PiP)

    @classmethod
    def engine_name(cls):
        base = u"exteplayer3" if cls.engine == 5002 else u"gstreamer"
        if cls.sink is not None and cls.tries < len(cls.attempts) and cls.attempts[cls.tries][2] == "gst":
            base = u"gst-launch"
        return base

    @classmethod
    def play(cls, session, url, title, eng_url=None, sink=None):
        fresh = False
        if not cls.active:
            try:
                cls.saved = session.nav.getCurrentlyPlayingServiceOrGroup()
            except Exception:
                cls.saved = None
            try:
                cls.saved_ref = session.nav.getCurrentlyPlayingServiceReference()
            except Exception:
                cls.saved_ref = None
            cls.active = True
            fresh = True
        cls.sink = sink
        cls.cur_url, cls.cur_title = url, title
        eu = eng_url or url
        other = 5002 if cls.engine == 4097 else 4097
        if sink is not None:
            cls.attempts = [(cls.engine, eu, "internal"), (other, eu, "internal"), (cls.engine, eu, "gst")]
        else:
            cls.attempts = [(cls.engine, eu, None), (other, eu, None)]
        if eu != url:                       # proxy trouble -> last resort: the direct URL
            cls.attempts.append((cls.engine, url, "internal" if sink is not None else None))
        cls.tries = 0
        cls.started = cls._go(session)
        return fresh

    @classmethod
    def _go(cls, session):
        while cls.tries < len(cls.attempts):
            stype, url, backend = cls.attempts[cls.tries]
            cls.eng_url = url
            if backend:                                         # overlay output
                if cls.sink is not None and cls.sink.play(stype, url, cls.cur_title or u"", backend):
                    return True
                cls.tries += 1
                continue
            ref = eServiceReference(stype, 0, url)
            ref.setName(cls.cur_title or u"")
            session.nav.playService(ref)
            return True
        return False

    @classmethod
    def fail(cls, session):
        """Try the next attempt. Returns False when nothing is left."""
        if not cls.active or cls.tries + 1 >= len(cls.attempts):
            return False
        cls.tries += 1
        return cls._go(session)

    @classmethod
    def toggle_engine(cls, session):
        cls.engine = 5002 if cls.engine == 4097 else 4097
        return cls.engine

    @classmethod
    def halt_output(cls, session):
        """Stop sound but keep the state (used by pause on live streams)."""
        try:
            if cls.sink is not None:
                cls.sink.stop()
            else:
                session.nav.stopService()
        except Exception as e:
            print("[QuranHub] halt error: %s" % e)

    @classmethod
    def stop(cls, session, restore=True):
        if not cls.active:
            return
        try:
            if cls.sink is not None:
                cls.sink.stop()                      # the TV channel was never touched
            else:
                session.nav.stopService()
                target = cls.saved
                if restore and cls.restore_hook is not None:
                    try:
                        target = cls.restore_hook() or target
                    except Exception as e:
                        print("[QuranHub] restore hook: %s" % e)
                if restore and target is not None:
                    cls.restoring = True
                    try:
                        session.nav.playService(target)
                    finally:
                        cls.restoring = False
        except Exception as e:
            print("[QuranHub] stop error: %s" % e)
        cls.active = False
        cls.saved = None
        cls.saved_ref = None
        cls.cur_url = None
        cls.eng_url = None
        cls.sink = None


# ------------------------------------------------------------------ content
def surah_payload(rec_name, n, url=None, resolve=None):
    d = {"title": u"%s - سورة %s" % (rec_name, data.surah_name(n)), "autonext": True, "n": n}
    if url:
        d["url"] = url
    else:
        d["resolve"] = resolve
    return d


def surah_row(n):
    return u"%d. %s" % (n, data.surah_name(n))


def section_loader(key):
    if key == "mp3q_reciters":
        return lambda: [(r["name"], {"rec": r}) for r in data.mp3quran_reciters()]
    if key == "mp3q_radios":
        return lambda: [(n, {"title": n, "url": u, "live": True}) for n, u in data.mp3quran_radios()]
    if key == "qcom":
        return lambda: [(n, {"qcom": (n, rid)}) for n, rid in data.quran_com_reciters()]
    if key == "sq_reciters":
        return lambda: [(n, {"sq": (n, u)}) for n, u in data.surahquran_reciters()]
    if key == "sq_radios":
        return lambda: [(n, {"title": n, "live": True,
                             "resolve": (lambda pg=pg: data.surahquran_radio_url(pg))})
                        for n, pg in data.SQ_RADIOS]
    if key == "islam":
        return lambda: [(n, {"iw": (n, qid)}) for n, qid in data.islamweb_reciters()]
    if key == "way_reciters":
        return lambda: [(n, {"w2": (n, slug)}) for n, slug in data.way2quran_reciters()]
    if key == "way_iconic":
        def iconic():
            out = []
            for c in data.way2quran_iconic():
                label = u"%s — %s" % (c["reciter"], c["surah"])
                sub = u" • ".join(x for x in (c["riwaya"], c["duration"]) if x)
                out.append((label, {
                    "title": label, "autonext": True, "sub": sub,
                    "resolve": (lambda c=c: data.way2quran_resolve(c["slug"], c["n"], c["riwaya"]))}))
            return out
        return iconic
    if key == "pls":
        return lambda: [(n, {"pl": n}) for n in sorted(BG.cfg.get("pls", {}))]
    if key == "hist":
        return lambda: [(h["title"], {"title": h["title"], "url": h["url"], "live": h.get("live", False),
                                      "autonext": not h.get("live", False),
                                      "sub": time.strftime("%Y-%m-%d %H:%M", time.localtime(h.get("ts", 0)))})
                        for h in BG.cfg.get("hist", [])]
    if key == "most":
        return lambda: [(h["title"], {"title": h["title"], "url": h["url"], "live": h.get("live", False),
                                      "autonext": not h.get("live", False), "sub": u"%d مرة" % c})
                        for c, h in extras.most_played(BG.cfg)]
    if key == "local":
        return lambda: [(n, {"title": n, "url": localserve.url_for(pth), "path": pth, "autonext": True, "sub": u"ملف محفوظ"})
                        for n, pth in extras.local_files()]
    if key == "srch":
        return lambda: list(BG.search_rows)
    if key == "acache":
        return lambda: [(t, {"title": t, "url": u, "path": localserve.path_of(u), "autonext": True,
                             "sub": data.fmt_bytes(sz)}) for t, u, sz in AUDIO.entries()]
    if key == "sync":
        return lambda: [(u"%s - %s" % (r["name"], r["rewaya"]), {"syn": r}) for r in data.timing_reads()]
    if key == "qpedia":
        return lambda: [(lab, {"qp": (lab, srv, sur)}) for lab, srv, sur in data.quranpedia_reciters()]
    if key == "tvq":
        return lambda: [(n, {"tvq": (n, u)}) for n, u in data.tvquran_reciters()]
    if key == "assabile":
        return lambda: [(n, {"as": (n, s)}) for n, s in data.assabile_reciters()]
    if key == "ourq":
        return lambda: [(n, {"oq": (n, u)}) for n, u in data.ourquraan_reciters()]
    if key.startswith("dsk:"):
        root = key[4:]
        return lambda: [(n, {"dsk": (n, f)}) for n, f in library.disk_reciters(root)]
    if key.startswith("tg:"):
        u = key[3:]
        name = dict(tg_channels(BG.cfg)).get(u, u)
        return lambda: data.tg_rows(u, name)
    raise ValueError(key)


def subs_for(entry):
    """Rows for the surah column. May block (surahquran) -> run in a thread."""
    out = []
    if "rec" in entry:                      # mp3quran.net
        rec = entry["rec"]
        multi = len(rec["moshaf"]) > 1
        for m in rec["moshaf"]:
            if multi:
                extra = u"" if len(m["surahs"]) >= 114 else u" (%d)" % len(m["surahs"])
                out.append((u"—  %s%s  —" % (m["name"], extra), None))
            for n in m["surahs"]:
                out.append((surah_row(n), surah_payload(
                    rec["name"], n, url=data.mp3quran_surah_url(m["server"], n))))
    elif "dsk" in entry:                    # a folder on the HDD / USB stick
        name, folder = entry["dsk"]
        rec = name.split(u" - ")[-1]
        for n, label, pth in library.disk_tracks(folder):
            d = {"title": u"%s - %s" % (rec, (u"سورة " + data.surah_name(n)) if n else label),
                 "url": localserve.url_for(pth), "path": pth, "autonext": True}
            if n:
                d["n"] = n
            out.append((label, d))
    elif "qcom" in entry:                   # quran.com
        name, rid = entry["qcom"]
        for n in range(1, 115):
            pay = surah_payload(name, n, resolve=(lambda r=rid, c=n: data.quran_com_audio(r, c)))
            pay["qdc"] = [rid, n]               # quran.com gives the time of every word of this file
            out.append((surah_row(n), pay))
    elif "iw" in entry:                     # islamweb.net
        name, qid = entry["iw"]
        last = None
        for riw, n, label, url in data.islamweb_tracks(qid):
            if riw and riw != last:
                out.append((u"—  %s  —" % riw, None))
                last = riw
            row = surah_row(n) if n else label
            out.append((row, {"title": u"%s - %s" % (name, label), "url": url, "autonext": True}))
    elif "w2" in entry:                     # way2quran.com
        name, slug = entry["w2"]
        last = None
        for riw, n, url in data.way2quran_tracks(slug):
            if riw != last:
                out.append((u"—  %s  —" % data.W2_RIWAYAT.get(riw, riw), None))
                last = riw
            out.append((surah_row(n), surah_payload(name, n, url=url)))
    elif "syn" in entry:                    # mp3quran recitations with exact ayah timing
        r = entry["syn"]
        for n in range(1, min(114, r["count"]) + 1):
            pay = surah_payload(r["name"], n, url="%s%03d.mp3" % (r["folder"], n))
            pay["timing"] = r["id"]
            out.append((surah_row(n), pay))
    elif "qp" in entry:                     # quranpedia.net (servers from its API)
        name, server, surahs = entry["qp"]
        for n in surahs:
            out.append((surah_row(n), surah_payload(name, n, url="%s%03d.mp3" % (server, n))))
    elif "tvq" in entry:                    # tvquran.com
        name, url = entry["tvq"]
        tracks = data.tvquran_tracks(url)
        groups = len(set(g for g, _n, _l, _u in tracks))
        last = None
        for g, n, label, u in tracks:
            if groups > 1 and g != last:
                out.append((u"—  مصحف %d  —" % (g + 1), None))
                last = g
            if n:
                out.append((surah_row(n), surah_payload(name, n, url=u)))
            else:
                out.append((label, {"title": u"%s - %s" % (name, label), "url": u, "autonext": True}))
    elif "as" in entry:                     # assabile.com (download page -> mp3)
        name, slug = entry["as"]
        for n, label, dl in data.assabile_tracks(slug):
            pay = {"title": u"%s - %s" % (name, (u"سورة " + data.surah_name(n)) if n else label), "autonext": True,
                   "resolve": (lambda d=dl: data.follow_audio(d))}
            if n:
                pay["n"] = n
            out.append((surah_row(n) if n else label, pay))
    elif "oq" in entry:                     # ourquraan.com
        name, url = entry["oq"]
        for n, label, u in data.ourquraan_tracks(url):
            pay = {"title": u"%s - %s" % (name, (u"سورة " + data.surah_name(n)) if n else label), "url": u,
                   "autonext": True}
            if n:
                pay["n"] = n
            out.append((surah_row(n) if n else label, pay))
    elif "pl" in entry:                     # user playlist
        for it in BG.cfg.get("pls", {}).get(entry["pl"], []):
            live = bool(it.get("live"))
            out.append((it["title"], {"title": it["title"], "url": it["url"], "live": live,
                                      "autonext": not live, "plname": entry["pl"]}))
    elif "sq" in entry:                     # surahquran.com
        name, url = entry["sq"]
        for n, direct, page in data.surahquran_tracks(url):
            out.append((surah_row(n), surah_payload(
                name, n, resolve=(lambda n=n, d=direct, pg=page:
                                  data.surahquran_resolve(n, d, pg)))))
    return out


def fav_loader(favs):
    """Re-create the entries of favourite (section, name) pairs."""
    def run():
        out, cache = [], {}
        for key, name in favs:
            if key not in cache:
                try:
                    cache[key] = dict(section_loader(key)())
                except Exception:
                    cache[key] = {}
            entry = cache[key].get(name)
            if entry is not None:
                out.append((name, dict(entry, favkey=(key, name))))
        return out
    return run


def entry_has_subs(entry):
    return bool(entry) and any(k in entry for k in ("rec", "qcom", "sq", "iw", "w2", "pl", "qp", "tvq", "as", "oq", "syn", "dsk"))


def entry_needs_network(entry):
    return bool(entry) and any(k in entry for k in ("sq", "iw", "w2", "tvq", "as", "oq"))


def popup(text, timeout=4):
    try:
        from Tools import Notifications
        from Screens.MessageBox import MessageBox
        Notifications.AddPopup(text=text, type=MessageBox.TYPE_INFO,
                               timeout=timeout, id="QuranHub")
    except Exception:
        pass


# ------------------------------------------------------------------ background
RECITER_KEYS = ("mp3q_reciters", "qcom", "qpedia", "tvq", "sq_reciters", "islam", "way_reciters", "assabile", "ourq")


def reciter_key(label):
    """Name used to put the same reciter from different sites together."""
    t = data.norm(label or u"")
    t = re.sub(u"\\(.*?\\)|\\[.*?\\]", u"", t)
    t = re.sub(u"^(الشيخ|القارئ|المقرئ|الشيخ القارئ)\\s+", u"", t.strip())
    return t.replace(u" ", u"").replace(u"ـ", u"")


class Hub16Bg(object):
    """1.6: reciter search over every site, downloads in a chosen format into a folder per reciter,
    background jobs on the library, and the Telegram bot (all on the background object, so the bot
    works with the plugin screen closed)."""
    jobs = None
    bot = None
    bot_timer = None
    events = None
    dl_resumed = False
    tg_pin = None
    tg_pin_until = 0
    tg_bad = None
    tg_ctx = None
    tg_seq = 0
    tg_warned = None

    # -- set-up (called from attach) --------------------------------------------------------
    def gh_check(self, manual=False):
        """Ask GitHub for the newest public version (version.json); tell the user when there is one."""
        if private_edition():
            return
        self.cfg["gh_checked"] = int(time.time())

        def job():
            return json.loads(data.http_text(GITHUB_INFO, 20))

        def done(res):
            if isinstance(res, Exception) or not isinstance(res, dict) or not res.get("version"):
                if manual:
                    self.set_status(u"تعذّر الوصول إلى GitHub: %s" % res, notify=True)
                return
            self.cfg["gh_latest"] = {"version": res["version"], "ipk": res.get("ipk", u""), "notes": res.get("notes", u""),
                                     "sha256": res.get("sha256", u"")}
            self.save()
            if vtuple(res["version"]) > vtuple(PLUGIN_VERSION):
                msg = u"⬆ يتوفر إصدار جديد من Saad Quran Hub: %s\nللتثبيت: MENU > أدوات وتشخيص > تحديث البلاجين" % res["version"]
                if res.get("notes"):
                    msg += u"\n\n" + res["notes"][:300]
                popup(msg, 15)
                self.tg_notify(msg)
            elif manual:
                self.set_status(u"لديك أحدث إصدار (%s)" % PLUGIN_VERSION, notify=True)
        self.runner.run(job, done, done)

    def init16(self):
        if self.events is None:
            self.events = []
        try:
            if not self.cfg.get("tg_token") and tgbot.default_token():
                self.cfg["tg_token"] = tgbot.default_token()    # survives any later package update
                self.save()
        except Exception:
            pass
        if self.jobs is None:
            self.jobs = library.Jobs()
            self.jobs.on_event = lambda k, t, d: self.events.append(("job", k, t, d))
        try:
            self.dl.on_event = lambda k, t, d: self.events.append(("dl", k, t, d))
        except Exception:
            pass
        if self.bot_timer is None:
            self.bot_timer, self._c16 = make_timer(self.bot_tick)
            self.bot_timer.start(700, False)
        if not self.dl_resumed:
            self.dl_resumed = True
            try:
                n = self.dl.resume_saved()
                if n:
                    self.set_status(u"استئناف %d تنزيل لم يكتمل قبل إطفاء الجهاز" % n)
            except Exception as e:
                qlog("resume downloads: %s" % e)
        if self.bot is None and self.bot_enabled():
            self.bot_start()

    # -- reciter search over every site -------------------------------------------------------
    def search_reciters(self, query, done):
        q = reciter_key(query)
        titles = dict((s[0], s[1]) for s in SECTIONS)

        def load_all():
            """Every site's reciter list, fetched side by side (at most ~25 s for the slow ones)."""
            got = {}

            def one(key):
                try:
                    got[key] = section_loader(key)()
                except Exception as e:
                    qlog("reciter search %s: %s" % (key, e))
            ths = []
            for key in RECITER_KEYS:
                if SEC_CACHE.get(key) is not None:
                    got[key] = SEC_CACHE[key]
                    continue
                th = threading.Thread(target=one, args=(key,))
                th.daemon = True
                th.start()
                ths.append(th)
            t_end = time.time() + 25
            for th in ths:
                th.join(max(0.1, t_end - time.time()))
            return dict(got)

        def run():
            groups = {}
            if len(q) < 2:
                return []
            lists = load_all()
            for key in RECITER_KEYS:
                if key not in lists:
                    continue
                if key not in SEC_CACHE:
                    SEC_CACHE[key] = lists[key]
                for label, entry in lists[key]:
                    if not entry:
                        continue
                    k = reciter_key(label)
                    if q in k:
                        g = groups.setdefault(k, [label, []])
                        g[1].append((titles.get(key, key), key, label, entry))
            out = sorted(groups.values(), key=lambda g: (not reciter_key(g[0]).startswith(q), -len(g[1]), g[0]))
            return out[:60]
        Runner().run(run, done, done)

    def source_rows(self, entry, done):
        Runner().run(lambda: subs_for(entry), done, done)

    # -- downloads: format + a folder per reciter ---------------------------------------------------
    def dl_format(self):
        f = self.cfg.get("dl_fmt", "original")
        if f != "original" and not data.backend_for(f):
            return "original"
        return f

    def download_payloads(self, payloads, fmt=None):
        root = extras.download_dir()
        if root is None:
            return self.set_status(u"لا يوجد HDD أو USB متصل للتنزيل")
        todo = [x for x in payloads if x and (x.get("url") or x.get("resolve")) and not x.get("live")]
        if not todo:
            return self.set_status(u"لا يوجد ما يُنزَّل")
        fmt = fmt or self.dl_format()
        if fmt != "original" and not data.backend_for(fmt):
            self.set_status(u"الصيغة %s تحتاج ffmpeg - سيُنزَّل الملف الأصلي" % data.FORMAT_LABEL.get(fmt, fmt))
            fmt = "original"

        def resolve_all():
            out = []
            for x in todo:
                try:
                    u = x.get("url") or x["resolve"]()
                    if u and u.startswith("http"):
                        out.append((x, u))
                except Exception as e:
                    qlog("download resolve: %s" % e)
            return out

        def go(rows):
            if isinstance(rows, Exception) or not rows:
                return self.set_status(u"تعذّر تجهيز روابط التنزيل")
            for x, u in rows:
                title = x.get("title", u"") or u
                rec = title.split(u" - ")[0].strip() if u" - " in title else library.LOOSE
                n = x.get("n")
                name = (u"%03d %s" % (n, data.surah_name(n))) if n else data.safe_name(title)
                self.dl.add(title, u, fmt, library.reciter_folder(root, rec), data.safe_name(name))
            self.set_status(u"بدأ التنزيل: %d ملف%s - في مجلد القارئ داخل downloads" % (
                len(rows), u" بصيغة " + data.FORMAT_LABEL.get(fmt, fmt) if fmt != "original" else u""), notify=True)
            self.ensure_timer()
        self.set_status(u"جاري تجهيز التنزيل ...")
        self.runner.run(resolve_all, go, lambda e: self.set_status(u"تعذّر التنزيل: %s" % e))

    def work_text(self):
        """Downloads + library jobs, for the status line and the bot."""
        out = []
        d = self.dl
        if d.busy():
            pct = u" %d%%" % (100 * d.bytes // d.total) if d.total else u""
            out.append(u"⬇ %s%s  (%d/%d)" % ((d.current or u"")[:40], pct, d.batch_done, d.batch))
        if self.jobs is not None and self.jobs.busy():
            out.append(self.jobs.text())
        return u"\n".join(out)

    # -- events from the worker threads (shown + sent to Telegram) ---------------------------------
    def process_events(self):
        while self.events:
            src, kind, title, detail = self.events.pop(0)
            if src == "dl" and kind == "batch":
                msg = u"✅ اكتمل التنزيل: %s ملف" % detail
                self.set_status(msg, notify=True)
                self.tg_notify(msg)
            elif src == "dl" and kind == "error":
                msg = u"⚠️ تعذّر تنزيل %s: %s" % (title, detail)
                self.set_status(msg)
                if u"المساحة" in detail:
                    self.tg_notify(msg)
            elif src == "job":
                msg = u"✅ انتهى: %s (%s)" % (title, detail)
                self.set_status(msg, notify=True)
                self.tg_notify(msg)

    # -- Telegram bot --------------------------------------------------------------------------
    def bot_token(self):
        return (self.cfg.get("tg_token") or tgbot.default_token() or u"").strip()

    def bot_enabled(self):
        return bool(self.bot_token()) and self.cfg.get("tg_bot", True)

    def bot_start(self):
        tok = self.bot_token()
        if not tok:
            return False
        if self.bot is not None and self.bot.token == tok:
            return self.bot.start()
        if self.bot is not None:
            self.bot.stop()
        self.bot = tgbot.TgBot(tok)
        self.tg_ctx = {}
        return self.bot.start()

    def bot_stop(self):
        if self.bot is not None:
            self.bot.stop()
        self.bot = None

    def bot_state(self):
        b = self.bot
        if b is None:
            return u"متوقف"
        if b.error and not b.ok_at:
            return u"خطأ: %s" % b.error[:60]
        if b.ok_at and time.time() - b.ok_at < 90:
            return u"متصل%s" % (u" (@%s)" % b.me.get("username") if b.me else u"")
        return u"جاري الاتصال ..." if not b.error else u"إعادة المحاولة: %s" % b.error[:50]

    def bot_tick(self):
        try:
            self.process_events()
        except Exception as e:
            qlog("events: %r" % (e,))
        try:
            self.tick18()
        except Exception as e:
            qlog("tick18: %r" % (e,))
        try:
            self.tick19()
        except Exception as e:
            qlog("tick19: %r" % (e,))
        if self.bot is None:
            return
        for u in self.bot.poll():
            try:
                self.tg_handle(u)
            except Exception as e:
                qlog("tg handle: %r" % (e,))

    def tg_owners(self):
        return self.cfg.get("tg_owners") or []

    def tg_is_owner(self, chat):
        return any(int(o.get("id", 0)) == int(chat) for o in self.tg_owners())

    def tg_notify(self, text):
        if self.bot is None or not self.cfg.get("tg_notify", True):
            return
        for o in self.tg_owners():
            self.bot.send(o["id"], text)

    def tg_new_pin(self):
        import random
        self.tg_pin = "%04d" % random.randint(1000, 9999)
        self.tg_pin_until = time.time() + 300
        popup(u"رمز ربط بوت تليجرام:  %s\nأرسله للبوت من جوالك خلال 5 دقائق" % self.tg_pin, 60)
        return self.tg_pin

    def tg_pair(self, chat, text, msg):
        if self.tg_bad is None:
            self.tg_bad = {}
        bad = self.tg_bad.get(chat, [0, 0])
        if bad[0] >= 5 and time.time() - bad[1] < 600:
            return
        if self.tg_pin and text == self.tg_pin and time.time() < self.tg_pin_until:
            name = (msg.get("from") or {}).get("first_name") or u"?"
            owners = [o for o in self.tg_owners() if int(o.get("id", 0)) != int(chat)]
            owners.append({"id": int(chat), "name": name})
            self.cfg["tg_owners"] = owners
            self.save()
            self.tg_pin = None
            popup(u"تم ربط تليجرام: %s" % name, 5)
            self.bot.send(chat, u"✅ تم الربط بالريسيفر. أهلاً %s\nاكتب اسم أي قارئ للبحث، أو استعمل الأزرار." % name,
                          reply_kb=tgbot.MAIN_KB)
            return
        if text.startswith(u"/start"):
            self.tg_new_pin()
            self.bot.send(chat, u"🔐 هذا البوت خاص بريسيفر صاحبه.\nأرسل الرمز المكوّن من 4 أرقام الظاهر الآن على شاشة التلفزيون.")
            return
        if text.isdigit() and len(text) == 4:
            self.tg_bad[chat] = [bad[0] + 1, time.time()]
            self.bot.send(chat, u"❌ الرمز غير صحيح أو انتهت صلاحيته. اكتب /start لرمز جديد.")
            return
        if self.tg_warned is None:
            self.tg_warned = {}
        if time.time() - self.tg_warned.get(chat, 0) > 60:
            self.tg_warned[chat] = time.time()
            self.bot.send(chat, u"🔐 البوت غير مربوط بهذا الحساب. اكتب /start ثم الرمز الظاهر على التلفزيون.")

    def tg_put(self, obj):
        if self.tg_ctx is None or len(self.tg_ctx) > 300:
            self.tg_ctx = {}
        self.tg_seq += 1
        k = str(self.tg_seq)
        self.tg_ctx[k] = obj
        return k

    HELP = (u"📖 Saad Quran Hub\n"
            u"• اكتب اسم قارئ للبحث في كل المواقع، ثم اختر السورة لتعمل على التلفزيون.\n"
            u"• /now التشغيل الآن وأزرار التحكم\n• /radio الإذاعات\n• /lib مكتبتي (تشغيل أو إرسال الملفات)\n"
            u"• /dl حالة التنزيلات\n• /ayah آية اليوم\n• /marks علاماتي\n• /speed سرعة التلاوة\n• /stop إيقاف\n"
            u"• /wird ورد الحفظ الآن\n• /backup نسخة احتياطية (أرسل الملف لاحقاً للاستعادة)\n• /station رابط إذاعتي الخاصة\n"
            u"• /stars نجوم الأسرة\n• /harvest حصاد الشهر")

    def tg_handle(self, u):
        if "callback_query" in u:
            return self.tg_callback(u["callback_query"])
        m = u.get("message") or {}
        chat = (m.get("chat") or {}).get("id")
        text = (m.get("text") or u"").strip()
        if chat and m.get("document") and self.tg_is_owner(chat):
            return self.tg_restore_file(chat, m["document"])
        if not chat or not text:
            return
        if not self.tg_is_owner(chat):
            return self.tg_pair(chat, text, m)
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0].lower() if text.startswith(u"/") else None
        arg = parts[1].strip() if len(parts) > 1 else u""
        b = self.bot
        if cmd in (u"/start", u"/help"):
            b.send(chat, self.HELP, reply_kb=tgbot.MAIN_KB)
        elif cmd == u"/now" or text == u"▶️ التشغيل الآن":
            self.tg_now(chat)
        elif cmd == u"/stop":
            self.stop_play()
            b.send(chat, u"⏹ تم الإيقاف")
        elif cmd == u"/marks" or text == u"🔖 علاماتي":
            ms = self.cfg.get("marks", [])
            if not ms:
                return b.send(chat, u"لا توجد علامات بعد")
            b.send(chat, u"🔖 علاماتي - اختر للتشغيل على التلفزيون:",
                   [[{"text": m["name"][:50], "callback_data": "M:%d" % i}] for i, m in enumerate(ms[:30])])
        elif cmd == u"/speed":
            b.send(chat, u"⏩ سرعة التلاوة (بنفس صوت الشيخ):", tgbot.grid(
                [(u"×%s" % self._sp(s), "V:%s" % s) for s in library.SPEEDS], 4))
        elif cmd == u"/radio" or text == u"📻 الإذاعات":
            self.tg_radios(chat, 0)
        elif cmd == u"/lib" or text == u"📚 مكتبتي":
            self.tg_lib(chat)
        elif cmd == u"/dl" or text == u"⬇️ التنزيلات":
            b.send(chat, self.work_text() or u"لا توجد تنزيلات أو أعمال جارية")
        elif cmd == u"/ayah" or text == u"📖 آية اليوم":
            b.send(chat, self.tg_ayah_text())
        elif (cmd == u"/search" and not arg) or text == u"🔎 بحث عن قارئ":
            b.send(chat, u"اكتب اسم القارئ (مثلاً: المنشاوي)")
        elif cmd == u"/search":
            self.tg_search(chat, arg)
        elif cmd == u"/wird":
            self.tg_wird(chat)
        elif cmd == u"/backup":
            self.tg_backup(chat)
        elif cmd == u"/stars":
            b.send(chat, u"⭐ النجوم\n" + u"\n".join(u"• %s: %d" % x for x in studio.stars_of(self.cfg)))
        elif cmd == u"/harvest":
            b.send(chat, studio.harvest_text(self.cfg, "month"))
        elif cmd == u"/station":
            url = self.station_url()
            b.send(chat, (u"📻 إذاعتي الخاصة (من شبكة البيت فقط):\n%s" % url) if url else u"تعذّر تشغيل الإذاعة")
        elif cmd:
            b.send(chat, self.HELP)
        else:
            self.tg_search(chat, text)

    def tg_now_text(self):
        if not Player.active:
            return u"⏹ لا يوجد تشغيل الآن"
        _pct, txt = self.progress()
        out = [u"▶️ %s" % (Player.cur_title or u""), u"⏱ %s" % (txt or u"")]
        try:
            cur = self.verse_now()
            if cur:
                v = dict(extras.local_verses(cur[0]) or []).get(cur[1], u"")
                out.append(u"📖 الآية %d: %s" % (cur[1], extras.sanitize(v)[:300]))
        except Exception:
            pass
        v = self.get_volume()
        if v is not None:
            out.append(u"🔊 %d%%" % v)
        w = self.work_text()
        if w:
            out.append(w)
        return u"\n".join(out)

    def tg_now(self, chat, msg_id=None):
        if msg_id:
            self.bot.edit(chat, msg_id, self.tg_now_text(), tgbot.CONTROL_KB)
        else:
            self.bot.send(chat, self.tg_now_text(), tgbot.CONTROL_KB)

    def tg_ayah_text(self, cur=None):
        try:
            if cur is None:
                key, text = extras.ayah_of_the_day()
                n, a = [int(x) for x in key.split(":")]
            else:
                n, a = cur
                text = dict(extras.local_verses(n) or []).get(a, u"")
            taf = extras.local_tafsir("muyassar", n) or []
            body = extras.sanitize(taf[a - 1]) if a - 1 < len(taf) and taf[a - 1] != u"=" else u""
            return u"﴿%s﴾\n[%s: %d]\n\nالتفسير الميسر: %s\n\nhttps://quran.com/%d/%d" % (
                extras.sanitize(text), data.surah_name(n), a, body, n, a)
        except Exception as e:
            return u"تعذّر: %s" % e

    def tg_search(self, chat, q):
        b = self.bot
        b.send(chat, u"🔎 أبحث عن «%s» في كل المواقع ..." % q)

        def done(groups):
            if isinstance(groups, Exception) or not groups:
                return b.send(chat, u"لم أجد قارئاً بهذا الاسم. جرّب جزءاً من الاسم.")
            gid = self.tg_put(groups)
            kb = [[{"text": u"%s  (%d)" % (g[0][:40], len(g[1])), "callback_data": "r:%s:%d" % (gid, i)}]
                  for i, g in enumerate(groups[:12])]
            b.send(chat, u"اختر القارئ (الرقم = عدد المصادر):", kb)
        self.search_reciters(q, done)

    def tg_surahs(self, chat, sid, page, msg_id=None):
        name, pls = self.tg_ctx.get(sid, (u"", []))
        per = 24
        rows = [(lab[:22], "y:%s:%d" % (sid, i)) for i, (lab, _x) in enumerate(pls)][page * per:(page + 1) * per]
        kb = tgbot.grid(rows, 3)
        nav = []
        if page > 0:
            nav.append({"text": u"◀ السابق", "callback_data": "p:%s:%d" % (sid, page - 1)})
        if (page + 1) * per < len(pls):
            nav.append({"text": u"التالي ▶", "callback_data": "p:%s:%d" % (sid, page + 1)})
        if nav:
            kb.append(nav)
        kb.append([{"text": u"⬇️ تنزيل الكل (%s)" % data.FORMAT_LABEL.get(self.dl_format(), u""),
                    "callback_data": "d:%s" % sid}])
        text = u"🎙 %s - اختر السورة لتعمل على التلفزيون (%d)" % (name, len(pls))
        if msg_id:
            self.bot.edit(chat, msg_id, text, kb)
        else:
            self.bot.send(chat, text, kb)

    def tg_open_source(self, chat, src):
        _title, _key, label, entry = src
        b = self.bot

        def done(rows):
            if isinstance(rows, Exception) or not rows:
                return b.send(chat, u"تعذّر تحميل سور هذا المصدر")
            pls = [(lab, x) for lab, x in rows if x and (x.get("url") or x.get("resolve"))]
            if not pls:
                return b.send(chat, u"لا توجد سور قابلة للتشغيل")
            self.tg_surahs(chat, self.tg_put((label, pls)), 0)
        self.source_rows(entry, done)

    def tg_radios(self, chat, page, msg_id=None):
        items = SEC_CACHE.get("mp3q_radios")
        if items is None:
            def done(res):
                if isinstance(res, Exception) or not res:
                    return self.bot.send(chat, u"تعذّر تحميل الإذاعات")
                SEC_CACHE.setdefault("mp3q_radios", res)
                self.tg_radios(chat, page)
            return Runner().run(lambda: section_loader("mp3q_radios")(), done, done)
        rid = self.tg_put(items)
        per = 12
        kb = [[{"text": lab[:40], "callback_data": "R:%s:%d" % (rid, i)}]
              for i, (lab, x) in enumerate(items) if x][page * per:(page + 1) * per]
        nav = []
        if page > 0:
            nav.append({"text": u"◀", "callback_data": "Rp:%d" % (page - 1)})
        if (page + 1) * per < len(items):
            nav.append({"text": u"▶", "callback_data": "Rp:%d" % (page + 1)})
        if nav:
            kb.append(nav)
        if msg_id:
            self.bot.edit(chat, msg_id, u"📻 الإذاعات المباشرة", kb)
        else:
            self.bot.send(chat, u"📻 الإذاعات المباشرة", kb)

    def tg_lib(self, chat):
        groups = library.scan()
        if not groups:
            return self.bot.send(chat, u"المكتبة فارغة (لا توجد ملفات منزّلة على القرص)")
        lid = self.tg_put(groups)
        kb = [[{"text": u"%s (%d)" % (g[0][:36], len(g[2])), "callback_data": "L:%s:%d" % (lid, i)}]
              for i, g in enumerate(groups[:40])]
        self.bot.send(chat, u"📚 مكتبتي - اختر القارئ:", kb)

    def tg_callback(self, cq):
        chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
        msg_id = (cq.get("message") or {}).get("message_id")
        d = cq.get("data") or u""
        b = self.bot
        if not chat or not self.tg_is_owner(chat):
            return b.answer(cq.get("id"), u"غير مصرح")
        b.answer(cq.get("id"))
        p_ = d.split(":")
        k = p_[0]
        if k == "BK":
            cfg, self.restore_pending = self.restore_pending, None
            if p_[1] == "ok" and cfg:
                self.restore_from(cfg)
                return b.send(chat, u"✅ تمت الاستعادة - أعد فتح البلاجين لتظهر الإعدادات")
            return b.send(chat, u"أُلغيت الاستعادة")
        if k == "c":
            act = p_[1]
            if act == "pp":
                self.toggle_pause()
            elif act == "nx":
                self.step(1)
            elif act == "pv":
                self.step(-1)
            elif act == "vu":
                self.vol_change(5)
            elif act == "vd":
                self.vol_change(-5)
            elif act == "st":
                self.stop_play()
            elif act == "ay":
                return b.send(chat, self.tg_ayah_text(self.verse_now()))
            return self.tg_now(chat, msg_id)
        ctx = self.tg_ctx or {}
        if k == "r":
            groups = ctx.get(p_[1])
            if not groups:
                return b.send(chat, u"انتهت صلاحية النتائج - ابحث مرة أخرى")
            g = groups[int(p_[2])]
            if len(g[1]) == 1:
                return self.tg_open_source(chat, g[1][0])
            kb = [[{"text": (u"%s · %s" % (s[0], s[2]))[:60], "callback_data": "s:%s:%s:%d" % (p_[1], p_[2], j)}]
                  for j, s in enumerate(g[1][:20])]
            return b.send(chat, u"🎙 %s - اختر المصدر / الرواية:" % g[0], kb)
        if k == "s":
            groups = ctx.get(p_[1])
            if not groups:
                return b.send(chat, u"انتهت صلاحية النتائج - ابحث مرة أخرى")
            return self.tg_open_source(chat, groups[int(p_[2])][1][int(p_[3])])
        if k == "p":
            return self.tg_surahs(chat, p_[1], int(p_[2]), msg_id)
        if k == "y" or k == "d":
            name, pls = ctx.get(p_[1], (u"", []))
            if not pls:
                return b.send(chat, u"انتهت صلاحية القائمة - ابحث مرة أخرى")
            if k == "d":
                self.download_payloads([x for _l, x in pls])
                return b.send(chat, u"⬇️ بدأ تنزيل %d سورة للقارئ %s بصيغة %s. سأخبرك عند الانتهاء." % (
                    len(pls), name, data.FORMAT_LABEL.get(self.dl_format(), u"")))
            i = int(p_[2])
            self.ctx = None
            self.play_list([x for _l, x in pls], i)
            return b.send(chat, u"▶️ يعمل الآن على التلفزيون: %s" % pls[i][1].get("title", u""), tgbot.CONTROL_KB)
        if k == "R":
            items = ctx.get(p_[1]) or []
            i = int(p_[2])
            if i < len(items) and items[i][1]:
                self.ctx = None
                self.play_list([items[i][1]], 0)
                return b.send(chat, u"📻 يعمل الآن: %s" % items[i][0], tgbot.CONTROL_KB)
        if k == "Rp":
            return self.tg_radios(chat, int(p_[1]), msg_id)
        if k == "M":
            ms = self.cfg.get("marks", [])
            i = int(p_[1])
            if i < len(ms):
                self.mark_play(ms[i])
                return b.send(chat, u"▶️ من العلامة: %s" % ms[i]["name"], tgbot.CONTROL_KB)
        if k == "V":
            self.set_speed(float(p_[1]))
            return b.send(chat, u"⏩ " + (self.status or u""))
        if k == "L":
            groups = ctx.get(p_[1]) or []
            i = int(p_[2])
            if i >= len(groups):
                return
            rec, _folder, items = groups[i]
            fid = self.tg_put((rec, items))
            kb = [[{"text": u"▶️ تشغيل الكل على التلفزيون", "callback_data": "LA:%s" % fid}]]
            kb += [[{"text": (u"▶️ " + lab)[:40], "callback_data": "FP:%s:%d" % (fid, j)},
                    {"text": u"📤", "callback_data": "FS:%s:%d" % (fid, j)}] for j, (_n, lab, _p, _s, _e) in enumerate(items[:40])]
            return b.send(chat, u"📚 %s - %s\n(▶️ تشغيل على التلفزيون • 📤 إرسال الملف إليك)" % (rec, library.summary(items)), kb)
        if k in ("LA", "FP", "FS"):
            rec, items = ctx.get(p_[1], (u"", []))
            if not items:
                return b.send(chat, u"انتهت صلاحية القائمة")
            pls = library.payloads(items, rec)
            if k == "LA":
                self.ctx = None
                self.play_list(pls, 0)
                return b.send(chat, u"▶️ يعمل: %s (%d ملف)" % (rec, len(pls)), tgbot.CONTROL_KB)
            j = int(p_[2])
            if k == "FP":
                self.ctx = None
                self.play_list(pls, j)
                return b.send(chat, u"▶️ يعمل: %s" % pls[j]["title"], tgbot.CONTROL_KB)
            path = items[j][2]
            try:
                b.send(chat, u"📤 جاري إرسال %s ..." % items[j][1])
                b.send_audio(chat, path, pls[j]["title"],
                             done=lambda r, e, c=chat: e and self.bot.send(c, u"تعذّر الإرسال: %s" % e))
            except Exception as e:
                b.send(chat, u"تعذّر الإرسال: %s" % e)



class Hub17Bg(object):
    """1.7: speed without changing the voice, A-B / ayah repeat, bookmarks, 'up next', resume of
    every surah where it was left, disk folders as sources, a channel-list bouquet of the favourites.
    (The playback / TV picture functions themselves are not touched.)"""
    speed_want = 1.0
    speed_busy = False
    ab = None
    ab_timer = None
    upnext = None

    # -- the current item -------------------------------------------------------------------
    def cur_speed(self):
        return float(self.cur_item().get("tempo") or 1.0)

    def orig_pos(self):
        """Position in the original recording (seconds), whatever the speed being played."""
        pp = self.play_pos()
        if not pp:
            return None
        return pp[0] * self.cur_speed()

    # -- speed -----------------------------------------------------------------------------
    def set_speed(self, speed, auto=False):
        speed = float(speed)
        if not Player.active:
            return self.set_status(u"لا يوجد تشغيل")
        if self.cur_live:
            return self.set_status(u"البث المباشر لا يمكن تغيير سرعته")
        item = self.cur_item()
        if not item:
            return
        self.speed_want = speed
        src = localserve.path_of(item.get("tempo_src") or self.cur_url)
        if not src:
            return
        if abs(speed - 1.0) < 0.01:
            if item.get("tempo"):
                pos = self.orig_pos() or 0
                back = dict(item)
                for k in ("tempo", "tempo_src"):
                    back.pop(k, None)
                back["url"] = localserve.url_for(src)
                back["title"] = back.get("title", u"").split(u"  ×")[0]
                self.pl[self.pi] = back
                self.resume_seek = int(pos)
                self.start_item(back)
            return self.set_status(u"السرعة: عادية ×1")
        if not data.which("ffmpeg"):
            return self.set_status(u"تغيير السرعة يحتاج ffmpeg (القائمة > التنزيل > الصيغة > تثبيت ffmpeg)", notify=True)
        dst = library.tempo_path(src, speed)
        if dst is None:
            return self.set_status(u"تغيير السرعة يحتاج HDD أو فلاشة (للملف المؤقت)", notify=True)
        if self.speed_busy:
            return self.set_status(u"جاري تجهيز سرعة أخرى - انتظر قليلاً")
        self.speed_busy = True
        tok = self.tok
        self.set_status(u"جاري تجهيز السرعة ×%s بنفس صوت الشيخ ... (من ثوانٍ إلى دقيقة)" % self._sp(speed), notify=not auto)

        def fetch(url, path):
            resp = data.open_stream(url, 20)
            try:
                with open(path, "wb") as f:
                    while True:
                        c = resp.read(65536)
                        if not c:
                            break
                        f.write(c)
            finally:
                resp.close()

        def done(res):
            self.speed_busy = False
            if isinstance(res, Exception):
                qlog("tempo: %r" % (res,))
                return self.set_status(u"تعذّر تغيير السرعة: %s" % res, notify=True)
            if tok != self.tok or not Player.active:
                return                           # the user moved to something else meanwhile
            pos = self.orig_pos() or 0
            it = dict(self.cur_item())
            for k in ("resolve", "qdc", "timing"):
                it.pop(k, None)
            it.update({"url": localserve.url_for(res), "tempo": speed, "tempo_src": src,
                       "title": it.get("title", u"").split(u"  ×")[0] + u"  ×%s" % self._sp(speed)})
            self.pl[self.pi] = it
            self.resume_seek = int(pos / speed)
            self.start_item(it)
            self.set_status(u"السرعة ×%s" % self._sp(speed))
        self.runner.run(lambda: library.tempo_make(src, speed, dst, fetch), done, done)

    @staticmethod
    def _sp(s):
        return (u"%.2f" % s).rstrip(u"0").rstrip(u".")

    def speed_tick(self):
        """Keep the chosen speed for the next surahs of the list."""
        if (abs(self.speed_want - 1.0) > 0.01 and Player.active and not self.cur_live and not self.speed_busy
                and self.play_ok and not self.cur_item().get("tempo") and self.t0 and time.time() - self.t0 > 3):
            self.set_speed(self.speed_want, auto=True)

    # -- A-B repeat / ayah repeat -------------------------------------------------------------
    def ab_set(self, a, b, times=0):
        """Repeat the part a..b (seconds of the playing file); times 0 = until cancelled."""
        self.ab = {"a": float(a), "b": float(b), "left": int(times) - 1 if times else -1}
        if self.ab_timer is None:
            self.ab_timer, self._c17 = make_timer(self.ab_tick)
        self.ab_timer.start(300, False)

    def ab_clear(self, msg=True):
        self.ab = None
        if self.ab_timer is not None:
            self.ab_timer.stop()
        if msg:
            self.set_status(u"انتهى تكرار المقطع")

    def ab_tick(self):
        ab = self.ab
        if not ab or not Player.active:
            return self.ab_clear(False)
        pp = self.play_pos()
        if not pp:
            return
        if pp[0] >= ab["b"] or pp[0] < ab["a"] - 5:
            if ab["left"] == 0:
                return self.ab_clear()
            if ab["left"] > 0:
                ab["left"] -= 1
            self.seek(ab["a"] - pp[0])

    def ab_key(self):
        """First press: A.  Second press: B (repeat starts).  Third press: stop repeating."""
        pp = self.play_pos()
        if not Player.active or self.cur_live or not pp:
            return self.set_status(u"التكرار يعمل مع السور (ليس البث المباشر)")
        if self.ab:
            return self.ab_clear()
        a = getattr(self, "ab_a", None)
        if a is None or pp[0] <= a + 1:
            self.ab_a = pp[0]
            return self.set_status(u"بداية المقطع (A) عند %s - اضغط مرة أخرى عند النهاية" % self._mmss(int(pp[0])))
        self.ab_a = None
        self.ab_set(a, pp[0], 0)
        self.seek(a - pp[0])
        self.set_status(u"يتكرر المقطع %s ← %s (اضغط مرة ثالثة للإيقاف)" % (self._mmss(int(a)), self._mmss(int(pp[0]))))

    def ayah_bounds(self, n, a):
        """(start, end) in seconds of an ayah in the playing file, from an exact timing."""
        item = self.cur_item()
        if item.get("tempo"):
            return None
        if item.get("qdc"):
            tl = self.qdc_timing(item)
            for aa, t0, t1, _s in tl or []:
                if aa == a:
                    return t0 / 1000.0, t1 / 1000.0
            return None
        tl, _m = self.timing_for(n)
        if tl and self.sync_exact:
            for aa, s, e in tl:
                if aa == a:
                    return s / 1000.0, e / 1000.0
        return None

    def repeat_ayah(self, times):
        cur = self.verse_now()
        b = self.ayah_bounds(*cur) if cur else None
        if not b:
            return self.set_status(u"تكرار الآية يحتاج تلاوة بتوقيت دقيق (قراء quran.com و mp3quran) - استعمل A-B", notify=True)
        self.ab_set(b[0], b[1] + 0.3, times)
        pp = self.play_pos()
        if pp:
            self.seek(b[0] - pp[0])
        self.set_status(u"تكرار الآية %d: %d مرات" % (cur[1], times))

    # -- bookmarks ---------------------------------------------------------------------------
    def mark_add(self, name=None):
        if not Player.active or self.cur_live:
            return self.set_status(u"العلامات للسور فقط (ليس البث المباشر)")
        item = self.cur_item()
        pos = int(self.orig_pos() or 0)
        title = (Player.cur_title or u"").split(u"  ×")[0]
        m = {"name": name or u"%s  @ %s" % (title, self._mmss(pos)), "title": title,
             "url": localserve.path_of(item.get("tempo_src") or self.cur_url), "pos": pos, "n": item.get("n"), "ts": int(time.time())}
        marks = [x for x in self.cfg.get("marks", []) if not (x["url"] == m["url"] and abs(x["pos"] - pos) < 5)]
        self.cfg["marks"] = ([m] + marks)[:50]
        self.save()
        self.set_status(u"🔖 حُفظت علامة: %s" % m["name"], notify=True)
        return m

    def mark_play(self, m):
        self.ctx = None
        self.resume_seek = int(m.get("pos", 0))
        item = {"title": m["title"], "url": localserve.url_for(m["url"]), "autonext": False, "nohist": False}
        if m.get("n"):
            item["n"] = m["n"]
        self.play_list([item], 0)

    # -- up next -------------------------------------------------------------------------------
    def upnext_add(self, payload):
        if self.upnext is None:
            self.upnext = []
        self.upnext.append(dict(payload))
        self.set_status(u"➕ أُضيف إلى «التالي» (%d في الانتظار)" % len(self.upnext))

    # -- every surah continues where it was left ---------------------------------------------------
    def spos_save(self):
        try:
            item = self.cur_item()
            if (not Player.active or self.cur_live or item.get("tempo") or item.get("ayah") or
                    item.get("stop_at_end") or not Player.cur_title):
                return
            pp = self.play_pos()
            if not pp or pp[1] < 120:
                return
            sp = self.cfg.setdefault("spos", {})
            key = Player.cur_title
            if pp[0] > pp[1] - 25 or pp[0] < 20:
                sp.pop(key, None)
            else:
                sp[key] = [int(pp[0]), int(pp[1]), int(time.time())]
            if len(sp) > 150:
                for k, _v in sorted(sp.items(), key=lambda kv: kv[1][2])[:len(sp) - 150]:
                    del sp[k]
        except Exception as e:
            qlog("spos: %r" % (e,))

    def spos_apply(self, item):
        if not self.cfg.get("auto_resume", True) or self.resume_seek or not item:
            return
        if item.get("live") or item.get("ayah") or item.get("stop_at_end") or item.get("tempo"):
            return
        v = (self.cfg.get("spos") or {}).get(item.get("title"))
        if v and v[0] > 20:
            self.resume_seek = int(v[0])
            self.set_status(u"متابعة من حيث توقفت: %s" % self._mmss(int(v[0])))

    # -- favourites as a bouquet in the channel list ---------------------------------------------
    def fav_bouquet(self, done):
        favs = [tuple(f) for f in self.cfg.get("fav", [])]

        def run():
            rows, unstable = [], []
            entries = fav_loader(favs)() if favs else []
            mp3q = None
            for name, entry in entries:
                if not entry_has_subs(entry):
                    u = entry.get("url")
                    if u:
                        rows.append((name, u))
                    else:
                        unstable.append(name)
                    continue
                subs = subs_for(entry)
                first, got = [], 0
                for lab, x in subs:
                    if x is None:
                        if first:
                            break
                        continue
                    first.append((lab, x))
                direct = [(lab, x) for lab, x in first if x.get("url")]
                if not direct:                       # links made on demand: use the same reciter on mp3quran
                    if mp3q is None:
                        try:
                            mp3q = SEC_CACHE.get("mp3q_reciters") or section_loader("mp3q_reciters")()
                        except Exception:
                            mp3q = []
                    k = reciter_key(name)
                    alt = next((e for lab, e in mp3q if reciter_key(lab) == k or k in reciter_key(lab)), None)
                    if alt is not None:
                        direct = []
                        for lab, x in subs_for(alt):
                            if x is None:
                                if direct:
                                    break          # first moshaf only
                                continue
                            if x.get("url"):
                                direct.append((lab, x))
                if not direct:
                    unstable.append(name)
                    continue
                rows.append((name, u""))
                for lab, x in direct:
                    t = x.get("title") or u"%s - %s" % (name, lab)
                    rows.append((t, x["url"]))
                    got += 1
            n = studio.build_bouquet(rows, name=u"القرآن الكريم - المفضلة", bq_file=studio.FAV_BQ_FILE)
            return n, unstable
        self.runner.run(run, done, done)



BUILD = 20             # one number for both editions (the "what's new" screen and the changelog)
CHANGELOG = [
    (20, [u"تحديث آمن: فحص الحزمة قبل التثبيت، والرجوع للإصدار السابق تلقائياً إذا لم يعمل الجديد",
          u"مكان التلاوة يُحفظ كل 10 ثوانٍ، والمتابعة بعد انقطاع الكهرباء (اختياري)",
          u"ما تسمعه يُحفظ على القرص ويعمل بدون إنترنت، والسورة التالية تُجهّز أثناء الاستماع",
          u"رسم المصحف كاملاً مسبقاً، وتحديث القوائم ليلاً، والقرص يستيقظ قبل الأذان والمواعيد",
          u"نسخة يومية للإعدادات (7 أيام + 4 أسابيع)، وتنبيه قبل امتلاء القرص",
          u"«إذاعتي الخاصة» كقناة في قائمة الراديو، ومكتبتك لتلفزيونات وجوالات البيت (DLNA)",
          u"ملف شخصي كامل لكل فرد، ونجوم للأطفال، وحصاد الشهر والسنة"]),
    (19, [u"كل ملفات البلاجين على الـHDD: الذاكرة المؤقتة، الحروف المرسومة، السجل، الملفات المؤقتة",
          u"نسخة من الإعدادات على الـHDD تُحفظ مع كل تغيير، وترجع وحدها بعد تثبيت صورة جديدة",
          u"ذاكرة الجهاز (RAM) أخف، والمصحف أسرع بعد إعادة التشغيل لأن الأسطر المرسومة محفوظة"]),
    (18, [u"وضع رمضان: تنبيه قبل الإفطار والسحور، جزء كل ليلة بقارئ تختاره، وتذكير بليالي العشر الأواخر",
          u"تذكير بالمناسبات الهجرية: عرفة، العيدان، عاشوراء، الأيام البيض، بداية رمضان",
          u"ورد الحفظ أو المراجعة يصلك على تليجرام كل يوم بالصوت والنص",
          u"نسخة احتياطية أسبوعية على تليجرام، واستعادتها بإرسال الملف للبوت",
          u"إذاعتي الخاصة: مكتبتك بلا توقف على الريسيفر، وبرابط لأي جهاز في البيت",
          u"مؤقت النوم يخفض الصوت تدريجياً ثم يدخل الجهاز وضع الانتظار",
          u"الوضع المبسّط لكبار السن، والواجهة بالإنجليزية (القائمة > المظهر > اللغة)",
          u"مصدر التحديث الرسمي (feed) وهذه الشاشة بعد كل تحديث"]),
    (17, [u"مكتبة الـHDD كمصدر، والمشغّل الكبير: السرعة، التكرار، العلامات، «التالي»، باقة المفضلة"]),
    (16, [u"البحث عن قارئ في كل المواقع، التنزيل بأي صيغة، مكتبتي، بوت تليجرام"]),
]
FEED_CONF = "/etc/opkg/saadquranhub-feed.conf"
FEED_URL = "https://raw.githubusercontent.com/%s/main/feed" % GITHUB_REPO
ERRBUF = []
_ERR_WORDS = ("Error", "Exception", "error:", "failed", "Traceback", "errno")


def note_error(line):
    if any(w in line for w in _ERR_WORDS):
        ERRBUF.append(u"%s %s" % (time.strftime("%H:%M:%S"), line))
        del ERRBUF[:-40]


def whats_new_text(since=0):
    out = []
    for b, lines in CHANGELOG:
        if b > since:
            out += [u"•  " + l for l in lines]
    return out


class Hub18Bg(object):
    """1.8: Ramadan + hijri occasions, the daily passage / weekly backup / error reports on Telegram,
    'my station', sleep fade-out, update feed."""
    t18 = 0
    fade = None
    station = None
    err_sent = 0
    restore_pending = None

    def tick18(self):
        now = time.time()
        if now - self.t18 < 20:
            return
        self.t18 = now
        try:
            self.fade_tick(now)
        except Exception as e:
            qlog("fade: %r" % (e,))
        lt = time.localtime(now)
        hm = "%02d:%02d" % (lt.tm_hour, lt.tm_min)
        today = time.strftime("%Y-%m-%d", lt)
        fired = self.cfg.setdefault("fired18", {})

        def once(key):
            if fired.get(key) == today:
                return False
            fired[key] = today
            self.save()
            return True
        try:
            self.ramadan_tick(now, hm, once)
        except Exception as e:
            qlog("ramadan: %r" % (e,))
        try:
            if self.cfg.get("occasions", True) and hm >= "20:00" and once("occasion"):
                occ = studio.occasion_for(now + 86400, studio.hijri_adjust(self.cfg))
                if occ:
                    msg = u"🌙 غداً بإذن الله: %s" % occ
                    popup(msg, 12)
                    self.tg_notify(msg)
        except Exception as e:
            qlog("occasion: %r" % (e,))
        if self.bot is not None:
            try:
                if self.cfg.get("tg_wird_time") and hm >= self.cfg["tg_wird_time"] and once("tg_wird"):
                    for o in self.tg_owners():
                        self.tg_wird(o["id"])
                if self.cfg.get("tg_backup", True) and lt.tm_wday == 4 and hm >= "10:00" and once("tg_backup"):
                    for o in self.tg_owners():
                        self.tg_backup(o["id"])
                if (self.cfg.get("tg_errors", private_edition()) and ERRBUF and now - self.err_sent > 1800):
                    self.err_sent = now
                    lines, ERRBUF[:] = list(ERRBUF), []
                    self.tg_notify(u"⚠️ أخطاء البلاجين (%s):\n%s" % (PLUGIN_VERSION, u"\n".join(lines[-15:])[:3500]))
            except Exception as e:
                qlog("tg18: %r" % (e,))

    # -- sleep: fade out, then standby ----------------------------------------------------------
    def fade_tick(self, now):
        if self.sleep_at and Player.active:
            left = self.sleep_at - now
            if left <= 300:
                if self.fade is None:
                    v = self.get_volume()
                    if v is None:
                        return
                    self.fade = {"v0": v}
                target = int(self.fade["v0"] * max(0.0, left) / 300.0)
                v = self.get_volume()
                if v is not None and abs(v - target) >= 2:
                    self.set_volume(max(0, target))
            return
        if self.fade is not None and not Player.active:          # the sleep timer has stopped the Quran
            v0 = self.fade["v0"]
            self.fade = None
            self.set_volume(v0)
            if self.cfg.get("sleep_standby", True):
                try:
                    from Screens.Standby import Standby, inStandby
                    if not inStandby:
                        from Tools import Notifications
                        Notifications.AddNotification(Standby)
                except Exception as e:
                    qlog("standby: %r" % (e,))
        elif self.fade is not None and not self.sleep_at:        # timer cancelled
            self.set_volume(self.fade["v0"])
            self.fade = None

    # -- Ramadan -------------------------------------------------------------------------------
    def ramadan_on(self, ts=None):
        mode = self.cfg.get("ramadan", "auto")
        if mode == "off":
            return 0
        return studio.ramadan_today(self.cfg, ts)

    def ramadan_tick(self, now, hm, once):
        d = self.ramadan_on(now)
        city = self.cfg.get("prayer_city")
        if not d or not city:
            return
        pt = extras.today_prayers(city, now)
        if not pt:
            return
        mins = lambda h: (int(h) * 60 + int(round((h - int(h)) * 60)))
        cur = time.localtime(now).tm_hour * 60 + time.localtime(now).tm_min
        mg, fj, isha = mins(pt["maghrib"]), mins(pt["fajr"]), mins(pt["isha"])
        if 0 <= mg - cur <= 15 and once("iftar"):
            msg = u"🌙 باقي %d دقيقة على أذان المغرب (الإفطار) - رمضان %d" % (mg - cur, d)
            popup(msg, 15)
            self.tg_notify(msg)
        if 0 <= fj - cur <= 30 and once("suhoor"):
            msg = u"🌙 باقي %d دقيقة على أذان الفجر (الإمساك)" % (fj - cur)
            popup(msg, 15)
            self.tg_notify(msg)
        if cur >= isha + 20 and once("juz"):
            juz = min(30, d)
            if d + 1 in (21, 23, 25, 27, 29):
                note = u"\nالليلة ليلة %d من رمضان (من ليالي العشر الأواخر)" % (d + 1)
            else:
                note = u""
            self.tg_notify(u"📖 جزء الليلة: الجزء %d%s" % (juz, note))
            self.ramadan_ask(juz, note)

    def ramadan_ask(self, juz, note=u""):
        text = u"ختمة رمضان: حان وقت الجزء %d.%s\n\nتشغيله الآن؟" % (juz, note)

        def answer(ok=None):
            if ok:
                self.play_juz(juz)
        try:
            from Tools import Notifications
            from Screens.MessageBox import MessageBox
            Notifications.AddNotificationWithCallback(answer, MessageBox, text, MessageBox.TYPE_YESNO, timeout=120)
        except Exception:
            popup(text, 15)

    def play_juz(self, juz):
        items = studio.juz_items(juz, int(self.cfg.get("ramadan_rec", 0)))
        if items:
            self.ctx = None
            self.play_list(items, 0)
            self.set_status(u"ختمة رمضان: الجزء %d (%d آية)" % (juz, len(items)), notify=True)

    # -- Telegram: daily passage, weekly backup, restore ----------------------------------------------
    def tg_wird(self, chat):
        n, a1, a2, why = studio.wird_passage(self.cfg)
        verses = dict(extras.local_verses(n) or [])
        a2 = min(a2, a1 + 9)
        text = u"📖 %s: سورة %s من آية %d إلى %d\n\n%s" % (
            why, data.surah_name(n), a1, a2,
            u"\n".join(u"﴿%s﴾ (%d)" % (extras.sanitize(verses.get(a, u"")), a) for a in range(a1, a2 + 1)))
        self.bot.send(chat, text)
        rec = studio.hifz_state(self.cfg)["rec"]
        urls = [studio.ayah_url(n, a, rec) for a in range(a1, a2 + 1)]
        self.bot.send_media_group(chat, urls, u"%s - سورة %s (%d-%d)" % (studio.HIFZ_RECITERS[rec][0], data.surah_name(n), a1, a2))

    def tg_backup(self, chat):
        path = data.tmp_path("saadquranhub_backup.json")
        cfg = dict(self.cfg)
        for k in ("tg_token", "tg_owners", "remote_pin"):
            cfg.pop(k, None)                       # never inside a file that leaves the receiver
        with open(path, "wb") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=1).encode("utf-8"))
        self.bot.send_document(chat, path, u"💾 نسخة احتياطية من إعدادات Saad Quran Hub (%s)\n"
                                           u"للاستعادة على أي جهاز: أرسل هذا الملف للبوت." % time.strftime("%Y-%m-%d"))

    def tg_restore_file(self, chat, doc):
        name = (doc.get("file_name") or u"").lower()
        if not name.endswith(".json"):
            return self.bot.send(chat, u"أرسل ملف النسخة الاحتياطية (json) لاستعادته")
        b = self.bot

        def job():
            raw = b.download(doc["file_id"])
            cfg = json.loads(raw.decode("utf-8"))
            if not isinstance(cfg, dict) or not any(k in cfg for k in ("fav", "hist", "theme", "pls", "reader_pos")):
                raise ValueError(u"ليس ملف نسخة احتياطية من Saad Quran Hub")
            return cfg

        def done(res):
            if isinstance(res, Exception):
                return b.send(chat, u"تعذّر قراءة الملف: %s" % res)
            self.restore_pending = res
            b.send(chat, u"♻️ وجدت نسخة احتياطية فيها %d إعداداً (المفضلة: %d). استعادتها على هذا الريسيفر؟" % (
                len(res), len(res.get("fav") or [])), [[{"text": u"♻️ نعم، استعادة", "callback_data": "BK:ok"},
                                                       {"text": u"إلغاء", "callback_data": "BK:no"}]])
        Runner().run(job, done, done)

    def restore_from(self, cfg):
        keep = dict((k, self.cfg.get(k)) for k in ("tg_token", "tg_owners", "remote_pin") if k in self.cfg)
        self.cfg.update(cfg)
        self.cfg.update(keep)
        self.save()

    # -- my station ----------------------------------------------------------------------------
    def station_files(self):
        out = []
        try:
            for _rec, _f, items in library.scan():
                out += [x[2] for x in items]
        except Exception:
            pass
        for d in self.cfg.get("disk_srcs", []):
            try:
                for _n, folder in library.disk_reciters(d["path"]):
                    out += [p_ for _n2, _l, p_ in library.disk_tracks(folder)]
            except Exception:
                continue
        return out

    def station_items(self, rec=None, shuffle=True):
        import random
        items = []
        try:
            groups = library.scan()
        except Exception:
            groups = []
        for d in self.cfg.get("disk_srcs", []):
            try:
                for name, folder in library.disk_reciters(d["path"]):
                    its = [(n, l, p_, 0, os.path.splitext(p_)[1]) for n, l, p_ in library.disk_tracks(folder)]
                    groups.append((name.split(u" - ")[-1], folder, its))
            except Exception:
                continue
        for r, _f, its in groups:
            if rec is None or r == rec:
                items += library.payloads(its, r)
        if shuffle:
            random.shuffle(items)
        for it in items:
            it["autonext"] = True
        return items, [g[0] for g in groups]

    def station_play(self, rec=None, shuffle=True):
        items, _recs = self.station_items(rec, shuffle)
        if not items:
            return self.set_status(u"المكتبة فارغة - نزّل قارئاً أو أضف مجلداً من القرص", notify=True)
        self.ctx = None
        self.play_list(items, 0)
        self.set_status(u"📻 إذاعتي الخاصة: %d ملف%s" % (len(items), u" (عشوائي)" if shuffle else u""), notify=True)

    def station_url(self):
        """Start the home stream (once) and give its address."""
        if not self.cfg.get("remote_pin"):
            import random
            self.cfg["remote_pin"] = "%04d" % random.randint(0, 9999)
            self.save()
        if self.station is None:
            try:
                self.station = localserve.HomeRadio(self.station_files, self.cfg["remote_pin"])
            except Exception as e:
                qlog("station: %r" % (e,))
                return None
        return u"http://%s:%d/radio/%s.mp3" % (remote.local_ip(), localserve.HomeRadio.PORT, self.cfg["remote_pin"])

    # -- update feed -----------------------------------------------------------------------------
    def feed_add(self):
        try:
            with open(FEED_CONF, "w") as f:
                f.write("src/gz saadquranhub %s\n" % FEED_URL)
            self.set_status(u"أُضيف مصدر التحديث الرسمي - التحديثات تصل من «تحديث البرامج» في الجهاز", notify=True)
            return True
        except Exception as e:
            self.set_status(u"تعذّرت إضافة المصدر: %s" % e, notify=True)
            return False

AUDIO = hddcache.AudioCache()


def _write_small(path, obj):
    """Tiny state files: write + rename (no fsync, so a sleeping disk never blocks the screen)."""
    try:
        tmp = path + ".new"
        with open(tmp, "wb") as f:
            f.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        os.rename(tmp, path)
        return True
    except Exception:
        return False


def _bg_thread(fn, *a):
    t = threading.Thread(target=fn, args=a)
    t.daemon = True
    t.start()
    return t


class Hub19Bg(object):
    """2.0: stability (position journal, resume after power cuts, HDD wake-up, disk watch, rotating
    backups), speed (kept audio, next track fetched ahead, pre-drawn mushaf, nightly list refresh),
    the station as a channel, DLNA, stars and the harvest."""
    t19 = 0
    j19 = 0
    jplaying = False
    wake_min = None
    dlna = None
    mpre = None
    kids_run = None
    boot_checked = False

    def init19(self):
        try:
            AUDIO.enabled = self.cfg.get("audio_cache", True)
            AUDIO.quota = int(float(self.cfg.get("audio_quota", 20)) * 1024 ** 3)
        except Exception:
            pass
        st = self.state_load()
        if st and st.get("url") and st.get("ts", 0) > self.cfg.get("resume_ts", 0):
            self.cfg["resume"] = dict((k, st[k]) for k in ("title", "url", "pos", "ctx") if k in st)
            self.cfg["resume_ts"] = st["ts"]

    # -- the URL that is really played: a kept copy when there is one ------------------------------
    def cache_swap(self, url, title=u"", live=False):
        try:
            if live or not AUDIO.cacheable(url):
                return url
            loc = AUDIO.local_for(url)
            if loc:
                return loc
            if self.cfg.get("audio_cache", True):
                AUDIO.want(url, title)
        except Exception as e:
            qlog("audio cache: %r" % (e,))
        return url

    def real_url(self, url):
        try:
            return AUDIO.remote_for(url)
        except Exception:
            return url

    def cache_next(self):
        """Fetch the next track of the list while this one plays."""
        try:
            if not self.cfg.get("audio_cache", True) or not self.pl or len(self.pl) < 2:
                return
            nxt = self.pl[(self.pi + 1) % len(self.pl)]
            u = nxt.get("url") or (nxt.get("_pre") or (None,))[0]
            if u and not nxt.get("live"):
                AUDIO.want(u, nxt.get("title", u""))
        except Exception as e:
            qlog("cache next: %r" % (e,))

    # -- 10-second journal of what plays (survives power cuts) ---------------------------------------
    def state_path(self):
        d = data.home_dir("system")
        return os.path.join(d, "state.json") if d else None

    def state_load(self):
        p = self.state_path()
        try:
            with open(p, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
        except Exception:
            return None

    def journal_tick(self, now):
        p = self.state_path()
        if not p:
            return
        playing = bool(Player.active and self.cur_url and not self.cur_live and self.adhan_prev is None)
        if playing and now - self.j19 >= 10:
            self.j19 = now
            pp = self.play_pos()
            st = {"title": Player.cur_title, "url": self.real_url(self.cur_url), "pos": int(pp[0]) if pp else 0,
                  "ctx": self.ctx or {}, "playing": True, "ts": int(now)}
            _write_small(p, st)
            self.jplaying = True
        elif not Player.active and self.jplaying:
            self.jplaying = False
            st = self.state_load() or {}
            st.update({"playing": False, "ts": int(now)})
            _write_small(p, st)

    def boot_resume(self):
        """After a power cut / restart: continue what was playing (only when switched on)."""
        st = self.state_load()
        if not st or not st.get("playing") or time.time() - st.get("ts", 0) > 12 * 3600 or Player.active:
            return
        self.cfg["resume"] = dict((k, st[k]) for k in ("title", "url", "pos", "ctx") if k in st)
        self.save()
        popup(u"متابعة التلاوة بعد إعادة التشغيل:\n%s" % (st.get("title") or u""), 6)
        self.resume_last()

    # -- the main 20-second tick ---------------------------------------------------------------------
    def tick19(self):
        now = time.time()
        try:
            self.journal_tick(now)
        except Exception as e:
            qlog("journal: %r" % (e,))
        if now - self.t19 < 20:
            return
        self.t19 = now
        lt = time.localtime(now)
        today = time.strftime("%Y-%m-%d", lt)
        fired = self.cfg.setdefault("fired19", {})

        def once(key):
            if fired.get(key) == today:
                return False
            fired[key] = today
            self.save()
            return True
        for name, fn in (("wake", lambda: self.wake_tick(now)), ("kids", self.kids_tick),
                         ("next", self.cache_next), ("mpre", lambda: self.mpre_tick(lt))):
            try:
                fn()
            except Exception as e:
                qlog("tick19 %s: %r" % (name, e))
        if not self.boot_checked and now - self.boot > 40:
            self.boot_checked = True
            try:
                note = safeupdate.rolled_back_note()
                if note:
                    msg = u"⚠️ الإصدار %s لم يعمل، فرجع البلاجين وحده إلى %s" % note
                    popup(msg, 15)
                    self.tg_notify(msg)
                safeupdate.clear_pending()          # this version started fine
            except Exception as e:
                qlog("update check: %r" % (e,))
            if self.cfg.get("boot_resume", False) and now - self.boot < 600:
                self.boot_resume()
        try:
            if lt.tm_hour in (3, 4) and once("night19"):
                _bg_thread(self.night_job)
            if lt.tm_hour >= 9 and once("disk19"):
                self.disk_watch()
            if lt.tm_hour in (2, 3, 4, 5, 13, 14) and not Player.active and once("rot19"):
                self.backup_rotate()
            if lt.tm_mday == 1 and lt.tm_hour >= 10 and once("harvest19"):
                prev = now - 2 * 86400
                txt = studio.harvest_text(self.cfg, "month", prev)
                self.tg_notify(txt)
        except Exception as e:
            qlog("daily19: %r" % (e,))

    # -- wake the disk before what is scheduled ---------------------------------------------------------
    def upcoming(self, now):
        """'HH:MM' of the things that will play soon (schedules, adhan, reminders)."""
        lt = time.localtime(now)
        out = set()
        for s in self.cfg.get("sched", []):
            if s.get("on", True) and (not s.get("days") or lt.tm_wday in s["days"]):
                out.add(s.get("hm"))
        for k in ("wird_time", "kahf_time", "mulk_time", "tg_ayah_time", "tg_wird_time"):
            if self.cfg.get(k):
                out.add(self.cfg[k])
        city = self.cfg.get("prayer_city")
        if city and (self.cfg.get("prayer_mode", "notify") != "off" or self.cfg.get("fajr_wake")):
            pt = extras.today_prayers(city, now) or {}
            for key in ("fajr", "dhuhr", "asr", "maghrib", "isha"):
                if key in pt:
                    m = int(round(pt[key] * 60))
                    out.add("%02d:%02d" % ((m // 60) % 24, m % 60))
        return out

    def wake_tick(self, now):
        if not self.cfg.get("hdd_wake", True):
            return
        soon = time.localtime(now + 60)
        hm = "%02d:%02d" % (soon.tm_hour, soon.tm_min)
        if hm == self.wake_min or hm not in self.upcoming(now):
            return
        self.wake_min = hm
        _bg_thread(self.wake_disk)

    def wake_disk(self):
        d = data.home_dir("system")
        if not d:
            return False
        try:
            with open(os.path.join(d, ".wake"), "w") as f:
                f.write(str(time.time()))
                f.flush()
                os.fsync(f.fileno())          # this is what spins a sleeping disk up
            return True
        except Exception:
            return False

    # -- disk watch, cleaning, backups ----------------------------------------------------------------
    def disk_watch(self):
        d = data.home_dir()
        if not d:
            return
        free = data.disk_free(d)
        if free is not None and free < 1024 ** 3:
            msg = u"⚠️ مساحة القرص قليلة: باقي %s فقط\nاحذف ملفات من «مكتبتي» أو قلّل حجم «ما سمعته سابقاً»" % data.fmt_bytes(free)
            popup(msg, 12)
            self.tg_notify(msg)
        _bg_thread(self.clean_old)

    def clean_old(self, days=30):
        """Lists, pictures and temp files not used for a month (the audio and the drawn text have
        their own limits)."""
        removed = 0
        now = time.time()
        for sub in ("cache", "tmp"):
            d = data.home_dir(sub)
            if not d:
                continue
            for f in os.listdir(d):
                path = os.path.join(d, f)
                if os.path.isfile(path) and not f.startswith(("timing_", "qcom_seg_")) and \
                        now - os.path.getmtime(path) > days * 86400:
                    try:
                        os.remove(path)
                        removed += 1
                    except OSError:
                        pass
        try:
            AUDIO.trim()
        except Exception:
            pass
        return removed

    def backup_dir19(self):
        return data.home_dir("backups")

    def backup_rotate(self, now=None):
        """A copy every day: the last 7 days and one for each of the last 4 weeks stay."""
        d = self.backup_dir19()
        if not d:
            return None
        now = now or time.time()
        name = "settings_%s.json" % time.strftime("%Y-%m-%d", time.localtime(now))
        path = os.path.join(d, name)
        cfg = dict(self.cfg)
        cfg.pop("tg_token", None)
        _write_small(path, cfg)
        files = sorted(f for f in os.listdir(d) if f.startswith("settings_") and f.endswith(".json"))
        keep, weeks = set(files[-7:]), {}
        for f in files:
            try:
                t = time.mktime(time.strptime(f[9:19], "%Y-%m-%d"))
            except ValueError:
                continue
            wk = time.strftime("%Y-%W", time.localtime(t))
            weeks[wk] = f                       # the last copy of each week
        keep |= set(sorted(weeks.values())[-4:])
        for f in files:
            if f not in keep:
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
        return path

    def backups19(self):
        d = self.backup_dir19()
        if not d:
            return []
        return [(f[9:19], os.path.join(d, f)) for f in sorted(os.listdir(d), reverse=True)
                if f.startswith("settings_") and f.endswith(".json")]

    def restore19(self, path):
        with open(path, "rb") as f:
            cfg = json.loads(f.read().decode("utf-8"))
        keep = dict((k, self.cfg.get(k)) for k in ("tg_token", "tg_owners", "remote_pin") if k in self.cfg)
        self.cfg.clear()
        self.cfg.update(cfg)
        self.cfg.update(keep)
        self.save()

    # -- night: refresh the lists, timings of what you listen to -----------------------------------------
    def night_job(self):
        data.REFRESH.on = True
        try:
            for key in ("mp3q_reciters", "mp3q_radios", "qcom", "sq_reciters", "sq_radios", "sync", "tvq"):
                try:
                    rows = section_loader(key)()
                    SEC_CACHE[key] = rows
                except Exception as e:
                    qlog("night refresh %s: %r" % (key, e))
                time.sleep(2)
        finally:
            data.REFRESH.on = False
        for rid in list(self.cfg.get("timing_used", []))[-3:]:     # the timed reciters you listen to
            for n in range(1, 115):
                try:
                    data.ayat_timing(int(rid), n)
                except Exception:
                    pass
                time.sleep(0.5)
        try:
            self.clean_old()
        except Exception:
            pass

    # -- the whole mushaf drawn ahead (when the box sleeps, or late at night) ----------------------------
    def mpre_sig(self):
        return u"%s|%s|%s|%s" % (self.cfg.get("mushaf_style", "paper"), self.theme_idx(),
                                 self.cfg.get("reader_font", 1), self.cfg.get("tajweed", True))

    def mpre_tick(self, lt):
        if not self.cfg.get("mushaf_pre", True) or not img_text() or not data.home_dir() or self.mpre is not None:
            return
        st = self.cfg.get("mpre") or {}
        if st.get("sig") == self.mpre_sig() and st.get("page", 0) >= 604:
            return
        try:
            from Screens.Standby import inStandby
        except Exception:
            inStandby = None
        if not (inStandby or (lt.tm_hour in (1, 2, 3, 4, 5) and self.ui is None)):
            return
        if st.get("sig") != self.mpre_sig():
            st = {"sig": self.mpre_sig(), "page": 0}
            self.cfg["mpre"] = st
        self.mpre = {"g": mushaf_ghost(), "q": [], "page": st["page"]}
        self.mpre["timer"], self.mpre["c"] = make_timer(self.mpre_step)
        self.mpre["timer"].start(150, False)

    def mpre_step(self):
        m = self.mpre
        if m is None:
            return
        try:
            from Screens.Standby import inStandby
        except Exception:
            inStandby = None
        lt = time.localtime()
        if not (inStandby or (lt.tm_hour in (1, 2, 3, 4, 5) and self.ui is None)) or self.cfg.get("mpre", {}).get("sig") != self.mpre_sig():
            m["timer"].stop()
            self.mpre = None
            return
        if not m["q"]:
            if m["page"] >= 604:
                m["timer"].stop()
                self.mpre = None
                self.cfg["mpre"]["page"] = 604
                self.save()
                return
            m["page"] += 1
            m["q"] = mushaf_page_jobs(m["g"], m["page"])
            if m["page"] % 10 == 0:
                self.cfg["mpre"]["page"] = m["page"] - 1
                self.save()
            return
        args = m["q"].pop(0)
        try:
            qtext.render(*args)
        except Exception as e:
            qlog("mushaf pre: %r" % (e,))

    # -- DLNA -------------------------------------------------------------------------------------------
    def dlna_groups(self):
        groups = []
        try:
            for rec, _f, items in library.scan():
                groups.append((rec, [(lab, path) for _n, lab, path, _s, _e in items]))
        except Exception:
            pass
        for d in self.cfg.get("disk_srcs", []):
            try:
                for name, folder in library.disk_reciters(d["path"]):
                    groups.append((name, [(lab, p_) for _n, lab, p_ in library.disk_tracks(folder)]))
            except Exception:
                continue
        try:
            ents = AUDIO.entries()
            if ents:
                groups.append((u"ما سمعته سابقاً", [(t, localserve.path_of(u)) for t, u, _s in ents]))
        except Exception:
            pass
        return groups

    def dlna_set(self, on):
        if on and self.dlna is None:
            try:
                self.dlna = dlna.Server(self.dlna_groups, u"Saad Quran Hub (%s)" % remote.local_ip())
            except Exception as e:
                qlog("dlna: %r" % (e,))
                return False
        elif not on and self.dlna is not None:
            self.dlna.close()
            self.dlna = None
        return True

    # -- the station as a channel in the channel list ----------------------------------------------------
    STATION_BQ = "userbouquet.saadquranhub_station.radio"

    def station_bouquet(self, on=True):
        if not on:
            studio.remove_bouquet(bq_file=self.STATION_BQ)
            self.cfg["station_bq"] = False
            self.save()
            reload_bouquets()
            return 0
        url = self.station_url()
        if not url:
            raise ValueError(u"تعذّر تشغيل الإذاعة")
        local = u"http://127.0.0.1:%d/radio/%s.mp3" % (localserve.HomeRadio.PORT, self.cfg["remote_pin"])
        n = studio.build_bouquet([(u"📻 إذاعتي الخاصة - مكتبتي", local)], name=u"إذاعتي الخاصة", bq_file=self.STATION_BQ)
        self.cfg["station_bq"] = True
        self.save()
        reload_bouquets()
        return n

    # -- children's stars --------------------------------------------------------------------------------
    def kids_tick(self):
        k = self.kids_run
        if not k:
            return
        if Player.active and self.pl is k["pl"]:
            k["max"] = max(k["max"], self.pi + 1)
            return
        self.kids_run = None
        if k["max"] >= max(1, int(len(k["pl"]) * 0.9)):
            n = studio.star_add(self.cfg, u"سورة %s في وضع الأطفال" % data.surah_name(k["n"]))
            self.save()
            msg = u"⭐ أحسنت! نجمة جديدة (المجموع %d)" % n
            popup(msg, 6)
            self.tg_notify(u"%s: %s" % (self.cfg.get("profile") or u"", msg))


def mushaf_ghost():
    """A mushaf screen that is never shown: it cuts the pages exactly like the real one."""
    g = QHMushaf.__new__(QHMushaf)
    th = g.page_theme(THEMES[BG.theme_idx()])
    g.qh_th = th
    g.qh_bgc = "#101418" if th["bg"] == "transparent" else th["bg"]
    g.qh_fi = min(len(g.FONTS) - 1, max(0, int(BG.cfg.get("reader_font", 1))))
    g.qh_fs = g.FONTS[g.qh_fi]
    g.qh_rowh, g.qh_rows = g.geometry(g.qh_fs)
    g.qh_hl, g.qh_hl_roles, g.qh_pg = None, None, 0
    g.qh_pages = [[(u"", set(), False)]]
    return g


def mushaf_page_jobs(g, page):
    """-> [qtext.render arguments] of every line of one mushaf page (as QHMushaf draws it)."""
    blocks, _refs = studio.page_blocks(page)
    g.qh_pg = 0
    g.paginate(blocks, flow=True)
    jobs = []
    for k in range(len(g.qh_pages)):
        g.qh_pg = k
        for text, fg, _back, cols, _al, just in g.line_specs(g.qh_pages[k], True):
            if text.strip():
                jobs.append((text, g.img_px(), fg, p(g.qh_rowh), cols, just))
    return jobs


def reload_bouquets():
    try:
        from enigma import eDVBDB
        eDVBDB.getInstance().reloadBouquets()
    except Exception as e:
        qlog("bouquet reload: %r" % (e,))


class Background(Hub16Bg, Hub17Bg, Hub18Bg, Hub19Bg):
    """Everything that must survive closing/minimising the screen."""

    def __init__(self):
        self.session = None
        self.ui = None              # the open QuranHub screen, if any
        self.cfg = data.load_settings()
        Player.engine = 5002 if self.cfg.get("engine") == 5002 else 4097
        self.pl, self.pi = [], -1
        self.status = u""
        self.tok = 0
        self.t0 = None
        self.rec = None
        self.sleep_at = None
        self.sleep_min = 0
        self.qinfo = None
        self.rx_base = self.rx_prev = None
        self.rx_hist, self.rate = [], 0.0
        self.tv_on = False
        self.tv_want = False
        self.tv_ref = None
        self.tv_attempt = self.tv_restarts = self.tv_refresh_in = self.tv_tick = 0
        self.tv_err, self.tv_geo = u"", u""
        self.tv_autohide = False
        self.tv_timer = self.re_timer = None
        self._c3 = self._c4 = None
        self.re_times, self.reconnects, self.stall = [], 0, 0
        # overlay mode (TV channel keeps running, Quran plays on a second player)
        self.overlay_active = False
        self.overlay_failed = False
        self.ts_failed = False
        self.play_ok = False
        self.out = None
        self.tv_muted = False
        self.tv_track = 0
        self.mute_chk = 0.0
        self.mute_timer = None
        self._c5 = None
        # time-shift / seek
        self.proxy = None
        self.live_buf = None
        self.delay = 0
        self.paused_at = None
        self.cur_live = False
        self.cur_url = None
        self.mini = None
        self.hooked = False
        self.runner = None
        self.timer = None
        self._c = None

    # -- setup --------------------------------------------------------------
    def attach(self, session):
        self.session = session
        i18n.LANG[0] = self.cfg.get("lang", "ar")
        if not self.hooked:
            try:
                session.nav.event.append(self.on_event)
                self.hooked = True
            except Exception:
                pass
        if self.runner is None:
            self.runner = Runner()
        if self.timer is None:
            self.timer, self._c = make_timer(self.tick)
        if self.tv_timer is None:
            self.tv_timer, self._c3 = make_timer(self._tv_try)
        if self.re_timer is None:
            self.re_timer, self._c4 = make_timer(self.do_reconnect)
        if self.mute_timer is None:
            self.mute_timer, self._c5 = make_timer(self.mute_tv)
        if self.out is None:
            self.out = AudioOut(self.on_audio_event)
        Player.restore_hook = self.follow_restore
        self.install_zap_hook()
        if self.gap_timer is None:
            self.gap_timer, self._c6 = make_timer(self.gap_done)
        if not self.standby_hooked:
            self.standby_hooked = True
            try:
                from Components.config import config
                config.misc.standbyCounter.addNotifier(self.on_standby, initial_call=False)
            except Exception as e:
                qlog("standby hook: %s" % e)
        if not self.extras_ready:
            self.init_extras()
            self.ensure_timer()
        try:
            self.init16()
        except Exception as e:
            qlog("init16: %r" % (e,))
        if not getattr(self, "ready19", False):
            self.ready19 = True
            try:
                self.init19()
                extras.URL_FIX[0] = AUDIO.remote_for          # history keeps the internet address
                if self.cfg.get("dlna"):
                    self.dlna_set(True)
                if self.cfg.get("station_bq"):
                    self.station_url()                          # the channel needs the stream running
            except Exception as e:
                qlog("init19: %r" % (e,))

    gap_timer = None
    _c6 = None
    standby_hooked = False

    def on_standby(self, *a):
        if Player.active or self.tv_want:
            qlog("standby -> stop")
            self.stop_all()

    def gap_done(self):
        if Player.active or self.gap_pending:
            self.gap_pending = False
            self.step(1)

    gap_pending = False

    def save(self):
        data.save_settings(self.cfg)

    def ensure_timer(self):
        if self.timer is not None and not self.timer.isActive():
            self.timer.start(1000, False)

    # -- status / labels ----------------------------------------------------------
    def set_status(self, text, notify=False):
        self.status = text
        if self.ui is not None:
            self.ui.qh_status_text(text)
        elif notify:
            popup(text)

    def now_text(self):
        if not Player.active or not Player.cur_title:
            return u""
        t = u"▶ %s" % Player.cur_title
        if self.t0:
            sec = int(time.time() - self.t0)
            t += u"  %02d:%02d" % (sec // 60, sec % 60)
        return t

    def rec_text(self):
        parts = []
        r = self.rec
        if r is not None:
            if r.stage == "converting":
                parts.append(u"⚙ تحويل إلى %s ..." % data.FORMAT_LABEL.get(r.fmt, r.fmt))
            elif r.stopping:
                parts.append(u"⚙ إنهاء ...")
            else:
                tag = u"" if r.fmt == "original" else u" " + data.FORMAT_LABEL.get(r.fmt, r.fmt)
                parts.append(u"● REC %.1f MB%s" % (r.bytes / 1048576.0, tag))
        if self.sleep_at:
            left = max(0, int((self.sleep_at - time.time()) / 60.0 + 0.99))
            parts.append(u"⏾ %d د" % left)
        if self.extras_ready and self.dl.busy():
            parts.append(self.dl_text())
        return u"  ".join(parts)

    def net_text(self):
        if not Player.active:
            return u""
        parts = []
        if self.rx_base is not None and self.rx_prev is not None:
            parts.append(u"⬇ %s" % data.fmt_bytes(self.rx_prev - self.rx_base))
            if self.rate:
                parts.append(u"%d kbps فعلي" % round(self.rate))
        q = data.quality_text(self.qinfo, self.rate)
        if q:
            parts.append(q)
        return u"  •  ".join(parts)

    def card_net(self):
        if not Player.active or self.rx_base is None or self.rx_prev is None:
            return u"⬇ —"
        t = u"⬇ %s" % data.fmt_bytes(self.rx_prev - self.rx_base)
        if self.rate:
            t += u"\n%d kbps فعلي" % round(self.rate)
        return t

    def card_quality(self):
        if not Player.active:
            return u"♪ —"
        return data.quality_text(self.qinfo, self.rate).replace(u" • ", u"\n", 1) or u"♪ ..."

    def progress(self):
        """-> (percent 0..100, text) for the now-playing card."""
        if not Player.active:
            return 0, u""
        if self.live_buf is not None:
            if self.delay <= 0:
                return 100, u"LIVE"
            avail = max(self.live_buf.available(), self.delay + 1.0)
            return int(100 * (1 - self.delay / avail)), u"-%s" % self._mmss(self.delay)
        pos = None
        try:
            if Player.sink is not None and self.out is not None:
                pos = self.out.position()
            else:
                sk = self.session.nav.getCurrentService().seek()
                ln, ps = sk.getLength(), sk.getPlayPosition()
                if not ln[0] and not ps[0] and ln[1] > 0:
                    pos = (ps[1] / 90000.0, ln[1] / 90000.0)
        except Exception:
            pos = None
        if pos:
            return int(100 * min(1.0, pos[0] / pos[1])), u"%s / %s" % (self._mmss(pos[0]), self._mmss(pos[1]))
        return 100, u""

    @staticmethod
    def _mmss(sec):
        sec = int(max(0, sec))
        return u"%02d:%02d" % (sec // 60, sec % 60) if sec < 3600 else u"%d:%02d:%02d" % (
            sec // 3600, sec % 3600 // 60, sec % 60)

    def stability(self):
        recent = [t for t in self.re_times if time.time() - t < 120]
        if not Player.active:
            return u""
        if recent:
            return u"غير مستقر"
        if self.paused_at:
            return u"متوقف مؤقتًا"
        return u"مستقر"

    def minibar_text(self):
        if not Player.active or not Player.cur_title:
            return u""
        t = u"▶ %s" % Player.cur_title
        if self.rx_base is not None and self.rx_prev is not None:
            t += u"  |  ⬇ %s" % data.fmt_bytes(self.rx_prev - self.rx_base)
            if self.rate:
                t += u" (%d kbps)" % round(self.rate)
        if self.live_buf is not None and self.delay > 0:
            t += u"  |  -%s" % self._mmss(self.delay)
        return t + u"  -  " + self.stability()

    def sample_net(self):
        rx = data.read_rx()
        if rx is None:
            return
        if self.rx_base is None:
            self.rx_base = rx
        if self.rx_prev is not None:
            self.rx_hist = (self.rx_hist + [max(0, rx - self.rx_prev)])[-5:]
            self.rate = sum(self.rx_hist) * 8 / 1000.0 / len(self.rx_hist)
        self.rx_prev = rx

    def reset_net(self):
        self.rx_base = self.rx_prev = None
        self.rx_hist, self.rate, self.qinfo = [], 0.0, None

    def fmt_label(self):
        return u"الصيغة (2): %s" % data.FORMAT_LABEL.get(self.cfg.get("fmt"), u"الأصلي")

    def sleep_label(self):
        m = self.cfg_sleep_minutes()
        return u"مؤقت النوم (7): %s" % (u"%d د" % m if m else u"إيقاف")

    def cfg_sleep_minutes(self):
        return getattr(self, "sleep_min", 0) if self.sleep_at else 0

    # -- playback --------------------------------------------------------------
    def play_list(self, pl, pi, ctx=None):
        try:
            self.spos_apply(pl[pi])
        except Exception:
            pass
        self.pl, self.pi = pl, pi
        if ctx is not None:
            self.ctx = ctx
        if self.ctx is not None:
            self.ctx["idx"] = pi
        self.start_item(pl[pi])

    cur_nohist = False
    cur_video = False
    video_screen = None

    def open_video(self):
        """Bring the video to the front (from the library screen, which is the current modal screen)."""
        if self.video_screen is not None or self.ui is None:
            return
        try:
            if getattr(self.session, "current_dialog", self.ui) is not self.ui:
                return
            self.session.open(QHVideo)
        except Exception as e:
            qlog("video screen: %s" % e)

    def start_item(self, item):
        title = item.get("title", u"")
        self.cur_nohist = bool(item.get("nohist"))
        vid = bool(item.get("video"))
        if vid and not self.cur_video and Player.active:
            self.stop_play()                        # a video needs the main screen: leave PiP / overlay first
        self.cur_video = vid
        self.tok += 1
        self.alt_tried = None
        live = bool(item.get("live"))
        if item.get("url"):
            return self.start_play(item["url"], title, live)
        self.set_status(u"جاري تجهيز: %s" % title)
        tok = self.tok
        self.runner.run(item["resolve"],
                        lambda r, t=title, k=tok, lv=live: self.resolved(r, t, k, lv),
                        lambda e, k=tok: self.resolve_failed(e, k))

    def clean_audio(self, path):
        """ffmpeg: noise reduction (afftdn) + loudness levelling; writes '<name>_نقي.mp3' next to it."""
        src = path[7:] if path.startswith("file://") else path
        base, _ext = os.path.splitext(src)
        dst = base + u"_نقي.mp3"
        self.set_status(u"جاري تنقية الصوت ... (قد يستغرق دقائق)", notify=True)

        def job():
            import subprocess
            dn = open(os.devnull, "wb")
            rc = subprocess.call([data.which("ffmpeg"), "-y", "-i", src, "-af",
                                  "highpass=f=70,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5", "-b:a", "128k", dst],
                                 stdout=dn, stderr=dn)
            if rc != 0 or not os.path.exists(dst):
                raise ValueError(u"فشل ffmpeg (%s)" % rc)
            return dst

        def done(r):
            if isinstance(r, Exception):
                self.set_status(u"تعذّرت التنقية: %s" % r, notify=True)
            else:
                self.set_status(u"تم: %s" % os.path.basename(r), notify=True)
        self.runner.run(job, done, done)

    def prefetch_next(self):
        """Resolve the next item's link now, so the next track starts at once."""
        try:
            if not self.pl or len(self.pl) < 2:
                return
            nxt = self.pl[(self.pi + 1) % len(self.pl)]
            if nxt.get("url") or not nxt.get("resolve") or nxt.get("_pre"):
                return

            def done(r, it=nxt):
                if not isinstance(r, Exception) and r:
                    it["_pre"] = (r, time.time())
            self.runner.run(nxt["resolve"], done, lambda e: None)
        except Exception as e:
            qlog("prefetch: %s" % e)

    def resolve_failed(self, exc, tok):
        if tok == self.tok:
            self.set_status(u"تعذّر التشغيل: %s" % exc)

    def resolved(self, result, title, tok, live=False):
        if tok != self.tok:
            return
        if isinstance(result, Exception):
            return self.resolve_failed(result, tok)
        self.start_play(self.cache_swap(result, title, live), title, live)

    # -- output mode ----------------------------------------------------------------------
    def main_has_tv(self):
        try:
            return self.session.nav.getCurrentlyPlayingServiceReference() is not None
        except Exception:
            return False

    TV_MODES = [("auto", u"تلقائي (الأنسب لجهازك)"),
                ("pip", u"القرآن + صورة القناة كاملة (الأثبت)"),
                ("overlay", u"القرآن بمشغّل ثانٍ فوق القناة"),
                ("off", u"إيقاف (الصوت يحل محل القناة)")]
    follow = False          # Quran on the main service + the TV channel in a full-screen PiP
    pip_failed = False
    _orig_play = None

    def tv_mode(self):
        m = self.cfg.get("tv_mode")
        if m not in dict(self.TV_MODES):
            m = "auto"
        return m

    def tv_strategy(self):
        """-> 'pip' | 'overlay' | 'off'  (what will really be used on this box)."""
        m = self.tv_mode()
        pip_ok = self.pip_available() and not self.pip_failed
        ov_any = self.out is not None and not self.overlay_failed
        ov_ok = ov_any and not self.cfg.get("overlay_bad")
        if m == "off":
            return "off"
        if m == "pip":
            return "pip" if pip_ok else ("overlay" if ov_ok else "off")
        if m == "overlay":
            return "overlay" if ov_any else ("pip" if pip_ok else "off")
        return "pip" if pip_ok else ("overlay" if ov_ok else "off")

    def overlay_wanted(self):
        if self.tv_want or self.follow or not self.main_has_tv():
            return False
        return self.tv_strategy() == "overlay"

    # -- follow mode: the Quran keeps playing while you zap; the channel is shown in a PiP --------
    @staticmethod
    def is_tv_ref(ref):
        try:
            if ref is None:
                return False
            mask = getattr(eServiceReference, "isDirectory", 7) | getattr(eServiceReference, "isMarker", 64)
            if ref.flags & mask:
                return False
            return ref.type == 1                      # idDVB: a satellite / cable / terrestrial channel
        except Exception:
            return False

    def install_zap_hook(self):
        """Wrap session.nav.playService: while the Quran plays, a channel change (CH+/-, numbers,
        channel list, EPG zap ...) goes to the full-screen PiP instead of stopping the Quran."""
        nav = getattr(self.session, "nav", None)
        if nav is None or getattr(nav, "_qh_hooked", False):
            return
        orig = nav.playService
        self._orig_play = orig

        def hooked(ref, *a, **kw):
            try:
                if BG.zap_intercept(ref):
                    return 0
            except Exception as e:
                qlog("zap hook: %s" % e)
            return orig(ref, *a, **kw)
        try:
            nav.playService = hooked
            nav._qh_hooked = True
        except Exception as e:
            qlog("zap hook install: %s" % e)

    def raw_play(self, ref):
        (self._orig_play or self.session.nav.playService)(ref)

    def zap_intercept(self, ref):
        if Player.restoring or not Player.active or Player.sink is not None or self.cur_video:
            return False
        if not self.cfg.get("follow", True) or not self.is_tv_ref(ref):
            return False
        if self.tv_strategy() != "pip":
            return False
        try:
            from Screens.Standby import inStandby
            if inStandby:
                return False
        except Exception:
            pass
        name = self.ref_name(ref)
        pip = getattr(self.session, "pip", None)
        if self.follow and self.tv_on and pip is not None:
            ok = False
            try:
                ok = bool(pip.playService(ref))
            except Exception as e:
                qlog("pip zap: %s" % e)
            if ok:
                self.tv_ref = ref
                self.remember_tv(ref)
                self.tv_apply_geometry()
                popup(u"%s  •  القرآن مستمر" % name, 3)
                return True
        qlog("zap -> follow %s" % name)
        self.follow_begin(ref, 300)
        popup(u"%s  •  القرآن مستمر (الصورة في نافذة كاملة)" % name, 4)
        return True

    def ref_name(self, ref):
        try:
            from enigma import eServiceCenter
            info = eServiceCenter.getInstance().info(ref)
            return (info.getName(ref) or u"").replace(u"\xc2\x86", u"").replace(u"\xc2\x87", u"")
        except Exception:
            return u"القناة"

    def remember_tv(self, ref):
        try:
            self.cfg["tv"] = ref.toString()
            self.save()
        except Exception:
            pass

    def follow_begin(self, ref, delay=1500):
        self.follow = True
        self.tv_ref = ref
        self.tv_want = True
        self.tv_attempt = self.tv_restarts = 0
        self.remember_tv(ref)
        self.install_zap_hook()
        self.ensure_timer()
        self.tv_timer.start(delay, True)       # let the main decoder switch to the Quran first
        self.set_status(u"القرآن يعمل - صورة القناة كاملة، غيّر القنوات بحرية")

    def follow_restore(self):
        """Called by Player.stop: close the PiP, return the channel to put back on the main service."""
        if not (self.follow or self.tv_want or self.tv_on):
            return None
        ref = self.tv_ref
        self.tv_stop()
        self.follow = False
        return ref

    def follow_fallback(self):
        """PiP does not work on this box: channel back on the main service, Quran on the second player."""
        ref = self.tv_ref
        qlog("follow fallback (PiP failed) -> overlay")
        self.pip_failed = True
        self.follow = False
        self.tv_want = False
        self.tv_autohide = False
        self._tv_close_dialog()
        self.tv_on = False
        url, title, live = self.cur_url, Player.cur_title, self.cur_live
        Player.stop(self.session, restore=False)
        if ref is not None:
            try:
                Player.restoring = True
                self.raw_play(ref)
            finally:
                Player.restoring = False
        if url:
            self.start_play(url, title or u"", live)
        self.set_status(u"صورة PiP لم تعمل على جهازك - تحويل تلقائي إلى (المشغّل الثاني فوق القناة)", notify=True)

    def live_url(self, url, live):
        """Route live radios through the local time-shift buffer (rewind / pause)."""
        if not (live and self.cfg.get("timeshift", True)) or self.ts_failed or ".m3u8" in url.lower():
            self.drop_buffer()
            return url
        try:
            if self.proxy is None:
                self.proxy = timeshift.TimeshiftProxy()
            if self.live_buf is None or self.cur_url != url:
                self.live_buf = self.proxy.add("live", lambda u=url: data.open_stream(u, 15))
                self.delay = 0
                self.paused_at = None
            return self.proxy.url("live", self.delay)
        except Exception as e:
            qlog("timeshift unavailable: %s" % e)
            self.drop_buffer()
            return url

    def ts_fallback(self):
        """The local time-shift route did not start in time -> play the stream directly."""
        qlog("timeshift route did not start - direct playback")
        self.ts_failed = True
        self.drop_buffer()
        url = self.cur_url
        if url and Player.active:
            self._output(url, Player.cur_title, url)
            self.t0 = time.time()
            self.set_status(u"ذاكرة الرجوع غير متاحة هنا - تشغيل مباشر")

    def drop_buffer(self):
        if self.proxy is not None and self.live_buf is not None:
            try:
                self.live_buf.stop()
                self.proxy.buffers.pop("live", None)
            except Exception:
                pass
        self.live_buf = None
        self.delay = 0
        self.paused_at = None

    def start_play(self, url, title, live=False):
        was_active = Player.active
        follow_ref = None
        if not was_active:                                   # decide the output mode once per listening session
            if self.cur_video:
                self.follow = False
                self.overlay_active = False
                if self.tv_want or self.tv_on:
                    self.tv_stop()
            elif self.follow and self.tv_want:
                self.overlay_active = False                  # keep the picture we already show
            else:
                self.follow = False
                self.overlay_active = self.overlay_wanted()
                if not self.overlay_active and self.cfg.get("follow", True) and self.tv_strategy() == "pip":
                    try:
                        cur = self.session.nav.getCurrentlyPlayingServiceReference()
                    except Exception:
                        cur = None
                    if self.is_tv_ref(cur):
                        follow_ref = cur
        eng_url = self.live_url(url, live)
        self.cur_live = live
        self.cur_url = url
        try:
            if self.adhan_prev is None and not self.cur_nohist:
                extras.history_add(self.cfg, title, url, live)
            self.save()
        except Exception as e:
            qlog("history: %s" % e)
        fresh = self._output(url, title, eng_url)
        if follow_ref is not None and Player.started:
            self.follow_begin(follow_ref)
        if fresh and Player.saved_ref is not None:           # the channel being watched -> "last channel"
            try:
                self.cfg["tv"] = Player.saved_ref.toString()
                self.save()
            except Exception:
                pass
        self.t0 = time.time()
        self.stall = 0
        self.play_ok = False
        self.qinfo = None
        if self.rx_base is None:
            self.sample_net()
        tok = self.tok
        self.runner.run(lambda u=url: data.probe_stream(u),
                        lambda r, k=tok: self.probed(r, k),
                        lambda e: None)
        mode = u" + القناة" if self.overlay_active else u""
        self.set_status(u"جاري الاتصال بالبث ... (%s%s)" % (Player.engine_name(), mode))
        self.ensure_timer()
        self.show_minibar()
        if self.ui is not None:
            self.ui.qh_labels()

    def _output(self, url, title, eng_url):
        """Start the audio on the right output; falls back to the main service."""
        sink = self.out if self.overlay_active else None
        if sink is not None:
            self.mute_failed = False
            self.mute_tv(True)                       # silence the channel BEFORE our audio starts
            self.ov_check_at = time.time() + 6
        fresh = Player.play(self.session, url, title, eng_url, sink)
        if sink is not None:
            if Player.started:
                self.mute_tv()
                self.mute_timer.start(1500, True)            # once more after the channel settled
            else:
                self.overlay_fallback(u"تعذّر تشغيل الصوت المنفصل (%s)" % (self.out.err or u"?"))
        return fresh

    def overlay_fallback(self, why):
        qlog("overlay fallback: %s" % why)
        self.overlay_failed = True
        self.overlay_active = False
        self.unmute_tv()
        title = Player.cur_title
        Player.stop(self.session, restore=False)
        Player.active = False
        url = self.cur_url
        if url:
            self.set_status(why + u" - التشغيل على القناة الرئيسية", notify=True)
            Player.play(self.session, url, title, None, None)

    def restart_current(self):
        """Replay the current item (mode / engine / time-shift changed)."""
        if Player.active and self.pl and 0 <= self.pi < len(self.pl) and self.cur_url:
            item = self.pl[self.pi]
            title = Player.cur_title or item.get("title", u"")
            url = self.cur_url
            keep = self.follow or self.tv_want
            Player.stop(self.session, restore=not keep)
            self.unmute_tv()
            self.overlay_active = False if keep else self.overlay_wanted()
            self.start_play(url, title, self.cur_live)

    # -- muting the TV channel -----------------------------------------------------------------
    def _tv_tracks(self):
        try:
            svc = self.session.nav.getCurrentService()
            return svc.audioTracks() if svc is not None else None
        except Exception:
            return None

    def mute_tv(self, force=False):
        """Silence the channel's own audio (picture stays). Re-applied after zapping."""
        if not (self.overlay_active and (Player.active or force)):
            return False
        at = self._tv_tracks()
        if at is None:
            return False
        try:
            cur = at.getCurrentTrack()
            if cur != -1:
                self.tv_track = cur
                at.selectTrack(-1)
                now = at.getCurrentTrack()
                self.tv_muted = (now == -1)
                if not self.tv_muted:
                    self.mute_failed = True
                    qlog("mute_tv: selectTrack(-1) had no effect (track=%s)" % now)
                    self.set_status(u"تعذّر كتم صوت القناة على هذا الجهاز - سيُسمع الصوتان (جرّب وضع PiP)",
                                    notify=True)
            else:
                self.tv_muted = True
            return self.tv_muted
        except Exception as e:
            self.mute_failed = True
            qlog("mute_tv failed: %s" % e)
            return False

    def unmute_tv(self):
        if not self.tv_muted:
            return
        at = self._tv_tracks()
        self.tv_muted = False
        if at is None:
            return
        try:
            at.selectTrack(self.tv_track if self.tv_track >= 0 else 0)
        except Exception as e:
            qlog("unmute_tv failed: %s" % e)

    def overlay_nav_event(self, ev):
        """TV events while overlay is active: re-mute after zapping."""
        if ev in PLAY_OK_EVENTS or ev == getattr(iPlayableService, "evStart", -1):
            now = time.time()
            if now - self.mute_chk > 1.0:
                self.mute_chk = now
                at = self._tv_tracks()
                try:
                    if at is not None and at.getCurrentTrack() != -1:
                        self.tv_muted = False
                        self.mute_timer.start(800, True)
                except Exception:
                    pass

    def probed(self, result, tok):
        if tok == self.tok and not isinstance(result, Exception):
            self.qinfo = result
            if self.ui is not None:
                self.ui.qh_labels()

    def step(self, delta):
        if not self.pl:
            return
        self.pi = (self.pi + delta) % len(self.pl)
        item = self.pl[self.pi]
        if self.ctx is not None:
            self.ctx["idx"] = self.pi
        if self.ui is not None:
            self.ui.qh_highlight(item)
        self.start_item(item)

    def is_ours(self):
        """True when what is playing now is the stream we started (so a failure
        on a TV channel the user zapped to never restarts our audio)."""
        if not Player.active:
            return False
        if Player.sink is not None:
            return True
        try:
            ref = self.session.nav.getCurrentlyPlayingServiceReference()
            return ref is not None and ref.getPath() == Player.eng_url
        except Exception:
            return True

    def on_event(self, ev):                 # nav events (main service)
        if not Player.active:
            return
        if self.overlay_active:
            return self.overlay_nav_event(ev)
        self.play_event(ev)

    def on_audio_event(self, ev):           # events of the second player
        if Player.active and self.overlay_active:
            self.play_event(ev)

    def play_event(self, ev):
        if ev == iPlayableService.evEOF:
            if not self.is_ours() and Player.sink is None:
                return
            if self.adhan_prev is not None:
                return self.adhan_done()
            if self.pl and 0 <= self.pi < len(self.pl) and self.pl[self.pi].get("stop_at_end"):
                self.set_status(u"انتهى ورد الحفظ - جعله الله في ميزان حسناتك", notify=True)
                return self.stop_play()
            if self.upnext:
                nxt = self.upnext.pop(0)
                self.ctx = None
                return self.play_list([nxt], 0)
            if self.pl and self.pl[self.pi].get("autonext") and len(self.pl) > 1:
                gap = int(self.pl[self.pi].get("gap") or 0)
                if gap > 0 and self.gap_timer is not None:
                    self.gap_pending = True
                    self.set_status(u"ردّد الآية ... (%d ث)" % gap)
                    return self.gap_timer.start(gap * 1000, True)
                self.step(1)
            elif self.is_live():
                self.reconnect(u"انقطع البث")
        elif ev == iPlayableService.evTuneFailed:
            if Player.sink is None and not self.is_ours():
                return
            qlog("tune failed engine=%s url=%s" % (Player.engine_name(), Player.eng_url))
            if Player.fail(self.session):
                self.set_status(u"فشل المشغّل - تجربة مشغّل آخر ...")
            elif self.overlay_active:
                self.overlay_fallback(u"تعذّر تشغيل الصوت المنفصل")
            elif self.is_live():
                self.reconnect(u"تعذّر تشغيل البث")
            elif self.adhan_prev is not None:
                self.adhan_done(u"(تعذّر تشغيل صوت الأذان)")
            elif not self.try_alt_source(u"فشل تشغيل الرابط"):
                self.set_status(u"تعذّر تشغيل هذا الرابط (جرّب MENU أو التسجيل)")
        elif ev in PLAY_OK_EVENTS:
            if self.is_ours():
                if self.cur_video and not self.play_ok:
                    self.open_video()
                self.play_ok = True
                self.set_status(u"يتم التشغيل (%s)" % Player.engine_name())
                if self.tv_on:
                    self.tv_refresh_in = 1      # keep the picture on top after audio (re)starts

    # -- automatic fallback source ----------------------------------------------------------
    alt_tried = None

    def try_alt_source(self, why):
        """A surah that will not play: switch (once) to the same reciter on another site."""
        try:
            if self.cur_live or not (self.pl and 0 <= self.pi < len(self.pl)):
                return False
            item = self.pl[self.pi]
            n = item.get("n")
            if not n or self.alt_tried is not None or not self.cfg.get("alt_source", True):
                return False
            title = Player.cur_title or item.get("title", u"")
            url, kw = data.alt_surah_url(title.split(u" - ")[0], int(n))
            if url == self.cur_url:
                return False
            self.alt_tried = url
            qlog("alt source (%s): %s" % (why, url))
            self.set_status(u"%s - تحويل تلقائي إلى مصدر بديل%s" % (
                why, u" (نفس القارئ)" if kw else u" (قارئ بديل: العفاسي)"), notify=True)
            self.start_play(url, title, False)
            return True
        except Exception as e:
            qlog("alt source error: %s" % e)
            return False

    # -- keep live radios alive -----------------------------------------------------------
    def is_live(self):
        return bool(self.cur_live) and Player.active

    def reconnect(self, why):
        now = time.time()
        self.re_times = [t for t in self.re_times if now - t < 300]
        if len(self.re_times) >= 6:
            return self.set_status(u"%s - توقفت إعادة المحاولة (6 مرات خلال 5 دقائق)" % why, notify=True)
        self.re_times.append(now)
        self.reconnects += 1
        qlog("reconnect #%d: %s" % (self.reconnects, why))
        self.set_status(u"%s - إعادة الاتصال (%d) ..." % (why, self.reconnects))
        self.re_timer.start(2500, True)

    def do_reconnect(self):
        if Player.active and Player.cur_url and not self.paused_at:
            self._output(Player.cur_url, Player.cur_title, self.live_url(Player.cur_url, self.cur_live))
            self.stall = 0

    # -- rewind / forward / pause / back to live ------------------------------------------------
    def seek(self, secs):
        """secs < 0 rewinds, secs > 0 goes forward (towards live)."""
        if not Player.active:
            return
        if self.live_buf is not None:
            avail = int(self.live_buf.available())
            new = int(max(0, min(self.delay - secs, max(0, avail - 3))))
            if secs < 0 and avail < 5:
                return self.set_status(u"لا توجد ذاكرة كافية بعد للرجوع (انتظر قليلاً)")
            self.delay = new
            self._live_restart()
            return self.set_status(u"البث المباشر" if new == 0 else
                                   u"متأخر %s عن البث المباشر (▶▶ للتقدّم)" % self._mmss(new))
        if self.cur_live and self.live_buf is None:
            return self.set_status(u"الرجوع للخلف في الإذاعات يحتاج «ذاكرة الرجوع» (MENU) أو لم تتوفر هنا")
        ok = False
        if Player.sink is not None and self.out is not None:
            ok = self.out.seek_rel(secs)
        else:
            try:
                sk = self.session.nav.getCurrentService().seek()
                sk.seekRelative(1 if secs >= 0 else -1, int(abs(secs) * 90000))
                ok = True
            except Exception:
                ok = False
        self.set_status((u"تقديم %d ث" if secs >= 0 else u"إرجاع %d ث") % abs(secs) if ok
                        else u"الرجوع للخلف غير متاح لهذا المقطع/المشغّل")

    def go_live(self):
        if self.live_buf is not None and self.delay:
            self.delay = 0
            self._live_restart()
            self.set_status(u"العودة إلى البث المباشر")

    def _live_restart(self):
        if Player.active and self.cur_url:
            self._output(self.cur_url, Player.cur_title, self.live_url(self.cur_url, True))
            if self.ui is not None:
                self.ui.qh_labels()

    def toggle_pause(self):
        if not Player.active:
            return
        if self.live_buf is not None:
            if self.paused_at is None:                       # pause: remember where we were
                self.paused_at = time.time()
                Player.halt_output(self.session)
                self.set_status(u"إيقاف مؤقت (البث يُحفظ - اضغط تشغيل للمتابعة)")
            else:                                            # resume: continue from the pause point
                self.delay += int(time.time() - self.paused_at)
                self.paused_at = None
                self.delay = min(self.delay, max(0, int(self.live_buf.available()) - 3))
                self._live_restart()
                self.set_status(u"متابعة (متأخر %s عن المباشر)" % self._mmss(self.delay))
            return
        ok = False
        flag = not getattr(self, "_paused_file", False)
        if Player.sink is not None and self.out is not None:
            ok = self.out.pause(flag)
        else:
            try:
                ps = self.session.nav.getCurrentService().pause()
                ps.pause() if flag else ps.unpause()
                ok = True
            except Exception:
                ok = False
        if ok:
            self._paused_file = flag
            self.set_status(u"إيقاف مؤقت" if flag else u"متابعة التشغيل")
        else:
            self.set_status(u"الإيقاف المؤقت غير متاح هنا")

    def stop_play(self):
        try:
            self.save_resume()
        except Exception:
            pass
        self.cur_video = False
        Player.stop(self.session)
        self.unmute_tv()
        self.overlay_active = False
        self.drop_buffer()
        self._paused_file = False
        self.hide_minibar()
        self.t0 = None
        self.cur_url = None
        self.reset_net()
        self.tok += 1
        self.set_status(u"تم الإيقاف")
        if self.ui is not None:
            self.ui.qh_labels()

    def stop_all(self):
        """Stop audio, recording and the sleep timer."""
        self.sleep_at = None
        self.sleep_min = 0
        if self.rec is not None and self.rec.stage == "recording":
            self.rec.stop()
        self.pl, self.pi = [], -1
        self.tv_stop()
        self.stop_play()
        self.ensure_timer()

    def toggle_engine(self):
        eng = Player.toggle_engine(self.session)
        self.cfg["engine"] = eng
        self.save()
        self.restart_current()
        self.set_status(u"المشغّل: %s" % Player.engine_name())

    def toggle_flag(self, key, default, label):
        self.cfg[key] = not self.cfg.get(key, default)
        self.save()
        self.set_status(u"%s: %s" % (label, u"مفعّل" if self.cfg[key] else u"معطّل"))
        return self.cfg[key]

    def cycle_tv_mode(self):
        order = [m for m, _ in self.TV_MODES]
        nxt = order[(order.index(self.tv_mode()) + 1) % len(order)]
        self.cfg["tv_mode"] = nxt
        self.cfg["overlay_bad"] = False
        self.overlay_failed = False
        self.pip_failed = False
        self.save()
        self.set_status(u"وضع القناة مع القرآن: %s" % dict(self.TV_MODES)[nxt])
        if Player.active:
            self.restart_current()
        return nxt

    def toggle_overlay(self):
        return self.cycle_tv_mode()

    def toggle_timeshift(self):
        self.toggle_flag("timeshift", True, u"ذاكرة الرجوع للخلف للإذاعات")
        if Player.active and self.cur_live:
            self.restart_current()

    def toggle_minibar(self):
        self.toggle_flag("minibar", True, u"الشريط المصغّر")
        self.show_minibar()

    # -- floating mini bar (visible while the plugin is minimised) -----------------------------
    def show_minibar(self):
        if not (self.cfg.get("minibar", True) and Player.active):
            return self.hide_minibar()
        try:
            if self.mini is None:
                self.mini = self.session.instantiateDialog(QHMiniBar, self)
            self.mini.show()
            try:
                self.mini.execBegin()               # enable its remote-control ActionMap
            except Exception:
                pass
            self.mini.refresh(self.minibar_text())
        except Exception as e:
            qlog("minibar: %s" % e)
            self.mini = None

    def hide_minibar(self):
        if self.mini is not None:
            try:
                self.mini.hide()
                self.mini.execEnd()
            except Exception:
                pass

    # -- recording -----------------------------------------------------------------
    def toggle_record(self):
        r = self.rec
        if r is not None and r.stage == "recording" and not r.stopping:
            r.stop()
            self.set_status(u"جاري إنهاء التسجيل ...")
            return self.ensure_timer()
        if r is not None:
            return self.set_status(u"انتظر حتى ينتهي التسجيل السابق ...")
        url, title = Player.cur_url, Player.cur_title
        if not Player.active or not url:
            return self.set_status(u"شغّل إذاعة أو سورة أولاً ثم اضغط تسجيل")
        folder = data.record_dir()
        if folder is None:
            return self.set_status(u"لا يوجد HDD أو USB متصل (/media/hdd)")
        fmt = self.cfg.get("fmt", "original")
        note = u""
        if fmt != "original" and not data.backend_for(fmt):
            fmt = "original"
            note = u" (لا يوجد مُحوِّل لهذه الصيغة - سيُحفظ الأصلي)"
        self.rec = data.StreamRecorder(url, title, folder, fmt)
        self.rec.start()
        self.set_status(u"بدأ التسجيل [%s] في: %s%s" % (
            data.FORMAT_LABEL.get(fmt, fmt), folder, note))
        self.ensure_timer()

    def cycle_format(self):
        fmts = data.available_formats()
        keys = [k for k, _ in fmts]
        cur = self.cfg.get("fmt", "original")
        nxt = keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0]
        self.cfg["fmt"] = nxt
        self.save()
        if len(keys) == 1:
            self.set_status(u"لا يوجد ffmpeg/مُرمِّز على الجهاز - متاح الصيغة الأصلية فقط "
                            u"(opkg install ffmpeg)")
        else:
            self.set_status(u"صيغة التسجيل: %s   (المتاح: %s)" % (
                data.FORMAT_LABEL[nxt], u" / ".join(l for _, l in fmts)))
        if self.ui is not None:
            self.ui.qh_labels()

    # -- TV picture (video only, audio stays with the Quran) ---------------------------
    def pip_available(self):
        if self.cfg.get("pip_force"):
            return True
        try:
            from Components.SystemInfo import SystemInfo
            return bool(SystemInfo.get("PIPAvailable"))
        except Exception:
            return False

    def tv_size_name(self):
        return TV_SIZES[self.cfg.get("tv_size", 0) % len(TV_SIZES)][0]

    def tv_start(self, ref):
        """Show a TV channel as a PiP picture. A PiP window never outputs sound,
        so only the Quran audio (main service) is heard. Retries and a watchdog
        make it dependable; see tv_check()."""
        self.tv_ref = ref
        self.tv_want = True
        self.follow = True
        self.install_zap_hook()
        if self.overlay_active:                 # PiP needs the main service for the Quran audio
            self.restart_current()
        self.tv_attempt = self.tv_restarts = 0
        try:
            self.cfg["tv"] = ref.toString()
            self.save()
        except Exception:
            pass
        self._tv_try()

    def _tv_close_dialog(self):
        sess = self.session
        try:
            if hasattr(sess, "pip"):
                del sess.pip
        except Exception as e:
            qlog("pip close: %s" % e)
        sess.pipshown = False

    def _tv_try(self):
        if not self.tv_want or self.tv_ref is None:
            return
        if not self.pip_available():
            self.tv_want = False
            self.tv_err = u"PiP غير مدعوم"
            return self.set_status(
                u"PiP غير مدعوم حسب الجهاز - جرّب «تجاهل فحص PiP» من قائمة 9 (يعمل في صور كثيرة)",
                notify=True)
        self.tv_attempt += 1
        sess = self.session
        self._tv_close_dialog()
        ok, err = False, u""
        try:
            from Screens.PictureInPicture import PictureInPicture
            sess.pip = sess.instantiateDialog(PictureInPicture)
            sess.pip.show()
            ok = bool(sess.pip.playService(self.tv_ref))
        except Exception as e:
            err = u"%s" % e
        qlog("pip try #%d ok=%s err=%s" % (self.tv_attempt, ok, err))
        if ok:
            sess.pipshown = True
            try:
                from Screens.InfoBar import InfoBar
                sess.pip.servicePath = InfoBar.instance.servicelist.getCurrentServicePath()
            except Exception:
                pass
            self.tv_on = True
            self.tv_err = u""
            self.tv_apply_geometry()
            self.tv_refresh_in = 2
            self.ensure_timer()
            self.set_status(u"صورة التلفاز تعمل - الصوت من القرآن فقط", notify=self.ui is None)
            if self.tv_autohide and self.ui is not None:
                self.tv_autohide = False
                self.ui.close()                 # hide the plugin so the picture is visible
        else:
            self._tv_close_dialog()
            self.tv_on = False
            self.tv_err = err or u"القناة رُفضت (لا يوجد مُوالِف/ديكودر حر؟)"
            if self.tv_attempt < 3:
                self.set_status(u"إعادة محاولة الصورة (%d/3) ..." % self.tv_attempt)
                self.tv_timer.start(2000, True)
            else:
                if self.follow and Player.active:
                    return self.follow_fallback()
                self.tv_want = False
                self.tv_autohide = False
                self.set_status(u"تعذّرت صورة التلفاز: %s" % self.tv_err, notify=True)
        if self.ui is not None:
            self.ui.qh_labels()

    def tv_apply_geometry(self):
        pip = getattr(self.session, "pip", None)
        if pip is None:
            return
        try:
            size = getDesktop(0).size()
            W, H = size.width(), size.height()
        except Exception:
            return
        name, fx, fy, fw, fh = TV_SIZES[self.cfg.get("tv_size", 0) % len(TV_SIZES)]
        x, y, w, h = int(W * fx), int(H * fy), int(W * fw), int(H * fh)
        done = []
        for fn, args in (("move", (x, y)), ("resize", (w, h))):
            try:
                getattr(pip, fn)(*args)
                done.append(fn)
            except Exception as e:
                qlog("pip.%s failed: %s" % (fn, e))
        if len(done) < 2:                       # other image flavours: talk to the widget itself
            try:
                from enigma import ePoint, eSize
                pip.instance.move(ePoint(x, y))
                pip.instance.resize(eSize(w, h))
                try:
                    pip["video"].instance.resize(eSize(w, h))
                except Exception:
                    pass
                done.append("instance")
            except Exception as e:
                qlog("pip instance resize failed: %s" % e)
        self.tv_geo = u",".join(done) or u"-"
        try:
            pip.show()
        except Exception:
            pass

    def tv_refresh(self):
        if self.tv_on:
            self.tv_apply_geometry()

    def tv_check(self):
        """Watchdog: restart the picture if the PiP dialog died or lost its service."""
        if not self.tv_want or self.tv_timer.isActive():
            return
        pip = getattr(self.session, "pip", None)
        alive = pip is not None and getattr(self.session, "pipshown", False) and self.tv_on
        if alive:
            try:
                alive = pip.getCurrentService() is not None
            except Exception:
                pass
        if alive:
            return
        self.tv_restarts += 1
        qlog("pip lost -> restart #%d" % self.tv_restarts)
        if self.tv_restarts > 6:
            if self.follow and Player.active:
                return self.follow_fallback()
            self.tv_want = False
            self.tv_on = False
            return self.set_status(u"انقطعت صورة التلفاز عدة مرات - أوقفتها (اضغط 9 > تشخيص)", notify=True)
        self.tv_on = False
        self.tv_attempt = 0
        self.set_status(u"انقطعت الصورة - إعادة تشغيلها (%d) ..." % self.tv_restarts)
        self._tv_try()

    def pip_video_width(self, pip):
        """Width of the picture decoded in the PiP window (0 = nothing decoded), None = unknown."""
        try:
            from enigma import iServiceInformation
            svc = getattr(pip, "pipservice", None)
            if svc is None:
                cur = pip.getCurrentService()
                svc = cur if hasattr(cur, "info") else None
            info = svc.info() if svc is not None else None
            if info is None:
                return None
            return int(info.getInfo(iServiceInformation.sVideoWidth))
        except Exception as e:
            qlog("pip width: %s" % e)
            return None

    def tv_stop(self):
        was = self.tv_on or self.tv_want
        self.tv_want = False
        self.tv_autohide = False
        if self.tv_timer is not None:
            self.tv_timer.stop()
        if self.follow and self.tv_ref is not None:
            Player.saved = self.tv_ref         # stopping later puts this channel back
        self.follow = False
        if not was:
            return
        self._tv_close_dialog()
        self.tv_on = False
        self.set_status(u"تم إيقاف صورة التلفاز")
        if self.ui is not None:
            self.ui.qh_labels()

    def tv_retry(self):
        ref = self.tv_ref or self.tv_last_ref()
        if ref is not None:
            self.tv_start(ref)

    def tv_cycle_size(self):
        self.cfg["tv_size"] = (self.cfg.get("tv_size", 0) + 1) % len(TV_SIZES)
        self.save()
        self.tv_apply_geometry()
        self.set_status(u"حجم الصورة: %s" % self.tv_size_name())
        if self.ui is not None:
            self.ui.qh_labels()

    def tv_toggle_force(self):
        self.cfg["pip_force"] = not self.cfg.get("pip_force", False)
        self.save()
        self.set_status(u"تجاهل فحص دعم PiP: %s" % (u"مفعّل" if self.cfg["pip_force"] else u"معطّل"))

    def zap(self, ref):
        """Change the main channel (picture); the Quran keeps playing on its own player."""
        try:
            self.session.nav.playService(ref)
            self.cfg["tv"] = ref.toString()
            self.save()
        except Exception as e:
            return self.set_status(u"تعذّر تغيير القناة: %s" % e)
        if self.overlay_active:
            self.tv_muted = False
            self.mute_timer.start(1200, True)
            self.mute_timer.start(2500, True)
        self.set_status(u"تم تغيير القناة")

    def tv_last_ref(self):
        s = self.cfg.get("tv")
        if s:
            try:
                return eServiceReference(s)
            except Exception:
                pass
        return Player.saved_ref

    def tv_label(self):
        if self.tv_on:
            state = u"✔ %s" % self.tv_size_name()
        else:
            state = u"محاولة ..." if self.tv_want else u"إيقاف"
        return u"9 صورة التلفاز: %s" % state

    def diag_text(self):
        lines = [
            u"PiP available: %s   (force=%s)" % (self.pip_available(), self.cfg.get("pip_force", False)),
            u"TV on=%s want=%s attempts=%d restarts=%d" % (self.tv_on, self.tv_want,
                                                          self.tv_attempt, self.tv_restarts),
            u"TV ref: %s" % (self.cfg.get("tv") or u"-"),
            u"Last error: %s" % (self.tv_err or u"-"),
            u"Geometry via: %s   size: %s" % (self.tv_geo or u"-", self.tv_size_name()),
            u"Audio: engine=%s active=%s live=%s reconnects=%d" % (
                Player.engine_name(), Player.active, self.is_live(), self.reconnects),
            u"Overlay: wanted=%s active=%s muted=%s" % (self.cfg.get("overlay", False),
                                                      self.overlay_active, self.tv_muted),
            u"Timeshift: %s  minibar=%s  remote=%s" % (self.cfg.get("timeshift", True),
                                                      self.cfg.get("minibar", True), self.cfg.get("remote", True)),
            u"Net: %s" % (self.net_text() or u"-"),
            u"Log: %s" % log_path(),
        ]
        qlog("DIAG " + " | ".join(lines))
        return u"\n".join(lines)

    # ================================================================== v1.8 extras
    mute_failed = False
    ov_check_at = 0
    rec_stop_at = 0
    ctx = None                    # (section, entry label, index) of what is playing - for "continue listening"
    resume_seek = 0
    extras_ready = False

    def init_extras(self):
        self.extras_ready = True
        self.dl = extras.Downloader()
        self.remote = None
        self.sched_fired = set()
        self.prayer_fired = set()
        self.prayer_paused = False
        self.prayer_resume_at = 0
        self.ramp = None
        self.search_rows = []
        self.pos_saved = time.time()
        self.min_tick = 0
        self.radio_cache = []
        self.dl_reported = 0
        self.rem_tick = 0
        self.prefetched = False
        self.adhan_pf = False
        self.boot = time.time()
        self._st_last = time.time()
        self._st_saved = time.time()
        try:                                    # lists survive reboots when a disk is attached
            d = data.record_dir()
            if d:
                data.CACHE_DIR = os.path.join(d, "cache")
                data.CACHE_TTL = 7 * 24 * 3600
        except Exception:
            pass
        try:
            d = data.record_dir()
            if d:
                qtext.WW_FILE = os.path.join(d, ".saadquranhub_widths.bin")
                tc = data.home_dir("cache/text")
                if tc:
                    qtext.set_cache(tc)               # drawn Quran lines: on the disk, kept across restarts
        except Exception:
            pass
        if not self.cfg.get("migr_saad14"):          # 1.4: Arabic drawn as pictures
            self.cfg["migr_saad14"] = True
            self.cfg["quran_font"] = "img"
            self.save()
        if not self.cfg.get("migr_saad13"):          # 1.3: Quran font -> harakat over the letters
            self.cfg["migr_saad13"] = True
            if self.cfg.get("tashkeel") == "medial":
                del self.cfg["tashkeel"]
            self.save()
        if not self.cfg.get("migr_saad12"):        # put back what 1.0 wrote over the box default (0 = automatic)
            self.cfg["migr_saad12"] = True
            try:
                video_plane_undo()
            except Exception as e:
                qlog("video undo: %s" % e)
            self.save()
        if not self.cfg.get("migr31"):          # v3.1: new TV method and library-first layout
            self.cfg.update({"migr31": True, "tv_mode": "auto", "overlay_bad": False, "home_screen": False,
                             "tv_size": 0, "follow": True})
            self.save()
        if self.cfg.get("remote_web"):
            self.remote_enable(True, quiet=True)

    def keep_alive(self):
        """True when the 1-second timer must keep running even with nothing playing."""
        c = self.cfg
        return bool(c.get("sched") or (c.get("prayer_city") and c.get("prayer_mode", "notify") != "off")
                    or c.get("fajr_wake") or c.get("wird_time") or c.get("kahf_time") or c.get("mulk_time")
                    or self.remote is not None or self.dl.busy() or self.taf_prog is not None)

    # -- position / volume ----------------------------------------------------------------
    def play_pos(self):
        """-> (position, length) in seconds, or None."""
        try:
            if Player.sink is not None and self.out is not None:
                return self.out.position()
            sk = self.session.nav.getCurrentService().seek()
            ln, ps = sk.getLength(), sk.getPlayPosition()
            if not ln[0] and not ps[0] and ln[1] > 0:
                return ps[1] / 90000.0, ln[1] / 90000.0
        except Exception:
            pass
        return None

    @staticmethod
    def _vc():
        try:
            from enigma import eDVBVolumecontrol
            return eDVBVolumecontrol.getInstance()
        except Exception:
            return None

    def get_volume(self):
        vc = self._vc()
        try:
            return vc.getVolume() if vc else None
        except Exception:
            return None

    def set_volume(self, v):
        vc = self._vc()
        try:
            if vc:
                v = int(max(0, min(100, v)))
                vc.setVolume(v, v)
        except Exception:
            pass

    def vol_change(self, delta):
        v = self.get_volume()
        if v is None:
            return self.set_status(u"التحكم بالصوت غير متاح")
        self.set_volume(v + delta)
        self.set_status(u"مستوى الصوت: %d" % max(0, min(100, v + delta)))

    def vol_mute(self):
        vc = self._vc()
        try:
            if vc:
                vc.volumeToggleMute()
        except Exception:
            pass

    def start_ramp(self, target):
        if target:
            self.ramp = {"target": target, "t0": time.time()}
            self.set_volume(max(3, target // 10))

    def ramp_tick(self, now):
        r = self.ramp
        frac = min(1.0, (now - r["t0"]) / 60.0)
        self.set_volume(r["target"] * max(0.1, frac))
        if frac >= 1.0:
            self.ramp = None

    # -- continue listening ---------------------------------------------------------------
    def save_resume(self):
        if not Player.active or not self.cur_url or self.cur_live or self.adhan_prev is not None:
            return
        pp = self.play_pos()
        self.cfg["resume"] = {"title": Player.cur_title, "url": self.real_url(self.cur_url),
                              "pos": int(pp[0]) if pp else 0, "ctx": self.ctx or {}}
        self.save()

    def resume_last(self):
        r = self.cfg.get("resume")
        if not r:
            return self.set_status(u"لا يوجد ما يُستأنف بعد")
        ctx = r.get("ctx") or {}

        def build():
            if ctx.get("sec") and ctx.get("label"):
                entry = dict(section_loader(ctx["sec"])()).get(ctx["label"])
                if entry is not None:
                    rows = subs_for(entry) if entry_has_subs(entry) else [(ctx["label"], entry)]
                    return [x for _, x in rows if x is not None and (x.get("url") or x.get("resolve"))]
            return None
        self.set_status(u"جاري استئناف: %s" % r.get("title", u""))
        self.runner.run(build, lambda res: self._resume_go(res, r), lambda e: self._resume_go(None, r))

    def _resume_go(self, res, r):
        ctx = r.get("ctx") or {}
        idx = ctx.get("idx", 0)
        if isinstance(res, Exception) or not res or not (0 <= idx < len(res)):
            res, idx = [{"title": r.get("title", u""), "url": r["url"], "autonext": True}], 0
        self.ctx = dict(ctx)
        self.resume_seek = int(r.get("pos", 0)) if r.get("pos", 0) > 5 else 0
        self.play_list(res, idx)

    # -- schedules ----------------------------------------------------------------------------
    def start_record_url(self, url, title, minutes=0):
        """Record a stream in the background (does not interrupt what you are watching)."""
        if self.rec is not None:
            return self.set_status(u"يوجد تسجيل قيد العمل - تخطّي التسجيل المجدول", notify=True)
        folder = data.record_dir()
        if folder is None:
            return self.set_status(u"لا يوجد HDD أو USB متصل للتسجيل", notify=True)
        fmt = self.cfg.get("fmt", "original")
        if fmt != "original" and not data.backend_for(fmt):
            fmt = "original"
        self.rec = data.StreamRecorder(url, title, folder, fmt)
        self.rec.start()
        self.rec_stop_at = time.time() + minutes * 60 if minutes else 0
        self.set_status(u"بدأ التسجيل المجدول: %s (%s)" % (title, u"%d د" % minutes if minutes else u"مفتوح"),
                        notify=True)
        self.ensure_timer()

    def run_schedule(self, s):
        if s.get("rec"):
            if s.get("url"):
                qlog("scheduled recording: %s" % s.get("title"))
                self.start_record_url(s["url"], s.get("title", u"") or u"recording", int(s.get("dur", 60)))
            return
        items = []
        if s.get("pl") and self.cfg.get("pls", {}).get(s["pl"]):
            for it in self.cfg["pls"][s["pl"]]:
                live = bool(it.get("live"))
                items.append({"title": it["title"], "url": it["url"], "live": live, "autonext": not live})
        elif s.get("url"):
            live = bool(s.get("live"))
            items = [{"title": s.get("title", u""), "url": s["url"], "live": live, "autonext": not live}]
        if not items:
            return
        qlog("schedule fired: %s" % s.get("title"))
        vol0 = self.get_volume()
        self.ctx = None
        self.play_list(items, 0)
        if s.get("ramp", True):
            self.start_ramp(vol0)
        popup(u"تشغيل مجدول: %s" % s.get("title", u""), 5)

    def sched_add(self, hm, days, title, url=None, live=False, pl=None, rec=False, dur=60):
        ids = [x.get("id", 0) for x in self.cfg.get("sched", [])] or [0]
        s = {"id": max(ids) + 1, "hm": hm, "days": days, "title": title, "ramp": True, "on": True}
        if rec:
            s["rec"], s["dur"] = True, int(dur)
        if pl:
            s["pl"] = pl
        else:
            s["url"], s["live"] = url, bool(live)
        self.cfg.setdefault("sched", []).append(s)
        self.save()
        self.ensure_timer()
        return s

    def sched_del(self, sid):
        self.cfg["sched"] = [x for x in self.cfg.get("sched", []) if x.get("id") != sid]
        self.save()

    # -- prayer times -----------------------------------------------------------------------
    # -- v2.0 helpers -----------------------------------------------------------------------------
    diag_rows = None
    taf_prog = None

    def info_line(self):
        if not Player.active:
            return u""
        return u"%s  •  %s" % (Player.engine_name(), self.net_text())

    def diag_enigma_checks(self):
        """Receiver-side checks for the self-diagnostic screen (runs on the GUI thread)."""
        rows = []
        try:
            ok = qtext.available()
            rows.append((True if ok else False, u"رسم الحروف العربية كصور",
                         (u"جاهز (%d أحجام)  -  %s" % (len(qtext.sizes()), u"مفعّل" if img_text() else u"غير مفعّل"))
                         if ok else u"ملفات الحروف غير موجودة",
                         u"" if ok else u"أعد تثبيت البلاجين"))
            rows.append((None if not register_quran_fonts() else True, u"تسجيل الخط القرآني في الجهاز",
                         u"نجح" if register_quran_fonts() else u"فشل (لهذا كانت الحروف مقطعة) - الصور لا تحتاجه", u""))
        except Exception as e:
            rows.append((None, u"رسم الحروف", u"%s" % e, u""))
        try:
            av = self.pip_available()
            rows.append((True if av else None, u"صورة داخل صورة (PiP)", u"متاح" if av else u"غير متاح في هذه الصورة",
                         u"" if av else u"سيُستعمل وضع الصوت المنفصل أو التبديل العادي للقناة"))
        except Exception as e:
            rows.append((None, u"صورة داخل صورة (PiP)", u"%s" % e, u""))
        try:
            if self.main_has_tv():
                at = self._tv_tracks()
                if at is None:
                    rows.append((None, u"كتم صوت القناة", u"لا يمكن الوصول لمسارات الصوت",
                                 u"وضع (قناة + صوت منفصل) قد لا يعمل - جرّب PiP"))
                else:
                    rows.append((True, u"كتم صوت القناة", u"ممكن (%s)" % (u"مفعّل الآن" if self.tv_muted else u"جاهز"), u""))
            else:
                rows.append((None, u"كتم صوت القناة", u"لا توجد قناة تعمل الآن للفحص", u"شغّل قناة ثم أعد الفحص"))
        except Exception as e:
            rows.append((None, u"كتم صوت القناة", u"%s" % e, u""))
        try:
            strat = self.tv_strategy()
            lab = {"pip": u"القرآن + صورة القناة كاملة (PiP)", "overlay": u"مشغّل ثانٍ فوق القناة", "off": u"بدون صورة"}[strat]
            rows.append((True if strat != "off" else None, u"القرآن مع صورة القناة", lab,
                         u"" if strat != "off" else u"لا PiP ولا مشغّل ثانٍ - سيحل الصوت محل القناة"))
            rows.append((True if getattr(self.session.nav, "_qh_hooked", False) else None,
                         u"تغيير القناة دون إيقاف القرآن",
                         u"جاهز" if getattr(self.session.nav, "_qh_hooked", False) else u"غير مركّب", u""))
            if self.pip_failed:
                rows.append((None, u"PiP", u"فشل على هذا الجهاز أثناء التشغيل", u"غيّر الوضع من القائمة لإعادة المحاولة"))
            pip = getattr(self.session, "pip", None)
            if pip is not None and self.tv_on:
                w = self.pip_video_width(pip)
                rows.append((True if (w or 0) > 0 else (None if w is None else False), u"صورة القناة في PiP",
                             u"عرض %s بكسل" % w if w else (u"غير معروف" if w is None else u"لا توجد صورة"),
                             u"" if (w or 0) > 0 else u"قناة مشفرة لا تُفك مرتين؟ جرّب قناة مفتوحة"))
        except Exception as e:
            rows.append((None, u"القرآن مع صورة القناة", u"%s" % e, u""))
        rows.append((True if self.out is not None else None, u"المشغّل الثاني (صوت فوق القناة)",
                     u"جاهز" if self.out is not None else u"غير متاح", u""))
        if self.cfg.get("overlay_bad"):
            rows.append((None, u"وضع القناة + صوت منفصل", u"عُطّل تلقائياً لأن كتم القناة فشل على هذا الجهاز",
                         u"استخدم PiP أو غيّر الوضع من القائمة"))
        rows.append((True, u"المشغّل الحالي", Player.engine_name(), u""))
        rows.append((True if self.cfg.get("alt_source", True) else None, u"المصدر البديل التلقائي",
                     u"مفعّل" if self.cfg.get("alt_source", True) else u"معطّل", u""))
        try:
            import socket
            sk = socket.socket()
            sk.settimeout(0.5)
            busy = sk.connect_ex(("127.0.0.1", remote.PORT)) == 0
            sk.close()
            if self.remote is not None:
                rows.append((True, u"تطبيق الجوال", u"يعمل: http://%s:%d" % (remote.local_ip(), remote.PORT), u""))
            else:
                rows.append((None if busy else True, u"تطبيق الجوال",
                             u"المنفذ %d مشغول" % remote.PORT if busy else u"متوقف (فعّله من القائمة)", u""))
        except Exception:
            pass
        rows.append((True, u"أذان بالصوت", (u"مفعّل - " + extras.adhan_source(self.cfg)[1]) if
                     self.cfg.get("prayer_mode") == "adhan" and extras.adhan_source(self.cfg) else u"غير مفعّل", u""))
        return rows

    def tafsir_download(self, key):
        """Fetch a whole tafsir surah by surah onto the disk (for reading without internet)."""
        if extras.tafsir_available(key):
            return self.set_status(u"هذا التفسير موجود بالكامل على الجهاز", notify=True)
        if extras.writable_data_dir() is None:
            return self.set_status(u"يلزم HDD أو USB لحفظ التفسير - أو ثبّت حزمة التفاسير", notify=True)
        if self.taf_prog is not None:
            return self.set_status(u"يوجد تنزيل تفسير قيد العمل", notify=True)
        self.taf_prog = [key, 0, 0, None]

        def job(st=self.taf_prog):
            for n in range(1, 115):
                try:
                    extras.chapter_tafsir(n, key)
                except Exception as e:
                    st[2] += 1
                    st[3] = u"%s" % e
                st[1] = n
            return st
        self.runner.run(job, lambda r: None, lambda e: None)
        self.set_status(u"بدأ تنزيل %s ..." % extras.TAFSIR_BY_KEY[key][1], notify=True)
        self.ensure_timer()

    def taf_tick(self):
        st = self.taf_prog
        if st is None:
            return
        if st[1] >= 114:
            self.taf_prog = None
            self.set_status(u"اكتمل تنزيل %s (فشل %d سورة)" % (extras.TAFSIR_BY_KEY[st[0]][1], st[2]) if st[2]
                            else u"اكتمل تنزيل %s - يعمل الآن بدون إنترنت" % extras.TAFSIR_BY_KEY[st[0]][1], notify=True)
        elif int(time.time()) % 5 == 0:
            self.set_status(u"تنزيل %s: %d / 114" % (extras.TAFSIR_BY_KEY[st[0]][1], st[1]))

    # -- automatic theme (day/night or by prayer time) -----------------------------------------
    PRAYER_THEME_DEFAULT = {"fajr": 2, "sunrise": 6, "dhuhr": 6, "asr": 1, "maghrib": 3, "isha": 0, "night": 7}
    _theme_cache = (0, 0, None)

    def theme_idx(self):
        c = self.cfg
        n = len(THEMES)
        mode = c.get("auto_theme", "off")
        if mode not in ("daynight", "prayer"):
            return int(c.get("theme", 0)) % n
        now = time.time()
        t0, idx, m0 = self._theme_cache
        if m0 == mode and now - t0 < 30:
            return idx
        try:
            city = c.get("prayer_city")
            if mode == "daynight":
                idx = c.get("theme_day", 6) if extras.is_daytime(city, now) else c.get("theme_night", 7)
            else:
                per = extras.day_period(city, now)
                idx = (c.get("theme_prayer") or {}).get(per, self.PRAYER_THEME_DEFAULT.get(per, 0))
        except Exception:
            idx = c.get("theme", 0)
        idx = int(idx) % n
        self._theme_cache = (now, idx, mode)
        return idx

    # -- adhan: play the adhan itself, then go back to what was playing ----------------------------
    adhan_prev = None
    adhan_deadline = 0

    def adhan_start(self, label):
        if self.adhan_prev is not None:
            return
        src = extras.adhan_source(self.cfg)
        if src is None:
            return
        url, nm = src
        if not url.startswith("http") and not url.startswith("file://"):
            url = "file://" + url
        paused = self.is_paused()
        prev = {"active": bool(Player.active and not paused), "pl": list(self.pl), "pi": self.pi,
                "ctx": dict(self.ctx) if self.ctx else None, "live": bool(self.cur_live), "pos": 0}
        if prev["active"] and not prev["live"]:
            try:
                pp = self.play_pos()
                prev["pos"] = int(pp[0]) if pp else 0
            except Exception:
                pass
        try:
            self.save_resume()
        except Exception:
            pass
        self.adhan_prev = prev
        self.adhan_deadline = time.time() + 8 * 60
        self.ramp = None
        qlog("adhan start: %s (%s)" % (nm, url))
        self.ctx = None
        self.play_list([{"title": u"الأذان - %s" % label, "url": url, "live": False, "autonext": False}], 0)
        self.ensure_timer()

    def adhan_done(self, why=u""):
        prev, self.adhan_prev = self.adhan_prev, None
        if prev is None:
            return
        qlog("adhan done %s" % why)
        if prev["active"] and prev["pl"] and 0 <= prev["pi"] < len(prev["pl"]):
            self.ctx = prev["ctx"]
            self.resume_seek = prev["pos"] if prev["pos"] > 5 and not prev["live"] else 0
            popup(u"استئناف التلاوة بعد الأذان", 4)
            self.play_list(prev["pl"], prev["pi"])
        else:
            Player.stop(self.session)
            self.unmute_tv()
            self.overlay_active = False
            self.drop_buffer()
            self._paused_file = False
            self.hide_minibar()
            self.t0 = None
            self.cur_url = None
            self.reset_net()
            self.tok += 1

    def adhan_tick(self, now):
        if self.adhan_prev is not None and now > self.adhan_deadline:
            self.adhan_done(u"(انتهت المهلة)")
        if (not self.adhan_pf and self.cfg.get("prayer_mode") == "adhan" and self.runner is not None
                and now - self.boot > 45):
            self.adhan_pf = True
            self.runner.run(lambda: extras.adhan_prefetch(self.cfg),
                            lambda r: qlog("adhan prefetch: %r" % (r,)),
                            lambda e: qlog("adhan prefetch failed: %s" % e))

    def prayer_fire(self, label):
        if self.cfg.get("prayer_mode") == "adhan":
            popup(u"حان الآن موعد أذان %s" % label, 20)
            return self.adhan_start(label)
        popup(u"حان الآن موعد أذان %s" % label, 20)
        if (self.cfg.get("prayer_mode") == "pause" and Player.active and not self.prayer_paused
                and not self.is_paused()):
            self.toggle_pause()
            self.prayer_paused = True
            self.prayer_resume_at = time.time() + 60 * int(self.cfg.get("prayer_pause_min", 10))

    def prayer_resume(self):
        self.prayer_paused = False
        if Player.active and self.is_paused():
            self.toggle_pause()
            popup(u"استئناف التلاوة", 4)

    def is_paused(self):
        return self.paused_at is not None or bool(getattr(self, "_paused_file", False))

    def next_prayer_text(self):
        c = self.cfg.get("prayer_city")
        if not c:
            return u""
        np = extras.next_prayer(c)
        if not np:
            return u""
        left = int(np[1] * 60 - (time.localtime().tm_hour * 60 + time.localtime().tm_min))
        left = left % (24 * 60)
        return u"الصلاة القادمة: %s %s  (بعد %d:%02d)" % (np[0], extras.hm(np[1]), left // 60, left % 60)

    def prayer_table(self):
        c = self.cfg.get("prayer_city")
        pt = extras.today_prayers(c) if c else None
        if not pt:
            return u"اختر المدينة أولاً"
        rows = [u"مواقيت الصلاة - %s" % c, u""]
        rows.append(u"الفجر      %s" % extras.hm(pt["fajr"]))
        rows.append(u"الشروق    %s" % extras.hm(pt["sunrise"]))
        rows.append(u"الظهر      %s" % extras.hm(pt["dhuhr"]))
        rows.append(u"العصر      %s" % extras.hm(pt["asr"]))
        rows.append(u"المغرب    %s" % extras.hm(pt["maghrib"]))
        rows.append(u"العشاء     %s" % extras.hm(pt["isha"]))
        rows.append(u"")
        rows.append(self.next_prayer_text())
        return u"\n".join(rows)

    # -- idle line: prayer / dhikr / ayah of the day --------------------------------------------
    def ensure_aotd(self):
        today = time.strftime("%Y-%m-%d")
        if (self.cfg.get("aotd") or {}).get("d") == today or self.runner is None:
            return

        def done(r):
            if not isinstance(r, Exception):
                self.cfg["aotd"] = {"d": today, "k": r[0], "t": r[1]}
                self.save()
        self.runner.run(extras.ayah_of_the_day, done, lambda e: None)

    def idle_text(self):
        k = int(time.time() // 12) % 4
        if k == 3:
            try:
                return self.reciter_of_day_text() + u"  (من القائمة)"
            except Exception:
                pass
        if k == 0:
            t = self.next_prayer_text()
            if t:
                return t
        if k == 1:
            a = self.cfg.get("aotd")
            if a and a.get("t"):
                return u"﴿ %s ﴾ (%s)" % (a["t"], a["k"])
        return extras.dhikr_of_the_moment()

    def prefetch(self):
        """Warm the main lists in the background once, so opening a section is instant."""
        if self.prefetched or self.runner is None:
            return
        self.prefetched = True

        def run():
            out = {}
            for key in ("mp3q_reciters", "mp3q_radios", "qcom"):
                if key in SEC_CACHE:
                    continue
                try:
                    out[key] = section_loader(key)()
                except Exception as e:
                    qlog("prefetch %s: %s" % (key, e))
            return out

        def done(res):
            if not isinstance(res, Exception):
                for k, v in res.items():
                    SEC_CACHE.setdefault(k, v)
        self.runner.run(run, done, lambda e: None)

    # -- downloads: see Hub16Bg.download_payloads ----------------------------------------------
    def dl_text(self):
        d = self.dl
        out = u""
        if d.busy():
            pct = u" %d%%" % (100 * d.bytes // d.total) if d.total else u" %s" % data.fmt_bytes(d.bytes)
            out = u"⬇ تنزيل%s (%d)" % (pct, d.pending())
        if self.jobs is not None and self.jobs.busy():
            out = (out + u"  " if out else u"") + self.jobs.text()
        return out

    # -- global search -------------------------------------------------------------------------
    def search_all(self, query, done):
        q = data.norm(query)
        labels = dict((k, l) for k, l, _h, _s in SECTIONS)

        def run():
            rows = []
            sn = [n for n in range(1, 115) if q and q in data.norm(data.surah_name(n))]
            if sn and len(q) >= 3:
                try:
                    for name, entry in section_loader("mp3q_reciters")():
                        rec = entry["rec"]
                        for n in sn[:2]:
                            for m in rec["moshaf"]:
                                if n in m["surahs"]:
                                    rows.append((u"سورة %s — %s" % (data.surah_name(n), name),
                                                 surah_payload(name, n, url=data.mp3quran_surah_url(m["server"], n))))
                                    break
                        if len(rows) >= 80:
                            break
                except Exception as e:
                    qlog("search surah: %s" % e)
            for key in ("mp3q_reciters", "mp3q_radios", "qcom", "sq_reciters", "sq_radios", "islam", "way_reciters"):
                try:
                    items = section_loader(key)()
                except Exception:
                    continue
                for label, payload in items:
                    if q in data.norm(label):
                        rows.append((u"%s  ·  %s" % (label, labels.get(key, u"")), dict(payload, favkey=(key, label))))
                if len(rows) > 300:
                    break
            return rows
        self.runner.run(run, done, lambda e: done(e))

    # -- backup ------------------------------------------------------------------------------
    def backup_now(self):
        try:
            path = extras.backup_settings(self.cfg)
        except Exception as e:
            return self.set_status(u"فشل النسخ الاحتياطي: %s" % e)
        self.set_status(u"تم حفظ النسخة الاحتياطية: %s" % path if path else u"لا يوجد HDD أو USB", notify=True)

    def restore_now(self):
        path = extras.find_backup()
        if not path:
            return self.set_status(u"لم أجد ملف نسخة احتياطية على HDD/USB")
        try:
            cfg = extras.restore_settings(path)
        except Exception as e:
            return self.set_status(u"ملف النسخة تالف: %s" % e)
        self.cfg.update(cfg)
        self.save()
        self.set_status(u"تمت الاستعادة من %s - أعد فتح الإضافة" % path, notify=True)

    # -- phone remote ----------------------------------------------------------------------------
    def remote_enable(self, on, quiet=False):
        self.cfg["remote_web"] = bool(on)
        if on:
            if not self.cfg.get("remote_pin"):
                import random
                self.cfg["remote_pin"] = "%04d" % random.randint(0, 9999)
            if self.remote is None:
                self.remote = remote.RemoteServer(pin=self.cfg["remote_pin"])
            ok = self.remote.start()
            if not ok:
                self.remote = None
                self.cfg["remote_web"] = False
            elif not self.radio_cache and self.runner is not None:
                self.runner.run(lambda: list(data.mp3quran_radios()),
                                lambda r: setattr(self, "radio_cache", [] if isinstance(r, Exception) else r),
                                lambda e: None)
            if not quiet:
                self.set_status((u"التحكم من الجوال: http://%s:%d  الرمز %s" % (
                    remote.local_ip(), remote.PORT, self.cfg["remote_pin"])) if ok
                    else u"تعذّر تشغيل خادم التحكم (المنفذ مشغول؟)", notify=True)
            self.ensure_timer()
        else:
            if self.remote is not None:
                self.remote.stop()
            self.remote = None
            if not quiet:
                self.set_status(u"تم إيقاف التحكم من الجوال")
        self.save()

    def remote_info(self):
        if self.remote is None:
            return u"متوقف"
        return u"http://%s:%d   الرمز: %s" % (remote.local_ip(), remote.PORT, self.cfg.get("remote_pin"))

    def remote_state(self):
        lists = []
        if self.cfg.get("hist"):
            lists.append({"key": "hist", "name": u"آخر ما سمعت",
                          "items": [{"t": h["title"], "live": h.get("live", False)} for h in self.cfg["hist"][:15]]})
        if self.radio_cache:
            lists.append({"key": "radio", "name": u"الإذاعات",
                          "items": [{"t": n, "live": True} for n, _u in self.radio_cache[:60]]})
        lib = self.lib_cached()
        if lib:
            lists.append({"key": "lib", "name": u"مكتبتي (الملفات المنزّلة) - تشغيل القارئ كاملاً",
                          "items": [{"t": u"%s  (%d)" % (rec, len(items)), "live": False} for rec, _f, items in lib[:60]]})
        for i, name in enumerate(sorted(self.cfg.get("pls", {}))):
            lists.append({"key": "pl%d" % i, "name": u"قائمة: " + name,
                          "items": [{"t": x["title"], "live": x.get("live", False)} for x in self.cfg["pls"][name]]})
        st = {"playing": bool(Player.active), "title": Player.cur_title or u"", "status": self.status,
              "lists": lists, "clock": time.strftime("%H:%M"), "pct": 0, "pos": None, "len": None,
              "ayah": (self.cfg.get("aotd") or {}).get("t", u""), "city": self.cfg.get("prayer_city") or u"",
              "prayers": [], "next": self.next_prayer_text(), "verse": u"", "verse_no": 0, "surah": 0,
              "week": u"", "url": self.cur_url if (Player.active and not self.cur_live and self.cur_url
                                                    and self.cur_url.startswith("http")
                                                    and "127.0.0.1" not in self.cur_url) else u"",
              "paused": self.is_paused()}
        try:
            cur = self.verse_now()
            if cur:
                st["surah"], st["verse_no"] = cur
                vs = dict(extras.local_verses(cur[0]) or [])
                st["verse"] = extras.sanitize(vs.get(cur[1], u""))
            st["week"] = studio.weekly_text(self.cfg)
        except Exception:
            pass
        try:
            pr = self.play_pos() if Player.active and not self.cur_live else None
            if pr:
                st["pos"], st["len"] = int(pr[0]), int(pr[1])
                st["pct"] = int(100 * min(1.0, pr[0] / max(1.0, pr[1])))
            elif Player.active:
                st["pct"] = 100
        except Exception:
            pass
        try:
            c = self.cfg.get("prayer_city")
            pt = extras.today_prayers(c) if c else None
            if pt:
                np = extras.next_prayer(c)
                for key, label in extras.PRAYER_NAMES:
                    st["prayers"].append([label, extras.hm(pt[key]), bool(np and np[0] == label)])
        except Exception:
            pass
        return st

    _lib_cache = (0, [])

    def lib_cached(self):
        """The library for the phone app (scanned at most once a minute)."""
        t0, lib = self._lib_cache
        if time.time() - t0 > 60:
            try:
                lib = library.scan()
            except Exception:
                lib = []
            self._lib_cache = (time.time(), lib)
        return lib

    def remote_tick(self):
        self.rem_tick += 1
        for cmd in self.remote.pop_commands():
            try:
                self.remote_do(cmd)
            except Exception as e:
                qlog("remote cmd: %s" % e)
        if self.rem_tick % 3 == 0:
            self.remote.publish(self.remote_state())

    def remote_do(self, cmd):
        if cmd[0] == "cmd" and cmd[1].startswith("tvat:"):
            return self.continue_on_tv(cmd[1][5:])
        if cmd[0] == "cmd" and cmd[1] == "phone":
            if Player.active and not self.is_paused():
                self.toggle_pause()
            return
        if cmd[0] == "cmd":
            c = cmd[1]
            table = {"pause": self.toggle_pause, "stop": self.stop_play, "next": lambda: self.step(1),
                     "prev": lambda: self.step(-1), "rew": lambda: self.seek(-30), "fwd": lambda: self.seek(30),
                     "vol+": lambda: self.vol_change(5), "vol-": lambda: self.vol_change(-5),
                     "mute": self.vol_mute, "resume": self.resume_last, "live": self.go_live,
                     "adhan_test": lambda: self.adhan_start(u"تجربة"),
                     "kahf": lambda: self.play_surah(18), "mulk": lambda: self.play_surah(67),
                     "hifz": self.hifz_play}
            if c in table:
                table[c]()
        elif cmd[0] == "play":
            _, k, i = cmd
            items, idx = [], i
            if k == "lib":
                lib = self.lib_cached()
                if 0 <= i < len(lib):
                    rec, _f, files = lib[i]
                    self.ctx = None
                    return self.play_list(library.payloads(files, rec), 0)
                return
            if k == "hist":
                rows = self.cfg.get("hist", [])[:15]
            elif k == "radio":
                rows = [{"title": n, "url": u, "live": True} for n, u in self.radio_cache[:60]]
            elif k.startswith("pl"):
                names = sorted(self.cfg.get("pls", {}))
                rows = self.cfg["pls"][names[int(k[2:])]] if int(k[2:]) < len(names) else []
            else:
                rows = []
            for it in rows:
                live = bool(it.get("live"))
                items.append({"title": it["title"], "url": it["url"], "live": live, "autonext": not live})
            if items and 0 <= idx < len(items):
                self.ctx = None
                self.play_list(items, idx)

    # -- the per-second hook -----------------------------------------------------------------
    # -- exact ayah timing ---------------------------------------------------------------------
    timing_cache = None
    timing_reads_list = None
    sync_exact = False

    def cur_item(self):
        return self.pl[self.pi] if self.pl and 0 <= self.pi < len(self.pl) else {}

    def load_timing_reads(self):
        if self.timing_reads_list is not None:
            return
        self.timing_reads_list = []                   # loading
        self.runner.run(data.timing_reads, self._reads_done, lambda e: None)

    def _reads_done(self, r):
        if not isinstance(r, Exception):
            self.timing_reads_list = r

    def timing_for(self, n):
        """Timing list of the surah being played, or None (fetched in the background)."""
        if self.timing_cache is None:
            self.timing_cache = {}
        item = self.cur_item()
        read, matched = item.get("timing"), False
        if not read:
            self.load_timing_reads()
            r = data.timing_read_for(self.timing_reads_list or [], Player.cur_title or u"")
            if r is None:
                return None, False
            read, matched = r["id"], True
        key = (read, n)
        tu = self.cfg.setdefault("timing_used", [])
        if read not in tu[-5:]:
            tu.append(read)
            del tu[:-5]
        v = self.timing_cache.get(key)
        if v is None:
            self.timing_cache[key] = "pending"
            self.runner.run(lambda: data.ayat_timing(read, n),
                            lambda res, k=key: self.timing_cache.__setitem__(k, res if isinstance(res, list) else False),
                            lambda e, k=key: self.timing_cache.__setitem__(k, False))
            return None, matched
        return (v if isinstance(v, list) else None), matched

    qdc_cache = None

    def qdc_timing(self, item):
        """quran.com word timing of the file being played (fetched once in the background)."""
        if self.qdc_cache is None:
            self.qdc_cache = {}
        key = tuple(item["qdc"])
        v = self.qdc_cache.get(key)
        if v is None:
            self.qdc_cache[key] = "pending"
            self.runner.run(lambda: data.quran_com_timing(key[0], key[1]),
                            lambda res, k=key: self.qdc_cache.__setitem__(k, res if (isinstance(res, list) and res) else False),
                            lambda e, k=key: self.qdc_cache.__setitem__(k, False))
            return None
        return v if isinstance(v, list) else None

    def word_now(self):
        """(surah, ayah, word number) being recited - only for quran.com recordings (word timing)."""
        try:
            if not Player.active or self.cur_live:
                return None
            item = self.cur_item()
            if not item.get("qdc"):
                return None
            tl = self.qdc_timing(item)
            pp = self.play_pos()
            if not tl or not pp:
                return None
            r = data.word_from_timing(tl, pp[0] * 1000.0)
            if not r:
                return None
            return int(item["qdc"][1]), r[0], r[1]
        except Exception as e:
            qlog("word now: %r" % (e,))
            return None

    def exact_ayah(self, n):
        """Ayah from the official timing when this recording has one (name matches are checked
        against the length of the file, so another recording of the same reciter is not used)."""
        self.sync_exact = False
        try:
            tl, matched = self.timing_for(n)
            if not tl:
                return None
            pp = self.play_pos()
            if not pp:
                return None
            pos, length = pp
            if matched:
                end = float(tl[-1][2]) or 1.0
                if length <= 0 or abs(length * 1000.0 - end) / end > 0.04:
                    return None
            self.sync_exact = True
            return data.ayah_from_timing(tl, pos * 1000.0)
        except Exception as e:
            qlog("timing: %s" % e)
            return None

    def verse_now(self):
        """(surah, ayah) being recited (exact in the memorisation studio and for timed recordings,
        estimated otherwise)."""
        if not Player.active:
            return None
        item = self.pl[self.pi] if self.pl and 0 <= self.pi < len(self.pl) else {}
        if item.get("ayah"):
            return int(item["ayah"][0]), int(item["ayah"][1])
        if self.cur_live:
            return None
        if item.get("tempo"):
            n = item.get("n") or extras.surah_of_title((Player.cur_title or u"").split(u"  ×")[0])
            pp = self.play_pos()
            if not n or not pp or pp[1] <= 0:
                return None
            return n, studio.ayah_at(n, min(1.0, pp[0] / float(pp[1])))
        if item.get("qdc"):
            wn = self.word_now()
            if wn:
                self.sync_exact = True
                return wn[0], wn[1]
        n = extras.surah_of_title(Player.cur_title)
        if not n:
            return None
        ex = self.exact_ayah(n)
        if ex:
            return n, ex
        pct, txt = self.progress()
        if not txt or txt == u"LIVE":
            return None
        return n, studio.ayah_at(n, pct / 100.0)

    def continue_on_tv(self, sec):
        """The phone stopped at `sec`: carry on from there on the TV."""
        try:
            sec = max(0, int(float(sec)))
        except Exception:
            return
        if Player.active:
            if self.is_paused():
                self.toggle_pause()
            pp = self.play_pos()
            if pp:
                self.seek(sec - int(pp[0]))
        elif self.pl and 0 <= self.pi < len(self.pl):
            self.resume_seek = sec
            self.start_item(self.pl[self.pi])
        popup(u"متابعة الاستماع على التلفاز", 3)

    def hifz_play(self):
        st = studio.hifz_state(self.cfg)
        self.ctx = None
        self.play_list(studio.hifz_items(st), 0)

    DAY_SURAHS = [36, 55, 67, 56, 19, 12, 18, 2, 3, 25, 31, 50, 73, 76, 89, 93, 94, 97, 112, 1, 20, 14, 17]

    def reciter_of_day(self, ts=None):
        """-> (name, surah, url, read_id or None) - a different reciter every day (exact ayah sync)."""
        lt = time.localtime(ts)
        day = extras.day_index(ts)
        n = 18 if lt.tm_wday == 4 else self.DAY_SURAHS[day % len(self.DAY_SURAHS)]
        reads = [r for r in (self.timing_reads_list or []) if r["count"] >= 114]
        if reads:
            r = reads[(day * 7) % len(reads)]
            return r["name"], n, "%s%03d.mp3" % (r["folder"], n), r["id"]
        kws = [k for k, _e in data.ALT_EDITIONS if not k.isascii()] if hasattr(str, "isascii") else [u"العفاسي"]
        k = kws[day % len(kws)]
        url, _kw = data.alt_surah_url(k, n)
        return k, n, url, None

    def play_reciter_of_day(self):
        name, n, url, read = self.reciter_of_day()
        item = {"title": u"%s - سورة %s" % (name, data.surah_name(n)), "url": url, "n": n, "autonext": False}
        if read:
            item["timing"] = read
        self.ctx = None
        self.play_list([item], 0)

    def reciter_of_day_text(self):
        name, n, _u, _r = self.reciter_of_day()
        return u"قارئ اليوم: %s - سورة %s" % (name, data.surah_name(n))

    # -- nightly check of the sources ---------------------------------------------------------
    def health_urls(self):
        urls = {"mp3q_reciters": data.MP3Q_RECITERS[0], "mp3q_radios": data.MP3Q_RADIOS[0],
                "qcom": "https://api.quran.com/api/v4/chapters?language=ar", "sq_reciters": "https://surahquran.com/",
                "sq_radios": "https://surahquran.com/", "islam": "https://audio.islamweb.net/audio/index.php?page=qareelast",
                "way_reciters": "https://way2quran.com/ar/reciters", "way_iconic": "https://way2quran.com/ar/reciters",
                "qpedia": data.QPEDIA_RECITERS[0], "tvq": data.TVQ_BASE + "/ar/scholar/94/profile/",
                "assabile": data.AS_BASE + "/quran", "ourq": data.OQ_BASE + "/", "sync": data.TIMING_READS[0]}
        for u, _n in tg_channels(self.cfg):
            urls["tg:" + u] = data.TG_PAGE % u
        hidden = set(self.cfg.get("hidden_secs", []))
        return dict((k, v) for k, v in urls.items() if k not in hidden)

    def health_check(self, notify=True):
        urls = self.health_urls()
        self.set_status(u"جاري فحص المصادر (%d) ..." % len(urls))

        def job():
            res = {}
            for k, u in urls.items():
                try:
                    nb, secs = diag._peek(u, 1024, timeout=12)
                    res[k] = [nb > 0, int(time.time()), u"%.1f ث" % secs]
                except Exception as e:
                    res[k] = [False, int(time.time()), (u"%s" % e)[:80]]
            return res

        def done(res):
            if isinstance(res, Exception):
                return
            self.cfg["src_health"] = res
            self.cfg["src_health_seen"] = ""
            self.save()
            bad = self.health_bad()
            if self.ui is not None:
                try:
                    self.ui.apply(0)
                except Exception:
                    pass
            if notify:
                self.set_status(u"فحص المصادر: %s" % (
                    (u"متوقف: " + u"، ".join(bad)) if bad else u"كل المصادر تعمل"), notify=bool(bad))
        self.runner.run(job, done, done)

    def health_bad(self):
        names = dict((s[0], s[1]) for s in SECTIONS)
        return [names.get(k, k) for k, v in sorted((self.cfg.get("src_health") or {}).items()) if not v[0]]

    fajr_timer = None
    _c7 = None

    def fajr_wake_now(self):
        """Leave standby, then the adhan and the chosen surah with a soft volume rise."""
        self.tg_notify(u"🕌 حان وقت صلاة الفجر")
        woke = False
        try:
            from Screens.Standby import inStandby
            if inStandby is not None:
                inStandby.Power()
                woke = True
        except Exception as e:
            qlog("fajr wake: %s" % e)
        if self.fajr_timer is None:
            self.fajr_timer, self._c7 = make_timer(self.fajr_play)
        self.fajr_timer.start(9000 if woke else 500, True)       # let the TV come back first

    def fajr_play(self):
        items = []
        src = extras.adhan_source(self.cfg)
        if src:
            url = src[0] if src[0].startswith("http") or src[0].startswith("file://") else "file://" + src[0]
            items.append({"title": u"أذان الفجر", "url": url, "autonext": True, "nohist": True})
        n = int(self.cfg.get("fajr_surah", 1))
        r = self.cfg.get("resume") or {}
        name = studio.title_reciter(r.get("title")) if r.get("title") else u""
        url, kw = data.alt_surah_url(name, n)
        items.append({"title": u"%s - سورة %s" % (name if kw and name else u"مشاري العفاسي", data.surah_name(n)),
                      "url": url, "n": n, "autonext": False})
        vol0 = self.get_volume()
        self.ctx = None
        self.play_list(items, 0)
        try:
            self.set_volume(max(5, int(vol0 * 0.3)))
            self.start_ramp(vol0)
        except Exception as e:
            qlog("fajr ramp: %s" % e)
        popup(u"الصلاة خير من النوم - أذان الفجر", 8)

    def season_tick(self, now):
        lt = time.localtime(now)
        hm = "%02d:%02d" % (lt.tm_hour, lt.tm_min)
        today = time.strftime("%Y-%m-%d", lt)
        fired = self.cfg.setdefault("season_fired", {})
        if self.cfg.get("fajr_wake") and self.cfg.get("prayer_city") and fired.get("fajr") != today:
            if studio.fajr_hm(self.cfg["prayer_city"], now) == hm:
                fired["fajr"] = today
                self.save()
                self.fajr_wake_now()

        def due(key):
            if self.cfg.get(key) == hm and fired.get(key) != today:
                fired[key] = today
                self.save()
                return True
            return False
        if due("wird_time"):
            self.wird_remind()
            self.tg_notify(u"📖 حان وقت وردك اليومي")
        if (self.cfg.get("gh_update", True) and not private_edition()
                and now - float(self.cfg.get("gh_checked", 0) or 0) > 86400 and time.time() - self.boot > 120):
            self.gh_check()
        if due("tg_ayah_time"):
            if self.bot is not None:
                for o in self.tg_owners():
                    self.bot.send(o["id"], u"🌅 آية اليوم\n" + self.tg_ayah_text())
        if self.cfg.get("auto_backup", True) and not Player.active and \
                now - float(self.cfg.get("auto_backup_at", 0) or 0) > 7 * 86400 and lt.tm_hour in (3, 4, 13, 14):
            self.cfg["auto_backup_at"] = now
            try:
                extras.backup_settings(self.cfg)
            except Exception as e:
                qlog("auto backup: %s" % e)
            self.save()
        hh = self.cfg.get("health_time", "04:00")
        if hh and hh == hm and fired.get("health") != today and not Player.active:
            fired["health"] = today
            self.save()
            self.health_check(notify=False)
        if lt.tm_wday == 4 and due("kahf_time"):
            self.play_surah(18, u"الجمعة: سورة الكهف")
        if due("mulk_time"):
            self.play_surah(67, u"قبل النوم: سورة الملك")
            self.sleep_min = 20
            self.sleep_at = now + 20 * 60

    def play_surah(self, n, why=u""):
        r = self.cfg.get("resume") or {}
        name = studio.title_reciter(r.get("title")) if r.get("title") else u""
        url, kw = data.alt_surah_url(name, n)
        rec = name if kw and name else u"مشاري العفاسي"
        self.ctx = None
        self.play_list([{"title": u"%s - سورة %s" % (rec, data.surah_name(n)), "url": url, "n": n,
                         "autonext": False}], 0)
        if why:
            popup(why, 6)

    def wird_remind(self):
        k = studio.khatma_state(self.cfg)
        j = studio.khatma_juz(k)
        text = u"حان وقت وردك اليومي: %d صفحة تبدأ من الجزء %d (%s).\n\nافتح المصحف الآن؟" % (
            studio.khatma_daily(k), j, data.surah_name(extras.juz_surah(j)))

        def answer(ok=None):
            if ok:
                try:
                    self.session.open(QHReader, extras.juz_surah(j), "mushaf")
                except Exception as e:
                    qlog("wird open: %s" % e)
        try:
            from Tools import Notifications
            from Screens.MessageBox import MessageBox
            Notifications.AddNotificationWithCallback(answer, MessageBox, text, MessageBox.TYPE_YESNO, timeout=120)
        except Exception:
            popup(text, 15)

    def stats_tick(self, now):
        dt, self._st_last = now - self._st_last, now
        if Player.active and 0 < dt <= 30 and self.adhan_prev is None and not self.is_paused():
            studio.stats_add(self.cfg, Player.cur_title, dt, now)
            if now - self._st_saved >= 180:
                self._st_saved = now
                self.save()

    def extras_tick(self):
        now = time.time()
        self.stats_tick(now)
        if Player.active and not self.cur_live and self.cur_url and now - self.pos_saved >= 60:
            self.pos_saved = now
            self.spos_save()
            self.save_resume()
        try:
            self.speed_tick()
        except Exception as e:
            qlog("speed tick: %r" % (e,))
        if self.resume_seek and Player.active and self.play_ok and self.t0 and now - self.t0 > 2:
            pos, self.resume_seek = self.resume_seek, 0
            self.seek(pos)
        if self.ov_check_at and now >= self.ov_check_at:
            self.ov_check_at = 0
            if self.overlay_active and Player.active and self.mute_failed:
                if self.tv_mode() == "auto":
                    self.cfg["overlay_bad"] = True        # remember: this box cannot do it
                    self.save()
                self.overlay_fallback(u"تعذّر كتم صوت القناة على هذا الجهاز")
        if self.rec_stop_at and now >= self.rec_stop_at:
            self.rec_stop_at = 0
            if self.rec is not None and self.rec.stage == "recording" and not self.rec.stopping:
                self.rec.stop()
                self.set_status(u"انتهى وقت التسجيل المجدول", notify=True)
        if self.remote is not None:
            self.remote_tick()
        self.adhan_tick(now)
        self.taf_tick()
        if self.ramp:
            self.ramp_tick(now)
        if self.prayer_paused and now >= self.prayer_resume_at:
            self.prayer_resume()
        if self.dl.errors:
            err = self.dl.errors.pop(0)
            self.set_status(u"فشل التنزيل: %s" % err, notify=True)
        if len(self.dl.done_files) != self.dl_reported:
            self.dl_reported = len(self.dl.done_files)
            if not self.dl.busy():
                self.set_status(u"اكتمل التنزيل (%d ملف)" % self.dl_reported, notify=True)
        m = int(now // 60)
        if m != self.min_tick:
            self.min_tick = m
            for s in extras.sched_due(self.cfg, now, self.sched_fired):
                self.run_schedule(s)
            city = self.cfg.get("prayer_city")
            if city and self.cfg.get("prayer_mode", "notify") != "off":
                due = extras.prayer_due(city, now)
                if due and not (due[0] == "fajr" and self.cfg.get("fajr_wake")):
                    key = (time.strftime("%Y%m%d"), due[0])
                    if key not in self.prayer_fired:
                        self.prayer_fired.add(key)
                        self.prayer_fire(due[1])
            try:
                self.season_tick(now)
            except Exception as e:
                qlog("season: %s" % e)
            if len(self.sched_fired) > 300:
                self.sched_fired.clear()
            if len(self.prayer_fired) > 50:
                self.prayer_fired.clear()

    # -- sleep timer ------------------------------------------------------------------
    def cycle_sleep(self):
        cur = getattr(self, "sleep_min", 0) if self.sleep_at else 0
        nxt = SLEEP_STEPS[(SLEEP_STEPS.index(cur) + 1) % len(SLEEP_STEPS)] \
            if cur in SLEEP_STEPS else 0
        self.sleep_min = nxt
        self.sleep_at = time.time() + nxt * 60 if nxt else None
        self.set_status(u"مؤقت النوم: %s" % (u"%d دقيقة" % nxt if nxt else u"متوقف"))
        self.ensure_timer()
        if self.ui is not None:
            self.ui.qh_labels()

    # -- periodic -----------------------------------------------------------------------
    def tick(self):
        try:
            self.extras_tick()
        except Exception as e:
            qlog("extras_tick: %s" % e)
        r = self.rec
        if r is not None:
            if r.error is not None:
                self.rec = None
                self.set_status(u"فشل التسجيل: %s" % r.error, notify=True)
            elif r.done:
                self.rec = None
                self.set_status(u"تم حفظ التسجيل (%.1f MB): %s %s" % (
                    r.bytes / 1048576.0, r.path, r.note), notify=True)
        if self.sleep_at and time.time() >= self.sleep_at:
            self.stop_all()
            self.set_status(u"انتهى مؤقت النوم - تم إيقاف التشغيل", notify=True)
        if (Player.active and self.live_buf is not None and not self.ts_failed and not self.play_ok
                and self.delay == 0 and self.t0 and time.time() - self.t0 > 14):
            self.ts_fallback()
        if (Player.active and not self.cur_live and not self.play_ok and self.t0
                and not self.paused_at and time.time() - self.t0 > 22 and self.alt_tried is None):
            self.try_alt_source(u"لم يبدأ التشغيل")
        if Player.active:
            self.sample_net()
            if self.is_live() and len(self.rx_hist) >= 5 and self.rate < 1.0 and self.rx_base is not None:
                self.stall += 1
                if self.stall >= 25:            # live radio but no data for 25 s
                    self.stall = 0
                    self.reconnect(u"توقف البث")
            else:
                self.stall = 0
        if Player.active and self.overlay_active and Player.sink is not None \
                and Player.sink.backend == "gst" and not Player.sink.alive() and not self.paused_at:
            self.play_event(iPlayableService.evEOF)         # gst-launch process ended
        if self.mini is not None:
            try:
                self.mini.refresh(self.minibar_text())
            except Exception:
                pass
        if self.tv_want:
            self.tv_tick += 1
            if self.tv_refresh_in > 0:
                self.tv_refresh_in -= 1
                if self.tv_refresh_in == 0:
                    self.tv_refresh()
            if self.tv_tick % 3 == 0:
                self.tv_check()
        if not (Player.active or self.rec is not None or self.sleep_at or self.tv_want or self.keep_alive()):
            if self.timer is not None:
                self.timer.stop()
        if self.ui is not None:
            self.ui.qh_labels()


def video_plane_undo():
    """Put back 0,0,0,0 (the box default seen in the log) when 1.0 wrote 720x576 over it."""
    vals = {}
    for name in ("dst_left", "dst_top", "dst_width", "dst_height"):
        try:
            with open("/proc/stb/vmpeg/0/" + name) as f:
                vals[name] = int(f.read().strip() or "0", 16)
        except Exception:
            return None
    if vals != {"dst_left": 0, "dst_top": 0, "dst_width": 720, "dst_height": 576}:
        return False
    for name in ("dst_width", "dst_height", "dst_left", "dst_top"):
        try:
            with open("/proc/stb/vmpeg/0/" + name, "w") as f:
                f.write("%08x" % 0)
        except Exception:
            pass
    qlog("video plane: 1.0 values undone (back to automatic)")
    return True


class QHVideo(Screen):
    """A see-through screen in front of everything while a Telegram video plays.
    Any key closes it (and stops the video); left / right previous / next."""

    def __init__(self, session):
        th = THEMES[BG.theme_idx()]
        self.skin = (u'<screen name="QuranHubVideo" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="#ff000000">'
                     u'<widget name="vd_bar" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                     u'foregroundColor="#ffffff" backgroundColor="#30000000" zPosition="2" />'
                     u'</screen>') % (p(1280), p(720), p(140), p(652), p(1000), p(44), p(19))
        Screen.__init__(self, session)
        self.skinName = "QuranHubVideo"
        self["vd_bar"] = Label(u"")
        keys = {"cancel": self.close_video, "ok": self.close_video, "red": self.close_video,
                "green": self.close_video, "yellow": self.close_video, "blue": self.close_video,
                "up": self.close_video, "down": self.close_video,
                "left": lambda: BG.step(1), "right": lambda: BG.step(-1)}
        for k in "0123456789":
            keys[k] = self.close_video
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions", "NumberActions"], keys, -1)
        self["qh_seek"] = ActionMap(["InfobarSeekActions"], {"seekBack": lambda: BG.seek(-15),
                                                              "seekFwd": lambda: BG.seek(15),
                                                              "playpauseService": BG.toggle_pause}, -1)
        self.qh_timer, self._c = make_timer(self.tick)
        self.qh_hide_at = time.time() + 6
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        BG.video_screen = self
        BG.hide_minibar()
        self.apply()
        self.qh_timer.start(1000, False)

    def apply(self):
        self.hint(u"%s   •   ◀▶ التالي / السابق   •   أي زر آخر: إغلاق" % (
            (Player.cur_title or u"").split(u" - ", 1)[-1][:60]))

    def hint(self, text):
        self["vd_bar"].setText(text)
        self["vd_bar"].show()
        self.qh_hide_at = time.time() + 6

    def tick(self):
        if not Player.active or not BG.cur_video:
            return self.close()
        if self.qh_hide_at and time.time() > self.qh_hide_at:
            self.qh_hide_at = 0
            self["vd_bar"].hide()

    def close_video(self):
        BG.stop_play()
        self.close()

    def cleanup(self):
        self.qh_timer.stop()
        if BG.video_screen is self:
            BG.video_screen = None


class QHMiniBar(Screen):
    """Small floating bar (top-left): what is playing, data used, stability."""
    stand_alone = True
    skin = _build_minibar_skin(0)

    def __init__(self, session, bg):
        self.skin = _build_minibar_skin(bg.theme_idx())
        Screen.__init__(self, session)
        self.qh_bg = bg
        self["qh_mb"] = Label(u"")
        self["actions"] = ActionMap(
            ["InfobarSeekActions"],
            {"seekBack": self.k_back, "seekFwd": self.k_fwd,
             "playpauseService": self.k_pause, "pauseService": self.k_pause,
             "unPauseService": self.k_pause}, -1)

    def refresh(self, text):
        self["qh_mb"].setText(text)

    def remote_on(self):
        return self.qh_bg.cfg.get("remote", True) and Player.active

    def k_back(self):
        if self.remote_on():
            self.qh_bg.seek(-30)

    def k_fwd(self):
        if self.remote_on():
            self.qh_bg.seek(30)

    def k_pause(self):
        if self.remote_on():
            self.qh_bg.toggle_pause()


_start_item_33 = Background.start_item


def _start_item_kept(self, item):
    """2.0: a kept copy on the disk plays instead of the internet file (start_item itself is unchanged)."""
    try:
        if item.get("url") and not item.get("live"):
            u = self.cache_swap(item["url"], item.get("title", u""), False)
            if u != item["url"]:
                item = dict(item, url=u)
    except Exception as e:
        qlog("kept copy: %r" % (e,))
    return _start_item_33(self, item)


Background.start_item = _start_item_kept

BG = Background()


# ------------------------------------------------------------------ screen
QFONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_QF_STATE = []


def register_quran_fonts():
    """Register the two reading fonts (Amiri-based, OFL) with enigma2 once."""
    if _QF_STATE:
        return _QF_STATE[0]
    ok = False
    try:
        from enigma import addFont
        for v in ("A", "B"):
            pth = os.path.join(QFONT_DIR, "SaadQuran%s.ttf" % v)
            if os.path.exists(pth):
                addFont(pth, "SaadQuran%s" % v, 100, False)
                ok = True
    except Exception as e:
        qlog("addFont: %s" % e)
    _QF_STATE.append(ok)
    return ok


def img_text():
    """1.4: Quran / tafsir lines are drawn as pictures (qtext) - the receiver's text engine is not used."""
    if BG.cfg.get("quran_font", "img") != "img" or os.environ.get("SQH_TEXT_ENGINE") == "font":
        return False
    try:
        return qtext.available()
    except Exception:
        return False


_PIX_ERR = []
_PIXC = {}


def text_pixmap(text, px, color, h, colors=None, justify=None):
    """-> (pixmap, width) of one line drawn by qtext, or (None, 0) when anything fails."""
    try:
        from Tools.LoadPixmap import LoadPixmap
        path, w, _h = qtext.render(text, px, color, h, colors, justify)
        pix = _PIXC.get(path)
        if pix is None:
            try:
                pix = LoadPixmap(path, cached=False)
            except TypeError:
                pix = LoadPixmap(path)
            if len(_PIXC) > 40:              # about three pages of decoded lines stay in memory
                for k in list(_PIXC)[:15]:
                    del _PIXC[k]
            _PIXC[path] = pix
        return pix, w
    except Exception as e:
        if not _PIX_ERR:
            qlog("qtext: %r" % (e,))
        _PIX_ERR.append(1)
        return None, 0


def tajweed_on():
    return bool(BG.cfg.get("tajweed", True)) and img_text()


def img_entry(text, w, h, color, back=None, align="right", px=None, colors=None, justify=None, mark=None):
    """MultiContent row parts showing one line of Arabic as a picture (falls back to plain text).
    justify: stretch to this width (printed-mushaf lines);  mark: (word number in the line, colour)
    puts a coloured band behind one word - drawn by the receiver, the picture is not redrawn."""
    px = px or int(h / 1.85)
    parts = []
    if back is not None:
        parts.append(MultiContentEntryText(pos=(0, 0), size=(w, h), font=0, text=u"",
                                           backcolor=back, backcolor_sel=back))
    if not text.strip():
        return parts or [MultiContentEntryText(pos=(0, 0), size=(w, h), font=0, text=u"")]
    pix, iw = text_pixmap(text, px, color, h, colors, justify)
    if pix is None:
        kw = dict(pos=(0, 0), size=(w, h), font=0, text=extras.shape_arabic(text, "medial"),
                  flags=(RT_HALIGN_CENTER if align == "center" else RT_HALIGN_RIGHT) | RT_VALIGN_CENTER,
                  color=color, color_sel=color)
        if back is not None:
            kw.update(backcolor=back, backcolor_sel=back)
        return [MultiContentEntryText(**kw)]
    iw = min(iw, w)
    x = (w - iw) // 2 if align == "center" else max(0, w - iw - p(4))
    if mark is not None:
        try:
            spans = qtext.word_spans(text, px)
            wi, mcol = mark
            if 0 <= wi < len(spans):
                off, ww = spans[wi]
                pad = max(4, px // 6)
                right = x + iw
                parts.append(MultiContentEntryText(pos=(max(0, right - off - ww - pad), max(0, h // 10)),
                                                   size=(ww + 2 * pad, h - 2 * max(0, h // 10)), font=0, text=u"",
                                                   backcolor=mcol, backcolor_sel=mcol))
        except Exception as e:
            qlog("word mark: %r" % (e,))
    parts.append(_PixEntry(pos=(x, 0), size=(iw, h), png=pix))
    return parts


def line_tajweed(text, nxt=u""):
    """Tajweed colours of one line (the first word of the next line is looked at for the rules
    that join two words)."""
    try:
        full = text + (u" " + nxt.split()[0] if nxt and nxt.split() else u"")
        n = len(text)
        return dict((k, v) for k, v in tajweed.colors(full).items() if k < n)
    except Exception as e:
        qlog("tajweed: %r" % (e,))
        return None


def quran_face():
    """Font used for Quran / tafsir text when it is not drawn as pictures."""
    v = BG.cfg.get("quran_font", "img")
    if v in ("A", "B") and register_quran_fonts():
        return "SaadQuran" + v
    return "Regular"


def tashkeel_mode():
    """'keep' with the Quran font (its harakat take no room), 'medial' on the image's font."""
    m = BG.cfg.get("tashkeel")
    if m in ("medial", "keep", "none"):
        return m
    return "keep" if quran_face() != "Regular" else "medial"


QFONT_LABEL = {"img": u"رسم الحروف كصور (الأوضح)", "A": u"خط قرآني (أ)", "B": u"خط قرآني (ب)",
               "off": u"خط الجهاز"}


def _cint(v):
    """'#rrggbb' / '#aarrggbb' / int -> int (for MultiContentEntryText colours)."""
    if isinstance(v, int):
        return v
    v = (v or "#ffffff").lstrip("#")
    return int(v[-6:], 16)


class QHPaged(Screen):
    """Base of every text screen (reader, tafsir, adhkar, quiz).

    The text is drawn as rows of a MenuList (eListboxPythonMultiContent) - exactly the widget the
    library columns use, which renders on every image.  A 'message box' engine is kept as a
    last-resort fallback (setting reader_engine = msgbox)."""
    FONTS = [26, 32, 38, 44]
    MAXROWS = 16
    TEXT_W = 1180
    HINT = u"◀ ▶ صفحة  •  7/9 حجم الخط  •  EXIT رجوع"

    @classmethod
    def geometry(cls, fs):
        rowh = int(fs * 1.6)
        return rowh, max(4, min(cls.MAXROWS, 548 // rowh))

    JUSTIFY = False

    def page_theme(self, th):
        return th

    def style_line(self, text, role, fg, back):
        """-> (text, fg, back, align) of one line (the mushaf decorates its surah titles)."""
        return text, fg, back, "right"

    def _setup(self, session, title):
        BG.attach(session)
        th = self.page_theme(THEMES[BG.theme_idx()])
        self.qh_th = th
        self.qh_bgc = "#101418" if th["bg"] == "transparent" else th["bg"]
        self.qh_fi = min(len(self.FONTS) - 1, max(0, int(BG.cfg.get("reader_font", 1))))
        fs = self.FONTS[self.qh_fi]
        self.qh_fs = fs
        self.qh_rowh, self.qh_rows = self.geometry(fs)
        self.qh_list_h = self.qh_rowh * self.qh_rows
        self.skin = self._skin(th, fs)
        Screen.__init__(self, session)
        self.skinName = "QuranHubText31"
        self.qh_engine = BG.cfg.get("reader_engine", "list")
        self.qh_pages, self.qh_pg = [[(u"", set(), False)]], 0
        self.qh_hl = None                 # block index to highlight
        self.qh_hl_roles = None           # restrict the highlight to these line roles
        self["rd_title"] = Label(title)
        lst = MenuList([], False, eListboxPythonMultiContent)
        lst.l.setFont(0, gFont(quran_face(), p(fs)))
        lst.l.setItemHeight(p(self.qh_rowh))
        self["rd_list"] = lst
        self["rd_info"] = Label(u"")
        self["rd_hint"] = Label(self.HINT)
        self["rd_leg"] = Pixmap()
        self.onClose.append(self._stop_bg)

    @classmethod
    def _skin(cls, th, fs):
        bgc = "#101418" if th["bg"] == "transparent" else th["bg"]
        rowh, rows = cls.geometry(fs)
        o = [u'<screen name="QuranHubText31" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (
            p(1280), p(720), bgc)]
        o.append(u'<eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="0" />' % (p(1280), p(66), th["bar"]))
        o.append(u'<eLabel position="0,%d" size="%d,%d" backgroundColor="%s" zPosition="0" />' % (p(66), p(1280), p(3), th["line"]))
        o.append(u'<widget name="rd_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="#ffffff" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                     p(20), p(4), p(1240), p(58), p(32), th["bar"]))
        o.append(u'<widget name="rd_list" position="%d,%d" size="%d,%d" scrollbarMode="showNever" '
                 u'backgroundColor="%s" foregroundColor="%s" backgroundColorSelected="%s" foregroundColorSelected="%s" '
                 u'zPosition="1" />' % (p(50), p(80), p(cls.TEXT_W), p(rowh * rows), bgc, th["text"], bgc, th["text"]))
        o.append(u'<widget name="rd_info" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                     p(20), p(636), p(1240), p(34), p(21), th["dim"], bgc))
        o.append(u'<widget name="rd_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                     p(20), p(676), p(1240), p(34), p(17), th["dim"], bgc))
        o.append(u'<widget name="rd_leg" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="2" />' % (
            p(20), p(676), p(1240), p(34)))
        o.append(u'</screen>')
        return u"".join(o)

    # -- drawing --------------------------------------------------------------------------------
    def cpl(self):
        return max(18, int(self.TEXT_W / (self.qh_fs * 0.52)))

    def img_px(self):
        return int(p(self.qh_rowh) / 1.85)

    def img_meas(self):
        if not img_text():
            return None
        try:
            px = self.img_px()
            sp = qtext.atlas(px)["space"]
            return (lambda w: qtext.line_width(w, px), p(self.TEXT_W) - p(12), sp)
        except Exception as e:
            qlog("qtext meas: %r" % (e,))
            return None

    def paginate(self, blocks, flow=False, heads=False, upto_block=None):
        """Long books (a big tafsir) are cut into pages a part at a time: the pages needed now are
        ready at once, the rest is done in the background in small steps."""
        meas = self.img_meas()
        self.qh_pgen = getattr(self, "qh_pgen", 0) + 1
        big = meas is not None and not flow and len(blocks) > 30 and sum(len(b) for b in blocks) > 25000
        if not big:
            self.qh_paging = False
            self._set_pages(extras.wrap_tagged(blocks, self.cpl(), flow=flow, heads=heads, meas=meas))
            return
        self.qh_pst = {"blocks": blocks, "k": 0, "heads": heads, "meas": meas, "lines": [], "gen": self.qh_pgen}
        self.qh_paging = True
        need = (self.qh_pg + 3) * self.qh_rows
        st = self.qh_pst
        self._wrap_more(lambda: len(st["lines"]) >= need and (upto_block is None or st["k"] > upto_block + 1))
        self._set_pages(st["lines"])
        if self.qh_paging:
            if not getattr(self, "qh_ptimer", None):
                self.qh_ptimer, self.qh_ptimer_c = make_timer(self._page_bg)
            self.qh_ptimer.start(60, False)

    def _wrap_more(self, stop, budget=None):
        st = self.qh_pst
        blocks, cpl = st["blocks"], self.cpl()
        t0 = time.time()
        while st["k"] < len(blocks):
            if stop():
                return
            if budget is not None and time.time() - t0 > budget:
                return
            k = st["k"]
            st["lines"].extend(extras.wrap_tagged(blocks[k:k + 1], cpl, heads=st["heads"], meas=st["meas"],
                                                  offset=k, trim=False))
            st["k"] = k + 1
        lines = st["lines"]                   # finished
        while lines and not lines[-1][0]:
            lines.pop()
        self.qh_paging = False

    def _page_bg(self):
        st = getattr(self, "qh_pst", None)
        if not st or st["gen"] != getattr(self, "qh_pgen", 0) or not self.qh_paging:
            self.qh_ptimer.stop()
            return
        self._wrap_more(lambda: False, budget=0.06)
        self._set_pages(st["lines"])
        try:
            self["rd_info"].setText(self.info_text())
        except Exception:
            pass
        if not self.qh_paging:
            self.qh_ptimer.stop()

    def ensure_page(self, k):
        """Make sure page k exists (cut more pages now if the background has not got there yet)."""
        if getattr(self, "qh_paging", False):
            st = self.qh_pst
            need = (k + 1) * self.qh_rows
            self._wrap_more(lambda: len(st["lines"]) >= need)
            self._set_pages(st["lines"])

    def _stop_bg(self):
        try:
            qtext.save_widths()
        except Exception:
            pass
        for name in ("qh_pre", "qh_ptimer"):
            tm = getattr(self, name, None)
            if tm is not None:
                try:
                    tm.stop()
                except Exception:
                    pass
        self.qh_preq = []
        self.qh_paging = False

    def _set_pages(self, lines):
        r = self.qh_rows
        self.qh_pages = [lines[i:i + r] for i in range(0, len(lines), r)] or [[(u"", set(), False)]]
        self.qh_pg = max(0, min(self.qh_pg, len(self.qh_pages) - 1))

    def total_text(self):
        return u"%d%s" % (len(self.qh_pages), u"+" if getattr(self, "qh_paging", False) else u"")

    def line_specs(self, lines, pic=None):
        """-> [(text, fg, back, tajweed colours)] for a page (shared by drawing and pre-drawing)."""
        th = self.qh_th
        txt, gold, bg = _cint(th["text"]), _cint(th["gold"]), _cint(self.qh_bgc)
        num = _cint(th["line"]) if _cint(th["line"]) != gold else 0x58d68d
        hlbg = _cint(th["sel"])
        pic = img_text() if pic is None else pic
        tj_roles = self.tajweed_roles() if (pic and tajweed_on()) else None
        plain = [(x if isinstance(x, tuple) else (x, set(), 0)) for x in lines]
        out = []
        for li, ln in enumerate(plain):
            text, tags, role = ln
            role = int(role or 0)
            hl = self.qh_hl is not None and self.qh_hl in tags
            if hl and self.qh_hl_roles and role not in self.qh_hl_roles:
                hl = False                  # tafsir: only the number and the ayah are highlighted
            fg = num if role == 2 else (gold if (hl or role == 1) else txt)
            back = hlbg if hl else bg
            cols = None
            if tj_roles is not None and role in tj_roles and text.strip():
                nxt = plain[li + 1][0] if li + 1 < len(plain) and int(plain[li + 1][2] or 0) == role else u""
                cols = line_tajweed(text, nxt)
                if cols and self.light_page():
                    cols = dict((k, tajweed.ON_PAPER.get(v, v)) for k, v in cols.items())
            just = None
            if self.JUSTIFY and pic and role == 0 and text.strip():
                if li + 1 < len(plain):
                    nr = int(plain[li + 1][2] or 0)
                    ok_ = nr == 0 and plain[li + 1][0].strip()
                else:
                    ok_ = self.qh_pg < len(self.qh_pages) - 1
                if ok_:
                    just = p(self.TEXT_W) - p(10)
            text, fg, back, align = self.style_line(text, role, fg, back)
            out.append((text, fg, back, cols, align, just))
        return out

    def set_lines(self, lines):
        """lines: plain strings or (text, tags, is_head) tuples."""
        shape = BG.cfg.get("arabic_shape", True)
        rows = []
        w, h = p(self.TEXT_W), p(self.qh_rowh)
        pic = img_text()
        px = self.img_px()
        for text, fg, back, cols, align, just in self.line_specs(lines, pic):
            if pic:
                rows.append([None] + img_entry(text, w, h, fg, back=back, px=px, colors=cols, align=align,
                                               justify=just))
                continue
            if shape:
                text = extras.shape_arabic(text, tashkeel_mode())
            rows.append([None, MultiContentEntryText(pos=(0, 0), size=(w, h), font=0,
                                                     flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=text,
                                                     color=fg, color_sel=fg, backcolor=back, backcolor_sel=back)])
        self["rd_list"].setList(rows)
        try:
            self["rd_list"].instance.setSelectionEnable(0)
        except Exception:
            pass
        self.qh_shown = [x[0] if isinstance(x, tuple) else x for x in lines]

    def tajweed_roles(self):
        """Line roles that are Quran text (None = no tajweed colouring on this screen)."""
        return None

    def light_page(self):
        try:
            c = _cint(self.qh_bgc)
            return ((c >> 16) & 255) + ((c >> 8) & 255) + (c & 255) > 500
        except Exception:
            return False

    def show_legend(self):
        """Colour key of the tajweed rules, drawn in the hint row."""
        try:
            leg = self["rd_leg"]
            if not (img_text() and tajweed_on() and self.tajweed_roles() is not None):
                leg.hide()
                self["rd_hint"].show()
                return
            names = [(n, tajweed.ON_PAPER.get(c, c) if self.light_page() else c) for _k, n, c in tajweed.RULES]
            text = u"   ".join(u"• " + n for n, _c in names)
            cols, pos = {}, 0
            for n, c in names:
                for k in range(len(u"• " + n)):
                    cols[pos + k] = c
                pos += len(u"• " + n) + 3
            h = p(34)
            pix, iw = text_pixmap(text, int(h / 1.7), 0xffffff, h, cols)
            if pix is None:
                return
            leg.instance.setPixmap(pix)
            leg.instance.resize(eSize(iw, h))
            leg.instance.move(ePoint(max(0, (p(1280) - iw) // 2), p(676)))
            self["rd_hint"].hide()
            leg.show()
        except Exception as e:
            qlog("legend: %r" % (e,))

    def toggle_tajweed(self):
        BG.cfg["tajweed"] = not BG.cfg.get("tajweed", True)
        BG.save()
        popup(u"تلوين أحكام التجويد: %s" % (u"يعمل" if BG.cfg["tajweed"] else u"متوقف"), 2)
        self.paint()

    def page_text(self):
        return u"\n".join(t for t, _g, _h in self.qh_pages[self.qh_pg])

    def info_text(self):
        return u"صفحة %d / %s" % (self.qh_pg + 1, self.total_text())

    def paint(self):
        self.set_lines(self.qh_pages[self.qh_pg])
        self["rd_info"].setText(self.info_text())
        self.show_legend()
        if self.qh_engine == "msgbox":
            self.msg_show()
        if img_text():                      # draw the pages around this one in the background
            try:
                q = []
                for d in (1, -1, 2):
                    k = self.qh_pg + d
                    if 0 <= k < len(self.qh_pages):
                        q += [s for s in self.line_specs(self.qh_pages[k], True) if s[0].strip()]
                self.qh_preq = q
                if not getattr(self, "qh_pre", None):
                    self.qh_pre, self.qh_pre_c = make_timer(self.prerender)
                self.qh_pre.start(250, False)
            except Exception:
                pass

    def prerender(self):
        """One line per tick, so the remote keys are never kept waiting."""
        try:
            q = getattr(self, "qh_preq", None)
            if not q:
                self.qh_pre.stop()
                return
            text, fg, _back, cols, _al, just = q.pop(0)
            qtext.render(text, self.img_px(), fg, p(self.qh_rowh), cols, just)
            self.qh_pre.start(30, False)
        except Exception:
            try:
                self.qh_pre.stop()
            except Exception:
                pass

    # -- message-box engine (fallback) ------------------------------------------------------
    def msg_show(self):
        if getattr(self, "qh_msg_open", False):
            return
        try:
            from Screens.MessageBox import MessageBox
            self.qh_msg_open = True
            self.session.openWithCallback(
                self.msg_done, MessageBox, u"%s\n%s\n\n%s\n\nOK الصفحة التالية   •   EXIT خروج" % (
                    self["rd_title"].getText(), self.info_text(),
                    extras.shape_arabic(self.page_text(), tashkeel_mode())
                    if BG.cfg.get("arabic_shape", True) else self.page_text()),
                MessageBox.TYPE_INFO)
        except Exception as e:
            qlog("msg engine: %s" % e)

    def msg_done(self, res=None):
        self.qh_msg_open = False
        if res:
            self.next_page()
        else:
            self.close()

    def font(self, d):
        fi = max(0, min(len(self.FONTS) - 1, self.qh_fi + d))
        if fi == self.qh_fi:
            return
        self.qh_fi = fi
        BG.cfg["reader_font"] = fi
        BG.save()
        fs = self.FONTS[fi]
        self.qh_fs = fs
        self.qh_rowh = int(fs * 1.6)
        self.qh_rows = max(3, self.qh_list_h // self.qh_rowh)
        lst = self["rd_list"]
        try:
            lst.l.setFont(0, gFont(quran_face(), p(fs)))
            lst.l.setItemHeight(p(self.qh_rowh))
        except Exception as e:
            qlog("font: %s" % e)
        self.refit()

    def cycle_quran_font(self):
        order = ["img", "A", "B", "off"]
        cur = BG.cfg.get("quran_font", "img")
        BG.cfg["quran_font"] = order[(order.index(cur) + 1) % len(order)] if cur in order else "img"
        BG.save()
        try:
            self["rd_list"].l.setFont(0, gFont(quran_face(), p(self.qh_fs)))
        except Exception as e:
            qlog("font switch: %s" % e)
        self.refit()

    def refit(self):
        """Paginate again after a font change (keeps the reading position)."""
        self.paint()

    def close_and_reopen(self):
        self.refit()


class QHReader(QHPaged):
    """Quran text, mushaf style, tafsir (8 books) or translation.  Paged, continues into the next
    surah, remembers the position and highlights the ayah being recited."""
    MODES = [("text", u"النص"), ("mushaf", u"المصحف"), ("tafsir", u"التفسير"), ("translation", u"الترجمة")]
    HINT = (u"◀ ▶ صفحة • 1 نص 2 مصحف 3 تفسير 4 ترجمة • OK تتبّع التلاوة • CH± تصحيح الآية • "
            u"7/9 الخط • 8 سورة 0 جزء • MENU")

    def __init__(self, session, n, mode="text", pg=0, tafsir=None):
        self._setup(session, u"")
        self.qh_n, self.qh_mode = max(1, min(114, int(n))), mode if mode in dict(self.MODES) else "text"
        self.qh_taf = tafsir or BG.cfg.get("reader_tafsir", "muyassar")
        if self.qh_taf not in extras.TAFSIR_BY_KEY:
            self.qh_taf = "muyassar"
        self.qh_runner = Runner()
        self.qh_blocks, self.qh_pg = [], max(0, int(pg))
        self.qh_note = u""
        self.qh_last = False
        self.qh_off = 0
        self.qh_follow = (not pg) and self.playing_here() is not None
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "NumberActions", "InfobarMenuActions",
             "ChannelSelectBaseActions"],
            {"cancel": self.close, "ok": self.toggle_follow,
             "left": self.next_page, "down": self.next_page, "right": self.prev_page, "up": self.prev_page,
             "red": lambda: self.set_mode("text"), "green": lambda: self.set_mode("tafsir"),
             "yellow": lambda: self.set_mode("translation"), "blue": self.toggle_follow,
             "1": lambda: self.set_mode("text"), "2": lambda: self.set_mode("mushaf"),
             "3": lambda: self.set_mode("tafsir"), "4": lambda: self.set_mode("translation"),
             "5": self.menu, "mainMenu": self.menu,
             "7": lambda: self.font(-1), "9": lambda: self.font(1),
             "8": self.pick_surah, "0": self.pick_juz, "6": lambda: open_surah_card(self.session, self.qh_n),
             "nextBouquet": lambda: self.nudge(1), "prevBouquet": lambda: self.nudge(-1)}, -1)
        self.qh_timer, self._c = make_timer(self.follow_tick)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        self.load()
        self.qh_timer.start(1000, False)

    def cleanup(self):
        self.qh_timer.stop()
        self.qh_runner.close()
        self.save_pos(True)

    def save_pos(self, flush=False):
        try:
            BG.cfg["reader_pos"] = {"n": self.qh_n, "mode": self.qh_mode, "pg": self.qh_pg, "taf": self.qh_taf}
            BG.cfg["reader_tafsir"] = self.qh_taf
            if flush:
                BG.save()
        except Exception:
            pass

    def title_text(self):
        mname = dict(self.MODES)[self.qh_mode]
        if self.qh_mode == "tafsir":
            mname = extras.TAFSIR_BY_KEY[self.qh_taf][1]
        return u"سورة %s  -  %s  (الجزء %d)" % (data.surah_name(self.qh_n), mname, extras.juz_of(self.qh_n))

    def load(self):
        self["rd_title"].setText(self.title_text())
        self.set_lines([u"جاري التحميل ..."])
        n, mode, taf = self.qh_n, self.qh_mode, self.qh_taf
        self.qh_runner.run(lambda: extras.reader_load(n, mode, taf), self.loaded, self.loaded)

    def loaded(self, res):
        if isinstance(res, Exception):
            qlog("reader load failed: %r" % (res,))
            return self.set_lines(extras.wrap_lines(
                [u"تعذّر تحميل النص", u"", u"%s" % res, u"",
                 u"افتح «التشخيص الذاتي» من القائمة لمعرفة السبب."], 60))
        self.qh_blocks, self.qh_note = res
        self.repaginate()
        if self.qh_last:
            self.qh_last = False
            self.ensure_page(10 ** 6)
            self.qh_pg = len(self.qh_pages) - 1
            self.paint()
        if self.qh_follow:
            self.follow_tick(force=True)

    def tajweed_roles(self):
        if self.qh_mode in ("text", "mushaf"):
            return (0, 1)
        return (1,)

    def repaginate(self):
        self.qh_hl_roles = (1, 2) if self.qh_mode in ("tafsir", "translation") else None
        self.paginate(self.qh_blocks, flow=(self.qh_mode == "mushaf"),
                      heads=self.qh_mode in ("tafsir", "translation"))
        self.paint()

    def info_text(self):
        f = u""
        if self.qh_follow:
            f = u"  •  %s%s" % (u"تزامن دقيق" if BG.sync_exact else u"تتبّع التلاوة",
                               u" (تصحيح %+d)" % self.qh_off if self.qh_off else u"")
        book = u""
        if self.qh_mode == "tafsir":
            book = extras.TAFSIR_BY_KEY[self.qh_taf][1] + u"   •   "
        return u"%sصفحة %d / %s%s   •   %s" % (book, self.qh_pg + 1, self.total_text(), f,
                                            self.qh_note.split(u"|")[-1].strip())

    def paint(self):
        QHPaged.paint(self)
        if self.qh_pg % 8 == 0:
            self.save_pos()

    def goto_surah(self, n, last=False, pg=0):
        self.qh_n = (n - 1) % 114 + 1
        self.qh_pg, self.qh_last = pg, last
        self.qh_hl = None
        self.load()

    def next_page(self):
        self.qh_follow = False
        self.ensure_page(self.qh_pg + 1)
        if self.qh_pg >= len(self.qh_pages) - 1:
            return self.goto_surah(self.qh_n + 1)
        self.qh_pg += 1
        self.paint()

    def prev_page(self):
        self.qh_follow = False
        if self.qh_pg <= 0:
            return self.goto_surah(self.qh_n - 1, last=True)
        self.qh_pg -= 1
        self.paint()

    def set_mode(self, mode):
        if mode != self.qh_mode:
            self.qh_mode, self.qh_pg = mode, 0
            self.load()

    def refit(self):
        first = None
        try:
            for _t, tags, _r in self.qh_pages[self.qh_pg]:
                if tags:
                    first = min(tags)
                    break
        except Exception:
            pass
        self.paginate(self.qh_blocks, flow=(self.qh_mode == "mushaf"),
                      heads=self.qh_mode in ("tafsir", "translation"), upto_block=first)
        if first is not None:
            for i, pg in enumerate(self.qh_pages):
                if any(first in tags for _t, tags, _r in pg):
                    self.qh_pg = i
                    break
        self.paint()

    # -- following the recitation -------------------------------------------------------------
    def playing_here(self):
        """-> (surah, exact_ayah_or_None) of what is playing, or None."""
        if not Player.active:
            return None
        try:
            item = BG.pl[BG.pi] if BG.pl and 0 <= BG.pi < len(BG.pl) else {}
        except Exception:
            item = {}
        if item.get("ayah"):
            return int(item["ayah"][0]), int(item["ayah"][1])
        if BG.cur_live:
            return None
        n = extras.surah_of_title(Player.cur_title)
        return (n, None) if n else None

    def current_ayah(self):
        ph = self.playing_here()
        if ph is None:
            return None
        n, a = ph
        if a is not None:
            return n, a
        ex = BG.exact_ayah(n)
        if ex:
            return n, max(1, min(studio.ayah_counts()[n - 1], ex + self.qh_off))
        pct, txt = BG.progress()
        if not txt or txt == u"LIVE":
            return None
        return n, studio.ayah_at(n, pct / 100.0, self.qh_off)

    def block_of(self, a):
        head = 1 if (self.qh_mode == "mushaf" and self.qh_n not in (1, 9)) else 0
        return a - 1 + head

    def ayah_of_block(self, b):
        head = 1 if (self.qh_mode == "mushaf" and self.qh_n not in (1, 9)) else 0
        return max(1, b + 1 - head)

    def follow_tick(self, force=False):
        if not self.qh_follow:
            return
        cur = self.current_ayah()
        if cur is None:
            return
        n, a = cur
        if n != self.qh_n:
            return self.goto_surah(n)
        bi = self.block_of(a)
        if bi == self.qh_hl and not force:
            return
        self.qh_hl = bi
        if getattr(self, "qh_paging", False) and bi is not None:
            st = self.qh_pst
            self._wrap_more(lambda: st["k"] > bi + 1)
            self._set_pages(st["lines"])
        for i, pg in enumerate(self.qh_pages):
            if any(bi in tags for _t, tags, _h in pg):
                self.qh_pg = i
                break
        self.paint()

    def toggle_follow(self):
        if self.playing_here() is None:
            self.qh_follow = False
            self.qh_hl = None
            self["rd_info"].setText(u"لا توجد تلاوة لسورة الآن - شغّل سورة ثم اضغط OK")
            return
        self.qh_follow = not self.qh_follow
        if not self.qh_follow:
            self.qh_hl = None
            self.paint()
        else:
            self.follow_tick(force=True)

    def nudge(self, d):
        self.qh_off += d
        self.qh_follow = True
        self.follow_tick(force=True)

    # -- menus ---------------------------------------------------------------------------------
    def _choose(self, title, opts, cb):
        try:
            from Screens.ChoiceBox import ChoiceBox
            self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
        except Exception as e:
            self["rd_info"].setText(u"%s" % e)

    def menu(self):
        have = extras.tafsir_available(self.qh_taf)
        eng = BG.cfg.get("reader_engine", "list")
        self._choose(u"القراءة والتفسير", [
            (u"اختيار كتاب التفسير (الحالي: %s)" % extras.TAFSIR_BY_KEY[self.qh_taf][1], "taf"),
            (u"تنزيل هذا التفسير للقراءة بدون إنترنت%s" % (u" (موجود)" if have else u""), "dl"),
            (u"اختيار السورة", "surah"), (u"اختيار الجزء", "juz"),
            (u"تتبّع التلاوة وتظليل الآية: %s" % (u"يعمل" if self.qh_follow else u"متوقف"), "follow"),
            (u"حجم الخط +", "f+"), (u"حجم الخط -", "f-"),
            (u"طريقة عرض النص: %s" % (u"قائمة (افتراضي)" if eng == "list" else u"مربعات رسائل"), "engine"),
            (u"وصل الحروف مع التشكيل: %s" % (u"يعمل" if BG.cfg.get("arabic_shape", True) else u"متوقف"), "shape"),
            (u"عرض الحروف: %s  (اضغط للتغيير)" % QFONT_LABEL.get(BG.cfg.get("quran_font", "img"), u""), "qfont"),
            (u"تلوين أحكام التجويد: %s" % (u"يعمل" if BG.cfg.get("tajweed", True) else u"متوقف"), "tajweed"),
            (u"بطاقة السورة (زر 6)", "card"), (u"مشاركة الآية (كود QR للجوال)", "share"),
            (u"التشكيل: %s  (اضغط للتغيير)" % {"medial": u"على خط وصل (لخط الجهاز)", "keep": u"كامل فوق الحروف",
                                               "none": u"بدون تشكيل"}.get(tashkeel_mode()), "tashkeel"),
            (u"المصحف بالصفحات (604 صفحة مثل المطبوع)", "pages")],
            self.menu_done)

    def menu_done(self, c=None):
        if not c:
            return
        k = c[1]
        if k == "taf":
            self.pick_tafsir()
        elif k == "dl":
            BG.tafsir_download(self.qh_taf)
        elif k == "surah":
            self.pick_surah()
        elif k == "juz":
            self.pick_juz()
        elif k == "follow":
            self.toggle_follow()
        elif k == "f+":
            self.font(1)
        elif k == "f-":
            self.font(-1)
        elif k == "engine":
            BG.cfg["reader_engine"] = "msgbox" if BG.cfg.get("reader_engine", "list") == "list" else "list"
            BG.save()
            self.qh_engine = BG.cfg["reader_engine"]
            self.paint()
        elif k == "shape":
            BG.cfg["arabic_shape"] = not BG.cfg.get("arabic_shape", True)
            BG.save()
            self.paint()
        elif k == "tashkeel":
            order = ["keep", "medial", "none"]
            cur = tashkeel_mode()
            BG.cfg["tashkeel"] = order[(order.index(cur) + 1) % 3] if cur in order else "keep"
            BG.save()
            self.paint()
        elif k == "qfont":
            self.cycle_quran_font()
        elif k == "tajweed":
            self.toggle_tajweed()
        elif k == "card":
            open_surah_card(self.session, self.qh_n)
        elif k == "share":
            a = 1
            try:
                for _t, tags, _r in self.qh_pages[self.qh_pg]:
                    if tags:
                        a = self.ayah_of_block(min(tags))
                        break
            except Exception:
                pass
            if self.qh_hl is not None:
                a = self.ayah_of_block(self.qh_hl) or a
            open_share(self.session, self.qh_n, a or 1)
        elif k == "pages":
            n0 = self.qh_n
            self.session.open(QHMushaf, studio.page_of(n0, 1))

    def pick_tafsir(self):
        opts = []
        for key, title, _s, _a, _q, bundled in extras.TAFSIRS:
            tag = u"[على الجهاز] " if extras.tafsir_available(key) else u"[يُنزَّل] "
            opts.append((tag + title, key))
        self._choose(u"اختر التفسير", opts, self.tafsir_chosen)

    def tafsir_chosen(self, c=None):
        if c:
            self.qh_taf = c[1]
            self.qh_mode, self.qh_pg = "tafsir", 0
            BG.cfg["reader_tafsir"] = c[1]
            self.load()

    def pick_surah(self):
        self._choose(u"اختر السورة", [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)],
                     lambda c: c and self.goto_surah(c[1]))

    def pick_juz(self):
        self._choose(u"اختر الجزء", [(u"الجزء %d  (%s)" % (j, data.surah_name(extras.juz_surah(j))), j)
                                     for j in range(1, 31)],
                     lambda c: c and self.goto_surah(extras.juz_surah(c[1])))



MUSHAF_STYLES = [("paper", u"ورقي مثل المصحف المطبوع"), ("night", u"ليلي"), ("theme", u"ألوان المظهر")]


def mushaf_theme(th):
    st = BG.cfg.get("mushaf_style", "paper")
    th = dict(th)
    if st == "paper":
        th.update({"bg": "#f3ead3", "bar": "#6e5023", "line": "#b38b46", "text": "#1c1810", "gold": "#8c1d18",
                   "sel": "#e3cf9a", "dim": "#6b5838"})
    elif st == "night":
        th.update({"bg": "#0a0c0f", "bar": "#151a21", "line": "#c9a45a", "text": "#ece4cf", "gold": "#f1c96b",
                   "sel": "#26303b", "dim": "#8a8f98"})
    return th


def open_surah_card(session, n):
    try:
        session.open(QHText, u"بطاقة سورة %s" % data.surah_name(n), [u"\n".join(studio.surah_info(n))], u"", False)
    except Exception as e:
        qlog("surah card: %r" % (e,))


def open_share(session, n, a):
    try:
        session.open(QHShare, int(n), int(a))
    except Exception as e:
        qlog("share: %r" % (e,))


def qr_png(text, path, scale=8, border=3):
    """QR code of a link as a black-on-white PNG (qrcodegen - MIT, Project Nayuki)."""
    from . import qrcodegen
    q = qrcodegen.QrCode.encode_text(text, qrcodegen.QrCode.Ecc.MEDIUM)
    n = q.get_size()
    size = (n + 2 * border) * scale
    rows = []
    for y in range(size):
        my = y // scale - border
        line = bytearray(b"\xff" * size)
        if 0 <= my < n:
            for mx in range(n):
                if q.get_module(mx, my):
                    x0 = (mx + border) * scale
                    line[x0:x0 + scale] = b"\x00" * scale
        rows.append(b"\0" + bytes(line))
    import struct
    import zlib

    def chunk(t_, d):
        c = struct.pack(">I", len(d)) + t_ + d
        return c + struct.pack(">I", zlib.crc32(t_ + d) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return size


class QHShare(Screen):
    """A QR code to open the ayah (and its tafsir) on the phone."""

    def __init__(self, session, n, a):
        BG.attach(session)
        th = THEMES[BG.theme_idx()]
        self.qs_n, self.qs_a = n, a
        bg = "#101418" if th["bg"] == "transparent" else th["bg"]
        self.skin = (u'<screen name="QuranHubShare" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">'
                     u'<eLabel position="0,0" size="%d,%d" backgroundColor="%s" />'
                     u'<widget name="sh_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="%s" transparent="1" />'
                     u'<widget name="sh_qr" position="%d,%d" size="%d,%d" alphatest="off" zPosition="2" />'
                     u'<widget name="sh_list" position="%d,%d" size="%d,%d" scrollbarMode="showNever" backgroundColor="%s" backgroundColorSelected="%s" />'
                     u'<widget name="sh_info" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="top" foregroundColor="%s" backgroundColor="%s" transparent="1" />'
                     u'<widget name="sh_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="1" />'
                     u'</screen>') % (
            p(1280), p(720), bg, p(1280), p(66), th["bar"],
            p(20), p(4), p(1240), p(58), p(30), th["bar"],
            p(60), p(110), p(400), p(400),
            p(500), p(110), p(720), p(300), bg, bg,
            p(500), p(430), p(720), p(170), p(20), th["dim"], bg,
            p(20), p(660), p(1240), p(34), p(18), th["dim"], bg)
        Screen.__init__(self, session)
        self.skinName = "QuranHubShare"
        self["sh_title"] = Label(u"مشاركة الآية %d من سورة %s" % (a, data.surah_name(n)))
        self["sh_qr"] = Pixmap()
        lst = MenuList([], False, eListboxPythonMultiContent)
        lst.l.setFont(0, gFont("Regular", p(26)))
        lst.l.setItemHeight(p(60))
        self["sh_list"] = lst
        self["sh_info"] = Label(u"")
        self["sh_hint"] = Label(u"صوّر الكود بكاميرا الجوال  •  ◀ ▶ الآية السابقة / التالية  •  EXIT رجوع")
        self["actions"] = ActionMap(["OkCancelActions", "DirectionActions"],
                                    {"cancel": self.close, "ok": self.close,
                                     "left": lambda: self.step(1), "right": lambda: self.step(-1)}, -1)
        self.onLayoutFinish.append(self.paint)

    def step(self, d):
        cnt = len(extras.local_verses(self.qs_n) or []) or 286
        self.qs_a = max(1, min(cnt, self.qs_a + d))
        self["sh_title"].setText(u"مشاركة الآية %d من سورة %s" % (self.qs_a, data.surah_name(self.qs_n)))
        self.paint()

    def paint(self):
        n, a = self.qs_n, self.qs_a
        url = "https://quran.com/%d/%d" % (n, a)
        try:
            path = data.tmp_path("sqh_qr.png")
            size = qr_png(url, path, scale=max(4, p(400) // 41))
            from Tools.LoadPixmap import LoadPixmap
            try:
                pix = LoadPixmap(path, cached=False)
            except TypeError:
                pix = LoadPixmap(path)
            self["sh_qr"].instance.setPixmap(pix)
            self["sh_qr"].instance.resize(eSize(size, size))
        except Exception as e:
            qlog("qr: %r" % (e,))
        verses = dict(extras.local_verses(n) or [])
        text = u"%s (%s)" % (extras.sanitize(verses.get(a, u"")), extras.ar_num(a))
        w, h = p(720), p(60)
        rows = []
        if img_text():
            px = int(h / 1.85)
            lines = extras.wrap_lines([text], 60, meas=(lambda s: qtext.line_width(s, px), w - p(10),
                                                        qtext.atlas(px)["space"]))[:5]
            for ln in lines:
                rows.append([None] + img_entry(ln, w, h, 0xf4ecd2, align="right"))
        else:
            rows = [[None, MultiContentEntryText(pos=(0, 0), size=(w, h), font=0, text=extras.shape_arabic(ln, "medial"),
                                                 flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER)]
                    for ln in extras.wrap_lines([text], 50)[:5]]
        self["sh_list"].setList(rows)
        self["sh_info"].setText(u"الرابط: %s\nيفتح الآية مع تلاوتها وتفسيرها على موقع quran.com،\n"
                                u"ومنه يمكن إرسالها لمن تحب." % url)


class QHMushaf(QHPaged):
    """The Madinah mushaf page by page (the same ayahs on the same 604 pages as the printed copy),
    with the ayah being recited highlighted and the page turning by itself."""
    HINT = u"◀ ▶ صفحة  •  OK تتبّع التلاوة  •  8 سورة  0 جزء  •  5 رقم الصفحة  •  7/9 الخط  •  MENU  •  EXIT"

    def __init__(self, session, page=None):
        self._setup(session, u"")
        self.qm_page = max(1, min(604, int(page or BG.cfg.get("mushaf_page", 1))))
        self.qm_refs = []
        self.qh_follow = BG.verse_now() is not None
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "NumberActions", "ColorActions", "InfobarMenuActions"],
            {"cancel": self.close, "ok": self.toggle_follow,
             "left": self.next_page, "down": self.next_page, "right": self.prev_page, "up": self.prev_page,
             "7": lambda: self.font(-1), "9": lambda: self.font(1), "8": self.pick_surah, "0": self.pick_juz,
             "5": self.pick_page, "mainMenu": self.menu, "blue": self.toggle_follow}, -1)
        self.qh_timer, self._c = make_timer(self.follow_tick)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        self.load_page(self.qm_page)
        self.qh_timer.start(1000, False)

    def cleanup(self):
        self.qh_timer.stop()
        BG.cfg["mushaf_page"] = self.qm_page
        BG.save()

    def load_page(self, page, sub=0):
        self.qm_page = max(1, min(604, page))
        blocks, self.qm_refs = studio.page_blocks(self.qm_page)
        self.qh_blocks = blocks
        first = next((r for r in self.qm_refs if r), (1, 1))
        self["rd_title"].setText(u"صفحة %d  •  سورة %s  •  الجزء %d  •  %s" % (
            self.qm_page, data.surah_name(first[0]), extras.juz_of(*first), studio.hizb_label(*first)))
        self.qh_pg = sub
        self.paginate(blocks, flow=True)
        if sub < 0:
            self.qh_pg = len(self.qh_pages) - 1
        self.paint()

    def refit(self):
        self.paginate(self.qh_blocks, flow=True)
        self.paint()

    JUSTIFY = True

    def page_theme(self, th):
        return mushaf_theme(th)

    def style_line(self, text, role, fg, back):
        if role == 1:                        # surah title / basmala: centred, the title on a band
            if text.startswith(u"سورة "):
                band = _cint(self.qh_th["bar"])
                return u"\uFD3F  %s  \uFD3E" % text, 0xf6e7b8, band, "center"
            return text, fg, back, "center"
        return text, fg, back, "right"

    def tajweed_roles(self):
        return (0,)

    def info_text(self):
        part = u"  (جزء %d من %d)" % (self.qh_pg + 1, len(self.qh_pages)) if len(self.qh_pages) > 1 else u""
        return u"صفحة %d من 604%s%s" % (self.qm_page, part, u"   •   " + (u"تزامن دقيق" if BG.sync_exact else u"تتبّع التلاوة")
                                         if self.qh_follow else u"")

    def next_page(self):
        self.qh_follow = False
        if self.qh_pg < len(self.qh_pages) - 1:
            self.qh_pg += 1
            return self.paint()
        self.load_page(self.qm_page % 604 + 1)

    def prev_page(self):
        self.qh_follow = False
        if self.qh_pg > 0:
            self.qh_pg -= 1
            return self.paint()
        self.load_page((self.qm_page - 2) % 604 + 1, -1)

    def toggle_follow(self):
        self.qh_follow = not self.qh_follow and BG.verse_now() is not None
        if not self.qh_follow:
            self.qh_hl = None
            self.paint()
        else:
            self.follow_tick(True)

    def follow_tick(self, force=False):
        if not self.qh_follow:
            return
        cur = BG.verse_now()
        if cur is None:
            return
        pg = studio.page_of(*cur)
        if pg != self.qm_page:
            self.load_page(pg)
        try:
            bi = self.qm_refs.index(tuple(cur))
        except ValueError:
            return
        if bi == self.qh_hl and not force:
            return
        self.qh_hl = bi
        for i, lines in enumerate(self.qh_pages):
            if any(bi in tags for _t, tags, _r in lines):
                self.qh_pg = i
                break
        self.paint()

    def _choose(self, title, opts, cb):
        try:
            from Screens.ChoiceBox import ChoiceBox
            self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
        except Exception as e:
            self["rd_info"].setText(u"%s" % e)

    def pick_surah(self):
        self._choose(u"اختر السورة", [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)],
                     lambda c: c and self.load_page(studio.page_of(c[1], 1)))

    def pick_juz(self):
        self._choose(u"اختر الجزء", [(u"الجزء %d" % j, j) for j in range(1, 31)],
                     lambda c: c and self.load_page(studio.page_of(*extras.JUZ_START[c[1] - 1])))

    def cur_ref(self):
        if self.qh_hl is not None and 0 <= self.qh_hl < len(self.qm_refs) and self.qm_refs[self.qh_hl]:
            return self.qm_refs[self.qh_hl]
        try:
            for _t, tags, _r in self.qh_pages[self.qh_pg]:
                for b in sorted(tags):
                    if 0 <= b < len(self.qm_refs) and self.qm_refs[b]:
                        return self.qm_refs[b]
        except Exception:
            pass
        return next((r for r in self.qm_refs if r), (1, 1))

    def cycle_style(self):
        keys = [k for k, _l in MUSHAF_STYLES]
        cur = BG.cfg.get("mushaf_style", "paper")
        BG.cfg["mushaf_style"] = keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else "paper"
        BG.save()
        popup(u"شكل الصفحة: %s\nيظهر عند فتح المصحف مرة أخرى" % dict(MUSHAF_STYLES)[BG.cfg["mushaf_style"]], 4)

    def pick_page(self):
        opts = []
        for pg in range(1, 605):
            n, a = studio.meta()["pages"][pg - 1]
            opts.append((u"صفحة %d  -  سورة %s آية %d" % (pg, data.surah_name(n), a), pg))
        try:
            from Screens.ChoiceBox import ChoiceBox
            self.session.openWithCallback(lambda c: c and self.load_page(c[1]), ChoiceBox,
                                          title=u"اختر الصفحة", list=opts, selection=self.qm_page - 1)
        except TypeError:
            self._choose(u"اختر الصفحة", opts, lambda c: c and self.load_page(c[1]))

    def menu(self):
        self._choose(u"المصحف بالصفحات", [
            (u"عرض الحروف: %s" % QFONT_LABEL.get(BG.cfg.get("quran_font", "img"), u""), "qfont"),
            (u"تلوين أحكام التجويد: %s" % (u"يعمل" if BG.cfg.get("tajweed", True) else u"متوقف"), "tajweed"),
            (u"شكل الصفحة: %s" % dict(MUSHAF_STYLES).get(BG.cfg.get("mushaf_style", "paper")), "style"),
            (u"بطاقة السورة", "card"), (u"مشاركة الآية (كود QR للجوال)", "share"),
            (u"تفسير هذه الصفحة", "taf"), (u"اذهب إلى صفحة ...", "page")],
            lambda c: c and (self.cycle_quran_font() if c[1] == "qfont" else
                             self.toggle_tajweed() if c[1] == "tajweed" else
                             self.cycle_style() if c[1] == "style" else
                             open_surah_card(self.session, self.cur_ref()[0]) if c[1] == "card" else
                             open_share(self.session, *self.cur_ref()) if c[1] == "share" else
                             self.pick_page() if c[1] == "page" else
                             self.session.open(QHReader, (next((r for r in self.qm_refs if r), (1, 1)))[0], "tafsir")))


class QHCinema(Screen):
    """Cinema recitation mode: the ayah being recited, large and centred, with its short tafsir."""
    SIZES = [40, 48, 56]

    def __init__(self, session):
        BG.attach(session)
        th = THEMES[BG.theme_idx()]
        self.qc_th = th
        self.qc_si = min(2, max(0, int(BG.cfg.get("cinema_size", 1))))
        fs = self.SIZES[self.qc_si]
        bg = "#05080c"
        self.skin = (u'<screen name="QuranHubCinema" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">'
                     u'<widget name="cn_top" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="1" />'
                     u'<widget name="cn_list" position="%d,%d" size="%d,%d" scrollbarMode="showNever" backgroundColor="%s" foregroundColor="#f4ecd2" backgroundColorSelected="%s" foregroundColorSelected="#f4ecd2" />'
                     u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" />'
                     u'<widget name="cn_taf" position="%d,%d" size="%d,%d" scrollbarMode="showNever" backgroundColor="%s" foregroundColor="#a9b4c0" backgroundColorSelected="%s" foregroundColorSelected="#a9b4c0" />'
                     u'<widget name="cn_info" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="#7d8894" backgroundColor="%s" transparent="1" />'
                     u'</screen>') % (
            p(1280), p(720), bg,
            p(40), p(24), p(1200), p(50), p(26), th["line"], bg,
            p(60), p(110), p(1160), p(int(fs * 1.7) * 5), bg, bg,
            p(540), p(110 + int(fs * 1.7) * 5 + 14), p(200), p(2), th["line"],
            p(100), p(110 + int(fs * 1.7) * 5 + 30), p(1080), p(34 * 3), bg, bg,
            p(40), p(666), p(1200), p(36), p(19), bg)
        Screen.__init__(self, session)
        self.skinName = "QuranHubCinema"
        self.qc_fs = fs
        self.qc_cur = None
        self.qc_taf_on = BG.cfg.get("cinema_tafsir", True)
        self["cn_top"] = Label(u"")
        self["cn_info"] = Label(u"")
        for name, size, rh in (("cn_list", fs, int(fs * 1.7)), ("cn_taf", 22, 34)):
            lst = MenuList([], False, eListboxPythonMultiContent)
            lst.l.setFont(0, gFont(quran_face() if name == "cn_list" else "Regular", p(size)))
            lst.l.setItemHeight(p(rh))
            self[name] = lst
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions", "NumberActions", "InfobarMenuActions"],
            {"cancel": self.close, "ok": BG.toggle_pause, "left": lambda: BG.seek(-30), "right": lambda: BG.seek(30),
             "red": lambda: BG.step(-1), "green": lambda: BG.step(1), "yellow": self.toggle_tafsir,
             "mainMenu": self.share_now,
             "blue": self.close, "up": lambda: BG.vol_change(5), "down": lambda: BG.vol_change(-5),
             "7": lambda: self.size(-1), "9": lambda: self.size(1)}, -1)
        self.qc_timer, self._c = make_timer(self.refresh)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        BG.hide_minibar()
        self.qc_word = None
        self.qc_lines = []
        self.refresh(True)
        self.qc_timer.start(250, False)

    def share_now(self):
        cur = self.qc_cur or BG.verse_now()
        if cur:
            open_share(self.session, cur[0], cur[1])

    def word_rows(self, lines, wnum):
        """The ayah lines with a band behind word number wnum (counted over the whole ayah)."""
        w, h = p(1160), p(int(self.qc_fs * 1.7))
        rows, k = [], 0
        cols_all = []
        for i, ln in enumerate(lines):
            cols_all.append(line_tajweed(ln, lines[i + 1] if i + 1 < len(lines) else u"") if tajweed_on() else None)
        band = 0x3a3220
        for i, ln in enumerate(lines):
            nw = len(ln.split())
            mark = None
            if ln.strip() and wnum and k < wnum <= k + nw:
                mark = (wnum - k - 1, band)
            k += nw
            rows.append([None] + img_entry(ln, w, h, 0xf4ecd2, align="center", colors=cols_all[i], mark=mark))
        return rows

    def radio_page(self):
        """While a radio plays: an ayah and its tafsir, changing every 20 seconds."""
        slot = int(time.time() // 20)
        if getattr(self, "qc_slot", None) == slot:
            return
        self.qc_slot = slot
        try:
            key, text = extras.ayah_of_the_day(ts=slot * 86400)
            n, a = [int(x) for x in key.split(":")]
            body = u"%s (%s)" % (extras.sanitize(text), extras.ar_num(a))
            self.show_ayah_text(n, a, body)
        except Exception as e:
            qlog("radio page: %r" % (e,))

    def cleanup(self):
        self.qc_timer.stop()
        BG.show_minibar()

    def _rows(self, lines, w, h, color, center=True, tj=False):
        rows = []
        if img_text():
            for i, ln in enumerate(lines):
                cols = line_tajweed(ln, lines[i + 1] if i + 1 < len(lines) else u"") if (tj and tajweed_on()) else None
                rows.append([None] + img_entry(ln, w, h, color, align="center" if center else "right", colors=cols))
            return rows
        for ln in lines:
            txt = extras.shape_arabic(ln, tashkeel_mode()) if BG.cfg.get("arabic_shape", True) else ln
            rows.append([None, MultiContentEntryText(pos=(0, 0), size=(w, h), font=0,
                                                     flags=(RT_HALIGN_CENTER if center else RT_HALIGN_RIGHT) | RT_VALIGN_CENTER,
                                                     text=txt, color=color, color_sel=color)])
        return rows

    def refresh(self, force=False):
        cur = BG.verse_now()
        title = (Player.cur_title or u"").split(u"  ")[0]
        self["cn_top"].setText(title if Player.active else u"وضع التلاوة السينمائي")
        pct, txt = BG.progress()
        want = 250 if getattr(self, "qc_word", None) else 700
        if getattr(self, "qc_iv", None) != want:
            self.qc_iv = want
            self.qc_timer.start(want, False)
        self["cn_info"].setText(u"%s   •   OK إيقاف مؤقت  •  أحمر/أخضر السابق/التالي  •  أصفر التفسير  •  7/9 الحجم  •  MENU مشاركة  •  EXIT%s" % (
            txt or u"", u"   •   تتبّع الكلمة" if getattr(self, "qc_word", None) else u""))
        wn = BG.word_now() if cur is not None else None
        if cur == self.qc_cur and not force:
            if wn and wn[2] != self.qc_word and self.qc_lines and img_text():
                self.qc_word = wn[2]
                pad = self.qc_pad
                self["cn_list"].setList(self._rows([u""] * pad, p(1160), p(int(self.qc_fs * 1.7)), 0xf4ecd2) +
                                        self.word_rows(self.qc_lines, wn[2]))
            elif cur is None and Player.active and BG.cur_live:
                self.radio_page()
            return
        self.qc_cur = cur
        self.qc_word = wn[2] if wn else None
        if cur is None and Player.active and BG.cur_live:
            self.qc_slot = None
            return self.radio_page()
        if cur is None:
            msg = u"شغّل تلاوة سورة لتظهر آياتها هنا" if not Player.active else u"..."
            self["cn_list"].setList(self._rows([u"", u"", msg], p(1160), p(int(self.qc_fs * 1.7)), 0xa9b4c0))
            self["cn_taf"].setList([])
            return
        n, a = cur
        verses = dict(extras.local_verses(n) or [])
        text = u"%s (%s)" % (extras.sanitize(verses.get(a, u"")), extras.ar_num(a))
        self.show_ayah_text(n, a, text)

    def show_ayah_text(self, n, a, text):
        cpl = max(14, int(1160 / (self.qc_fs * 0.5)))
        meas = None
        if img_text():
            try:
                px = int(p(int(self.qc_fs * 1.7)) / 1.85)
                meas = (lambda w: qtext.line_width(w, px), p(1140), qtext.atlas(px)["space"])
            except Exception:
                meas = None
        lines = extras.wrap_lines([text], cpl, meas=meas)[:5]
        pad = (5 - len(lines)) // 2
        self.qc_lines, self.qc_pad = lines, pad
        if self.qc_word and img_text():
            self["cn_list"].setList(self._rows([u""] * pad, p(1160), p(int(self.qc_fs * 1.7)), 0xf4ecd2) +
                                    self.word_rows(lines, self.qc_word))
        else:
            self["cn_list"].setList(self._rows([u""] * pad + lines, p(1160), p(int(self.qc_fs * 1.7)), 0xf4ecd2, tj=True))
        if self.qc_taf_on:
            taf = extras.local_tafsir("muyassar", n) or []
            body = extras.sanitize(taf[a - 1]) if a - 1 < len(taf) and taf[a - 1] != u"=" else u""
            tm = None
            if img_text():
                try:
                    tpx = int(p(34) / 1.85)
                    tm = (lambda w: qtext.line_width(w, tpx), p(1060), qtext.atlas(tpx)["space"])
                except Exception:
                    tm = None
            self["cn_taf"].setList(self._rows(extras.wrap_lines([body], 95, meas=tm)[:3], p(1080), p(34), 0xa9b4c0))
        else:
            self["cn_taf"].setList([])

    def toggle_tafsir(self):
        self.qc_taf_on = not self.qc_taf_on
        BG.cfg["cinema_tafsir"] = self.qc_taf_on
        BG.save()
        self.refresh(True)

    def size(self, d):
        self.qc_si = max(0, min(2, self.qc_si + d))
        BG.cfg["cinema_size"] = self.qc_si
        BG.save()
        self.qc_fs = self.SIZES[self.qc_si]
        try:
            self["cn_list"].l.setFont(0, gFont(quran_face(), p(self.qc_fs)))
        except Exception:
            pass
        self.refresh(True)


class QHText(QHPaged):
    """Generic paged text (adhkar, names of Allah, memorisation text, weekly card ...)."""

    def __init__(self, session, title, blocks, note=u"", flow=False):
        self._setup(session, title)
        self.qh_title_text, self.qh_blocks, self.qh_note = title, list(blocks), note
        self.qh_flow = flow
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "NumberActions", "ColorActions"],
            {"cancel": self.close, "ok": self.close,
             "left": self.next_page, "down": self.next_page, "right": self.prev_page, "up": self.prev_page,
             "7": lambda: self.font(-1), "9": lambda: self.font(1),
             "green": self.next_page, "red": self.prev_page}, -1)
        self.onLayoutFinish.append(self.start)

    def start(self):
        self.paginate(self.qh_blocks, flow=self.qh_flow)
        self.paint()

    def info_text(self):
        return u"صفحة %d / %d%s" % (self.qh_pg + 1, len(self.qh_pages),
                                    (u"   •   " + self.qh_note) if self.qh_note else u"")

    def next_page(self):
        if self.qh_pg < len(self.qh_pages) - 1:
            self.qh_pg += 1
            self.paint()
        elif self.qh_engine == "msgbox":
            self.close()

    def prev_page(self):
        if self.qh_pg > 0:
            self.qh_pg -= 1
            self.paint()

    def refit(self):
        self.paginate(self.qh_blocks, flow=self.qh_flow)
        self.paint()


class QHQuiz(QHPaged):
    """Memorisation test: words are hidden, OK shows the ayah, green = I knew it, red = I did not."""
    HINT = u"OK إظهار الآية  •  أخضر: عرفتها  •  أحمر: لم أعرفها  •  أصفر: استمع للآية  •  EXIT إنهاء"

    def __init__(self, session, n, a1, a2):
        self._setup(session, u"اختبار الحفظ - سورة %s (%d-%d)" % (data.surah_name(n), a1, a2))
        self.qz_n, self.qz_a1, self.qz_a2 = n, a1, a2
        self.qz_items = studio.quiz_items(n, a1, a2)
        self.qz_i, self.qz_right, self.qz_done, self.qz_reveal = 0, 0, 0, False
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {"cancel": self.finish, "ok": self.reveal, "green": lambda: self.answer(True),
             "red": lambda: self.answer(False), "yellow": self.listen}, -1)
        self.onLayoutFinish.append(self.render)

    def render(self):
        if not self.qz_items:
            return self.set_lines([u"لا توجد آيات في هذا المقطع."])
        it = self.qz_items[self.qz_i]
        body = it["text"] if self.qz_reveal else it["puzzle"]
        blocks = [u"الآية %d" % it["a"], u"", body]
        if self.qz_reveal:
            blocks += [u"", u"الكلمات المخفية: " + u" • ".join(it["hidden"])]
        self.qh_pg = 0
        self.paginate(blocks)
        self.qh_hl = None
        self.set_lines(self.qh_pages[0])
        self["rd_info"].setText(u"السؤال %d من %d   •   صحيح %d من %d" % (
            self.qz_i + 1, len(self.qz_items), self.qz_right, self.qz_done))

    def reveal(self):
        self.qz_reveal = not self.qz_reveal
        self.render()

    def answer(self, ok):
        if not self.qz_items:
            return
        self.qz_done += 1
        if ok:
            self.qz_right += 1
        if self.qz_i >= len(self.qz_items) - 1:
            return self.finish()
        self.qz_i += 1
        self.qz_reveal = False
        self.render()

    def listen(self):
        if not self.qz_items:
            return
        st = studio.hifz_state(BG.cfg)
        a = self.qz_items[self.qz_i]["a"]
        BG.ctx = None
        BG.play_list([{"title": u"%s - آية %d من سورة %s" % (studio.HIFZ_RECITERS[st["rec"]][0], a,
                                                            data.surah_name(self.qz_n)),
                       "url": studio.ayah_url(self.qz_n, a, st["rec"], st["src"]), "autonext": False,
                       "nohist": True, "ayah": [self.qz_n, a]}], 0)

    def finish(self):
        if self.qz_done:
            r = studio.quiz_record(BG.cfg, self.qz_n, self.qz_a1, self.qz_a2, self.qz_right, self.qz_done)
            it = studio.srs_result(BG.cfg, self.qz_n, self.qz_a1, self.qz_a2, r["last"])
            BG.save()
            popup(u"نتيجة الاختبار: %d%%  (أفضل نتيجة %d%%)\nالمراجعة القادمة بعد %d يوم" % (
                r["last"], r["best"], studio.SRS_DAYS[it["box"]]), 6)
        self.close()

    def refit(self):
        self.render()


# ------------------------------------------------------------------ studio flows
def _studio_ask(session, title, opts, cb):
    try:
        from Screens.ChoiceBox import ChoiceBox
        session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
    except Exception as e:
        qlog("studio ask: %s" % e)
        popup(u"تعذّر فتح القائمة: %s" % e, 8)


def _studio_info(session, text, then=None, timeout=0):
    try:
        from Screens.MessageBox import MessageBox
        session.openWithCallback((lambda *a: then()) if then else None, MessageBox, text,
                                 MessageBox.TYPE_INFO, timeout=timeout)
    except Exception as e:
        qlog("studio info: %s" % e)
        popup(text, 10)
        if then:
            then()


def _cycle(lst, cur):
    return lst[(lst.index(cur) + 1) % len(lst)] if cur in lst else lst[0]


# ---- memorisation studio
def studio_hifz(session):
    BG.attach(session)
    st = studio.hifz_state(BG.cfg)
    again = lambda: studio_hifz(session)

    def done(c=None):
        if not c:
            return
        k = c[1]
        if k == "go":
            return hifz_start(session)
        if k == "sel":
            return hifz_pick_surah(session)
        if k == "text":
            return session.open(QHText, u"نص المقطع - سورة %s (%d-%d)" % (data.surah_name(st["n"]), st["a1"], st["a2"]),
                                studio.hifz_text(st), u"", False)
        if k == "each":
            st["each"] = _cycle(studio.HIFZ_EACH, st["each"])
        elif k == "rng":
            st["rng"] = _cycle(studio.HIFZ_RANGE, st["rng"])
        elif k == "rec":
            return hifz_pick_reciter(session)
        elif k == "src":
            st["src"] = "islamnet" if st["src"] == "everyayah" else "everyayah"
        elif k == "gap":
            st["gap"] = _cycle(studio.HIFZ_GAPS, st.get("gap", 0))
        elif k == "quiz":
            return session.open(QHQuiz, st["n"], st["a1"], st["a2"])
        BG.cfg["hifz"] = st
        BG.save()
        again()

    try:
        studio.ayah_counts()
    except Exception as e:
        return _studio_info(session, u"بيانات المصحف غير متوفرة: %s" % e)
    _studio_ask(session, u"استوديو الحفظ", [
        (u"▶ ابدأ: %s" % studio.hifz_summary(st), "go"),
        (u"اختيار السورة والآيات ...", "sel"),
        (u"تكرار كل آية: %d مرات  (اضغط للتغيير)" % st["each"], "each"),
        (u"تكرار المقطع كاملاً: %d دورات  (اضغط للتغيير)" % st["rng"], "rng"),
        (u"القارئ: %s ..." % studio.HIFZ_RECITERS[st["rec"]][0], "rec"),
        (u"مهلة للترديد بعد كل آية: %s  (اضغط للتغيير)" % (u"%d ثوانٍ" % st["gap"] if st.get("gap") else u"بدون"), "gap"),
        (u"مصدر الصوت: %s  (اضغط للتغيير)" % (u"everyayah" if st["src"] == "everyayah" else u"islamic.network"), "src"),
        (u"اعرض نص المقطع للقراءة", "text"),
        (u"اختبر حفظك لهذا المقطع", "quiz")], done)


def hifz_pick_surah(session):
    st = studio.hifz_state(BG.cfg)

    def surah_chosen(c=None):
        if not c:
            return studio_hifz(session)
        st["n"] = c[1]
        cnt = studio.ayah_counts()[c[1] - 1]
        texts = dict(extras.local_verses(c[1]) or [])
        opts = [(u"%d - %s" % (a, extras.sanitize(texts.get(a, u""))[:34]), a) for a in range(1, cnt + 1)]

        def from_chosen(c2=None):
            if not c2:
                return studio_hifz(session)
            st["a1"] = c2[1]
            opts2 = [(u"%d - %s" % (a, extras.sanitize(texts.get(a, u""))[:34]), a) for a in range(c2[1], cnt + 1)]

            def to_chosen(c3=None):
                st["a2"] = c3[1] if c3 else min(cnt, c2[1] + 4)
                BG.cfg["hifz"] = st
                BG.save()
                studio_hifz(session)
            _studio_ask(session, u"إلى أي آية؟", opts2, to_chosen)
        _studio_ask(session, u"من أي آية؟", opts, from_chosen)
    _studio_ask(session, u"اختر السورة", [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)],
                surah_chosen)


def hifz_pick_reciter(session):
    st = studio.hifz_state(BG.cfg)

    def chosen(c=None):
        if c:
            st["rec"] = c[1]
            BG.cfg["hifz"] = st
            BG.save()
        studio_hifz(session)
    _studio_ask(session, u"اختر القارئ", [(r[0], i) for i, r in enumerate(studio.HIFZ_RECITERS)], chosen)


def hifz_start(session):
    st = studio.hifz_state(BG.cfg)
    BG.cfg["hifz"] = st
    BG.save()
    items = studio.hifz_items(st)
    if not items:
        return
    BG.ctx = None
    BG.play_list(items, 0, None)
    studio.srs_add(BG.cfg, st["n"], st["a1"], st["a2"])          # the passage enters the smart review
    BG.save()
    BG.set_status(u"استوديو الحفظ: %s" % studio.hifz_summary(st), notify=True)
    session.open(QHReader, st["n"], "text")



# ---- kids & family, quiz, reminders and seasons (v3.1)
def studio_kids(session):
    BG.attach(session)

    def chosen(c=None):
        if not c:
            return
        st = studio.kids_state(c[1])
        BG.ctx = None
        items = studio.hifz_items(st)
        BG.play_list(items, 0, None)
        BG.kids_run = {"pl": items, "n": c[1], "max": 0}
        BG.set_status(u"وضع الأطفال: سورة %s مع الحصري المعلّم" % data.surah_name(c[1]), notify=True)
        session.open(QHReader, c[1], "text")
    _studio_ask(session, u"وضع الأطفال والأسرة: الشيخ يقرأ الآية 3 مرات ثم مهلة للترديد",
                [(u"%s  (%d آيات)" % (data.surah_name(n), studio.ayah_counts()[n - 1]), n) for n in studio.KIDS_SURAHS],
                chosen)


def studio_quiz(session):
    BG.attach(session)
    st = studio.hifz_state(BG.cfg)

    def chosen(c=None):
        if not c:
            return
        if c[1] == "cur":
            return session.open(QHQuiz, st["n"], st["a1"], st["a2"])
        if c[1] == "res":
            return _studio_info(session, studio.quiz_summary(BG.cfg))

        def surah(c2=None):
            if c2:
                session.open(QHQuiz, c2[1], 1, studio.ayah_counts()[c2[1] - 1])
        _studio_ask(session, u"اختبر سورة كاملة", [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)], surah)
    _studio_ask(session, u"اختبار الحفظ", [
        (u"المقطع الحالي: سورة %s (%d-%d)" % (data.surah_name(st["n"]), st["a1"], st["a2"]), "cur"),
        (u"سورة كاملة ...", "all"), (u"نتائجي", "res")], chosen)


def studio_week(session):
    session.open(QHText, u"ملخص الأسبوع", studio.weekly_text(BG.cfg).split(u"\n"), u"", False)


def studio_menu(session):
    BG.attach(session)

    def chosen(c=None):
        if not c:
            return
        {"hifz": studio_hifz, "quiz": studio_quiz, "kids": studio_kids, "khatma": studio_khatma,
         "adhkar": studio_adhkar_menu, "week": studio_week, "remind": studio_reminders,
         "review": studio_review, "multi": studio_multi, "search": studio_search,
         "profile": studio_profiles}[c[1]](session)
    due = len(studio.srs_due(BG.cfg))
    _studio_ask(session, u"الاستوديو  -  الملف: %s" % (BG.cfg.get("profile") or studio.profiles(BG.cfg)[0]), [
        (u"المراجعة الذكية%s" % (u"  (%d مستحق اليوم)" % due if due else u""), "review"),
        (u"استوديو الحفظ والتكرار", "hifz"), (u"اختبار الحفظ (كلمات مخفية)", "quiz"),
        (u"آية واحدة بأصوات القراء", "multi"), (u"بحث في نص القرآن", "search"),
        (u"وضع الأطفال والأسرة", "kids"), (u"الختمة والورد اليومي", "khatma"),
        (u"الأذكار والأدعية وأسماء الله", "adhkar"), (u"ملخص الأسبوع والإحصائيات", "week"),
        (u"التذكيرات والمواسم (الورد • الكهف • الملك • رمضان • الفجر)", "remind"),
        (u"الملف الشخصي: %s ..." % (BG.cfg.get("profile") or studio.profiles(BG.cfg)[0]), "profile")], chosen)


def studio_review(session):
    due = studio.srs_due(BG.cfg)
    if not due:
        return _studio_info(session, studio.srs_text(BG.cfg) + u"\n\nلا توجد مراجعة مستحقة اليوم. المقاطع تدخل المراجعة "
                                                            u"تلقائياً عندما تحفظها في استوديو الحفظ.")
    _studio_ask(session, studio.srs_text(BG.cfg), [
        (u"سورة %s (%d-%d)  -  آخر نتيجة %s" % (data.surah_name(n), a1, a2,
                                               (u"%d%%" % it["last"]) if "last" in it else u"-"), (n, a1, a2))
        for _k, n, a1, a2, it in due], lambda c: c and session.open(QHQuiz, *c[1]))


def _pick_ayah(session, title, cb):
    def surah_chosen(c=None):
        if not c:
            return
        n = c[1]
        texts = dict(extras.local_verses(n) or [])
        _studio_ask(session, u"اختر الآية", [(u"%d - %s" % (a, extras.sanitize(texts.get(a, u""))[:40]), a)
                                            for a in range(1, studio.ayah_counts()[n - 1] + 1)],
                    lambda c2: c2 and cb(n, c2[1]))
    _studio_ask(session, title, [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)], surah_chosen)


def play_ayah_reciters(session, n, a):
    BG.ctx = None
    BG.play_list(studio.ayah_all_reciters(n, a, studio.hifz_state(BG.cfg)["src"]), 0, None)
    session.open(QHReader, n, "text")


def studio_multi(session):
    _pick_ayah(session, u"آية واحدة بأصوات القراء - اختر السورة", lambda n, a: play_ayah_reciters(session, n, a))


def studio_search(session):
    def typed(text=None):
        if not text:
            return
        res = studio.search_quran(text)
        if not res:
            return _studio_info(session, u"لا توجد آيات فيها: %s" % text)

        def chosen(c=None):
            if not c:
                return
            n, a = c[1]

            def act(c2=None):
                if not c2:
                    return
                k = c2[1]
                if k == "page":
                    session.open(QHMushaf, studio.page_of(n, a))
                elif k == "listen":
                    st = studio.hifz_state(BG.cfg)
                    BG.ctx = None
                    BG.play_list([{"title": u"%s - آية %d من سورة %s" % (studio.HIFZ_RECITERS[st["rec"]][0], a, data.surah_name(n)),
                                   "url": studio.ayah_url(n, a, st["rec"], st["src"]), "autonext": False,
                                   "nohist": True, "ayah": [n, a]}], 0)
                elif k == "tafsir":
                    session.open(QHReader, n, "tafsir")
                elif k == "multi":
                    play_ayah_reciters(session, n, a)
            _studio_ask(session, u"سورة %s - الآية %d" % (data.surah_name(n), a), [
                (u"اعرضها في المصحف (الصفحة %d)" % studio.page_of(n, a), "page"), (u"استمع إليها", "listen"),
                (u"تفسير السورة", "tafsir"), (u"بأصوات القراء", "multi")], act)
        _studio_ask(session, u"%d نتيجة لـ «%s»%s" % (len(res), text, u" (أول 200)" if len(res) >= 200 else u""),
                    [(u"%s %d: %s" % (data.surah_name(n), a, t[:60]), (n, a)) for n, a, t in res], chosen)
    try:
        session.openWithCallback(typed, VirtualKeyBoard, title=u"ابحث عن كلمة أو أكثر في القرآن (بدون تشكيل)")
    except Exception as e:
        qlog("search kb: %s" % e)


def studio_profiles(session):
    cur = BG.cfg.get("profile") or studio.profiles(BG.cfg)[0]

    def chosen(c=None):
        if not c:
            return
        k = c[1]
        if k == "add":
            def named(name=None):
                if name and name.strip():
                    studio.profile_switch(BG.cfg, name.strip())
                    BG.save()
                    popup(u"الملف الشخصي الآن: %s" % name.strip(), 4)
            return session.openWithCallback(named, VirtualKeyBoard, title=u"اسم الفرد (مثال: أحمد)")
        if k.startswith("del:"):
            if studio.profile_delete(BG.cfg, k[4:]):
                BG.save()
            return studio_profiles(session)
        studio.profile_switch(BG.cfg, k)
        BG.save()
        popup(u"الملف الشخصي الآن: %s" % k, 4)
    opts = [((u"✓ " if p_ == cur else u"") + p_, p_) for p_ in studio.profiles(BG.cfg)]
    opts.append((u"إضافة فرد جديد ...", "add"))
    opts += [(u"حذف: %s" % p_, "del:" + p_) for p_ in studio.profiles(BG.cfg) if len(studio.profiles(BG.cfg)) > 1]
    _studio_ask(session, u"الملفات الشخصية (لكل فرد ختمته وحفظه ومراجعته وإحصائياته)", opts, chosen)


def _hm_choices():
    out = [(u"إيقاف", None)]
    for h in range(24):
        for m in (0, 30):
            out.append((u"%02d:%02d" % (h, m), u"%02d:%02d" % (h, m)))
    return out


def studio_reminders(session):
    BG.attach(session)
    cfg = BG.cfg
    lab = lambda k: cfg.get(k) or u"إيقاف"
    rd = studio.ramadan_day(adjust=cfg.get("hijri_adj", 0))

    def chosen(c=None):
        if not c:
            return
        k = c[1]
        if k in ("wird_time", "kahf_time", "mulk_time"):
            def setv(c2=None, key=k):
                if c2:
                    cfg[key] = c2[1]
                    BG.save()
                studio_reminders(session)
            title = {"wird_time": u"وقت تذكير الورد اليومي", "kahf_time": u"وقت تشغيل الكهف يوم الجمعة",
                     "mulk_time": u"وقت سورة الملك قبل النوم"}[k]
            return _studio_ask(session, title, _hm_choices(), setv)
        if k == "fajr":
            if not cfg.get("prayer_city"):
                return _studio_info(session, u"اختر مدينة الصلاة أولاً من: MENU > الصلاة والجدولة > مدينة الصلاة")
            cfg["fajr_wake"] = not cfg.get("fajr_wake")
            BG.save()
            BG.ensure_timer()
            return studio_reminders(session)
        if k == "fajr_surah":
            def setn(c2=None):
                if c2:
                    cfg["fajr_surah"] = c2[1]
                    BG.save()
                studio_reminders(session)
            return _studio_ask(session, u"السورة بعد أذان الفجر", [(u"%d. %s" % (i, data.surah_name(i)), i)
                                                                  for i in range(1, 115)], setn)
        if k == "adj":
            cfg["hijri_adj"] = _cycle([0, 1, 2, -2, -1], cfg.get("hijri_adj", 0))
            BG.save()
            return studio_reminders(session)
        if k == "ramadan":
            st = studio.khatma_set_days(cfg, 30)
            st["pages"] = int((rd - 1) * studio.PAGES / 30.0)
            cfg["khatma"] = st
            BG.save()
            return session.open(QHReader, extras.juz_surah(rd), "mushaf")
    opts = [(u"أذان الفجر يوقظ الجهاز من الانتظار: %s" % (u"يعمل" if cfg.get("fajr_wake") else u"متوقف"), "fajr"),
            (u"سورة الاستيقاظ بعد الأذان: %s" % data.surah_name(int(cfg.get("fajr_surah", 1))), "fajr_surah"),
            (u"تذكير الورد اليومي: %s" % lab("wird_time"), "wird_time"),
            (u"سورة الكهف تلقائياً يوم الجمعة: %s" % lab("kahf_time"), "kahf_time"),
            (u"سورة الملك قبل النوم (ثم إيقاف بعد 20 د): %s" % lab("mulk_time"), "mulk_time"),
            (u"التاريخ الهجري: %s  (تصحيح %+d - اضغط للتغيير)" % (
                studio.hijri_text(adjust=cfg.get("hijri_adj", 0)), cfg.get("hijri_adj", 0)), "adj")]
    if rd:
        opts.insert(0, (u"رمضان: اقرأ جزء اليوم (الجزء %d)" % rd, "ramadan"))
    _studio_ask(session, u"التذكيرات والمواسم", opts, chosen)


# ---- khatma
def studio_khatma(session):
    BG.attach(session)
    cfg = BG.cfg

    def menu():
        k = studio.khatma_state(cfg)
        daily = studio.khatma_daily(k)
        _studio_ask(session, u"الختمة والورد اليومي", [
            (u"✔ أتممت ورد اليوم (+%d صفحة)" % daily, "done"),
            (u"افتح المصحف عند موضعي (الجزء %d)" % studio.khatma_juz(k), "open"),
            (u"سجّل عدداً آخر من الصفحات ...", "pages"),
            (u"تغيير الهدف: ختمة كل %d يوماً" % k["days"], "days"),
            (u"بدء ختمة جديدة من الصفر", "reset")], chosen)

    def chosen(c=None):
        if not c:
            return
        k = c[1]
        if k == "done":
            st, fin = studio.khatma_mark(cfg)
            BG.save()
            msg = u"بارك الله فيك! أتممت الختمة (رقم %d) - مبارك." % st["count"] if fin else u"تم تسجيل ورد اليوم."
            return _studio_info(session, msg + u"\n\n" + studio.khatma_text(cfg), menu)
        if k == "open":
            st = studio.khatma_state(cfg)
            return session.open(QHReader, extras.juz_surah(studio.khatma_juz(st)), "mushaf")
        if k == "pages":
            def addp(c2=None):
                if c2:
                    studio.khatma_mark(cfg, c2[1])
                    BG.save()
                menu()
            return _studio_ask(session, u"كم صفحة قرأت؟", [(u"%d صفحات" % n, n) for n in (2, 5, 10, 20, 40, 100)], addp)
        if k == "days":
            def setd(c2=None):
                if c2:
                    studio.khatma_set_days(cfg, c2[1])
                    BG.save()
                menu()
            return _studio_ask(session, u"أتم الختمة خلال", [(u"%d يوماً" % d, d) for d in studio.KHATMA_DAYS], setd)
        if k == "reset":
            studio.khatma_reset(cfg)
            BG.save()
            menu()

    head = studio.hijri_text(adjust=cfg.get("hijri_adj", 0))
    rd = studio.ramadan_day(adjust=cfg.get("hijri_adj", 0))
    if rd:
        head += u"  •  رمضان: جزء اليوم %d" % rd
    _studio_info(session, head + u"\n\n" + studio.khatma_text(cfg), menu)


# ---- adhkar & names
def studio_adhkar_menu(session):
    def chosen(c=None):
        if not c:
            return
        if c[1] == "names":
            return session.open(QHText, u"أسماء الله الحسنى", [u"  •  ".join(studio.names_blocks())], u"٩٩ اسماً", True)
        studio_adhkar_list(session)
    _studio_ask(session, u"الأذكار والأدعية", [
        (u"أذكار الصباح والمساء", "m"), (u"أذكار النوم", "sleep"),
        (u"كل الأذكار والأدعية (حصن المسلم) ...", "all"), (u"أسماء الله الحسنى", "names")],
        lambda c=None: _adhkar_fast(session, c) if c and c[1] in ("m", "sleep") else chosen(c))


def _adhkar_fast(session, c):
    idx = 0 if c[1] == "m" else 1
    title, blocks = studio.adhkar_blocks(idx)
    session.open(QHText, title, blocks, u"حصن المسلم", False)


def studio_adhkar_list(session):
    try:
        cats = studio.adhkar_categories()
    except Exception as e:
        return _studio_info(session, u"بيانات الأذكار غير متوفرة: %s" % e)

    def chosen(c=None):
        if c:
            title, blocks = studio.adhkar_blocks(c[1])
            session.open(QHText, title, blocks, u"حصن المسلم", False)
    _studio_ask(session, u"اختر الباب", [(u"%d. %s" % (i + 1, t), i) for i, (t, _a) in enumerate(cats)], chosen)


# ---- more: stats, bouquet, tools
def studio_more(session):
    def chosen(c=None):
        if not c:
            return
        k = c[1]
        if k == "search":
            return session.open(QuranHub, None, "gsearch")
        if k == "stats":
            return _studio_info(session, studio.stats_text(BG.cfg))
        if k == "bouquet":
            return studio_bouquet(session)
        if k == "menu":
            return session.open(QuranHub, None, "menu")
        if k == "diag":
            return session.open(QHDiag)
        if k == "names":
            return session.open(QHText, u"أسماء الله الحسنى", [u"  •  ".join(studio.names_blocks())], u"٩٩ اسماً", True)
    _studio_ask(session, u"المزيد", [
        (u"بحث شامل (قارئ / سورة / إذاعة)", "search"),
        (u"إحصائيات الاستماع", "stats"),
        (u"باقة الإذاعات في قائمة القنوات", "bouquet"),
        (u"القائمة الكاملة والإعدادات", "menu"),
        (u"التشخيص الذاتي", "diag")], chosen)


def studio_bouquet(session):
    inst = studio.bouquet_installed()

    def chosen(c=None):
        if not c:
            return
        if c[1] == "remove":
            try:
                studio.remove_bouquet()
                _reload_bouquets()
                _studio_info(session, u"تمت إزالة باقة القرآن من قائمة القنوات.")
            except Exception as e:
                _studio_info(session, u"تعذّرت الإزالة: %s" % e)
            return
        BG.set_status(u"جاري تجهيز باقة الإذاعات ...")

        def build(rows):
            if isinstance(rows, Exception):
                return _studio_info(session, u"تعذّر جلب الإذاعات: %s" % rows)
            try:
                rows = list(rows) + [(u"إذاعة القرآن الكريم من القاهرة", data.SQ_RADIO_KNOWN["Radio-Quran-Cairo.html"])]
                n = studio.build_bouquet(rows)
                _reload_bouquets()
                _studio_info(session, u"تمت إضافة %d إذاعة.\n\nافتح قائمة القنوات > راديو > «القرآن الكريم»، "
                                      u"وتعمل الإذاعات بدون فتح البلاجين." % n)
            except Exception as e:
                qlog("bouquet: %s" % e)
                _studio_info(session, u"تعذّر إنشاء الباقة: %s" % e)
        BG.runner.run(lambda: data.mp3quran_radios(), build, build)
    opts = [(u"إنشاء / تحديث باقة الإذاعات", "make")]
    if inst:
        opts.append((u"إزالة الباقة", "remove"))
    _studio_ask(session, u"باقة الإذاعات%s" % (u" (مضافة)" if inst else u""), opts, chosen)


def _reload_bouquets():
    try:
        from enigma import eDVBDB
        db = eDVBDB.getInstance()
        db.reloadBouquets()
    except Exception as e:
        qlog("reloadBouquets: %s" % e)




class QuranHub(Screen):
    skin = _build_skin(0)

    def __init__(self, session, start_sec=None, start_action=None):
        BG.attach(session)
        self.skin = _build_skin(BG.theme_idx())
        Screen.__init__(self, session)
        self.skinName = "QuranHub"
        self.qh_start_sec, self.qh_start_action = start_sec, start_action
        self.qh_runner = Runner()
        self.qh_focus = 0
        self.qh_sec = 0
        self.qh_tok = {1: 0, 2: 0}
        self.qh_cache = SEC_CACHE
        self.qh_full = {0: [], 1: [], 2: []}
        self.qh_view = {0: [], 1: [], 2: []}
        self.qh_q = {0: u"", 1: u"", 2: u""}

        self["qh_title"] = Label(PLUGIN_NAME)
        self["qh_now"] = Label(u"")
        self["qh_rec"] = Label(u"")
        self["qh_status"] = Label(u"")
        for h in HDRS:
            self[h] = Label(u"")
        for name in NAMES:
            lst = MenuList([], False, eListboxPythonMultiContent)
            lst.l.setFont(0, gFont("Regular", GEO["font"]))
            lst.l.setItemHeight(ROW_H)
            self[name] = lst
        self["qh_red"] = Label(u"تصغير ↓ (1)")
        self["qh_green"] = Label(u"تشغيل / فتح")
        self["qh_yellow"] = Label(u"بحث")
        self["qh_blue"] = Label(u"إيقاف")
        self["qh_recbtn"] = Label(u"تسجيل  REC / 0")
        self["qh_net"] = Label(u"")
        self["qh_tv"] = Label(BG.tv_label())
        self["qh_fmt"] = Label(BG.fmt_label())
        self["qh_fav"] = Label(u"★ مفضلة (3)")
        self["qh_sleep"] = Label(BG.sleep_label())
        self["qh_theme"] = Label(u"المظهر (8): %s" % THEMES[BG.theme_idx()]["name"])

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions",
             "ChannelSelectBaseActions", "NumberActions"],
            {
                "ok": self.key_ok, "green": lambda: self.shortcut("green"),
                "cancel": self.key_back, "red": lambda: self.shortcut("red"),
                "yellow": lambda: self.shortcut("yellow"), "blue": lambda: self.shortcut("blue"),
                "up": self.key_up, "down": self.key_down,
                "left": self.key_deeper, "right": self.key_back_level,
                "nextBouquet": self.key_page_down, "prevBouquet": self.key_page_up,
                "1": lambda: self.shortcut("1"), "2": lambda: self.shortcut("2"),
                "3": lambda: self.shortcut("3"), "4": lambda: self.shortcut("4"),
                "5": lambda: self.shortcut("5"), "6": lambda: self.shortcut("6"),
                "7": lambda: self.shortcut("7"), "8": lambda: self.shortcut("8"),
                "9": lambda: self.shortcut("9"), "0": lambda: self.shortcut("0"),
            }, -1)
        self["qh_keys"] = ActionMap(
            ["InfobarInstantRecord", "InfobarMenuActions"],
            {"instantRecord": self.key_record, "mainMenu": self.key_menu}, -1)
        self["qh_seek"] = ActionMap(
            ["InfobarSeekActions", "MediaPlayerSeekActions"],
            {"seekBack": self.key_rewind, "seekFwd": self.key_forward,
             "seekBackManual": self.key_rewind, "seekFwdManual": self.key_forward,
             "playpauseService": BG.toggle_pause, "pauseService": BG.toggle_pause,
             "unPauseService": BG.toggle_pause}, -1)

        self.qh_sec_timer, self._c1 = make_timer(self.load_section)
        self.qh_sub_timer, self._c2 = make_timer(self.load_subs)

        self.onLayoutFinish.append(self.qh_start)
        self.onClose.append(self.qh_cleanup)
        BG.ui = self

    # -- lifecycle ----------------------------------------------------------
    # the right column holds only the Quran sources and radios; the rest is opened from MENU
    SOURCE_KEYS = ("fav", "mp3q_reciters", "mp3q_radios", "qcom", "sq_reciters", "sq_radios", "islam",
                   "way_reciters", "way_iconic")

    def build_sections(self, extra=None):
        sync_tg_sections(BG.cfg)
        hidden = set(BG.cfg.get("hidden_secs", []))
        idx = dict((s[0], i) for i, s in enumerate(SECTIONS) if s[0] not in hidden or s[0] == extra)
        rows, shown, self.qh_group_of = [], set(), {}
        for title, keys in GROUPS:
            ks = []
            for k in keys:
                if k == "@tg":
                    ks += ["tg:" + u for u, _n in tg_channels(BG.cfg)]
                elif k == "@dsk":
                    ks += ["dsk:" + d["path"] for d in BG.cfg.get("disk_srcs", [])]
                elif k == "@acache":                 # shown once something has been kept
                    try:
                        if AUDIO.entries():
                            ks.append("acache")
                    except Exception:
                        pass
                else:
                    ks.append(k)
            ks = [k for k in ks if k in idx]
            order = BG.cfg.get("sec_order") or []
            if order:
                pos = dict((k, i) for i, k in enumerate(order))
                ks = sorted(ks, key=lambda k: (pos.get(k, 999), ks.index(k)))
            if not ks:
                continue
            if rows:
                rows.append((u"—  %s  —" % title, None))
            for k in ks:
                rows.append((SECTIONS[idx[k]][1], idx[k]))
                shown.add(k)
                self.qh_group_of[idx[k]] = title
        if extra and extra in idx and extra not in shown:
            rows += [(u"—  مكتبتي  —", None), (SECTIONS[idx[extra]][1], idx[extra])]
            self.qh_group_of[idx[extra]] = u"مكتبتي"
        self.qh_extra_sec = extra
        self.qh_full[0] = rows
        self.apply(0)

    def skip_headers(self, step):
        """Never rest on a group title in the right column."""
        lst = self[NAMES[0]]
        view = self.qh_view[0]
        i = lst.getSelectionIndex()
        n = len(view)
        guard = 0
        while 0 <= i < n and view[i][1] is None and guard < n:
            i = i + step
            if i < 0 or i >= n:
                step = -step
                i = max(0, min(n - 1, i + step))
            guard += 1
        if 0 <= i < n:
            lst.moveToIndex(i)

    def jump_group(self, step):
        view = self.qh_view[0]
        heads = [0] + [i + 1 for i, (_l, p_) in enumerate(view) if p_ is None]
        cur = self[NAMES[0]].getSelectionIndex()
        if step > 0:
            nxt = [h for h in heads if h > cur]
            tgt = nxt[0] if nxt else heads[0]
        else:
            prev = [h for h in heads if h < cur]
            tgt = prev[-1] if prev else heads[-1]
        self[NAMES[0]].moveToIndex(max(0, min(len(view) - 1, tgt)))
        self.skip_headers(1)
        self.selection_changed()

    def sec_row(self, i):
        for r, (_l, pl) in enumerate(self.qh_view[0]):
            if pl == i:
                return r
        return None

    def fetch_tg_pictures(self):
        for u, _n in tg_channels(BG.cfg):
            if u.lower() in TG_PIX:
                continue
            TG_PIX[u.lower()] = None
            self.qh_runner.run(lambda u=u: data.tg_photo(u), lambda r, u=u: self.tg_picture(u, r), lambda e: None)

    def tg_picture(self, u, path):
        if isinstance(path, Exception) or not path:
            return
        pix = load_scaled(path, ICON_PX, ICON_PX)
        if pix is not None:
            TG_PIX[u.lower()] = pix
            self.apply(0)

    def qh_start(self):
        self.build_sections()
        seen = int(BG.cfg.get("seen_build", 0) or 0)
        if seen < BUILD:
            BG.cfg["seen_build"] = BUILD
            BG.save()
            if seen or BG.cfg.get("hist") or BG.cfg.get("fav"):     # an update, not a first install
                self.qh_wn_timer, self._cw = make_timer(lambda: self.show_whats_new(seen))
                self.qh_wn_timer.start(800, True)
        self.fetch_tg_pictures()
        BG.load_timing_reads()
        bad = BG.health_bad()
        today = time.strftime("%Y-%m-%d")
        if bad and BG.cfg.get("src_health_seen") != today:
            BG.cfg["src_health_seen"] = today
            BG.save()
            popup(u"الفحص الليلي: مصادر متوقفة\n%s\n\nقف عليها واضغط 5 لحذفها" % u"، ".join(bad), 10)
        if self.qh_start_sec is not None:
            try:
                i = int(self.qh_start_sec)
                if self.sec_row(i) is None:
                    self.build_sections(SECTIONS[i][0])
                self["qh_sec"].moveToIndex(self.sec_row(i) or 0)
            except Exception:
                pass
        elif not BG.cfg.get("fav"):          # nothing starred yet -> start on the reciters
            try:
                self["qh_sec"].moveToIndex(self.sec_row(1) or 0)
            except Exception:
                pass
        self.set_focus(0)
        self.color_labels()
        BG.ensure_aotd()
        BG.prefetch()
        self.qh_idle, self._ci = make_timer(self.qh_labels)
        self.qh_idle.start(5000, False)
        self.qh_status_text(BG.status or
                            u"MENU القائمة الرئيسية • ◀◀ ▶▶ رجوع/تقديم • الاختصارات قابلة للتخصيص من القائمة")
        self.qh_labels()
        self.load_section()
        BG.show_minibar()
        if self.qh_start_action:
            self.qh_act_timer, self._ca = make_timer(self.run_start_action)
            self.qh_act_timer.start(400, True)

    def run_start_action(self):
        a, self.qh_start_action = self.qh_start_action, None
        if a == "menu":
            self.key_menu()
        elif a == "gsearch":
            self.search_global()
        elif a == "tv":
            self.key_tv()

    def qh_cleanup(self):
        try:
            self.qh_idle.stop()
        except Exception:
            pass
        self.qh_runner.close()
        self.qh_sec_timer.stop()
        self.qh_sub_timer.stop()
        if BG.ui is self:
            BG.ui = None        # audio / recording keep running in BG
        BG.tv_refresh()         # raise the picture right after this screen goes away
        BG.tv_refresh_in = 2 if BG.tv_on else 0

    # -- callbacks used by BG --------------------------------------------------
    def qh_labels(self):
        self["qh_now"].setText(BG.now_text())
        self["qh_rec"].setText(BG.rec_text())
        if Player.active:
            pct, ptxt = BG.progress()
            bar = u""
            if ptxt and ptxt != u"LIVE":
                n = int(pct / 10)
                bar = u"[%s%s] %s   " % (u"=" * n, u"-" * (10 - n), ptxt)
            elif ptxt == u"LIVE":
                bar = u"LIVE   "
            self["qh_net"].setText(bar + BG.net_text())
        else:
            self["qh_net"].setText(BG.idle_text())
        self.button_labels()

    def qh_status_text(self, text):
        self["qh_status"].setText(text)

    def qh_highlight(self, item):
        for col in (2, 1):       # keep the highlight on the playing row
            for i, (_, pl) in enumerate(self.qh_view[col]):
                if pl is item:
                    try:
                        self[NAMES[col]].moveToIndex(i)
                    except Exception:
                        pass

    # -- list plumbing -------------------------------------------------------
    def entry(self, col, label, payload):
        if col == 0 and payload is not None:
            try:
                return self.sec_entry(label, payload)
            except Exception as e:
                qlog("sec entry: %s" % e)
        color = None
        if payload is None:
            th = THEMES[BG.theme_idx()]
            color = th["gold"] if label.startswith(u"—") else th["grey"]
        kw = dict(pos=(p(10), 0), size=(COL_W[col] - p(20), ROW_H), font=0,
                  flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=extras.strip_tashkeel(label))
        if color is not None:
            kw["color"] = color
            kw["color_sel"] = color
        return [payload, MultiContentEntryText(**kw)]

    def sec_entry(self, label, i):
        key = SECTIONS[i][0]
        pix = section_pixmap(key)
        w, h = COL_W[0], ROW_H
        ic = min(ICON_PX, h - p(4))
        hs = (BG.cfg.get("src_health") or {}).get(key)
        label = i18n.T(label)
        kw = dict(pos=(p(6), 0), size=(w - ic - p(20), h), font=0, flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=label)
        if hs and not hs[0]:
            kw.update(text=label + u" (متوقف)", color=0xff7b7b, color_sel=0xffd0d0)
        row = [i, MultiContentEntryText(**kw)]
        if pix is not None:
            row.append(_PixEntry(pos=(w - ic - p(6), (h - ic) // 2), size=(ic, ic), png=pix))
        return row

    def fav_key(self, label, payload):
        if payload and payload.get("favkey"):
            return tuple(payload["favkey"])
        return (SECTIONS[self.qh_sec][0], label)

    def apply(self, col):
        rows = self.qh_full[col]
        if col == 1:
            hid = set(tuple(x) for x in BG.cfg.get("hidden_items", []))
            if hid:
                key = SECTIONS[self.qh_sec][0]
                rows = [r for r in rows if (key, r[0]) not in hid]
        q = data.norm(self.qh_q[col])
        if q:
            rows = [r for r in rows if r[1] is not None and q in data.norm(r[0])]
        self.qh_view[col] = rows
        favs = [tuple(f) for f in BG.cfg.get("fav", [])]
        shown_rows = []
        for l, pl in rows:
            if col == 1 and pl is not None and self.fav_key(l, pl) in favs \
                    and SECTIONS[self.qh_sec][0] != "fav":
                l = u"★ " + l
            shown_rows.append((l, pl))
        self[NAMES[col]].setList([self.entry(col, l, pl) for l, pl in shown_rows])
        self.update_headers()

    def put(self, col, rows):
        self.qh_full[col] = rows
        self.qh_q[col] = u""
        self.apply(col)

    def message(self, col, text):
        self.put(col, [(text, None)])

    def current(self, col):
        idx = self[NAMES[col]].getSelectionIndex()
        view = self.qh_view[col]
        if 0 <= idx < len(view):
            return idx, view[idx][1]
        return None, None

    def has_subs_here(self):
        flag = SECTIONS[self.qh_sec][3]
        if flag is None:
            _, e = self.current(1)
            return entry_has_subs(e)
        return flag

    def max_focus(self):
        return 2 if self.has_subs_here() else 1

    def update_headers(self):
        sec = SECTIONS[self.qh_sec]
        titles = [getattr(self, "qh_group_of", {}).get(self.qh_sec, u"المصادر"), sec[2], u"السور"]
        for i in range(3):
            t = titles[i]
            if self.qh_q[i]:
                t += u"  [بحث: %s]" % self.qh_q[i]
            self[HDRS[i]].setText(i18n.T(t))

    def set_focus(self, col):
        self.qh_focus = max(0, min(col, self.max_focus()))
        if parseColor is None:
            return
        th = THEMES[BG.theme_idx()]
        for i in range(3):
            try:
                color = th["sel"] if i == self.qh_focus else th["head"]
                self[HDRS[i]].instance.setBackgroundColor(parseColor(color))
                self[HDRS[i]].instance.invalidate()
            except Exception:
                pass

    # -- loading -------------------------------------------------------------
    def load_section(self):
        _r, idx = self.current(0)
        if idx is None:                      # a group title: keep the current section
            idx = getattr(self, "qh_sec", 0) or 0
        self.qh_sec = idx
        key = SECTIONS[idx][0]
        self.qh_tok[2] += 1
        if SECTIONS[idx][3] is False:
            self.message(2, u"الإذاعات تعمل مباشرة")
        else:
            self.message(2, u"اختر قارئاً")
        self.update_headers()
        if key not in VOLATILE and not key.startswith("tg:") and not key.startswith("dsk:") and key in self.qh_cache:
            self.put(1, self.qh_cache[key])
            self.schedule_subs(50)
            return
        self.qh_tok[1] += 1
        token = self.qh_tok[1]
        if key == "fav":
            favs = [tuple(f) for f in BG.cfg.get("fav", [])]
            if not favs:
                return self.message(1, u"لا توجد مفضلة - اضغط 3 على أي قارئ أو إذاعة")
            loader = fav_loader(favs)
        else:
            loader = section_loader(key)
        self.message(1, u"جاري التحميل ...")
        self.qh_runner.run(loader,
                           lambda r, k=key, t=token: self.section_done(r, k, t),
                           lambda e, t=token: self.section_failed(e, t))

    def section_done(self, result, key, token):
        if isinstance(result, Exception):
            return self.section_failed(result, token)
        if key not in VOLATILE:
            self.qh_cache[key] = result
        if token != self.qh_tok[1]:
            return  # user already moved to another section
        self.put(1, result or [(u"لا توجد عناصر", None)])
        self.qh_status_text(u"%d عنصر" % len(result))
        self.schedule_subs(50)

    def section_failed(self, exc, token):
        if token != self.qh_tok[1]:
            return
        if isinstance(exc, ValueError) and SECTIONS[self.qh_sec][0].startswith("tg:"):
            self.message(1, u"%s" % exc)
        else:
            self.message(1, u"تعذّر التحميل - تحقق من الإنترنت")
        self.qh_status_text(u"خطأ: %s" % exc)

    def schedule_subs(self, ms=250):
        self.qh_sub_timer.stop()
        self.qh_sub_timer.start(ms, True)

    def load_subs(self):
        _, entry = self.current(1)
        if not entry_has_subs(entry):
            if SECTIONS[self.qh_sec][3] is not False:
                self.qh_tok[2] += 1
                self.message(2, u"اختر قارئاً" if entry is None else u"يعمل مباشرة")
            return
        self.qh_tok[2] += 1
        token = self.qh_tok[2]
        if entry_needs_network(entry):  # needs the network
            ck = tuple(sorted((k, str(v)) for k, v in entry.items() if k in ("sq", "iw", "w2")))
            if ck in SUBS_CACHE:
                return self.put(2, SUBS_CACHE[ck])
            self.message(2, u"جاري التحميل ...")
            self.qh_runner.run(lambda e=entry: subs_for(e),
                               lambda r, t=token, k=ck: self.subs_done(r, t, k),
                               lambda e, t=token: self.subs_failed(e, t))
        else:
            self.put(2, subs_for(entry))

    def subs_done(self, result, token, ck=None):
        if isinstance(result, Exception):
            return self.subs_failed(result, token)
        if ck is not None and result:
            if len(SUBS_CACHE) > 40:
                SUBS_CACHE.clear()
            SUBS_CACHE[ck] = result
        if token == self.qh_tok[2]:
            self.put(2, result)

    def subs_failed(self, exc, token):
        if token == self.qh_tok[2]:
            self.message(2, u"تعذّر تحميل السور")
            self.qh_status_text(u"خطأ: %s" % exc)

    # -- keys ------------------------------------------------------------------
    def selection_changed(self):
        if self.qh_focus == 0:
            self.qh_sec_timer.stop()
            self.qh_sec_timer.start(350, True)
        elif self.qh_focus == 1:
            self.schedule_subs(250)

    def key_up(self):
        self[NAMES[self.qh_focus]].up()
        if self.qh_focus == 0:
            self.skip_headers(-1)
        self.selection_changed()

    def key_down(self):
        self[NAMES[self.qh_focus]].down()
        if self.qh_focus == 0:
            self.skip_headers(1)
        self.selection_changed()

    def key_page_up(self):
        if self.qh_focus == 0:
            return self.jump_group(-1)
        self[NAMES[self.qh_focus]].pageUp()
        self.selection_changed()

    def key_page_down(self):
        if self.qh_focus == 0:
            return self.jump_group(1)
        self[NAMES[self.qh_focus]].pageDown()
        self.selection_changed()

    def key_deeper(self):          # left arrow: go one column to the left
        # apply a pending (debounced) selection immediately
        if self.qh_focus == 0 and self.qh_sec_timer.isActive():
            self.qh_sec_timer.stop()
            self.load_section()
        elif self.qh_focus == 1 and self.qh_sub_timer.isActive():
            self.qh_sub_timer.stop()
            self.load_subs()
        if self.qh_focus < self.max_focus():
            self.set_focus(self.qh_focus + 1)

    def key_back_level(self):      # right arrow: back to the parent column
        self.set_focus(self.qh_focus - 1)

    def key_ok(self):
        f = self.qh_focus
        if f == 0:
            return self.key_deeper()
        idx, payload = self.current(f)
        if payload is None:
            return
        if payload.get("tgmore"):
            return self.tg_more(payload["tgmore"])
        if f == 1 and entry_has_subs(payload):
            return self.key_deeper()
        self.play_from(f, idx)

    def tg_more(self, more):
        u, before = more
        name = dict(tg_channels(BG.cfg)).get(u, u)
        self.qh_status_text(u"جاري تحميل منشورات أقدم ...")
        tok = self.qh_tok[1]

        def done(rows):
            if tok != self.qh_tok[1]:
                return
            if isinstance(rows, Exception):
                return self.qh_status_text(u"تعذّر التحميل: %s" % rows)
            keep = [r for r in self.qh_full[1] if not (r[1] and r[1].get("tgmore"))]
            self.qh_full[1] = keep + rows
            self.apply(1)
            self.qh_status_text(u"أضيفت %d منشورات" % len([r for r in rows if r[1] and not r[1].get("tgmore")]))
        self.qh_runner.run(lambda: data.tg_rows(u, name, before), done, done)

    def key_back(self):
        if self.qh_focus > 0:
            self.set_focus(self.qh_focus - 1)
        else:
            self.key_minimise()

    def key_exit(self):
        """Close the screen AND stop everything."""
        BG.stop_all()
        data.save_settings(BG.cfg, now=True)          # disk + flash copy now
        self.close()

    def key_minimise(self):
        """Close the screen, keep playing / recording in the background."""
        if Player.active or BG.rec is not None:
            popup(u"القرآن يعمل في الخلفية مع صورة القناة\nللإيقاف: MENU > إغلاق البلاجين وإيقاف القرآن", 4)
        BG.show_minibar()
        self.close()

    def key_search(self):
        col = self.qh_focus
        if col == 0:
            return
        self.session.openWithCallback(lambda t, c=col: self.search_done(c, t),
                                      VirtualKeyBoard, title=u"بحث",
                                      text=self.qh_q[col])

    def search_done(self, col, text=None):
        if text is None:
            return
        self.qh_q[col] = text
        self.apply(col)

    def key_stop(self):
        BG.stop_play()

    def key_record(self):
        BG.toggle_record()
        self.qh_labels()

    def key_format(self):
        BG.cycle_format()

    def key_sleep(self):
        BG.cycle_sleep()

    def key_engine(self):
        BG.toggle_engine()

    # -- menus ------------------------------------------------------------------
    def _choice(self, title, opts, cb):
        try:
            from Screens.ChoiceBox import ChoiceBox
            if i18n.on():
                title, opts = i18n.T(title), [(i18n.T(o[0]),) + tuple(o[1:]) for o in opts]
            self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
        except Exception as e:
            self.qh_status_text(u"تعذّر فتح القائمة: %s" % e)

    # ================================================================== 1.8 menus
    def menu_ramadan(self):
        cfg = BG.cfg
        d = BG.ramadan_on()
        mode = {"auto": u"تلقائي في رمضان", "off": u"متوقف"}.get(cfg.get("ramadan", "auto"), u"تلقائي في رمضان")
        adj = studio.hijri_adjust(cfg)
        it = [(u"التاريخ الهجري اليوم: %s" % studio.hijri_text(adjust=adj), lambda: None),
              (u"تصحيح التاريخ الهجري: %+d يوم (اضغط للتغيير)" % adj, self.hijri_adjust_next),
              (u"وضع رمضان: %s" % mode, self.ramadan_toggle),
              (u"قارئ ختمة رمضان: %s" % studio.HIFZ_RECITERS[int(cfg.get("ramadan_rec", 0))][0], self.ramadan_rec_pick),
              (u"تذكير المناسبات الهجرية: %s" % self._on(cfg.get("occasions", True)),
               lambda: BG.toggle_flag("occasions", True, u"تذكير المناسبات الهجرية"))]
        if d:
            it.insert(0, (u"تشغيل جزء الليلة الآن (الجزء %d)" % min(30, d), lambda: BG.play_juz(min(30, d))))
        it.append((u"تشغيل جزء معيّن ...", lambda: self._choice(u"اختر الجزء", [(u"الجزء %d" % j, j) for j in range(1, 31)],
                                                                 lambda c: c and BG.play_juz(c[1]))))
        if not cfg.get("prayer_city"):
            it.append((u"(تنبيه الإفطار والسحور يحتاج مدينة الصلاة: القائمة > الصلاة)", lambda: None))
        self._menu(u"رمضان والمناسبات", it)

    def hijri_adjust_next(self):
        order = [0, 1, 2, -2, -1]
        cur = studio.hijri_adjust(BG.cfg)
        BG.cfg["hijri_adj"] = order[(order.index(cur) + 1) % len(order)]
        BG.save()
        self.qh_status_text(u"التاريخ الهجري: %s" % studio.hijri_text(adjust=BG.cfg["hijri_adj"]))

    def ramadan_toggle(self):
        BG.cfg["ramadan"] = "off" if BG.cfg.get("ramadan", "auto") == "auto" else "auto"
        BG.save()
        self.qh_status_text(u"وضع رمضان: %s" % (u"تلقائي" if BG.cfg["ramadan"] == "auto" else u"متوقف"))

    def ramadan_rec_pick(self):
        self._choice(u"قارئ ختمة رمضان", [(r[0], i) for i, r in enumerate(studio.HIFZ_RECITERS)],
                     lambda c: c and (BG.cfg.__setitem__("ramadan_rec", c[1]), BG.save()))

    def menu_station(self):
        it = [(u"إذاعتي الخاصة: كل المكتبة عشوائياً", lambda: BG.station_play(None, True)),
              (u"إذاعتي الخاصة: كل المكتبة بالترتيب", lambda: BG.station_play(None, False)),
              (u"إذاعتي الخاصة: قارئ واحد ...", self.station_one),
              (u"رابط الإذاعة لأجهزة البيت ...", self.station_link),
              ((u"إزالة «إذاعتي الخاصة» من قائمة الراديو" if BG.cfg.get("station_bq") else
                u"إضافة «إذاعتي الخاصة» كقناة في قائمة الراديو"), self.station_channel)]
        self._menu(u"إذاعتي الخاصة", it)

    def station_one(self):
        _items, recs = BG.station_items(None, False)
        if not recs:
            return self.qh_status_text(u"المكتبة فارغة")
        self._choice(u"اختر القارئ", [(r, r) for r in recs], lambda c: c and BG.station_play(c[1], False))

    def station_link(self):
        url = BG.station_url()
        if not url:
            return self.qh_status_text(u"تعذّر تشغيل إذاعة البيت")
        _studio_info(self.session, u"افتح هذا الرابط من الجوال أو أي جهاز على نفس شبكة البيت:\n\n%s\n\n"
                                   u"(ملفات MP3 من مكتبتك تعمل بلا توقف وبترتيب عشوائي)" % url)

    # ================================================================== 2.0 menus
    def menu_hdd(self):
        cfg = BG.cfg
        d = data.home_dir()
        if not d:
            return _studio_info(self.session, u"لا يوجد HDD أو فلاشة متصلة.\nالبلاجين يعمل كالمعتاد، وهذه المزايا تحتاج قرصاً.")
        free = data.disk_free(d)
        it = [(u"القرص: %s  •  المتاح %s" % (os.path.dirname(d), data.fmt_bytes(free) if free is not None else u"?"), lambda: None),
              (u"حفظ ما أسمعه على القرص (يعمل بدون إنترنت): %s" % self._on(cfg.get("audio_cache", True)), self.acache_toggle),
              (u"الحد الأقصى لما سمعته سابقاً: %s جيجا (المستخدم %s)" % (
                  cfg.get("audio_quota", 20), data.fmt_bytes(AUDIO.total())), self.acache_quota),
              (u"مسح ما سمعته سابقاً من القرص", self.acache_clear),
              (u"رسم المصحف كاملاً مسبقاً (أثناء الانتظار أو ليلاً): %s  (%d/604)" % (
                  self._on(cfg.get("mushaf_pre", True)), int((cfg.get("mpre") or {}).get("page", 0))),
               lambda: BG.toggle_flag("mushaf_pre", True, u"رسم المصحف مسبقاً")),
              (u"إيقاظ القرص قبل الأذان والمواعيد: %s" % self._on(cfg.get("hdd_wake", True)),
               lambda: BG.toggle_flag("hdd_wake", True, u"إيقاظ القرص قبل المواعيد")),
              (u"متابعة التلاوة تلقائياً بعد انقطاع الكهرباء: %s" % self._on(cfg.get("boot_resume", False)),
               lambda: BG.toggle_flag("boot_resume", False, u"المتابعة بعد إعادة التشغيل")),
              (u"تنظيف الملفات المؤقتة القديمة الآن", self.hdd_clean),
              (u"النسخ اليومية للإعدادات (آخر 7 أيام + 4 أسابيع) ...", self.menu_backups19)]
        self._menu(u"القرص والسرعة والثبات", it)

    def acache_toggle(self):
        BG.cfg["audio_cache"] = not BG.cfg.get("audio_cache", True)
        AUDIO.enabled = BG.cfg["audio_cache"]
        BG.save()
        self.qh_status_text(u"حفظ ما أسمعه على القرص: %s" % self._on(BG.cfg["audio_cache"]))

    def acache_quota(self):
        def setq(c=None):
            if c:
                BG.cfg["audio_quota"] = c[1]
                AUDIO.quota = int(c[1] * 1024 ** 3)
                BG.save()
                _bg_thread(AUDIO.trim)
                self.qh_status_text(u"الحد الأقصى: %s جيجا" % c[1])
        self._choice(u"أقصى مساحة لما سمعته سابقاً", [(u"%s جيجا" % g, g) for g in (2, 5, 10, 20, 50, 100)], setq)

    def acache_clear(self):
        _bg_thread(AUDIO.clear)
        self.qh_status_text(u"جاري المسح ...")

    def hdd_clean(self):
        n = BG.clean_old()
        self.qh_status_text(u"تم حذف %d ملفاً قديماً" % n)

    def menu_backups19(self):
        rows = BG.backups19()
        it = [(u"حفظ نسخة الآن", lambda: (BG.backup_rotate(), self.qh_status_text(u"تم الحفظ")))]
        it += [(u"استعادة نسخة يوم %s" % day, (lambda q=path: self.restore19_ask(q))) for day, path in rows]
        if not rows:
            it.append((u"(تُحفظ نسخة كل يوم تلقائياً)", lambda: None))
        self._menu(u"النسخ اليومية للإعدادات", it)

    def restore19_ask(self, path):
        def go(yes=None):
            if yes:
                BG.restore19(path)
                self.qh_status_text(u"تمت الاستعادة - أعد فتح البلاجين")
        try:
            from Screens.MessageBox import MessageBox
            self.session.openWithCallback(go, MessageBox, u"استعادة الإعدادات والمفضلة من هذه النسخة؟", MessageBox.TYPE_YESNO)
        except Exception:
            go(True)

    def menu_rollback(self):
        snaps = safeupdate.snapshots()
        if not snaps:
            return self.qh_status_text(u"لا توجد نسخة سابقة محفوظة (تُحفظ تلقائياً عند كل تحديث)")

        def go(c=None):
            if not c:
                return
            try:
                safeupdate.restore(c[1])
                self.update_done()
            except Exception as e:
                self.qh_status_text(u"تعذّر الرجوع: %s" % e)
        self._choice(u"الرجوع لإصدار سابق", [(u"الرجوع إلى الإصدار %s" % safeupdate.snap_version(p_), p_)
                                            for _t, p_ in snaps], go)

    def menu_profiles19(self):
        studio_profiles(self.session)

    def show_harvest(self, period="month"):
        txt = studio.harvest_text(BG.cfg, period)
        self.session.open(QHText, u"الحصاد", [txt], u"", False)
        if BG.bot is not None:
            BG.tg_notify(txt)

    def show_stars(self):
        lines = [studio.stars_text(BG.cfg), u"", u"نجوم كل أفراد الأسرة:"]
        lines += [u"• %s: %d" % (p_, n) for p_, n in studio.stars_of(BG.cfg)]
        self.session.open(QHText, u"⭐ النجوم - %s" % (BG.cfg.get("profile") or studio.profiles(BG.cfg)[0]),
                          [u"\n".join(lines)], u"", False)

    def menu_dlna(self):
        on = BG.dlna is not None
        it = [(u"مكتبتي لأجهزة البيت (DLNA): %s" % self._on(on), self.dlna_toggle)]
        if on:
            it.append((u"ابحث في التلفزيون أو الجوال عن «Saad Quran Hub» في الوسائط / DLNA", lambda: None))
        self._menu(u"مكتبتي لأجهزة البيت", it)

    def dlna_toggle(self):
        want = BG.dlna is None
        ok = BG.dlna_set(want)
        BG.cfg["dlna"] = want and ok
        BG.save()
        self.qh_status_text(u"DLNA: %s" % (u"يعمل" if BG.cfg["dlna"] else (u"متوقف" if ok else u"تعذّر التشغيل")))

    def station_channel(self):
        try:
            if BG.cfg.get("station_bq"):
                BG.station_bouquet(False)
                return self.qh_status_text(u"أُزيلت قناة «إذاعتي الخاصة» من قائمة القنوات")
            BG.station_bouquet(True)
            self.qh_status_text(u"أُضيفت «إذاعتي الخاصة» إلى قائمة الراديو - تعمل بدون فتح البلاجين")
        except Exception as e:
            self.qh_status_text(u"تعذّر: %s" % e)

    def menu_lang(self):
        self._choice(u"اللغة / Language", [(u"العربية", "ar"), (u"English", "en")], self._lang_set)

    def _lang_set(self, c=None):
        if not c:
            return
        BG.cfg["lang"] = c[1]
        BG.save()
        i18n.LANG[0] = c[1]
        self.color_labels()
        self.build_sections(self.qh_extra_sec)
        self.qh_status_text(u"Language: English" if c[1] == "en" else u"اللغة: العربية")

    def show_whats_new(self, since=0):
        lines = whats_new_text(since) or whats_new_text(0)
        self.session.open(QHText, u"ما الجديد في Saad Quran Hub %s" % PLUGIN_VERSION, [u"\n".join(lines)], u"", False)

    @staticmethod
    def _on(flag):
        return u"مفعّل" if flag else u"معطّل"

    # ================================================================== v1.8 menus
    def _menu(self, title, items):
        self._choice(title, [(l, f) for l, f in items], lambda c: c and c[1]())

    def key_menu(self):
        cfg = BG.cfg
        it = []
        if Player.active or BG.rec is not None or BG.tv_want:
            it.append((u"إغلاق البلاجين وإيقاف القرآن (يعود صوت القناة)", self.key_exit))
        if Player.active:
            it.append((u"🎛 المشغّل الكبير (سرعة • تكرار • علامات)", self.open_player))
            it.append((u"سرعة التلاوة: ×%s ..." % BG._sp(BG.cur_speed()), self.speed_menu))
            it.append((u"شاشة التشغيل الآن (صورة القارئ والتقدم)", self.open_now))
            it.append((u"وضع التلاوة السينمائي (الآية بخط كبير مع الصوت)", lambda: self.session.open(QHCinema)))
        r = cfg.get("resume")
        if r:
            it.append((u"تابع الاستماع: %s" % (r.get("title") or u"")[:38], BG.resume_last))
        if self.qh_focus in (0, 1, 2):
            it.append((u"حذف المحدد من القائمة (مصدر لا يعمل أو قارئ) - زر 5", self.key_hide))
        if self.qh_focus == 0 and self.current(0)[1] is not None:
            it.append((u"تحريك المصدر المحدد لأعلى", lambda: self.move_source(-1)))
            it.append((u"تحريك المصدر المحدد لأسفل", lambda: self.move_source(1)))
        if BG.cfg.get("hidden_secs") or BG.cfg.get("hidden_items"):
            it.append((u"المحذوفات (استعادة) ...", self.menu_hidden))
        it.append((BG.reciter_of_day_text() + u"  ▶", BG.play_reciter_of_day))
        if self.qh_focus in (1, 2) and self.sel_payload():
            it.append((u"➕ إضافة المحدد إلى «التالي» (يعمل بعد الحالي)", self.upnext_selected))
        if BG.cfg.get("marks"):
            it.append((u"🔖 علاماتي (%d) ..." % len(BG.cfg["marks"]), self.marks_menu))
        it += [(u"🔎 البحث عن قارئ (كل المواقع) - تشغيل وتنزيل ...", self.reciter_search),
               (u"📁 مصادر من القرص (مجلدات القراء MP3 / FLAC) ...", self.menu_disk),
               (u"📺 باقة المفضلة في قائمة القنوات ...", self.menu_fav_bouquet),
               (u"📚 مكتبتي (الملفات المنزّلة • تحويل الصيغة) ...", self.menu_mylib),
               (u"🤖 بوت تليجرام ...", self.menu_bot),
               (u"القرآن مع صورة القناة ...", self.menu_tv),
               (u"القراءة والتفسير والأذكار ...", self.menu_reader),
               (u"الاستوديو: الحفظ • الاختبار • الأطفال • الختمة ...", lambda: studio_menu(self.session)),
               (u"السجل • الأكثر استماعاً • قوائمي • المحفوظات ...", self.menu_library),
               (u"بحث شامل في كل المواقع ...", self.search_global),
               (u"الصلاة والجدولة والتذكيرات ...", self.menu_time),
               (u"🌙 رمضان والمناسبات ...", self.menu_ramadan),
               (u"📻 إذاعتي الخاصة ...", self.menu_station),
               (u"💽 القرص والسرعة والثبات ...", self.menu_hdd),
               (u"👪 الملف الشخصي: %s ..." % (BG.cfg.get("profile") or studio.profiles(BG.cfg)[0]), self.menu_profiles19),
               (u"🌾 حصاد الشهر", lambda: self.show_harvest("month")),
               (u"🌾 حصاد السنة", lambda: self.show_harvest("year")),
               (u"⭐ النجوم", self.show_stars),
               (u"📡 مكتبتي لأجهزة البيت (DLNA) ...", self.menu_dlna),
               (u"المظهر والعرض والاختصارات ...", self.menu_display),
               (u"التحكم من الجوال ...", self.menu_phone),
               (u"قنوات تليجرام (إضافة / حذف) ...", self.menu_tg),
               (u"باقة الإذاعات في قائمة القنوات ...", lambda: studio_bouquet(self.session)),
               (u"نسخ احتياطي واستعادة ...", self.menu_backup),
               (u"أدوات وتشخيص ...", self.menu_misc),
               (u"شاشة البطاقات", self.open_home_screen)]
        self._menu(u"القائمة الرئيسية", it)

    def move_source(self, d):
        """Change the place of the selected source inside its group (remembered)."""
        _l, i = self.current(0)
        if i is None:
            return
        key = SECTIONS[i][0]
        group = self.qh_group_of.get(i)
        view = [SECTIONS[x][0] for _lab, x in self.qh_view[0] if x is not None and self.qh_group_of.get(x) == group]
        if key not in view:
            return
        j = view.index(key)
        k = j + d
        if k < 0 or k >= len(view):
            return
        view[j], view[k] = view[k], view[j]
        order = [x for x in (BG.cfg.get("sec_order") or []) if x not in view]
        BG.cfg["sec_order"] = order + view
        BG.save()
        self.build_sections(self.qh_extra_sec)
        for r, (_lab, x) in enumerate(self.qh_view[0]):
            if x == i:
                self[NAMES[0]].moveToIndex(r)
                break
        self.selection_changed()

    def key_hide(self):
        """Remove the selected source (right column) or reciter (middle column) from the lists."""
        f = self.qh_focus
        if f == 2:
            f = 1
            self.set_focus(1)
        _i, payload = self.current(f)
        if payload is None:
            return self.qh_status_text(u"اختر مصدراً أو قارئاً أولاً")
        if f == 0:
            key = SECTIONS[payload][0]
            if key == "fav":
                return self.qh_status_text(u"لا يمكن حذف المفضلة")
            what, label = u"المصدر", SECTIONS[payload][1]
        else:
            key = SECTIONS[self.qh_sec][0]
            what, label = u"القارئ", self.qh_view[1][_i][0].lstrip(u"★ ")

        def done(c=None):
            if not c or c[1] != "yes":
                return
            if f == 0:
                BG.cfg["hidden_secs"] = sorted(set(BG.cfg.get("hidden_secs", [])) | {key})
                BG.save()
                self.build_sections()
                self.load_section()
            else:
                lst = [list(x) for x in BG.cfg.get("hidden_items", [])]
                lst.append([key, self.qh_view[1][_i][0]])
                BG.cfg["hidden_items"] = lst
                BG.save()
                self.apply(1)
            self.qh_status_text(u"تم حذف %s: %s  (للاستعادة: MENU > المحذوفات)" % (what, label))
        self._choice(u"حذف %s «%s» من القائمة؟" % (what, label), [(u"نعم، احذفه", "yes"), (u"لا", "no")], done)

    def menu_hidden(self):
        it = []
        names = dict((s[0], s[1]) for s in SECTIONS)
        for k in BG.cfg.get("hidden_secs", []):
            it.append((u"استعادة المصدر: %s" % names.get(k, k), lambda k=k: self.unhide_sec(k)))
        for k, label in BG.cfg.get("hidden_items", []):
            it.append((u"استعادة القارئ: %s  (%s)" % (label, names.get(k, k)), lambda k=k, l=label: self.unhide_item(k, l)))
        if not it:
            return self.qh_status_text(u"لا توجد عناصر محذوفة")
        it.append((u"استعادة الكل", self.unhide_all))
        self._menu(u"المحذوفات", it)

    def unhide_sec(self, k):
        BG.cfg["hidden_secs"] = [x for x in BG.cfg.get("hidden_secs", []) if x != k]
        BG.save()
        self.build_sections()

    def unhide_item(self, k, label):
        BG.cfg["hidden_items"] = [x for x in BG.cfg.get("hidden_items", []) if list(x) != [k, label]]
        BG.save()
        self.apply(1)

    def unhide_all(self):
        BG.cfg["hidden_secs"], BG.cfg["hidden_items"] = [], []
        BG.save()
        self.build_sections()
        self.apply(1)

    def health_time_pick(self):
        opts = [(u"إيقاف", None)] + [(u"%02d:00" % h, u"%02d:00" % h) for h in range(24)]

        def done(c=None):
            if c:
                BG.cfg["health_time"] = c[1]
                BG.save()
        self._choice(u"وقت الفحص الليلي (يعمل والجهاز غير مشغول)", opts, done)

    def menu_tg(self):
        it = [(u"إضافة قناة تليجرام عامة (اسم المستخدم أو الرابط) ...", self.tg_add)]
        for u, n in tg_channels(BG.cfg):
            it.append((u"حذف: %s  (@%s)" % (n, u), lambda u=u: self.tg_remove(u)))
        it.append((u"ملاحظة: تُشغَّل المقاطع المرئية والصوتية القصيرة فقط - ملفات الصوت الكاملة تُفتح في تطبيق تليجرام",
                   lambda: None))
        self._menu(u"قنوات تليجرام", it)

    def tg_add(self):
        self.session.openWithCallback(self.tg_add_done, VirtualKeyBoard, title=u"اسم القناة (مثال: El_minshawy أو t.me/El_minshawy)")

    def tg_add_done(self, text=None):
        u = data.tg_clean_user(text)
        if not u:
            return self.qh_status_text(u"اسم القناة غير صحيح")
        self.qh_status_text(u"جاري فحص القناة @%s ..." % u)

        def done(title):
            if isinstance(title, Exception):
                return self.qh_status_text(u"تعذّر الوصول للقناة: %s" % title)
            name = (title or u).strip()
            chans = [x for x in BG.cfg.get("tg_channels", []) if x[0].lower() != u.lower()]
            chans.append([u, name])
            BG.cfg["tg_channels"] = chans
            BG.cfg["tg_removed"] = [x for x in BG.cfg.get("tg_removed", []) if x.lower() != u.lower()]
            BG.save()
            self.build_sections()
            self.fetch_tg_pictures()
            self.qh_status_text(u"أضيفت القناة: %s" % name)
        self.qh_runner.run(lambda: data.tg_title(u), done, done)

    def tg_remove(self, u):
        BG.cfg["tg_channels"] = [x for x in BG.cfg.get("tg_channels", []) if x[0].lower() != u.lower()]
        rem = set(x.lower() for x in BG.cfg.get("tg_removed", []))
        if u.lower() in set(x.lower() for x, _n in data.TG_DEFAULT):
            rem.add(u.lower())
        BG.cfg["tg_removed"] = sorted(rem)
        BG.save()
        self.build_sections()
        self.qh_status_text(u"حُذفت القناة @%s" % u)

    def menu_library(self):
        self._menu(u"مكتبتي", [
            (u"سجل الاستماع", lambda: self.goto_section("hist")),
            (u"الأكثر استماعاً", lambda: self.goto_section("most")),
            (u"قوائمي", lambda: self.goto_section("pls")),
            (u"المحفوظات على القرص (HDD/USB)", lambda: self.goto_section("local")),
            (u"إدارة قوائم التشغيل ...", self.menu_playlists),
            (u"التنزيل ...", self.menu_downloads)])

    TV_STRAT = {"pip": u"صورة القناة كاملة + القرآن", "overlay": u"مشغّل ثانٍ فوق القناة", "off": u"بدون صورة"}

    def menu_tv(self):
        cfg = BG.cfg
        it = [(u"الوضع: %s   (المستخدم الآن: %s)" % (dict(BG.TV_MODES)[BG.tv_mode()], self.TV_STRAT[BG.tv_strategy()]),
               self.key_tvmode),
              (u"تغيير القناة من الريموت لا يوقف القرآن: %s" % self._on(cfg.get("follow", True)),
               lambda: BG.toggle_flag("follow", True, u"تغيير القناة لا يوقف القرآن")),
              (u"اختر قناة الآن (صورتها مع صوت القرآن)", lambda: self.tv_choice((u"", "zap")))]
        if BG.tv_last_ref() is not None:
            it.append((u"اعرض آخر قناة مع القرآن", lambda: self.tv_choice((u"", "pip_last"))))
        it += [(u"حجم الصورة: %s" % BG.tv_size_name(), BG.tv_cycle_size)]
        if BG.tv_want or BG.tv_on:
            it += [(u"إعادة تشغيل الصورة", lambda: self.tv_choice((u"", "retry"))),
                   (u"إيقاف الصورة (يبقى القرآن)", BG.tv_stop)]
        it += [(u"تجاهل فحص دعم PiP: %s" % self._on(cfg.get("pip_force")), BG.tv_toggle_force),
               (u"كيف يعمل؟", self.tv_help), (u"سجل الأخطاء التقني", self.show_diag)]
        self._menu(u"القرآن مع صورة القناة", it)

    def tv_help(self):
        try:
            from Screens.MessageBox import MessageBox
            self.session.open(MessageBox, (
                u"شغّل أي تلاوة أو إذاعة ثم اخرج من البلاجين (EXIT أو الأحمر).\n\n"
                u"غيّر القنوات كالمعتاد (CH+ / CH- / الأرقام / قائمة القنوات): تتغيّر الصورة فقط ويستمر القرآن.\n\n"
                u"الطريقة: القرآن على المشغّل الرئيسي، والقناة في نافذة PiP بحجم الشاشة (نافذة PiP لا تُخرج صوتاً، "
                u"فلا يختلط الصوتان).\n\n"
                u"إن لم يدعم جهازك PiP يتحوّل البلاجين تلقائياً إلى المشغّل الثاني فوق القناة.\n\n"
                u"لإيقاف القرآن والعودة لصوت القناة: الزر الأزرق > Saad Quran Hub - إيقاف التشغيل الخلفي، أو من داخل البلاجين."),
                MessageBox.TYPE_INFO)
        except Exception:
            pass

    # -- display / control
    def menu_display(self):
        cfg = BG.cfg
        self._menu(u"القناة والعرض والتحكم", [
            (u"اللغة / Language: %s" % (u"English" if i18n.on() else u"العربية"), self.menu_lang),
            (u"الوضع المبسّط (لكبار السن): %s" % self._on(cfg.get("simple_mode", False)),
             lambda: BG.toggle_flag("simple_mode", False, u"الوضع المبسّط - يظهر عند فتح البلاجين")),
            (u"مؤقت النوم: خفض الصوت تدريجياً ثم الانتظار: %s" % self._on(cfg.get("sleep_standby", True)),
             lambda: BG.toggle_flag("sleep_standby", True, u"الانتظار بعد مؤقت النوم")),
            (u"ما الجديد في هذا الإصدار", self.show_whats_new),
            (u"القرآن مع صورة القناة ...", self.menu_tv),
            (u"العودة إلى البث المباشر", BG.go_live),
            (u"ذاكرة الرجوع للخلف للإذاعات: %s" % self._on(cfg.get("timeshift", True)), BG.toggle_timeshift),
            (u"الشريط المصغّر: %s" % self._on(cfg.get("minibar", True)), BG.toggle_minibar),
            (u"التحكم بالريموت أثناء التصغير: %s" % self._on(cfg.get("remote", True)),
             lambda: BG.toggle_flag("remote", True, u"التحكم بالريموت أثناء التصغير")),
            (u"تخصيص الاختصارات (الألوان والأرقام) ...", self.menu_colors),
            (u"اختيار المظهر (%d مظهراً) ..." % len(THEMES), self.theme_pick),
            (u"المظهر التلقائي: %s ..." % self.AUTO_THEME_LABEL.get(cfg.get("auto_theme", "off")), self.auto_theme_menu),
            (u"شاشة البطاقات عند الفتح بدل المكتبة: %s" % self._on(cfg.get("home_screen", False)),
             lambda: BG.toggle_flag("home_screen", False, u"شاشة البطاقات عند الفتح")),
            (u"المصدر البديل التلقائي: %s" % self._on(cfg.get("alt_source", True)),
             lambda: BG.toggle_flag("alt_source", True, u"المصدر البديل التلقائي")),
            (u"المظهر التالي: %s" % THEMES[BG.theme_idx()]["name"], self.key_theme),
            (u"طريقة عرض النص في القراءة: %s" % (u"قائمة" if cfg.get("reader_engine", "list") == "list" else u"مربعات رسائل"),
             self.toggle_engine_text),
            (u"تحديث القوائم (مسح الذاكرة المؤقتة)", self.refresh_lists)])

    def toggle_engine_text(self):
        BG.cfg["reader_engine"] = "msgbox" if BG.cfg.get("reader_engine", "list") == "list" else "list"
        BG.save()
        self.qh_status_text(u"طريقة عرض النص: %s" % (u"قائمة" if BG.cfg["reader_engine"] == "list" else u"مربعات رسائل"))

    AUTO_THEME_LABEL = {"off": u"إيقاف", "daynight": u"نهار / ليل", "prayer": u"حسب وقت الصلاة"}

    def auto_theme_menu(self):
        self._choice(u"المظهر التلقائي", [
            (u"إيقاف (مظهر ثابت)", "off"),
            (u"نهار: فاتح رملي  /  ليل: أسود OLED", "daynight"),
            (u"حسب وقت الصلاة (فجر أزرق • ظهر فاتح • عصر دافئ • مغرب بنفسجي • عشاء زمردي)", "prayer"),
            (u"اختيار مظهر النهار ...", "day"), (u"اختيار مظهر الليل ...", "night")], self._auto_theme_set)

    def _auto_theme_set(self, c=None):
        if not c:
            return
        k = c[1]
        if k in ("day", "night"):
            def done(r=None, key="theme_" + k):
                if r:
                    BG.cfg[key] = r[1]
                    BG.cfg["auto_theme"] = "daynight"
                    BG.save()
                    BG._theme_cache = (0, 0, None)
                    self.close("retheme")
            return self._choice(u"مظهر النهار" if k == "day" else u"مظهر الليل",
                                [(u"%2d. %s" % (i + 1, t["name"]), i) for i, t in enumerate(THEMES)], done)
        BG.cfg["auto_theme"] = k
        BG.save()
        BG._theme_cache = (0, 0, None)
        BG.hide_minibar()
        BG.mini = None
        self.close("retheme")

    def menu_misc(self):
        self._menu(u"أدوات", [
            (u"التشخيص الذاتي (الإنترنت • المواقع • القرص • المشغّلات) ...", self.open_diag),
            (u"صيغة التسجيل: %s" % data.FORMAT_LABEL.get(BG.cfg.get("fmt"), u"الأصلي"), self.key_format),
            (u"مؤقت النوم", self.key_sleep),
            (u"المشغّل: %s" % Player.engine_name(), self.key_engine),
            (u"إحصائيات الاستماع", lambda: _studio_info(self.session, studio.stats_text(BG.cfg))),
            (u"فحص كل المصادر الآن", BG.health_check),
            (u"تحديث البلاجين (من ملف ipk أو رابط) ...", self.menu_update),
            (u"آية عند تشغيل الجهاز: %s" % self._on(BG.cfg.get("boot_ayah", True)),
             lambda: BG.toggle_flag("boot_ayah", True, u"آية عند تشغيل الجهاز")),
            (u"المصادر والحقوق", lambda: self.session.open(QHText, u"المصادر والحقوق", studio.CREDITS, u"", False)),
            (u"وقت الفحص الليلي للمصادر: %s" % (BG.cfg.get("health_time", "04:00") or u"إيقاف"), self.health_time_pick),
            (u"سجل الأخطاء التقني", self.show_diag)])

    # -- shortcuts: colour keys and number keys, all configurable
    ACTIONS = [("minimise", u"تصغير", "key_minimise"), ("play", u"تشغيل / فتح", "key_ok"),
               ("closeall", u"إغلاق البلاجين وإيقاف القرآن", "key_exit"),
               ("hide", u"حذف المحدد من القائمة", "key_hide"),
               ("search", u"بحث", "key_search"), ("gsearch", u"بحث شامل", "search_global"),
               ("stop", u"إيقاف", "key_stop"), ("record", u"تسجيل", "key_record"),
               ("fav", u"مفضلة", "key_fav"), ("menu", u"القائمة", "key_menu"),
               ("prev", u"السابق", "prev_track"), ("next", u"التالي", "next_track"),
               ("rewind", u"رجوع 30 ث", "key_rewind"), ("forward", u"تقديم 30 ث", "key_forward"),
               ("pause", u"إيقاف مؤقت", "key_pause"), ("golive", u"العودة للمباشر", "key_golive"),
               ("resume", u"تابع الاستماع", "key_resume"), ("reader", u"قراءة السورة", "open_reader_now"),
               ("format", u"صيغة التسجيل", "key_format"), ("engine", u"المشغّل", "key_engine"),
               ("sleep", u"مؤقت النوم", "key_sleep"), ("tv", u"القنوات والصورة", "key_tv"),
               ("tvmode", u"وضع القناة + القرآن", "key_tvmode"), ("theme", u"المظهر التالي", "key_theme"),
               ("themepick", u"اختيار المظهر", "theme_pick"), ("volup", u"رفع الصوت", "vol_up"),
               ("voldown", u"خفض الصوت", "vol_down"), ("mute", u"كتم", "vol_mute"),
               ("dl", u"تنزيل الحالي", "dl_current"), ("pladd", u"إضافة لقائمة", "key_pladd"),
               ("prayer", u"مواقيت الصلاة", "prayer_show"), ("refresh", u"تحديث القوائم", "refresh_lists"),
               ("nowplaying", u"شاشة التشغيل الآن", "open_now"), ("home", u"الشاشة الرئيسية", "open_home_screen"),
               ("rsearch", u"البحث عن قارئ", "reciter_search"), ("mylib", u"مكتبتي", "menu_mylib"),
               ("player", u"المشغّل الكبير", "open_player"), ("speed", u"سرعة التلاوة", "speed_menu"),
               ("mark", u"حفظ علامة", "mark_here"), ("abrep", u"تكرار مقطع A-B", "ab_here"),
               ("diag", u"التشخيص الذاتي", "open_diag"),
               ("help", u"عرض الاختصارات", "show_shortcuts")]
    KEY_DEFAULT = {"red": "minimise", "green": "play", "yellow": "search", "blue": "stop",
                   "0": "record", "1": "minimise", "2": "format", "3": "fav", "4": "prev",
                   "5": "hide", "6": "next", "7": "sleep", "8": "theme", "9": "tv"}
    KEY_NAMES = {"red": u"الأحمر", "green": u"الأخضر", "yellow": u"الأصفر", "blue": u"الأزرق"}
    KEY_ORDER = ["red", "green", "yellow", "blue", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    # on-screen buttons that show the action of a number key
    BUTTON_KEYS = (("qh_tv", "9"), ("qh_fmt", "2"), ("qh_fav", "3"), ("qh_sleep", "7"), ("qh_theme", "8"))

    @classmethod
    def key_title(cls, k):
        return cls.KEY_NAMES.get(k, u"رقم " + k)

    def key_action(self, k):
        want = (BG.cfg.get("keys") or {}).get(k, self.KEY_DEFAULT[k])
        for aid, label, meth in self.ACTIONS:
            if aid == want:
                return aid, label, meth
        return self.ACTIONS[0]

    def shortcut(self, k):
        getattr(self, self.key_action(k)[2])()

    def action_text(self, aid, label):
        if aid == "format":
            return u"الصيغة: %s" % data.FORMAT_LABEL.get(BG.cfg.get("fmt"), u"الأصلي")
        if aid == "sleep":
            m = BG.cfg_sleep_minutes()
            return u"نوم: %s" % (u"%d د" % m if m else u"إيقاف")
        if aid == "theme":
            return u"المظهر: %s" % THEMES[BG.theme_idx()]["name"]
        if aid == "tv":
            return u"القنوات: %s" % (u"✔" if BG.tv_on else (u"..." if BG.tv_want else u"إيقاف"))
        if aid == "tvmode":
            return u"قناة+قرآن: %s" % dict(BG.TV_MODES)[BG.tv_mode()].split(u" ")[0]
        return label

    def color_labels(self):
        for c in ("red", "green", "yellow", "blue"):
            self["qh_" + c].setText(i18n.T(self.key_action(c)[1]))
        self.button_labels()

    def button_labels(self):
        for widget, k in self.BUTTON_KEYS:
            aid, label, _m = self.key_action(k)
            self[widget].setText(u"%s (%s)" % (i18n.T(self.action_text(aid, label)), k))

    def menu_colors(self):
        self._menu(u"اختر زراً لتخصيصه", [
            (u"%s  ←  %s" % (self.key_title(k), self.key_action(k)[1]), (lambda k=k: self.pick_key_action(k)))
            for k in self.KEY_ORDER] + [(u"استعادة الاختصارات الافتراضية", self.reset_keys),
                                        (u"عرض كل الاختصارات", self.show_shortcuts)])

    def pick_key_action(self, k):
        def setit(aid):
            BG.cfg.setdefault("keys", {})[k] = aid
            BG.save()
            self.color_labels()
            self.qh_status_text(u"تم: %s ← %s" % (self.key_title(k), dict((a, l) for a, l, _ in self.ACTIONS)[aid]))
        self._menu(u"وظيفة %s" % self.key_title(k),
                   [(l, (lambda a=a: setit(a))) for a, l, _ in self.ACTIONS])

    def reset_keys(self):
        BG.cfg["keys"] = {}
        BG.save()
        self.color_labels()
        self.qh_status_text(u"أُعيدت الاختصارات الافتراضية")

    def show_shortcuts(self):
        lines = [u"%s :  %s" % (self.key_title(k), self.key_action(k)[1]) for k in self.KEY_ORDER]
        lines += [u"", u"MENU :  القائمة الرئيسية", u"◀◀ ▶▶ :  رجوع / تقديم 30 ث", u"OK :  فتح / تشغيل"]
        text = u"\n".join(lines)
        try:
            from Screens.MessageBox import MessageBox
            self.session.open(MessageBox, text, MessageBox.TYPE_INFO)
        except Exception:
            self.qh_status_text(text.replace(u"\n", u" | "))

    def key_pause(self):
        BG.toggle_pause()

    def key_golive(self):
        BG.go_live()

    def key_tvmode(self):
        BG.cycle_tv_mode()
        self.button_labels()

    def vol_up(self):
        BG.vol_change(5)

    def vol_down(self):
        BG.vol_change(-5)

    def vol_mute(self):
        BG.vol_mute()

    def key_pladd(self):
        self.pl_pick(self.pl_add_current)

    def refresh_lists(self):
        SEC_CACHE.clear()
        SUBS_CACHE.clear()
        try:
            import shutil
            shutil.rmtree(data.CACHE_DIR, ignore_errors=True)
        except Exception:
            pass
        self.qh_status_text(u"تم مسح الذاكرة المؤقتة - جاري إعادة التحميل")
        self.load_section()

    def theme_pick(self):
        self._choice(u"اختر المظهر", [(u"%2d. %s" % (i + 1, t["name"]), i) for i, t in enumerate(THEMES)],
                     self._theme_set)

    def _theme_set(self, c=None):
        if c is None:
            return
        BG.cfg["theme"] = c[1]
        BG.cfg["auto_theme"] = "off"
        BG.save()
        BG.hide_minibar()
        BG.mini = None
        self.close("retheme")

    def key_resume(self):
        BG.resume_last()

    # -- section helpers
    def goto_section(self, key):
        for i, s in enumerate(SECTIONS):
            if s[0] == key:
                if self.sec_row(i) is None:
                    self.build_sections(key)
                try:
                    self["qh_sec"].moveToIndex(self.sec_row(i) or 0)
                except Exception:
                    pass
                self.qh_sec_timer.stop()
                self.load_section()
                self.set_focus(1)
                return

    def cur_item(self):
        if not Player.active or not BG.cur_url:
            return None
        return {"title": Player.cur_title or BG.cur_url, "url": BG.cur_url, "live": bool(BG.cur_live)}

    def sel_payload(self):
        if self.qh_focus == 0:
            return None
        _, pl_ = self.current(self.qh_focus)
        if pl_ and (pl_.get("url") or pl_.get("resolve")):
            return pl_
        return None

    # -- global search
    def search_global(self):
        self.session.openWithCallback(self._gsearch, VirtualKeyBoard, title=u"بحث شامل (قارئ / إذاعة / سورة)", text=u"")

    def _gsearch(self, text=None):
        if not text or not text.strip():
            return
        self.qh_status_text(u"جاري البحث في كل المواقع ...")
        BG.search_all(text.strip(), self._gsearch_done)

    def _gsearch_done(self, rows):
        if isinstance(rows, Exception):
            return self.qh_status_text(u"تعذّر البحث: %s" % rows)
        BG.search_rows = rows or [(u"لا توجد نتائج", None)]
        self.qh_status_text(u"نتائج البحث: %d" % len(rows or []))
        self.goto_section("srch")

    # -- playlists
    def menu_playlists(self):
        it = [(u"قائمة جديدة (وتضم المقطع الحالي)", self.pl_new),
              (u"إضافة المقطع الحالي إلى قائمة", lambda: self.pl_pick(self.pl_add_current)),
              (u"إضافة المحدّد إلى قائمة", lambda: self.pl_pick(self.pl_add_selected)),
              (u"حذف قائمة", lambda: self.pl_pick(self.pl_delete))]
        _, cur = self.current(1) if self.qh_focus >= 1 else (None, None)
        if SECTIONS[self.qh_sec][0] == "pls" and self.qh_focus == 2:
            it.append((u"إزالة المحدّد من هذه القائمة", self.pl_remove_selected))
        it.append((u"فتح قسم قوائمي", lambda: self.goto_section("pls")))
        self._menu(u"قوائم التشغيل", it)

    def pl_new(self):
        self.session.openWithCallback(self._pl_named, VirtualKeyBoard, title=u"اسم القائمة الجديدة", text=u"")

    def _pl_named(self, name=None):
        if not name or not name.strip():
            return
        name = name.strip()
        BG.cfg.setdefault("pls", {}).setdefault(name, [])
        item = self.cur_item()
        if item:
            extras.pl_add(BG.cfg, name, item)
        BG.save()
        self.qh_status_text(u"تم إنشاء القائمة: %s" % name)

    def pl_pick(self, cb):
        names = sorted(BG.cfg.get("pls", {}))
        if not names:
            return self.qh_status_text(u"لا توجد قوائم - أنشئ قائمة جديدة أولاً")
        self._choice(u"اختر القائمة", [(n, n) for n in names], lambda c: c and cb(c[1]))

    def pl_add_current(self, name):
        item = self.cur_item()
        if not item:
            return self.qh_status_text(u"لا يوجد مقطع قيد التشغيل")
        ok = extras.pl_add(BG.cfg, name, item)
        BG.save()
        self.qh_status_text(u"أُضيف إلى «%s»" % name if ok else u"المقطع موجود في «%s» مسبقاً" % name)

    def pl_add_selected(self, name):
        pld = self.sel_payload()
        if pld is None:
            return self.qh_status_text(u"حدّد مقطعاً أو سورة أولاً")
        title = pld.get("title", u"")
        live = bool(pld.get("live"))

        def add(url):
            if isinstance(url, Exception) or not url:
                return self.qh_status_text(u"تعذّر تجهيز الرابط")
            ok = extras.pl_add(BG.cfg, name, {"title": title, "url": url, "live": live})
            BG.save()
            self.qh_status_text(u"أُضيف إلى «%s»: %s" % (name, title) if ok else u"موجود مسبقاً")
        if pld.get("url"):
            add(pld["url"])
        else:
            self.qh_status_text(u"جاري تجهيز الرابط ...")
            self.qh_runner.run(pld["resolve"], add, add)

    def pl_delete(self, name):
        BG.cfg.get("pls", {}).pop(name, None)
        BG.save()
        self.qh_status_text(u"حُذفت القائمة: %s" % name)
        if SECTIONS[self.qh_sec][0] == "pls":
            self.load_section()

    def pl_remove_selected(self):
        pld = self.sel_payload()
        if not pld or not pld.get("plname"):
            return
        items = BG.cfg.get("pls", {}).get(pld["plname"], [])
        BG.cfg["pls"][pld["plname"]] = [x for x in items if x["url"] != pld["url"]]
        BG.save()
        self.qh_status_text(u"أُزيل من القائمة")
        self.load_subs()

    # ================================================================== 1.6: reciter search / library / bot
    def _choice_at(self, title, opts, cb, sel=0):
        try:
            from Screens.ChoiceBox import ChoiceBox
            if i18n.on():
                title, opts = i18n.T(title), [(i18n.T(o[0]),) + tuple(o[1:]) for o in opts]
            try:
                self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts, selection=max(0, sel))
            except TypeError:
                self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
        except Exception as e:
            self.qh_status_text(u"تعذّر فتح القائمة: %s" % e)

    def reciter_search(self):
        def got(text=None):
            if text and text.strip():
                self.qh_rs_q = text.strip()
                self.qh_status_text(u"🔎 أبحث عن «%s» في كل المواقع ..." % self.qh_rs_q)
                BG.search_reciters(self.qh_rs_q, self._rs_done)
        self.session.openWithCallback(got, VirtualKeyBoard, title=u"البحث عن قارئ في كل المواقع",
                                      text=getattr(self, "qh_rs_q", u""))

    def _rs_done(self, groups):
        if isinstance(groups, Exception) or not groups:
            return self.qh_status_text(u"لم أجد قارئاً بهذا الاسم - جرّب جزءاً من الاسم")
        self.qh_status_text(u"وجدت %d قارئاً" % len(groups))
        self._choice(u"نتائج «%s» (الرقم = عدد المصادر)" % self.qh_rs_q,
                     [(u"%s   (%d)" % (g[0], len(g[1])), g) for g in groups],
                     lambda c: c and self.reciter_pick(c[1]))

    def reciter_pick(self, g):
        if len(g[1]) == 1:
            return self.reciter_source(g[1][0])
        self._choice(u"%s - اختر المصدر / الرواية" % g[0], [(u"%s  ·  %s" % (s[0], s[2]), s) for s in g[1]],
                     lambda c: c and self.reciter_source(c[1]))

    def reciter_source(self, src):
        _t, _k, label, entry = src
        self.qh_status_text(u"جاري تحميل سور %s ..." % label)

        def done(rows):
            if isinstance(rows, Exception) or not rows:
                return self.qh_status_text(u"تعذّر تحميل سور هذا المصدر")
            parts, cur = [], [label, []]
            for lab, x in rows:
                if x is None:
                    if cur[1]:
                        parts.append(cur)
                    cur = [u"%s - %s" % (label, lab.strip(u"— ").strip()), []]
                elif x.get("url") or x.get("resolve"):
                    cur[1].append((lab, x))
            if cur[1]:
                parts.append(cur)
            if not parts:
                return self.qh_status_text(u"لا توجد سور قابلة للتشغيل")
            if len(parts) == 1:
                return self.reciter_actions(parts[0][0], parts[0][1])
            self._choice(u"%s - اختر المصحف / الرواية" % label,
                         [(u"%s  (%d سورة)" % (p_[0], len(p_[1])), p_) for p_ in parts],
                         lambda c: c and self.reciter_actions(c[1][0], c[1][1]))
        BG.source_rows(entry, done)

    def reciter_actions(self, name, pls):
        self.qh_rs_cur = (name, pls)
        fmt = data.FORMAT_LABEL.get(BG.dl_format(), u"")
        self._menu(u"%s  (%d سورة)" % (name, len(pls)), [
            (u"▶ تشغيل سورة ...", lambda: self._choice(u"%s - اختر السورة" % name,
                                                       [(lab, i) for i, (lab, _x) in enumerate(pls)],
                                                       lambda c: c and self._rs_play(pls, c[1]))),
            (u"▶ تشغيل الكل بالترتيب", lambda: self._rs_play(pls, 0)),
            (u"⬇ تنزيل سور مختارة ...", lambda: self._rs_multi(name, pls, set(), 0)),
            (u"⬇ تنزيل المصحف كاملاً (%d سورة)" % len(pls), lambda: self._rs_dl_all(name, pls)),
            (u"صيغة التنزيل: %s" % fmt, lambda: self.pick_dl_format(lambda: self.reciter_actions(name, pls)))])

    def _rs_play(self, pls, i):
        BG.ctx = None
        BG.play_list([x for _l, x in pls], i)
        self.qh_status_text(u"▶ %s" % pls[i][1].get("title", u""))

    def _rs_dl_all(self, name, pls):
        self._choice(u"تنزيل %d سورة للقارئ %s بصيغة %s؟" % (len(pls), name, data.FORMAT_LABEL.get(BG.dl_format(), u"")),
                     [(u"نعم، ابدأ (يكمل في الخلفية ولو أُغلق البلاجين)", True), (u"إلغاء", False)],
                     lambda c: c and c[1] and BG.download_payloads([x for _l, x in pls]))

    def _rs_multi(self, name, pls, sel, pos):
        opts = [(u"✔ ابدأ تنزيل المحدّد (%d)" % len(sel), "go"), (u"☑ تحديد الكل", "all"), (u"☐ إلغاء التحديد", "none")]
        opts += [((u"☑ " if i in sel else u"☐ ") + lab, i) for i, (lab, _x) in enumerate(pls)]

        def cb(c=None):
            if not c:
                return
            v = c[1]
            if v == "go":
                if sel:
                    BG.download_payloads([pls[i][1] for i in sorted(sel)])
                return
            if v == "all":
                return self._rs_multi(name, pls, set(range(len(pls))), 0)
            if v == "none":
                return self._rs_multi(name, pls, set(), 0)
            sel.symmetric_difference_update([v])
            self._rs_multi(name, pls, sel, v + 3)
        self._choice_at(u"%s - حدّد السور ثم «ابدأ»" % name, opts, cb, pos)

    def pick_dl_format(self, then=None):
        opts = [(u"%s%s" % (l, u"  ✓" if k == BG.dl_format() else u""), k) for k, l in data.available_formats()]
        if not data.which("ffmpeg"):
            opts.append((u"تثبيت ffmpeg لتفعيل كل الصيغ ...", "ffmpeg"))

        def cb(c=None):
            if c and c[1] == "ffmpeg":
                return self.install_ffmpeg()
            if c:
                BG.cfg["dl_fmt"] = c[1]
                BG.save()
            if then:
                then()
        self._choice(u"صيغة التنزيل (الأصلي = أفضل جودة بلا تحويل)", opts, cb)

    def install_ffmpeg(self):
        try:
            from Screens.Console import Console
            self.session.openWithCallback(self._ffmpeg_done, Console, title=u"تثبيت ffmpeg",
                                          cmdlist=["opkg update", "opkg install ffmpeg"])
        except Exception as e:
            self.qh_status_text(u"تعذّر التثبيت: %s" % e)

    def _ffmpeg_done(self, *a):
        data._cache.clear()
        self.qh_status_text(u"ffmpeg: %s" % (u"جاهز ✓" if data.which("ffmpeg") else u"لم يُثبَّت - ثبّته من مدير الإضافات"))

    # -- my library
    def menu_mylib(self):
        self.qh_status_text(u"جاري قراءة المكتبة ...")
        def scan_all():
            out = library.scan()
            for d in BG.cfg.get("disk_srcs", []):
                try:
                    for name, folder in library.disk_reciters(d["path"]):
                        items = []
                        for n, label, pth in library.disk_tracks(folder):
                            try:
                                items.append((n, label, pth, os.path.getsize(pth), os.path.splitext(pth)[1].lower()))
                            except OSError:
                                pass
                        if items:
                            out.append((u"%s ← %s" % (name.split(u" - ")[-1], d["name"]), folder, items))
                except Exception:
                    continue
            return out
        Runner().run(scan_all, self._lib_done, self._lib_done)

    def _lib_done(self, groups):
        if isinstance(groups, Exception):
            return self.qh_status_text(u"تعذّر قراءة المكتبة: %s" % groups)
        opts = [(u"%s  —  %s" % (rec, library.summary(items)), (rec, folder, items)) for rec, folder, items in groups]
        opts += [(u"🧹 ترتيب الملفات القديمة في مجلد لكل قارئ", "org"),
                 (u"⬇ التنزيلات والأعمال الجارية", "work")]
        if not groups:
            self.qh_status_text(u"المكتبة فارغة - نزّل قارئاً من «البحث عن قارئ»")
        self._choice(u"مكتبتي (الملفات المنزّلة على القرص)", opts, self._lib_pick)

    def _lib_pick(self, c=None):
        if not c:
            return
        v = c[1]
        if v == "org":
            n = library.organize()
            self.qh_status_text(u"رُتّب %d ملفاً في مجلدات القراء" % n)
            return self.menu_mylib()
        if v == "work":
            return self.qh_status_text(BG.work_text() or u"لا توجد تنزيلات أو أعمال جارية")
        self.lib_reciter(*v)

    def lib_reciter(self, rec, folder, items):
        pls = library.payloads(items, rec)
        it = [(u"▶ تشغيل الكل (%d)" % len(pls), lambda: self._lib_play(pls, 0)),
              (u"▶ تشغيل سورة ...", lambda: self._choice(rec, [(x[1], i) for i, x in enumerate(items)],
                                                         lambda c: c and self._lib_play(pls, c[1]))),
              (u"🔄 تحويل الصيغة (مثلاً MP3 ← FLAC) ...", lambda: self.lib_convert(rec, items)),
              (u"✨ تنقية الصوت لكل الملفات (إزالة التشويش وتوحيد العلو)", lambda: self.lib_clean(rec, items)),
              (u"💾 نسخ إلى فلاشة (للسيارة) ...", lambda: self.lib_copy(rec, items))]
        if BG.bot is not None and BG.tg_owners():
            it.append((u"📤 إرسال سورة إلى تليجرام ...", lambda: self._choice(
                u"أرسل إلى تليجرام", [(x[1], x) for x in items], lambda c: c and self.lib_send(rec, c[1]))))
        it.append((u"🗑 حذف كل ملفات %s" % rec, lambda: self._choice(
            u"حذف %d ملف نهائياً؟" % len(items), [(u"نعم، احذف", True), (u"إلغاء", False)],
            lambda c: c and c[1] and self.qh_status_text(u"حُذف %d ملف" % library.delete_files([x[2] for x in items])))))
        self._menu(u"%s — %s" % (rec, library.summary(items)), it)

    def _lib_play(self, pls, i):
        BG.ctx = None
        BG.play_list(pls, i)

    def lib_convert(self, rec, items):
        fmts = [(l, k) for k, l in data.available_formats() if k != "original"]
        if not fmts:
            return self._choice(u"التحويل يحتاج ffmpeg", [(u"تثبيت ffmpeg الآن", True), (u"إلغاء", False)],
                                lambda c: c and c[1] and self.install_ffmpeg())
        lossy = any(x[4] in (".mp3", ".m4a", ".ogg", ".aac", ".opus") for x in items)

        def fmt_cb(c=None):
            if not c:
                return
            fmt = c[1]
            note = u""
            if lossy and fmt in ("flac", "wav"):
                note = u"\nتنبيه: الملفات الآن MP3؛ تحويلها إلى %s يكبر حجمها ولا يحسّن الصوت." % data.FORMAT_LABEL[fmt]
            self._choice(u"تحويل %d ملف إلى %s%s" % (len(items), data.FORMAT_LABEL[fmt], note),
                         [(u"تحويل وحذف الملف القديم", False), (u"تحويل مع الإبقاء على القديم", True), (u"إلغاء", None)],
                         lambda k: k and k[1] is not None and self._lib_convert_go(rec, items, fmt, k[1]))
        self._choice(u"الصيغة الجديدة لملفات %s" % rec, fmts, fmt_cb)

    def _lib_convert_go(self, rec, items, fmt, keep):
        steps = [library.convert_step(x[2], fmt, keep) for x in items]
        BG.jobs.add(u"تحويل %s إلى %s" % (rec, data.FORMAT_LABEL[fmt]), steps)
        self.qh_status_text(u"بدأ التحويل في الخلفية (%d ملف) - سأخبرك عند الانتهاء" % len(steps))

    def lib_clean(self, rec, items):
        if not data.which("ffmpeg"):
            return self.install_ffmpeg()
        BG.jobs.add(u"تنقية صوت %s" % rec, [library.clean_step(x[2]) for x in items])
        self.qh_status_text(u"بدأت تنقية الصوت في الخلفية (%d ملف)" % len(items))

    def lib_copy(self, rec, items):
        dests = library.usb_targets(exclude=extras.download_dir())
        if not dests:
            return self.qh_status_text(u"لم أجد فلاشة أخرى متصلة (غير قرص المكتبة)")

        def cb(c=None):
            if not c:
                return
            dest = os.path.join(c[1], data.safe_name(u"القرآن - " + rec))
            BG.jobs.add(u"نسخ %s إلى الفلاشة" % rec, [library.copy_step(x[2], dest, x[0]) for x in items])
            self.qh_status_text(u"بدأ النسخ إلى %s" % dest)
        self._choice(u"انسخ %s إلى" % rec, dests, cb)

    def lib_send(self, rec, x):
        try:
            for o in BG.tg_owners():
                BG.bot.send_audio(o["id"], x[2], u"%s - %s" % (rec, x[1]))
            self.qh_status_text(u"📤 جاري الإرسال إلى تليجرام: %s" % x[1])
        except Exception as e:
            self.qh_status_text(u"تعذّر الإرسال: %s" % e)

    # -- telegram bot settings
    def menu_bot(self):
        cfg = BG.cfg
        owners = BG.tg_owners()
        it = [(u"البوت: %s" % (u"يعمل" if cfg.get("tg_bot", True) else u"متوقف"), self.bot_toggle),
              (u"الحالة: %s" % BG.bot_state(), lambda: self.qh_status_text(BG.bot_state())),
              (u"ربط جوال جديد (يظهر رمز على الشاشة)", BG.tg_new_pin),
              (u"الحسابات المربوطة (%d) - اضغط للإلغاء" % len(owners), self.bot_owners),
              (u"التنبيهات على تليجرام: %s" % self._on(cfg.get("tg_notify", True)),
               lambda: BG.toggle_flag("tg_notify", True, u"التنبيهات على تليجرام")),
              (u"آية الصباح على تليجرام: %s" % (cfg.get("tg_ayah_time") or u"إيقاف"), self.bot_ayah_time),
              (u"إرسال رسالة تجربة", lambda: (BG.tg_notify(u"✅ تجربة من Saad Quran Hub"),
                                              self.qh_status_text(u"أُرسلت" if owners else u"لا يوجد حساب مربوط بعد"))),
              (u"ورد الحفظ على الجوال: %s" % (cfg.get("tg_wird_time") or u"إيقاف"), self.bot_wird_time),
              (u"نسخة احتياطية أسبوعية على تليجرام: %s" % self._on(cfg.get("tg_backup", True)),
               lambda: BG.toggle_flag("tg_backup", True, u"النسخة الاحتياطية الأسبوعية")),
              (u"إرسال نسخة احتياطية الآن", lambda: [BG.tg_backup(o["id"]) for o in owners] if BG.bot else None)]
        if private_edition():
            it.append((u"تقارير الأعطال إليك: %s" % self._on(cfg.get("tg_errors", True)),
                       lambda: BG.toggle_flag("tg_errors", True, u"تقارير الأعطال")))
        it.append((u"التوكن: %s (اضغط للتغيير)" % tgbot.mask(BG.bot_token()), self.bot_token_edit))
        self._menu(u"بوت تليجرام", it)

    def bot_wird_time(self):
        opts = [(u"إيقاف", None)] + [(u"%02d:00" % h, u"%02d:00" % h) for h in (5, 6, 7, 8, 9, 10, 14, 17, 20, 21, 22)]

        def setit(c=None):
            if c:
                BG.cfg["tg_wird_time"] = c[1]
                BG.save()
                self.qh_status_text(u"ورد الحفظ على الجوال: %s" % (c[1] or u"إيقاف"))
        self._choice(u"وقت إرسال ورد الحفظ", opts, setit)

    def bot_toggle(self):
        BG.cfg["tg_bot"] = not BG.cfg.get("tg_bot", True)
        BG.save()
        if BG.cfg["tg_bot"]:
            BG.bot_start()
        else:
            BG.bot_stop()
        self.qh_status_text(u"بوت تليجرام: %s" % (u"يعمل" if BG.cfg["tg_bot"] else u"متوقف"))

    def bot_owners(self):
        owners = BG.tg_owners()
        if not owners:
            return self.qh_status_text(u"لا يوجد حساب مربوط - اختر «ربط جوال جديد» ثم أرسل الرمز للبوت")

        def cb(c=None):
            if c:
                BG.cfg["tg_owners"] = [o for o in owners if o["id"] != c[1]]
                BG.save()
                self.qh_status_text(u"أُلغي الربط")
        self._choice(u"إلغاء ربط حساب", [(u"%s  (%s)" % (o.get("name", u"?"), o["id"]), o["id"]) for o in owners], cb)

    def bot_ayah_time(self):
        opts = [(u"إيقاف", "")] + [(t, t) for t in ("05:30", "06:00", "07:00", "08:00", "09:00", "12:00", "20:00")]

        def cb(c=None):
            if c is not None:
                BG.cfg["tg_ayah_time"] = c[1]
                BG.save()
        self._choice(u"وقت آية الصباح على تليجرام", opts, cb)

    def bot_token_edit(self):
        def done(v=None):
            if v is not None and v.strip():
                BG.cfg["tg_token"] = v.strip()
                BG.save()
                BG.bot_stop()
                BG.bot_start()
                self.qh_status_text(u"تم حفظ التوكن وإعادة تشغيل البوت")
        self.session.openWithCallback(done, VirtualKeyBoard, title=u"توكن البوت من BotFather",
                                      text=BG.cfg.get("tg_token") or u"")

    # ================================================================== 1.7: player, disk folders, bouquet
    def open_player(self):
        self.session.open(QHPlayer)

    def mark_here(self):
        BG.mark_add()

    def ab_here(self):
        BG.ab_key()

    def speed_menu(self):
        if not Player.active:
            return self.qh_status_text(u"شغّل سورة أولاً")
        cur = BG.cur_speed()
        self._choice(u"سرعة التلاوة (بنفس صوت الشيخ)",
                     [((u"×%s%s" % (BG._sp(s), u"  ✓" if abs(s - cur) < 0.01 else u"")), s) for s in library.SPEEDS],
                     lambda c: c and BG.set_speed(c[1]))

    def marks_menu(self):
        ms = BG.cfg.get("marks", [])
        if not ms:
            return self.qh_status_text(u"لا توجد علامات - احفظها من المشغّل الكبير (الأزرق)")
        self._choice(u"علاماتي (اختر للتشغيل)", [(m["name"], m) for m in ms] + [(u"🗑 حذف كل العلامات", "clear")],
                     self._marks_done)

    def _marks_done(self, c=None):
        if not c:
            return
        if c[1] == "clear":
            BG.cfg["marks"] = []
            BG.save()
            return self.qh_status_text(u"حُذفت العلامات")
        BG.mark_play(c[1])

    def upnext_selected(self):
        pld = self.sel_payload()
        if not pld or not (pld.get("url") or pld.get("resolve")):
            return self.qh_status_text(u"حدّد سورة أو إذاعة أولاً")
        BG.upnext_add(pld)

    # -- folders on the disk as sources
    def menu_disk(self):
        srcs = BG.cfg.get("disk_srcs", [])
        it = [(u"➕ إضافة مجلد من HDD / الفلاشة ...", lambda: self.disk_browse(u"/media"))]
        for d in srcs:
            ok_ = os.path.isdir(d["path"])
            it.append((u"🗑 إزالة: %s  (%s)%s" % (d["name"], d["path"], u"" if ok_ else u"  - غير متصل"),
                       (lambda x=d: self.disk_remove(x))))
        self._menu(u"مصادر من القرص (ملفات القراء MP3 / FLAC)", it)

    def disk_browse(self, path):
        opts = [(u"✔ اختر هذا المجلد: %s" % path, ("pick", path))]
        if path not in ("/", "/media"):
            opts.append((u"⬆ رجوع", ("go", os.path.dirname(path.rstrip("/")) or "/")))
        opts += [(lab, ("go", p_)) for lab, p_ in library.browse(path)]

        def cb(c=None):
            if not c:
                return
            kind, p_ = c[1]
            if kind == "go":
                return self.disk_browse(p_)
            self.disk_name(p_)
        self._choice(u"اختر المجلد الذي فيه ملفات القراء", opts, cb)

    def disk_name(self, path):
        def got(name=None):
            if name is None:
                return
            name = name.strip() or os.path.basename(path.rstrip("/")) or path
            srcs = [d for d in BG.cfg.get("disk_srcs", []) if d["path"] != path]
            srcs.append({"name": name, "path": path})
            BG.cfg["disk_srcs"] = srcs
            BG.save()
            sync_tg_sections(BG.cfg)
            self.build_sections(self.qh_extra_sec)
            try:
                n = len(library.disk_reciters(path))
            except Exception:
                n = 0
            self.qh_status_text(u"أُضيف المصدر «%s» (%d قارئ) - تجده في العمود الأيمن" % (name, n))
        self.session.openWithCallback(got, VirtualKeyBoard, title=u"اسم المصدر",
                                      text=u"مكتبة " + (os.path.basename(path.rstrip("/")) or u"القرص"))

    def disk_remove(self, d):
        BG.cfg["disk_srcs"] = [x for x in BG.cfg.get("disk_srcs", []) if x["path"] != d["path"]]
        BG.save()
        self.build_sections(self.qh_extra_sec)
        self.qh_status_text(u"أُزيل المصدر (الملفات نفسها لم تُمس)")

    # -- favourites -> bouquet
    def menu_fav_bouquet(self):
        inst = studio.bouquet_installed(bq_file=studio.FAV_BQ_FILE)
        it = [(u"إنشاء / تحديث باقة «القرآن الكريم - المفضلة» في قائمة القنوات", self.fav_bouquet_make)]
        if inst:
            it.append((u"إزالة الباقة من قائمة القنوات", self.fav_bouquet_remove))
        self._menu(u"باقة المفضلة", it)

    def fav_bouquet_make(self):
        if not BG.cfg.get("fav"):
            return self.qh_status_text(u"المفضلة فارغة - اضغط 3 على قارئ أو إذاعة لإضافته")
        self.qh_status_text(u"جاري تجهيز الباقة من المفضلة ...")

        def done(res):
            if isinstance(res, Exception):
                qlog("fav bouquet: %r" % (res,))
                return self.qh_status_text(u"تعذّر إنشاء الباقة: %s" % res)
            n, unstable = res
            _reload_bouquets()
            msg = u"تمت إضافة %d قناة في باقة «القرآن الكريم - المفضلة» (قائمة القنوات > راديو)." % n
            if unstable:
                msg += u"\nبدون رابط ثابت (لم تُضف): %s" % u"، ".join(unstable[:6])
            _studio_info(self.session, msg)
        BG.fav_bouquet(done)

    def fav_bouquet_remove(self):
        try:
            studio.remove_bouquet(bq_file=studio.FAV_BQ_FILE)
            _reload_bouquets()
            self.qh_status_text(u"أُزيلت باقة المفضلة")
        except Exception as e:
            self.qh_status_text(u"تعذّرت الإزالة: %s" % e)

    # -- downloads
    def menu_downloads(self):
        self._menu(u"التنزيل والمحفوظات", [
            (u"البحث عن قارئ وتنزيله بأي صيغة ...", self.reciter_search),
            (u"مكتبتي (تشغيل • تحويل الصيغة • نسخ للفلاشة) ...", self.menu_mylib),
            (u"صيغة التنزيل: %s" % data.FORMAT_LABEL.get(BG.dl_format(), u""), self.pick_dl_format),
            (u"تنزيل المقطع الحالي إلى HDD", self.dl_current),
            (u"تنزيل المحدّد", self.dl_selected),
            (u"تنزيل المصحف كاملاً لهذا القارئ (يكمل من حيث توقف)", self.dl_all),
            (u"إيقاف التنزيلات", BG.dl.cancel),
            (u"تنقية صوت ملف محفوظ (إزالة التشويش وتوحيد الصوت) ...", self.clean_pick),
            (u"فتح المحفوظات", lambda: self.goto_section("local"))])

    def clean_pick(self):
        if not data.which("ffmpeg"):
            return self.qh_status_text(u"يحتاج ffmpeg (ثبّته من مدير الإضافات ثم أعد المحاولة)")
        files = extras.local_files()[:200]
        if not files:
            return self.qh_status_text(u"لا توجد ملفات محفوظة")
        self._choice(u"اختر الملف لتنقية صوته", [(n, pth) for n, pth in files],
                     lambda c: c and BG.clean_audio(c[1]))

    def dl_current(self):
        item = self.cur_item()
        if not item or item["live"]:
            return self.qh_status_text(u"لا يوجد مقطع (غير مباشر) قيد التشغيل لتنزيله")
        BG.download_payloads([item])

    def dl_selected(self):
        pld = self.sel_payload()
        if pld is None or pld.get("live"):
            return self.qh_status_text(u"حدّد سورة أو مقطعاً (الإذاعات المباشرة لا تُنزَّل)")
        BG.download_payloads([pld])

    def dl_all(self):
        col = self.qh_focus
        rows = [x for _, x in self.qh_view[col] if x and (x.get("url") or x.get("resolve")) and not x.get("live")] \
            if col else []
        if not rows:
            return self.qh_status_text(u"لا توجد عناصر قابلة للتنزيل هنا")
        if len(rows) > 6:
            return self._choice(u"تنزيل %d ملف؟ (قد يستغرق وقتاً ومساحة)" % len(rows),
                                [(u"نعم، ابدأ", True), (u"إلغاء", False)],
                                lambda c: c and c[1] and BG.download_payloads(rows))
        BG.download_payloads(rows)

    # -- schedules and prayer times
    def menu_time(self):
        cfg = BG.cfg
        city = cfg.get("prayer_city")
        mode = {"off": u"إيقاف", "notify": u"تنبيه فقط", "pause": u"تنبيه + إيقاف التلاوة مؤقتاً",
                "adhan": u"أذان بصوته ثم متابعة التلاوة"}.get(cfg.get("prayer_mode", "notify"))
        self._menu(u"الجدولة ومواقيت الصلاة", [
            (u"التذكيرات والمواسم (الورد • الكهف • الملك • رمضان) ...", lambda: studio_reminders(self.session)),
            (u"جدولة تشغيل جديدة ...", self.sched_wizard),
            (u"جداولي (%d) - اضغط للحذف" % len(cfg.get("sched", [])), self.sched_list),
            (u"مدينة الصلاة: %s" % (city or u"غير محددة"), self.prayer_city_pick),
            (u"نمط تنبيه الأذان: %s" % mode, self.prayer_mode_pick),
            (u"صوت الأذان: %s" % self.adhan_label(), self.adhan_sound_pick),
            (u"تجربة الأذان الآن", lambda: BG.adhan_start(u"تجربة")),
            (u"عرض مواقيت اليوم", self.prayer_show)])

    def prayer_city_pick(self):
        self._choice(u"اختر المدينة", [(c[0], c[0]) for c in extras.CITIES], self._city_set)

    def _city_set(self, c=None):
        if c:
            BG.cfg["prayer_city"] = c[1]
            BG.save()
            BG.ensure_timer()
            self.qh_status_text(u"مدينة الصلاة: %s" % c[1])

    def prayer_mode_pick(self):
        self._choice(u"عند دخول وقت الصلاة", [
            (u"لا شيء", "off"), (u"تنبيه على الشاشة فقط", "notify"),
            (u"تنبيه + إيقاف التلاوة 10 دقائق ثم الاستئناف", "pause"),
            (u"تشغيل الأذان بصوته ثم متابعة التلاوة تلقائياً", "adhan")], self._mode_set)

    def adhan_label(self):
        sel = BG.cfg.get("adhan_sound", "online:0")
        if sel == "off":
            return u"بدون صوت"
        if sel.startswith("file:"):
            return os.path.basename(sel[5:])
        try:
            return extras.ADHAN_URLS[int(sel.split(":")[1]) % len(extras.ADHAN_URLS)][0]
        except Exception:
            return extras.ADHAN_URLS[0][0]

    def adhan_sound_pick(self):
        opts = [(t, "online:%d" % i) for i, (t, _u) in enumerate(extras.ADHAN_URLS)]
        for f in extras.adhan_user_files():
            opts.append((u"ملفك: " + os.path.basename(f), "file:" + f))
        opts.append((u"بدون صوت (تنبيه فقط)", "off"))

        def done(c=None):
            if c:
                BG.cfg["adhan_sound"] = c[1]
                BG.cfg["prayer_mode"] = "adhan" if c[1] != "off" else BG.cfg.get("prayer_mode", "notify")
                BG.adhan_pf = False
                BG.save()
                self.qh_status_text(u"صوت الأذان: %s  (ضع ملفاتك في مجلد adhan على الـUSB/HDD)" % self.adhan_label())
        self._choice(u"صوت الأذان", opts, done)

    def _mode_set(self, c=None):
        if c:
            BG.cfg["prayer_mode"] = c[1]
            BG.save()
            BG.ensure_timer()
            self.qh_status_text(u"تم ضبط تنبيه الأذان")

    def prayer_show(self):
        text = BG.prayer_table()
        try:
            from Screens.MessageBox import MessageBox
            self.session.open(MessageBox, text, MessageBox.TYPE_INFO)
        except Exception:
            self.qh_status_text(text.replace(u"\n", u" | "))

    def sched_wizard(self):
        opts = []
        item = self.cur_item()
        if item:
            opts.append((u"المقطع الحالي: %s" % item["title"][:40], ("cur", item)))
        for n in sorted(BG.cfg.get("pls", {})):
            opts.append((u"قائمة: %s" % n, ("pl", n)))
        if not opts:
            return self.qh_status_text(u"شغّل مقطعاً أو إذاعة أو أنشئ قائمة أولاً ثم أعد المحاولة")
        self._choice(u"ما الهدف؟", opts, self._sw_target)

    def _sw_target(self, c=None):
        if not c:
            return
        tgt = c[1]
        if tgt[0] == "cur":
            self._choice(u"ماذا تفعل؟", [(u"تشغيل في الوقت المحدد", "play"),
                                         (u"تسجيل في الخلفية (على HDD/USB)", "rec")],
                         lambda k: k and self._sw_hours({"tgt": tgt, "kind": k[1]}))
        else:
            self._sw_hours({"tgt": tgt, "kind": "play"})

    def _sw_hours(self, st):
        self._choice(u"الساعة", [(u"%02d:__" % h, h) for h in range(24)],
                     lambda h: h and self._sw_mins(dict(st, h=h[1])))

    def _sw_mins(self, st):
        self._choice(u"الدقيقة", [(u"%02d:%02d" % (st["h"], m), m) for m in range(0, 60, 5)],
                     lambda m: m and self._sw_days(dict(st, m=m[1])))

    def _sw_days(self, st):
        self._choice(u"الأيام", [(l, d) for l, d in extras.DAY_SETS],
                     lambda d: d and self._sw_after_days(dict(st, days=d[1])))

    def _sw_after_days(self, st):
        if st["kind"] == "rec":
            self._choice(u"مدة التسجيل", [(u"%d دقيقة" % m, m) for m in (15, 30, 45, 60, 90, 120, 180)],
                         lambda d: d and self._sw_done(dict(st, dur=d[1])))
        else:
            self._sw_done(st)

    def _sw_done(self, st):
        hm_ = u"%02d:%02d" % (st["h"], st["m"])
        tgt = st["tgt"]
        if tgt[0] == "pl":
            s = BG.sched_add(hm_, st["days"], u"قائمة " + tgt[1], pl=tgt[1])
        else:
            it = tgt[1]
            s = BG.sched_add(hm_, st["days"], it["title"], url=it["url"], live=it["live"],
                             rec=(st["kind"] == "rec"), dur=st.get("dur", 60))
        self.qh_status_text(u"تمت الجدولة: " + extras.sched_label(s))

    def sched_list(self):
        rows = BG.cfg.get("sched", [])
        if not rows:
            return self.qh_status_text(u"لا توجد جداول")
        self._choice(u"اختر جدولاً لحذفه", [(extras.sched_label(s), s["id"]) for s in rows],
                     lambda c: c and (BG.sched_del(c[1]), self.qh_status_text(u"حُذف الجدول")))

    # -- phone remote and backup
    def menu_phone(self):
        on = BG.remote is not None
        it = [(u"التحكم من الجوال: %s" % self._on(on), lambda: BG.remote_enable(not on))]
        if on:
            it.append((u"العنوان والرمز: %s" % BG.remote_info(), lambda: self.qh_status_text(BG.remote_info())))
            it.append((u"رمز دخول جديد", self.new_pin))
        self._menu(u"التحكم من الجوال (افتح العنوان من متصفح الجوال على نفس الشبكة)", it)

    def new_pin(self):
        BG.cfg["remote_pin"] = ""
        BG.remote_enable(False, quiet=True)
        BG.remote_enable(True)

    def menu_backup(self):
        self._menu(u"النسخ الاحتياطي", [(u"حفظ الإعدادات والقوائم والمفضلة على HDD/USB", BG.backup_now),
                                        (u"استعادة آخر نسخة", BG.restore_now),
                                        (u"نسخة تلقائية كل أسبوع: %s" % self._on(BG.cfg.get("auto_backup", True)),
                                         lambda: BG.toggle_flag("auto_backup", True, u"النسخة التلقائية الأسبوعية"))])

    def menu_update(self):
        if not private_edition():
            gh = BG.cfg.get("gh_latest") or {}
            if gh.get("version") and vtuple(gh["version"]) > vtuple(PLUGIN_VERSION):
                it0 = [(u"⬆ تحديث من GitHub إلى %s - تنزيل وتثبيت" % gh["version"], self.update_from_github)]
            else:
                it0 = [(u"فحص GitHub الآن عن تحديث", lambda: BG.gh_check(manual=True))]
            it0.append((u"فحص التحديثات تلقائياً كل يوم: %s" % self._on(BG.cfg.get("gh_update", True)),
                        lambda: BG.toggle_flag("gh_update", True, u"فحص التحديثات من GitHub")))
        else:
            it0 = [(u"(نسختك الخاصة تُحدَّث بملف ipk منفصل، وليس من GitHub)", lambda: None)]
        found = find_update_ipks()
        it = [(u"تثبيت %s  (%s)" % (os.path.basename(pth), ver), (lambda q=pth: self.install_ipk(q)))
              for ver, pth in found]
        if not found:
            it.append((u"لم أجد ملف ipk أحدث في /tmp أو الفلاشة أو القرص", lambda: None))
        url = BG.cfg.get("update_url") or u""
        it.append((u"رابط التحديث: %s" % (url or u"غير محدد"), self.set_update_url))
        if url:
            it.append((u"تنزيل التحديث من الرابط وتثبيته", self.update_from_url))
        if not private_edition():
            it.append((u"إضافة مصدر التحديث الرسمي (feed) إلى الجهاز", BG.feed_add))
        it.append((u"ما الجديد في هذا الإصدار", self.show_whats_new))
        it.append((u"الرجوع لإصدار سابق ...", self.menu_rollback))
        it.append((u"الإصدار الحالي: %s" % PLUGIN_VERSION, lambda: None))
        self._menu(u"تحديث البلاجين", it0 + it)

    def update_from_github(self):
        gh = BG.cfg.get("gh_latest") or {}
        if not gh.get("ipk"):
            return BG.gh_check(manual=True)
        BG.cfg["update_url"] = gh["ipk"]
        BG.save()
        self.qh_expect_sha = gh.get("sha256") or None
        self.update_from_url()

    def set_update_url(self):
        def done(v=None):
            if v is not None:
                BG.cfg["update_url"] = v.strip()
                BG.save()
        self.session.openWithCallback(done, VirtualKeyBoard, title=u"رابط ملف ipk المباشر",
                                      text=BG.cfg.get("update_url") or u"https://")

    def update_from_url(self):
        url = BG.cfg.get("update_url")
        dst = data.tmp_path("saadquranhub_update.ipk")

        def job():
            raw = data.http_get(url, timeout=60)
            if not raw or len(raw) < 1000 or raw[:7] != b"!<arch>":
                raise IOError(u"الملف ليس حزمة ipk")
            with open(dst, "wb") as f:
                f.write(raw)
            return dst

        def done(res):
            if isinstance(res, Exception):
                return self.qh_status_text(u"فشل تنزيل التحديث: %s" % res)
            self.install_ipk(res)
        self.qh_status_text(u"جاري تنزيل التحديث ...")
        Runner().run(job, done, done)

    def install_ipk(self, path):
        sha, self.qh_expect_sha = getattr(self, "qh_expect_sha", None), None
        try:
            ver = safeupdate.verify_ipk(path, sha)
        except Exception as e:
            return self.qh_status_text(u"لم أثبّت التحديث: %s" % e)
        try:
            if safeupdate.snapshot(PLUGIN_VERSION):        # the running version stays on the disk
                safeupdate.mark_pending(ver, PLUGIN_VERSION)
        except Exception as e:
            qlog("snapshot: %r" % (e,))
        try:
            from Screens.Console import Console
            self.session.openWithCallback(self.update_done, Console, title=u"تحديث Saad Quran Hub",
                                          cmdlist=["opkg install --force-reinstall '%s'" % path])
        except Exception as e:
            qlog("update: %s" % e)
            os.system("opkg install --force-reinstall '%s' >/tmp/sqh_update.log 2>&1" % path)
            self.update_done()

    def update_done(self, *a):
        try:
            from Screens.MessageBox import MessageBox
            self.session.openWithCallback(self.update_restart, MessageBox,
                                          u"تم التثبيت. إعادة تشغيل الواجهة الآن ليعمل الإصدار الجديد؟",
                                          MessageBox.TYPE_YESNO)
        except Exception:
            pass

    def update_restart(self, yes=None):
        if yes:
            try:
                from Screens.Standby import TryQuitMainloop
                self.session.open(TryQuitMainloop, 3)
            except Exception as e:
                qlog("restart: %s" % e)

    # -- reader
    def cur_surah(self):
        if Player.active and 0 <= BG.pi < len(BG.pl):
            n = BG.pl[BG.pi].get("n")
            if n:
                return n
        n = extras.surah_of_title(Player.cur_title) if Player.active else None
        if n:
            return n
        pld = self.sel_payload()
        if pld:
            return pld.get("n") or extras.surah_of_title(pld.get("title", u""))
        return None

    def menu_reader(self):
        n = self.cur_surah()
        it = []
        rp = BG.cfg.get("reader_pos") or {}
        if rp.get("n"):
            it.append((u"تابع القراءة: سورة %s" % data.surah_name(rp["n"]),
                       lambda: self.session.open(QHReader, rp["n"], rp.get("mode", "mushaf"), rp.get("pg", 0), rp.get("taf"))))
        if n:
            nm = data.surah_name(n)
            tk = BG.cfg.get("reader_tafsir", "muyassar")
            it += [(u"المصحف المقروء - سورة %s" % nm, lambda: self.open_reader(n, "mushaf")),
                   (u"نص سورة %s" % nm, lambda: self.open_reader(n, "text")),
                   (u"تفسير سورة %s (%s)" % (nm, extras.TAFSIR_BY_KEY.get(tk, extras.TAFSIRS[0])[1]),
                    lambda: self.open_reader(n, "tafsir")),
                   (u"ترجمة سورة %s (Saheeh International)" % nm, lambda: self.open_reader(n, "translation"))]
        it += [(u"المصحف بالصفحات (604 صفحة مثل المطبوع)", lambda: self.session.open(
                   QHMushaf, studio.page_of(n, 1) if n else BG.cfg.get("mushaf_page", 1))),
               (u"وضع التلاوة السينمائي", lambda: self.session.open(QHCinema)),
               (u"بحث في نص القرآن ...", lambda: studio_search(self.session)),
               (u"اختيار سورة أخرى ...", self.reader_pick),
               (u"الأذكار والأدعية (حصن المسلم) ...", lambda: studio_adhkar_menu(self.session)),
               (u"أسماء الله الحسنى", lambda: self.session.open(
                   QHText, u"أسماء الله الحسنى", [u"  •  ".join(studio.names_blocks())], u"", True)),
               (u"اختيار كتاب التفسير ...", self.tafsir_pick),
               (u"تنزيل تفسير للقراءة بدون إنترنت ...", self.tafsir_dl_pick)]
        self._menu(u"القراءة والتفسير", it)

    def tafsir_pick(self):
        opts = [((u"[على الجهاز] " if extras.tafsir_available(k) else u"[يُنزَّل] ") + t, k) for k, t, _s, _a, _q, _b in extras.TAFSIRS]

        def done(c=None):
            if c:
                BG.cfg["reader_tafsir"] = c[1]
                BG.save()
                self.qh_status_text(u"التفسير المختار: %s" % extras.TAFSIR_BY_KEY[c[1]][1])
        self._choice(u"كتاب التفسير", opts, done)

    def tafsir_dl_pick(self):
        opts = [(t, k) for k, t, _s, _a, _q, _b in extras.TAFSIRS if not extras.tafsir_available(k)]
        if not opts:
            return self.qh_status_text(u"كل التفاسير موجودة على الجهاز")
        self._choice(u"تنزيل تفسير كامل (يحتاج HDD/USB)", opts, lambda c: c and BG.tafsir_download(c[1]))

    def open_now(self):
        self.session.open(QHNow)

    def open_home_screen(self):
        self.session.open(QHHome)

    def open_diag(self):
        self.session.open(QHDiag)

    def open_reader_now(self):
        n = self.cur_surah()
        if n:
            self.open_reader(n, "mushaf")
        else:
            self.reader_pick()

    def reader_pick(self):
        self._choice(u"اختر السورة", [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)],
                     lambda c: c and self.open_reader(c[1], "mushaf"))

    def open_reader(self, n, mode):
        self.session.open(QHReader, n, mode)

    def show_diag(self):
        text = BG.diag_text()
        try:
            from Screens.MessageBox import MessageBox
            self.session.open(MessageBox, text, MessageBox.TYPE_INFO)
        except Exception:
            self.qh_status_text(text.replace(u"\n", u" | "))

    def key_tv(self):
        """Channels menu: change the channel (picture + Quran) or use a PiP picture."""
        return self.menu_tv()

    def key_tv_old(self):
        opts = [(u"تغيير القناة الرئيسية (الصورة + صوت القرآن)", "zap")]
        if BG.tv_last_ref() is not None:
            opts.append((u"صورة بنافذة PiP: آخر قناة", "pip_last"))
        opts.append((u"صورة بنافذة PiP: اختيار قناة", "pip_pick"))
        if BG.tv_want or BG.tv_on:
            opts.append((u"إعادة تشغيل الصورة", "retry"))
        opts.append((u"حجم صورة PiP: %s  (اضغط للتغيير)" % BG.tv_size_name(), "size"))
        if BG.tv_want or BG.tv_on:
            opts.append((u"إيقاف صورة PiP", "off"))
        opts.append((u"تجاهل فحص دعم PiP: %s" % self._on(BG.cfg.get("pip_force")), "force"))
        opts.append((u"تشخيص / سجل الأخطاء", "diag"))
        self._choice(u"القنوات والصورة (الصوت من القرآن فقط)", opts, self.tv_choice)

    def tv_choice(self, choice=None):
        if not choice:
            return
        what = choice[1]
        if what == "off":
            return BG.tv_stop()
        if what == "retry":
            BG.tv_autohide = True
            return BG.tv_retry()
        if what == "size":
            return BG.tv_cycle_size()
        if what == "force":
            return BG.tv_toggle_force()
        if what == "diag":
            return self.show_diag()
        if what == "pip_last":
            ref = BG.tv_last_ref()
            if ref is None:
                return self.qh_status_text(u"لا توجد قناة محفوظة - اختر من القائمة")
            return self.tv_go(ref)
        try:
            from Screens.ChannelSelection import SimpleChannelSelection
            cb = self.tv_zapped if what == "zap" else self.tv_picked
            self.session.openWithCallback(cb, SimpleChannelSelection, u"اختر قناة", True)
        except Exception as e:
            self.qh_status_text(u"تعذّر فتح قائمة القنوات: %s" % e)

    def tv_zapped(self, ref=None):
        if ref is not None:
            if Player.active and BG.tv_strategy() == "pip":
                BG.tv_autohide = True
            BG.zap(ref)

    def tv_picked(self, ref=None):
        if ref is not None:
            self.tv_go(ref)

    def tv_go(self, ref):
        BG.tv_autohide = True       # plugin hides itself as soon as the picture is up
        BG.tv_start(ref)

    def key_rewind(self):
        BG.seek(-30)

    def key_forward(self):
        BG.seek(30)

    def key_theme(self):
        BG.cfg["theme"] = (BG.theme_idx() + 1) % len(THEMES)
        BG.cfg["auto_theme"] = "off"
        BG.save()
        BG.hide_minibar()
        BG.mini = None                      # rebuilt with the new colours
        self.close("retheme")

    def key_fav(self):
        idx, entry = self.current(1)
        if entry is None or self.qh_focus == 0:
            return self.qh_status_text(u"اختر قارئاً أو إذاعة أولاً")
        label = self.qh_view[1][idx][0]
        fk = list(self.fav_key(label, entry))
        favs = BG.cfg.setdefault("fav", [])
        if fk in favs:
            favs.remove(fk)
            self.qh_status_text(u"أُزيل من المفضلة: %s" % label)
        else:
            favs.append(fk)
            self.qh_status_text(u"أُضيف إلى المفضلة ★: %s" % label)
        BG.save()
        if SECTIONS[self.qh_sec][0] == "fav":
            self.qh_cache.pop("fav", None)
            self.load_section()
        else:
            self.apply(1)
            try:
                self["qh_items"].moveToIndex(idx)
            except Exception:
                pass

    # -- playback ----------------------------------------------------------------
    def play_from(self, col, idx):
        view = self.qh_view[col]
        item = view[idx][1]
        pl = [x for _, x in view if x is not None and (x.get("url") or x.get("resolve"))]
        pi = 0
        for i, x in enumerate(pl):
            if x is item:
                pi = i
                break
        if not pl:
            return
        ctx = {}
        try:
            key = SECTIONS[self.qh_sec][0]
            if col == 2:
                i1, ent = self.current(1)
                if ent is not None:
                    lab = self.qh_view[1][i1][0]
                    k, l = tuple(ent["favkey"]) if ent.get("favkey") else (key, lab)
                    ctx = {"sec": k, "label": l}
        except Exception:
            ctx = {}
        BG.play_list(pl, pi, ctx)
        self.qh_labels()

    def next_track(self):
        BG.step(1)

    def prev_track(self):
        BG.step(-1)


# ================================================================== v2.0 screens
def _hex(c):
    return c if isinstance(c, str) else "#%06x" % c


class QHHome(Screen):
    """Home screen (v3): 4 x 3 grid of tiles, each with its own accent colour."""
    TW, TH = 288, 128
    GX, GY = 22, 16
    COLS, ROWS = 4, 3
    ACCENTS = ["#2fbf71", "#e0a82e", "#2f9fd8", "#8e6bd8", "#d8694f", "#3bb8b0",
               "#d85f8a", "#9ab53a", "#d89a3a", "#4f86d8", "#a98be0", "#6fb0b8"]

    def __init__(self, session):
        BG.attach(session)
        self.qh_theme = BG.theme_idx()
        th = THEMES[self.qh_theme]
        self.qh_th = th
        self.skin = self._skin(th)
        Screen.__init__(self, session)
        self.skinName = "QuranHubHome"
        self.qh_idx = 0
        self.qh_runner = Runner()
        self["hm_title"] = Label(PLUGIN_NAME)
        self["hm_clock"] = Label(u"")
        self["hm_now"] = Label(u"")
        self["hm_ayah"] = Label(u"")
        self["hm_hint"] = Label(u"OK فتح  •  1-9 و 0 مباشر  •  MENU الإعدادات  •  أحمر: التشغيل الآن  •  أخضر: تابع  •  أصفر: بحث  •  أزرق: تشخيص")
        self["hm_cursor"] = Label(u"")
        for i in range(self.COLS * self.ROWS):
            self["t%d" % i] = Label(u"")
            self["s%d" % i] = Label(u"")
        keys = {"ok": lambda: self.activate(self.qh_idx), "cancel": self.close,
                "left": lambda: self.move(1, 0), "right": lambda: self.move(-1, 0),
                "up": lambda: self.move(0, -1), "down": lambda: self.move(0, 1),
                "red": lambda: self.activate(0), "green": BG.resume_last,
                "yellow": lambda: self.open_hub(None, "gsearch"), "blue": self.open_diag,
                "mainMenu": lambda: self.open_hub(None, "menu"), "0": lambda: self.activate(9)}
        for k in range(1, 10):
            keys[str(k)] = (lambda i=k - 1: self.activate(i))
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions", "NumberActions", "InfobarMenuActions"], keys, -1)
        self.qh_timer, self._c = make_timer(self.refresh)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    # tile order = RTL grid: index 0 is top-right
    @classmethod
    def pos(cls, i):
        r, c = divmod(i, cls.COLS)
        x = 1280 - 30 - cls.TW - c * (cls.TW + cls.GX)
        y = 100 + r * (cls.TH + cls.GY)
        return x, y

    @classmethod
    def _skin(cls, th):
        glass = th["bg"] == "transparent"
        bgc = "#e6000000" if glass else th["bg"]
        card = "#c0111820" if glass else th["panel"]
        out = [u'<screen name="QuranHubHome" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (
            p(1280), p(720), bgc)]
        out.append(u'<eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="0" />' % (p(1280), p(84), th["bar"]))
        out.append(u'<eLabel position="0,%d" size="%d,%d" backgroundColor="%s" zPosition="1" />' % (p(84), p(1280), p(3), th["line"]))
        out.append(u'<widget name="hm_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                   u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="2" />' % (
                       p(700), p(8), p(540), p(68), p(46), "#ffffff", th["bar"]))
        out.append(u'<widget name="hm_clock" position="%d,%d" size="%d,%d" font="Regular;%d" halign="left" valign="center" '
                   u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="2" />' % (
                       p(40), p(8), p(200), p(68), p(32), th["line"], th["bar"]))
        out.append(u'<widget name="hm_now" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                   u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="2" />' % (
                       p(250), p(8), p(450), p(68), p(21), th["text"], th["bar"]))
        out.append(u'<widget name="hm_cursor" position="0,0" size="%d,%d" backgroundColor="%s" zPosition="1" />' % (
            p(cls.TW + 10), p(cls.TH + 10), th["line"]))
        for i in range(cls.COLS * cls.ROWS):
            x, y = cls.pos(i)
            ac = cls.ACCENTS[i % len(cls.ACCENTS)]
            out.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="2" />' % (
                p(x), p(y), p(cls.TW), p(cls.TH), card))
            out.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="3" />' % (
                p(x + cls.TW - 7), p(y), p(7), p(cls.TH), ac))
            out.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="3" />' % (
                p(x), p(y + cls.TH - 3), p(cls.TW - 7), p(3), ac))
            out.append(u'<widget name="t%d" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                       u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="4" />' % (
                           i, p(x + 10), p(y + 8), p(cls.TW - 28), p(44), p(29), th["text"], card))
            out.append(u'<widget name="s%d" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="top" '
                       u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="4" />' % (
                           i, p(x + 10), p(y + 56), p(cls.TW - 28), p(66), p(18), th["dim"], card))
        yb = 100 + cls.ROWS * (cls.TH + cls.GY)
        out.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="2" />' % (
            p(30), p(yb + 2), p(1220), p(84), card))
        out.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="3" />' % (
            p(30), p(yb + 2), p(7), p(84), th["line"]))
        out.append(u'<widget name="hm_ayah" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                   u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="4" />' % (
                       p(54), p(yb + 4), p(1180), p(80), p(27), _hex(th["gold"]), card))
        out.append(u'<widget name="hm_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                   u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="4" />' % (
                       p(20), p(yb + 94), p(1240), p(30), p(17), th["dim"], bgc))
        out.append(u'</screen>')
        return u"".join(out)

    # -- content -------------------------------------------------------------------------------
    def tile_defs(self):
        playing = Player.active
        rp = BG.cfg.get("reader_pos") or {}
        r = BG.cfg.get("resume") or {}
        pt = BG.next_prayer_text()
        k = studio.khatma_state(BG.cfg)
        tvm = {"pip": u"صورة القناة كاملة + القرآن", "overlay": u"مشغّل ثانٍ فوق القناة",
               "off": u"الصوت يحل محل القناة"}[BG.tv_strategy()]
        return [
            (u"▶ يتم التشغيل الآن" if playing else u"▶ تابع الاستماع",
             (Player.cur_title or u"")[:44] if playing else ((r.get("title") or u"لا يوجد بعد")[:44])),
            (u"★ المفضلة", u"%d عنصراً" % len(BG.cfg.get("fav", []))),
            (u"الإذاعات", u"إذاعات القرآن على الهواء مباشرة"),
            (u"القراء والمكتبة", u"كل القراء من المواقع الستة"),
            (u"المصحف المقروء", (u"تابع القراءة: سورة %s" % data.surah_name(rp["n"])) if rp.get("n") else u"اقرأ السور بخط كبير"),
            (u"التفاسير", u"الميسر • السعدي • ابن كثير • الطبري ..."),
            (u"استوديو الحفظ", u"كرّر الآية والمقطع بصوت القارئ"),
            (u"الختمة والورد", u"تقدّمك %d%% • الورد %d صفحة" % (int(k["pages"] * 100 / float(studio.PAGES)), studio.khatma_daily(k))),
            (u"الأذكار والأدعية", u"حصن المسلم • أسماء الله الحسنى"),
            (u"قناة + تلاوة", tvm),
            (u"مواقيت الصلاة", pt or u"اختر المدينة من الإعدادات"),
            (u"المزيد", u"بحث • إحصائيات • باقة إذاعات • تشخيص"),
        ]

    def start(self):
        BG.ensure_aotd()
        self.place_cursor()
        self.refresh()
        self.qh_timer.start(1000, False)

    def cleanup(self):
        self.qh_timer.stop()
        self.qh_runner.close()

    def refresh(self):
        if BG.theme_idx() != self.qh_theme:                     # day/night or prayer-time theme switch
            return self.close("retheme")
        vals = {}
        for i, (t, s) in enumerate(self.tile_defs()):
            vals["t%d" % i], vals["s%d" % i] = t, s
        vals["hm_clock"] = time.strftime("%H:%M")
        vals["hm_now"] = (u"♪ %s" % Player.cur_title)[:60] if Player.active else BG.next_prayer_text()
        a = BG.cfg.get("aotd") or {}
        vals["hm_ayah"] = (u"﴿ %s ﴾" % a["t"]) if a.get("t") else u"آية اليوم: جاري التحميل ..."
        last = getattr(self, "qh_last_vals", {})
        for k, v in vals.items():              # only touch labels that changed (cheap on small boxes)
            if last.get(k) != v:
                self[k].setText(v)
        self.qh_last_vals = vals

    def place_cursor(self):
        x, y = self.pos(self.qh_idx)
        try:
            self["hm_cursor"].instance.move(ePoint(p(x - 5), p(y - 5)))
        except Exception:
            pass

    def move(self, dc, dr):
        r, c = divmod(self.qh_idx, self.COLS)
        c = max(0, min(self.COLS - 1, c + dc))
        r = max(0, min(self.ROWS - 1, r + dr))
        self.qh_idx = r * self.COLS + c
        self.place_cursor()

    # -- actions -------------------------------------------------------------------------------
    def open_hub(self, sec=None, action=None):
        self.session.open(QuranHub, sec, action)

    def open_diag(self):
        self.session.open(QHDiag)

    def activate(self, i):
        self.qh_idx = i
        self.place_cursor()
        if i == 0:
            if Player.active:
                self.session.open(QHNow)
            else:
                BG.resume_last()
        elif i == 1:
            self.open_hub(0)
        elif i == 2:
            self.open_hub(2)
        elif i == 3:
            self.open_hub(1)
        elif i == 4:
            rp = BG.cfg.get("reader_pos") or {}
            if rp.get("n"):
                self.session.open(QHReader, rp["n"], rp.get("mode", "mushaf"), rp.get("pg", 0), rp.get("taf"))
            else:
                self.pick_surah("mushaf")
        elif i == 5:
            self.pick_surah("tafsir")
        elif i == 6:
            studio_hifz(self.session)
        elif i == 7:
            studio_khatma(self.session)
        elif i == 8:
            studio_adhkar_menu(self.session)
        elif i == 9:
            self.open_hub(None, "tv")
        elif i == 10:
            text = BG.prayer_table()
            try:
                from Screens.MessageBox import MessageBox
                self.session.open(MessageBox, text, MessageBox.TYPE_INFO)
            except Exception:
                pass
        elif i == 11:
            studio_more(self.session)

    def pick_surah(self, mode):
        try:
            from Screens.ChoiceBox import ChoiceBox
            n0 = 0
            if Player.active:
                n0 = extras.surah_of_title(Player.cur_title) or 0
            opts = [(u"%d. %s" % (i, data.surah_name(i)), i) for i in range(1, 115)]
            if n0:
                opts.insert(0, (u"سورة التلاوة الحالية: %s" % data.surah_name(n0), n0))
            self.session.openWithCallback(lambda c: c and self.session.open(QHReader, c[1], mode),
                                          ChoiceBox, title=u"اختر السورة", list=opts)
        except Exception as e:
            qlog("home pick: %s" % e)
            popup(u"تعذّر فتح قائمة السور: %s" % e, 8)


class QHNow(Screen):
    """Now Playing: big card with the reciter's picture, progress bar and a level animation."""
    BARS = 28

    def __init__(self, session):
        BG.attach(session)
        th = THEMES[BG.theme_idx()]
        self.skin = self._skin(th)
        Screen.__init__(self, session)
        self.skinName = "QuranHubNow"
        self.qh_runner = Runner()
        self.qh_title = None
        self.qh_img = None
        self.qh_tick = 0
        self["nw_reciter"] = Label(u"")
        self["nw_title"] = Label(u"")
        self["nw_info"] = Label(u"")
        self["nw_time"] = Label(u"")
        self["nw_status"] = Label(u"")
        self["nw_prayer"] = Label(u"")
        self["nw_letter"] = Label(u"")
        self["nw_fill"] = Label(u"")
        self["nw_pix"] = Pixmap()
        self["nw_hint"] = Label(u"◀◀ رجوع 30 ث  •  ▶▶ تقديم  •  OK إيقاف مؤقت  •  أحمر السابق  •  أخضر التالي  •  أصفر قراءة السورة  •  أزرق إيقاف")
        self["nw_ayah"] = Pixmap()
        self.qn_verse = None
        for i in range(self.BARS):
            self["nw_b%d" % i] = Label(u"")
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions", "InfobarMenuActions"],
            {"ok": BG.toggle_pause, "cancel": self.close, "mainMenu": self.close,
             "left": lambda: BG.seek(-30), "right": lambda: BG.seek(30),
             "up": lambda: BG.vol_change(5), "down": lambda: BG.vol_change(-5),
             "red": lambda: BG.step(-1), "green": lambda: BG.step(1),
             "yellow": self.read_surah, "blue": self.stop_and_close}, -1)
        self["qh_seek"] = ActionMap(
            ["InfobarSeekActions", "MediaPlayerSeekActions"],
            {"seekBack": lambda: BG.seek(-30), "seekFwd": lambda: BG.seek(30),
             "playpauseService": BG.toggle_pause, "pauseService": BG.toggle_pause,
             "unPauseService": BG.toggle_pause}, -1)
        self.qh_timer, self._c = make_timer(self.refresh)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    BX0, BW, BG_ = 70, 20, 8                      # bars: x0, width, gap

    @classmethod
    def _skin(cls, th):
        glass = th["bg"] == "transparent"
        bgc = "#e8000000" if glass else th["bg"]
        card = "#c0111820" if glass else th["panel"]
        o = [u'<screen name="QuranHubNow" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (
            p(1280), p(720), bgc)]
        o.append(u'<eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="0" />' % (p(1280), p(8), th["line"]))
        o.append(u'<widget name="nw_prayer" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="2" />' % (
                     p(40), p(18), p(1200), p(34), p(21), th["dim"], bgc))
        o.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="1" />' % (p(40), p(64), p(1200), p(540), card))
        # picture / letter badge (right side)
        o.append(u'<widget name="nw_letter" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" zPosition="2" />' % (p(900), p(100), p(300), p(300), p(150), "#ffffff", th["sel"]))
        o.append(u'<widget name="nw_pix" position="%d,%d" size="%d,%d" alphatest="on" scale="1" zPosition="3" />' % (
            p(900), p(100), p(300), p(300)))
        o.append(u'<widget name="nw_reciter" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />' % (
                     p(70), p(96), p(800), p(64), p(42), th["text"], card))
        o.append(u'<widget name="nw_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="top" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />' % (
                     p(70), p(166), p(800), p(100), p(32), _hex(th["gold"]), card))
        o.append(u'<widget name="nw_info" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />' % (
                     p(70), p(272), p(800), p(32), p(20), th["dim"], card))
        o.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="3" />' % (p(70), p(330), p(800), p(14), th["head"]))
        o.append(u'<widget name="nw_fill" position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="4" />' % (
            p(70), p(330), p(2), p(14), th["line"]))
        o.append(u'<widget name="nw_time" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="3" />' % (
                     p(70), p(350), p(800), p(36), p(24), th["text"], card))
        o.append(u'<widget name="nw_ayah" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="5" />' % (
            p(70), p(392), p(800), p(52)))
        for i in range(cls.BARS):
            x = cls.BX0 + i * (cls.BW + cls.BG_)
            o.append(u'<widget name="nw_b%d" position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="3" />' % (
                i, p(x), p(586), p(cls.BW), p(6), th["sel"] if i % 2 else th["line"]))
        o.append(u'<widget name="nw_status" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="2" />' % (
                     p(40), p(612), p(1200), p(34), p(21), th["text"], bgc))
        o.append(u'<widget name="nw_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="2" />' % (
                     p(20), p(660), p(1240), p(34), p(17), th["dim"], bgc))
        o.append(u'</screen>')
        return u"".join(o)

    def start(self):
        try:
            self["nw_pix"].instance.setScale(1)
        except Exception:
            pass
        self["nw_pix"].hide()
        self.refresh(True)
        self.qh_timer.start(300, False)

    def cleanup(self):
        self.qh_timer.stop()
        self.qh_runner.close()

    @staticmethod
    def split_title(title):
        title = title or u""
        if u" - " in title:
            a, b = title.split(u" - ", 1)
            return a.strip(), b.strip()
        return title.strip(), u""

    def refresh(self, force=False):
        self.qh_tick += 1
        title = Player.cur_title if Player.active else None
        if title != self.qh_title or force:
            self.qh_title = title
            rec, sub = self.split_title(title)
            self["nw_reciter"].setText(rec or u"لا يوجد تشغيل")
            self["nw_title"].setText(sub)
            self["nw_letter"].setText((rec or u"؟")[:1])
            self["nw_pix"].hide()
            self["nw_letter"].show()
            if rec and not self.qh_img == rec:
                self.qh_img = rec
                self.qh_runner.run(lambda r=rec: data.reciter_image(r), lambda r, k=rec: self.img_loaded(r, k),
                                   lambda e: None)
        if self.qh_tick % 3 == 1 or force:
            pct, txt = BG.progress()
            try:
                self["nw_fill"].instance.resize(eSize(max(2, int(p(800) * pct / 100.0)), p(14)))
            except Exception:
                pass
            self["nw_time"].setText(txt or (u"" if Player.active else u"—"))
            self["nw_status"].setText(BG.status or u"")
            self["nw_info"].setText(BG.info_line())
            self["nw_prayer"].setText(BG.next_prayer_text() or BG.idle_text())
            self.show_verse()
        self.animate(Player.active and not BG.is_paused())

    def show_verse(self):
        """The ayah being recited, drawn as a picture (one line, cut to the card width)."""
        try:
            cur = BG.verse_now() if img_text() else None
            if cur == self.qn_verse:
                return
            self.qn_verse = cur
            if not cur:
                self["nw_ayah"].hide()
                return
            n, a = cur
            verses = dict(extras.local_verses(n) or [])
            words = extras.sanitize(verses.get(a, u"")).split()
            h = p(52)
            px = int(h / 1.85)
            lim = p(800) - p(80)
            out = []
            for w_ in words:
                if qtext.line_width(u" ".join(out + [w_]), px) > lim:
                    out.append(u"…")
                    break
                out.append(w_)
            text = u" ".join(out) + u" (%s)" % extras.ar_num(a)
            pix, iw = text_pixmap(text, px, 0xf4ecd2, h, line_tajweed(text) if tajweed_on() else None)
            if pix is None:
                return
            self["nw_ayah"].instance.setPixmap(pix)
            self["nw_ayah"].instance.resize(eSize(iw, h))
            self["nw_ayah"].instance.move(ePoint(p(70) + max(0, p(800) - iw), p(392)))
            self["nw_ayah"].show()
        except Exception as e:
            qlog("now verse: %r" % (e,))

    def img_loaded(self, path, rec):
        if isinstance(path, Exception) or not path or rec != self.qh_img:
            return
        try:
            self["nw_pix"].instance.setPixmapFromFile(path)
            self["nw_pix"].show()
            self["nw_letter"].hide()
        except Exception as e:
            qlog("now image: %s" % e)

    qh_flat = False

    def animate(self, live):
        if not live and self.qh_flat:
            return
        self.qh_flat = not live
        t = self.qh_tick * 0.3
        for i in range(self.BARS):
            if live:
                h = 8 + int(130 * abs(math.sin(t * 2.3 + i * 0.55) * math.cos(t * 0.9 + i * 0.21)))
            else:
                h = 6
            try:
                w = self["nw_b%d" % i].instance
                w.resize(eSize(p(self.BW), p(h)))
                w.move(ePoint(p(self.BX0 + i * (self.BW + self.BG_)), p(592 - h)))
            except Exception:
                return

    def read_surah(self):
        n = extras.surah_of_title(Player.cur_title) if Player.active else None
        self.session.open(QHReader, n or 1, "mushaf")

    def stop_and_close(self):
        BG.stop_play()
        self.close()


class QHPlayer(Screen):
    """The big player: the reciter's picture large, the ayah being recited, a progress bar and every
    control on the remote (seek, jump to %, speed, A-B repeat, ayah repeat, bookmarks)."""
    HINT = (u"OK إيقاف/تشغيل • ◀▶ 10 ث • ▲▼ دقيقة • 1-9 قفز % • 0 تكرار A-B • أحمر/أخضر السابق/التالي • "
            u"أصفر السرعة • أزرق علامة • MENU المزيد")

    def __init__(self, session):
        BG.attach(session)
        th = THEMES[BG.theme_idx()]
        self.qp_th = th
        bg = "#06090d"
        o = [u'<screen name="QuranHubPlayer" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (
            p(1280), p(720), bg)]
        o.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" />' % (p(40), p(60), p(470), p(470), th["panel"]))
        o.append(u'<widget name="qp_letter" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="#ffffff" backgroundColor="%s" zPosition="2" />' % (p(55), p(75), p(440), p(440), p(220), th["sel"]))
        o.append(u'<widget name="qp_pix" position="%d,%d" size="%d,%d" alphatest="on" scale="1" zPosition="3" />' % (
            p(55), p(75), p(440), p(440)))
        o.append(u'<widget name="qp_rec" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                 u'foregroundColor="#ffffff" backgroundColor="%s" transparent="1" />' % (p(540), p(60), p(700), p(70), p(46), bg))
        o.append(u'<widget name="qp_sub" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" />' % (p(540), p(135), p(700), p(50), p(32), _hex(th["gold"]), bg))
        o.append(u'<widget name="qp_ayah" position="%d,%d" size="%d,%d" scrollbarMode="showNever" backgroundColor="%s" '
                 u'backgroundColorSelected="%s" transparent="1" />' % (p(540), p(200), p(700), p(240), bg, bg))
        o.append(u'<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" />' % (p(540), p(460), p(700), p(12), th["head"]))
        o.append(u'<widget name="qp_fill" position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="2" />' % (
            p(540), p(460), p(2), p(12), th["line"]))
        o.append(u'<widget name="qp_time" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="#ffffff" backgroundColor="%s" transparent="1" />' % (p(540), p(480), p(700), p(40), p(26), bg))
        o.append(u'<widget name="qp_state" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" />' % (p(40), p(560), p(1200), p(40), p(24), _hex(th["gold"]), bg))
        o.append(u'<widget name="qp_status" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" />' % (p(40), p(605), p(1200), p(34), p(20), th["dim"], bg))
        o.append(u'<widget name="qp_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" />' % (p(20), p(668), p(1240), p(34), p(16), th["dim"], bg))
        o.append(u'</screen>')
        self.skin = u"".join(o)
        Screen.__init__(self, session)
        self.skinName = "QuranHubPlayer"
        for n in ("qp_letter", "qp_rec", "qp_sub", "qp_time", "qp_state", "qp_status", "qp_fill"):
            self[n] = Label(u"")
        self["qp_hint"] = Label(self.HINT)
        self["qp_pix"] = Pixmap()
        lst = MenuList([], False, eListboxPythonMultiContent)
        lst.l.setFont(0, gFont("Regular", p(30)))
        lst.l.setItemHeight(p(60))
        self["qp_ayah"] = lst
        self.qp_title = None
        self.qp_img = None
        self.qp_verse = None
        self.qp_runner = Runner()
        acts = {"cancel": self.close, "ok": BG.toggle_pause,
                "left": lambda: self.seek(-10), "right": lambda: self.seek(10),
                "up": lambda: self.seek(60), "down": lambda: self.seek(-60),
                "red": lambda: BG.step(-1), "green": lambda: BG.step(1),
                "yellow": self.speed_menu, "blue": BG.mark_add, "mainMenu": self.menu, "0": BG.ab_key}
        for i in range(1, 10):
            acts[str(i)] = (lambda k=i: self.jump(k * 10))
        self["actions"] = ActionMap(["OkCancelActions", "DirectionActions", "ColorActions", "NumberActions",
                                     "InfobarMenuActions"], acts, -1)
        self.qp_timer, self._c = make_timer(self.refresh)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    def start(self):
        BG.hide_minibar()
        try:
            self["qp_pix"].instance.setScale(1)
        except Exception:
            pass
        self["qp_pix"].hide()
        self.refresh(True)
        self.qp_timer.start(500, False)

    def cleanup(self):
        self.qp_timer.stop()
        self.qp_runner.close()
        BG.show_minibar()

    def seek(self, s):
        BG.seek(s)

    def jump(self, pct):
        pp = BG.play_pos()
        if not pp or BG.cur_live:
            return BG.set_status(u"القفز يعمل مع السور (ليس البث المباشر)")
        BG.seek(pp[1] * pct / 100.0 - pp[0])

    def speed_menu(self):
        cur = BG.cur_speed()
        opts = [((u"×%s%s" % (BG._sp(s), u"  ✓" if abs(s - cur) < 0.01 else u"")) +
                 (u"  (عادية)" if s == 1.0 else u"  (أبطأ للحفظ)" if s < 1 else u"  (أسرع)"), s) for s in library.SPEEDS]
        self._choice(u"سرعة التلاوة (بنفس صوت الشيخ)", opts, lambda c: c and BG.set_speed(c[1]))

    def _choice(self, title, opts, cb):
        try:
            from Screens.ChoiceBox import ChoiceBox
            self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
        except Exception as e:
            qlog("player menu: %s" % e)

    def menu(self):
        it = [(u"السرعة ...", self.speed_menu),
              (u"تكرار الآية الحالية 3 مرات", lambda: BG.repeat_ayah(3)),
              (u"تكرار الآية الحالية 5 مرات", lambda: BG.repeat_ayah(5)),
              (u"تكرار الآية الحالية 10 مرات", lambda: BG.repeat_ayah(10)),
              (u"تكرار مقطع A-B (زر 0)", BG.ab_key),
              (u"إيقاف التكرار", BG.ab_clear),
              (u"🔖 حفظ علامة هنا (أزرق)", BG.mark_add),
              (u"🔖 علاماتي (%d) ..." % len(BG.cfg.get("marks", [])), self.marks),
              (u"وضع التلاوة السينمائي", lambda: self.session.open(QHCinema)),
              (u"مشاركة الآية (QR)", lambda: BG.verse_now() and open_share(self.session, *BG.verse_now())),
              (u"⏹ إيقاف التشغيل", lambda: (BG.stop_play(), self.close()))]
        self._choice(u"المشغّل", [(l, f) for l, f in it], lambda c: c and c[1]())

    def marks(self):
        ms = BG.cfg.get("marks", [])
        if not ms:
            return BG.set_status(u"لا توجد علامات - اضغط الأزرق أثناء التلاوة")
        self._choice(u"علاماتي", [(m["name"], m) for m in ms], lambda c: c and BG.mark_play(c[1]))

    def refresh(self, force=False):
        title = Player.cur_title if Player.active else None
        if title != self.qp_title or force:
            self.qp_title = title
            rec, sub = QHNow.split_title(title)
            self["qp_rec"].setText(rec or u"لا يوجد تشغيل")
            self["qp_sub"].setText(sub)
            self["qp_letter"].setText((rec or u"؟")[:1])
            base = (rec or u"").split(u"  ×")[0]
            if base and base != self.qp_img:
                self.qp_img = base
                self["qp_pix"].hide()
                self["qp_letter"].show()
                self.qp_runner.run(lambda r=base: data.reciter_image(r), lambda r, k=base: self.img_loaded(r, k),
                                   lambda e: None)
        pct, txt = BG.progress()
        try:
            self["qp_fill"].instance.resize(eSize(max(2, int(p(700) * pct / 100.0)), p(12)))
        except Exception:
            pass
        self["qp_time"].setText(txt or u"")
        st = []
        sp = BG.cur_speed()
        if abs(sp - 1.0) > 0.01 or abs(BG.speed_want - 1.0) > 0.01:
            st.append(u"السرعة ×%s" % BG._sp(sp if abs(sp - 1.0) > 0.01 else BG.speed_want))
        if BG.ab:
            st.append(u"🔁 تكرار %s ← %s%s" % (BG._mmss(int(BG.ab["a"])), BG._mmss(int(BG.ab["b"])),
                                               (u" (%d)" % (BG.ab["left"] + 1)) if BG.ab["left"] >= 0 else u""))
        if BG.is_paused():
            st.append(u"⏸ متوقف مؤقتاً")
        if BG.upnext:
            st.append(u"التالي: %d" % len(BG.upnext))
        self["qp_state"].setText(u"   •   ".join(st))
        self["qp_status"].setText(BG.status or u"")
        self.show_verse()

    def show_verse(self):
        try:
            cur = BG.verse_now() if img_text() else None
            if cur == self.qp_verse:
                return
            self.qp_verse = cur
            if not cur:
                return self["qp_ayah"].setList([])
            n, a = cur
            text = u"%s (%s)" % (extras.sanitize(dict(extras.local_verses(n) or []).get(a, u"")), extras.ar_num(a))
            w, h = p(700), p(60)
            px = int(h / 1.85)
            lines = extras.wrap_lines([text], 40, meas=(lambda s: qtext.line_width(s, px), w - p(10),
                                                        qtext.atlas(px)["space"]))[:4]
            rows = []
            for i, ln in enumerate(lines):
                cols = line_tajweed(ln, lines[i + 1] if i + 1 < len(lines) else u"") if tajweed_on() else None
                rows.append([None] + img_entry(ln, w, h, 0xf4ecd2, align="right", colors=cols))
            self["qp_ayah"].setList(rows)
            try:
                self["qp_ayah"].instance.setSelectionEnable(0)
            except Exception:
                pass
        except Exception as e:
            qlog("player verse: %r" % (e,))

    def img_loaded(self, path, rec):
        if isinstance(path, Exception) or not path or rec != self.qp_img:
            return
        try:
            self["qp_pix"].instance.setPixmapFromFile(path)
            self["qp_pix"].show()
            self["qp_letter"].hide()
        except Exception as e:
            qlog("player image: %s" % e)


class QHDiag(Screen):
    """Self-diagnostic: runs every check and shows OK / failed with the reason."""
    ROWS = 14

    def __init__(self, session):
        BG.attach(session)
        th = THEMES[BG.theme_idx()]
        self.qh_th = th
        self.qh_bgc = "#101418" if th["bg"] == "transparent" else th["bg"]
        self.skin = self._skin(th)
        Screen.__init__(self, session)
        self.skinName = "QuranHubDiag"
        self.qh_runner = Runner()
        self.qh_results = []
        self.qh_lines = []
        self.qh_pg = 0
        self.qh_done = False
        self.qh_seen = 0
        self["dg_title"] = Label(u"التشخيص الذاتي")
        self["dg_sum"] = Label(u"")
        self["dg_hint"] = Label(u"▲▼ تمرير  •  OK إعادة  •  أخضر حفظ التقرير  •  EXIT خروج   |   أخضر سليم  •  أصفر تنبيه  •  أحمر فشل")
        for i in range(self.ROWS):
            self["dg_r%d" % i] = Label(u"")
            self["dg_m%d" % i] = Label(u"")
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {"ok": self.rerun, "cancel": self.close, "up": lambda: self.page(-1), "down": lambda: self.page(1),
             "left": lambda: self.page(1), "right": lambda: self.page(-1),
             "red": self.close, "green": self.save}, -1)
        self.qh_timer, self._c = make_timer(self.poll)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    @classmethod
    def _skin(cls, th):
        bgc = "#f0101418" if th["bg"] == "transparent" else th["bg"]
        o = [u'<screen name="QuranHubDiag" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (
            p(1280), p(720), bgc)]
        o.append(u'<eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="0" />' % (p(1280), p(70), th["bar"]))
        o.append(u'<widget name="dg_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                 u'foregroundColor="#ffffff" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                     p(700), p(6), p(540), p(58), p(38), th["bar"]))
        o.append(u'<widget name="dg_sum" position="%d,%d" size="%d,%d" font="Regular;%d" halign="left" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                     p(40), p(6), p(640), p(58), p(24), th["line"], th["bar"]))
        for i in range(cls.ROWS):
            o.append(u'<widget name="dg_r%d" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" '
                     u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                         i, p(40), p(82 + i * 40), p(1166), p(38), p(22), th["text"], bgc))
            o.append(u'<widget name="dg_m%d" position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="1" />' % (
                i, p(1218), p(93 + i * 40), p(16), p(16), bgc))
        o.append(u'<widget name="dg_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" zPosition="1" />' % (
                     p(20), p(672), p(1240), p(36), p(19), th["dim"], bgc))
        o.append(u'</screen>')
        return u"".join(o)

    COL_OK, COL_BAD, COL_WARN, COL_HINT = "#58d68d", "#ff6b6b", "#f4c542", "#9aa5b1"

    def hooks(self):
        return {"enigma": BG.diag_enigma_checks}

    def start(self):
        self.rerun()
        self.qh_timer.start(500, False)

    def cleanup(self):
        self.qh_timer.stop()
        self.qh_runner.close()

    def rerun(self):
        self.qh_results, self.qh_done, self.qh_pg, self.qh_seen = [], False, 0, 0
        out = self.qh_results
        # the enigma checks need the GUI thread -> collect them first, run the network checks in a thread
        try:
            enigma_rows = BG.diag_enigma_checks()
        except Exception as e:
            enigma_rows = [(None, u"فحوصات الجهاز", u"%s" % e, u"")]
        self.qh_enigma = enigma_rows

        def job():
            return diag.run(None, progress=lambda r: out.append(r))
        self.qh_runner.run(job, self.finished, self.finished)
        self.render()

    def finished(self, res):
        if isinstance(res, Exception):
            self.qh_results.append((False, u"الفحص نفسه", u"%s" % res, u""))
        for r in self.qh_enigma:
            self.qh_results.append(r)
        self.qh_done = True
        BG.diag_rows = list(self.qh_results)
        self.render()

    def poll(self):
        if len(self.qh_results) != self.qh_seen:
            self.qh_seen = len(self.qh_results)
            self.render()

    def build_lines(self):
        lines = []
        for r in list(self.qh_results):
            state, title, detail, hint = r
            col = self.COL_OK if state is True else (self.COL_BAD if state is False else self.COL_WARN)
            word = u"" if state is True else (u"[فشل] " if state is False else u"[تنبيه] ")
            lines.append((u"%s%s :  %s" % (word, title, detail), col, col))
            if state is not True and hint:
                lines.append((u"← " + hint, self.COL_HINT, None))
        return lines

    def render(self):
        self.qh_lines = self.build_lines()
        ok, warn, bad = diag.summary(self.qh_results)
        self["dg_sum"].setText((u"ناجح %d  •  تحذير %d  •  فشل %d" % (ok, warn, bad)) +
                               (u"" if self.qh_done else u"   ...جاري الفحص"))
        self.show_page()

    def page(self, d):
        mx = max(0, (len(self.qh_lines) - 1) // self.ROWS)
        self.qh_pg = max(0, min(mx, self.qh_pg + d))
        self.show_page()

    def show_page(self):
        base = self.qh_pg * self.ROWS
        for i in range(self.ROWS):
            lab = self["dg_r%d" % i]
            mk = self["dg_m%d" % i]
            if base + i < len(self.qh_lines):
                text, col, mcol = self.qh_lines[base + i]
                lab.setText(text[:120])
                try:
                    lab.instance.setForegroundColor(parseColor(col))
                    mk.instance.setBackgroundColor(parseColor(mcol or self.qh_bgc))
                except Exception:
                    pass
            else:
                lab.setText(u"")
                try:
                    mk.instance.setBackgroundColor(parseColor(self.qh_bgc))
                except Exception:
                    pass

    def save(self):
        paths = diag.save_report(self.qh_results)
        BG.set_status((u"تم حفظ التقرير: " + u"  ".join(paths)) if paths else u"تعذّر حفظ التقرير", notify=True)
        self["dg_hint"].setText((u"حُفظ التقرير في: " + paths[0]) if paths else u"تعذّر حفظ التقرير")


def studio_more_full(session):
    studio_menu(session)


class QHSimple(Screen):
    """Simple mode (elderly): six big buttons, big letters, high contrast.  MENU opens the full plugin."""
    TILES = [("fav", u"▶  قارئي المفضل"), ("radio", u"📻  الإذاعة"), ("resume", u"⏯  تابع الاستماع"),
             ("mushaf", u"📖  المصحف"), ("adhkar", u"📿  الأذكار"), ("stop", u"⏹  إيقاف")]
    BG_, FG, SEL, TILE = "#000000", "#ffffff", "#f4c542", "#1c2733"

    def __init__(self, session):
        BG.attach(session)
        o = [u'<screen name="QuranHubSimple" position="0,0" size="%d,%d" flags="wfNoBorder" backgroundColor="%s">' % (
            p(1280), p(720), self.BG_)]
        o.append(u'<widget name="sm_title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" />' % (p(20), p(10), p(1240), p(70), p(44), self.SEL, self.BG_))
        for i in range(6):
            x = p(40 + (1 - i % 2) * 610)          # right-to-left: the first tile on the right
            y = p(100 + (i // 2) * 170)
            o.append(u'<widget name="sm_t%d" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                     u'foregroundColor="%s" backgroundColor="%s" />' % (i, x, y, p(590), p(150), p(52), self.FG, self.TILE))
        o.append(u'<widget name="sm_now" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="%s" backgroundColor="%s" transparent="1" />' % (p(20), p(612), p(1240), p(50), p(32), self.FG, self.BG_))
        o.append(u'<widget name="sm_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" '
                 u'foregroundColor="#9aa5b1" backgroundColor="%s" transparent="1" />' % (p(20), p(668), p(1240), p(40), p(24), self.BG_))
        o.append(u'</screen>')
        self.skin = u"".join(o)
        Screen.__init__(self, session)
        self.skinName = "QuranHubSimple"
        self["sm_title"] = Label(u"القرآن الكريم")
        for i, (_k, lab) in enumerate(self.TILES):
            self["sm_t%d" % i] = Label(i18n.T(lab))
        self["sm_now"] = Label(u"")
        self["sm_hint"] = Label(i18n.T(u"الأسهم للاختيار • OK للتشغيل • MENU القائمة الكاملة • EXIT خروج"))
        self.sm_i = 0
        self["actions"] = ActionMap(["OkCancelActions", "DirectionActions", "InfobarMenuActions"],
                                    {"cancel": self.close, "ok": self.press, "mainMenu": self.full,
                                     "left": lambda: self.move(1), "right": lambda: self.move(-1),
                                     "up": lambda: self.move(-2), "down": lambda: self.move(2)}, -1)
        self.sm_timer, self._c = make_timer(self.refresh)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(lambda: self.sm_timer.stop())

    def start(self):
        self.paint()
        self.refresh()
        self.sm_timer.start(2000, False)

    def paint(self):
        if parseColor is None:
            return
        for i in range(6):
            try:
                w = self["sm_t%d" % i].instance
                sel = i == self.sm_i
                w.setBackgroundColor(parseColor(self.SEL if sel else self.TILE))
                w.setForegroundColor(parseColor("#000000" if sel else self.FG))
            except Exception:
                pass

    def move(self, d):
        self.sm_i = (self.sm_i + d) % 6
        self.paint()

    def refresh(self):
        self["sm_now"].setText((u"▶ " + (Player.cur_title or u"")) if Player.active else u"")

    def full(self):
        open_hub(self.session)

    def _choice(self, title, opts, cb):
        try:
            from Screens.ChoiceBox import ChoiceBox
            self.session.openWithCallback(cb, ChoiceBox, title=title, list=opts)
        except Exception as e:
            qlog("simple: %s" % e)

    def press(self):
        k = self.TILES[self.sm_i][0]
        if k == "stop":
            return BG.stop_play()
        if k == "resume":
            return BG.resume_last()
        if k == "mushaf":
            return self.session.open(QHMushaf, BG.cfg.get("mushaf_page", 1))
        if k == "adhkar":
            return studio_adhkar_menu(self.session)
        if k == "radio":
            return self.pick_radio()
        self.pick_fav()

    def pick_radio(self):
        favs = [tuple(f) for f in BG.cfg.get("fav", []) if f and f[0] in ("mp3q_radios", "sq_radios")]

        def go(rows):
            if isinstance(rows, Exception) or not rows:
                return BG.set_status(u"تعذّر تحميل الإذاعات", notify=True)
            self._choice(u"اختر الإذاعة", [(l, x) for l, x in rows if x], lambda c: c and BG.play_list([c[1]], 0))
        Runner().run(fav_loader(favs) if favs else section_loader("mp3q_radios"), go, go)

    def pick_fav(self):
        favs = [tuple(f) for f in BG.cfg.get("fav", [])]
        if not favs:
            return BG.resume_last()

        def go(rows):
            if isinstance(rows, Exception) or not rows:
                return BG.resume_last()
            self._choice(u"قارئي المفضل", [(l, x) for l, x in rows if x], self.fav_chosen)
        Runner().run(fav_loader(favs), go, go)

    def fav_chosen(self, c=None):
        if not c:
            return
        entry = c[1]
        if not entry_has_subs(entry):
            return BG.play_list([entry], 0)

        def go(rows):
            pls = [(l, x) for l, x in (rows if not isinstance(rows, Exception) else []) if x and (x.get("url") or x.get("resolve"))]
            if not pls:
                return BG.set_status(u"تعذّر تحميل السور", notify=True)
            self._choice(u"اختر السورة", [(l, i) for i, (l, _x) in enumerate(pls)],
                         lambda k: k and BG.play_list([x for _l, x in pls], k[1]))
        Runner().run(lambda: subs_for(entry), go, go)


def open_hub(session):
    def again(result=None):
        if result == "retheme":
            open_hub(session)
    session.openWithCallback(again, QuranHub)


def open_start(session):
    """Home screen (default) or the classic three-column library."""
    BG.attach(session)
    if BG.cfg.get("simple_mode", False):
        return session.open(QHSimple)
    if not BG.cfg.get("home_screen", False):
        return open_hub(session)

    def again(result=None):
        if result == "retheme":
            open_start(session)
    session.openWithCallback(again, QHHome)


def main(session, **kwargs):
    open_start(session)


def stop_background(session, **kwargs):
    BG.attach(session)
    active = Player.active or BG.rec is not None
    BG.stop_all()
    try:
        from Screens.MessageBox import MessageBox
        session.open(MessageBox,
                     u"تم إيقاف تشغيل القرآن الكريم" if active else u"لا يوجد تشغيل في الخلفية",
                     MessageBox.TYPE_INFO, timeout=3)
    except Exception:
        pass


def find_update_ipks():
    """ipk files of this plugin newer than the running version: [(version, path)] newest first."""
    import glob
    out = []
    pats = ["/tmp/", "/media/*/", "/media/*/*/", "/media/hdd/"]
    seen = set()
    for d in pats:
        for pth in glob.glob(d + "enigma2-plugin-extensions-saadquranhub_*.ipk"):
            if pth in seen:
                continue
            seen.add(pth)
            ver = os.path.basename(pth).split("_")[1] if "_" in os.path.basename(pth) else "0"
            try:
                newer = [int(x) for x in ver.split(".")] > [int(x) for x in PLUGIN_VERSION.split(".")]
            except ValueError:
                newer = False
            if newer:
                out.append((ver, pth))
    return sorted(out, key=lambda v: [int(x) for x in v[0].split(".")], reverse=True)


class QHAyahCard(Screen):
    """A short ayah with its tafsir for a few seconds when the receiver starts (MENU > tools to switch off)."""

    def __init__(self, session):
        BG.attach(session)
        th = THEMES[BG.theme_idx()]
        self.skin = (u'<screen name="QuranHubAyahCard" position="%d,%d" size="%d,%d" flags="wfNoBorder" backgroundColor="#e0101418">'
                     u'<eLabel position="0,0" size="%d,%d" backgroundColor="%s" />'
                     u'<widget name="ac_top" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="%s" backgroundColor="#101418" transparent="1" />'
                     u'<widget name="ac_list" position="%d,%d" size="%d,%d" scrollbarMode="showNever" backgroundColor="#101418" backgroundColorSelected="#101418" transparent="1" />'
                     u'<widget name="ac_hint" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="#7d8894" backgroundColor="#101418" transparent="1" />'
                     u'</screen>') % (
            p(140), p(420), p(1000), p(270), p(1000), p(4), th["line"],
            p(20), p(12), p(960), p(36), p(22), th["gold"],
            p(20), p(52), p(960), p(180),
            p(20), p(236), p(960), p(28), p(16))
        Screen.__init__(self, session)
        self.skinName = "QuranHubAyahCard"
        self["ac_top"] = Label(u"")
        self["ac_hint"] = Label(u"OK استمع للسورة  •  EXIT إغلاق  •  الإيقاف من: القائمة > أدوات")
        lst = MenuList([], False, eListboxPythonMultiContent)
        lst.l.setFont(0, gFont("Regular", p(26)))
        lst.l.setItemHeight(p(45))
        self["ac_list"] = lst
        self.ac_key = None
        self["actions"] = ActionMap(["OkCancelActions"], {"cancel": self.close, "ok": self.listen}, -1)
        self.ac_timer, self._c = make_timer(self.close)
        self.onLayoutFinish.append(self.start)

    def start(self):
        try:
            key, text = extras.ayah_of_the_day()
            self.ac_key = key
            n, a = [int(x) for x in key.split(":")]
            self["ac_top"].setText(u"آية اليوم  •  سورة %s (%s)" % (data.surah_name(n), extras.ar_num(a)))
            w, h = p(960), p(45)
            meas = None
            if img_text():
                px = int(h / 1.85)
                meas = (lambda s: qtext.line_width(s, px), w - p(10), qtext.atlas(px)["space"])
            lines = extras.wrap_lines([extras.sanitize(text)], 70, meas=meas)[:3]
            taf = extras.local_tafsir("muyassar", n) or []
            body = extras.sanitize(taf[a - 1]) if a - 1 < len(taf) and taf[a - 1] != u"=" else u""
            tl = extras.wrap_lines([body], 90, meas=(lambda s: qtext.line_width(s, int(p(34) / 1.85)), w - p(10),
                                                         qtext.atlas(int(p(34) / 1.85))["space"]) if meas else None)[:1]
            rows = []
            for i, ln in enumerate(lines):
                cols = line_tajweed(ln, lines[i + 1] if i + 1 < len(lines) else u"") if tajweed_on() else None
                rows.append([None] + img_entry(ln, w, h, 0xf4ecd2, align="center", colors=cols))
            for ln in tl:
                rows.append([None] + img_entry(ln, w, p(34), 0xa9b4c0, align="center"))
            self["ac_list"].setList(rows)
            try:
                self["ac_list"].instance.setSelectionEnable(0)
            except Exception:
                pass
        except Exception as e:
            qlog("ayah card: %r" % (e,))
            return self.close()
        self.ac_timer.start(15000, True)

    def listen(self):
        try:
            n = int(self.ac_key.split(":")[0])
            self.close()
            BG.play_surah(n, u"")
        except Exception:
            self.close()


_BOOT = []


def boot_ayah():
    try:
        from Screens.Standby import inStandby
        if inStandby or not BG.cfg.get("boot_ayah", True) or Player.active or getattr(BG, "ui", None):
            return
        from Tools import Notifications
        Notifications.AddNotification(QHAyahCard)
    except Exception as e:
        qlog("boot ayah: %s" % e)


def autostart(reason, **kwargs):
    """Session start: schedules, prayer reminders and the phone remote work without opening the plugin."""
    if reason == 0 and kwargs.get("session") is not None:
        try:
            BG.attach(kwargs["session"])
            BG.ensure_timer()
        except Exception as e:
            qlog("autostart: %s" % e)
        try:
            if not _BOOT:
                tm, c = make_timer(boot_ayah)
                _BOOT.extend([tm, c])
                tm.start(40000, True)
        except Exception as e:
            qlog("boot timer: %s" % e)


def autostop(reason, **kwargs):
    """Restart / shutdown of the receiver: write the settings to the disk and the flash copy now."""
    if reason == 1:
        try:
            data.save_settings(BG.cfg, now=True)
        except Exception:
            pass


def Plugins(**kwargs):
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
        PluginDescriptor(where=PluginDescriptor.WHERE_AUTOSTART, fnc=autostop),
        PluginDescriptor(
            name=u"Saad Quran Hub - القرآن الكريم",
            description=u"Quran reciters and radios (mp3quran, quran.com, surahquran)",
            where=[PluginDescriptor.WHERE_PLUGINMENU,
                   PluginDescriptor.WHERE_EXTENSIONSMENU],
            icon="plugin.png",
            fnc=main),
        PluginDescriptor(
            name=u"Saad Quran Hub - إيقاف التشغيل الخلفي",
            description=u"Stop Saad Quran Hub background audio",
            where=[PluginDescriptor.WHERE_EXTENSIONSMENU],
            fnc=stop_background),
    ]
