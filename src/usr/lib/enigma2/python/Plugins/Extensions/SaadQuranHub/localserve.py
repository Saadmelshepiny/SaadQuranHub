# -*- coding: utf-8 -*-
"""Saad Quran Hub - files of the HDD / USB stick served on http://127.0.0.1 (1.7.2).

The receiver keeps the TV picture fine while it plays an internet recitation, but a file opened
straight from the disk made the picture go black on the owner's box.  So disk files take exactly the
road of the internet recitations: a tiny HTTP server on 127.0.0.1 (never reachable from outside)
serves them, with byte ranges (seeking works), and without the pictures stored inside the files
(ID3 cover art of MP3, PICTURE blocks of FLAC), which some players treat as a video.
Pure Python, no enigma2 imports."""
from __future__ import print_function

import os
import struct
import threading

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    from urllib.parse import quote, unquote, urlparse, parse_qs
except ImportError:                                      # python 2
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn
    from urllib import quote, unquote
    from urlparse import urlparse, parse_qs

AUDIO = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac",
         ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav"}


def layout(path):
    """-> (prefix bytes, offset in the file where the copied part starts).
    The served stream = prefix + file[offset:]."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as f:
            head = f.read(10)
            if ext == ".mp3" and len(head) == 10 and head[:3] == b"ID3":
                sz = head[6:10]
                size = (bytearray(sz)[0] << 21) | (bytearray(sz)[1] << 14) | (bytearray(sz)[2] << 7) | bytearray(sz)[3]
                footer = 10 if (bytearray(head)[5] & 0x10) else 0
                return b"", 10 + size + footer                    # the ID3v2 tag (and its pictures) skipped
            if ext == ".flac" and head[:4] == b"fLaC":
                f.seek(4)
                blocks = []
                while True:
                    h = f.read(4)
                    if len(h) < 4:
                        return b"", 0
                    last = bool(bytearray(h)[0] & 0x80)
                    btype = bytearray(h)[0] & 0x7F
                    blen = struct.unpack(">I", b"\0" + h[1:4])[0]
                    body = f.read(blen)
                    if btype != 6:                                 # 6 = PICTURE
                        blocks.append((btype, body))
                    if last:
                        break
                data_off = f.tell()
                out = [b"fLaC"]
                for i, (bt, body) in enumerate(blocks):
                    flag = 0x80 if i == len(blocks) - 1 else 0
                    out.append(struct.pack(">B", flag | bt) + struct.pack(">I", len(body))[1:] + body)
                return b"".join(out), data_off
    except Exception:
        pass
    return b"", 0


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LocalFiles(object):
    PORT = 8086                       # fixed, so history / resume entries stay valid after a reboot

    def __init__(self):
        try:
            self.server = _Server(("127.0.0.1", self.PORT), self._handler())
        except Exception:
            self.server = _Server(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.cache = {}
        th = threading.Thread(target=self.server.serve_forever)
        th.daemon = True
        th.start()

    def url(self, path):
        ext = os.path.splitext(path)[1].lower()
        p = path.encode("utf-8") if not isinstance(path, bytes) else path
        return "http://127.0.0.1:%d/f%s?p=%s" % (self.port, ext, quote(p, safe=""))

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass

    def _layout(self, path):
        try:
            key = (path, os.path.getmtime(path), os.path.getsize(path))
        except OSError:
            return None
        v = self.cache.get(key)
        if v is None:
            if len(self.cache) > 50:
                self.cache.clear()
            v = self.cache[key] = layout(path) + (key[2],)
        return v

    def _handler(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _target(self):
                u = urlparse(self.path)
                p = parse_qs(u.query).get("p", [""])[0]
                path = unquote(p)
                if not isinstance(path, str):
                    try:
                        path = path.decode("utf-8")
                    except Exception:
                        pass
                ext = os.path.splitext(path)[1].lower()
                if ext not in AUDIO or not os.path.isfile(path):
                    return None, None
                return path, ext

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_GET(self, head=False):
                path, ext = self._target()
                if path is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                lay = outer._layout(path)
                if lay is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                prefix, off, fsize = lay
                total = len(prefix) + max(0, fsize - off)
                start, end = 0, total - 1
                rng = self.headers.get("Range")
                partial = False
                if rng and rng.startswith("bytes="):
                    try:
                        a, b = rng[6:].split(",")[0].split("-")
                        if a.strip():
                            start = int(a)
                            if b.strip():
                                end = min(total - 1, int(b))
                        else:
                            start = max(0, total - int(b))
                        partial = True
                    except ValueError:
                        start, end = 0, total - 1
                if start >= total and total:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % total)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                n = max(0, end - start + 1)
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", AUDIO[ext])
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(n))
                if partial:
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, total))
                self.end_headers()
                if head or not n:
                    return
                try:
                    pos = start
                    if pos < len(prefix):
                        chunk = prefix[pos:min(len(prefix), end + 1)]
                        self.wfile.write(chunk)
                        pos += len(chunk)
                    if pos <= end:
                        with open(path, "rb") as f:
                            f.seek(off + pos - len(prefix))
                            left = end - pos + 1
                            while left > 0:
                                c = f.read(min(65536, left))
                                if not c:
                                    break
                                self.wfile.write(c)
                                left -= len(c)
                except Exception:
                    pass
        return H


_SRV = []


def url_for(path):
    """http://127.0.0.1 address of a disk file (the path itself if the server cannot start)."""
    if not path or path.startswith("http") or not os.path.splitext(path)[1].lower() in AUDIO:
        return path
    try:
        if not _SRV:
            _SRV.append(LocalFiles())
        return _SRV[0].url(path)
    except Exception:
        return path


def path_of(url):
    """The disk path behind one of our URLs (or the url itself)."""
    if url and url.startswith("http://127.0.0.1:") and "/f." in url and "?p=" in url:
        p = unquote(url.split("?p=", 1)[1])
        if not isinstance(p, str):
            try:
                p = p.decode("utf-8")
            except Exception:
                pass
        return p
    return url


# ------------------------------------------------------------------ "my station" for the home (1.8)
class HomeRadio(object):
    """http://<receiver>:8087/radio/<pin>.mp3 - the MP3 files of the library one after another, without
    end, for any phone / speaker / PC in the home.  Only on the home network (a PIN in the address)."""
    PORT = 8087

    def __init__(self, files, pin, shuffle=True):
        self.files, self.pin, self.shuffle = files, str(pin), shuffle
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                if urlparse(self.path).path != "/radio/%s.mp3" % outer.pin:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("icy-name", "Saad Quran Hub")
                self.end_headers()
                outer.stream(self.wfile)
        self.server = _Server(("0.0.0.0", self.PORT), H)
        th = threading.Thread(target=self.server.serve_forever)
        th.daemon = True
        th.start()

    def playlist(self):
        import random
        fs = [f for f in (self.files() or []) if f.lower().endswith(".mp3") and os.path.isfile(f)]
        if self.shuffle:
            random.shuffle(fs)
        return fs

    def stream(self, out):
        empty = 0
        while empty < 3:
            fs = self.playlist()
            if not fs:
                empty += 1
                continue
            for f in fs:
                try:
                    _pre, off = layout(f)
                    size = os.path.getsize(f)
                    end = size
                    with open(f, "rb") as fh:
                        if size > 128:
                            fh.seek(size - 128)
                            if fh.read(3) == b"TAG":
                                end = size - 128            # ID3v1 at the end
                        fh.seek(off)
                        left = end - off
                        while left > 0:
                            c = fh.read(min(32768, left))
                            if not c:
                                break
                            out.write(c)
                            left -= len(c)
                except (IOError, OSError) as e:
                    if getattr(e, "errno", None) in (32, 104):     # the listener went away
                        return
                    continue
                except Exception:
                    return

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass
