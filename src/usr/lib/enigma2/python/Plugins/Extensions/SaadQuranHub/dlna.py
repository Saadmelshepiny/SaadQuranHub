# -*- coding: utf-8 -*-
"""2.0: a small DLNA / UPnP media server, so smart TVs, phones and other receivers in the house can
browse and play your Quran library (reciter folders -> files).  Off until switched on in the menu."""
import os
import socket
import struct
import threading
import time
import uuid

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    from urllib.parse import quote, unquote
except ImportError:  # python 2 images
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn
    from urllib import quote, unquote

try:
    from xml.sax.saxutils import escape
except ImportError:
    escape = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

PORT = 8088
SSDP = ("239.255.255.250", 1900)
MIME = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
        ".opus": "audio/ogg", ".wav": "audio/wav", ".aac": "audio/aac"}
DEVICE = "urn:schemas-upnp-org:device:MediaServer:1"
CDS = "urn:schemas-upnp-org:service:ContentDirectory:1"
CMS = "urn:schemas-upnp-org:service:ConnectionManager:1"


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _text(x):
    if isinstance(x, bytes):
        return x.decode("utf-8", "ignore")
    return x


class _Threaded(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Server(object):
    """groups(): -> [(folder name, [(title, path)])]  (called on every browse, so it is always current)"""

    def __init__(self, groups, name=u"Saad Quran Hub", port=PORT):
        self.groups = groups
        self.name = name
        self.port = port
        self.uuid = "uuid:%s" % uuid.uuid5(uuid.NAMESPACE_DNS, "saadquranhub-" + local_ip())
        self.ip = local_ip()
        self.running = True
        self._files = {}
        srv = self
        h = type("H", (_Handler,), {"srv": srv})
        self.http = _Threaded(("0.0.0.0", port), h)
        t = threading.Thread(target=self.http.serve_forever, name="dlna-http")
        t.daemon = True
        t.start()
        self.ssdp_thread = threading.Thread(target=self._ssdp, name="dlna-ssdp")
        self.ssdp_thread.daemon = True
        self.ssdp_thread.start()

    def location(self):
        return "http://%s:%d/desc.xml" % (self.ip, self.port)

    # -- content ---------------------------------------------------------------------------------
    def tree(self):
        out = []
        for gi, (name, files) in enumerate(self.groups() or []):
            items = []
            for fi, (title, path) in enumerate(files):
                fid = "%d.%d" % (gi, fi)
                self._files[fid] = path
                items.append((fid, title, path))
            out.append(("g%d" % gi, name, items))      # never "0": that is the root
        return out

    def didl(self, oid, start, count):
        tree = self.tree()
        parts = []
        if oid == "0":
            rows = [("c", str(gi), name, len(items)) for gi, name, items in tree]
        else:
            g = next((t for t in tree if t[0] == oid), None)
            rows = [("i", fid, title, path) for fid, title, path in (g[2] if g else [])]
        total = len(rows)
        rows = rows[start:start + count] if count else rows[start:]
        for r in rows:
            if r[0] == "c":
                parts.append(u'<container id="%s" parentID="0" restricted="1" childCount="%d"><dc:title>%s</dc:title>'
                             u'<upnp:class>object.container.album.musicAlbum</upnp:class></container>' % (
                                 r[1], r[3], escape(r[2])))
            else:
                ext = os.path.splitext(r[3])[1].lower()
                try:
                    size = os.path.getsize(r[3])
                except OSError:
                    size = 0
                url = "http://%s:%d/f/%s%s" % (self.ip, self.port, r[1], ext)
                parts.append(u'<item id="%s" parentID="%s" restricted="1"><dc:title>%s</dc:title>'
                             u'<upnp:class>object.item.audioItem.musicTrack</upnp:class>'
                             u'<res protocolInfo="http-get:*:%s:*" size="%d">%s</res></item>' % (
                                 r[1], oid, escape(r[2]), MIME.get(ext, "audio/mpeg"), size, url))
        didl = (u'<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
                u'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
                + u"".join(parts) + u"</DIDL-Lite>")
        return didl, len(rows), total

    def file(self, fid):
        if fid not in self._files:
            self.tree()
        return self._files.get(fid)

    # -- discovery -----------------------------------------------------------------------------------
    def _reply(self, st):
        return ("HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nEXT:\r\nLOCATION: %s\r\n"
                "SERVER: Linux UPnP/1.0 SaadQuranHub/2.0\r\nST: %s\r\nUSN: %s::%s\r\n\r\n" % (
                    self.location(), st, self.uuid, st)).encode("ascii")

    def _notify(self, sock):
        for nt in ("upnp:rootdevice", DEVICE, CDS):
            msg = ("NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nCACHE-CONTROL: max-age=1800\r\n"
                   "LOCATION: %s\r\nNT: %s\r\nNTS: ssdp:alive\r\nSERVER: Linux UPnP/1.0 SaadQuranHub/2.0\r\n"
                   "USN: %s::%s\r\n\r\n" % (self.location(), nt, self.uuid, nt)).encode("ascii")
            try:
                sock.sendto(msg, SSDP)
            except Exception:
                pass

    def _ssdp(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
            s.bind(("", SSDP[1]))
            mreq = struct.pack("4s4s", socket.inet_aton(SSDP[0]), socket.inet_aton("0.0.0.0"))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.settimeout(2.0)
        except Exception:
            return
        last = 0
        while self.running:
            if time.time() - last > 300:
                last = time.time()
                self._notify(s)
            try:
                raw, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception:
                break
            txt = raw.decode("ascii", "ignore")
            if not txt.startswith("M-SEARCH"):
                continue
            st = ""
            for line in txt.split("\r\n"):
                if line.lower().startswith("st:"):
                    st = line.split(":", 1)[1].strip()
            sts = [st] if st in ("upnp:rootdevice", DEVICE, CDS, self.uuid) else (
                ["upnp:rootdevice", DEVICE, CDS] if st == "ssdp:all" else [])
            for x in sts:
                try:
                    s.sendto(self._reply(x), addr)
                except Exception:
                    pass
        try:
            s.close()
        except Exception:
            pass

    def close(self):
        self.running = False
        try:
            self.http.shutdown()
            self.http.server_close()
        except Exception:
            pass


DESC = u"""<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><specVersion><major>1</major><minor>0</minor></specVersion>
<device><deviceType>%s</deviceType><friendlyName>%s</friendlyName><manufacturer>Saad</manufacturer>
<modelName>Saad Quran Hub</modelName><UDN>%s</UDN>
<serviceList><service><serviceType>%s</serviceType><serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
<SCPDURL>/cds.xml</SCPDURL><controlURL>/cds</controlURL><eventSubURL>/ev</eventSubURL></service>
<service><serviceType>%s</serviceType><serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
<SCPDURL>/cms.xml</SCPDURL><controlURL>/cms</controlURL><eventSubURL>/ev</eventSubURL></service></serviceList>
</device></root>"""

SCPD = u"""<?xml version="1.0"?><scpd xmlns="urn:schemas-upnp-org:service-1-0"><specVersion><major>1</major>
<minor>0</minor></specVersion><actionList><action><name>Browse</name><argumentList>
<argument><name>ObjectID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_ObjectID</relatedStateVariable></argument>
<argument><name>BrowseFlag</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_BrowseFlag</relatedStateVariable></argument>
<argument><name>Filter</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Filter</relatedStateVariable></argument>
<argument><name>StartingIndex</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Index</relatedStateVariable></argument>
<argument><name>RequestedCount</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
<argument><name>SortCriteria</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SortCriteria</relatedStateVariable></argument>
<argument><name>Result</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Result</relatedStateVariable></argument>
<argument><name>NumberReturned</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
<argument><name>TotalMatches</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
<argument><name>UpdateID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_UpdateID</relatedStateVariable></argument>
</argumentList></action></actionList><serviceStateTable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_ObjectID</name><dataType>string</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_BrowseFlag</name><dataType>string</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_Filter</name><dataType>string</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_Index</name><dataType>ui4</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_Count</name><dataType>ui4</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_SortCriteria</name><dataType>string</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_Result</name><dataType>string</dataType></stateVariable>
<stateVariable sendEvents="no"><name>A_ARG_TYPE_UpdateID</name><dataType>ui4</dataType></stateVariable>
</serviceStateTable></scpd>"""

CMSD = u"""<?xml version="1.0"?><scpd xmlns="urn:schemas-upnp-org:service-1-0"><specVersion><major>1</major>
<minor>0</minor></specVersion><actionList/><serviceStateTable/></scpd>"""


def _arg(body, name):
    i = body.find("<%s>" % name)
    if i < 0:
        i = body.find("<%s " % name)
        if i < 0:
            return ""
        i = body.find(">", i)
    else:
        i += len(name) + 2
    j = body.find("</%s>" % name, i)
    return body[i:j] if j > i else ""


class _Handler(BaseHTTPRequestHandler):
    srv = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/xml; charset=\"utf-8\""):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        s = self.srv
        if p == "/desc.xml":
            return self._send(200, DESC % (DEVICE, escape(s.name), s.uuid, CDS, CMS))
        if p == "/cds.xml":
            return self._send(200, SCPD)
        if p == "/cms.xml":
            return self._send(200, CMSD)
        if p.startswith("/f/"):
            return self._file(os.path.splitext(unquote(p[3:]))[0])
        self._send(404, "not found", "text/plain")

    def do_HEAD(self):
        self.do_GET()

    def do_SUBSCRIBE(self):
        self.send_response(200)
        self.send_header("SID", "uuid:%s" % uuid.uuid4())
        self.send_header("TIMEOUT", "Second-1800")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = _text(self.rfile.read(n))
        if "Browse" not in body:
            return self._send(500, "unsupported", "text/plain")
        oid = _arg(body, "ObjectID") or "0"
        flag = _arg(body, "BrowseFlag")
        start = int(_arg(body, "StartingIndex") or 0)
        count = int(_arg(body, "RequestedCount") or 0)
        if flag == "BrowseMetadata":
            didl = (u'<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
                    u'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
                    u'<container id="%s" parentID="-1" restricted="1"><dc:title>%s</dc:title>'
                    u'<upnp:class>object.container.storageFolder</upnp:class></container></DIDL-Lite>' % (
                        escape(oid), escape(self.srv.name)))
            ret, total = 1, 1
        else:
            didl, ret, total = self.srv.didl(oid, start, count)
        resp = (u'<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                u's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                u'<u:BrowseResponse xmlns:u="%s"><Result>%s</Result><NumberReturned>%d</NumberReturned>'
                u'<TotalMatches>%d</TotalMatches><UpdateID>1</UpdateID></u:BrowseResponse></s:Body></s:Envelope>' % (
                    CDS, escape(didl), ret, total))
        self._send(200, resp)

    def _file(self, fid):
        path = self.srv.file(fid)
        if not path or not os.path.isfile(path):
            return self._send(404, "not found", "text/plain")
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if (a and b) else size - 1
            except ValueError:
                start, end = 0, size - 1
        end = min(end, size - 1)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(path)[1].lower(), "audio/mpeg"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except Exception:
                    break
                left -= len(chunk)
