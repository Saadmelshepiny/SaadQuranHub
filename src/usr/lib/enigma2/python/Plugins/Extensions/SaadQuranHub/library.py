# -*- coding: utf-8 -*-
"""Saad Quran Hub - 'My library': the downloaded files, one folder per reciter, and the background
jobs that work on them (format conversion, cleaning the sound, copying to a USB stick, tidying old
downloads).  Pure Python (no enigma2 imports) so it can be unit-tested."""
from __future__ import print_function

import os
import re
import shutil
import threading

from . import data, extras, localserve

LOOSE = u"ملفات متفرقة"
_NUM_RE = re.compile(r"^(\d{1,3})\b")


def surah_from_name(name):
    """Surah number from a file name ('001 الفاتحة', 'مشاري - سورة الكهف', '018.mp3'...) or None."""
    base = os.path.splitext(os.path.basename(name))[0]
    m = _NUM_RE.match(base)
    if m and 1 <= int(m.group(1)) <= 114:
        return int(m.group(1))
    n = extras.surah_of_title(base)
    return n or None


def reciter_from_name(name):
    base = os.path.splitext(os.path.basename(name))[0]
    if u" - " in base:
        return base.split(u" - ")[0].strip()
    return None


def file_name(n, ext):
    """'018 الكهف.mp3' - sorts in mushaf order on every player (car radios too)."""
    return u"%03d %s%s" % (n, data.surah_name(n), ext)


def reciter_folder(root, reciter):
    return os.path.join(root, data.safe_name(reciter or LOOSE))


def scan(root=None):
    """-> [(reciter, folder, [(surah or None, label, path, size)])] sorted by reciter.
    Files in a reciter's folder belong to him; loose files are grouped by the name in front of
    ' - ' (old downloads) or listed as 'loose files'."""
    root = root or extras.download_dir()
    if not root or not os.path.isdir(root):
        return []
    groups = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "cache"]
        rel = os.path.relpath(dirpath, root)
        for fn in files:
            if not fn.lower().endswith(extras.AUDIO_EXT) or fn.endswith(".part"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if rel != ".":
                rec, folder = rel.split(os.sep)[0], os.path.join(root, rel.split(os.sep)[0])
            else:
                rec = reciter_from_name(fn) or LOOSE
                folder = root
            n = surah_from_name(fn)
            label = (u"%d. سورة %s" % (n, data.surah_name(n))) if n else os.path.splitext(fn)[0]
            groups.setdefault(rec, (folder, []))[1].append((n, label, p, size, os.path.splitext(fn)[1].lower()))
    out = []
    for rec, (folder, items) in groups.items():
        items.sort(key=lambda x: (x[0] or 999, x[1]))
        out.append((rec, folder, items))
    out.sort(key=lambda g: (g[0] == LOOSE, g[0]))
    return out


def summary(items):
    size = sum(x[3] for x in items)
    exts = sorted(set(x[4].lstrip(".").upper() for x in items))
    return u"%d ملف • %s • %s" % (len(items), data.fmt_bytes(size), u"/".join(exts))


def organize(root=None):
    """Move old downloads ('reciter - سورة X.mp3' at the top of the folder) into a folder per reciter
    with mushaf-order names.  -> number of files moved."""
    root = root or extras.download_dir()
    if not root:
        return 0
    moved = 0
    for fn in sorted(os.listdir(root)):
        p = os.path.join(root, fn)
        if not os.path.isfile(p) or not fn.lower().endswith(extras.AUDIO_EXT):
            continue
        rec, n = reciter_from_name(fn), surah_from_name(fn)
        if not rec or not n:
            continue
        folder = reciter_folder(root, rec)
        try:
            if not os.path.isdir(folder):
                os.makedirs(folder)
            dst = os.path.join(folder, file_name(n, os.path.splitext(fn)[1].lower()))
            if os.path.exists(dst):
                continue
            shutil.move(p, dst)
            moved += 1
        except Exception:
            continue
    return moved


def usb_targets(exclude=None):
    """Mounted, writable disks other than the one holding the library: [(label, path)]."""
    out = []
    ex = os.path.realpath(exclude) if exclude else None
    for b in sorted(set(["/media/usb", "/media/usb0", "/media/usb1", "/media/usb2", "/media/hdd", "/media/mmc",
                         "/media/sdcard"] + [os.path.join("/media", d) for d in _listdir("/media")])):
        if not os.path.isdir(b) or not os.access(b, os.W_OK):
            continue
        try:
            if not os.path.ismount(b):
                continue
        except Exception:
            continue
        rb = os.path.realpath(b)
        if ex and (ex == rb or ex.startswith(rb + os.sep)):
            continue
        free = data.disk_free(b)
        out.append((u"%s  (%s متاحة)" % (b, data.fmt_bytes(free) if free is not None else u"?"), b))
    return out


def _listdir(d):
    try:
        return os.listdir(d)
    except Exception:
        return []


class Jobs(object):
    """Background jobs, one at a time: [(title, [step callables])].  The step functions run in a
    thread; progress is read by the GUI (text()) and reported through on_event(kind, title, detail)."""

    def __init__(self):
        self.queue = []
        self.title = None
        self.i = self.n = 0
        self.errors = []
        self.stop_flag = False
        self.lock = threading.Lock()
        self.thread = None
        self.on_event = None

    def add(self, title, steps):
        with self.lock:
            self.queue.append((title, list(steps)))
        if self.thread is None or not self.thread.is_alive():
            self.stop_flag = False
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()

    def busy(self):
        return self.title is not None or bool(self.queue)

    def cancel(self):
        self.stop_flag = True
        with self.lock:
            self.queue = []

    def text(self):
        if self.title is None:
            return u""
        return u"⚙ %s (%d/%d)" % (self.title, self.i, self.n)

    def _emit(self, kind, title, detail=u""):
        if self.on_event:
            try:
                self.on_event(kind, title, detail)
            except Exception:
                pass

    def _run(self):
        while not self.stop_flag:
            with self.lock:
                if not self.queue:
                    break
                title, steps = self.queue.pop(0)
            self.title, self.i, self.n = title, 0, len(steps)
            bad = 0
            for st in steps:
                if self.stop_flag:
                    break
                try:
                    st()
                except Exception as e:
                    bad += 1
                    self.errors.append(u"%s: %s" % (title, e))
                self.i += 1
            self.title = None
            self._emit("job", title, u"%d/%d%s" % (self.n - bad, self.n, (u" (%d فشل)" % bad) if bad else u""))


# ------------------------------------------------------------------ job steps
def convert_step(path, fmt, keep=False):
    def run():
        dst = data.transcode(path, fmt)
        if not keep and os.path.abspath(dst) != os.path.abspath(path):
            os.remove(path)
    return run


def copy_step(path, dest_dir, n=None):
    def run():
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
        name = file_name(n, os.path.splitext(path)[1].lower()) if n else os.path.basename(path)
        dst = os.path.join(dest_dir, name)
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(path):
            return
        free = data.disk_free(dest_dir)
        if free is not None and free < os.path.getsize(path) + 5 * 1024 * 1024:
            raise IOError(u"لا توجد مساحة كافية على الفلاشة")
        shutil.copyfile(path, dst + ".part")
        os.rename(dst + ".part", dst)
    return run


def clean_step(path):
    """ffmpeg noise reduction + loudness levelling, in place (the file keeps its name)."""
    def run():
        import subprocess
        ff = data.which("ffmpeg")
        if not ff:
            raise IOError("ffmpeg")
        base, ext = os.path.splitext(path)
        tmp = base + ".sqhclean" + ext
        rc = subprocess.call([ff, "-y", "-loglevel", "error", "-i", path, "-af",
                              "afftdn=nf=-25,highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11", "-vn", tmp])
        if rc != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise RuntimeError("ffmpeg %s" % rc)
        os.rename(tmp, path)
    return run


def delete_files(paths):
    n = 0
    for p in paths:
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
    return n


def payloads(items, reciter):
    """Play-list entries for library files."""
    out = []
    for n, label, path, _size, _ext in items:
        d = {"title": u"%s - %s" % (reciter, (u"سورة " + data.surah_name(n)) if n else label),
             "url": localserve.url_for(path), "path": path, "autonext": True}
        if n:
            d["n"] = n
        out.append(d)
    return out


# ------------------------------------------------------------------ folders on the disk as sources (1.7)
def _has_audio(folder):
    try:
        return any(f.lower().endswith(extras.AUDIO_EXT) for f in os.listdir(folder))
    except Exception:
        return False


def disk_reciters(root):
    """A folder chosen by the user -> [(reciter name, folder)]: every sub-folder (two levels deep)
    holding audio files is one reciter; files lying in the folder itself form one more."""
    if not os.path.isdir(root):
        raise IOError(u"المجلد غير متصل: %s" % root)
    out = []
    if _has_audio(root):
        out.append((os.path.basename(root.rstrip("/")) or root, root))
    for d in sorted(_listdir(root)):
        p = os.path.join(root, d)
        if d.startswith(".") or not os.path.isdir(p):
            continue
        if _has_audio(p):
            out.append((d, p))
        for d2 in sorted(_listdir(p)):
            p2 = os.path.join(p, d2)
            if not d2.startswith(".") and os.path.isdir(p2) and _has_audio(p2):
                out.append((u"%s - %s" % (d, d2), p2))
    return out


def disk_tracks(folder):
    """[(surah or None, label, path)] of one reciter folder, in mushaf order."""
    items = []
    for fn in _listdir(folder):
        p = os.path.join(folder, fn)
        if not fn.lower().endswith(extras.AUDIO_EXT) or not os.path.isfile(p):
            continue
        n = surah_from_name(fn)
        ext = os.path.splitext(fn)[1].lstrip(".").upper()
        label = (u"%d. سورة %s  (%s)" % (n, data.surah_name(n), ext)) if n else u"%s  (%s)" % (os.path.splitext(fn)[0], ext)
        items.append((n, label, p))
    items.sort(key=lambda x: (x[0] or 999, x[1]))
    return items


def browse(path):
    """Sub-folders of path for the folder picker: [(label, path)]."""
    out = []
    for d in sorted(_listdir(path)):
        p = os.path.join(path, d)
        if d.startswith(".") or not os.path.isdir(p):
            continue
        n = sum(1 for f in _listdir(p) if f.lower().endswith(extras.AUDIO_EXT))
        out.append(((u"📁 %s" % d) + (u"  (%d ملف صوتي)" % n if n else u""), p))
    return out


# ------------------------------------------------------------------ speed (tempo) without changing the voice
SPEEDS = [0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0]


def tempo_dir():
    d = data.record_dir()
    if not d:
        return None
    d = os.path.join(d, ".saadquranhub_speed")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def tempo_path(src_key, speed):
    import hashlib
    d = tempo_dir()
    if d is None:
        return None
    h = hashlib.md5((u"%s" % src_key).encode("utf-8")).hexdigest()[:16]
    return os.path.join(d, "%s_%03d.mp3" % (h, int(round(speed * 100))))


def tempo_make(src, speed, dst, fetch=None):
    """ffmpeg atempo (keeps the reciter's voice) at low priority. src may be a URL: it is fetched
    first (fetch(url, path)).  The newest few results are kept, older ones removed."""
    import subprocess
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return dst
    ff = data.which("ffmpeg")
    if not ff:
        raise IOError("ffmpeg")
    tmp_src = None
    if src.startswith("http"):
        tmp_src = dst + ".src"
        fetch(src, tmp_src)
        src = tmp_src
    try:
        chain = []
        s = float(speed)
        while s < 0.5:
            chain.append("atempo=0.5")
            s /= 0.5
        while s > 2.0:
            chain.append("atempo=2.0")
            s /= 2.0
        chain.append("atempo=%.3f" % s)
        cmd = [ff, "-y", "-loglevel", "error", "-i", src, "-vn", "-filter:a", ",".join(chain),
               "-c:a", "libmp3lame", "-q:a", "4", dst + ".part.mp3"]
        nice = data.which("nice")
        if nice:
            cmd = [nice, "-n", "19"] + cmd
        rc = subprocess.call(cmd)
        if rc != 0 or not os.path.exists(dst + ".part.mp3"):
            raise RuntimeError("ffmpeg %s" % rc)
        os.rename(dst + ".part.mp3", dst)
    finally:
        for p in (tmp_src, dst + ".part.mp3"):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    try:
        d = os.path.dirname(dst)
        fs = sorted((os.path.getmtime(os.path.join(d, f)), f) for f in os.listdir(d) if f.endswith(".mp3"))
        for _t, f in fs[:-6]:
            os.remove(os.path.join(d, f))
    except Exception:
        pass
    return dst
