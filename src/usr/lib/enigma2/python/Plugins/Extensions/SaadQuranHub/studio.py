# -*- coding: utf-8 -*-
"""Quran Hub studio (v3): memorisation, khatma, adhkar, names of Allah, listening statistics and the
radio bouquet.  Pure Python (no enigma2 imports) so every function can be tested off the receiver."""
from __future__ import print_function

import os
import time

from . import data, extras

# ------------------------------------------------------------------ memorisation (hifz) studio
# label, everyayah.com folder, islamic.network edition (None = not available there)
HIFZ_RECITERS = [
    (u"مشاري العفاسي", "Alafasy_128kbps", "ar.alafasy"),
    (u"محمود خليل الحصري", "Husary_128kbps", "ar.husary"),
    (u"الحصري (معلّم - ببطء وتكرار)", "Husary_Muallim_128kbps", None),
    (u"محمد صديق المنشاوي (مرتل)", "Minshawy_Murattal_128kbps", "ar.minshawi"),
    (u"عبد الباسط عبد الصمد (مرتل)", "Abdul_Basit_Murattal_192kbps", "ar.abdulbasitmurattal"),
    (u"عبد الرحمن السديس", "Abdurrahmaan_As-Sudais_192kbps", "ar.abdurrahmaansudais"),
    (u"سعود الشريم", "Saood_ash-Shuraym_128kbps", "ar.saoodshuraym"),
    (u"ماهر المعيقلي", "MaherAlMuaiqly128kbps", "ar.mahermuaiqly"),
    (u"هاني الرفاعي", "Hani_Rifai_192kbps", "ar.hanirifai"),
    (u"علي الحذيفي", "Hudhaify_128kbps", "ar.hudhaify"),
]
EVERYAYAH = "https://everyayah.com/data/%s/%03d%03d.mp3"
ISLAMNET = "https://cdn.islamic.network/quran/audio/128/%s/%d.mp3"
HIFZ_EACH = [1, 3, 5, 7, 10, 20]
HIFZ_RANGE = [1, 2, 3, 5, 10]
HIFZ_MAX_ITEMS = 400
HIFZ_GAPS = [0, 3, 5, 8, 12]           # seconds of silence after each ayah (time to repeat it)
HIFZ_DEFAULT = {"n": 1, "a1": 1, "a2": 7, "each": 3, "rng": 1, "rec": 0, "src": "everyayah", "gap": 0}

AYAH_COUNTS = []


def ayah_counts():
    """Number of ayahs of each surah (from the bundled Quran text)."""
    global AYAH_COUNTS
    if not AYAH_COUNTS:
        q = extras._mem("quran.json.gz")
        if not q:
            raise ValueError("quran data missing")
        AYAH_COUNTS = [len(q[str(i)]) for i in range(1, 115)]
    return AYAH_COUNTS


def global_ayah(n, a):
    return sum(ayah_counts()[:n - 1]) + a


def hifz_state(cfg):
    st = dict(HIFZ_DEFAULT)
    st.update(cfg.get("hifz") or {})
    try:
        n = max(1, min(114, int(st["n"])))
        cnt = ayah_counts()[n - 1]
        st["n"] = n
        st["a1"] = max(1, min(cnt, int(st["a1"])))
        st["a2"] = max(st["a1"], min(cnt, int(st["a2"])))
        st["each"] = int(st["each"]) if int(st["each"]) in HIFZ_EACH else 3
        st["rng"] = int(st["rng"]) if int(st["rng"]) in HIFZ_RANGE else 1
        st["rec"] = max(0, min(len(HIFZ_RECITERS) - 1, int(st["rec"])))
        st["gap"] = int(st.get("gap", 0)) if int(st.get("gap", 0)) in HIFZ_GAPS else 0
    except Exception:
        st = dict(HIFZ_DEFAULT)
    if st.get("src") not in ("everyayah", "islamnet"):
        st["src"] = "everyayah"
    return st


def ayah_url(n, a, rec, src="everyayah"):
    label, folder, edition = HIFZ_RECITERS[rec]
    if src == "islamnet" and edition:
        return ISLAMNET % (edition, global_ayah(n, a))
    return EVERYAYAH % (folder, n, a)


def hifz_plan(st):
    """-> [(ayah, k, each, round, rounds)]  in playing order."""
    plan = []
    for r in range(1, st["rng"] + 1):
        for a in range(st["a1"], st["a2"] + 1):
            for k in range(1, st["each"] + 1):
                plan.append((a, k, st["each"], r, st["rng"]))
                if len(plan) >= HIFZ_MAX_ITEMS:
                    return plan
    return plan


def hifz_items(st):
    """Playlist items for BG.play_list()."""
    n = st["n"]
    rec = HIFZ_RECITERS[st["rec"]][0]
    texts = dict(extras.local_verses(n) or [])
    plan = hifz_plan(st)
    items = []
    for i, (a, k, each, r, rounds) in enumerate(plan):
        rep = u"تكرار %d/%d" % (k, each)
        if rounds > 1:
            rep += u" • دورة %d/%d" % (r, rounds)
        t = u"%s - آية %d من سورة %s (%s)" % (rec, a, data.surah_name(n), rep)
        tx = extras.sanitize(texts.get(a, u""))
        if tx:
            t += u"  ﴿ %s ﴾" % tx
        it = {"title": t, "url": ayah_url(n, a, st["rec"], st["src"]), "autonext": True, "nohist": True,
              "ayah": [n, a]}
        if st.get("gap"):
            it["gap"] = st["gap"]
        if i == len(plan) - 1:
            it["stop_at_end"] = True
        items.append(it)
    return items


def hifz_summary(st):
    s = u"سورة %s: من آية %d إلى %d • كل آية %d مرة • المقطع %d دورة • %s" % (
        data.surah_name(st["n"]), st["a1"], st["a2"], st["each"], st["rng"], HIFZ_RECITERS[st["rec"]][0])
    if st.get("gap"):
        s += u" • مهلة %d ث للترديد" % st["gap"]
    return s


def hifz_text(st):
    """The ayahs of the selected range as reading blocks."""
    verses = extras.local_verses(st["n"]) or []
    return [u"%s ﴿%d﴾" % (extras.sanitize(t), a) for a, t in verses if st["a1"] <= a <= st["a2"]]


# ------------------------------------------------------------------ khatma (daily wird)
PAGES = 604
KHATMA_DAYS = [7, 10, 15, 20, 30, 40, 60]


def khatma_state(cfg):
    k = dict(cfg.get("khatma") or {})
    k.setdefault("days", 30)
    k.setdefault("pages", 0)           # mushaf pages read in the current khatma
    k.setdefault("count", 0)           # completed khatmas
    k.setdefault("start", time.strftime("%Y-%m-%d"))
    k.setdefault("today", "")
    k.setdefault("today_pages", 0)
    return k


def khatma_daily(k):
    return int(-(-PAGES // max(1, int(k["days"]))))        # ceil


def khatma_juz(k):
    """Juz (1-30) where the next reading starts."""
    return max(1, min(30, int(k["pages"] * 30 / float(PAGES)) + 1))


def khatma_mark(cfg, pages=None, ts=None):
    """Record that today's wird (or `pages`) was read. -> (state, finished_khatma)"""
    k = khatma_state(cfg)
    today = time.strftime("%Y-%m-%d", time.localtime(ts))
    add = int(pages) if pages is not None else khatma_daily(k)
    if pages is None:
        star_add(cfg, u"الورد اليومي")
    if k["today"] != today:
        k["today"], k["today_pages"] = today, 0
    k["today_pages"] += add
    k["pages"] += add
    finished = False
    if k["pages"] >= PAGES:
        k["pages"] -= PAGES
        k["count"] += 1
        k["start"] = today
        finished = True
    cfg["khatma"] = k
    return k, finished


def khatma_set_days(cfg, days):
    k = khatma_state(cfg)
    k["days"] = int(days)
    cfg["khatma"] = k
    return k


def khatma_reset(cfg):
    k = khatma_state(cfg)
    k["pages"], k["start"], k["today"], k["today_pages"] = 0, time.strftime("%Y-%m-%d"), "", 0
    cfg["khatma"] = k
    return k


def khatma_text(cfg, ts=None):
    k = khatma_state(cfg)
    today = time.strftime("%Y-%m-%d", time.localtime(ts))
    done_today = k["today_pages"] if k["today"] == today else 0
    daily = khatma_daily(k)
    pct = int(k["pages"] * 100 / float(PAGES))
    j = khatma_juz(k)
    left = max(0, PAGES - k["pages"])
    days_left = int(-(-left // daily)) if daily else 0
    lines = [
        u"هدفك: ختمة كل %d يوماً  (الورد اليومي %d صفحة تقريباً)" % (k["days"], daily),
        u"التقدّم الآن: %d%%  (%d من %d صفحة)" % (pct, k["pages"], PAGES),
        u"أنت الآن عند الجزء %d (%s)" % (j, data.surah_name(extras.juz_surah(j))),
        u"قرأت اليوم: %d من %d صفحة %s" % (min(done_today, daily), daily,
                                          u"- أتممت وردك" if done_today >= daily else u""),
        u"المتبقي لإتمام الختمة: نحو %d يوماً" % days_left,
        u"الختمات المكتملة: %d" % k["count"],
    ]
    return u"\n".join(lines)


# ------------------------------------------------------------------ adhkar (Hisn al-Muslim) & names of Allah
def adhkar_categories():
    """-> [(title, [(text, count)])]  (bundled, works offline)"""
    d = extras._mem("adhkar.json.gz")
    if not d:
        raise ValueError("adhkar data missing")
    return [(c[0], [(t, n) for t, n in c[1]]) for c in d]


def adhkar_blocks(idx):
    cats = adhkar_categories()
    title, arr = cats[idx]
    out = []
    for i, (t, n) in enumerate(arr, 1):
        t = extras.sanitize(t)
        out.append(u"%d) %s" % (i, t))
        if n and int(n) > 1:
            out.append(u"( يُكرَّر %d مرات )" % int(n))
        out.append(u"")
    return title, out


NAMES_99 = [
    u"الله", u"الرحمن", u"الرحيم", u"الملك", u"القدوس", u"السلام", u"المؤمن", u"المهيمن", u"العزيز", u"الجبار",
    u"المتكبر", u"الخالق", u"البارئ", u"المصور", u"الغفار", u"القهار", u"الوهاب", u"الرزاق", u"الفتاح", u"العليم",
    u"القابض", u"الباسط", u"الخافض", u"الرافع", u"المعز", u"المذل", u"السميع", u"البصير", u"الحكم", u"العدل",
    u"اللطيف", u"الخبير", u"الحليم", u"العظيم", u"الغفور", u"الشكور", u"العلي", u"الكبير", u"الحفيظ", u"المقيت",
    u"الحسيب", u"الجليل", u"الكريم", u"الرقيب", u"المجيب", u"الواسع", u"الحكيم", u"الودود", u"المجيد", u"الباعث",
    u"الشهيد", u"الحق", u"الوكيل", u"القوي", u"المتين", u"الولي", u"الحميد", u"المحصي", u"المبدئ", u"المعيد",
    u"المحيي", u"المميت", u"الحي", u"القيوم", u"الواجد", u"الماجد", u"الواحد", u"الصمد", u"القادر",
    u"المقتدر", u"المقدم", u"المؤخر", u"الأول", u"الآخر", u"الظاهر", u"الباطن", u"الوالي", u"المتعالي", u"البر",
    u"التواب", u"المنتقم", u"العفو", u"الرؤوف", u"مالك الملك", u"ذو الجلال والإكرام", u"المقسط", u"الجامع",
    u"الغني", u"المغني", u"المانع", u"الضار", u"النافع", u"النور", u"الهادي", u"البديع", u"الباقي", u"الوارث",
    u"الرشيد", u"الصبور",
]


def names_blocks():
    out = []
    for i, n in enumerate(NAMES_99, 1):
        out.append(u"%d.  %s" % (i, n))
    return out


# ------------------------------------------------------------------ listening statistics
def title_reciter(title):
    title = title or u""
    return (title.split(u" - ", 1)[0] if u" - " in title else title).strip()[:60] or u"-"


def stats_add(cfg, title, secs, ts=None, live=False):
    st = cfg.setdefault("stats", {})
    secs = max(0.0, min(float(secs), 30.0))
    st["total"] = st.get("total", 0.0) + secs
    day = time.strftime("%Y-%m-%d", time.localtime(ts))
    days = st.setdefault("days", {})
    days[day] = days.get(day, 0.0) + secs
    if len(days) > 62:
        for k in sorted(days)[:len(days) - 62]:
            del days[k]
    rec = title_reciter(title)
    rs = st.setdefault("rec", {})
    rs[rec] = rs.get(rec, 0.0) + secs
    if len(rs) > 80:
        for k, _v in sorted(rs.items(), key=lambda kv: kv[1])[:len(rs) - 80]:
            del rs[k]
    return st


def _hm(sec):
    sec = int(sec)
    h, m = sec // 3600, (sec % 3600) // 60
    return u"%d ساعة و%d دقيقة" % (h, m) if h else u"%d دقيقة" % m


def stats_text(cfg, ts=None):
    st = cfg.get("stats") or {}
    if not st.get("total"):
        return u"لا توجد إحصائيات بعد - ابدأ الاستماع وسيُسجَّل الوقت تلقائياً."
    days = st.get("days", {})
    now = ts or time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    week = sum(days.get(time.strftime("%Y-%m-%d", time.localtime(now - i * 86400)), 0) for i in range(7))
    streak = 0
    while days.get(time.strftime("%Y-%m-%d", time.localtime(now - streak * 86400)), 0) >= 60:
        streak += 1
    top = sorted(st.get("rec", {}).items(), key=lambda kv: -kv[1])[:5]
    lines = [u"اليوم: %s" % _hm(days.get(today, 0)),
             u"آخر 7 أيام: %s" % _hm(week),
             u"الإجمالي: %s" % _hm(st["total"]),
             u"أيام متتالية من الاستماع: %d" % streak, u"", u"الأكثر استماعاً:"]
    for i, (n, s) in enumerate(top, 1):
        lines.append(u"%d. %s  (%s)" % (i, n, _hm(s)))
    return u"\n".join(lines)


# ------------------------------------------------------------------ radio bouquet (channel list)
BQ_FILE = "userbouquet.quranhub_radio.radio"
BQ_LINE = '#SERVICE 1:7:2:0:0:0:0:0:0:0:FROM BOUQUET "%s" ORDER BY bouquet' % BQ_FILE


def _enc(url):
    return url.replace("%", "%25").replace(":", "%3a")


def build_bouquet(stations, directory="/etc/enigma2", name=u"القرآن الكريم", bq_file=None):
    """Write a radio bouquet and register it. stations: [(name, url)] - url = http stream or a file
    on the disk; url "" = a title line (marker) in the channel list.  -> number of services"""
    bq_file = bq_file or BQ_FILE
    rows = []
    for n, u in stations:
        if not n:
            continue
        if u == u"":
            rows.append((n, u))
        elif u and (u.lower().startswith("http") or u.startswith("/")) and ".m3u8" not in u.lower():
            rows.append((n, u))
    if not any(u for _n, u in rows):
        raise ValueError("no stations")
    lines = [u"#NAME %s" % name]
    count, mk = 0, 0
    for n, u in rows:
        n = n.replace(u"\n", u" ").replace(u":", u" -").strip()
        if not u:
            mk += 1
            lines.append(u"#SERVICE 1:64:%d:0:0:0:0:0:0:0::%s" % (mk, n))
            lines.append(u"#DESCRIPTION %s" % n)
            continue
        lines.append(u"#SERVICE 4097:0:2:0:0:0:0:0:0:0:%s:%s" % (_enc(u), n))
        lines.append(u"#DESCRIPTION %s" % n)
        count += 1
    with open(os.path.join(directory, bq_file), "wb") as f:
        f.write((u"\n".join(lines) + u"\n").encode("utf-8"))
    reg = os.path.join(directory, "bouquets.radio")
    cur = u""
    if os.path.exists(reg):
        with open(reg, "rb") as f:
            cur = f.read().decode("utf-8", "replace")
    if bq_file not in cur:
        if cur and not cur.endswith(u"\n"):
            cur += u"\n"
        if not cur:
            cur = u"#NAME Radio (TV)\n"
        cur += (u'#SERVICE 1:7:2:0:0:0:0:0:0:0:FROM BOUQUET "%s" ORDER BY bouquet' % bq_file) + u"\n"
        with open(reg, "wb") as f:
            f.write(cur.encode("utf-8"))
    return count


def remove_bouquet(directory="/etc/enigma2", bq_file=None):
    bq_file = bq_file or BQ_FILE
    reg = os.path.join(directory, "bouquets.radio")
    if os.path.exists(reg):
        with open(reg, "rb") as f:
            cur = f.read().decode("utf-8", "replace")
        keep = [l for l in cur.split(u"\n") if bq_file not in l]
        with open(reg, "wb") as f:
            f.write(u"\n".join(keep).encode("utf-8"))
    p = os.path.join(directory, bq_file)
    if os.path.exists(p):
        os.remove(p)
    return True


def bouquet_installed(directory="/etc/enigma2", bq_file=None):
    return os.path.exists(os.path.join(directory, bq_file or BQ_FILE))


FAV_BQ_FILE = "userbouquet.saadquranhub_fav.radio"


# ------------------------------------------------------------------ kids & family mode
KIDS_SURAHS = [1] + list(range(114, 76, -1))          # al-Fatiha then juz amma from the shortest


def kids_state(n):
    """Teacher style: al-Husary (muallim), each ayah 3 times, 5 s to repeat after him."""
    cnt = ayah_counts()[n - 1]
    return {"n": n, "a1": 1, "a2": cnt, "each": 3, "rng": 1, "rec": 2, "src": "everyayah", "gap": 5}


# ------------------------------------------------------------------ memorisation quiz
def quiz_hide(text, level=3, seed=0):
    """Hide every `level`-th word (deterministic, so the same ayah gives the same puzzle).
    -> (puzzle, hidden words)"""
    words = text.split()
    if len(words) < 2:
        return u"……", words
    out, hidden = [], []
    for i, w in enumerate(words):
        if (i + seed) % level == level - 1:
            out.append(u"……")
            hidden.append(w)
        else:
            out.append(w)
    if not hidden:
        out[-1], hidden = u"……", [words[-1]]
    return u" ".join(out), hidden


def quiz_items(n, a1, a2, level=3):
    verses = extras.local_verses(n) or []
    out = []
    for a, t in verses:
        if a1 <= a <= a2:
            t = extras.sanitize(t)
            pz, hid = quiz_hide(t, level, a)
            out.append({"a": a, "text": t, "puzzle": pz, "hidden": hid})
    return out


def quiz_record(cfg, n, a1, a2, right, total, ts=None):
    q = cfg.setdefault("quiz", {})
    key = "%d:%d-%d" % (n, a1, a2)
    pct = int(round(100.0 * right / max(1, total)))
    if pct >= 70:
        star_add(cfg, u"اختبار حفظ %d%%" % pct)
    old = q.get(key, {})
    q[key] = {"best": max(pct, old.get("best", 0)), "last": pct, "times": old.get("times", 0) + 1,
              "ts": int(ts or time.time())}
    return q[key]


def quiz_summary(cfg):
    q = cfg.get("quiz") or {}
    if not q:
        return u"لم تُجرِ أي اختبار بعد."
    rows = []
    for k, v in sorted(q.items(), key=lambda kv: -kv[1].get("ts", 0))[:10]:
        n, rng = k.split(":")
        rows.append(u"سورة %s (%s): آخر نتيجة %d%% • أفضل %d%% • %d مرة" % (
            data.surah_name(int(n)), rng, v["last"], v["best"], v["times"]))
    return u"\n".join(rows)


# ------------------------------------------------------------------ following the recitation (verse highlight)
def ayah_weights(n):
    """Estimated relative duration of each ayah (letters + a pause), with the basmala as ayah 0."""
    verses = extras.local_verses(n) or []
    import unicodedata
    def letters(t):
        return len([c for c in t if unicodedata.category(c).startswith("L")])
    w = [(a, letters(t) + 10) for a, t in verses]
    if n not in (1, 9):
        w.insert(0, (0, 30))          # isti'adha / basmala at the start of most recordings
    return w


def ayah_at(n, frac, offset=0):
    """Ayah being recited at `frac` (0..1) of the surah audio (estimate). offset = manual correction."""
    w = ayah_weights(n)
    if not w:
        return 1
    total = float(sum(x for _a, x in w))
    target, acc, cur = max(0.0, min(1.0, frac)) * total, 0.0, w[0][0]
    for a, x in w:
        cur = a
        acc += x
        if acc >= target:
            break
    cnt = ayah_counts()[n - 1]
    return max(1, min(cnt, (cur or 1) + int(offset)))


# ------------------------------------------------------------------ hijri date (tabular / Kuwaiti algorithm)
HIJRI_MONTHS = [u"محرم", u"صفر", u"ربيع الأول", u"ربيع الآخر", u"جمادى الأولى", u"جمادى الآخرة",
                u"رجب", u"شعبان", u"رمضان", u"شوال", u"ذو القعدة", u"ذو الحجة"]


def hijri(ts=None, adjust=0):
    """-> (year, month, day).  Arithmetic calendar: may differ by a day from the local sighting
    (adjust with `adjust` days)."""
    lt = time.localtime((ts or time.time()) + adjust * 86400)
    y, m, d = lt.tm_year, lt.tm_mon, lt.tm_mday
    if m < 3:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524
    l = jd - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    hm = (24 * l) // 709
    hd = l - (709 * hm) // 24
    hy = 30 * n + j - 30
    return hy, hm, hd


def hijri_text(ts=None, adjust=0):
    y, m, d = hijri(ts, adjust)
    return u"%d %s %d هـ" % (d, HIJRI_MONTHS[m - 1], y)


def ramadan_day(ts=None, adjust=0):
    y, m, d = hijri(ts, adjust)
    return d if m == 9 else 0


# ------------------------------------------------------------------ weekly card
def weekly_text(cfg, ts=None):
    k = khatma_state(cfg)
    lines = [u"ملخص الأسبوع", u"", stats_text(cfg, ts), u"",
             u"الختمة: %d%% • الختمات المكتملة %d" % (int(k["pages"] * 100 / float(PAGES)), k["count"])]
    q = cfg.get("quiz") or {}
    if q:
        lines.append(u"اختبارات الحفظ: %d • متوسط آخر النتائج %d%%" % (
            len(q), int(sum(v["last"] for v in q.values()) / float(len(q)))))
    return u"\n".join(lines)


# ================================================================== Saad Quran Hub 1.3
import json as _json

_META = {}


def meta():
    """Madinah mushaf layout: page starts (604), sajdas, quarter-hizb starts (240)."""
    if not _META:
        p = extras.find_data("meta.json")
        with open(p, "rb") as f:
            _META.update(_json.loads(f.read().decode("utf-8")))
    return _META


def _key(n, a):
    return n * 1000 + a


def page_of(n, a=1):
    starts = meta()["pages"]
    k = _key(n, a)
    lo, hi = 0, len(starts) - 1
    while lo < hi:                                 # last page whose start <= (n, a)
        mid = (lo + hi + 1) // 2
        if _key(*starts[mid]) <= k:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def page_ayahs(page):
    """[(surah, ayah)] printed on that page of the Madinah mushaf."""
    starts = meta()["pages"]
    page = max(1, min(len(starts), int(page)))
    n, a = starts[page - 1]
    end = _key(*starts[page]) if page < len(starts) else _key(115, 1)
    cnt = ayah_counts()
    out = []
    while _key(n, a) < end and n <= 114:
        out.append((n, a))
        a += 1
        if a > cnt[n - 1]:
            n, a = n + 1, 1
    return out


def rub_of(n, a):
    """Quarter-hizb number (1..240) the ayah belongs to."""
    k, r = _key(n, a), 1
    for i, (s, v) in enumerate(meta()["rub"]):
        if _key(s, v) <= k:
            r = i + 1
    return r


def hizb_label(n, a):
    r = rub_of(n, a)
    hizb, q = (r - 1) // 4 + 1, (r - 1) % 4
    return u"الحزب %d%s" % (hizb, (u"", u" (ربع)", u" (نصف)", u" (ثلاثة أرباع)")[q])


def page_blocks(page):
    """Reading blocks for one mushaf page + the (surah, ayah) of each block (None for headers)."""
    sajdas = set(tuple(x) for x in meta()["sajdas"])
    blocks, refs = [], []
    texts = {}
    for n, a in page_ayahs(page):
        if a == 1:
            blocks.append(u"سورة %s\n" % data.surah_name(n))
            refs.append(None)
            if n not in (1, 9):
                blocks.append(extras.BASMALA + u"\n")
                refs.append(None)
        if n not in texts:
            texts[n] = dict(extras.local_verses(n) or [])
        t = extras.sanitize(texts[n].get(a, u""))
        mark = u" ۩" if (n, a) in sajdas else u""
        blocks.append(u"%s (%s)%s" % (t, extras.ar_num(a), mark))
        refs.append((n, a))
    return blocks, refs


# ------------------------------------------------------------------ offline search in the Quran text
def norm_ar(t):
    t = extras.strip_tashkeel(t or u"")
    for a, b in ((u"أ", u"ا"), (u"إ", u"ا"), (u"آ", u"ا"), (u"ٱ", u"ا"), (u"ى", u"ي"), (u"ة", u"ه"),
                 (u"ؤ", u"و"), (u"ئ", u"ي"), (u"ـ", u"")):
        t = t.replace(a, b)
    return u" ".join(t.split())


_SEARCH = []


def search_quran(query, limit=200):
    """-> [(surah, ayah, text)] containing every word of the query (tashkeel and hamza forms ignored)."""
    words = [w for w in norm_ar(query).split() if w]
    if not words:
        return []
    if not _SEARCH:
        q = extras._mem("quran.json.gz")
        for n in range(1, 115):
            for i, t in enumerate(q[str(n)]):
                _SEARCH.append((n, i + 1, t, norm_ar(t)))
    out = []
    for n, a, t, nt in _SEARCH:
        if all(w in nt for w in words):
            out.append((n, a, extras.sanitize(t)))
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------------ one ayah, many reciters
def ayah_all_reciters(n, a, src="everyayah"):
    texts = dict(extras.local_verses(n) or [])
    tx = extras.sanitize(texts.get(a, u""))
    items = []
    for i, (label, _folder, _ed) in enumerate(HIFZ_RECITERS):
        items.append({"title": u"%s - آية %d من سورة %s  ﴿ %s ﴾" % (label, a, data.surah_name(n), tx[:80]),
                      "url": ayah_url(n, a, i, src), "autonext": True, "nohist": True, "ayah": [n, a]})
    if items:
        items[-1]["stop_at_end"] = True
    return items


# ------------------------------------------------------------------ smart review (spaced repetition)
SRS_DAYS = [1, 3, 7, 14, 30, 60]


def _day(ts=None):
    return int((ts or time.time()) // 86400)


def srs_add(cfg, n, a1, a2, ts=None):
    s = cfg.setdefault("srs", {})
    key = "%d:%d-%d" % (n, a1, a2)
    if key not in s:
        s[key] = {"box": 0, "due": _day(ts) + SRS_DAYS[0]}
    return s[key]


def srs_result(cfg, n, a1, a2, pct, ts=None):
    """After a test: >= 80% moves the passage to a longer interval, < 50% back to the start."""
    it = srs_add(cfg, n, a1, a2, ts)
    if pct >= 80:
        it["box"] = min(len(SRS_DAYS) - 1, it["box"] + 1)
    elif pct < 50:
        it["box"] = 0
    it["due"] = _day(ts) + SRS_DAYS[it["box"]]
    it["last"] = int(pct)
    return it


def srs_due(cfg, ts=None):
    """[(key, n, a1, a2, item)] due today or earlier, the most overdue first."""
    today = _day(ts)
    out = []
    for key, it in (cfg.get("srs") or {}).items():
        if it.get("due", 0) <= today:
            n, rng = key.split(":")
            a1, a2 = rng.split("-")
            out.append((key, int(n), int(a1), int(a2), it))
    out.sort(key=lambda x: x[4].get("due", 0))
    return out


def srs_text(cfg, ts=None):
    s = cfg.get("srs") or {}
    due = srs_due(cfg, ts)
    return u"المقاطع في المراجعة: %d  •  المستحق اليوم: %d" % (len(s), len(due))


# ------------------------------------------------------------------ family profiles
PROFILE_KEYS = ("khatma", "quiz", "srs", "stats", "hifz", "reader_pos",
                # 2.0: each person also has own favourites, lists, history, places and stars
                "fav", "pls", "hist", "plays", "spos", "resume", "marks", "mushaf_page", "stars")


def profiles(cfg):
    return cfg.get("profiles") or [u"الأسرة"]


def profile_switch(cfg, name):
    """Keep each person's khatma / tests / review / statistics apart."""
    cur = cfg.get("profile") or profiles(cfg)[0]
    store = cfg.setdefault("pdata", {})
    store[cur] = dict((k, cfg[k]) for k in PROFILE_KEYS if k in cfg)
    for k in PROFILE_KEYS:
        cfg.pop(k, None)
    for k, v in (store.get(name) or {}).items():
        cfg[k] = v
    if name not in profiles(cfg):
        cfg["profiles"] = profiles(cfg) + [name]
    cfg["profile"] = name
    return name


def profile_delete(cfg, name):
    lst = [p for p in profiles(cfg) if p != name]
    if not lst:
        return False
    if (cfg.get("profile") or lst[0]) == name:
        profile_switch(cfg, lst[0])
    cfg["profiles"] = lst
    (cfg.get("pdata") or {}).pop(name, None)
    return True


# ------------------------------------------------------------------ fajr wake-up
def fajr_hm(city_name, ts=None):
    pt = extras.today_prayers(city_name, ts)
    if not pt:
        return None
    return extras.hm(pt["fajr"])


# ------------------------------------------------------------------ credits (shown in the plugin)
CREDITS = [
    u"Saad Quran Hub - إضافة مجانية لأجهزة Enigma2",
    u"",
    u"نص المصحف: مشروع Tanzil (tanzil.net) - يُعرض كما هو دون تعديل",
    u"تقسيم الصفحات والأجزاء والسجدات: fawazahmed0/quran-api (ملكية عامة)",
    u"الترجمة الإنجليزية: Saheeh International عبر QuranEnc.com",
    u"التفاسير: مستودع spa5k/tafsir_api (ترخيص MIT)",
    u"الأذكار: حصن المسلم - مستودع Adhkar-json",
    u"الخط القرآني: مشتق من خط أميري (Amiri) لخالد حسني - ترخيص SIL OFL 1.1",
    u"رسم الحروف كصور (qtext): صور الحروف مقطوعة من خط أميري نفسه - SIL OFL 1.1",
    u"تلوين التجويد: يُستخرج من حروف النص وحركاته لأشهر الأحكام - وسيلة مساعدة، والمرجع مصحف التجويد المطبوع",
    u"مكان نزول السور: بيانات Tanzil (CC BY 3.0)  •  توقيت الكلمات: quran.com",
    u"كود QR: مكتبة QR-Code-generator من Project Nayuki (ترخيص MIT)",
    u"تلاوات الآيات: everyayah.com و cdn.islamic.network",
    u"توقيت الآيات والقراء والإذاعات: mp3quran.net",
    u"المصادر الأخرى: quran.com، quranpedia.net، tvquran.com، ourquraan.com، assabile.com،",
    u"surahquran.com، islamweb.net، way2quran.com، والقنوات العامة على تليجرام.",
    u"الصوت يُشغَّل من مواقعه مباشرة، والبلاجين لا يستضيف أي تلاوة.",
]


# ------------------------------------------------------------------ surah card (1.5)
# m = meccan, d = medinan (Tanzil metadata, CC BY 3.0)
SURAH_TYPE = "mddddmmddmmmdmmmmmmmmdmdmmmmmmmmdmmmmmmmmmmmmmdddmmmmmdmddddddddddmmmmmmmmmdmmmmmmmmmmmmmmmmmmmmmddmmmmmmmmmmdmmmm"


def surah_info(n):
    """Lines of the surah card: where it was revealed, ayahs, words, letters, pages, juz, sajdas."""
    n = max(1, min(114, int(n)))
    rows = extras.local_verses(n) or []
    texts = [r[1] for r in rows]
    words = sum(len(x.split()) for x in texts)
    letters = sum(1 for x in texts for c in x if (0x0621 <= ord(c) <= 0x064A or ord(c) == 0x0671))
    p0 = page_of(n, 1)
    p1 = page_of(n, len(texts)) if texts else p0
    j0, j1 = extras.juz_of(n, 1), extras.juz_of(n, max(1, len(texts)))
    sj = [a for s, a in meta()["sajdas"] if s == n]
    out = [u"سورة %s" % data.surah_name(n),
           u"",
           u"ترتيبها في المصحف: %d" % n,
           u"نزلت: %s" % (u"مكية" if SURAH_TYPE[n - 1] == "m" else u"مدنية"),
           u"عدد آياتها: %d" % len(texts),
           u"عدد كلماتها: %d  •  عدد حروفها: %d" % (words, letters),
           u"الصفحات: %s" % (u"%d" % p0 if p0 == p1 else u"من %d إلى %d" % (p0, p1)),
           u"الجزء: %s" % (u"%d" % j0 if j0 == j1 else u"من %d إلى %d" % (j0, j1)),
           u"%s" % hizb_label(n, 1)]
    if sj:
        out.append(u"فيها سجدة تلاوة: الآية %s" % u"، ".join(str(a) for a in sj))
    if n != 1 and n != 9:
        out += [u"", u"بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"]
    if texts:
        out += [u"", u"أولها: " + u" ".join(texts[0].split()[:8])]
    return out


# ------------------------------------------------------------------ Ramadan + hijri occasions (1.8)
def hijri_adjust(cfg):
    try:
        return max(-2, min(2, int(cfg.get("hijri_adj", 0))))      # the same setting as the reminders menu
    except Exception:
        return 0


def ramadan_today(cfg, ts=None):
    """Day of Ramadan (1..30) or 0, with the user's hijri correction."""
    _y, m, d = hijri(ts, hijri_adjust(cfg))
    return d if m == 9 else 0


def juz_bounds(j):
    """(first (surah, ayah), last (surah, ayah)) of juz j."""
    j = max(1, min(30, int(j)))
    start = extras.JUZ_START[j - 1]
    if j < 30:
        n2, a2 = extras.JUZ_START[j]
        if a2 > 1:
            end = (n2, a2 - 1)
        else:
            end = (n2 - 1, ayah_counts()[n2 - 2])
    else:
        end = (114, ayah_counts()[113])
    return start, end


def juz_items(j, rec=0, src="everyayah"):
    """Every ayah of juz j as a play list (the Ramadan night khatma)."""
    (n1, a1), (n2, a2) = juz_bounds(j)
    label = HIFZ_RECITERS[rec][0]
    items = []
    for n in range(n1, n2 + 1):
        first = a1 if n == n1 else 1
        last = a2 if n == n2 else ayah_counts()[n - 1]
        for a in range(first, last + 1):
            items.append({"title": u"%s - الجزء %d - سورة %s آية %d" % (label, j, data.surah_name(n), a),
                          "url": ayah_url(n, a, rec, src), "autonext": True, "nohist": True, "ayah": [n, a]})
    if items:
        items[-1]["stop_at_end"] = True
    return items


OCCASIONS = {(1, 1): u"رأس السنة الهجرية", (1, 9): u"يوم تاسوعاء", (1, 10): u"يوم عاشوراء",
             (9, 1): u"أول أيام شهر رمضان", (9, 21): u"بداية العشر الأواخر من رمضان",
             (10, 1): u"عيد الفطر المبارك", (12, 1): u"بداية العشر الأوائل من ذي الحجة",
             (12, 9): u"يوم عرفة", (12, 10): u"عيد الأضحى المبارك"}


def occasion_for(ts=None, adjust=0):
    """Occasion of the hijri day containing ts, or None (the white days except in Dhul-Hijjah)."""
    _y, m, d = hijri(ts, adjust)
    if (m, d) in OCCASIONS:
        return OCCASIONS[(m, d)]
    if d == 13 and m != 12:
        return u"بداية الأيام البيض (13 و14 و15 من %s)" % HIJRI_MONTHS[m - 1]
    return None


def wird_passage(cfg, ts=None):
    """The passage to send to the phone today: (surah, a1, a2, why) - due review first, else the
    memorisation range of the studio."""
    due = srs_due(cfg, ts)
    if due:
        _k, n, a1, a2, _it = due[0]
        return n, a1, a2, u"مراجعة اليوم"
    st = hifz_state(cfg)
    return st["n"], st["a1"], st["a2"], u"ورد الحفظ"


# ------------------------------------------------------------------ 2.0: stars (children) and the harvest
def star_add(cfg, why=u"", n=1, ts=None):
    st = cfg.setdefault("stars", {"n": 0, "log": []})
    st["n"] = int(st.get("n", 0)) + n
    st.setdefault("log", []).insert(0, [int(ts or time.time()), why])
    del st["log"][30:]
    return st["n"]


def stars_of(cfg):
    """-> [(profile, stars)] of every person."""
    cur = cfg.get("profile") or profiles(cfg)[0]
    out = []
    for p_ in profiles(cfg):
        st = cfg.get("stars") if p_ == cur else ((cfg.get("pdata") or {}).get(p_) or {}).get("stars")
        out.append((p_, int((st or {}).get("n", 0))))
    return out


def stars_text(cfg):
    st = cfg.get("stars") or {}
    n = int(st.get("n", 0))
    lines = [u"⭐ " * min(n, 10) + (u"(%d)" % n if n > 10 else u""), u"عدد النجوم: %d" % n, u""]
    for t, why in (st.get("log") or [])[:8]:
        lines.append(u"• %s  %s" % (time.strftime("%m-%d", time.localtime(t)), why))
    if not st.get("log"):
        lines.append(u"النجوم تأتي من: إتمام سورة في وضع الأطفال، والورد اليومي، واختبار الحفظ بنتيجة 70% فأكثر")
    return u"\n".join(lines)


def harvest(cfg, period="month", ts=None):
    """-> dict of the listening of this month / this year (from the daily statistics)."""
    now = ts or time.time()
    lt = time.localtime(now)
    pre = time.strftime("%Y-%m" if period == "month" else "%Y", lt)
    st = cfg.get("stats") or {}
    days = dict((d, s) for d, s in (st.get("days") or {}).items() if d.startswith(pre))
    q = cfg.get("quiz") or {}
    t0 = time.mktime((lt.tm_year, lt.tm_mon if period == "month" else 1, 1, 0, 0, 0, 0, 0, -1))
    quizzes = [v for v in q.values() if v.get("ts", 0) >= t0]
    k = cfg.get("khatma") or {}
    stars = [x for x in ((cfg.get("stars") or {}).get("log") or []) if x[0] >= t0]
    return {"pre": pre, "secs": sum(days.values()), "days": len([1 for s in days.values() if s >= 60]),
            "best": max(days.items(), key=lambda kv: kv[1]) if days else None,
            "quizzes": len(quizzes), "quiz_avg": int(sum(v.get("last", 0) for v in quizzes) / len(quizzes)) if quizzes else 0,
            "khatmas": int(k.get("count", 0)), "khatma_pct": int(k.get("pages", 0) * 100 / float(PAGES)) if k else 0,
            "stars": len(stars), "top": sorted((st.get("rec") or {}).items(), key=lambda kv: -kv[1])[:3]}


def harvest_text(cfg, period="month", ts=None):
    h = harvest(cfg, period, ts)
    title = u"حصاد الشهر %s" % h["pre"] if period == "month" else u"حصاد السنة %s" % h["pre"]
    lines = [u"🌾 " + title, u"",
             u"وقت الاستماع: %s" % _hm(h["secs"]),
             u"أيام الاستماع (دقيقة فأكثر): %d" % h["days"]]
    if h["best"]:
        lines.append(u"أفضل يوم: %s (%s)" % (h["best"][0], _hm(h["best"][1])))
    lines += [u"الختمة الحالية: %d%%  •  الختمات المكتملة: %d" % (h["khatma_pct"], h["khatmas"]),
              u"اختبارات الحفظ: %d%s" % (h["quizzes"], (u"  •  المتوسط %d%%" % h["quiz_avg"]) if h["quizzes"] else u""),
              u"النجوم: %d" % h["stars"]]
    if h["top"]:
        lines += [u"", u"أكثر القراء استماعاً (الإجمالي):"] + [u"%d. %s" % (i, n) for i, (n, _s) in enumerate(h["top"], 1)]
    return u"\n".join(lines)


# ------------------------------------------------------------------ 2.1: juz of an ayah, translation & tafsir audio
def juz_of(n, a=1):
    k = _key(n, a)
    j = 1
    for i, (s, v) in enumerate(extras.JUZ_START):
        if _key(s, v) <= k:
            j = i + 1
    return j


# label, alquran.cloud audio edition (ayah by ayah)
TRANSLATION_AUDIO = [
    (u"English - Ibrahim Walk (Saheeh International)", "en.walk"),
    (u"اردو - شمشاد علی خان", "ur.khan"),
    (u"Français - Youssouf Leclerc", "fr.leclerc"),
]
ALQ_SURAH = "https://api.alquran.cloud/v1/surah/%d/%s"


def translation_audio_urls(n, edition):
    """-> {ayah: audio url} of a translation, read from alquran.cloud (kept on the disk for good)."""
    d = data.cached_json(ALQ_SURAH % (n, edition), "timing_tr_%s_%d.json" % (edition, n))
    out = {}
    for x in ((d or {}).get("data") or {}).get("ayahs") or []:
        u = x.get("audio") or (x.get("audioSecondary") or [None])[0]
        if u:
            out[int(x.get("numberInSurah"))] = u
    if not out:
        raise IOError(u"لا توجد ترجمة صوتية لهذه السورة")
    return out


def translation_items(n, rec, edition, a1=1, a2=None):
    """Arabic ayah, then its translation, for every ayah (rec = HIFZ_RECITERS index)."""
    tr = translation_audio_urls(n, edition)
    a2 = a2 or ayah_counts()[n - 1]
    lab = dict((e, l) for l, e in TRANSLATION_AUDIO).get(edition, edition)
    items = []
    for a in range(a1, a2 + 1):
        items.append({"title": u"%s - سورة %s آية %d" % (HIFZ_RECITERS[rec][0], data.surah_name(n), a),
                      "url": ayah_url(n, a, rec), "autonext": True, "nohist": True, "ayah": [n, a]})
        if a in tr:
            items.append({"title": u"%s - %d" % (lab, a), "url": tr[a], "autonext": True, "nohist": True,
                          "ayah": [n, a]})
    if items:
        items[-1]["stop_at_end"] = True
    return items


TAFSIR_AUDIO_API = ["https://mp3quran.net/api/v3/tafsir?tafsir=1&language=ar",
                    "https://www.mp3quran.net/api/v3/tafsir?tafsir=1&language=ar"]


def _walk_urls(x, out):
    if isinstance(x, dict):
        u = x.get("url")
        s = x.get("sura_id") or x.get("surah_id") or x.get("sura")
        if u and s and str(u).startswith("http"):
            out.append((int(s), x.get("name") or u"", u))
        for v in x.values():
            _walk_urls(v, out)
    elif isinstance(x, list):
        for v in x:
            _walk_urls(v, out)


def tafsir_audio(n=None):
    """-> [(surah, part name, url)] of the audio tafsir (al-Muyassar, mp3quran.net)."""
    d = data.cached_json(TAFSIR_AUDIO_API, "tafsir_audio_1.json")
    out = []
    _walk_urls(d, out)
    out.sort(key=lambda x: (x[0], x[2]))
    if n:
        out = [x for x in out if x[0] == int(n)]
    if not out:
        raise IOError(u"التفسير الصوتي غير متاح الآن")
    return out


# ------------------------------------------------------------------ 2.1: ready lists shared on GitHub
LISTS_BASE = "https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main/lists/"


def shared_lists():
    """-> [{"id", "name", "desc", "file", "count"}] (index of the developer's lists)."""
    d = data.cached_json(LISTS_BASE + "index.json", "lists_index.json")
    return [x for x in (d or {}).get("lists", []) if x.get("file")]


def shared_list(entry):
    """-> [play items] of one shared list.  An item is {"title", "url"} or {"title", "server", "n"}
    (whole surah from an mp3quran folder) or {"title", "ea": everyayah folder, "n"} (ayah by ayah)."""
    d = data.cached_json(LISTS_BASE + entry["file"], "list_%s.json" % entry.get("id", "x"))
    items = []
    for x in (d or {}).get("items", []):
        if x.get("url"):
            items.append({"title": x.get("title") or x["url"], "url": x["url"], "autonext": True})
        elif x.get("server") and x.get("n"):
            items.append({"title": x.get("title") or data.surah_name(int(x["n"])),
                          "url": "%s%03d.mp3" % (x["server"], int(x["n"])), "autonext": True})
        elif x.get("ea") and x.get("n"):
            n = int(x["n"])
            for a in range(1, ayah_counts()[n - 1] + 1):
                items.append({"title": u"%s - %d" % (x.get("title") or data.surah_name(n), a),
                              "url": EVERYAYAH % (x["ea"], n, a), "autonext": True, "nohist": True, "ayah": [n, a]})
    return items
