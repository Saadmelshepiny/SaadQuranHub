# -*- coding: utf-8 -*-
"""Quran Hub extras - pure Python (no enigma2 imports) so it can be unit-tested.

* prayer times (offline astronomical calculation)
* adhkar / ayah of the day
* chapter text, tafsir and translation from api.quran.com
* downloads and the local archive
* backup / restore of the settings
* scheduling helpers
"""
from __future__ import print_function

import glob
import json
import math
import os
import re
import shutil
import threading
import time

from . import data

# ------------------------------------------------------------------ prayer times
# (name, latitude, longitude, method)   method: egypt | mwl | makkah | karachi | isna
CITIES = [
    (u"القاهرة", 30.0444, 31.2357, "egypt"),
    (u"الإسكندرية", 31.2001, 29.9187, "egypt"),
    (u"الجيزة", 30.0131, 31.2089, "egypt"),
    (u"أسوان", 24.0889, 32.8998, "egypt"),
    (u"مكة المكرمة", 21.3891, 39.8579, "makkah"),
    (u"المدينة المنورة", 24.5247, 39.5692, "makkah"),
    (u"الرياض", 24.7136, 46.6753, "makkah"),
    (u"جدة", 21.4858, 39.1925, "makkah"),
    (u"الدمام", 26.4207, 50.0888, "makkah"),
    (u"دبي", 25.2048, 55.2708, "mwl"),
    (u"أبوظبي", 24.4539, 54.3773, "mwl"),
    (u"الكويت", 29.3759, 47.9774, "mwl"),
    (u"الدوحة", 25.2854, 51.5310, "makkah"),
    (u"المنامة", 26.2285, 50.5860, "makkah"),
    (u"مسقط", 23.5880, 58.3829, "mwl"),
    (u"صنعاء", 15.3694, 44.1910, "makkah"),
    (u"عمّان", 31.9454, 35.9284, "egypt"),
    (u"القدس", 31.7683, 35.2137, "egypt"),
    (u"غزة", 31.5017, 34.4668, "egypt"),
    (u"بيروت", 33.8938, 35.5018, "egypt"),
    (u"دمشق", 33.5138, 36.2765, "egypt"),
    (u"بغداد", 33.3152, 44.3661, "mwl"),
    (u"الخرطوم", 15.5007, 32.5599, "egypt"),
    (u"طرابلس", 32.8872, 13.1913, "egypt"),
    (u"تونس", 36.8065, 10.1815, "mwl"),
    (u"الجزائر", 36.7538, 3.0588, "mwl"),
    (u"الرباط", 34.0209, -6.8416, "mwl"),
    (u"الدار البيضاء", 33.5731, -7.5898, "mwl"),
    (u"إسطنبول", 41.0082, 28.9784, "mwl"),
    (u"لندن", 51.5072, -0.1276, "mwl"),
]

METHODS = {
    "egypt": (19.5, 17.5, None),      # Egyptian General Authority of Survey
    "mwl": (18.0, 17.0, None),        # Muslim World League
    "makkah": (18.5, None, 90),       # Umm al-Qura (isha 90 min after maghrib)
    "karachi": (18.0, 18.0, None),
    "isna": (15.0, 15.0, None),
}

PRAYER_NAMES = [("fajr", u"الفجر"), ("dhuhr", u"الظهر"), ("asr", u"العصر"),
                ("maghrib", u"المغرب"), ("isha", u"العشاء")]


def _d2r(d):
    return d * math.pi / 180.0


def _r2d(r):
    return r * 180.0 / math.pi


def _fix(a, b):
    a = a - b * math.floor(a / b)
    return a + b if a < 0 else a


def _julian(y, m, d):
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100.0)
    b = 2 - a + math.floor(a / 4.0)
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def _sun(jd):
    d = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * d, 360)
    q = _fix(280.459 + 0.98564736 * d, 360)
    l = _fix(q + 1.915 * math.sin(_d2r(g)) + 0.020 * math.sin(_d2r(2 * g)), 360)
    e = 23.439 - 0.00000036 * d
    ra = _r2d(math.atan2(math.cos(_d2r(e)) * math.sin(_d2r(l)), math.cos(_d2r(l)))) / 15.0
    eqt = q / 15.0 - _fix(ra, 24)
    decl = _r2d(math.asin(math.sin(_d2r(e)) * math.sin(_d2r(l))))
    return decl, eqt


def prayer_times(year, month, day, lat, lon, tz, method="mwl"):
    """Return {'fajr':h, 'sunrise':h, 'dhuhr':h, 'asr':h, 'maghrib':h, 'isha':h} in local hours."""
    fa, ia, imin = METHODS.get(method, METHODS["mwl"])
    jd = _julian(year, month, day) - lon / (15 * 24.0)

    def mid(t):
        return _fix(12 - _sun(jd + t)[1], 24)

    def at(angle, t, ccw=False):
        decl = _sun(jd + t)[0]
        x = (-math.sin(_d2r(angle)) - math.sin(_d2r(decl)) * math.sin(_d2r(lat))) / \
            (math.cos(_d2r(decl)) * math.cos(_d2r(lat)))
        x = max(-1.0, min(1.0, x))
        z = _r2d(math.acos(x)) / 15.0
        return mid(t) + (-z if ccw else z)

    def asr(t, factor=1):
        decl = _sun(jd + t)[0]
        ang = -_r2d(math.atan(1.0 / (factor + math.tan(_d2r(abs(lat - decl))))))
        return at(ang, t)

    t = {"fajr": 5, "sunrise": 6, "dhuhr": 12, "asr": 13, "maghrib": 18, "isha": 18}
    t = dict((k, v / 24.0) for k, v in t.items())
    r = {
        "fajr": at(fa, t["fajr"], True),
        "sunrise": at(0.833, t["sunrise"], True),
        "dhuhr": mid(t["dhuhr"]),
        "asr": asr(t["asr"], 1),
        "maghrib": at(0.833, t["maghrib"]),
    }
    r["isha"] = (r["maghrib"] + imin / 60.0) if imin else at(ia, t["isha"])
    shift = tz - lon / 15.0
    for k in r:
        r[k] = _fix(r[k] + shift, 24)
    r["dhuhr"] += 1 / 60.0
    r["maghrib"] += 1 / 60.0
    return r


def hm(h):
    m = int(round(h * 60)) % (24 * 60)
    return "%02d:%02d" % (m // 60, m % 60)


def local_tz_hours(ts=None):
    lt = time.localtime(ts)
    try:
        return lt.tm_gmtoff / 3600.0
    except AttributeError:
        return -time.timezone / 3600.0


def city(name):
    for c in CITIES:
        if c[0] == name:
            return c
    return None


def today_prayers(city_name, ts=None):
    c = city(city_name)
    if c is None:
        return None
    lt = time.localtime(ts)
    return prayer_times(lt.tm_year, lt.tm_mon, lt.tm_mday, c[1], c[2], local_tz_hours(ts), c[3])


def prayer_due(city_name, ts=None, window=60):
    """Name of the prayer whose time is within the current minute, else None."""
    pt = today_prayers(city_name, ts)
    if pt is None:
        return None
    lt = time.localtime(ts)
    now = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    for key, label in PRAYER_NAMES:
        s = int(pt[key] * 3600)
        if 0 <= now - (s - s % 60) < window:
            return key, label
    return None


def next_prayer(city_name, ts=None):
    pt = today_prayers(city_name, ts)
    if pt is None:
        return None
    lt = time.localtime(ts)
    now = lt.tm_hour + lt.tm_min / 60.0
    for key, label in PRAYER_NAMES:
        if pt[key] > now:
            return label, pt[key]
    return PRAYER_NAMES[0][1], pt["fajr"] + 24


# ------------------------------------------------------------------ adhkar / ayah of the day
ADHKAR = [
    u"سبحان الله وبحمده، سبحان الله العظيم",
    u"لا حول ولا قوة إلا بالله",
    u"أستغفر الله العظيم وأتوب إليه",
    u"اللهم صلِّ وسلِّم على نبينا محمد",
    u"لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير",
    u"حسبنا الله ونعم الوكيل",
    u"سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    u"رب اغفر لي وتب عليّ إنك أنت التواب الرحيم",
    u"اللهم إني أسألك العفو والعافية في الدنيا والآخرة",
    u"ربنا آتنا في الدنيا حسنة وفي الآخرة حسنة وقنا عذاب النار",
]

AYAH_KEYS = ["2:255", "2:286", "94:5", "94:6", "65:2", "65:3", "13:28", "3:173", "39:53",
             "2:152", "55:13", "20:46", "2:153", "9:51", "29:69", "40:60", "2:186", "24:35",
             "2:45", "3:139", "8:46", "12:87", "18:10", "21:87", "59:22", "59:23", "112:1"]

API = "https://api.quran.com/api/v4/"


def day_index(ts=None):
    lt = time.localtime(ts)
    return lt.tm_yday + lt.tm_year * 366


def dhikr_of_the_moment(ts=None):
    return ADHKAR[int((ts or time.time()) // 30) % len(ADHKAR)]


def clean_text(t):
    t = re.sub(r"<sup[^>]*>.*?</sup>", u"", t or u"", flags=re.S)
    t = re.sub(r"<br\s*/?>", u"\n", t)
    t = re.sub(r"</p>", u"\n", t)
    t = re.sub(r"<[^>]+>", u"", t)
    try:
        t = data.unescape_html(t)
    except Exception:
        pass
    return re.sub(u"[ \t]+", u" ", t).strip()


def ayah_of_the_day(ts=None):
    """(key, text).  Uses the bundled Quran text first (works offline), the internet only as a fallback."""
    key = AYAH_KEYS[day_index(ts) % len(AYAH_KEYS)]
    try:
        sn, an = [int(x) for x in key.split(":")]
        rows = local_verses(sn)
        if rows and 1 <= an <= len(rows):
            return key, rows[an - 1][1]
    except Exception:
        pass
    js = data.cached_json(API + "verses/by_key/%s?fields=text_uthmani" % key, "ayah_" + key.replace(":", "_"))
    txt = js["verse"]["text_uthmani"]
    return key, txt


# ------------------------------------------------------------------ time of day (automatic themes)
def day_period(city_name=None, ts=None):
    """-> one of fajr / sunrise / dhuhr / asr / maghrib / isha / night  (by prayer times when a city is set)."""
    lt = time.localtime(ts)
    now = lt.tm_hour + lt.tm_min / 60.0
    pt = today_prayers(city_name, ts) if city_name else None
    if pt is None:
        if now < 4.5:
            return "night"
        if now < 6.5:
            return "fajr"
        if now < 12:
            return "sunrise"
        if now < 15.5:
            return "dhuhr"
        if now < 18:
            return "asr"
        if now < 19.5:
            return "maghrib"
        return "isha"
    cur = "night"
    for key in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"):
        if now >= pt[key]:
            cur = key
    if cur == "isha" and now >= pt["isha"] + 4:
        cur = "night"
    return cur


def is_daytime(city_name=None, ts=None):
    return day_period(city_name, ts) in ("sunrise", "dhuhr", "asr")


# ------------------------------------------------------------------ adhan sound
ADHAN_URLS = [(u"أذان 1", "https://www.islamcan.com/audio/adhan/azan1.mp3"),
              (u"أذان 2", "https://www.islamcan.com/audio/adhan/azan2.mp3"),
              (u"أذان 3", "https://www.islamcan.com/audio/adhan/azan3.mp3"),
              (u"أذان 4", "https://www.islamcan.com/audio/adhan/azan4.mp3")]
ADHAN_MIN_BYTES = 40000


def adhan_user_files():
    """Your own adhan files: <disk>/QuranHub/adhan/*.mp3 or /etc/enigma2/quranhub_adhan/*"""
    dirs = ["/etc/enigma2/quranhub_adhan"]
    try:
        rd = data.record_dir()
        if rd:
            dirs.insert(0, os.path.join(rd, "adhan"))
    except Exception:
        pass
    out = []
    for d in dirs:
        for e in AUDIO_EXT:
            out.extend(sorted(glob.glob(os.path.join(d, "*" + e))))
    return out


def adhan_cache_path(idx):
    base = None
    try:
        rd = data.record_dir()
        if rd:
            base = os.path.join(rd, "adhan_cache")
    except Exception:
        pass
    base = base or os.path.join(data.CACHE_DIR, "adhan")
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
    except OSError:
        return None
    return os.path.join(base, "adhan_%d.mp3" % idx)


def adhan_source(cfg):
    """-> (path_or_url, label) or None when the adhan sound is switched off."""
    sel = cfg.get("adhan_sound", "online:0")
    if sel == "off":
        return None
    if sel.startswith("file:"):
        pth = sel[5:]
        if os.path.exists(pth):
            return pth, os.path.basename(pth)
    files = adhan_user_files()
    if sel.startswith("online:"):
        try:
            idx = int(sel.split(":")[1]) % len(ADHAN_URLS)
        except ValueError:
            idx = 0
    else:
        idx = 0
    cp = adhan_cache_path(idx)
    if cp and os.path.exists(cp) and os.path.getsize(cp) > ADHAN_MIN_BYTES:
        return cp, ADHAN_URLS[idx][0]
    if files and not sel.startswith("online:"):
        return files[0], os.path.basename(files[0])
    return ADHAN_URLS[idx][1], ADHAN_URLS[idx][0]


def adhan_prefetch(cfg):
    """Download the chosen online adhan once so it also plays with a flaky connection."""
    sel = cfg.get("adhan_sound", "online:0")
    if not sel.startswith("online:"):
        return False
    try:
        idx = int(sel.split(":")[1]) % len(ADHAN_URLS)
    except ValueError:
        idx = 0
    cp = adhan_cache_path(idx)
    if not cp or (os.path.exists(cp) and os.path.getsize(cp) > ADHAN_MIN_BYTES):
        return False
    raw = data.http_get(ADHAN_URLS[idx][1], 40)
    if len(raw) < ADHAN_MIN_BYTES:
        raise ValueError("adhan file too small (%d bytes)" % len(raw))
    with open(cp + ".part", "wb") as f:
        f.write(raw)
    os.rename(cp + ".part", cp)
    return True


# ------------------------------------------------------------------ chapter text / tafsir / translation
# Everything the reader needs is bundled inside the plugin (qdata/), so it works with no internet.
# Online sources are only used for the big tafsirs that are not bundled, and are tried one after
# another (automatic fallback).  Every attempt is logged so the diagnostic screen can show why.
import gzip

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
QDATA = os.path.join(PLUGIN_DIR, "qdata")

ALQ = "https://api.alquran.cloud/v1/surah/%d/%s"
BASMALA = u"بسم الله الرحمن الرحيم"
SPA5K = ["https://cdn.jsdelivr.net/gh/spa5k/tafsir_api@main/tafsir/%s/%d.json",
         "https://fastly.jsdelivr.net/gh/spa5k/tafsir_api@main/tafsir/%s/%d.json",
         "https://raw.githubusercontent.com/spa5k/tafsir_api/main/tafsir/%s/%d.json"]

# key, Arabic title, spa5k slug, alquran.cloud edition, quran.com tafsir id, bundled in the plugin
TAFSIRS = [
    ("muyassar", u"التفسير الميسر", "ar-tafsir-muyassar", "ar.muyassar", 16, True),
    ("saadi", u"تفسير السعدي", "ar-tafseer-al-saddi", None, 91, True),
    ("jalalayn", u"تفسير الجلالين", "ar-tafsir-al-jalalayn", "ar.jalalayn", None, True),
    ("ibnkathir", u"تفسير ابن كثير", "ar-tafsir-ibn-kathir", None, 14, False),
    ("tabari", u"تفسير الطبري", "ar-tafsir-al-tabari", None, 15, False),
    ("qurtubi", u"تفسير القرطبي", "ar-tafseer-al-qurtubi", None, 90, False),
    ("baghawi", u"تفسير البغوي", "ar-tafsir-al-baghawi", None, 94, False),
    ("wasit", u"التفسير الوسيط", "ar-tafsir-al-wasit", None, 93, False),
]
TAFSIR_BY_KEY = dict((t[0], t) for t in TAFSIRS)
SAME_AS_ABOVE = u"(هذه الآية داخلة في تفسير ما قبلها)"

# first (surah, ayah) of each juz
JUZ_START = [(1, 1), (2, 142), (2, 253), (3, 92), (4, 24), (4, 148), (5, 82), (6, 111), (7, 88), (8, 41),
             (9, 93), (11, 6), (12, 53), (15, 1), (17, 1), (18, 75), (21, 1), (23, 1), (25, 21), (27, 56),
             (29, 46), (33, 31), (36, 28), (39, 32), (41, 47), (46, 1), (51, 31), (58, 1), (67, 1), (78, 1)]

LOG = []          # [(time, what, ok, detail)]
LAST = {}         # kind -> short source description


def log(what, ok, detail=u""):
    LOG.append((time.time(), what, bool(ok), u"%s" % (detail,)))
    del LOG[:-80]


class SourceError(Exception):
    pass


def data_dirs():
    """Folders that may hold extra data (a pack unpacked on a USB stick / HDD, downloads...)."""
    out = [QDATA, "/etc/enigma2/quranhub_data"]
    try:
        rd = data.record_dir()
        if rd:
            out.append(os.path.join(rd, "data"))
    except Exception:
        pass
    for b in sorted(glob.glob("/media/*")):
        out.append(os.path.join(b, "QuranHub", "data"))
    seen, res = set(), []
    for d in out:
        if d not in seen and os.path.isdir(d):
            seen.add(d)
            res.append(d)
    return res


def writable_data_dir():
    try:
        rd = data.record_dir()
        if rd:
            d = os.path.join(rd, "data")
            if not os.path.isdir(d):
                os.makedirs(d)
            return d
    except Exception:
        pass
    return None


def find_data(rel):
    for d in data_dirs():
        p = os.path.join(d, rel)
        if os.path.exists(p):
            return p
    return None


def _read_json_gz(path):
    with gzip.open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


_MEM = {}


def _mem(rel):
    """Whole-file data kept in memory (the Quran text and the translation are ~1 MB each)."""
    if rel in _MEM:
        return _MEM[rel]
    p = find_data(rel)
    if not p:
        return None
    obj = _read_json_gz(p)
    _MEM[rel] = obj
    return obj


def local_quran_ok():
    try:
        q = _mem("quran.json.gz")
        return bool(q) and sum(len(v) for v in q.values()) == 6236
    except Exception:
        return False


def local_verses(n):
    q = _mem("quran.json.gz")
    if not q:
        return None
    return [(i + 1, t) for i, t in enumerate(q[str(n)])]


def local_translation(n):
    t = _mem("tr_en.json.gz")
    return list(t[str(n)]) if t else None


def local_tafsir(key, n):
    p = find_data("taf_%s/%d.json.gz" % (key, n))
    if not p:
        p = find_data("taf_%s.json.gz" % key)
        if p:
            return _read_json_gz(p).get(str(n))
        return None
    return _read_json_gz(p)


def tafsir_available(key):
    """True when the whole tafsir is present locally (bundled, or an unpacked pack)."""
    return bool(find_data("taf_%s/114.json.gz" % key) or find_data("taf_%s.json.gz" % key))


def _store_tafsir(key, n, arr):
    d = writable_data_dir()
    if not d:
        return False
    try:
        dd = os.path.join(d, "taf_" + key)
        if not os.path.isdir(dd):
            os.makedirs(dd)
        raw = json.dumps(arr, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.GzipFile(os.path.join(dd, "%d.json.gz" % n), "wb", 6, mtime=0) as f:
            f.write(raw)
        return True
    except Exception:
        return False


def _alq(n, edition):
    """alquran.cloud returns a whole surah in ONE request -> [(number in surah, text)]"""
    js = data.cached_json(ALQ % (n, edition), "alq_%s_%d" % (edition, n))
    rows = js["data"]["ayahs"]
    return [(int(a["numberInSurah"]), a["text"]) for a in rows]


def _strip_basmala(n, rows):
    """alquran.cloud glues the basmala in front of verse 1 of every surah except 1 and 9."""
    if n in (1, 9) or not rows:
        return rows
    num, text = rows[0]
    words = text.split()
    if len(words) > 4 and data.norm(u" ".join(words[:4])) == BASMALA:
        rows = [(num, u" ".join(words[4:]))] + rows[1:]
    return rows


def _try(chain, what):
    """Run [(label, func)] until one returns something truthy; log every attempt."""
    errs = []
    for label, fn in chain:
        try:
            res = fn()
            if res:
                log("%s <- %s" % (what, label), True)
                LAST[what] = label
                return res
            errs.append(u"%s: فارغ" % label)
            log("%s <- %s" % (what, label), False, u"empty")
        except Exception as e:
            errs.append(u"%s: %s" % (label, e))
            log("%s <- %s" % (what, label), False, e)
    raise SourceError(u" | ".join(errs) or u"لا توجد مصادر")


def chapter_verses(n):
    """[(verse_number, text)] - the bundled text first, then the internet."""
    def online_alq():
        return _strip_basmala(n, _alq(n, "quran-simple"))

    def online_qcom():
        rows = _paged(API + "verses/by_chapter/%d?fields=text_imlaei&per_page=50&page=%%d" % n,
                      "ch_text_%d" % n, "verses")
        return [(v["verse_number"], v.get("text_imlaei") or v.get("text_uthmani", u"")) for v in rows]

    return _try([(u"داخل البلوجين", lambda: local_verses(n)),
                 (u"alquran.cloud", online_alq),
                 (u"quran.com", online_qcom)], "verses")


def _spa5k_rows(slug, n):
    errs = []
    for fmt in SPA5K:
        try:
            js = data.cached_json(fmt % (slug, n), "spa_%s_%d" % (slug, n))
            if js:
                return js
        except Exception as e:
            errs.append(e)
    raise SourceError(u"; ".join([u"%s" % e for e in errs]))


def chapter_tafsir(n, key="muyassar"):
    """[text per verse] ('=' = same as the previous verse)."""
    tid = TAFSIR_BY_KEY.get(key) or TAFSIR_BY_KEY["muyassar"]
    key, _title, slug, alq, qid, _bundled = tid
    count = len(local_verses(n) or []) or 0

    def from_spa():
        rows = _spa5k_rows(slug, n)
        arr = [u""] * max(count, max([int(r.get("ayah", 0)) for r in rows] + [0]))
        for r in rows:
            a = int(r.get("ayah", 0))
            if 1 <= a <= len(arr):
                arr[a - 1] = clean_text(r.get("text", u""))
        for i in range(len(arr) - 1, 0, -1):
            if arr[i] and arr[i] == arr[i - 1]:
                arr[i] = u"="
        _store_tafsir(key, n, arr)
        return arr

    def from_alq():
        if not alq:
            return None
        rows = dict(_alq(n, alq))
        arr = [rows.get(i + 1, u"") for i in range(max(count, max(rows or [0])))]
        _store_tafsir(key, n, arr)
        return arr

    def from_qcom():
        if not qid:
            return None
        rows = _paged(API + "tafsirs/%d/by_chapter/%d?per_page=50&page=%%d" % (qid, n),
                      "ch_tafsir%d_%d" % (qid, n), "tafsirs")
        out = {}
        for r in rows:
            try:
                out[int(str(r["verse_key"]).split(":")[1])] = clean_text(r["text"])
            except Exception:
                pass
        arr = [out.get(i + 1, u"") for i in range(max(count, max(out or [0])))]
        _store_tafsir(key, n, arr)
        return arr

    return _try([(u"داخل البلوجين / القرص", lambda: local_tafsir(key, n)),
                 (u"jsdelivr/github", from_spa),
                 (u"alquran.cloud", from_alq),
                 (u"quran.com", from_qcom)], "tafsir:" + key)


def chapter_translation(n, rid=20):
    """[text] in verse order - Saheeh International."""
    def from_alq():
        return [clean_text(t) for _, t in _alq(n, "en.sahih")]

    def from_qcom():
        js = data.cached_json(API + "quran/translations/%d?chapter_number=%d" % (rid, n),
                              "ch_tr%d_%d" % (rid, n))
        return [clean_text(x.get("text", u"")) for x in js.get("translations", [])]

    return _try([(u"داخل البلوجين", lambda: local_translation(n)),
                 (u"alquran.cloud", from_alq),
                 (u"quran.com", from_qcom)], "translation")


_AR_DIGITS = u"٠١٢٣٤٥٦٧٨٩"


def ar_num(v):
    return u"".join(_AR_DIGITS[int(c)] for c in str(v))


def reader_load(n, mode="text", tafsir="muyassar"):
    blocks, note = _reader_load(n, mode, tafsir)
    return [sanitize(b) for b in blocks], note


def _reader_load(n, mode="text", tafsir="muyassar"):
    """-> (blocks, note).  blocks: list of unicode strings (one per verse)."""
    verses = chapter_verses(n)
    note = u"المصدر: " + LAST.get("verses", u"")
    if mode == "tafsir":
        taf = chapter_tafsir(n, tafsir)
        note = u"%s  |  المصدر: %s" % (TAFSIR_BY_KEY.get(tafsir, TAFSIRS[0])[1], LAST.get("tafsir:" + tafsir, u""))
        blocks = []
        for i, (v, t) in enumerate(verses):
            body = taf[i] if i < len(taf) else u""
            if body == u"=":
                body = SAME_AS_ABOVE
            blocks.append(u"الآية (%s)\n%s\n%s\n" % (ar_num(v), t, body or u"-"))
        return blocks, note
    if mode == "translation":
        tr = chapter_translation(n)
        note = u"Saheeh International  |  المصدر: " + LAST.get("translation", u"")
        return [u"الآية (%s)\n%s\n%s\n" % (ar_num(v), t, tr[i] if i < len(tr) else u"") for i, (v, t) in enumerate(verses)], note
    if mode == "mushaf":
        head = []
        if n not in (1, 9):
            head = [BASMALA + u"\n"]
        return head + [u"%s (%s)" % (t, ar_num(v)) for v, t in verses], note
    return [u"%s (%s)" % (t, ar_num(v)) for v, t in verses], note


def sanitize(t):
    """Drop control / invisible format characters that make some enigma2 labels render nothing."""
    import unicodedata
    out = []
    for ch in t:
        if ch in u"\n":
            out.append(ch)
        elif ch == u"\t":
            out.append(u" ")
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            continue
        else:
            out.append(ch)
    return u"".join(out)


def reader_blocks(n, mode="text", tafsir="muyassar"):
    return reader_load(n, mode, tafsir)[0]


def juz_of(surah, ayah=1):
    j = 1
    for i, (s, a) in enumerate(JUZ_START):
        if (surah, ayah) >= (s, a):
            j = i + 1
    return j


def juz_surah(j):
    return JUZ_START[max(1, min(30, j)) - 1][0]


def _split_long(block, budget):
    out = []
    while len(block) > budget:
        cut = block.rfind(u" ", 0, budget)
        if cut < budget // 2:
            cut = budget
        out.append(block[:cut].rstrip())
        block = block[cut:].lstrip()
    out.append(block)
    return out


def paginate(blocks, budget, sep=u"\n"):
    """Group blocks into pages of about `budget` characters (long blocks are split at spaces)."""
    flat = []
    for b in blocks:
        flat.extend(_split_long(b, budget))
    pages, cur, size = [], [], 0
    for b in flat:
        if cur and size + len(b) > budget:
            pages.append(sep.join(cur))
            cur, size = [], 0
        cur.append(b)
        size += len(b) + 1
    if cur:
        pages.append(sep.join(cur))
    return pages or [u""]


def _nlines(text, cpl):
    return sum(max(1, -(-len(l) // cpl)) for l in text.split(u"\n"))


def paginate_lines(blocks, cpl, max_lines, sep=u"\n"):
    """Pages that really fit the screen: a page holds at most `max_lines` wrapped lines."""
    flat = []
    for b in blocks:
        flat.extend(_split_long(b, max(40, int(cpl * max_lines * 0.8))))
    pages, cur, used = [], [], 0
    for b in flat:
        n = _nlines(b, cpl) + (0 if sep == u" " else 0)
        if sep == u" ":                      # flowing text: count characters only
            n = len(b) / float(cpl)
        if cur and used + n > max_lines:
            pages.append(sep.join(cur))
            cur, used = [], 0
        cur.append(b)
        used += n
    if cur:
        pages.append(sep.join(cur))
    return pages or [u""]


def wrap_lines(blocks, cpl, flow=False, meas=None):
    """Word-wrap into single lines (the reader draws one label per line, which every skin renders).
    flow=True joins the blocks into one continuous paragraph (mushaf style)."""
    paras = []
    if flow:
        paras = [u" ".join(b.replace(u"\n", u" ").strip() for b in blocks)]
    else:
        for b in blocks:
            paras.extend(b.split(u"\n"))
    out = []
    for para in paras:
        words = para.split()
        if not words:
            out.append(u"")
            continue
        if meas:                                     # (width_of, max_width, space): real pixel widths
            wf, lim, sp = meas
            cur, cw = u"", 0
            for w in words:
                ww = wf(w)
                if cur and cw + sp + ww > lim:
                    out.append(cur)
                    cur, cw = w, ww
                else:
                    cur, cw = ((cur + u" " + w), cw + sp + ww) if cur else (w, ww)
            if cur:
                out.append(cur)
            continue
        cur = u""
        for w in words:
            while len(w) > cpl:                      # a single huge word
                if cur:
                    out.append(cur)
                    cur = u""
                out.append(w[:cpl])
                w = w[cpl:]
            if cur and len(cur) + 1 + len(w) > cpl:
                out.append(cur)
                cur = w
            else:
                cur = (cur + u" " + w) if cur else w
        if cur:
            out.append(cur)
    while out and out[-1] == u"":
        out.pop()
    return out or [u""]


def wrap_tagged(blocks, cpl, flow=False, heads=False, meas=None, offset=0, trim=True):
    """Like wrap_lines but every line knows which block(s) it came from.
    -> [(line, set(block indexes), is_head)]   is_head: first line of a block (tafsir/translation)."""
    out = []
    if flow:
        words = []
        for bi, b in enumerate(blocks):
            if b.endswith(u"\n") and b.strip():          # a heading (the basmala): a line of its own
                words.append((None, bi))
                words.append((b.strip(), -1 - bi))
                words.append((None, bi))
                continue
            for w in b.replace(u"\n", u" ").split():
                words.append((w, bi))
        cur, tags = u"", set()
        if meas:
            wf, lim, sp = meas
            cw = 0
        for w, bi in words:
            if w is None:
                if cur:
                    out.append((cur, tags, False))
                cur, tags = u"", set()
                continue
            if bi < 0:
                out.append((w, set([-1 - bi]), 1))
                continue
            if meas:
                ww = wf(w)
                if cur and cw + sp + ww > lim:
                    out.append((cur, tags, False))
                    cur, tags, cw = w, set([bi]), ww
                else:
                    cur, cw = ((cur + u" " + w), cw + sp + ww) if cur else (w, ww)
                    tags.add(bi)
                continue
            while len(w) > cpl:
                if cur:
                    out.append((cur, tags, False))
                    cur, tags = u"", set()
                out.append((w[:cpl], set([bi]), False))
                w = w[cpl:]
            if cur and len(cur) + 1 + len(w) > cpl:
                out.append((cur, tags, False))
                cur, tags = w, set([bi])
            else:
                cur = (cur + u" " + w) if cur else w
                tags.add(bi)
        if cur:
            out.append((cur, tags, False))
        return out or [(u"", set(), False)]
    for bi, b in enumerate(blocks, offset):
        paras = b.split(u"\n")
        numbered = heads and len(paras) > 1 and paras[0].startswith(u"الآية")
        for pi_, para in enumerate(paras):
            if heads:
                role = (2 if pi_ == 0 else (1 if pi_ == 1 else 0)) if numbered else (1 if pi_ == 0 else 0)
            else:
                role = 0
            for ln in wrap_lines([para], cpl, meas=meas):
                out.append((ln, set([bi]), role if ln else 0))
    if not trim:
        return out
    while out and not out[-1][0]:
        out.pop()
    return out or [(u"", set(), False)]


def surah_of_title(title):
    m = re.search(u"سورة\\s+(.+?)\\s*$", title or u"")
    if m:
        try:
            return data.surah_no(m.group(1))
        except Exception:
            return None
    return None


# ------------------------------------------------------------------ downloads / local archive
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wav", ".opus")


def ext_from_url(url):
    path = url.split("?")[0].lower()
    for e in AUDIO_EXT:
        if path.endswith(e):
            return e
    return ".mp3"


def download_dir(base=None):
    d = base or data.record_dir()
    if d is None:
        return None
    d = os.path.join(d, "downloads")
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
    except OSError:
        return None
    return d


class Downloader(object):
    """One background download at a time with a queue.
    1.6: per-file format (converted with ffmpeg after the download), one folder per reciter,
    free-space check, the queue is kept on the disk and resumed after a reboot, and an event
    callback (on_event(kind, title, detail)) for the Telegram bot."""
    MIN_FREE = 200 * 1024 * 1024
    QUEUE_FILE = ".saadquranhub_queue.json"

    def __init__(self, folder=None):
        self.folder = folder
        self.queue = []              # [{"title", "url", "fmt", "folder", "name"}]
        self.current = None
        self.bytes = 0
        self.total = 0
        self.done_files = []
        self.errors = []
        self.stop_flag = False
        self.lock = threading.Lock()
        self.thread = None
        self.on_event = None
        self.batch = 0
        self.batch_done = 0

    def add(self, title, url, fmt="original", folder=None, name=None, save=True):
        with self.lock:
            if not self.busy():
                self.batch = self.batch_done = 0
            self.queue.append({"title": title, "url": url, "fmt": fmt or "original", "folder": folder, "name": name})
            self.batch += 1
        if save:
            self.save_queue()
        self._kick()

    def _kick(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_flag = False
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()

    def cancel(self):
        self.stop_flag = True
        with self.lock:
            self.queue = []
        self.save_queue()

    def busy(self):
        return self.current is not None or bool(self.queue)

    def pending(self):
        return len(self.queue) + (1 if self.current else 0)

    # -- the queue survives a reboot -----------------------------------------------------
    def _qpath(self):
        d = self.folder or download_dir()
        return os.path.join(d, self.QUEUE_FILE) if d else None

    def save_queue(self):
        p = self._qpath()
        if not p:
            return
        try:
            with self.lock:
                items = list(self.queue)
            if self.current_item is not None:
                items.insert(0, self.current_item)
            if not items:
                if os.path.exists(p):
                    os.remove(p)
                return
            with open(p + ".tmp", "w") as f:
                json.dump([dict(x, resolve=None) for x in items if x.get("url")], f)
            os.rename(p + ".tmp", p)
        except Exception:
            pass

    def resume_saved(self):
        """Put back what was still waiting when the receiver was switched off -> number of files."""
        p = self._qpath()
        if not p or not os.path.exists(p):
            return 0
        try:
            with open(p) as f:
                items = json.load(f)
        except Exception:
            return 0
        n = 0
        for x in items:
            if x.get("url"):
                self.add(x.get("title", u""), x["url"], x.get("fmt"), x.get("folder"), x.get("name"), save=False)
                n += 1
        return n

    current_item = None

    def _emit(self, kind, title, detail=u""):
        cb = self.on_event
        if cb:
            try:
                cb(kind, title, detail)
            except Exception:
                pass

    def target(self, item):
        folder = item.get("folder") or self.folder or download_dir()
        if folder is None:
            raise IOError("no disk")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        name = item.get("name") or data.safe_name(item["title"])
        return folder, name

    def _run(self):
        while not self.stop_flag:
            with self.lock:
                if not self.queue:
                    break
                item = self.queue.pop(0)
            self.current_item = item
            title, url, fmt = item["title"], item["url"], item.get("fmt") or "original"
            self.current = title
            self.bytes = self.total = 0
            try:
                folder, name = self.target(item)
                src_ext = ext_from_url(url)
                want_ext = data.format_ext(fmt) if fmt != "original" else src_ext
                final = os.path.join(folder, name + (want_ext or src_ext))
                if os.path.exists(final) and os.path.getsize(final) > 10000:
                    self.done_files.append(final)
                    self.batch_done += 1
                    continue
                free = data.disk_free(folder)
                if free is not None and free < self.MIN_FREE:
                    raise IOError(u"المساحة على القرص غير كافية (%s متبقية)" % data.fmt_bytes(free))
                dest = os.path.join(folder, name + src_ext)
                if not (os.path.exists(dest) and os.path.getsize(dest) > 10000):
                    self._fetch(url, dest)
                path = dest
                convert = fmt != "original" and (src_ext.lower() != (want_ext or "").lower() or fmt.startswith("mp3_"))
                if convert:
                    try:
                        path = data.transcode(dest, fmt)
                        if os.path.abspath(path) != os.path.abspath(dest):
                            os.remove(dest)
                    except Exception as e:
                        self.errors.append(u"%s: تعذّر التحويل إلى %s (%s) - بقي الملف الأصلي" % (title, fmt, e))
                        path = dest
                self.done_files.append(path)
                self.batch_done += 1
                self._emit("file", title, path)
            except Exception as e:
                self.errors.append(u"%s: %s" % (title, e))
                self._emit("error", title, u"%s" % e)
                if u"المساحة" in (u"%s" % e):
                    with self.lock:
                        self.queue = []
            finally:
                self.current = None
                self.current_item = None
                self.save_queue()
        if not self.stop_flag and self.batch:
            self._emit("batch", u"", u"%d/%d" % (self.batch_done, self.batch))

    def _fetch(self, url, dest):
        resp = data.open_stream(url, 20)
        part = dest + ".part"
        try:
            try:
                self.total = int(resp.headers.get("Content-Length") or 0)
            except Exception:
                self.total = 0
            with open(part, "wb") as f:
                while not self.stop_flag:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    self.bytes += len(chunk)
            if self.stop_flag:
                raise IOError("cancelled")
            os.rename(part, dest)
        finally:
            try:
                resp.close()
            except Exception:
                pass
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass


def local_files(base=None, limit=400):
    """Recorded and downloaded audio files, newest first: [(name, path)]"""
    root = base or data.record_dir()
    if root is None:
        return []
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "cache"]
        for fn in files:
            if fn.lower().endswith(AUDIO_EXT):
                p = os.path.join(dirpath, fn)
                try:
                    found.append((os.path.getmtime(p), os.path.splitext(fn)[0], p))
                except OSError:
                    pass
    found.sort(reverse=True)
    return [(n, p) for _, n, p in found[:limit]]


# ------------------------------------------------------------------ backup / restore
BACKUP_NAME = "quranhub_backup.json"


def backup_dir():
    return data.record_dir()


def backup_settings(cfg, folder=None):
    d = folder or backup_dir()
    if d is None:
        return None
    path = os.path.join(d, BACKUP_NAME)
    with open(path, "wb") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=1).encode("utf-8"))
    return path


def find_backup(folder=None):
    roots = [folder] if folder else [os.path.join(b, "QuranHub") for b in
                                     ["/media/hdd", "/media/usb", "/media/mmc"] + sorted(glob.glob("/media/*"))]
    best = None
    for r in roots:
        p = os.path.join(r, BACKUP_NAME)
        if os.path.isfile(p) and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
            best = p
    return best


def restore_settings(path):
    with open(path, "rb") as f:
        cfg = json.loads(f.read().decode("utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("bad backup")
    return cfg


# ------------------------------------------------------------------ playlists / history / schedules
def pl_add(cfg, name, item):
    pls = cfg.setdefault("pls", {})
    items = pls.setdefault(name, [])
    entry = {"title": item.get("title", u""), "url": item["url"]}
    if item.get("live"):
        entry["live"] = True
    if any(x["url"] == entry["url"] for x in items):
        return False
    items.append(entry)
    return True


def history_add(cfg, title, url, live=False, ts=None):
    hist = cfg.setdefault("hist", [])
    if hist and hist[0].get("url") == url:
        return
    hist.insert(0, {"title": title, "url": url, "live": bool(live), "ts": int(ts or time.time())})
    del hist[100:]
    plays = cfg.setdefault("plays", {})
    plays[title] = plays.get(title, 0) + 1
    if len(plays) > 300:
        for k, _v in sorted(plays.items(), key=lambda kv: kv[1])[:60]:
            plays.pop(k, None)


def most_played(cfg, n=30):
    plays = cfg.get("plays", {})
    urls = {}
    for h in cfg.get("hist", []):
        urls.setdefault(h["title"], h)
    rows = []
    for title, c in sorted(plays.items(), key=lambda kv: -kv[1])[:n]:
        h = urls.get(title)
        if h:
            rows.append((c, h))
    return rows


DAY_NAMES = [u"الاثنين", u"الثلاثاء", u"الأربعاء", u"الخميس", u"الجمعة", u"السبت", u"الأحد"]
DAY_SETS = [(u"كل يوم", []), (u"يوم الجمعة", [4]), (u"الاثنين والخميس", [0, 3]),
            (u"أيام الأسبوع (الأحد - الخميس)", [6, 0, 1, 2, 3]),
            (u"السبت", [5]), (u"الأحد", [6])]


def sched_label(s):
    days = s.get("days") or []
    dtxt = u"كل يوم" if not days else u"، ".join(DAY_NAMES[d] for d in days)
    kind = u"تسجيل %d د" % s.get("dur", 60) if s.get("rec") else u"تشغيل"
    return u"%s  •  %s  •  %s: %s" % (s["hm"], dtxt, kind, s.get("title", u""))


def sched_due(cfg, ts=None, fired=None):
    """Schedules due in the current minute, each at most once per minute."""
    lt = time.localtime(ts)
    cur = "%02d:%02d" % (lt.tm_hour, lt.tm_min)
    stamp = (lt.tm_year, lt.tm_yday, cur)
    out = []
    for s in cfg.get("sched", []):
        if s.get("hm") != cur or not s.get("on", True):
            continue
        days = s.get("days") or []
        if days and lt.tm_wday not in days:
            continue
        key = (s.get("id"),) + stamp
        if fired is not None:
            if key in fired:
                continue
            fired.add(key)
        out.append(s)
    return out


# ------------------------------------------------------------------ Arabic shaping (v3.4)
# Some enigma2 images join Arabic letters only when no tashkeel sits between them, so a text with
# full harakat is drawn as separate letters.  We join the letters ourselves (presentation forms) and
# keep every haraka: the marks are 'transparent' for joining, exactly like in the printed mushaf.
# letter: (isolated, final, initial, medial)   - None = cannot take that form (joins on the right only)
_FORMS = {
    0x0621: (0xFE80, None, None, None), 0x0622: (0xFE81, 0xFE82, None, None), 0x0623: (0xFE83, 0xFE84, None, None),
    0x0624: (0xFE85, 0xFE86, None, None), 0x0625: (0xFE87, 0xFE88, None, None), 0x0626: (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C),
    0x0627: (0xFE8D, 0xFE8E, None, None), 0x0628: (0xFE8F, 0xFE90, 0xFE91, 0xFE92), 0x0629: (0xFE93, 0xFE94, None, None),
    0x062A: (0xFE95, 0xFE96, 0xFE97, 0xFE98), 0x062B: (0xFE99, 0xFE9A, 0xFE9B, 0xFE9C), 0x062C: (0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0),
    0x062D: (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4), 0x062E: (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8), 0x062F: (0xFEA9, 0xFEAA, None, None),
    0x0630: (0xFEAB, 0xFEAC, None, None), 0x0631: (0xFEAD, 0xFEAE, None, None), 0x0632: (0xFEAF, 0xFEB0, None, None),
    0x0633: (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4), 0x0634: (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8), 0x0635: (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC),
    0x0636: (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0), 0x0637: (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4), 0x0638: (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8),
    0x0639: (0xFEC9, 0xFECA, 0xFECB, 0xFECC), 0x063A: (0xFECD, 0xFECE, 0xFECF, 0xFED0), 0x0641: (0xFED1, 0xFED2, 0xFED3, 0xFED4),
    0x0642: (0xFED5, 0xFED6, 0xFED7, 0xFED8), 0x0643: (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC), 0x0644: (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0),
    0x0645: (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4), 0x0646: (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8), 0x0647: (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC),
    0x0648: (0xFEED, 0xFEEE, None, None), 0x0649: (0xFEEF, 0xFEF0, None, None), 0x064A: (0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4),
    0x0671: (0xFB50, 0xFB51, None, None), 0x06CC: (0xFBFC, 0xFBFD, 0xFBFE, 0xFBFF), 0x06A9: (0xFB8E, 0xFB8F, 0xFB90, 0xFB91),
    0x06AF: (0xFB92, 0xFB93, 0xFB94, 0xFB95), 0x067E: (0xFB56, 0xFB57, 0xFB58, 0xFB59), 0x0686: (0xFB7A, 0xFB7B, 0xFB7C, 0xFB7D),
    0x0698: (0xFB8A, 0xFB8B, None, None), 0x06A4: (0xFB6A, 0xFB6B, 0xFB6C, 0xFB6D),
}
_LAM_ALEF = {0x0622: (0xFEF5, 0xFEF6), 0x0623: (0xFEF7, 0xFEF8), 0x0625: (0xFEF9, 0xFEFA), 0x0627: (0xFEFB, 0xFEFC)}
_TATWEEL = 0x0640


def _transparent(cp):
    return (0x0610 <= cp <= 0x061A or 0x064B <= cp <= 0x065F or cp == 0x0670 or 0x06D6 <= cp <= 0x06DC
            or 0x06DF <= cp <= 0x06E4 or 0x06E7 <= cp <= 0x06E8 or 0x06EA <= cp <= 0x06ED)


def _joins_left(cp):        # can connect to the following letter (has initial / medial forms)
    if cp == _TATWEEL:
        return True
    f = _FORMS.get(cp)
    return bool(f and f[2] is not None)


def _joins_right(cp):       # can connect to the previous letter
    if cp == _TATWEEL:
        return True
    f = _FORMS.get(cp)
    return bool(f and f[1] is not None)


# a haraka between two joined letters is drawn by many receiver fonts as a separate (spacing) glyph,
# which opens a gap in the word.  Its 'medial form' is the same mark on a short kashida, so the
# word stays joined.  (Marks with no medial form are kept as they are.)
_MARK_MEDIAL = {0x064E: 0xFE77, 0x064F: 0xFE79, 0x0650: 0xFE7B, 0x0651: 0xFE7D, 0x0652: 0xFE7F, 0x064B: 0xFE71}


def strip_tashkeel(text):
    return u"".join(c for c in text if not _transparent(ord(c)))


def shape_arabic(text, marks="medial"):
    """Logical-order text -> the same text with joined (presentation form) letters.
    marks: 'medial' (harakat inside a word sit on a kashida), 'keep' (combining marks) or 'none'."""
    if not text or not any(0x0621 <= ord(c) <= 0x06FF for c in text):
        return text
    if marks == "none":
        text = strip_tashkeel(text)
    cps = [ord(c) for c in text]
    n = len(cps)
    out = []
    i = 0

    def prev_letter(k):
        k -= 1
        while k >= 0 and _transparent(cps[k]):
            k -= 1
        return cps[k] if k >= 0 else None

    def next_index(k):
        k += 1
        while k < n and _transparent(cps[k]):
            k += 1
        return k

    def put_marks(seq, joined):
        for m in seq:
            out.append(_MARK_MEDIAL.get(m, m) if (joined and marks == "medial") else m)

    while i < n:
        cp = cps[i]
        if cp not in _FORMS:
            out.append(cp)
            i += 1
            continue
        p = prev_letter(i)
        joined_before = p is not None and _joins_left(p) and _joins_right(cp)
        j = next_index(i)
        if cp == 0x0644 and j < n and cps[j] in _LAM_ALEF:       # lam + alef ligature
            iso, fin = _LAM_ALEF[cps[j]]
            out.append(fin if joined_before else iso)
            k = next_index(j)
            put_marks(cps[i + 1:j] + cps[j + 1:k], False)
            i = k
            continue
        nx = cps[j] if j < n else None
        joined_after = nx is not None and _joins_left(cp) and _joins_right(nx) and (nx in _FORMS or nx == _TATWEEL)
        iso, fin, ini, med = _FORMS[cp]
        if joined_before and joined_after and med:
            out.append(med)
        elif joined_before and fin:
            out.append(fin)
        elif joined_after and ini:
            out.append(ini)
        else:
            out.append(iso)
        put_marks(cps[i + 1:j], joined_after)
        i = j
    return u"".join(_unichr(c) for c in out)


try:
    _unichr = unichr                                  # python 2
except NameError:
    _unichr = chr
