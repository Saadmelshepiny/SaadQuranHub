# -*- coding: utf-8 -*-
"""Time-shift for live radio streams (pure python, no enigma2 imports).

A LiveBuffer keeps the last N minutes of an upstream radio stream in memory.
A tiny local HTTP server (127.0.0.1) then re-serves it to the player:

    http://127.0.0.1:PORT/live          -> the live edge
    http://127.0.0.1:PORT/live?delay=90 -> 90 seconds behind live, paced in
                                           real time (so the delay is kept)

"Rewind" / "pause" simply reconnect the player with a larger delay, "go live"
reconnects with delay=0. Chunks are time-stamped, so no bitrate is needed.
"""
from __future__ import print_function

import socket
import threading
import time

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
except ImportError:  # python2
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn


class LiveBuffer(object):
    def __init__(self, opener, max_seconds=1800, max_bytes=32 * 1024 * 1024):
        self.opener = opener              # () -> file-like response with .read(n)/.headers
        self.max_seconds, self.max_bytes = max_seconds, max_bytes
        self.chunks = []                  # [(seq, ts, bytes)]
        self.first_seq = 0
        self.next_seq = 0
        self.size = 0
        self.ctype = "audio/mpeg"
        self.cv = threading.Condition()
        self.stop_flag = False
        self.error = None
        self.reconnects = 0
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_flag = True
        with self.cv:
            self.cv.notify_all()

    # -- upstream reader (reconnects on its own) ----------------------------------
    def _run(self):
        backoff = 1.0
        while not self.stop_flag:
            resp = None
            try:
                resp = self.opener()
                try:
                    self.ctype = resp.headers.get("Content-Type") or self.ctype
                except Exception:
                    pass
                self.error = None
                backoff = 1.0
                while not self.stop_flag:
                    data = resp.read(4096)
                    if not data:
                        break
                    self._append(data)
            except Exception as e:
                self.error = e
            finally:
                try:
                    if resp is not None:
                        resp.close()
                except Exception:
                    pass
            if self.stop_flag:
                break
            self.reconnects += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

    def _append(self, data):
        now = time.time()
        with self.cv:
            self.chunks.append((self.next_seq, now, data))
            self.next_seq += 1
            self.size += len(data)
            while self.chunks and (self.size > self.max_bytes or
                                   now - self.chunks[0][1] > self.max_seconds):
                _, _, d = self.chunks.pop(0)
                self.size -= len(d)
                self.first_seq += 1
            self.cv.notify_all()

    # -- queries ---------------------------------------------------------------------
    def available(self):
        """Seconds of history that can be rewound."""
        with self.cv:
            if not self.chunks:
                return 0.0
            return max(0.0, time.time() - self.chunks[0][1])

    def seq_for_delay(self, delay):
        """Sequence number of the first chunk that is at least `delay` s old."""
        with self.cv:
            if not self.chunks:
                return self.next_seq
            if delay <= 0:
                return max(self.first_seq, self.next_seq - 1)
            target = time.time() - delay
            for seq, ts, _ in self.chunks:
                if ts >= target:
                    return seq
            return self.next_seq - 1

    def get(self, seq, timeout=1.0):
        """-> (ts, data) for chunk `seq`, waiting up to `timeout`; None on timeout;
        'gone' if it has already been discarded."""
        with self.cv:
            if seq < self.first_seq:
                return "gone"
            end = time.time() + timeout
            while seq >= self.next_seq:
                left = end - time.time()
                if left <= 0 or self.stop_flag:
                    return None
                self.cv.wait(left)
            _, ts, data = self.chunks[seq - self.first_seq]
            return ts, data


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TimeshiftProxy(object):
    """One local server, many buffers (by key)."""

    def __init__(self):
        self.buffers = {}
        self.server = _Server(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def add(self, key, opener, **kw):
        old = self.buffers.pop(key, None)
        if old:
            old.stop()
        self.buffers[key] = LiveBuffer(opener, **kw).start()
        return self.buffers[key]

    def url(self, key, delay=0):
        return "http://127.0.0.1:%d/%s?delay=%d" % (self.port, key, int(delay))

    def close(self):
        for b in self.buffers.values():
            b.stop()
        self.buffers.clear()
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass

    def _handler(self):
        proxy = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                path, _, query = self.path.partition("?")
                key = path.strip("/")
                buf = proxy.buffers.get(key)
                if buf is None:
                    self.send_error(404)
                    return
                delay = 0
                for part in query.split("&"):
                    if part.startswith("delay="):
                        try:
                            delay = max(0, int(float(part[6:])))
                        except ValueError:
                            pass
                # wait (briefly) for the first data so the player gets a real answer
                t0 = time.time()
                while buf.next_seq == 0 and time.time() - t0 < 12 and not buf.stop_flag:
                    time.sleep(0.1)
                if buf.next_seq == 0:
                    self.send_error(504)
                    return
                self.send_response(200)
                self.send_header("Content-Type", buf.ctype)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                seq = buf.seq_for_delay(delay)
                burst = 4.0                    # seconds of head start for the player's buffer
                try:
                    while not buf.stop_flag:
                        item = buf.get(seq, 1.0)
                        if item is None:
                            continue
                        if item == "gone":
                            seq = buf.seq_for_delay(delay)
                            continue
                        ts, data = item
                        if delay > 0:          # keep the same distance behind live
                            wait = ts - (time.time() - delay) - burst
                            if wait > 0:
                                time.sleep(min(wait, 1.0))
                                if wait > 1.0:
                                    continue
                        self.wfile.write(data)
                        seq += 1
                except (socket.error, IOError, ValueError):
                    pass

        return H
