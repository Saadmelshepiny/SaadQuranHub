# -*- coding: utf-8 -*-
"""Safe updates (2.0): the package is checked before it is installed, the running version is kept on
the HDD, and when the new version does not even start, the previous one is put back by itself."""
import hashlib
import json
import os
import tarfile
import time

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "enigma2-plugin-extensions-saadquranhub"
KEEP = 2


def _home(sub):
    from . import data
    return data.home_dir(sub)


# -- checking an ipk -----------------------------------------------------------------------------
def _ar_members(raw):
    if raw[:8] != b"!<arch>\n":
        raise ValueError(u"ليس ملف ipk")
    pos, out = 8, {}
    while pos + 60 <= len(raw):
        head = raw[pos:pos + 60]
        name = head[:16].decode("ascii", "ignore").strip().rstrip("/")
        size = int(head[48:58].decode("ascii").strip())
        out[name] = raw[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
    return out


def verify_ipk(path, sha256=None):
    """-> version of a Saad Quran Hub package that is complete and whose Python code compiles.
    Raises ValueError (in Arabic) for anything else."""
    import io
    with open(path, "rb") as f:
        raw = f.read()
    if sha256 and hashlib.sha256(raw).hexdigest().lower() != sha256.lower():
        raise ValueError(u"الملف لم يُنزَّل كاملاً (البصمة لا تطابق)")
    m = _ar_members(raw)
    for need in ("debian-binary", "control.tar.gz", "data.tar.gz"):
        if need not in m:
            raise ValueError(u"الحزمة ناقصة (%s)" % need)
    with tarfile.open(fileobj=io.BytesIO(m["control.tar.gz"]), mode="r:gz") as t:
        ctl = t.extractfile("./control").read().decode("utf-8", "ignore")
    fields = dict(l.split(":", 1) for l in ctl.splitlines() if ":" in l)
    if fields.get("Package", "").strip() != PACKAGE:
        raise ValueError(u"هذه ليست حزمة Saad Quran Hub")
    version = fields.get("Version", "").strip()
    found = 0
    with tarfile.open(fileobj=io.BytesIO(m["data.tar.gz"]), mode="r:gz") as t:
        for mem in t.getmembers():
            if mem.isfile() and mem.name.endswith(".py") and "/SaadQuranHub/" in mem.name:
                src = t.extractfile(mem).read()
                try:
                    compile(src, mem.name, "exec")
                except SyntaxError as e:
                    raise ValueError(u"خطأ في ملف %s: %s" % (os.path.basename(mem.name), e))
                found += mem.name.endswith("/plugin.py")
    if not found:
        raise ValueError(u"الحزمة لا تحتوي البلاجين")
    return version


# -- keeping the running version ---------------------------------------------------------------------
def snapshot(version):
    """Pack the installed plugin into <disk>/QuranHub/rollback/<version>.tar.gz (the last 2 are kept)."""
    d = _home("rollback")
    if not d:
        return None
    path = os.path.join(d, "%s.tar.gz" % version)
    tmp = path + ".part"
    with tarfile.open(tmp, "w:gz") as t:
        for root, dirs, files in os.walk(PLUGIN_DIR):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(root, f)
                t.add(full, os.path.relpath(full, PLUGIN_DIR))
    os.rename(tmp, path)
    for _t, old in snapshots()[KEEP:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def snapshots():
    """-> [(mtime, path)] newest first."""
    d = _home("rollback")
    if not d:
        return []
    out = []
    for f in os.listdir(d):
        if f.endswith(".tar.gz"):
            p = os.path.join(d, f)
            out.append((os.path.getmtime(p), p))
    out.sort(reverse=True)
    return out


def snap_version(path):
    return os.path.basename(path)[:-len(".tar.gz")]


def restore(path, target=None):
    """Put a kept version back in place of the installed files."""
    target = target or PLUGIN_DIR
    with tarfile.open(path, "r:gz") as t:
        for mem in t.getmembers():
            if mem.name.startswith("/") or ".." in mem.name.split("/"):
                continue
            t.extract(mem, target)
    now = time.time()
    for root, _d, files in os.walk(target):      # the restored sources are newer than any .pyc
        for f in files:
            if f.endswith(".py"):
                try:
                    os.utime(os.path.join(root, f), (now, now))
                except OSError:
                    pass
    return True


# -- the first start of a new version ------------------------------------------------------------------
def _marker():
    d = _home("system")
    return os.path.join(d, "update_pending.json") if d else None


def mark_pending(new_version, old_version):
    m = _marker()
    if m:
        with open(m, "w") as f:
            json.dump({"new": new_version, "old": old_version, "ts": int(time.time())}, f)


def pending():
    m = _marker()
    try:
        with open(m) as f:
            return json.load(f)
    except Exception:
        return None


def clear_pending():
    m = _marker()
    try:
        if m and os.path.exists(m):
            os.remove(m)
    except OSError:
        pass


def auto_rollback():
    """Called when plugin.py cannot be imported: right after an update, put the previous version back.
    -> the version restored, or None."""
    p = pending()
    if not p:
        return None
    for _t, path in snapshots():
        if snap_version(path) == p.get("old"):
            restore(path)
            clear_pending()
            d = _home("system")
            if d:
                with open(os.path.join(d, "rolled_back.json"), "w") as f:
                    json.dump({"from": p.get("new"), "to": p.get("old"), "ts": int(time.time())}, f)
            return p.get("old")
    return None


def rolled_back_note():
    """-> (from, to) once, after an automatic roll-back."""
    d = _home("system")
    if not d:
        return None
    path = os.path.join(d, "rolled_back.json")
    try:
        with open(path) as f:
            x = json.load(f)
        os.remove(path)
        return x.get("from"), x.get("to")
    except Exception:
        return None
