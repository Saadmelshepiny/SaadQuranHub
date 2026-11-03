# -*- coding: utf-8 -*-
"""2.0: what you listen to is kept on the HDD (in the background), so playing it again is instant and
works without the internet; the next track is fetched while the current one plays."""
import hashlib
import json
import os
import threading
import time

from . import data
from . import localserve

AUDIO_EXT = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav")
MAX_FILE = 400 * 1024 * 1024
MIN_FREE = 1024 * 1024 * 1024          # never fill the disk: 1 GB stays free


def _ext_of(url):
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    for e in AUDIO_EXT:
        if path.endswith(e):
            return e
    return None


class AudioCache(object):
    def __init__(self, quota_gb=20):
        self.quota = int(quota_gb * 1024 ** 3)
        self.lock = threading.Lock()
        self.queue = []
        self.busy = None              # url being fetched
        self.thread = None
        self.index = None
        self.dirty = 0
        self.enabled = True

    # -- index -----------------------------------------------------------------------------------
    def folder(self):
        return data.home_dir("audio")

    def _load(self):
        if self.index is not None:
            return self.index
        self.index = {}
        d = self.folder()
        if d:
            try:
                with open(os.path.join(d, "index.json"), "rb") as f:
                    self.index = json.loads(f.read().decode("utf-8"))
            except Exception:
                self.index = {}
        return self.index

    def _save(self, force=False):
        d = self.folder()
        if not d or (not force and time.time() - self.dirty < 30):
            return
        self.dirty = time.time()
        try:
            tmp = os.path.join(d, "index.json.new")
            with open(tmp, "wb") as f:
                f.write(json.dumps(self._load(), ensure_ascii=False).encode("utf-8"))
            os.rename(tmp, os.path.join(d, "index.json"))
        except Exception:
            pass

    @staticmethod
    def key(url):
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    def cacheable(self, url, live=False):
        return (self.enabled and not live and url and url.startswith("http") and not url.startswith("http://127.0.0.1")
                and _ext_of(url) is not None and ".m3u8" not in url)

    # -- lookups -----------------------------------------------------------------------------------
    def local_for(self, url):
        """-> local (127.0.0.1) address of a kept copy, or None."""
        if not url or not self.enabled:
            return None
        d = self.folder()
        if not d:
            return None
        with self.lock:
            e = self._load().get(url)
        if not e:
            return None
        path = os.path.join(d, e["f"])
        if not os.path.exists(path):
            with self.lock:
                self._load().pop(url, None)
            return None
        e["t"] = int(time.time())
        return localserve.url_for(path)

    def remote_for(self, url):
        """The internet address behind a kept copy (history / resume keep the real address)."""
        p = localserve.path_of(url) if url else url
        if not p or p == url:
            return url
        d = self.folder()
        if not d or not p.startswith(d):
            return url
        f = os.path.basename(p)
        with self.lock:
            for u, e in self._load().items():
                if e.get("f") == f:
                    return u
        return url

    def entries(self):
        """-> [(title, local url, size)] newest first (the 'without internet' list)."""
        d = self.folder()
        if not d:
            return []
        with self.lock:
            items = list(self._load().items())
        out = []
        for u, e in sorted(items, key=lambda kv: -kv[1].get("t", 0)):
            path = os.path.join(d, e["f"])
            if os.path.exists(path):
                out.append((e.get("title") or u.rsplit("/", 1)[-1], localserve.url_for(path), e.get("size", 0)))
        return out

    def total(self):
        with self.lock:
            return sum(e.get("size", 0) for e in self._load().values())

    # -- fetching ----------------------------------------------------------------------------------
    def want(self, url, title=u""):
        """Keep a copy of url (in the background, one file at a time)."""
        if not self.cacheable(url) or not self.folder():
            return False
        with self.lock:
            if url in self._load() or url == self.busy or any(u == url for u, _t in self.queue):
                return False
            self.queue.append((url, title))
            del self.queue[:-4]                  # only the latest few wishes matter
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()
        return True

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.busy = None
                    return
                url, title = self.queue.pop(0)
                self.busy = url
            try:
                self._fetch(url, title)
            except Exception:
                pass

    def _fetch(self, url, title):
        d = self.folder()
        if not d:
            return
        free = data.disk_free(d)
        if free is not None and free < MIN_FREE:
            return
        name = self.key(url) + (_ext_of(url) or ".mp3")
        path = os.path.join(d, name)
        part = path + ".part"
        r = data.open_stream(url, 30)
        size = 0
        try:
            total = int(r.headers.get("Content-Length") or 0)
        except Exception:
            total = 0
        if total > MAX_FILE:
            r.close()
            return
        try:
            with open(part, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                    if size > MAX_FILE:
                        raise IOError("too big")
                    time.sleep(0.002)              # leave the network to what is playing
        finally:
            r.close()
        if size < 20000 or (total and size < total):
            os.remove(part)
            return
        os.rename(part, path)
        with self.lock:
            self._load()[url] = {"f": name, "size": size, "t": int(time.time()), "title": title}
        self.trim()
        self._save(True)

    def trim(self):
        """Least recently played copies go first when the quota is passed."""
        d = self.folder()
        if not d:
            return 0
        removed = 0
        with self.lock:
            idx = self._load()
            items = sorted(idx.items(), key=lambda kv: kv[1].get("t", 0))
            total = sum(e.get("size", 0) for _u, e in items)
            for u, e in items:
                if total <= self.quota:
                    break
                try:
                    os.remove(os.path.join(d, e["f"]))
                except OSError:
                    pass
                total -= e.get("size", 0)
                idx.pop(u, None)
                removed += 1
        if removed:
            self._save(True)
        return removed

    def clear(self):
        d = self.folder()
        with self.lock:
            idx, self.index = self._load(), {}
        for e in idx.values():
            try:
                os.remove(os.path.join(d, e["f"]))
            except Exception:
                pass
        self._save(True)
