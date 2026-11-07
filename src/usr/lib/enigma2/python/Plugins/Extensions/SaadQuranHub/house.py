# -*- coding: utf-8 -*-
"""2.1: several receivers in one house.  Receivers that share the same "house code" find each other on
the local network (UDP 8089) and can: play the same recitation everywhere (in step), stop everywhere,
and continue here what another room is playing.  Every message is signed with the house code."""
import hashlib
import hmac
import json
import socket
import threading
import time
import uuid

PORT = 8089
MAX_AGE = 30            # seconds a message stays valid


def box_id():
    return "%012x" % uuid.getnode()


class House(object):
    def __init__(self, code, name, on_command, state):
        """on_command(msg) is called on the listener thread (queue it for the GUI);
        state() -> dict of what plays here (url, title, pos)."""
        self.code = (code or "").encode("utf-8")
        self.name = name
        self.on_command = on_command
        self.state = state
        self.me = box_id()
        self.peers = {}             # id -> {"name", "ip", "t", "title"}
        self.replies = {}
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", PORT))
        self.sock.settimeout(1.0)
        t = threading.Thread(target=self._listen, name="sqh-house")
        t.daemon = True
        t.start()

    # -- signing ------------------------------------------------------------------------------------
    def _sig(self, body):
        return hmac.new(self.code, body.encode("utf-8"), hashlib.sha256).hexdigest()

    def _pack(self, msg):
        msg = dict(msg, frm=self.me, name=self.name, ts=time.time())
        body = json.dumps(msg, sort_keys=True, ensure_ascii=False)
        return json.dumps({"b": body, "s": self._sig(body)}).encode("utf-8")

    def _unpack(self, raw):
        try:
            env = json.loads(raw.decode("utf-8"))
            body = env["b"]
            if not hmac.compare_digest(self._sig(body), env["s"]):
                return None
            msg = json.loads(body)
            if msg.get("frm") == self.me or abs(time.time() - msg.get("ts", 0)) > MAX_AGE:
                return None
            return msg
        except Exception:
            return None

    # -- sending ------------------------------------------------------------------------------------
    def send(self, msg, ip="255.255.255.255"):
        try:
            self.sock.sendto(self._pack(msg), (ip, PORT))
            return True
        except Exception:
            return False

    def discover(self, wait=1.5):
        """-> {id: peer} of the receivers of this house that answered."""
        self.send({"t": "hello"})
        time.sleep(wait)
        now = time.time()
        return dict((k, v) for k, v in self.peers.items() if now - v["t"] < 60)

    def play_everywhere(self, url, title, pos=0, delay=3.0):
        """Every room starts the same recitation at the same moment (delay seconds from now)."""
        at = time.time() + delay
        self.send({"t": "play", "url": url, "title": title, "pos": pos, "at": at})
        return at

    def stop_everywhere(self):
        self.send({"t": "stop"})

    def ask_state(self, peer_id, wait=1.5):
        """What another room plays now -> {"url", "title", "pos"} or None."""
        self.replies.pop(peer_id, None)
        ip = self.peers.get(peer_id, {}).get("ip", "255.255.255.255")
        self.send({"t": "state?", "to": peer_id}, ip)
        t0 = time.time()
        while time.time() - t0 < wait:
            if peer_id in self.replies:
                return self.replies.pop(peer_id)
            time.sleep(0.05)
        return None

    # -- receiving ----------------------------------------------------------------------------------
    def _listen(self):
        while self.running:
            try:
                raw, addr = self.sock.recvfrom(8192)
            except socket.timeout:
                continue
            except Exception:
                break
            msg = self._unpack(raw)
            if not msg:
                continue
            t = msg.get("t")
            self.peers[msg["frm"]] = {"name": msg.get("name"), "ip": addr[0], "t": time.time()}
            if t == "hello":
                self.send({"t": "here"}, addr[0])
            elif t == "state?" and msg.get("to") == self.me:
                try:
                    self.send(dict(self.state() or {}, t="state", to=msg["frm"]), addr[0])
                except Exception:
                    pass
            elif t == "state" and msg.get("to") == self.me:
                self.replies[msg["frm"]] = dict((k, msg.get(k)) for k in ("url", "title", "pos"))
            elif t in ("play", "stop"):
                try:
                    self.on_command(msg)
                except Exception:
                    pass

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
