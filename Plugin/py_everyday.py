# -*- coding: utf-8 -*-
"""
{
  "name": "港灣直播",
  "key": "gw_everyday",
  "type": 3,
  "url": "",
  "api": "./Plugin/py_everyday.py",
  "playerType": 1,
  "timeout": 30,
  "ext": {
    "site_base": "http://99754106633f94d350db34d548d6091a.everydaytv.top"
  }
}
"""

import base64
import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime
from urllib.parse import quote, unquote, urlparse

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        siteKey = ""
        def getName(self):
            return ""
        def init(self, extend=""):
            pass
        def getProxyUrl(self, local=True):
            return ""
        def getCache(self, key):
            return None
        def setCache(self, key, value):
            return "fail"


DEFAULT_CFG = {
    "site_base": "http://99754106633f94d350db34d548d6091a.everydaytv.top",
    "list_url": "",
    "list_cache_ttl": 1800,
    "cache_version": 10,
    "token_override": "",
    "play_ua": (
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
        "Chrome/120.0 Mobile Safari/537.36"
    ),
    "de_map": {
        "~": "A", ":": "B", "-": "C", "@": "D", "#": "F", "%": "G",
        "'": "H", "&": "J", "*": "K", "?": "L", ";": "N", "!": "S",
        "_": "V", ")": "X", "(": "Z",
    },
}

ENABLE_LOG = True
LOG_PATH = "/sdcard/gw-everyday.log"
LOG_MAX = 1 * 1024 * 1024

_MEM = {"ts": 0.0, "data": None, "ver": 0}
_URL_CACHE = {}


def _log(msg, level="INFO"):
    if not ENABLE_LOG:
        return
    try:
        line = "[%s] [%s] %s\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            level,
            str(msg)[:400],
        )
        if os.path.exists(LOG_PATH):
            try:
                if os.path.getsize(LOG_PATH) >= LOG_MAX:
                    with open(LOG_PATH, "w", encoding="utf-8") as f:
                        f.write("[%s] [INFO] rotated\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


class Spider(BaseSpider):
    def getName(self):
        return "港灣直播"

    def init(self, extend=""):
        options = {}
        if isinstance(extend, dict):
            options = extend
        elif extend:
            try:
                options = json.loads(extend)
            except Exception:
                options = {}
        if not isinstance(options, dict):
            options = {}
        self.cfg = dict(DEFAULT_CFG)
        for k, v in options.items():
            if v is not None:
                self.cfg[k] = v
        if not isinstance(self.cfg.get("de_map"), dict):
            self.cfg["de_map"] = dict(DEFAULT_CFG["de_map"])
        _log("init siteKey=%s" % getattr(self, "siteKey", ""))

    def destroy(self):
        pass

    def _proxy_base(self):
        try:
            base = str(self.getProxyUrl(True) or "").strip()
        except Exception:
            base = ""
        if not base:
            try:
                from com.github.catvod import Proxy
                base = "%s?do=py" % Proxy.getUrl(True)
            except Exception:
                base = "http://127.0.0.1:9978/proxy?do=py"
        site = str(getattr(self, "siteKey", "") or "gw_everyday")
        sep = "&" if "?" in base else "?"
        return "%s%ssite=%s" % (base, sep, quote(site, safe=""))

    def _proxy_url(self, href):
        return "%s&type=live&play=%s" % (self._proxy_base(), quote(self._b64e(href), safe=""))

    # ---- 直播列表 ----
    def liveContent(self, url):
        del url
        try:
            cats = self._channels()
            if not cats:
                _log("liveContent no cats", "ERROR")
                return self._err_m3u("列表拉取失敗")
            groups = OrderedDict()
            seen = {}
            num = 0
            for gname, chans in cats:
                g = gname or "未分組"
                for ch, href in chans:
                    if not href or href in seen:
                        continue
                    seen[href] = True
                    num += 1
                    name = ch or href
                    item = {
                        "name": name,
                        "tvgName": name,
                        "tvgId": href,
                        "number": "{:03d}".format(num),
                        "format": "application/x-mpegURL",
                        "ua": self.cfg.get("play_ua", DEFAULT_CFG["play_ua"]),
                        "header": self._play_headers(),
                        "urls": [self._proxy_url(href)],
                    }
                    groups.setdefault(g, []).append(item)
            if not groups:
                return self._err_m3u("未解析到頻道")
            _log("liveContent groups=%d chans=%d" % (len(groups), num))
            return [{"name": n, "channel": items} for n, items in groups.items()]
        except Exception as e:
            _log("liveContent ex: %s" % e, "ERROR")
            return self._err_m3u("%s: %s" % (type(e).__name__, e))

    # ---- 選台：localProxy / proxy ----
    def localProxy(self, param):
        return self._do_proxy(param)

    def proxy(self, params):
        return self._do_proxy(params)

    def _do_proxy(self, param):
        try:
            if not isinstance(param, dict):
                param = dict(param) if param is not None else {}
            _log("localProxy keys=%s" % list(param.keys()))
            play = ""
            for k in ("play", "id", "url", "href"):
                if param.get(k):
                    play = str(param.get(k)).strip()
                    break
            if not play:
                for v in param.values():
                    s = str(v)
                    if "play-" in s or len(s) > 12:
                        play = s
                        break
            if not play:
                _log("localProxy missing play", "ERROR")
                return [400, "text/plain; charset=utf-8", "missing play"]

            play = unquote(play)
            href = play
            dec = self._b64d(play)
            if dec and re.search(r"play-\d+-\d+-\d+\.html", dec):
                href = dec
            href = self._norm(href)
            _log("localProxy href=%s" % href)

            real = self._real_url(href)
            if not real:
                _log("localProxy resolve fail %s" % href, "ERROR")
                return [500, "text/plain; charset=utf-8", "resolve fail: " + href]

            _log("localProxy real=%s" % real[:120])
            # 回 200 + playlist 內容（播放器跟清單內的 URL）
            body = (
                "#EXTM3U\n"
                "#EXT-X-VERSION:3\n"
                "#EXTINF:-1,live\n"
                "%s\n" % real
            )
            return [200, "application/vnd.apple.mpegurl", body]
        except Exception as e:
            _log("localProxy ex: %s" % e, "ERROR")
            return [500, "text/plain; charset=utf-8", str(e)[:160]]

    def homeContent(self, filter):
        return {"class": []}

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        return {"list": []}

    def detailContent(self, ids):
        return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        try:
            href = self._norm(id or "")
            if not re.search(r"play-\d+-\d+-\d+\.html", href):
                dec = self._b64d(id or "")
                if dec:
                    href = self._norm(dec)
            url = self._real_url(href)
            if not url:
                return {"parse": 0, "msg": "無法解析"}
            return {"parse": 0, "jx": 0, "url": url, "header": self._play_headers()}
        except Exception as e:
            return {"parse": 0, "msg": str(type(e).__name__)}

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".flv", ".m3u8", ".mp4", "/live/"))

    def manualVideoCheck(self):
        return False

    def _play_headers(self):
        return {
            "User-Agent": self.cfg.get("play_ua", DEFAULT_CFG["play_ua"]),
            "Referer": str(self.cfg.get("site_base") or DEFAULT_CFG["site_base"]).rstrip("/") + "/",
        }

    @staticmethod
    def _err_m3u(msg):
        msg = str(msg).replace(",", "，").replace("\n", " ")
        return "#EXTM3U\n#EXTINF:-1 group-title=\"錯誤\"," + msg + "\nhttp://127.0.0.1/null\n"

    def _http(self, url, timeout=25):
        try:
            from com.github.catvod.net import OkHttp
            from java.util import HashMap
            from java.util.concurrent import TimeUnit
            headers = HashMap()
            headers.put("User-Agent", "Mozilla/5.0 (compatible; GangwanM3U/1.0)")
            call = OkHttp.newCall(url, headers)
            call.timeout().timeout(int(timeout), TimeUnit.SECONDS)
            resp = call.execute()
            try:
                body = resp.body()
                if body is None:
                    return None
                text = str(body.string())
                return text if text else None
            finally:
                resp.close()
        except Exception as e:
            _log("OkHttp fail %s: %s" % (url[:60], e), "WARN")
        try:
            if hasattr(self, "fetch"):
                rsp = self.fetch(url)
                if isinstance(rsp, str) and rsp:
                    return rsp
                if rsp is not None:
                    t = getattr(rsp, "text", None)
                    if isinstance(t, str) and t:
                        return t
        except Exception:
            pass
        try:
            import ssl
            from urllib.request import Request, urlopen
            ctx = ssl._create_unverified_context()
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GangwanM3U/1.0)"})
            with urlopen(req, timeout=timeout, context=ctx) as r:
                data = r.read()
            for enc in ("utf-8", "gbk", "big5", "latin-1"):
                try:
                    return data.decode(enc)
                except Exception:
                    continue
            return data.decode("utf-8", errors="ignore")
        except Exception as e:
            _log("urllib fail %s: %s" % (url[:60], e), "WARN")
            return None

    def _decrypt(self, html):
        m = re.search(
            r'var\s+str=de\("([^"]*)"\)\.replace\(/([0-9a-f]+)/g,\'M\'\)',
            html or "",
            re.S,
        )
        if m:
            enc, token = m.group(1), m.group(2)
        else:
            m2 = re.search(r'de\("([^"]*)"\)', html or "", re.S)
            if not m2:
                return None
            enc = m2.group(1)
            token = self.cfg.get("token_override") or "65b52ae6cbf740ae4765ce18614c95d6"
        de_map = self.cfg.get("de_map") or DEFAULT_CFG["de_map"]
        for k, v in de_map.items():
            enc = enc.replace(k, v)
        enc = enc.replace(token, "M")
        try:
            pad = (4 - len(enc) % 4) % 4
            raw = base64.b64decode(enc + "=" * pad)
        except Exception:
            return None
        text = raw.decode("utf-8", errors="ignore")
        mu = re.search(r"(https?://\S+?\.(?:flv|m3u8|ts|mp4)(?:\?\S*)?)", text)
        if mu:
            return mu.group(1).rstrip("\"'")
        mu = re.search(r"(https?://[^\s\"'<>]+)", text)
        if mu:
            return mu.group(1).rstrip("\"'#")
        p = text.find("#")
        return text[:p].strip() if p != -1 else text.strip()

    def _real_url(self, href):
        key = self._norm(href)
        if key in _URL_CACHE:
            return _URL_CACHE[key]
        site = str(self.cfg.get("site_base") or DEFAULT_CFG["site_base"]).rstrip("/")
        if href.startswith("http"):
            play_url = href
        elif href.startswith("/"):
            play_url = site + href
        else:
            play_url = site + "/" + href
        play_html = self._http(play_url, timeout=25)
        if not play_html:
            alt = site + "/" + key
            if alt != play_url:
                play_html = self._http(alt, timeout=25)
        if not play_html:
            return None
        pm = re.search(r'src="([^"]*player-[0-9A-Fa-f]+\.html)"', play_html)
        if not pm:
            return None
        purl = pm.group(1)
        if not purl.startswith("http"):
            purl = site + (purl if purl.startswith("/") else "/" + purl)
        player_html = self._http(purl, timeout=25)
        if not player_html:
            path = urlparse(purl).path
            if path:
                player_html = self._http(site + path, timeout=25)
        if not player_html:
            return None
        real = self._decrypt(player_html)
        if real:
            _URL_CACHE[key] = real
        return real

    @staticmethod
    def _norm(href):
        m = re.search(r"play-\d+-\d+-\d+\.html", href or "")
        return m.group(0) if m else (href or "")

    def _cache_get(self):
        global _MEM
        ttl = int(self.cfg.get("list_cache_ttl", 1800))
        ver = int(self.cfg.get("cache_version", 10))
        if _MEM.get("data") is not None and _MEM.get("ver") == ver and (time.time() - _MEM["ts"]) < ttl:
            return _MEM["data"]
        try:
            raw = self.getCache("gw_list_v%s" % ver)
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, list) and data:
                    _MEM.update({"data": data, "ts": time.time(), "ver": ver})
                    return data
        except Exception:
            pass
        return None

    def _cache_set(self, cats):
        global _MEM
        ver = int(self.cfg.get("cache_version", 10))
        _MEM.update({"data": cats, "ts": time.time(), "ver": ver})
        try:
            self.setCache("gw_list_v%s" % ver, json.dumps(cats, ensure_ascii=False))
        except Exception:
            pass

    def _parse_accordion(self, html):
        cats = []
        for it in re.findall(r'<dl class="am-accordion-item.*?</dl>', html or "", re.S):
            tm = re.search(r'<dt class="am-accordion-title">(.*?)</dt>', it, re.S)
            if not tm:
                continue
            name = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
            if not name or len(name) > 60:
                continue
            if "語言" in name or "Language" in name:
                continue
            ddm = re.search(r'<dd class="am-accordion-bd.*?</dd>', it, re.S)
            if not ddm:
                continue
            chans = []
            for x in re.finditer(
                r'<a href="([^"]*play-\d+-\d+-\d+\.html)"[^>]*>([^<]+)</a>',
                ddm.group(0),
            ):
                chans.append((x.group(2).strip(), self._norm(x.group(1))))
            if chans:
                cats.append((name, chans))
        return cats

    def _parse_gallery(self, html):
        chans = []
        for x in re.finditer(
            r'<a href="([^"]*play-\d+-\d+-\d+\.html)"[^>]*>([^<]+)</a>',
            html or "",
        ):
            n = x.group(2).strip()
            if n:
                chans.append((n, self._norm(x.group(1))))
        return chans

    def _channels(self):
        cached = self._cache_get()
        if cached is not None:
            return cached
        site = str(self.cfg.get("site_base") or DEFAULT_CFG["site_base"]).rstrip("/")
        list_url = self.cfg.get("list_url") or (site + "/list.html")
        html = self._http(list_url)
        cats = self._parse_accordion(html) if html else []
        if not cats or sum(len(c[1]) for c in cats) < 5:
            extra = []
            for path, gname in (("list-0.html", "香港頻道"), ("list-1.html", "台灣頻道")):
                h = self._http(site + "/" + path)
                if not h:
                    continue
                ch = self._parse_gallery(h)
                if ch:
                    extra.append((gname, ch))
            if extra:
                cats = extra
        if cats:
            self._cache_set(cats)
        return cats or None

    @staticmethod
    def _b64e(s):
        return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def _b64d(s):
        try:
            pad = (4 - len(s) % 4) % 4
            return base64.urlsafe_b64decode(s + "=" * pad).decode("utf-8")
        except Exception:
            return None
