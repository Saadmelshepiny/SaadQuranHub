# -*- coding: utf-8 -*-
"""Saad Quran Hub - Telegram bot client (Bot API over HTTPS, long polling).

Only the network lives here: a thread asks Telegram for new messages (getUpdates, 25 s long poll)
and puts them in a queue; the plugin empties the queue on the GUI thread (poll()).  Messages are
sent from short worker threads so the receiver's screen never waits for the internet.
Pure Python (urllib + json), no enigma2 imports, so it can be unit-tested."""
from __future__ import print_function

import json
import os
import threading
import time
import uuid

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except ImportError:                          # python 2
    from urllib2 import Request, urlopen
    from urllib import urlencode

from . import data

API = "https://api.telegram.org/bot%s/%s"
CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.conf")
MAX_FILE = 49 * 1024 * 1024                  # Telegram's limit for bots is 50 MB


def default_token():
    """Token installed with the owner's private package (bot.conf next to the plugin)."""
    try:
        with open(CONF) as f:
            for line in f:
                line = line.strip()
                if line.startswith("token=") and ":" in line:
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return u""


def mask(token):
    return (token[:6] + u"…" + token[-4:]) if token and len(token) > 12 else u"—"


class TgBot(object):
    def __init__(self, token):
        self.token = (token or u"").strip()
        self.offset = 0
        self.inbox = []
        self.lock = threading.Lock()
        self.thread = None
        self.running = False
        self.error = None
        self.ok_at = 0
        self.me = None
        self.sent = 0

    # -- low level ----------------------------------------------------------------------
    def _open(self, req, timeout):
        last = None
        for ctx in data._contexts():
            try:
                kw = {"timeout": timeout}
                if ctx is not None:
                    kw["context"] = ctx
                return urlopen(req, **kw).read()
            except Exception as e:
                last = e
                if hasattr(e, "code"):           # an HTTP answer: the TLS was fine, do not retry
                    try:
                        return e.read()
                    except Exception:
                        raise e
        raise last

    def call(self, method, params=None, timeout=20):
        body = urlencode(dict((k, (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v))
                              for k, v in (params or {}).items())).encode("utf-8")
        req = Request(API % (self.token, method), data=body,
                      headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": data.UA})
        res = json.loads(self._open(req, timeout).decode("utf-8"))
        if not res.get("ok"):
            raise IOError(u"%s: %s" % (method, res.get("description", u"error")))
        return res.get("result")

    def upload(self, method, params, field, path, timeout=600):
        """multipart/form-data upload of one file (sendAudio / sendDocument)."""
        b = "----sqh%s" % uuid.uuid4().hex
        parts = []
        for k, v in params.items():
            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else u"%s" % v
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n" % (b, k)).encode("utf-8") +
                         v.encode("utf-8") + b"\r\n")
        name = os.path.basename(path)
        with open(path, "rb") as f:
            blob = f.read()
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                      "Content-Type: application/octet-stream\r\n\r\n" % (b, field, name)).encode("utf-8") +
                     blob + b"\r\n")
        parts.append(("--%s--\r\n" % b).encode("utf-8"))
        req = Request(API % (self.token, method), data=b"".join(parts),
                      headers={"Content-Type": "multipart/form-data; boundary=%s" % b, "User-Agent": data.UA})
        res = json.loads(self._open(req, timeout).decode("utf-8"))
        if not res.get("ok"):
            raise IOError(res.get("description", u"upload failed"))
        return res.get("result")

    # -- polling --------------------------------------------------------------------------
    def start(self):
        if not self.token or (self.thread is not None and self.thread.is_alive()):
            return bool(self.token)
        self.running = True
        self.thread = threading.Thread(target=self._loop)
        self.thread.daemon = True
        self.thread.start()
        return True

    def stop(self):
        self.running = False

    def _loop(self):
        wait = 3
        try:
            self.me = self.call("getMe", timeout=20)
            self.call("setMyCommands", {"commands": COMMANDS}, timeout=20)
        except Exception as e:
            self.error = u"%s" % e
        while self.running:
            try:
                ups = self.call("getUpdates", {"timeout": 25, "offset": self.offset,
                                               "allowed_updates": ["message", "callback_query"]}, timeout=40)
                self.error = None
                self.ok_at = time.time()
                wait = 3
                for u in ups or []:
                    self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
                    with self.lock:
                        self.inbox.append(u)
            except Exception as e:
                self.error = u"%s" % e
                for _i in range(int(wait)):
                    if not self.running:
                        break
                    time.sleep(1)
                wait = min(60, wait * 2)

    def poll(self):
        """Updates received since the last call (GUI thread)."""
        with self.lock:
            out, self.inbox = self.inbox, []
        return out

    # -- sending (never blocks the caller) ------------------------------------------------
    def _bg(self, fn, done=None):
        def run():
            try:
                r = fn()
                self.sent += 1
                if done:
                    done(r, None)
            except Exception as e:
                self.error = u"%s" % e
                if done:
                    done(None, e)
        th = threading.Thread(target=run)
        th.daemon = True
        th.start()
        return th

    def send(self, chat, text, kb=None, reply_kb=None, done=None):
        p = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}
        if kb is not None:
            p["reply_markup"] = {"inline_keyboard": kb}
        elif reply_kb is not None:
            p["reply_markup"] = {"keyboard": reply_kb, "resize_keyboard": True, "is_persistent": True}
        return self._bg(lambda: self.call("sendMessage", p), done)

    def edit(self, chat, msg_id, text, kb=None):
        p = {"chat_id": chat, "message_id": msg_id, "text": text[:4000], "disable_web_page_preview": "true"}
        if kb is not None:
            p["reply_markup"] = {"inline_keyboard": kb}
        return self._bg(lambda: self.call("editMessageText", p))

    def answer(self, cb_id, text=u""):
        return self._bg(lambda: self.call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:190]}))

    def send_audio(self, chat, path, title=u"", done=None):
        if os.path.getsize(path) > MAX_FILE:
            raise IOError(u"الملف أكبر من 50 ميجا (حد تليجرام)")
        return self._bg(lambda: self.upload("sendAudio", {"chat_id": chat, "title": title[:60],
                                                          "performer": u"Saad Quran Hub"}, "audio", path), done)


COMMANDS = [
    {"command": "now", "description": u"التشغيل الآن وأزرار التحكم"},
    {"command": "search", "description": u"البحث عن قارئ"},
    {"command": "radio", "description": u"الإذاعات المباشرة"},
    {"command": "lib", "description": u"مكتبتي (الملفات المنزّلة)"},
    {"command": "dl", "description": u"حالة التنزيلات"},
    {"command": "ayah", "description": u"آية اليوم مع تفسيرها"},
    {"command": "marks", "description": u"علاماتي (المواضع المحفوظة)"},
    {"command": "speed", "description": u"سرعة التلاوة"},
    {"command": "stop", "description": u"إيقاف التشغيل"},
    {"command": "help", "description": u"المساعدة"},
]

MAIN_KB = [[{"text": u"▶️ التشغيل الآن"}, {"text": u"🔎 بحث عن قارئ"}],
           [{"text": u"📻 الإذاعات"}, {"text": u"📚 مكتبتي"}],
           [{"text": u"⬇️ التنزيلات"}, {"text": u"📖 آية اليوم"}],
           [{"text": u"🔖 علاماتي"}]]

CONTROL_KB = [[{"text": u"⏮", "callback_data": "c:pv"}, {"text": u"⏯", "callback_data": "c:pp"},
               {"text": u"⏭", "callback_data": "c:nx"}],
              [{"text": u"🔉", "callback_data": "c:vd"}, {"text": u"🔊", "callback_data": "c:vu"},
               {"text": u"⏹", "callback_data": "c:st"}],
              [{"text": u"🔄 تحديث", "callback_data": "c:now"}, {"text": u"📖 الآية", "callback_data": "c:ay"}]]


def grid(buttons, cols=3):
    """[(text, data)] -> inline keyboard rows."""
    rows, cur = [], []
    for t, d in buttons:
        cur.append({"text": t, "callback_data": d})
        if len(cur) == cols:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    return rows
