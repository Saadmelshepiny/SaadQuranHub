# -*- coding: utf-8 -*-
"""2.1: optional data packs kept on the HDD/USB instead of the receiver's flash.

* fonts-big : the large letter pictures (62/74/88 px)  - only the "lite" package leaves them out
* tafsir    : the three bundled tafsirs                - only the "lite" package leaves them out
* fonts-4k  : extra-large letter pictures (104/124 px) - only for skins wider than 1920

They come from the public GitHub repository (pack/index.json + .tar.gz, checked by SHA-256)."""
import hashlib
import json
import os
import tarfile
import threading

from . import data

BASE = "https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main/pack/"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LITE_MARK = os.path.join(PLUGIN_DIR, "LITE")


def is_lite():
    return os.path.exists(LITE_MARK)


def pack_dir():
    return data.home_dir("pack")


def desktop_width():
    try:
        from enigma import getDesktop
        return getDesktop(0).size().width()
    except Exception:
        return 1280


def ram_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def wanted():
    """Packs this receiver should have."""
    out = []
    if is_lite():
        out += ["fonts-big", "tafsir"]
    if desktop_width() > 1920 and ram_mb() >= 1400:
        out.append("fonts-4k")
    return out


def installed(name):
    d = pack_dir()
    return bool(d) and os.path.exists(os.path.join(d, name + ".ok"))


def atlas_dirs():
    """Extra folders holding letter pictures (for qtext)."""
    d = pack_dir()
    q = os.path.join(d, "qtext") if d else None
    return [q] if q and os.path.isdir(q) else []


def install(name, progress=None):
    """Download, check and unpack one pack (worker thread).  -> True when installed."""
    d = pack_dir()
    if not d:
        raise IOError(u"لا يوجد HDD أو فلاشة")
    idx = json.loads(data.http_text(BASE + "index.json", 30))
    info = idx[name]
    tmp = os.path.join(data.home_dir("tmp") or d, name + ".tar.gz.part")
    r = data.open_stream(BASE + info["file"], 30)
    h, got = hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress:
                    progress(got, info.get("size", 0))
    finally:
        r.close()
    if h.hexdigest() != info["sha256"]:
        os.remove(tmp)
        raise IOError(u"الملف لم يُنزَّل كاملاً")
    with tarfile.open(tmp, "r:gz") as t:
        for m in t.getmembers():
            if m.name.startswith("/") or ".." in m.name.split("/"):
                continue
            # qtext/... stays in pack/, data/... goes to <disk>/QuranHub/data (read by extras.data_dirs)
            target = d if m.name.startswith("qtext") else os.path.dirname(d)
            t.extract(m, target)
    os.remove(tmp)
    with open(os.path.join(d, name + ".ok"), "w") as f:
        f.write(info["sha256"])
    return True


def ensure(done=None):
    """Fetch the missing wanted packs in the background (once per start)."""
    need = [n for n in wanted() if not installed(n)]
    if not need or not pack_dir():
        return False

    def run():
        ok = []
        for n in need:
            try:
                if install(n):
                    ok.append(n)
            except Exception:
                pass
        if done:
            done(ok)
    t = threading.Thread(target=run, name="sqh-packs")
    t.daemon = True
    t.start()
    return True
