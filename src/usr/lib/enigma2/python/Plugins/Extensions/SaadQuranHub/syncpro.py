# -*- coding: utf-8 -*-
"""3.1: exact ayah timing for recordings that have none.

Three sources, best first:
  * "tap"     - the listener pressed OK at the start of each ayah once (QHPlayer menu);
  * "silence" - the receiver listened to the file itself: ffmpeg finds the pauses between the ayat
                (silencedetect, in the background, lowest priority), and they are matched to the
                ayat by their expected lengths (dynamic programming), with a confidence check;
  * the official timing of mp3quran / quran.com (handled in plugin.py, not here).

Timings are kept for ever on the disk (QuranHub/sync/<md5 of the file>.json), with a copy in RAM.
A manual offset per reciter (+/- seconds) is applied on top of any timing.
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time

try:
    from . import data, studio
except Exception:                      # tests
    data = studio = None

_MEM = {}
_LOCK = threading.Lock()
_JOBS = {"busy": None, "done": set(), "failed": {}}
FFMPEG_PATHS = ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg")


# ------------------------------------------------------------------ storage
def key_of(url):
    """Same file whatever the query string / local server port."""
    u = (url or u"").split("?")[0]
    m = re.search(r"/file/(.+)$", u)               # localserve urls carry the real path
    if m:
        u = m.group(1)
    return hashlib.md5(u.encode("utf-8")).hexdigest()


def _dir():
    try:
        return data.home_dir("sync")
    except Exception:
        return None


def get(url):
    """{"n","dur","t":[[a,s_ms,e_ms],...],"src","q"} for this file, or None."""
    k = key_of(url)
    if k in _MEM:
        return _MEM[k]
    v = None
    d = _dir()
    if d:
        try:
            with open(os.path.join(d, k + ".json")) as f:
                v = json.load(f)
        except Exception:
            v = None
    _MEM[k] = v
    return v


def put(url, n, dur, timing, src, q=1.0):
    v = {"n": int(n), "dur": float(dur), "t": [[int(a), int(s), int(e)] for a, s, e in timing],
         "src": src, "q": round(float(q), 3), "ts": int(time.time())}
    k = key_of(url)
    old = get(url)
    if old and old.get("src") == "tap" and src != "tap":
        return old                                # the listener's own sync wins
    _MEM[k] = v
    d = _dir()
    if d:
        try:
            tmp = os.path.join(d, k + ".tmp")
            with open(tmp, "w") as f:
                json.dump(v, f)
            os.rename(tmp, os.path.join(d, k + ".json"))
        except Exception:
            pass
    return v


def forget(url):
    k = key_of(url)
    _MEM[k] = None
    d = _dir()
    if d:
        try:
            os.remove(os.path.join(d, k + ".json"))
        except Exception:
            pass


def count():
    d = _dir()
    try:
        return len([f for f in os.listdir(d) if f.endswith(".json")]) if d else 0
    except Exception:
        return 0


# ------------------------------------------------------------------ using a timing
def usable(v, n, length):
    """Is this stored timing for this surah and (about) this length of file?"""
    if not v or int(v.get("n", 0)) != int(n) or not v.get("t"):
        return False
    if length and length > 0 and v.get("dur"):
        return abs(float(v["dur"]) - length) / float(v["dur"]) < 0.03
    return True


def ayah_at(v, pos_s, offset=0.0):
    ms = (pos_s + offset) * 1000.0
    t = v["t"]
    for a, s, e in t:
        if s <= ms < e:
            return max(1, a)
    if ms >= t[-1][2]:
        return max(1, t[-1][0])
    return max(1, t[0][0])


def bounds(v, a, offset=0.0):
    for aa, s, e in v["t"]:
        if aa == a:
            return max(0.0, s / 1000.0 - offset), e / 1000.0 - offset
    return None


def offset_for(cfg, reciter):
    try:
        return float((cfg.get("sync_off") or {}).get(reciter or u"", 0.0))
    except Exception:
        return 0.0


def set_offset(cfg, reciter, delta=None, value=None):
    offs = cfg.setdefault("sync_off", {})
    cur = float(offs.get(reciter or u"", 0.0))
    cur = value if value is not None else round(cur + (delta or 0.0), 2)
    cur = max(-10.0, min(10.0, cur))
    if abs(cur) < 0.01:
        offs.pop(reciter or u"", None)
    else:
        offs[reciter or u""] = cur
    return cur


# ------------------------------------------------------------------ tapping the ayat
class Tapper(object):
    """The listener presses OK at the start of each ayah.  start(n, first_pos) ... tap(pos) ...
    finish(dur) -> timing (the ayat not tapped are filled in by their expected lengths)."""

    def __init__(self, n, total, weights):
        self.n, self.total = n, total
        self.w = dict(weights)
        self.marks = []                  # [(ayah, start_s)]

    def next_ayah(self):
        return len(self.marks) + 1

    def tap(self, pos):
        if self.marks and pos <= self.marks[-1][1] + 0.3:
            return None                  # double press
        if len(self.marks) >= self.total:
            return None
        self.marks.append((len(self.marks) + 1, float(pos)))
        return self.marks[-1][0]

    def undo(self):
        if self.marks:
            self.marks.pop()

    def done(self):
        return len(self.marks) >= self.total

    def timing(self, dur):
        if not self.marks:
            return None
        starts = [s for _a, s in self.marks]
        rest = list(range(len(starts) + 1, self.total + 1))
        if rest:                          # spread the remaining ayat by their weights
            t0 = starts[-1]
            # the last tapped ayah also needs an end: share the remaining time by weight
            ws = [self.w.get(len(starts), 30)] + [self.w.get(a, 30) for a in rest]
            span = max(1.0, dur - t0)
            acc = t0
            tot = float(sum(ws))
            for i, a in enumerate(rest):
                acc += span * ws[i] / tot
                starts.append(acc)
        out = []
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else dur
            out.append((i + 1, int(s * 1000), int(max(s + 0.2, e) * 1000)))
        return out


# ------------------------------------------------------------------ listening for the pauses
def ffmpeg_path():
    for p in FFMPEG_PATHS:
        if os.path.exists(p):
            return p
    return None


SIL_RE = re.compile(r"silence_(start|end): *(-?[0-9.]+)(?: \| silence_duration: *([0-9.]+))?")
DUR_RE = re.compile(r"Duration: *(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_silences(text):
    """ffmpeg silencedetect output -> (duration, [(start, end), ...])."""
    dur = 0.0
    m = DUR_RE.search(text)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    out, start = [], None
    for kind, v, _d in SIL_RE.findall(text):
        v = float(v)
        if kind == "start":
            start = max(0.0, v)
        elif start is not None:
            out.append((start, v))
            start = None
    if start is not None and dur:
        out.append((start, dur))
    return dur, out


def detect(src, timeout=900, noise="-33dB", min_sil=0.3):
    """Run ffmpeg silencedetect on a file or URL (lowest CPU / IO priority)."""
    ff = ffmpeg_path()
    if not ff:
        raise IOError("ffmpeg")
    cmd = [ff, "-hide_banner", "-nostats", "-vn", "-i", src, "-ac", "1", "-ar", "8000",
           "-af", "silencedetect=noise=%s:d=%s" % (noise, min_sil), "-f", "null", "-"]
    if os.path.exists("/usr/bin/nice"):
        cmd = ["/usr/bin/nice", "-n", "19"] + cmd
    if os.path.exists("/usr/bin/ionice"):
        cmd = ["/usr/bin/ionice", "-c", "3"] + cmd
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = time.time()
    err = []
    while True:
        line = p.stderr.readline()
        if not line:
            break
        err.append(line.decode("utf-8", "ignore"))
        if time.time() - t0 > timeout:
            p.kill()
            raise IOError("timeout")
    p.wait()
    return parse_silences(u"".join(err))


def align(n_ayat, weights, dur, sils, lead_weight=0.0):
    """Choose the pauses that end each ayah.

    weights: expected relative length of ayah 1..N; lead_weight: of what comes before ayah 1
    (isti'adha / basmala).  sils: [(start, end)] of the pauses.  Returns (timing [(a, s_ms, e_ms)],
    quality 0..1) or (None, 0).  The recitation can start after a lead-in: each of the first few
    pauses (or none) is tried as the end of the lead-in, the best fit wins."""
    N = n_ayat
    if N < 1 or dur <= 0:
        return None, 0.0
    cands = [((s + e) / 2.0, e - s, s, e) for s, e in sils if 0.5 < (s + e) / 2.0 < dur - 0.5]
    if N == 1:
        return [(1, 0, int(dur * 1000))], 0.5
    if len(cands) < N - 1:
        return None, 0.0
    best = (None, 1e18, 0.0)
    starts = [(0.0, None)] + [(c[3], i) for i, c in enumerate(cands[:4])]
    for t0, skip in starts:
        if lead_weight <= 0 and skip is not None:
            continue
        cs = [c for i, c in enumerate(cands) if (skip is None or i > skip) and c[0] > t0 + 0.3]
        if len(cs) < N - 1:
            continue
        r = _dp(weights, cs, t0, dur)
        if r and r[1] < best[1]:
            best = (r[0], r[1], t0)
    chosen, cost, t0 = best
    if chosen is None:
        return None, 0.0
    bnd = [t0] + [c[0] for c in chosen] + [dur]
    timing = [(a + 1, int(bnd[a] * 1000), int(bnd[a + 1] * 1000)) for a in range(N)]
    # quality: mean squared log-error of the ayah lengths (0 = perfect)
    q = max(0.0, min(1.0, 1.0 - cost / 0.35))
    return timing, q


def _dp(weights, cs, t0, dur, win=14):
    """Segment [t0, dur] at N-1 of the pauses `cs` so that each ayah lasts about its weight x the
    average speed: min sum (ln(len / expected))^2  - a small bonus for longer pauses.
    Local (ratio) costs, so a reciter slowing down or speeding up does not drift the match."""
    import math
    N, M = len(weights), len(cs)
    K = N - 1
    if M < K:
        return None
    sp = (dur - t0) / float(sum(weights))
    INF = 1e18
    T = [c[0] for c in cs]

    def seg(d, w):
        if d <= 0.05:
            return INF
        x = math.log(d / (w * sp))
        return x * x

    prev = None
    back = []
    for k in range(K):
        if k % 16 == 15:
            time.sleep(0.002)             # let the GUI thread run (the GIL)
        cur = [INF] * M
        arg = [-1] * M
        lo = k                          # boundary k needs k pauses before it
        hi = M - (K - k)                # and K-k-1 after it
        for j in range(lo, hi + 1):
            bonus = min(cs[j][1], 1.5) * 0.08
            if k == 0:
                c = seg(T[j] - t0, weights[0])
                if c < INF:
                    cur[j], arg[j] = c - bonus, -1
                continue
            bestc, besti = INF, -1
            for i in range(max(k - 1, j - win), j):
                if prev[i] >= INF:
                    continue
                c = prev[i] + seg(T[j] - T[i], weights[k])
                if c < bestc:
                    bestc, besti = c, i
            if besti >= 0:
                cur[j], arg[j] = bestc - bonus, besti
        back.append(arg)
        prev = cur
    # the last ayah runs to the end
    bestc, bj = INF, -1
    for j in range(M):
        if prev[j] < INF:
            c = prev[j] + seg(dur - T[j], weights[-1])
            if c < bestc:
                bestc, bj = c, j
    if bj < 0:
        return None
    chosen = []
    j = bj
    for k in range(K - 1, -1, -1):
        chosen.append(cs[j])
        j = back[k][j]
    chosen.reverse()
    bnd = [t0] + [c[0] for c in chosen] + [dur]
    err = sum(seg(bnd[a + 1] - bnd[a], weights[a]) for a in range(N)) / float(N)
    return chosen, err


def surah_weights(n):
    """(weights of ayah 1..N, weight of the lead-in) from studio.ayah_weights."""
    w = studio.ayah_weights(n)
    lead = sum(x for a, x in w if a == 0)
    return [x for a, x in w if a > 0], lead


class AutoSync(object):
    """One background job at a time: listen to a surah file and store its ayah timing."""

    def __init__(self):
        self.thread = None
        self.last = None

    def want(self, url, src, n, length):
        """(GUI thread) a surah is playing without exact timing: listen to it in the background."""
        if not ffmpeg_path() or not n or not url:
            return False
        k = key_of(url)
        if k in _JOBS["done"] or _JOBS["failed"].get(k, 0) >= 2 or get(url):
            return False
        if self.thread is not None and self.thread.is_alive():
            return False
        _JOBS["busy"] = k

        def run():
            try:
                w, lead = surah_weights(n)
                timing, q = None, 0.0
                # quiet studio recordings first; then for recordings with reverb / noise a higher floor
                for noise, ms in (("-33dB", 0.3), ("-28dB", 0.25), ("-24dB", 0.2)):
                    dur, sils = detect(src, noise=noise, min_sil=ms)
                    if length and (not dur or abs(dur - length) / max(1.0, length) > 0.05):
                        dur = dur or length
                    if len(sils) < len(w) - 1:
                        continue
                    t_, q_ = align(len(w), w, dur, sils, lead)
                    if t_ and q_ > q:
                        timing, q = t_, q_
                    if q >= 0.8:
                        break
                self.last = (n, q, len(sils))
                if timing and q >= 0.55:
                    put(url, n, dur, timing, "silence", q)
                    _JOBS["done"].add(k)
                else:
                    _JOBS["failed"][k] = _JOBS["failed"].get(k, 0) + 2
            except Exception as e:
                self.last = (n, 0.0, repr(e))
                _JOBS["failed"][k] = _JOBS["failed"].get(k, 0) + 1
            finally:
                _JOBS["busy"] = None
        self.thread = threading.Thread(target=run)
        self.thread.daemon = True
        self.thread.start()
        return True

    def busy(self):
        return self.thread is not None and self.thread.is_alive()


AUTO = AutoSync()
