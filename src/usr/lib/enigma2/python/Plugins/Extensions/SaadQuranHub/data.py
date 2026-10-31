# -*- coding: utf-8 -*-
"""Data layer for QuranHub (no enigma2 imports, so it can be tested anywhere).

Sources
  * mp3quran.net      -> https://mp3quran.net/api/v3/reciters | radios
  * quran.com         -> https://api.quran.com/api/v4/...
  * surahquran.com    -> scraped from its HTML pages (best effort)
"""
from __future__ import print_function

import json
import os
import re
import ssl
import time
import threading

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urljoin
except ImportError:  # python2 images
    from urllib2 import Request, urlopen
    from urlparse import urljoin

UA = "Mozilla/5.0 (X11; Linux armv7l) QuranHub/1.0"
CACHE_DIR = "/tmp/quranhub"
CACHE_TTL = 24 * 3600

MP3Q_RECITERS = ["https://mp3quran.net/api/v3/reciters?language=ar",
                 "https://www.mp3quran.net/api/v3/reciters?language=ar",
                 "http://mp3quran.net/api/v3/reciters?language=ar"]
MP3Q_RADIOS = ["https://mp3quran.net/api/v3/radios?language=ar",
               "https://www.mp3quran.net/api/v3/radios?language=ar",
               "http://mp3quran.net/api/v3/radios?language=ar"]
QCOM_RECITATIONS = "https://api.quran.com/api/v4/resources/recitations?language=ar"
QCOM_CHAPTER = "https://api.quran.com/api/v4/chapter_recitations/%s/%s"
QCOM_MEDIA_BASE = "https://verses.quran.com/"


def quran_com_timing(rid, n):
    """quran.com: [(ayah, from_ms, to_ms, [(word, from_ms, to_ms)])] of one surah recording
    (the same file that quran_com_audio plays)."""
    js = cached_json((QCOM_CHAPTER % (rid, n)) + "?segments=true", "qcom_seg_%s_%s.json" % (rid, n))
    out = []
    for t in (js.get("audio_file") or {}).get("timestamps") or []:
        try:
            a = int(str(t["verse_key"]).split(":")[1])
            segs = [(int(s[0]), int(s[1]), int(s[2])) for s in (t.get("segments") or []) if len(s) >= 3]
            out.append((a, int(t["timestamp_from"]), int(t["timestamp_to"]), segs))
        except Exception:
            continue
    return out


def word_from_timing(tl, ms):
    """(ayah, word number or 0) at a position in ms, from quran_com_timing()."""
    cur = None
    for a, t0, t1, segs in tl:
        if ms < t0:
            break
        cur = (a, 0)
        if ms <= t1:
            w = 0
            for wi, s0, s1 in segs:
                if s0 <= ms:
                    w = wi
                if ms < s1:
                    break
            return a, w
    return cur
SQ_BASE = "https://surahquran.com/"

SURAHS = [
    "الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام", "الأعراف",
    "الأنفال", "التوبة", "يونس", "هود", "يوسف", "الرعد", "إبراهيم", "الحجر",
    "النحل", "الإسراء", "الكهف", "مريم", "طه", "الأنبياء", "الحج", "المؤمنون",
    "النور", "الفرقان", "الشعراء", "النمل", "القصص", "العنكبوت", "الروم",
    "لقمان", "السجدة", "الأحزاب", "سبأ", "فاطر", "يس", "الصافات", "ص", "الزمر",
    "غافر", "فصلت", "الشورى", "الزخرف", "الدخان", "الجاثية", "الأحقاف", "محمد",
    "الفتح", "الحجرات", "ق", "الذاريات", "الطور", "النجم", "القمر", "الرحمن",
    "الواقعة", "الحديد", "المجادلة", "الحشر", "الممتحنة", "الصف", "الجمعة",
    "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك", "القلم", "الحاقة",
    "المعارج", "نوح", "الجن", "المزمل", "المدثر", "القيامة", "الإنسان",
    "المرسلات", "النبأ", "النازعات", "عبس", "التكوير", "الانفطار", "المطففين",
    "الانشقاق", "البروج", "الطارق", "الأعلى", "الغاشية", "الفجر", "البلد",
    "الشمس", "الليل", "الضحى", "الشرح", "التين", "العلق", "القدر", "البينة",
    "الزلزلة", "العاديات", "القارعة", "التكاثر", "العصر", "الهمزة", "الفيل",
    "قريش", "الماعون", "الكوثر", "الكافرون", "النصر", "المسد", "الإخلاص",
    "الفلق", "الناس",
]

STYLE_AR = {"Mujawwad": "مجوّد", "Murattal": "مرتل", "Muallim": "المعلم"}

# Radio pages listed on surahquran.com/Radio-Quran-Cairo.html
SQ_RADIOS = [
    ("إذاعة القرآن الكريم - القاهرة", "Radio-Quran-Cairo.html"),
    ("إذاعة القرآن الكريم - السعودية (مكة)", "Radio-Quran-Saudi.html"),
    ("إذاعة القرآن الكريم - الجزائر", "Radio-Quran-Algeria.html"),
    ("إذاعة القرآن الكريم - المغرب", "Radio-Quran-Morocco.html"),
    ("إذاعة الرقية الشرعية", "Radio-Quran-UAE.html"),
    ("Quran Radio - English", "Radio-Quran-USA.html"),
    ("قناة السنة النبوية - المدينة المنورة", "Radio-Quran-noor.html"),
    ("إذاعة تلاوات خاشعة", "Radio-Quran-Khashia.html"),
    ("تلاوات متنوعة لمختلف القراء", "Radio-Quran-Mix.html"),
    ("إذاعة عبدالرحمن السديس", "Radio-Quran-Sudais.html"),
    ("إذاعة ياسر الدوسري", "Radio-Quran-Dosari.html"),
    ("إذاعة مشاري العفاسي", "Radio-Quran-Afasi.html"),
    ("إذاعة عبدالباسط عبدالصمد (مجوّد)", "Radio-Quran-Abdulbasit.html"),
    ("إذاعة سورة البقرة لعدد من القراء", "Radio-Quran-Baqarah.html"),
    ("إذاعة تفسير القرآن الكريم", "Radio-Quran-Tafseer.html"),
    ("إذاعة القرآن الكريم - قطر 103.4", "Radio-Quran-Qatar.html"),
    ("إذاعة القرآن الكريم - قطر 106", "Radio-Quran-Qatar106.html"),
    ("إذاعة القرآن الكريم - البحرين", "Radio-Quran-Bahrain.html"),
    ("إذاعة القرآن الكريم - الأردن", "Radio-Quran-Jordan.html"),
    ("إذاعة القرآن الكريم - الكويت", "Radio-Quran-Kuwait.html"),
    ("إذاعة القرآن الكريم - عُمان", "Radio-Quran-Oman.html"),
    ("إذاعة القرآن الكريم - باكستان", "Radio-Quran-Pakistan.html"),
    ("إذاعة القرآن الكريم - فلسطين (نابلس)", "Radio-Quran-Palestine.html"),
    ("إذاعة الشارقة للقرآن الكريم", "Radio-Quran-Sharjah.html"),
]
# Stream URLs that were read directly from the pages (no scraping needed)
SQ_RADIO_KNOWN = {
    "Radio-Quran-Cairo.html": "https://stream.radiojar.com/8s5u5tpdtwzuv",
}


# ----------------------------------------------------------------- network
def _contexts():
    out = []
    try:
        out.append(ssl.create_default_context())
    except Exception:
        out.append(None)
    try:
        c = ssl._create_unverified_context()  # old images lack CA bundles
        out.append(c)
    except Exception:
        pass
    return out


def http_get(url, timeout=15):
    last = None
    for ctx in _contexts():
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            kw = {"timeout": timeout}
            if ctx is not None:
                kw["context"] = ctx
            return urlopen(req, **kw).read()
        except Exception as e:  # try the next context
            last = e
    raise last


def http_text(url, timeout=15):
    raw = http_get(url, timeout)
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("utf-8", "ignore")


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def cached_json(url, name):
    """`url` may be one URL or a list of mirrors that are tried in order."""
    urls = list(url) if isinstance(url, (list, tuple)) else [url]
    path = _cache_path(name)
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path) < CACHE_TTL)
    if fresh:
        try:
            with open(path, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
        except Exception:
            pass
    got, last = None, None
    for u in urls:
        try:
            got = json.loads(http_text(u, 25))
            break
        except Exception as e:
            last = e
    if got is None:
        if os.path.exists(path):  # stale cache beats nothing
            with open(path, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
        raise last
    try:
        if not os.path.isdir(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        with open(path, "wb") as f:
            f.write(json.dumps(got).encode("utf-8"))
    except Exception:
        pass
    return got


def cached_text(url, name):
    path = _cache_path(name)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path) < CACHE_TTL):
        try:
            with open(path, "rb") as f:
                return f.read().decode("utf-8", "ignore")
        except Exception:
            pass
    text = http_text(url, 20)
    try:
        if not os.path.isdir(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        with open(path, "wb") as f:
            f.write(text.encode("utf-8"))
    except Exception:
        pass
    return text


# ----------------------------------------------------------------- helpers
_DIAC = re.compile(u"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def norm(text):
    """Normalise Arabic for searching."""
    t = _DIAC.sub(u"", text or u"")
    for a, b in ((u"أ", u"ا"), (u"إ", u"ا"), (u"آ", u"ا"), (u"ة", u"ه"),
                 (u"ى", u"ي"), (u"ؤ", u"و"), (u"ئ", u"ي")):
        t = t.replace(a, b)
    return t.lower().strip()


def surah_name(n):
    return SURAHS[n - 1] if 1 <= n <= 114 else str(n)


def surah_label(n):
    return u"%03d - %s" % (n, surah_name(n))


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


# ----------------------------------------------------------------- mp3quran
def _mp3q_offline():
    """Built-in copy of the mp3quran reciter list (English names) - used only when the API is down."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qdata", "mp3q_offline.json")
    with open(p, "rb") as f:
        rows = json.loads(f.read().decode("utf-8"))
    out = []
    for rid, name, recit, server, total in rows:
        if not server:
            continue
        if not server.endswith("/"):
            server += "/"
        out.append({"name": u"%s (نسخة احتياطية)" % name,
                    "moshaf": [{"name": recit, "server": server, "surahs": list(range(1, 115))}]})
    out.sort(key=lambda x: norm(x["name"]))
    return out


def mp3quran_reciters():
    """-> [{'name', 'moshaf': [{'name', 'server', 'surahs': [int]}]}]  (falls back to the built-in list)"""
    try:
        data = cached_json(MP3Q_RECITERS, "mp3q_reciters.json")
    except Exception:
        return _mp3q_offline()
    out = []
    for r in data.get("reciters", []):
        moshafs = []
        for m in r.get("moshaf", []):
            server = m.get("server") or ""
            if not server:
                continue
            if not server.endswith("/"):
                server += "/"
            surahs = [int(x) for x in str(m.get("surah_list", "")).split(",")
                      if x.strip().isdigit()]
            if not surahs:
                continue
            moshafs.append({"name": m.get("name", ""), "server": server,
                            "surahs": surahs})
        if moshafs:
            out.append({"name": r.get("name", ""), "moshaf": moshafs})
    if not out:
        return _mp3q_offline()
    out.sort(key=lambda x: norm(x["name"]))
    return out


# automatic fallback audio: whole-surah mp3 from cdn.islamic.network (keyword in the reciter's name -> edition)
ALT_EDITIONS = [
    (u"العفاسي", "ar.alafasy"), (u"عبد الباسط", "ar.abdulbasitmurattal"), (u"عبدالباسط", "ar.abdulbasitmurattal"),
    (u"المنشاوي", "ar.muhammadsiddiqalminshawimujawwad"), (u"الحذيفي", "ar.aliabdurrahmanalhuthaify"),
    (u"العجمي", "ar.ahmedalajmi"), (u"الشريم", "ar.saudalshuraim"), (u"القطامي", "ar.nasseralqatami"),
    (u"الدوسري", "ar.yasseraldossari"), (u"الأخضر", "ar.ibrahimalakhdar"), (u"الجهني", "ar.abdullahawadaljuhani"),
    (u"خياط", "ar.abdullahkhayat"), (u"شخاشيرو", "ar.mahershakhashiro"), (u"هاني الرفاعي", "ar.haniarrifai"),
    (u"الجليل", "ar.khalidaljalil"), (u"المطرود", "ar.abdullahmatrood"), (u"بليلة", "ar.bandarbalila"),
    (u"أيوب", "ar.muhammadayyub"), (u"الصايغ", "ar.tawfeeqassayegh"), (u"مصطفى إسماعيل", "ar.mustafaismail"),
    (u"فارس عباد", "ar.faresabbad"), (u"النائحي", "ar.waleednaehi"), (u"البصفر", "ar.abdullahbasfar"),
    (u"القحطاني", "ar.khaledalqahtani"), (u"القاسم", "ar.abdulmuhsinalqasim"), (u"البدير", "ar.salahalbudair"),
    (u"الزهراني", "ar.abdulazizazzahrani"), (u"اللحيدان", "ar.muhammadalluhaidan"), (u"هزاع", "ar.alafasy"),
    (u"Alafasy", "ar.alafasy"), (u"Afasy", "ar.alafasy"), (u"Abdul Basit", "ar.abdulbasitmurattal"),
    (u"Minshawi", "ar.muhammadsiddiqalminshawimujawwad"), (u"Hudhaify", "ar.aliabdurrahmanalhuthaify"),
    (u"Ajmi", "ar.ahmedalajmi"), (u"Shuraim", "ar.saudalshuraim"), (u"Dossari", "ar.yasseraldossari"),
    (u"Akdar", "ar.ibrahimalakhdar"),
]
ALT_DEFAULT = "ar.alafasy"
ALT_URL = "https://cdn.islamic.network/quran/audio-surah/128/%s/%d.mp3"


def alt_surah_url(reciter_name, n):
    """-> (url, label) of the same reciter on another site, or a default reciter when unknown."""
    nm = reciter_name or u""
    for kw, ed in ALT_EDITIONS:
        if kw in nm:
            return ALT_URL % (ed, n), kw
    return ALT_URL % (ALT_DEFAULT, n), None


def mp3quran_surah_url(server, n):
    return "%s%03d.mp3" % (server, n)


def mp3quran_radios():
    """-> [(name, url)]"""
    data = cached_json(MP3Q_RADIOS, "mp3q_radios.json")
    out = []
    for r in data.get("radios", []):
        url = (r.get("url") or "").strip()
        name = (r.get("name") or "").strip().strip("-*").strip()
        if url and name:
            out.append((name, url))
    return out


# ----------------------------------------------------------------- quran.com
def quran_com_reciters():
    """-> [(label, recitation_id)]"""
    data = cached_json(QCOM_RECITATIONS, "qcom_recitations.json")
    out = []
    for r in data.get("recitations", []):
        tn = r.get("translated_name") or {}
        name = tn.get("name") or r.get("reciter_name") or ""
        style = r.get("style")
        if style:
            name = u"%s - %s" % (name, STYLE_AR.get(style, style))
        out.append((name, r.get("id")))
    out.sort(key=lambda x: norm(x[0]))
    return out


def quran_com_audio(recitation_id, chapter):
    data = json.loads(http_text(QCOM_CHAPTER % (recitation_id, chapter), 20))
    url = (data.get("audio_file") or {}).get("audio_url")
    if not url:
        raise ValueError("no audio_url")
    if not url.startswith("http"):
        url = urljoin(QCOM_MEDIA_BASE, url.lstrip("/"))
    return url


# ----------------------------------------------------------------- surahquran
_BAD_HOSTS = ("pinimg", "surahquran.com", "colorlib", "google", "gstatic",
              "w3.org", "schema.org", "facebook", "twitter", "youtube",
              "cloudflare", "jquery", "bootstrapcdn", "fontawesome", "fonts.")
_STREAMISH = re.compile(r"(radiojar|stream|\.m3u8|\.mp3|\.aac|\.pls|/live|icecast|"
                        r"shoutcast|:\d{4}/|listen|radio)", re.I)
_URL = re.compile(r"""https?://[^\s"'<>\)\]\\]+""")


def _clean_url(u):
    return u.rstrip(".,;")


def find_stream(html):
    """Pick the most likely live-stream URL out of a page."""
    urls = [_clean_url(u) for u in _URL.findall(html)]
    urls = [u for u in urls if not any(b in u.lower() for b in _BAD_HOSTS)]
    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    for u in uniq:
        if _STREAMISH.search(u):
            return u
    return None


def surahquran_radio_url(page):
    if page in SQ_RADIO_KNOWN:
        return SQ_RADIO_KNOWN[page]
    html = cached_text(SQ_BASE + page, "sq_" + page)
    url = find_stream(html)
    if not url:
        raise ValueError("stream not found on " + page)
    return url


SQ_RECITERS_FALLBACK = [
    (u"أئمة الحرم", "https://surahquran.com/mp3/Imams-alharam"),
    (u"أحمد الحذيفي", "https://surahquran.com/mp3/Ahmed-Al-Huthifi"),
    (u"أحمد ديبان", "https://surahquran.com/mp3/Ahmed-Deban"),
    (u"أحمد الطرابلسي", "https://surahquran.com/mp3/Ahmed-Trabelsi"),
    (u"أحمد بن علي العجمي", "https://surahquran.com/mp3/Al-Ajmy"),
    (u"أحمد طالب حميد", "https://surahquran.com/mp3/Ahmed-Talib"),
    (u"أحمد محمد طاهر", "https://surahquran.com/mp3/Ahmed-Mohamed-Taher-Sudanese"),
    (u"أحمد خليل شاهين", "https://surahquran.com/mp3/shahin"),
    (u"أحمد عيسى المعصراوي", "https://surahquran.com/mp3/maasarawy"),
    (u"أحمد اللحدان", "https://surahquran.com/mp3/ahmad-allahdan"),
    (u"أحمد النفيس", "https://surahquran.com/mp3/Ahmad-Alnufais"),
    (u"أحمد نعينع", "https://surahquran.com/mp3/Ahmad_Naene"),
    (u"أحمد نصر", "https://surahquran.com/mp3/Ahmed-Nasr"),
    (u"أحمد محمد عامر", "https://surahquran.com/mp3/ahmad-aamer"),
    (u"أحمد السعيد مندور", "https://surahquran.com/quran-mp3-qari-38.html"),
    (u"أحمد الشافعي", "https://surahquran.com/quran-mp3-qari-14.html"),
    (u"أحمد خضر", "https://surahquran.com/quran-mp3-qari-11.html"),
    (u"أحمد كاسب", "https://surahquran.com/mp3/Ahmed-Kasib/"),
    (u"إبراهيم الأخضر", "https://surahquran.com/mp3/alakhdar"),
    (u"ابراهيم الجبرين", "https://surahquran.com/quran-mp3-qari-5.html"),
    (u"ابراهيم العسيري", "https://surahquran.com/mp3/Ibrahim-al-Asiri"),
    (u"إدريس أبكر", "https://surahquran.com/mp3/Idris-Abkar"),
    (u"أدهم النابلسي", "https://surahquran.com/quran-mp3-qari-34.html"),
    (u"إسحاق دانيش", "https://surahquran.com/mp3/ishak-danish"),
    (u"إسلام صبحي", "https://surahquran.com/quran-mp3-qari-1.html"),
    (u"أكرم العلاقمي", "https://surahquran.com/mp3/akram-alaqimi"),
    (u"إلهان توك", "https://surahquran.com/mp3/Ilhan-Tok"),
    (u"أنس براق", "https://surahquran.com/quran-mp3-qari-39.html"),
    (u"أنس جلهوم", "https://surahquran.com/mp3/anas"),
    (u"أنس العمادي", "https://surahquran.com/mp3/Anas-alemadi"),
    (u"أنس الميمان", "https://surahquran.com/mp3/Anas-Almiman"),
    (u"أنس محمد", "https://surahquran.com/quran-mp3-qari-37.html"),
    (u"الياس حجري", "https://surahquran.com/quran-mp3-qari-18.html"),
    (u"الأمين محمد قنيوة", "https://surahquran.com/mp3/Amin-Quniwa"),
    (u"أيمن سويد", "https://surahquran.com/mp3/Ayman-Roshdy-Sweed"),
    (u"بندر بليله", "https://surahquran.com/mp3/balilah"),
    (u"بدر محمد التركي", "https://surahquran.com/mp3/badr-alturki"),
    (u"بيشه وا قادر الكردي", "https://surahquran.com/mp3/peshawa"),
    (u"توفيق الصايغ", "https://surahquran.com/mp3/Tawfeeq-As-Sayegh"),
    (u"تميم الريمي", "https://surahquran.com/mp3/Tamim-Al-Rimi"),
    (u"عبدالله عواد الجهني", "https://surahquran.com/mp3/Al-Johany"),
    (u"جزاع الصويلح", "https://surahquran.com/mp3/Jazza-Alswaileh"),
    (u"حاتم فريد الواعر", "https://surahquran.com/mp3/hatem"),
    (u"حازم سيف", "https://surahquran.com/quran-mp3-qari-8.html"),
    (u"حجاج الهنداوي", "https://surahquran.com/mp3/Hindawi"),
    (u"حمزة الجزائري", "https://surahquran.com/mp3/Hamza-Aljazairi"),
    (u"حمزة الفار", "https://surahquran.com/mp3/Hamza-El-Far"),
    (u"حسام الدين عبادي", "https://surahquran.com/quran-mp3-qari-28.html"),
    (u"حسن محمد صالح", "https://surahquran.com/mp3/Hassan-Saleh"),
    (u"حسن صالح ورش", "https://surahquran.com/mp3/Hassan-Saleh-Warsh"),
    (u"حسن الواجدي", "https://surahquran.com/mp3/Hassan-Al-waajidi"),
    (u"الحسيني العزازي", "https://surahquran.com/mp3/Husseini-Azazi"),
    (u"حمزة بوديب", "https://surahquran.com/quran-mp3-qari-24.html"),
    (u"خالد الجليل", "https://surahquran.com/mp3/aljalil"),
    (u"خالد القحطاني", "https://surahquran.com/mp3/Al-Qahtani"),
    (u"خالد عبدالكافي", "https://surahquran.com/mp3/abdulkafi"),
    (u"خالد المهنا", "https://surahquran.com/mp3/Almohanna"),
    (u"خليفة الطنيجي", "https://surahquran.com/mp3/khalifa"),
    (u"الحافظ خليل اسماعيل", "https://surahquran.com/mp3/Hafiz-Khalil-Ismail/"),
    (u"خليل الصغير", "https://surahquran.com/mp3/khalil-alsaghir"),
    (u"داوود حمزة", "https://surahquran.com/mp3/Daoud-Hamza"),
    (u"الدوكالي محمد العالم", "https://surahquran.com/mp3/doukkali"),
    (u"رعد محمد الكردي", "https://surahquran.com/mp3/kordy"),
    (u"رشيد بلعالية", "https://surahquran.com/mp3/Rachid-Belalia"),
    (u"رشيد بلعشية", "https://surahquran.com/mp3/Rachid-Belachia"),
    (u"رزكار محمد", "https://surahquran.com/quran-mp3-qari-35.html"),
    (u"ريان المحيسني", "https://surahquran.com/mp3/Rayyan-Al-Muhaisni/"),
    (u"زكي داغستاني", "https://surahquran.com/mp3/zaki"),
    (u"الزين محمد أحمد", "https://surahquran.com/mp3/zain"),
    (u"سالم الرويلي", "https://surahquran.com/quran-mp3-qari-27.html"),
    (u"سعد الغامدي", "https://surahquran.com/mp3/Al-Ghamdi"),
    (u"سعود الشريم", "https://surahquran.com/mp3/Al-Shuraim"),
    (u"سعيد الخطيب", "https://surahquran.com/mp3/Alkhateeb"),
    (u"سهل ياسين", "https://surahquran.com/mp3/Sahl-Yassin"),
    (u"سلمان العتيبي", "https://surahquran.com/quran-mp3-qari-4.html"),
    (u"سلمان المطيري", "https://surahquran.com/mp3/Salman-Mutairi/"),
    (u"سيد متولي عبدالعال", "https://surahquran.com/quran-mp3-qari-17.html"),
    (u"سيد سعيد", "https://surahquran.com/quran-mp3-qari-7.html"),
    (u"الشحات محمد أنور", "https://surahquran.com/mp3/Alshahat_M_Anwar"),
    (u"شعبان الصياد", "https://surahquran.com/mp3/Shaaban-AlSayyad"),
    (u"شريف مصطفى", "https://surahquran.com/quran-mp3-qari-15.html"),
    (u"شيخ أبو بكر الشاطري", "https://surahquran.com/mp3/Shatri"),
    (u"شيرزاد عبدالرحمن طاهر", "https://surahquran.com/mp3/Shirazad-Taher"),
    (u"صالح الصاهود", "https://surahquran.com/mp3/Alsahood"),
    (u"صالح الأنصاري", "https://surahquran.com/quran-mp3-qari-26.html"),
    (u"صالح أحمد صالح", "https://surahquran.com/mp3/Salih-Ahmed-Salih"),
    (u"صدقات الباكستاني", "https://surahquran.com/mp3/Sadaqat_Ali"),
    (u"صلاح البدير", "https://surahquran.com/mp3/Salah-Albudair"),
    (u"صلاح الباجي", "https://surahquran.com/quran-mp3-qari-41.html"),
    (u"صلاح بو خاطر", "https://surahquran.com/mp3/Bukhatir"),
    (u"صلاح الجمل", "https://surahquran.com/mp3/Salah-Jamal"),
    (u"صلاح الهاشم", "https://surahquran.com/mp3/Alhashem"),
    (u"صلاح باعثمان", "https://surahquran.com/mp3/Salah-Baothman"),
    (u"عبدالرشيد صوفي", "https://surahquran.com/mp3/soufi"),
    (u"طارق محمد", "https://surahquran.com/quran-mp3-qari-23.html"),
    (u"محمد الطبلاوي", "https://surahquran.com/mp3/Tablawi"),
    (u"عمار الملا علي", "https://surahquran.com/mp3/Ammar-Almulla/"),
    (u"عادل ريان", "https://surahquran.com/mp3/Adel-Ryan"),
    (u"عادل الكلباني", "https://surahquran.com/mp3/AlKalbani"),
    (u"عامر الكاظمي", "https://surahquran.com/mp3/Amer-Kazemi"),
    (u"عبدالبارئ الثبيتي", "https://surahquran.com/mp3/Abdul-Bari-Thubaiti"),
    (u"عبدالباسط عبدالصمد", "https://surahquran.com/mp3/Abdulbaset"),
    (u"عبد الباسط مرتل", "https://surahquran.com/mp3/Abdulbasitm"),
    (u"عبد الباسط ورش", "https://surahquran.com/mp3/Abdulbaset-warsh"),
    (u"عبد الحليم حسين", "https://surahquran.com/mp3/Abdualhaleem-Hussain"),
    (u"عبدالرحمن السديس", "https://surahquran.com/mp3/Alsudaes"),
    (u"السديس و الشريم", "https://surahquran.com/mp3/Alsudaes-sh"),
    (u"عبدالرحمن العوسي", "https://surahquran.com/mp3/AbdAlrahman-Al3osy"),
    (u"عبد الرحمن الماجد", "https://surahquran.com/mp3/Almajed"),
    (u"عبد الرحمن بنموسى", "https://surahquran.com/mp3/Ben-Moussa"),
    (u"عبد الرحمن الجريذي", "https://surahquran.com/mp3/Al-Juraidhi"),
    (u"عبد الرحمن مسعد", "https://surahquran.com/quran-mp3-qari-21.html"),
    (u"عبد الحميد احساين", "https://surahquran.com/mp3/Abdelhamid-Ehsain"),
    (u"عبدالعزيز الأحمد", "https://surahquran.com/mp3/Abdul-Aziz-Al-Ahmad"),
    (u"عبدالعزيز الزهراني", "https://surahquran.com/mp3/Abdulaziz-Al-Zahrani"),
    (u"عبد العزيز سحيم", "https://surahquran.com/quran-mp3-qari-46.html"),
    (u"عبد العزيز عسيري", "https://surahquran.com/quran-mp3-qari-12.html"),
    (u"عبد العزيز الكرعاني", "https://surahquran.com/quran-mp3-qari-43.html"),
    (u"عبدالله الخلف", "https://surahquran.com/mp3/Abdullah-Al-Khalaf"),
    (u"عبدالله المطرود", "https://surahquran.com/mp3/Al-Mattrod"),
    (u"عبدالله الموسى", "https://surahquran.com/mp3/mosa"),
    (u"عبدالله بصفر", "https://surahquran.com/mp3/basfar"),
    (u"عبدالله البعيجان", "https://surahquran.com/mquran-mp3-qari-50.html"),
    (u"عبدالله خياط", "https://surahquran.com/mp3/khayat"),
    (u"عبد الله الخليفي", "https://surahquran.com/mp3/Al-Khulaifi"),
    (u"عبدالله القرافي", "https://surahquran.com/mp3/Qarafi/"),
    (u"عبد الله كامل", "https://surahquran.com/mp3/Abdullah-Kamel"),
    (u"عبد الرزاق الدليمي", "https://surahquran.com/mp3/Abdul-Razzaq-al-Dulaimi"),
    (u"عبد الكبير الحديدي", "https://surahquran.com/mp3/Abdul-Kabeer-Al-Hadidi"),
    (u"عبد المحسن الحارثي", "https://surahquran.com/mp3/Al-Harthy"),
    (u"عبد المحسن القاسم", "https://surahquran.com/mp3/Al-qasim"),
    (u"عبد المجيب بنكيران", "https://surahquran.com/mp3/Abdelmoujib-Benkirane"),
    (u"عبدالهادي أحمد كناكري", "https://surahquran.com/mp3/Kanakeri"),
    (u"عبدالودود حنيف", "https://surahquran.com/mp3/Abdul-Wadud-Hanif"),
    (u"عبد الولي الأركاني", "https://surahquran.com/quran-mp3-qari-2.html"),
    (u"عبيدة موفق الكردي", "https://surahquran.com/mp3/Obaida-Muafaq"),
    (u"عز الدين العوامي", "https://surahquran.com/quran-mp3-qari-60.html"),
    (u"عفيف محمد تاج", "https://surahquran.com/quran-mp3-qari-16.html"),
    (u"عكاشة كميني", "https://surahquran.com/quran-mp3-qari-19.html"),
    (u"علاء عقل", "https://surahquran.com/quran-mp3-qari-61.html"),
    (u"علي الحذيفي", "https://surahquran.com/mp3/Ali-Alhuthaifi"),
    (u"الحذيفي برواية قالون", "https://surahquran.com/mp3/qalon-Alhuthaifi"),
    (u"علي جابر", "https://surahquran.com/mp3/Jaber"),
    (u"علي عبد السلام", "https://surahquran.com/quran-mp3-qari-22.html"),
    (u"عماد المنصري", "https://surahquran.com/mp3/Imad-Mansri"),
    (u"عمر عبد العزيز", "https://surahquran.com/quran-mp3-qari-9.html"),
    (u"عمر القزابري", "https://surahquran.com/mp3/Al-Qazabri"),
    (u"عمر الدريويز", "https://surahquran.com/quran-mp3-qari-45.html"),
    (u"عمر هشام العربي", "https://surahquran.com/mp3/Omar-Hisham"),
    (u"العيون الكوشي", "https://surahquran.com/mp3/kouchi"),
    (u"غسان الشوربجي", "https://surahquran.com/mp3/ghassan"),
    (u"فاتح جولاق", "https://surahquran.com/mp3/Fatih-Cholak"),
    (u"فارس عباد", "https://surahquran.com/mp3/Fares"),
    (u"الفاتح محمد الزبير", "https://surahquran.com/mp3/Alfateh-Alzubair"),
    (u"فهد واصل المطيري", "https://surahquran.com/mp3/Fahad-Almutairi"),
    (u"فؤاد الخامري", "https://surahquran.com/mp3/Foad-AlKhamere"),
    (u"فيصل الهاجري", "https://surahquran.com/mp3/Faisal-AlHajry"),
    (u"كريم منصوري", "https://surahquran.com/mp3/Karim-Mansouri"),
    (u"مصطفى اللاهوني", "https://surahquran.com/mp3/lahony"),
    (u"ماجد الزامل", "https://surahquran.com/mp3/Majid-Alzamil"),
    (u"ماهر المعيقلي", "https://surahquran.com/mp3/maher"),
    (u"ماهر شخاشيرو", "https://surahquran.com/mp3/Shakhashero"),
    (u"ماهر علوان - حدر", "https://surahquran.com/mp3/Maher-Alwan"),
    (u"محمد أيوب", "https://surahquran.com/mp3/Mohammad_Ayyub"),
    (u"محمد أيوب التراويح", "https://surahquran.com/mp3/M-Ayyub-traweeh"),
    (u"محمد البراك", "https://surahquran.com/mp3/barrak"),
    (u"محمد البخيت", "https://surahquran.com/mp3/Al-Bakhit"),
    (u"محمد الحضيري", "https://surahquran.com/mp3/Al-Hudayri"),
    (u"محمد الغزالي", "https://surahquran.com/mp3/Mohammed-Al-Ghazali"),
    (u"محمد ديبيروف", "https://surahquran.com/quran-mp3-qari-40.html"),
    (u"محمد طه جنيد", "https://surahquran.com/quran-mp3-qari-29.html"),
    (u"محمد السبيل", "https://surahquran.com/mp3/Alsubail"),
    (u"محمد الكنتاوي", "https://surahquran.com/mp3/Al-Kantaoui"),
    (u"محمد اللحيدان", "https://surahquran.com/mp3/allheadan"),
    (u"محمد المحيسني", "https://surahquran.com/mp3/Almohisni"),
    (u"محمد جبريل", "https://surahquran.com/mp3/Jibrel"),
    (u"محمد حسان", "https://surahquran.com/mp3/Hassan"),
    (u"محمود عبد الحكم", "https://surahquran.com/mp3/Mahmoud-Abdel-Hakam"),
    (u"محمد رفعت", "https://surahquran.com/mp3/Mohamed-Refaat"),
    (u"محمد الفقيه", "https://surahquran.com/mp3/Muhammad-Faqih/"),
    (u"محمد رشاد الشريف", "https://surahquran.com/mp3/Al-Sharif"),
    (u"محمد صديق المنشاوي", "https://surahquran.com/mp3/Al-Minshawi"),
    (u"المنشاوي مصحف مجود", "https://surahquran.com/mp3/Al-Minshawi_Mojawwad"),
    (u"المنشاوي مع الأطفال", "https://surahquran.com/mp3/Minshawi-with-kids"),
    (u"محمود خليل الحصري", "https://surahquran.com/mp3/Al-Hussary"),
    (u"الحصري مجود", "https://surahquran.com/mp3/Al-Hussary-Mujawwad"),
    (u"الحصري برواية ورش", "https://surahquran.com/mp3/Al-Hussary-warsh"),
    (u"الحصري برواية قالون", "https://surahquran.com/mp3/Al-Hussary-qaloon"),
    (u"الحصري المعلم أطفال", "https://surahquran.com/mp3/Al-Hosary-children"),
    (u"محمود علي البنا", "https://surahquran.com/mp3/Mahmoud-El-Banna"),
    (u"محمود الشحات أنور", "https://surahquran.com/quran-mp3-qari-30.html"),
    (u"محمد الهادي توري", "https://surahquran.com/mp3/Hadi-Toure"),
    (u"محمد هشام حسن", "https://surahquran.com/quran-mp3-qari-10.html"),
    (u"محمد سايد", "https://surahquran.com/mp3/sayed"),
    (u"محمد عبدالكريم", "https://surahquran.com/mp3/Mohamad-Abdullkarem"),
    (u"محمد حسين عامر", "https://surahquran.com/mp3/mohammad-3amer"),
    (u"مختار الحاج", "https://surahquran.com/quran-mp3-qari-49.html"),
    (u"معاذ الدويك", "https://surahquran.com/quran-mp3-qari-42.html"),
    (u"مفتاح السلطني", "https://surahquran.com/mp3/Muftah-Saltani"),
    (u"مشاري العفاسي", "https://surahquran.com/mp3/Alafasi"),
    (u"مشاري البغلي", "https://surahquran.com/quran-mp3-qari-31.html"),
    (u"مصطفى إسماعيل", "https://surahquran.com/mp3/mostafa"),
    (u"مصطفى اسماعيل تجويد", "https://surahquran.com/mp3/Mustafa-Ismail-Tajweed"),
    (u"مصطفى غربي", "https://surahquran.com/mp3/Mustafa-Gharbi"),
    (u"مصطفى رعد العزاوي", "https://surahquran.com/mp3/Mostafa-Raad-Al-Azzawi"),
    (u"مصطفى الفرجاني", "https://surahquran.com/quran-mp3-qari-3.html"),
    (u"ممدوح عامر", "https://surahquran.com/quran-mp3-qari-32.html"),
    (u"منصور السالمي", "https://surahquran.com/mp3/Mansour"),
    (u"ميثم التمار", "https://surahquran.com/mp3/Maytham-Tammar"),
    (u"ناصر القطامي", "https://surahquran.com/mp3/qattamy"),
    (u"نورين محمد صديق", "https://surahquran.com/mp3/Noreen-Siddiq"),
    (u"نبيل الرفاعي", "https://surahquran.com/mp3/nabil"),
    (u"نعمة الحسان", "https://surahquran.com/mp3/Nima-Al-Hassan"),
    (u"نور الدين سليم", "https://surahquran.com/quran-mp3-qari-36.html"),
    (u"هاني الرفاعي", "https://surahquran.com/mp3/Hani"),
    (u"هزاع البلوشي", "https://surahquran.com/mp3/hazzaa"),
    (u"هشام الهراز", "https://surahquran.com/mp3/Hisham-Al-Haraz"),
    (u"هيثم الدخين", "https://surahquran.com/quran-mp3-qari-33.html"),
    (u"هيثم الجدعاني", "https://surahquran.com/quran-mp3-qari-59.html"),
    (u"وديع اليمني", "https://surahquran.com/mp3/wadie_alyamni"),
    (u"الوليد الشمسان", "https://surahquran.com/quran-mp3-qari-58.html"),
    (u"وليد مهساس", "https://surahquran.com/quran-mp3-qari-44.html"),
    (u"ياسر الدوسري", "https://surahquran.com/mp3/Al-Dosari"),
    (u"ياسر القرشي", "https://surahquran.com/mp3/qurashi"),
    (u"ياسر سلامة", "https://surahquran.com/mp3/salamah"),
    (u"ياسر الزيلعي", "https://surahquran.com/quran-mp3-qari-25.html"),
    (u"ياسين الجزائري", "https://surahquran.com/mp3/yaseen"),
    (u"يحيى حوى", "https://surahquran.com/mp3/Yahya-Hawwa"),
    (u"يوسف بن نوح أحمد", "https://surahquran.com/mp3/yusuf-nooh"),
    (u"يوسف الشويعي", "https://surahquran.com/mp3/Youssef-Ashewaie"),
    (u"يوسف العيدروس", "https://surahquran.com/quran-mp3-qari-13.html"),
    (u"يوسف الصقير", "https://surahquran.com/quran-mp3-qari-62.html"),
    (u"يوسف كالو", "https://surahquran.com/quran-mp3-qari-20.html"),
    (u"يوسف معاطي", "https://surahquran.com/quran-mp3-qari-48.html"),
    (u"يونس اسويلص", "https://surahquran.com/quran-mp3-qari-6.html"),
]


_SQ_RECITER_PATH = re.compile(
    r"^/(?:mp3/(?!index)[^/]+/?|m?quran-mp3-qari-\d+\.html)$", re.I)


def _sq_parse_reciters(html):
    out, seen = [], set()
    for href, inner in re.findall(r"""<a\s[^>]*?href\s*=\s*["']?([^"'\s>]+)["']?[^>]*>(.*?)</a>""",
                                  html, re.S | re.I):
        url = urljoin(SQ_BASE, href.strip()).split("#")[0].split("?")[0]
        if not url.startswith(SQ_BASE) or not _SQ_RECITER_PATH.match(url[len(SQ_BASE) - 1:]):
            continue
        name = strip_tags(inner).strip()
        if not name or url in seen:
            continue
        seen.add(url)
        out.append((name, url))
    return out


def surahquran_reciters():
    """-> [(name, absolute_url)] from /qura.html, or the built-in list when the
    site cannot be read / its layout changed."""
    out = []
    for page, cache in (("qura.html", "sq_qura.html"), ("", "sq_home.html")):
        try:
            out = _sq_parse_reciters(cached_text(SQ_BASE + page, cache))
        except Exception:
            out = []
        if len(out) >= 20:
            break
    if len(out) < 20:                      # blocked page / layout change -> built-in list
        out = list(SQ_RECITERS_FALLBACK)
    out.sort(key=lambda x: norm(x[0]))
    return out


def _first_mp3(html, surah=None):
    urls = [_clean_url(u) for u in re.findall(r"""https?://[^\s"'<>\)\]\\]+?\.mp3(?![A-Za-z0-9_])""", html, re.I)]
    if surah is not None:
        tag = "%03d" % surah
        for u in urls:
            if tag in u.rsplit("/", 1)[-1]:
                return u
    return urls[0] if urls else None


def surahquran_tracks(reciter_url):
    """-> [(surah_number, direct_url or None, page_url or None)] for one reciter."""
    try:
        html = http_text(reciter_url, 20)
    except Exception:
        html = ""
    tracks = {}
    # 1) direct mp3 links with a 3-digit surah number in the file name
    for u in re.findall(r"""https?://[^\s"'<>\)\]\\]+?\.mp3(?![A-Za-z0-9_])""", html, re.I):
        m = re.search(r"(\d{3})\.mp3$", _clean_url(u), re.I)
        if m and 1 <= int(m.group(1)) <= 114:
            tracks.setdefault(int(m.group(1)), (_clean_url(u), None))
    # 2) per-surah pages: mp3quran-surah-N-sheikh-ID.html   or   /mp3/<slug>/N.html
    for href in re.findall(r"""href\s*=\s*["']?([^"'\s>]+)""", html):
        full = urljoin(reciter_url, href).split("#")[0]
        m = (re.search(r"mp3quran-surah-(\d+)-sheikh-\d+\.html$", full) or
             re.search(r"/mp3/[^/]+/(\d{1,3})\.html$", full))
        if m and 1 <= int(m.group(1)) <= 114:
            tracks.setdefault(int(m.group(1)), (None, full))
    if not tracks:                          # page unreadable -> build the known URL pattern
        base = reciter_url.rstrip("/")
        m = re.search(r"m?quran-mp3-qari-(\d+)\.html$", reciter_url)
        for n in range(1, 115):
            page = (SQ_BASE + "mp3quran-surah-%d-sheikh-%s.html" % (n, m.group(1))) if m \
                else "%s/%d.html" % (base, n)
            tracks[n] = (None, page)
    return [(n,) + tracks[n] for n in sorted(tracks)]


def surahquran_resolve(n, direct, page):
    if direct:
        return direct
    html = http_text(page, 20)
    url = _first_mp3(html, n)
    if not url:
        raise ValueError("mp3 not found on " + page)
    return url


# ----------------------------------------------------------------- recording
import glob
import threading

REC_BASES = ["/media/hdd", "/media/usb", "/media/mmc", "/media/net"]


def record_dir(bases=None, require_mount=True):
    """Folder on an attached HDD/USB (never the receiver's flash)."""
    cands = list(bases or (REC_BASES + sorted(glob.glob("/media/*"))))
    seen = set()
    for b in cands:
        if b in seen:
            continue
        seen.add(b)
        if not os.path.isdir(b) or not os.access(b, os.W_OK):
            continue
        if require_mount and not os.path.ismount(b):
            continue  # /media/hdd exists as an empty folder when no disk is mounted
        d = os.path.join(b, "QuranHub")
        try:
            if not os.path.isdir(d):
                os.makedirs(d)
            return d
        except OSError:
            continue
    return None


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s or "")
    return s.strip(" ._")[:60] or "quran"


def open_stream(url, timeout=15):
    last = None
    for ctx in _contexts():
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            kw = {"timeout": timeout}
            if ctx is not None:
                kw["context"] = ctx
            return urlopen(req, **kw)
        except Exception as e:
            last = e
    raise last


# ----------------------------------------------------------------- islamweb
IW_BASE = "https://audio.islamweb.net/audio/"
IW_PAGES = 14


def surah_no(name):
    """Arabic surah name ('سورة البقرة', 'البقرة') -> number or None."""
    t = norm(re.sub(r"^\s*(ما\s+تيسر\s+من\s+)?سورة\s*", "", name or "")).strip()
    if not t:
        return None
    for i in range(1, 115):
        if norm(surah_name(i)) == t:
            return i
    for i in range(1, 115):                       # tolerate small spelling differences
        nn = norm(surah_name(i))
        if nn.replace("ال", "", 1) == t.replace("ال", "", 1) and len(t) > 2:
            return i
    return None


def _first_text(inner):
    for t in re.findall(r">([^<>]+)<", "<x>" + inner + "<x>"):
        t = unescape_html(t).strip()
        if t:
            return t
    return strip_tags(inner).strip()


def unescape_html(t):
    try:
        import html as _h
        return _h.unescape(t)
    except Exception:
        return t


def _iw_list_page(n):
    url = IW_BASE + "index.php?pageno=%d&page=qareelast" % n
    html = cached_text(url, "iw_list_%d.html" % n)
    found = {}
    for href, inner in re.findall(r"""<a\s[^>]*href\s*=\s*["']?([^"'\s>]*page=allsoura[^"'\s>]*)["']?[^>]*>(.*?)</a>""",
                                  html, re.S | re.I):
        m = re.search(r"qid=(\d+)", href)
        if not m:
            continue
        name = _first_text(inner)
        if m.group(1) not in found or (name and not found[m.group(1)]):
            found[m.group(1)] = name
    return found


def islamweb_reciters():
    """-> [(name, qid)] from audio.islamweb.net (all pages, fetched in parallel)."""
    results, lock = {}, threading.Lock()

    def work(n):
        try:
            r = _iw_list_page(n)
        except Exception:
            r = {}
        with lock:
            results[n] = r
    threads = [threading.Thread(target=work, args=(n,)) for n in range(1, IW_PAGES + 1)]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(40)
    out, seen = [], set()
    for n in range(1, IW_PAGES + 1):
        for qid, name in results.get(n, {}).items():
            if qid not in seen and name:
                seen.add(qid)
                out.append((name, qid))
    if not out:
        raise ValueError("no reciters parsed from islamweb")
    out.sort(key=lambda x: norm(x[0]))
    return out


def islamweb_tracks(qid):
    """-> [(riwaya_or_None, surah_number_or_None, label, url)] in page order."""
    html = http_text(IW_BASE + "index.php?page=allsoura&qid=%s&tab=qareelast" % qid, 25)
    rows, seen = [], set()
    riwaya = None
    pend_id = pend_name = None

    def add(aid, name):
        seen.add(aid)
        rows.append((riwaya, surah_no(name), name.strip(),
                     IW_BASE + "downloadmp3.php?audioid=%s" % aid))
    for tok in re.findall(r"<[^>]+>|[^<]+", html):
        if tok.startswith("<"):
            m = re.search(r"audioid=(\d+)", tok)
            if m and ("downloadmp3" in tok or "audioinfo" in tok) and m.group(1) not in seen \
                    and m.group(1) != pend_id:
                if pend_name:
                    add(m.group(1), pend_name)
                    pend_name = None
                else:
                    pend_id = m.group(1)
            continue
        t = unescape_html(tok).strip()
        if not t:
            continue
        if "عدد المواد" in t:
            r = t.split("عدد المواد")[0].strip(" :-–—")
            if r:
                riwaya = r
            continue
        m = re.match(r"^(?:ما\s+تيسر\s+من\s+)?(سورة\s+\S.{0,28})$", t)
        if m:
            if pend_id and pend_id not in seen:
                add(pend_id, m.group(1))
                pend_id = None
            else:
                pend_name = m.group(1)
    if not rows:
        raise ValueError("no audio found for this reciter")
    return rows


# ----------------------------------------------------------------- way2quran
W2_BASE = "https://way2quran.com"
W2_MEDIA = "https://media.way2quran.com"
W2_RIWAYAT = {
    "hafs-an-asim": u"حفص عن عاصم", "warsh-an-nafi": u"ورش عن نافع", "qalun-an-nafi": u"قالون عن نافع",
    "shubah-an-asim": u"شعبة عن عاصم", "al-duri-an-abi-amr": u"الدوري عن أبي عمرو",
    "al-susi-an-abi-amr": u"السوسي عن أبي عمرو", "khalaf-an-hamzah": u"خلف عن حمزة",
    "khallad-an-hamzah": u"خلاد عن حمزة", "al-bazzi-an-ibn-kathir": u"البزي عن ابن كثير",
    "qunbul-an-ibn-kathir": u"قنبل عن ابن كثير",
}
W2_FALLBACK = [
    (u"عبد الرحمن مسعد", "abdul-rahman-musaad"), (u"السيد سعيد", "alsaid-saeed"),
    (u"أحمد كاسب", "ahmed-kaseb"), (u"بدر التركي", "badr-al-turki"), (u"علاء عقل", "alaa-aql"),
    (u"محمد صديق المنشاوي", "muhammad-siddiq-al-minshawi"), (u"عمر ضياء الدين", "omar-diaa-al-din"),
    (u"إسلام صبحي", "islam-sobhi"), (u"ياسر الدوسري", "yasser-al-dosary"),
    (u"سلمان عبيد المطيري", "salman-obaid-al-mutairi"),
]


def _w2_parse_reciters(html):
    out = {}
    for href, inner in re.findall(r"""<a\s[^>]*href\s*=\s*["']?([^"'\s>]*/reciters/[^"'\s>?#]+)[^"'\s>]*["']?[^>]*>(.*?)</a>""",
                                  html, re.S | re.I):
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        name = _first_text(inner)
        if slug and (slug not in out or (name and not out[slug])):
            out[slug] = name
    return out


def way2quran_reciters():
    """-> [(name, slug)]; walks ?page=N until nothing new, else uses the built-in list."""
    names = {}
    for k in range(1, 60):
        url = W2_BASE + "/ar/reciters" + ("" if k == 1 else "?page=%d" % k)
        try:
            got = _w2_parse_reciters(cached_text(url, "w2_rec_%d.html" % k))
        except Exception:
            got = {}
        new = [x for x in got if x not in names]
        for x in got:
            if got[x] or x not in names:
                names[x] = got[x] or names.get(x, "")
        if not new:
            break
    for name, slug in W2_FALLBACK:
        names.setdefault(slug, name)
    out = []
    for slug, name in names.items():
        out.append((name or slug.replace("-", " ").title(), slug))
    out.sort(key=lambda x: norm(x[0]))
    return out


def way2quran_tracks(slug):
    """-> [(riwaya_slug, surah_number, url)] for one reciter (all riwayat found)."""
    pat = re.compile(r"""https?://media\.way2quran\.com/[^\s"'<>)\]]*?/([a-z0-9\-]+)/(\d{1,3})\.mp3(?![A-Za-z0-9_])""", re.I)
    got, tried = {}, set()

    def scan(url):
        html = http_text(url, 25)
        for m in pat.finditer(html):
            riw, n = m.group(1).lower(), int(m.group(2))
            if 1 <= n <= 114:
                got.setdefault((riw, n), _clean_url(m.group(0)))
        return html
    base = W2_BASE + "/ar/reciters/" + slug
    html = scan(base)
    extra = [x for x in dict.fromkeys(re.findall(r"recitationSlug=([a-z0-9\-]+)", html)) if x][:6]
    for riw in extra:
        if not any(r == riw for r, _ in got):
            try:
                scan(base + "?recitationSlug=" + riw)
            except Exception:
                pass
    if not got:
        raise ValueError("no audio found for this reciter")
    return [(r, n, u) for (r, n), u in sorted(got.items(), key=lambda kv: (kv[0][0] != "hafs-an-asim", kv[0][0], kv[0][1]))]


def _riwaya_slug_from_label(t):
    for key, slug in ((u"ورش", "warsh-an-nafi"), (u"قالون", "qalun-an-nafi"), (u"شعبة", "shubah-an-asim"),
                      (u"الدوري", "al-duri-an-abi-amr"), (u"السوسي", "al-susi-an-abi-amr"),
                      (u"البزي", "al-bazzi-an-ibn-kathir"), (u"قنبل", "qunbul-an-ibn-kathir")):
        if key in (t or ""):
            return slug
    return "hafs-an-asim"


def way2quran_iconic():
    """-> [dict(reciter, surah, n, riwaya, duration, slug)] from /ar/iconic."""
    html = cached_text(W2_BASE + "/ar/iconic", "w2_iconic.html")
    marks = list(re.finditer(r"imgs(?:/|%2F)thumbs(?:/|%2F)([a-z0-9\-]+)\.webp", html, re.I))
    out = []
    for i, m in enumerate(marks):
        seg = html[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(html)]
        texts = [unescape_html(t).strip() for t in re.findall(r">([^<>]{2,80})<", seg)]
        texts = [t for t in texts if t and not t.startswith(("{", "http"))]
        dur = next((t for t in texts if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", t)), u"")
        surah = next((t for t in texts if u"سورة" in t), u"")
        rec = next((t for t in texts if t != surah and t != dur and u"سورة" not in t
                    and not re.search(u"عن\\s|حفص|ورش|قالون", t)), u"")
        riw = next((t for t in texts if re.search(u"عن\\s+\\S+|حفص|ورش|قالون", t) and t != surah), u"")
        n = surah_no(surah)
        if rec and n:
            out.append({"reciter": rec, "surah": re.sub(u"^ما تيسر من ", u"", surah), "n": n,
                        "riwaya": riw, "duration": dur, "slug": m.group(1)})
    if not out:
        raise ValueError("no iconic clips parsed from way2quran")
    return out


def way2quran_resolve(slug, n, riwaya_label=u""):
    riw = _riwaya_slug_from_label(riwaya_label)
    try:
        for r, k, u in way2quran_tracks(slug):
            if k == n and r == riw:
                return u
    except Exception:
        pass
    for r in (riw, "hafs-an-asim"):
        url = "%s/%s/%s/%03d.mp3" % (W2_MEDIA, slug, r, n)
        try:
            open_stream(url, 10).close()
            return url
        except Exception:
            continue
    raise ValueError("audio not found for %s / %d" % (slug, n))


# ----------------------------------------------------------------- settings
import subprocess

SETTINGS_PATH = "/etc/enigma2/quranhub.json"
DEFAULTS = {"fmt": "original", "engine": 4097, "theme": 0, "fav": []}


def load_settings(path=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(path or SETTINGS_PATH, "rb") as f:
            cfg.update(json.loads(f.read().decode("utf-8")))
    except Exception:
        pass
    return cfg


def save_settings(cfg, path=None):
    try:
        with open(path or SETTINGS_PATH, "wb") as f:
            f.write(json.dumps(cfg, ensure_ascii=False).encode("utf-8"))
        return True
    except Exception:
        return False


# ----------------------------------------------------------------- formats
FORMATS = [("original", u"الأصلي"), ("mp3", u"MP3"), ("mp3_128", u"MP3 128k"), ("mp3_192", u"MP3 192k"),
           ("mp3_320", u"MP3 320k"), ("flac", u"FLAC"), ("wav", u"WAV"), ("ogg", u"OGG"), ("m4a", u"M4A")]
FORMAT_LABEL = dict(FORMATS)

# format -> (ffmpeg args, required ffmpeg encoders, extension)
_FF = {
    "mp3": (["-c:a", "libmp3lame", "-q:a", "2"], ["libmp3lame"], ".mp3"),
    "mp3_128": (["-c:a", "libmp3lame", "-b:a", "128k"], ["libmp3lame"], ".mp3"),
    "mp3_192": (["-c:a", "libmp3lame", "-b:a", "192k"], ["libmp3lame"], ".mp3"),
    "mp3_320": (["-c:a", "libmp3lame", "-b:a", "320k"], ["libmp3lame"], ".mp3"),
    "flac": (["-c:a", "flac"], ["flac"], ".flac"),
    "wav": (["-c:a", "pcm_s16le"], ["pcm_s16le"], ".wav"),
    "ogg": (["-c:a", "libvorbis", "-q:a", "5"], ["libvorbis"], ".ogg"),
    "m4a": (["-c:a", "aac", "-b:a", "128k"], ["aac"], ".m4a"),
}
# format -> (gstreamer encoder chain, extension)
_GST = {
    "mp3": ("lamemp3enc", ".mp3"),
    "flac": ("flacenc", ".flac"),
    "wav": ("wavenc", ".wav"),
    "ogg": ("vorbisenc ! oggmux", ".ogg"),
}
_cache = {}


def which(cmd):
    for d in os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin").split(":"):
        p = os.path.join(d, cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _devnull():
    return open(os.devnull, "wb")


def _ffmpeg_encoders():
    if "ff" in _cache:
        return _cache["ff"]
    enc = set()
    ff = which("ffmpeg")
    if ff:
        try:
            out = subprocess.check_output([ff, "-hide_banner", "-encoders"],
                                          stderr=subprocess.STDOUT)
            for line in out.decode("utf-8", "ignore").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("A"):
                    enc.add(parts[1])
        except Exception:
            pass
    _cache["ff"] = enc
    return enc


def _gst_has(elements):
    gi = which("gst-inspect-1.0")
    if not gi or not which("gst-launch-1.0"):
        return False
    for el in elements:
        try:
            with _devnull() as dn:
                if subprocess.call([gi, el], stdout=dn, stderr=dn) != 0:
                    return False
        except Exception:
            return False
    return True


def backend_for(fmt):
    key = "be_" + fmt
    if key in _cache:
        return _cache[key]
    be = None
    if fmt in _FF and set(_FF[fmt][1]) <= _ffmpeg_encoders():
        be = "ffmpeg"
    elif fmt in _GST and _gst_has([e for e in _GST[fmt][0].split() if e != "!"]):
        be = "gst"
    _cache[key] = be
    return be


def available_formats():
    """[(key, label)] - 'original' always, others only if an encoder exists."""
    return [(k, l) for k, l in FORMATS if k == "original" or backend_for(k)]


def format_ext(fmt):
    if fmt in _FF:
        return _FF[fmt][2]
    if fmt in _GST:
        return _GST[fmt][1]
    return None


def transcode(src, fmt):
    """Convert one file; the result sits next to it (same name, new extension).  Converting to the
    same extension (MP3 -> MP3 320k) goes through a temporary file and then replaces the source."""
    be = backend_for(fmt)
    if be is None:
        raise ValueError("no encoder for %s" % fmt)
    base = os.path.splitext(src)[0]
    ext = format_ext(fmt)
    final = base + ext
    same = os.path.abspath(final) == os.path.abspath(src)
    dst = base + ".sqhtmp" + ext if same else final
    if be == "ffmpeg":
        args = _FF[fmt][0]
        cmd = [which("ffmpeg"), "-y", "-loglevel", "error", "-i", src, "-vn", "-map_metadata", "0"] + args + [dst]
    else:
        chain = _GST[fmt][0]
        cmd = ([which("gst-launch-1.0"), "-q", "filesrc", "location=" + src, "!", "decodebin",
                "!", "audioconvert", "!", "audioresample", "!"] + chain.split() +
               ["!", "filesink", "location=" + dst])
    with _devnull() as dn:
        rc = subprocess.call(cmd, stdout=dn, stderr=dn)
    if rc != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise RuntimeError("%s failed (rc=%s)" % (be, rc))
    if same:
        os.rename(dst, final)
    return final


def disk_free(path):
    """Free bytes on the disk holding path (None if unknown)."""
    try:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize
    except Exception:
        return None


# ----------------------------------------------------------------- network / quality
def fmt_bytes(n):
    n = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


_IGNORED_IF = ("lo", "br", "veth", "docker", "virbr", "dummy", "sit", "ifb")


def read_rx(path="/proc/net/dev"):
    """Total bytes received on the real network interfaces (None if unreadable)."""
    total, seen = 0, False
    try:
        with open(path) as f:
            for line in f:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                name = name.strip()
                if name == "lo" or name.startswith(_IGNORED_IF[1:]):
                    continue
                total += int(rest.split()[0])
                seen = True
    except Exception:
        return None
    return total if seen else None


_BR1 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_BR2 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
_AAC_SR = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000]


def _mp3_header(b, i):
    """(kbps, hz, channels, frame_len) for a valid MPEG audio layer III header at i."""
    if i + 4 > len(b) or b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
        return None
    ver, layer = (b[i + 1] >> 3) & 3, (b[i + 1] >> 1) & 3
    brx, srx = (b[i + 2] >> 4) & 15, (b[i + 2] >> 2) & 3
    if ver == 1 or layer != 1 or brx in (0, 15) or srx == 3:
        return None
    kbps = (_BR1 if ver == 3 else _BR2)[brx]
    hz = _SR[ver][srx]
    ch = 1 if ((b[i + 3] >> 6) & 3) == 3 else 2
    flen = (144 if ver == 3 else 72) * kbps * 1000 // hz + ((b[i + 2] >> 1) & 1)
    return kbps, hz, ch, flen


def parse_mp3(b):
    """Find the first two consecutive MP3 frames. Returns dict or None."""
    i = 0
    if b[:3] == b"ID3" and len(b) >= 10:
        i = 10 + (((b[6] & 0x7f) << 21) | ((b[7] & 0x7f) << 14) | ((b[8] & 0x7f) << 7) | (b[9] & 0x7f))
    while i + 4 <= len(b):
        h = _mp3_header(b, i)
        if h:
            nxt = _mp3_header(b, i + h[3])
            if nxt or i + h[3] + 4 > len(b):
                vbr = (b[i:i + 64].find(b"Xing") >= 0 or b[i:i + 64].find(b"Info") >= 0
                       or b[i:i + 64 + 32].find(b"VBRI") >= 0)
                return {"codec": "MP3", "kbps": h[0], "hz": h[1], "ch": h[2], "vbr": vbr}
        i += 1
    return None


def parse_adts(b):
    for i in range(0, max(0, len(b) - 7)):
        if b[i] == 0xFF and (b[i + 1] & 0xF6) == 0xF0:
            sr = (b[i + 2] >> 2) & 15
            if sr < len(_AAC_SR):
                ch = ((b[i + 2] & 1) << 2) | (b[i + 3] >> 6)
                return {"codec": "AAC", "kbps": None, "hz": _AAC_SR[sr], "ch": ch or 2}
    return None


def probe_stream(url, max_bytes=65536, max_secs=4.0):
    """Read the head of a stream and report codec / bitrate / sample rate."""
    info = {"codec": None, "kbps": None, "hz": None, "ch": None, "vbr": False}
    if ".m3u8" in url.lower():
        info["codec"] = "HLS"
        return info
    resp = open_stream(url, 8)
    try:
        h = resp.headers
        ctype = (h.get("Content-Type") or "").lower()
        br = h.get("icy-br") or h.get("ice-bitrate") or ""
        if br.split(",")[0].strip().isdigit():
            info["kbps"] = int(br.split(",")[0])
        buf, t0 = b"", time.time()
        while len(buf) < max_bytes and time.time() - t0 < max_secs:
            chunk = resp.read(8192)
            if not chunk:
                break
            buf += chunk
        parsed = None
        if "aac" in ctype or "mp4" in ctype:
            parsed = parse_adts(buf)
        elif "ogg" in ctype:
            info["codec"] = "OGG"
        else:
            parsed = parse_mp3(buf) or (parse_adts(buf) if "mpeg" not in ctype else None)
        if parsed:
            for k, v in parsed.items():
                if v is not None and not (k == "kbps" and info["kbps"]):
                    info[k] = v
        if info["codec"] is None:
            info["codec"] = "MP3" if "mpeg" in ctype or "mp3" in ctype else (ctype.split("/")[-1].upper() or None)
        return info
    finally:
        try:
            resp.close()
        except Exception:
            pass


def quality_label(kbps):
    if not kbps:
        return u""
    if kbps < 64:
        return u"منخفضة"
    if kbps < 128:
        return u"متوسطة"
    if kbps < 256:
        return u"جيدة"
    return u"عالية"


def quality_text(q, measured=None):
    if not q or not q.get("codec"):
        return u""
    kbps = q.get("kbps") or (int(round(measured)) if measured else None)
    parts = [q["codec"] + (u" %d kbps%s" % (kbps, u" VBR" if q.get("vbr") else u"") if kbps else u"")]
    if q.get("hz"):
        parts.append(u"%.1f kHz" % (q["hz"] / 1000.0))
    if q.get("ch"):
        parts.append(u"مونو" if q["ch"] == 1 else u"ستيريو")
    ql = quality_label(kbps)
    if ql:
        parts.append(u"الجودة: " + ql)
    return u" • ".join(parts)


class StreamRecorder(object):
    """Save an http(s) audio stream to disk in a thread, then optionally
    convert it to another format (mp3/flac/wav/ogg/m4a)."""

    def __init__(self, url, title, folder, fmt="original"):
        self.url, self.title, self.folder, self.fmt = url, title, folder, fmt
        self.path = None
        self.bytes = 0
        self.stage = "recording"      # recording -> converting -> done | error
        self.note = u""
        self.error = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def stopping(self):
        return self._stop.is_set()

    @property
    def done(self):
        return self.stage == "done"

    @property
    def running(self):
        return self.stage in ("recording", "converting")

    def _run(self):
        resp = None
        try:
            if ".m3u8" in self.url.lower():
                raise ValueError("HLS streams (m3u8) cannot be recorded")
            resp = open_stream(self.url, 20)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "mpegurl" in ctype:
                raise ValueError("HLS streams (m3u8) cannot be recorded")
            ext = ".aac" if "aac" in ctype else ".ogg" if "ogg" in ctype else ".mp3"
            self.path = os.path.join(self.folder, "%s_%s%s" % (
                safe_name(self.title), time.strftime("%Y%m%d_%H%M%S"), ext))
            with open(self.path, "wb") as f:
                while not self._stop.is_set():
                    chunk = resp.read(16384)
                    if not chunk:
                        break
                    f.write(chunk)
                    self.bytes += len(chunk)
            if self.fmt != "original" and self.bytes > 0:
                self.stage = "converting"
                try:
                    dst = transcode(self.path, self.fmt)
                    if os.path.abspath(dst) != os.path.abspath(self.path):
                        os.remove(self.path)
                    self.path = dst
                except Exception as e:
                    self.note = u"تعذّر التحويل (%s) - تم حفظ الملف الأصلي" % e
            self.stage = "done"
        except Exception as e:
            self.error = e
            self.stage = "error"
        finally:
            try:
                if resp is not None:
                    resp.close()
            except Exception:
                pass


# ----------------------------------------------------------------- reciter picture
WIKI_SEARCH = "https://ar.wikipedia.org/w/rest.php/v1/search/page?q=%s&limit=3"
WIKI_SUMMARY = "https://ar.wikipedia.org/api/rest_v1/page/summary/%s"
_IMG_BAD = ("svg", "gif", "webp", "tif")


def _img_cache_file(name, ext):
    import hashlib
    h = hashlib.md5(norm(name).encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, "img_%s.%s" % (h, ext))


def reciter_image(name):
    """Local path of a picture for the reciter (Arabic Wikipedia thumbnail), or None.
    A miss is remembered for a week so the search is not repeated on every track."""
    try:
        from urllib.parse import quote
    except ImportError:
        from urllib import quote
    name = (name or u"").strip()
    if not name:
        return None
    for ext in ("jpg", "png"):
        pth = _img_cache_file(name, ext)
        if os.path.exists(pth) and os.path.getsize(pth) > 500:
            return pth
    miss = _img_cache_file(name, "miss")
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 7 * 24 * 3600:
        return None
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    url = None
    try:
        q = quote((u"%s قارئ" % name).encode("utf-8"))
        res = json.loads(http_text(WIKI_SEARCH % q, 12)).get("pages", [])
        for pg in res:
            th = (pg.get("thumbnail") or {}).get("url")
            if th:
                url = th
                break
        if not url and res:
            key = quote(res[0].get("key", u"").encode("utf-8"), safe="")
            sm = json.loads(http_text(WIKI_SUMMARY % key, 12))
            url = (sm.get("thumbnail") or {}).get("source")
    except Exception:
        url = None
    if url:
        if url.startswith("//"):
            url = "https:" + url
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext not in _IMG_BAD and ext in ("jpg", "png"):
            try:
                raw = http_get(url, 20)
                if len(raw) > 500:
                    pth = _img_cache_file(name, ext)
                    with open(pth, "wb") as f:
                        f.write(raw)
                    return pth
            except Exception:
                pass
    try:
        open(miss, "wb").close()
    except Exception:
        pass
    return None


# ----------------------------------------------------------------- Telegram public channels
# Only what Telegram shows on its public web preview (t.me/s/<channel>) can be played: videos and
# voice notes.  Music/document files are not exposed there (they open only inside the Telegram app).
TG_DEFAULT = [
    ("El_minshawy", u"تراث المنشاوي وقراء مصر"),
    ("VGA4A1", u"خواطر الشعراوي"),
]
TG_PAGE = "https://t.me/s/%s"
TG_POST = "https://t.me/%s/%d?embed=1&mode=tme"
_TG_USER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def tg_clean_user(u):
    u = (u or u"").strip()
    for pre in (u"https://", u"http://", u"t.me/s/", u"t.me/", u"telegram.me/", u"@"):
        if u.lower().startswith(pre):
            u = u[len(pre):]
    u = u.split(u"/")[0].split(u"?")[0]
    return u if _TG_USER.match(u) else None


def _unescape(s):
    try:
        from html import unescape
    except ImportError:                              # pragma: no cover
        from HTMLParser import HTMLParser
        unescape = HTMLParser().unescape
    return unescape(s)


def _tg_text(chunk):
    m = re.search(r'js-message_text[^>]*>(.*?)</div>', chunk, re.S)
    if not m:
        return u""
    t = re.sub(r"<br\s*/?>", u"\n", m.group(1))
    t = _unescape(re.sub(r"<[^>]+>", u"", t))
    lines = [x.strip() for x in t.split(u"\n") if x.strip()]
    return u" - ".join(lines[:2])


def tg_parse(html_text, channel):
    """-> (posts, info).  posts: [{"id", "kind": video|voice|doc, "url", "dur", "text"}] oldest first.
    info: {"title", "photo", "docs"}"""
    info = {"title": u"", "photo": u"", "docs": 0}
    m = re.search(r'<meta property="og:title" content="([^"]*)"', html_text)
    if m:
        info["title"] = _unescape(m.group(1)).strip()
    m = re.search(r'<meta property="og:image" content="([^"]*)"', html_text)
    if m:
        info["photo"] = _unescape(m.group(1))
    posts = []
    parts = html_text.split('data-post="')
    for chunk in parts[1:]:
        m = re.match(r'([^"/]+)/(\d+)"', chunk)
        if not m:
            continue
        pid = int(m.group(2))
        nxt = chunk.find('data-post="')
        body = chunk if nxt < 0 else chunk[:nxt]
        kind = url = None
        v = re.search(r'<video[^>]+src="([^"]+)"', body)
        a = re.search(r'<audio[^>]+src="([^"]+)"', body)
        if v:
            kind, url = "video", _unescape(v.group(1))
        elif a:
            kind, url = "voice", _unescape(a.group(1))
        elif "tgme_widget_message_document" in body:
            info["docs"] += 1
            kind = "doc"
        if not kind:
            continue
        d = re.search(r'message_(?:video|voice)_duration[^>]*>([\d:]+)<', body)
        text = _tg_text(body)
        if kind == "doc" and not text:
            t = re.search(r'tgme_widget_message_document_title[^>]*>(.*?)</div>', body, re.S)
            text = _unescape(strip_tags(t.group(1))) if t else u""
        posts.append({"id": pid, "kind": kind, "url": url, "dur": d.group(1) if d else u"", "text": text})
    posts.sort(key=lambda x: x["id"])
    return posts, info


def tg_page(channel, before=None):
    url = TG_PAGE % channel + ("?before=%d" % before if before else "")
    return tg_parse(http_text(url, 20), channel)


def tg_label(p):
    t = (p["text"] or u"").strip()
    if len(t) > 70:
        t = t[:68] + u"…"
    if not t:
        t = u"مقطع مرئي" if p["kind"] == "video" else u"تسجيل صوتي"
    mark = u"▶ " if p["kind"] == "video" else u"♪ "
    return mark + t + (u"  (%s)" % p["dur"] if p["dur"] else u"")


def tg_media(channel, pid, fallback=None):
    """Fresh link of one post (the CDN links carry a token that expires)."""
    try:
        posts, _i = tg_parse(http_text(TG_POST % (channel, pid), 15), channel)
        for p in posts:
            if p["id"] == pid and p["url"]:
                return p["url"]
    except Exception:
        if fallback:
            return fallback
        raise
    if fallback:
        return fallback
    raise ValueError(u"المنشور لم يعد متاحاً")


def tg_rows(channel, name, before=None):
    """Rows for the library column: playable posts (newest first) + 'more'."""
    posts, info = tg_page(channel, before)
    rows = []
    for p in reversed(posts):
        if p["kind"] not in ("video", "voice"):
            continue
        rows.append((tg_label(p), {
            "title": u"%s - %s" % (name, (p["text"] or tg_label(p))[:80]), "autonext": True,
            "video": p["kind"] == "video", "tg": [channel, p["id"]],
            "resolve": (lambda c=channel, i=p["id"], u=p["url"]: tg_media(c, i, u))}))
    if posts:
        rows.append((u"↓ منشورات أقدم ...", {"tgmore": [channel, posts[0]["id"]]}))
    if not rows or (len(rows) == 1 and posts):
        if not posts:
            raise ValueError(u"هذه القناة لا تعرض منشوراتها للعامة على الويب")
        rows.insert(0, (u"(لا توجد مقاطع قابلة للتشغيل في هذه الصفحة - ملفات الصوت تُفتح في تطبيق تليجرام فقط)", None))
    return rows


def tg_photo(channel):
    """Local path of the channel picture (cached a week), or None."""
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    pth = os.path.join(CACHE_DIR, "tg_%s.jpg" % channel.lower())
    if os.path.exists(pth) and os.path.getsize(pth) > 500 and time.time() - os.path.getmtime(pth) < 7 * 24 * 3600:
        return pth
    _posts, info = tg_parse(http_text(TG_PAGE % channel, 15), channel)
    if not info["photo"]:
        return pth if os.path.exists(pth) else None
    raw = http_get(info["photo"], 20)
    if len(raw) > 500:
        with open(pth, "wb") as f:
            f.write(raw)
        return pth
    return None


def tg_title(channel):
    import unicodedata
    _p, info = tg_parse(http_text(TG_PAGE % channel, 15), channel)
    t = u"".join(c for c in info["title"] if unicodedata.category(c) not in ("So", "Sk", "Cs", "Co", "Cn", "Cf"))
    return u" ".join(t.split())


# ----------------------------------------------------------------- quranpedia.net (official JSON API)
QPEDIA_RECITERS = ["https://api.quranpedia.net/v1/reciters"]


def _flatten(x):
    if isinstance(x, list):
        for y in x:
            for z in _flatten(y):
                yield z
    elif isinstance(x, dict):
        yield x


def quranpedia_reciters():
    """-> [(label, server, [surahs])]  (only the 'per surah' mushafs: one mp3 per surah)."""
    raw = cached_json(QPEDIA_RECITERS, "qpedia_reciters.json")
    items = raw.get("data", raw) if isinstance(raw, dict) else raw
    out, seen = [], set()
    for r in _flatten(items):
        server = (r.get("server") or "").strip()
        cls = (r.get("classification") or {}).get("id")
        if not server or cls == 2:                   # 2 = split per ayah
            continue
        name = (r.get("name") or u"").strip()
        name = re.sub(u"^مصحف\\s+", u"", name)
        kind = (r.get("recitation_type") or {}).get("ar_name") or u""
        label = u"%s%s" % (name, (u" - " + kind) if kind and kind not in name else u"")
        key = (label, server)
        if key in seen:
            continue
        seen.add(key)
        surahs = [int(s) for s in (r.get("surahs_list") or range(1, 115)) if 1 <= int(s) <= 114]
        out.append((label, server.rstrip("/") + "/", surahs))
    out.sort(key=lambda x: norm(x[0]))
    return out


# ----------------------------------------------------------------- tvquran.com
TVQ_BASE = "https://www.tvquran.com"
TVQ_LIST = (TVQ_BASE + "/ar/quran/recitations/%D9%82%D8%A7%D8%A6%D9%85%D8%A9-%D8%A7%D9%84%D9%82%D8%B1%D8%A7%D8%A1"
            "?json=1&view=scholar-letter&letter={letter}&page={page}")
TVQ_LETTERS = [u"أ", u"إ", u"ا", u"ب", u"ت", u"ج", u"ح", u"خ", u"د", u"ر", u"ز", u"س", u"ش", u"ص", u"ط", u"ع",
               u"غ", u"ف", u"ق", u"ك", u"ل", u"م", u"ن", u"ه", u"و", u"ي"]
_TVQ_PROFILE = re.compile(r'/ar/scholar/(\d+)/profile/([^"\'\s<>?#]+)')


def _unquote(s):
    try:
        from urllib.parse import unquote
    except ImportError:                              # pragma: no cover
        from urllib import unquote
    return unquote(s)


def tvquran_parse_list(html_text):
    out = []
    for rid, slug in _TVQ_PROFILE.findall(html_text):
        name = _unquote(slug).replace(u"-", u" ").strip()
        out.append((int(rid), name))
    return out


def tvquran_reciters():
    """-> [(name, profile_url)] - all letters, every 'load more' page (cached a week)."""
    path = _cache_path("tvq_reciters.json")
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 24 * 3600:
            with open(path, "rb") as f:
                rows = json.loads(f.read().decode("utf-8"))
            if rows:
                return [tuple(r) for r in rows]
    except Exception:
        pass
    try:
        from urllib.parse import quote
    except ImportError:                              # pragma: no cover
        from urllib import quote
    found = {}
    errors = 0
    for letter in TVQ_LETTERS:
        for page in range(1, 9):
            try:
                html_text = http_text(TVQ_LIST.format(letter=quote(letter.encode("utf-8")), page=page), 15)
            except Exception:
                errors += 1
                break
            new = 0
            for rid, name in tvquran_parse_list(html_text):
                if rid not in found and not name.startswith(u"المصحف المترجم"):
                    found[rid] = name
                    new += 1
            if new == 0 or "page=%d" % (page + 1) not in html_text:
                break
    if not found:
        raise ValueError(u"تعذّر الوصول إلى tvquran.com")
    rows = sorted([(n, TVQ_BASE + "/ar/scholar/%d/profile/" % rid) for rid, n in found.items()],
                  key=lambda x: norm(x[0]))
    try:
        if not os.path.isdir(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        with open(path, "wb") as f:
            f.write(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass
    return rows


_MP3_HREF = re.compile(r'(?:href|data-url|data-src|src)\s*=\s*["\']((?:https?:)?//[^"\']+?\.mp3)["\']', re.I)


def tvquran_parse_tracks(html_text):
    """-> [(group, n_or_None, label, url)] in page order."""
    out, seen, groups = [], set(), []
    for m in _MP3_HREF.finditer(html_text):
        url = m.group(1)
        if url.startswith("//"):
            url = "https:" + url
        if url in seen:
            continue
        seen.add(url)
        folder = url.rsplit("/", 2)[-2]
        if folder not in groups:
            groups.append(folder)
        n = None
        fm = re.search(r"/(\d{3})\.mp3$", url)
        if fm and 1 <= int(fm.group(1)) <= 114:
            n = int(fm.group(1))
        label = None
        if n is None:
            before = html_text[max(0, m.start() - 600):m.start()]
            sm = re.findall(u"(سورة\\s+[\\u0621-\\u064a\\s]{2,25})", before)
            label = sm[-1].strip() if sm else u"تلاوة"
            n = surah_no(label)
        out.append((groups.index(folder), n, label or surah_label(n), url))
    return out


def tvquran_tracks(profile_url):
    return tvquran_parse_tracks(http_text(profile_url, 20))


# ----------------------------------------------------------------- assabile.com
AS_BASE = "https://ar.assabile.com"
_AS_RECITER = re.compile(r'href="(?:https://ar\.assabile\.com)?/([a-z0-9]+(?:-[a-z0-9]+)+)"[^>]*>([^<]{3,60})</a>')
_AS_SKIP = ("read-quran", "quran", "download", "media", "about", "contact", "privacy", "terms")


def assabile_parse_list(html_text):
    out = []
    for slug, name in _AS_RECITER.findall(html_text):
        name = _unescape(name).strip()
        if slug.split("-")[0] in _AS_SKIP or not re.search(u"[\\u0621-\\u064a]", name):
            continue
        out.append((name, slug))
    return out


def assabile_reciters():
    path = _cache_path("assabile_reciters.json")
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 24 * 3600:
            with open(path, "rb") as f:
                rows = json.loads(f.read().decode("utf-8"))
            if rows:
                return [tuple(r) for r in rows]
    except Exception:
        pass
    found = {}
    for page in range(1, 13):
        try:
            html_text = http_text(AS_BASE + "/quran" + ("?page=%d" % page if page > 1 else ""), 15)
        except Exception:
            if page == 1:
                raise
            break
        new = 0
        for name, slug in assabile_parse_list(html_text):
            if slug not in found:
                found[slug] = name
                new += 1
        if new == 0:
            break
    rows = sorted([(n, s) for s, n in found.items()], key=lambda x: norm(x[0]))
    if not rows:
        raise ValueError(u"تعذّر قراءة قائمة القراء من assabile.com")
    try:
        if not os.path.isdir(CACHE_DIR):
            os.makedirs(CACHE_DIR)
        with open(path, "wb") as f:
            f.write(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass
    return rows


def assabile_parse_tracks(html_text, slug):
    """-> [(n, label, download_url)]"""
    out = []
    pat = re.compile(r'href="(?:https://ar\.assabile\.com)?/%s/quran/([a-z0-9-]+)"[^>]*>([^<]+)</a>' % re.escape(slug))
    dls = [m for m in re.finditer(r'href="((?:https://ar\.assabile\.com)?/download/(\d+))"', html_text)]
    names = [m for m in pat.finditer(html_text)]
    for i, m in enumerate(names):
        label = _unescape(m.group(2)).strip()
        dl = None
        for d in dls:                                # first download link after this surah link
            if d.start() > m.start():
                if i + 1 < len(names) and d.start() > names[i + 1].start():
                    break
                dl = d.group(1)
                break
        if not dl:
            continue
        if dl.startswith("/"):
            dl = AS_BASE + dl
        out.append((surah_no(label), label, dl))
    return out


def assabile_tracks(slug):
    return assabile_parse_tracks(http_text(AS_BASE + "/" + slug, 20), slug)


def follow_audio(url, timeout=15):
    """A download page / redirect -> the real audio URL (checks the content type)."""
    last = None
    for ctx in _contexts():
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": url})
            kw = {"timeout": timeout}
            if ctx is not None:
                kw["context"] = ctx
            r = urlopen(req, **kw)
            final = r.geturl()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "audio" in ctype or "octet-stream" in ctype or final.lower().split("?")[0].endswith(".mp3"):
                try:
                    r.close()
                except Exception:
                    pass
                return final
            body = r.read(400000).decode("utf-8", "replace")
            m = re.search(r'["\']((?:https?:)?//[^"\']+?\.mp3[^"\']*)["\']', body)
            if m:
                u = m.group(1)
                return "https:" + u if u.startswith("//") else u
            raise ValueError(u"لا يوجد ملف صوتي في صفحة التحميل")
        except Exception as e:
            last = e
    raise last


# ----------------------------------------------------------------- ourquraan.com
OQ_BASE = "https://ourquraan.com"
_OQ_SHEIKH = re.compile(r'href="(https?://(?:www\.)?ourquraan\.com/shyookh/([^"/]+)/?)"[^>]*>(.*?)</a>', re.S)


def ourquraan_parse_list(html_text):
    out, seen = [], set()
    for url, slug, inner in _OQ_SHEIKH.findall(html_text):
        name = _unescape(strip_tags(inner)).strip() or _unquote(slug).replace(u"-", u" ")
        if not re.search(u"[\\u0621-\\u064a]", name):
            name = _unquote(slug).replace(u"-", u" ")
        if slug in seen:
            continue
        seen.add(slug)
        out.append((name[:60], url if url.endswith("/") else url + "/"))
    return out


def ourquraan_reciters():
    rows = ourquraan_parse_list(http_text(OQ_BASE + "/", 20))
    if not rows:
        raise ValueError(u"تعذّر قراءة قائمة الشيوخ من ourquraan.com")
    return sorted(rows, key=lambda x: norm(x[0]))


def ourquraan_parse_tracks(html_text):
    """Every mp3 on the sheikh page -> [(n, label, url)]"""
    out, seen = [], set()
    for m in re.finditer(r'["\']((?:https?:)?//[^"\']+?\.mp3)["\']', html_text):
        url = m.group(1)
        url = "https:" + url if url.startswith("//") else url
        if url in seen:
            continue
        seen.add(url)
        before = html_text[max(0, m.start() - 500):m.start()]
        sm = re.findall(u"(سورة\\s+[\\u0621-\\u064a\\s]{2,25})", before)
        label = sm[-1].strip() if sm else _unquote(url.rsplit("/", 1)[-1])[:-4].replace(u"-", u" ").replace(u"_", u" ")
        out.append((surah_no(label), label, url))
    return out


def ourquraan_tracks(url):
    return ourquraan_parse_tracks(http_text(url, 20))


# ----------------------------------------------------------------- exact ayah timing (mp3quran ayat_timing API)
TIMING_READS = ["https://mp3quran.net/api/v3/ayat_timing/reads",
                "https://www.mp3quran.net/api/v3/ayat_timing/reads"]
TIMING_SURAH = "https://mp3quran.net/api/v3/ayat_timing?surah=%d&read=%d"


def timing_reads():
    """-> [{"id", "name", "rewaya", "folder", "count"}]  recitations whose every ayah is timed."""
    raw = cached_json(TIMING_READS, "timing_reads.json")
    out = []
    for r in (raw if isinstance(raw, list) else raw.get("reads", [])):
        try:
            folder = (r.get("folder_url") or "").strip()
            if not folder:
                continue
            out.append({"id": int(r["id"]), "name": (r.get("name") or u"").strip(),
                        "rewaya": (r.get("rewaya") or u"").strip(), "folder": folder.rstrip("/") + "/",
                        "count": int(r.get("soar_count") or 114)})
        except Exception:
            continue
    out.sort(key=lambda x: norm(x["name"]))
    return out


def _bare_name(name):
    t = norm(name or u"")
    for w in (u"الشيخ ", u"شيخ ", u"القارئ ", u"الدكتور ", u"د. "):
        t = t.replace(norm(w), u"")
    return u" ".join(t.split())


def timing_read_for(reads, reciter_name):
    """The timed recitation of the same reciter (Hafs first), or None."""
    want = _bare_name(reciter_name.split(u" - ")[0])
    if len(want) < 4:
        return None
    best = None
    for r in reads:
        have = _bare_name(r["name"])
        if have and (have == want or have in want or want in have):
            if best is None or (u"حفص" in r["rewaya"] and u"حفص" not in best["rewaya"]):
                best = r
    return best


def ayat_timing(read_id, n):
    """-> [(ayah, start_ms, end_ms)]  (ayah 0 = isti'adha / basmala)."""
    raw = cached_json(TIMING_SURAH % (n, read_id), "timing_%d_%d.json" % (read_id, n))
    out = []
    for x in (raw if isinstance(raw, list) else []):
        try:
            out.append((int(x["ayah"]), int(x["start_time"]), int(x["end_time"])))
        except Exception:
            continue
    out.sort(key=lambda t: t[1])
    if not out:
        raise ValueError("no timing")
    return out


def ayah_from_timing(timing, pos_ms):
    for a, s, e in timing:
        if s <= pos_ms < e:
            return max(1, a)
    if timing and pos_ms >= timing[-1][2]:
        return max(1, timing[-1][0])
    return 1
