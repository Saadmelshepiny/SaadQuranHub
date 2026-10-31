# -*- coding: utf-8 -*-
"""Self-diagnostic for Quran Hub (pure Python - the enigma2 specific probes are passed in as hooks).

Every check yields (state, title, detail, hint):  state is True (OK), False (failed) or None (warning).
"""
from __future__ import print_function

import os
import socket
import sys
import time

from . import data, extras

OK, BAD, WARN = True, False, None

SITES = [
    (u"mp3quran.net (القراء والإذاعات)", "https://mp3quran.net/api/v3/radios?language=ar", 2048),
    (u"quran.com (API)", "https://api.quran.com/api/v4/chapters?language=ar", 2048),
    (u"surahquran.com", "https://surahquran.com/", 4096),
    (u"islamweb.net (الصوتيات)", "https://audio.islamweb.net/audio/index.php?page=qareelast", 4096),
    (u"way2quran.com", "https://way2quran.com/ar/reciters", 4096),
    (u"alquran.cloud (نص احتياطي)", "https://api.alquran.cloud/v1/surah/112/quran-simple", 2048),
    (u"jsdelivr (تفاسير احتياطية)", extras.SPA5K[0] % ("ar-tafsir-muyassar", 112), 2048),
    (u"everyayah.com (صوت الآيات - استوديو الحفظ)", "https://everyayah.com/data/Alafasy_128kbps/001001.mp3", 2048),
    (u"mp3quran ayat_timing (تزامن الآيات)", "https://mp3quran.net/api/v3/ayat_timing/reads", 2048),
    (u"api.quranpedia.net (موسوعة المصاحف)", "https://api.quranpedia.net/v1/reciters", 2048),
    (u"tvquran.com (مصاحف تلفزيون القرآن)", "https://www.tvquran.com/ar/scholar/94/profile/", 4096),
    (u"ar.assabile.com (قراء السبيل)", "https://ar.assabile.com/quran", 4096),
    (u"ourquraan.com (شيوخ قرآننا)", "https://ourquraan.com/", 4096),
    (u"t.me (قنوات تليجرام العامة)", "https://t.me/s/El_minshawy", 4096),
    (u"cdn.islamic.network (صوت بديل)", "https://cdn.islamic.network/quran/audio-surah/128/ar.alafasy/112.mp3", 2048),
]


def _peek(url, nbytes, timeout=12):
    """Open url and read only the first bytes -> (bytes read, seconds)."""
    t0 = time.time()
    last = None
    for ctx in data._contexts():
        try:
            req = data.Request(url, headers={"User-Agent": data.UA, "Accept": "*/*"})
            kw = {"timeout": timeout}
            if ctx is not None:
                kw["context"] = ctx
            r = data.urlopen(req, **kw)
            chunk = r.read(nbytes)
            try:
                r.close()
            except Exception:
                pass
            return len(chunk), time.time() - t0
        except Exception as e:
            last = e
    raise last


def _err(e):
    t = u"%s" % (e,)
    return t if len(t) < 90 else t[:87] + u"..."


def check_system():
    out = []
    out.append((OK, u"النظام", u"Python %s" % sys.version.split()[0], u""))
    try:
        year = time.localtime().tm_year
        if year < 2024:
            out.append((BAD, u"ساعة الجهاز", u"السنة %d - الوقت غير مضبوط" % year,
                        u"اضبط الوقت (أو فعّل ضبطه من القمر/الإنترنت) وإلا فشلت اتصالات https وأوقات الصلاة"))
        else:
            out.append((OK, u"ساعة الجهاز", time.strftime("%Y-%m-%d %H:%M"), u""))
    except Exception as e:
        out.append((WARN, u"ساعة الجهاز", _err(e), u""))
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
        free = (mem.get("MemAvailable") or mem.get("MemFree", 0)) // 1024
        out.append((OK if free > 60 else WARN, u"الذاكرة الحرة", u"%d MB" % free,
                    u"" if free > 60 else u"الذاكرة قليلة - أغلق إضافات أخرى"))
    except Exception:
        pass
    try:
        import ssl
        out.append((OK, u"تشفير https", ssl.OPENSSL_VERSION, u""))
    except Exception as e:
        out.append((BAD, u"تشفير https", _err(e), u"الصورة بلا مكتبة ssl - المواقع لن تعمل"))
    return out


def check_internet():
    out = []
    try:
        t0 = time.time()
        ip = socket.gethostbyname("mp3quran.net")
        out.append((OK, u"DNS", u"mp3quran.net -> %s (%.1f ث)" % (ip, time.time() - t0), u""))
    except Exception as e:
        out.append((BAD, u"DNS", _err(e), u"تحقق من كابل الشبكة وإعداد DNS في الراوتر (جرّب 8.8.8.8)"))
    try:
        t0 = time.time()
        s = socket.create_connection(("1.1.1.1", 443), 6)
        s.close()
        out.append((OK, u"الاتصال بالإنترنت", u"%.1f ث" % (time.time() - t0), u""))
    except Exception as e:
        out.append((BAD, u"الاتصال بالإنترنت", _err(e), u"لا يوجد إنترنت أو الراوتر يحجب الاتصال"))
    return out


def check_site(title, url, nbytes):
    try:
        n, secs = _peek(url, nbytes)
        if n <= 0:
            return (BAD, title, u"رد فارغ", u"الموقع يرد بلا محتوى")
        return (OK, title, u"%.1f ث" % secs, u"")
    except Exception as e:
        return (BAD, title, _err(e), u"الموقع محجوب أو متوقف - البلوجين سيستعمل مصدراً بديلاً تلقائياً")


def check_reader():
    """The three features reported as broken: text, tafsir, translation - tested the way the reader does."""
    out = []
    ok = extras.local_quran_ok()
    out.append((OK if ok else BAD, u"نص المصحف (داخل البلوجين)",
                u"6236 آية" if ok else u"ملفات qdata ناقصة أو تالفة",
                u"" if ok else u"أعد تثبيت البلوجين (مجلد qdata)"))
    try:
        from . import studio
        cats = studio.adhkar_categories()
        out.append((OK, u"الأذكار (داخل البلاجين)", u"%d باباً" % len(cats), u""))
    except Exception as e:
        out.append((BAD, u"الأذكار (داخل البلاجين)", _err(e), u"أعد تثبيت البلاجين (qdata/adhkar.json.gz)"))
    for key, title, _slug, _alq, _qid, bundled in extras.TAFSIRS:
        have = extras.tafsir_available(key)
        if have:
            out.append((OK, title, u"موجود بالكامل على الجهاز", u""))
        else:
            out.append((WARN, title, u"غير مثبّت - يُنزَّل سورة سورة عند الطلب",
                        u"ثبّت حزمة التفاسير أو نزّلها من (القراءة > تحميل التفاسير)"))
    for label, fn in ((u"تجربة قراءة النص", lambda: extras.reader_load(112, "text")),
                      (u"تجربة التفسير", lambda: extras.reader_load(112, "tafsir", "muyassar")),
                      (u"تجربة الترجمة", lambda: extras.reader_load(112, "translation"))):
        try:
            blocks, note = fn()
            out.append((OK, label, u"%d آيات | %s" % (len(blocks), note), u""))
        except Exception as e:
            out.append((BAD, label, _err(e), u"أرسل ملف التقرير للمطوّر"))
    return out


def check_disk():
    out = []
    try:
        d = data.record_dir()
    except Exception:
        d = None
    if not d:
        out.append((WARN, u"القرص (HDD/USB)", u"غير متصل أو غير مركّب",
                    u"بدونه: لا تسجيل ولا تنزيل ولا حفظ للقوائم بعد إعادة التشغيل"))
        return out
    try:
        st = os.statvfs(d)
        free = st.f_bavail * st.f_frsize / 1048576.0
        out.append((OK if free > 200 else WARN, u"القرص", u"%s - متاح %.0f MB" % (d, free),
                    u"" if free > 200 else u"المساحة قليلة"))
        test = os.path.join(d, ".wtest")
        with open(test, "wb") as f:
            f.write(b"x")
        os.remove(test)
        out.append((OK, u"الكتابة على القرص", u"تعمل", u""))
    except Exception as e:
        out.append((BAD, u"الكتابة على القرص", _err(e), u"القرص للقراءة فقط أو ممتلئ"))
    return out


def check_tools():
    out = []
    for cmd, why, bad in (("exteplayer3", u"مشغّل 5002", u"ثبّت exteplayer3 (أو استخدم gstreamer)"),
                          ("gst-launch-1.0", u"الصوت المنفصل فوق القناة", u"بدونه لا يعمل وضع (قناة + صوت منفصل)"),
                          ("ffmpeg", u"تحويل صيغ التسجيل", u"بدونه: التسجيل بالصيغة الأصلية فقط")):
        p = data.which(cmd)
        out.append((OK if p else WARN, u"%s (%s)" % (cmd, why), p or u"غير موجود", u"" if p else bad))
    return out


def run(hooks=None, progress=None):
    """Run all checks.  hooks: {'enigma': callable -> [(state,title,detail,hint)]}."""
    rows = []

    def add(items):
        for r in items:
            rows.append(r)
            if progress:
                try:
                    progress(r)
                except Exception:
                    pass

    add(check_system())
    add(check_internet())
    for title, url, nb in SITES:
        add([check_site(title, url, nb)])
    add(check_reader())
    add(check_disk())
    add(check_tools())
    if hooks and hooks.get("enigma"):
        try:
            add(hooks["enigma"]())
        except Exception as e:
            add([(WARN, u"فحوصات الجهاز", _err(e), u"")])
    return rows


def summary(rows):
    bad = len([r for r in rows if r[0] is False])
    warn = len([r for r in rows if r[0] is None])
    ok = len([r for r in rows if r[0] is True])
    return ok, warn, bad


def line(r):
    mark = u"✔" if r[0] is True else (u"✘" if r[0] is False else u"!")
    s = u"%s %s: %s" % (mark, r[1], r[2])
    if r[0] is not True and r[3]:
        s += u"\n     ← " + r[3]
    return s


def report_text(rows):
    ok, warn, bad = summary(rows)
    head = u"تقرير فحص Saad Quran Hub  %s\nناجح %d  |  تحذير %d  |  فشل %d\n\n" % (
        time.strftime("%Y-%m-%d %H:%M"), ok, warn, bad)
    tail = u"\n\nسجل مصادر القراءة:\n" + u"\n".join(
        u"%s %s %s" % (u"✔" if o else u"✘", w, d) for _t, w, o, d in extras.LOG[-25:])
    return head + u"\n".join(line(r) for r in rows) + tail


def save_report(rows):
    """Write the report next to the recordings (USB/HDD) and to /tmp. -> list of paths"""
    text = report_text(rows).encode("utf-8")
    paths = []
    cands = ["/tmp/quranhub_diag.txt"]
    try:
        d = data.record_dir()
        if d:
            cands.insert(0, os.path.join(d, "quranhub_diag.txt"))
    except Exception:
        pass
    for p in cands:
        try:
            with open(p, "wb") as f:
                f.write(text)
            paths.append(p)
        except Exception:
            pass
    return paths
