# -*- coding: utf-8 -*-
"""3.1: the Quran quiz - questions made from the Quran text on the receiver (never typed by hand, so
never wrong), for the TV (the family answers with the colour buttons) and for Telegram (native quiz
polls: whoever answers sees at once whether he was right, and the bot keeps the scores).

question = {"kind", "q" (the question), "ayah" (text shown with it or ""), "opts" [4 or 2],
            "ok" (index of the right option), "why" (short explanation), "ref" (surah, ayah)}
"""
import random
import time
import unicodedata

try:
    from . import data, extras, studio
except Exception:                      # tests
    data = extras = studio = None

LEVELS = ((1, u"سهل"), (2, u"متوسط"), (3, u"صعب"))
KINDS = (("surah", u"من أي سورة هذه الآية؟"), ("complete", u"أكمل الآية"), ("count", u"عدد الآيات"),
         ("type", u"مكية أم مدنية"), ("juz", u"في أي جزء"), ("order", u"ترتيب السور"),
         ("next", u"الآية التالية"))
POINTS = {1: 1, 2: 2, 3: 3}
AR_DIGITS = u"٠١٢٣٤٥٦٧٨٩"


def plain(t):
    """Text without diacritics / Quran marks (for labels and Telegram options)."""
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Me", "Cf", "Cc"):
            continue
        if u"ۖ" <= ch <= u"ۭ":           # small high marks, sajda, rub el hizb...
            continue
        out.append(ch)
    s = u"".join(out)
    s = s.replace(u"ٱ", u"ا")                # alef wasla
    return u" ".join(s.split())


def words(t):
    return [w for w in plain(t).split() if w]


def ar(n):
    return u"".join(AR_DIGITS[int(c)] if c.isdigit() else c for c in u"%d" % n)


def _pool(level):
    """Surahs the questions are taken from: juz 30 (+ famous) for the easy level."""
    if level <= 1:
        return [1, 36, 55, 56, 67] + list(range(78, 115))
    if level == 2:
        return [1, 2, 12, 18, 19, 36, 55, 56, 67] + list(range(50, 115))
    return list(range(1, 115))


def _verses(n):
    return extras.local_verses(n) or []


def _counts():
    return studio.ayah_counts()


def _names_near(n, k, rnd):
    """k other surahs that sound like plausible answers (near in the mushaf)."""
    cand = [x for x in range(max(1, n - 12), min(114, n + 12) + 1) if x != n]
    rnd.shuffle(cand)
    return cand[:k]


def _pick_ayah(rnd, level, min_words=4):
    for _i in range(60):
        n = rnd.choice(_pool(level))
        vs = _verses(n)
        if not vs:
            continue
        a, t = rnd.choice(vs)
        if len(words(t)) >= min_words:
            return n, a, t
    return None


def q_surah(rnd, level):
    p = _pick_ayah(rnd, level, 5)
    if not p:
        return None
    n, a, t = p
    ws = words(t)
    shown = u" ".join(ws[:14]) + (u" ..." if len(ws) > 14 else u"")
    others = _names_near(n, 3, rnd)
    opts = [n] + others
    rnd.shuffle(opts)
    return {"kind": "surah", "q": u"من أي سورة هذه الآية؟", "ayah": shown,
            "opts": [u"سورة " + data.surah_name(x) for x in opts], "ok": opts.index(n),
            "why": u"سورة %s، الآية %s" % (data.surah_name(n), ar(a)), "ref": (n, a)}


def q_complete(rnd, level):
    p = _pick_ayah(rnd, level, 7 if level < 3 else 9)
    if not p:
        return None
    n, a, t = p
    ws = words(t)
    cut = max(3, min(len(ws) - 3, len(ws) // 2))
    head = u" ".join(ws[:cut])
    tail = u" ".join(ws[cut:cut + 6]) + (u" ..." if len(ws) > cut + 6 else u"")
    # wrong endings: the ends of other ayat of the same length, from the same / nearby surahs
    wrong = set()
    for _i in range(80):
        m = rnd.choice([n] * 3 + _names_near(n, 4, rnd))
        vs = _verses(m)
        if not vs:
            continue
        _b, t2 = rnd.choice(vs)
        w2 = words(t2)
        if len(w2) < 5:
            continue
        c2 = max(2, len(w2) // 2)
        e = u" ".join(w2[c2:c2 + 6]) + (u" ..." if len(w2) > c2 + 6 else u"")
        if e != tail and e[:20] != tail[:20]:
            wrong.add(e)
        if len(wrong) >= 3:
            break
    if len(wrong) < 3:
        return None
    opts = [tail] + list(wrong)[:3]
    rnd.shuffle(opts)
    return {"kind": "complete", "q": u"أكمل الآية الكريمة:", "ayah": head + u" ...",
            "opts": opts, "ok": opts.index(tail),
            "why": u"سورة %s، الآية %s" % (data.surah_name(n), ar(a)), "ref": (n, a)}


def q_count(rnd, level):
    n = rnd.choice(_pool(level))
    c = _counts()[n - 1]
    d = max(1, c // 8) if level < 3 else max(1, c // 15)
    opts = {c}
    while len(opts) < 4:
        opts.add(max(3, c + rnd.choice([-3, -2, -1, 1, 2, 3]) * d))
    opts = sorted(opts)
    return {"kind": "count", "q": u"كم عدد آيات سورة %s؟" % data.surah_name(n), "ayah": u"",
            "opts": [u"%s آية" % ar(x) for x in opts], "ok": opts.index(c),
            "why": u"سورة %s %s آية" % (data.surah_name(n), ar(c)), "ref": (n, 1)}


def q_type(rnd, level):
    n = rnd.choice(_pool(level))
    m = studio.SURAH_TYPE[n - 1] == "m"
    return {"kind": "type", "q": u"سورة %s: مكية أم مدنية؟" % data.surah_name(n), "ayah": u"",
            "opts": [u"مكية", u"مدنية"], "ok": 0 if m else 1,
            "why": u"سورة %s %s" % (data.surah_name(n), u"مكية" if m else u"مدنية"), "ref": (n, 1)}


def q_juz(rnd, level):
    p = _pick_ayah(rnd, max(2, level), 5)
    if not p:
        return None
    n, a, t = p
    j = extras.juz_of(n, a)
    ws = words(t)
    opts = {j}
    while len(opts) < 4:
        x = j + rnd.choice([-3, -2, -1, 1, 2, 3])
        if 1 <= x <= 30:
            opts.add(x)
    opts = sorted(opts)
    return {"kind": "juz", "q": u"في أي جزء تقع هذه الآية؟", "ayah": u" ".join(ws[:12]) + (u" ..." if len(ws) > 12 else u""),
            "opts": [u"الجزء %s" % ar(x) for x in opts], "ok": opts.index(j),
            "why": u"سورة %s الآية %s في الجزء %s" % (data.surah_name(n), ar(a), ar(j)), "ref": (n, a)}


def q_order(rnd, level):
    n = rnd.choice([x for x in _pool(level) if x < 114])
    right = n + 1
    others = [x for x in _names_near(n, 6, rnd) if x != right][:3]
    opts = [right] + others
    rnd.shuffle(opts)
    return {"kind": "order", "q": u"ما السورة التي تأتي بعد سورة %s في المصحف؟" % data.surah_name(n), "ayah": u"",
            "opts": [u"سورة " + data.surah_name(x) for x in opts], "ok": opts.index(right),
            "why": u"بعد سورة %s (%s) تأتي سورة %s (%s)" % (data.surah_name(n), ar(n), data.surah_name(right), ar(right)),
            "ref": (right, 1)}


def q_next(rnd, level):
    for _i in range(40):
        p = _pick_ayah(rnd, level, 3)
        if not p:
            return None
        n, a, t = p
        vs = dict(_verses(n))
        if a + 1 not in vs:
            continue
        nxt = words(vs[a + 1])
        right = u" ".join(nxt[:6]) + (u" ..." if len(nxt) > 6 else u"")
        wrong = []
        for b in rnd.sample(sorted(vs), min(len(vs), 12)):
            if b in (a, a + 1):
                continue
            w2 = words(vs[b])
            e = u" ".join(w2[:6]) + (u" ..." if len(w2) > 6 else u"")
            if e != right and e not in wrong:
                wrong.append(e)
            if len(wrong) == 3:
                break
        if len(wrong) < 3:
            continue
        ws = words(t)
        opts = [right] + wrong
        rnd.shuffle(opts)
        return {"kind": "next", "q": u"ما الآية التي تلي هذه الآية؟", "ayah": u" ".join(ws[-12:]),
                "opts": opts, "ok": opts.index(right),
                "why": u"سورة %s، الآيتان %s و%s" % (data.surah_name(n), ar(a), ar(a + 1)), "ref": (n, a + 1)}
    return None


MAKERS = {"surah": q_surah, "complete": q_complete, "count": q_count, "type": q_type,
          "juz": q_juz, "order": q_order, "next": q_next}
MIX = {1: ["surah", "surah", "complete", "type", "count", "order", "next"],
       2: ["surah", "complete", "complete", "next", "juz", "count", "type", "order"],
       3: ["surah", "complete", "complete", "next", "next", "juz", "count"]}


def make(level=1, kind=None, seed=None, avoid=None):
    """A new question (None only if the Quran text is missing)."""
    rnd = random.Random(seed if seed is not None else time.time())
    for _i in range(25):
        k = kind or rnd.choice(MIX.get(level, MIX[1]))
        try:
            q = MAKERS[k](rnd, level)
        except Exception:
            q = None
        if q and (not avoid or q["q"] + q.get("ayah", u"") not in avoid):
            q["level"] = level
            return q
    return None


# ------------------------------------------------------------------ telegram poll limits
def for_poll(q):
    """(question <= 300, options each <= 100, explanation <= 200) for sendPoll type=quiz."""
    text = q["q"]
    if q.get("ayah"):
        text = u"%s\n﴿%s﴾" % (q["q"], q["ayah"])
    if len(text) > 295:
        text = text[:292] + u"...﴾"
    opts = [o if len(o) <= 100 else o[:97] + u"..." for o in q["opts"]]
    return u"🧠 " + text, opts, q.get("why", u"")[:200]


# ------------------------------------------------------------------ scores
def _week():
    import datetime
    y, w, _d = datetime.date.today().isocalendar()[:3]
    return u"%d-%02d" % (y, w)


def score(cfg, who, right, level=1):
    """Add an answer of `who` (a name).  Weekly and all-time points."""
    st = cfg.setdefault("quiz", {})
    wk = _week()
    if st.get("week") != wk:
        if st.get("weekly"):
            st["last_week"] = top(st.get("weekly"), 3)
        st["week"], st["weekly"] = wk, {}
    for book in (st.setdefault("all", {}), st["weekly"]):
        r = book.setdefault(who, [0, 0, 0])            # points, answers, right
        r[1] += 1
        if right:
            r[0] += POINTS.get(level, 1)
            r[2] += 1
    return st["all"][who]


def top(book, k=10):
    rows = sorted((book or {}).items(), key=lambda kv: (-kv[1][0], -kv[1][2], kv[0]))
    return [(name, r[0], r[1], r[2]) for name, r in rows[:k]]


def board_text(cfg, k=10):
    st = cfg.get("quiz") or {}
    medals = [u"🥇", u"🥈", u"🥉"]
    out = [u"🏆 ترتيب المسابقة هذا الأسبوع"]
    rows = top(st.get("weekly"), k)
    if not rows:
        out.append(u"لا إجابات بعد هذا الأسبوع - اكتب /quiz")
    for i, (name, pts, n, ok) in enumerate(rows):
        out.append(u"%s %s: %d نقطة (%d/%d)" % (medals[i] if i < 3 else u"%d." % (i + 1), name, pts, ok, n))
    allr = top(st.get("all"), 3)
    if allr:
        out.append(u"")
        out.append(u"⭐ الأعلى دائماً: " + u"، ".join(u"%s (%d)" % (n_, p_) for n_, p_, _a, _b in allr))
    if st.get("last_week"):
        out.append(u"🎖 بطل الأسبوع الماضي: %s" % st["last_week"][0][0])
    return u"\n".join(out)
