# -*- coding: utf-8 -*-
"""Phone remote: a tiny web page served on the local network (port 8085).

The server thread never touches enigma2 objects. It pushes commands into a
queue (consumed on the GUI thread) and reads a state snapshot published by
the plugin.
"""
from __future__ import print_function

import json
import os
import socket
import threading

try:                                    # python 3 (OpenBlackHole) / python 2
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
except ImportError:                     # pragma: no cover
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from urlparse import urlparse, parse_qs

PORT = 8085

PAGE = u"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f5132"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="القرآن">
<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>القرآن الكريم</title><style>
:root{color-scheme:dark;--g:#0f5132;--gl:#1b7a4b;--au:#e0b95a;--bg:#0e1116;--p:#151b23;--p2:#1f2933;--tx:#d7dde5;--dm:#9aa5b1}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;font-family:system-ui,Tahoma,sans-serif;background:var(--bg);color:var(--tx);
 padding-bottom:calc(70px + env(safe-area-inset-bottom));user-select:none}
header{padding:calc(12px + env(safe-area-inset-top)) 16px 12px;background:linear-gradient(135deg,var(--g),#0b3d26);
 font-size:19px;font-weight:700;display:flex;justify-content:space-between;align-items:center}
header small{font-weight:400;font-size:12px;color:#cfe9db}
.tab{display:none;padding:12px}.tab.on{display:block}
.card{background:var(--p);border-radius:18px;padding:16px;margin-bottom:12px;border:1px solid #232c36}
#t{font-size:20px;font-weight:700;line-height:1.5;color:#fff}#s{font-size:13px;color:var(--dm);margin-top:4px;min-height:18px}
.bar{height:8px;background:#26303b;border-radius:6px;margin:14px 0 6px;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--gl),var(--au));transition:width .6s}
#tm{font-size:12px;color:var(--dm);display:flex;justify-content:space-between;direction:ltr}
.row{display:flex;gap:8px;margin-top:10px}
button{flex:1;min-width:0;padding:15px 4px;border:0;border-radius:14px;background:var(--p2);color:#e6edf3;font-size:17px;font-family:inherit}
button:active{background:var(--gl);transform:scale(.97)}.big{font-size:24px;background:var(--gl)}.stop{background:#7a2323}
h3{margin:6px 4px 8px;font-size:15px;color:var(--au)}
.it{padding:13px 14px;border-bottom:1px solid #1d242c;font-size:16px}.it:active{background:var(--gl)}
.live{color:#7ee0b0;font-size:11px;margin-inline-start:8px;border:1px solid #2a6;border-radius:8px;padding:0 6px}
.pr{display:flex;justify-content:space-between;padding:11px 4px;border-bottom:1px solid #1d242c;font-size:17px}
.pr.nx{color:var(--au);font-weight:700}
#ay{font-size:23px;line-height:2;text-align:center;color:#f1e7c8;font-family:"Amiri","Traditional Arabic",serif}
nav{position:fixed;inset-inline:0;bottom:0;display:flex;background:#0b0f14;border-top:1px solid #232c36;
 padding-bottom:env(safe-area-inset-bottom)}
nav a{flex:1;text-align:center;padding:11px 0 9px;font-size:12px;color:var(--dm)}nav a b{display:block;font-size:20px}
nav a.on{color:var(--au)}
#inst{display:none;background:#2a2410;color:#f0dc9a;font-size:13px;padding:10px 14px;border-radius:12px;margin-bottom:12px;line-height:1.7}
#pinbox{display:none;position:fixed;inset:0;background:#000d;z-index:9;align-items:center;justify-content:center}
#pinbox div{background:var(--p);padding:22px;border-radius:18px;width:80%;max-width:320px;text-align:center}
#pinbox input{font-size:26px;width:100%;text-align:center;border-radius:12px;border:1px solid #345;background:#0b0f14;color:#fff;padding:10px}
#off{display:none;background:#5a2020;color:#fff;text-align:center;padding:6px;font-size:13px}
select{width:100%;font-size:17px;padding:10px;border-radius:12px;background:var(--p2);color:#fff;border:1px solid #345;font-family:inherit;margin-bottom:8px}
.rd{font-size:22px;line-height:2.1;font-family:"Amiri","Traditional Arabic",serif;color:#f1e7c8}
.rd p{margin:0 0 12px}.rd .tf{font-family:system-ui,Tahoma,sans-serif;font-size:16px;line-height:1.9;color:var(--tx)}
.rd .now{background:#1b3a2a;border-radius:10px;padding:4px 8px}
#vv{font-size:24px;line-height:2;text-align:center;color:#ffe9a8;font-family:"Amiri","Traditional Arabic",serif;min-height:10px}
#wk{white-space:pre-line;font-size:15px;line-height:1.9}
#mp{font-size:22px;line-height:2.2;text-align:justify;font-family:"Amiri","Traditional Arabic",serif;color:#2b2210;background:#fbf3dc;
 border-radius:14px;padding:14px 16px;border:6px double #b8913a}
#mp .sh{display:block;text-align:center;color:#7a5512;font-weight:700;margin:6px 0}#mp .on{background:#f3d27a;border-radius:6px}
#mp .n{color:#7a5512;font-size:16px}#mh{display:flex;justify-content:space-between;align-items:center;color:var(--dm);font-size:14px;margin-bottom:8px}
</style></head><body>
<header><span>القرآن الكريم</span><small id="clk"></small></header><div id="off">لا يوجد اتصال بالجهاز</div>
<div id="pinbox"><div><p>أدخل رمز الدخول الظاهر على شاشة التلفاز</p><input id="pin" inputmode="numeric" maxlength="8">
<div class="row"><button class="big" onclick="setpin()">دخول</button></div></div></div>

<section class="tab on" id="t1"><div id="inst"></div>
<div class="card"><div id="t">...</div><div id="s"></div>
<div class="bar"><i id="pb"></i></div><div id="tm"><span id="tl"></span><span id="tr"></span></div>
<div class="row"><button onclick="c('prev')">⏮</button><button onclick="c('rew')">⏪ ٣٠</button>
<button class="big" onclick="c('pause')">⏯</button><button onclick="c('fwd')">٣٠ ⏩</button><button onclick="c('next')">⏭</button></div>
<div class="row"><button onclick="c('vol-')">🔉 −</button><button onclick="c('vol+')">🔊 +</button>
<button onclick="c('mute')">🔇</button><button class="stop" onclick="c('stop')">⏹</button></div>
<div class="row"><button onclick="c('resume')">▶ تابع الاستماع</button><button onclick="c('live')">⏺ المباشر</button></div>
<div class="row"><button id="hp" onclick="toPhone()">🎧 أكمل على الجوال</button><button id="ht" onclick="toTv()">📺 أكمل على التلفاز</button></div>
<audio id="pa" preload="none" style="width:100%;margin-top:10px;display:none" controls></audio></div>
<div class="card"><div id="vv"></div><div id="ay"></div></div>
<div class="card"><h3>تشغيل سريع</h3><div class="row"><button onclick="c('kahf')">الكهف</button><button onclick="c('mulk')">الملك</button>
<button onclick="c('hifz')">ورد الحفظ</button></div></div></section>

<section class="tab" id="t4"><div class="card"><select id="rs"></select>
<select id="rm"><option value="text">النص</option><option value="tafsir">التفسير</option><option value="translation">الترجمة</option></select>
<select id="rt"></select><div class="row"><button class="big" onclick="rd()">اقرأ</button><button onclick="rdnow()">السورة الحالية</button></div></div>
<div class="card rd" id="rbox"></div></section>

<section class="tab" id="t5"><div class="card"><select id="as" onchange="ad()"></select></div><div class="card rd" id="abox"></div></section>

<section class="tab" id="t2"><div id="lists"></div></section>

<section class="tab" id="t6"><div id="mh"><span id="mpn"></span><label><input type="checkbox" id="mf" checked> يتبع التلفاز</label></div>
<div id="mp">...</div><div class="row"><button onclick="mpg(MP+1)">◀ التالية</button><button onclick="mpnow()">الآية الحالية</button>
<button onclick="mpg(MP-1)">السابقة ▶</button></div></section>

<section class="tab" id="t3"><div class="card"><h3 id="city"></h3><div id="pt"></div><p id="np" style="color:var(--au)"></p>
<div class="row"><button onclick="c('adhan_test')">🔔 تجربة الأذان</button></div></div>
<div class="card"><h3>ملخص الأسبوع</h3><div id="wk"></div></div></section>

<nav><a class="on" id="n1" onclick="tab(1)"><b>▶</b>التحكم</a><a id="n2" onclick="tab(2)"><b>☰</b>المكتبة</a>
<a id="n6" onclick="tab(6)"><b>📗</b>المصحف</a><a id="n4" onclick="tab(4)"><b>📖</b>القراءة</a><a id="n5" onclick="tab(5)"><b>📿</b>الأذكار</a>
<a id="n3" onclick="tab(3)"><b>🕌</b>الصلاة</a></nav>
<script>
var PIN=localStorage.getItem("qh_pin")||"",$=function(i){return document.getElementById(i)},fail=0;
function q(u){return u+(u.indexOf("?")<0?"?":"&")+"pin="+encodeURIComponent(PIN)}
function tab(n){for(var i=1;i<7;i++){$("t"+i).className="tab"+(i==n?" on":"");$("n"+i).className=i==n?"on":""}}
function setpin(){PIN=$("pin").value;localStorage.setItem("qh_pin",PIN);$("pinbox").style.display="none";st()}
function c(x){fetch(q("/api/cmd?c="+encodeURIComponent(x))).then(st)}
function p(k,i){fetch(q("/api/play?k="+k+"&i="+i)).then(function(){tab(1);st()})}
function mm(s){s=Math.max(0,Math.floor(s));return Math.floor(s/60)+":"+("0"+s%60).slice(-2)}
function st(){fetch(q("/api/state")).then(function(r){
 if(r.status==403){$("pinbox").style.display="flex";return null}return r.json()}).then(function(d){
 if(!d)return;fail=0;$("off").style.display="none";
 $("t").textContent=d.playing?d.title:"لا يوجد تشغيل";$("s").textContent=d.status||"";
 $("pb").style.width=(d.pct||0)+"%";$("tl").textContent=d.pos!=null?mm(d.pos):"";$("tr").textContent=d.len?mm(d.len):(d.playing?"LIVE":"");
 $("ay").textContent=d.ayah||"";$("clk").textContent=d.clock||"";
 $("city").textContent=d.city?("مواقيت الصلاة - "+d.city):"اختر مدينة الصلاة من البلوجين";
 var h="";(d.prayers||[]).forEach(function(x){h+='<div class="pr'+(x[2]?' nx':'')+'"><span>'+x[0]+'</span><span>'+x[1]+'</span></div>'});$("pt").innerHTML=h;
 LAST=d;$("np").textContent=d.next||"";$("vv").textContent=d.verse||"";$("wk").textContent=d.week||"";CUR=d.surah||0;
 if(d.surah&&RN==d.surah&&d.verse_no!=VN){VN=d.verse_no;hl()}
 if(d.surah&&$("mf").checked&&(d.surah+":"+d.verse_no)!=MK){MK=d.surah+":"+d.verse_no;mpat(d.surah,d.verse_no)}
 h="";(d.lists||[]).forEach(function(L){h+="<h3>"+L.name+"</h3><div class='card' style='padding:0'>";
  L.items.forEach(function(it,i){h+='<div class="it" onclick="p(\\''+L.key+'\\','+i+')">'+it.t+(it.live?'<span class="live">LIVE</span>':'')+'</div>'});h+="</div>"});
 if($("lists").dataset.h!==h){$("lists").innerHTML=h;$("lists").dataset.h=h}
}).catch(function(){fail++;if(fail>2)$("off").style.display="block"})}
var CUR=0,RN=0,VN=0,META=null,LAST=null,MP=1,MK="",MV=[];
function mshow(d){MP=d.page;MV=d.verses;$("mpn").textContent="صفحة "+d.page+" • "+(d.juz?("الجزء "+d.juz):"");var h="";
 d.verses.forEach(function(v){if(v[1]==1)h+='<span class="sh">سورة '+esc(v[3])+'</span>';
  h+='<span id="m'+v[0]+'_'+v[1]+'">'+esc(v[2])+' <span class="n">﴿'+v[1]+'﴾</span></span> '});$("mp").innerHTML=h;mhl()}
function mhl(){var o=document.querySelector("#mp .on");if(o)o.className="";if(!LAST||!LAST.surah)return;
 var e=$("m"+LAST.surah+"_"+LAST.verse_no);if(e){e.className="on";if($("t6").className.indexOf("on")>=0)e.scrollIntoView({block:"center",behavior:"smooth"})}}
function mpg(p){if(p<1||p>604)return;fetch(q("/api/page?p="+p)).then(function(r){return r.json()}).then(mshow)}
function mpat(n,a){fetch(q("/api/page?n="+n+"&a="+a)).then(function(r){return r.json()}).then(function(d){if(d.page!=MP||!MV.length)mshow(d);else mhl()})}
function mpnow(){if(LAST&&LAST.surah){$("mf").checked=true;mpat(LAST.surah,LAST.verse_no)}}
function toPhone(){if(!LAST||!LAST.url){alert("لا توجد تلاوة يمكن نقلها الآن");return}var a=$("pa");a.style.display="block";
 a.src=LAST.url;a.onloadedmetadata=function(){try{a.currentTime=LAST.pos||0}catch(e){}};a.play();c("phone")}
function toTv(){var a=$("pa");var s=Math.floor(a.currentTime||0);a.pause();a.style.display="none";c("tvat:"+s)}
function esc(s){return String(s).replace(/[&<>]/g,function(x){return{"&":"&amp;","<":"&lt;",">":"&gt;"}[x]})}
function meta(){fetch(q("/api/meta")).then(function(r){return r.json()}).then(function(m){META=m;var h="";
 m.surahs.forEach(function(s,i){h+='<option value="'+(i+1)+'">'+(i+1)+'. '+s+'</option>'});$("rs").innerHTML=h;
 h="";m.tafsirs.forEach(function(t){h+='<option value="'+t[0]+'">'+t[1]+'</option>'});$("rt").innerHTML=h;
 h="";m.adhkar.forEach(function(t,i){h+='<option value="'+i+'">'+(i+1)+'. '+t+'</option>'});$("as").innerHTML=h;ad()})}
function rd(n){n=n||$("rs").value;RN=+n;$("rbox").textContent="...";fetch(q("/api/text?n="+n+"&m="+$("rm").value+"&t="+$("rt").value))
 .then(function(r){return r.json()}).then(function(d){var h="";d.blocks.forEach(function(b,i){var p=b.split("\n");
  var num=p.length>2&&p[0].indexOf("الآية")==0;if(num){var n0=p.shift()}
  h+='<p id="v'+(i+1)+'">'+(num?'<b style="color:#58d68d">'+esc(n0)+'</b><br>':'')+esc(p[0])+(p.length>1?'<br><span class="tf">'+esc(p.slice(1).join(" "))+'</span>':'')+'</p>'});
  $("rbox").innerHTML=h+'<small>'+esc(d.note||"")+'</small>';hl()})}
function rdnow(){if(CUR){$("rs").value=CUR;rd(CUR)}}
function hl(){var o=document.querySelector(".rd .now");if(o)o.className="";var e=$("v"+VN);if(e){e.className="now";e.scrollIntoView({block:"center",behavior:"smooth"})}}
function ad(){var i=$("as").value;if(i==null||i==="")return;fetch(q("/api/adhkar?i="+i)).then(function(r){return r.json()}).then(function(d){
 var h="";d.items.forEach(function(x){h+='<p>'+esc(x[0])+(x[1]>1?' <span class="live">×'+x[1]+'</span>':'')+'</p>'});$("abox").innerHTML=h})}
st();setInterval(st,2500);meta();
var sa=window.matchMedia&&matchMedia("(display-mode: standalone)").matches||navigator.standalone;
if(!sa){var ios=/iphone|ipad/i.test(navigator.userAgent);$("inst").style.display="block";
 $("inst").innerHTML=ios?"لتثبيت التطبيق: اضغط زر المشاركة ثم «إضافة إلى الشاشة الرئيسية».":
 "لتثبيت التطبيق: قائمة المتصفح ⋮ ثم «إضافة إلى الشاشة الرئيسية» (أو «تثبيت التطبيق»).";}
if("serviceWorker"in navigator)navigator.serviceWorker.register("/sw.js").catch(function(){});
</script></body></html>"""

MANIFEST = u"""{"name":"Saad Quran Hub","short_name":"القرآن","start_url":"/","scope":"/","display":"standalone",
"orientation":"portrait","dir":"rtl","lang":"ar","background_color":"#0e1116","theme_color":"#0f5132",
"icons":[{"src":"/icon-192.png","sizes":"192x192","type":"image/png"},
{"src":"/icon-512.png","sizes":"512x512","type":"image/png"},
{"src":"/icon-maskable-512.png","sizes":"512x512","type":"image/png","purpose":"maskable"}]}"""

SW = u"""var C="sqh-v1";
self.addEventListener("install",function(e){e.waitUntil(caches.open(C).then(function(c){return c.addAll(["/"])}));self.skipWaiting()});
self.addEventListener("activate",function(e){e.waitUntil(self.clients.claim())});
self.addEventListener("fetch",function(e){var u=new URL(e.request.url);if(u.pathname.indexOf("/api/")==0)return;
 e.respondWith(fetch(e.request).then(function(r){var k=r.clone();caches.open(C).then(function(c){c.put(e.request,k)});return r})
 .catch(function(){return caches.match(e.request)}))});"""

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATIC_OPEN = ("/", "/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png",
               "/icon-maskable-512.png", "/apple-touch-icon.png", "/favicon.ico")


class RemoteServer(object):
    def __init__(self, port=PORT, pin=""):
        self.port = port
        self.pin = pin
        self.state = {"playing": False, "title": u"", "status": u"", "lists": []}
        self.cmds = []
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None

    # -- used by the plugin (GUI thread)
    def publish(self, state):
        self.state = state

    def pop_commands(self):
        with self.lock:
            out, self.cmds = self.cmds, []
        return out

    def push(self, cmd):
        with self.lock:
            if len(self.cmds) < 20:
                self.cmds.append(cmd)

    def start(self):
        if self.httpd is not None:
            return True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype):
                if not isinstance(body, bytes):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype + "; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _static(self, path):
                if path == "/":
                    return self._send(200, PAGE, "text/html")
                if path == "/manifest.webmanifest":
                    return self._send(200, MANIFEST, "application/manifest+json")
                if path == "/sw.js":
                    return self._send(200, SW, "application/javascript")
                name = path.lstrip("/")
                if name == "favicon.ico":
                    name = "icon-192.png"
                fp = os.path.join(WEB_DIR, name)
                if name.endswith(".png") and os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._send(404, "not found", "text/plain")

            def do_GET(self):
                u = urlparse(self.path)
                qs = parse_qs(u.query)
                if u.path in STATIC_OPEN:             # the app shell is public; only /api/* needs the PIN
                    return self._static(u.path)
                if outer.pin and qs.get("pin", [""])[0] != outer.pin:
                    return self._send(403, "forbidden", "text/plain")
                if u.path == "/api/state":
                    return self._send(200, json.dumps(outer.state, ensure_ascii=False), "application/json")
                if u.path == "/api/cmd":
                    outer.push(("cmd", qs.get("c", [""])[0]))
                    return self._send(200, "{}", "application/json")
                if u.path in ("/api/text", "/api/meta", "/api/adhkar", "/api/page"):
                    try:
                        return self._send(200, json.dumps(api_data(u.path, qs), ensure_ascii=False), "application/json")
                    except Exception as e:
                        return self._send(500, json.dumps({"error": u"%s" % e}, ensure_ascii=False), "application/json")
                if u.path == "/api/play":
                    try:
                        outer.push(("play", qs.get("k", [""])[0], int(qs.get("i", ["0"])[0])))
                    except ValueError:
                        pass
                    return self._send(200, "{}", "application/json")
                self._send(404, "not found", "text/plain")

        try:
            self.httpd = HTTPServer(("0.0.0.0", self.port), Handler)
        except Exception:
            self.httpd = None
            return False
        self.httpd.timeout = 1
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        return True

    def stop(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
        self.httpd = None


def api_data(path, qs):
    """Read-only data for the phone (runs in the server thread; pure python, no enigma2)."""
    from . import data, extras, studio
    if path == "/api/meta":
        return {"surahs": [data.surah_name(i) for i in range(1, 115)],
                "tafsirs": [[k, t] for k, t, _s, _a, _q, _b in extras.TAFSIRS],
                "adhkar": [c[0] for c in studio.adhkar_categories()]}
    if path == "/api/adhkar":
        cats = studio.adhkar_categories()
        i = max(0, min(len(cats) - 1, int(qs.get("i", ["0"])[0])))
        return {"title": cats[i][0], "items": [[extras.sanitize(t), n] for t, n in cats[i][1]]}
    if path == "/api/page":                    # 2.1: the mushaf page on the phone, following the TV
        if "p" in qs:
            pg = int(qs["p"][0])
        else:
            pg = studio.page_of(int(qs.get("n", ["1"])[0]), int(qs.get("a", ["1"])[0]))
        pg = max(1, min(604, pg))
        out, texts = [], {}
        for n_, a_ in studio.page_ayahs(pg):
            if n_ not in texts:
                texts[n_] = dict(extras.local_verses(n_) or [])
            out.append([n_, a_, extras.sanitize(texts[n_].get(a_, u"")), data.surah_name(n_)])
        juz = 0
        try:
            juz = studio.juz_of(out[0][0], out[0][1]) if out else 0
        except Exception:
            pass
        return {"page": pg, "verses": out, "juz": juz}
    n = max(1, min(114, int(qs.get("n", ["1"])[0])))
    m = qs.get("m", ["text"])[0]
    if m not in ("text", "tafsir", "translation"):
        m = "text"
    tk = qs.get("t", ["muyassar"])[0]
    if tk not in extras.TAFSIR_BY_KEY:
        tk = "muyassar"
    blocks, note = extras.reader_load(n, m, tk)
    return {"n": n, "mode": m, "blocks": blocks, "note": note}


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"
