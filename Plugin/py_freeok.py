# -*- coding: utf-8 -*-
"""
配置示例：
{
  "key": "freeok",
  "name": "FreeOK",
  "type": 3,
  "api": "py_freeok",
  "searchable": 1,
  "quickSearch": 1,
  "filterable": 1,
  "ext": ""
}
"""

import json
import re
import time
import ssl
import urllib.request
import urllib.parse
import urllib.error

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


class Spider(_BaseSpider):
    def init(self, extend=""):
        self.extend = extend or ""
        self.base = "https://freeok.com.de"
        self.host_param = "freeok.com.de"
        self.sion_id = ""
        self._ssl = ssl._create_unverified_context()
        self._timeout = 15
        self._ua = (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        )
        self.classes = [
            {"type_id": "dianying", "type_name": "电影"},
            {"type_id": "dianshiju", "type_name": "电视剧"},
            {"type_id": "zongyi", "type_name": "综艺"},
            {"type_id": "dongman", "type_name": "动漫"},
            {"type_id": "duanju", "type_name": "短剧"},
        ]
        self._parse_ext(self.extend)

    def _parse_ext(self, extend):
        if not extend:
            return
        s = str(extend).strip()
        try:
            if s.startswith("{"):
                obj = json.loads(s)
                self.base = (obj.get("base") or obj.get("url") or self.base).rstrip("/")
                self.sion_id = obj.get("sion_id") or self.sion_id
                self.host_param = obj.get("host") or self.host_param
                return
        except Exception:
            pass
        # URL form
        if s.startswith("http"):
            u = urllib.parse.urlparse(s)
            self.base = "%s://%s" % (u.scheme, u.netloc)
            qs = urllib.parse.parse_qs(u.query)
            if qs.get("sion_id"):
                self.sion_id = qs["sion_id"][0]
            if qs.get("host"):
                self.host_param = qs["host"][0]
            return
        if "sion_id=" in s:
            m = re.search(r"sion_id=([a-f0-9]+)", s)
            if m:
                self.sion_id = m.group(1)

    def getName(self):
        return "FreeOK"

    def destroy(self):
        pass

    def _qs(self, extra=None):
        q = {}
        if self.host_param:
            q["host"] = self.host_param
        if self.sion_id:
            q["sion_id"] = self.sion_id
        if extra:
            q.update(extra)
        return urllib.parse.urlencode(q)

    def _url(self, path, extra=None):
        path = path if path.startswith("/") else "/" + path
        q = self._qs(extra)
        if "?" in path:
            return self.base + path + ("&" + q if q else "")
        return self.base + path + (("?" + q) if q else "")

    def _get(self, path_or_url, retries=2):
        url = path_or_url if path_or_url.startswith("http") else self._url(path_or_url)
        last = None
        for i in range(retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": self._ua,
                        "Referer": self.base + "/",
                        "Accept": "text/html,application/json,*/*",
                    },
                )
                with urllib.request.urlopen(req, context=self._ssl, timeout=self._timeout) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                last = e
                time.sleep(1.2 * (i + 1))
        raise RuntimeError("GET fail %s: %s" % (url, last))

    def _abs(self, u):
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        return self.base + (u if u.startswith("/") else "/" + u)

    def _item_from_href(self, href, name="", pic=""):
        # /movie/xxx-123.html or /tv/xxx-123.html
        m = re.search(r"/(movie|tv)/([a-z0-9-]+)\.html", href)
        if not m:
            return None
        kind, vid = m.group(1), m.group(2)
        return {
            "vod_id": "%s:%s" % (kind, vid),
            "vod_name": name or vid,
            "vod_pic": self._abs(pic) if pic else "",
            "vod_remarks": "",
        }

    def _parse_list(self, html):
        items = []
        seen = set()
        # card pattern with img alt
        for m in re.finditer(
            r'href="(/(?:movie|tv)/([a-z0-9-]+)\.html)[^"]*"[^>]*>.*?(?:src|data-src)="([^"]+)"[^>]*alt="([^"]*)"',
            html,
            re.S,
        ):
            href, vid, pic, name = m.group(1), m.group(2), m.group(3), m.group(4)
            kind = "tv" if "/tv/" in href else "movie"
            key = "%s:%s" % (kind, vid)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "vod_id": key,
                    "vod_name": name or vid,
                    "vod_pic": self._abs(pic),
                    "vod_remarks": "",
                }
            )
        if items:
            return items
        # fallback: ids only
        for m in re.finditer(r'href="(/(?:movie|tv)/([a-z0-9-]+)\.html)[^"]*"', html):
            href, vid = m.group(1), m.group(2)
            kind = "tv" if "/tv/" in href else "movie"
            key = "%s:%s" % (kind, vid)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "vod_id": key,
                    "vod_name": vid,
                    "vod_pic": "",
                    "vod_remarks": "",
                }
            )
        return items

    def homeContent(self, filter):
        result = {"class": list(self.classes)}
        if filter:
            # 简易类型筛选（电影页 class 参数）
            genres = [
                "剧情",
                "喜剧",
                "动作",
                "爱情",
                "惊悚",
                "犯罪",
                "恐怖",
                "悬疑",
                "冒险",
                "奇幻",
                "科幻",
                "战争",
                "动画",
            ]
            result["filters"] = {
                "dianying": [
                    {
                        "key": "class",
                        "name": "类型",
                        "value": [{"n": "全部", "v": ""}]
                        + [{"n": g, "v": g} for g in genres],
                    }
                ]
            }
        return result

    def homeVideoContent(self):
        try:
            html = self._get("/dianying.html")
            return {"list": self._parse_list(html)[:24]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = str(pg or "1")
            path = "/%s.html" % tid
            extra = {}
            if str(pg) not in ("1", ""):
                extra["page"] = pg
            if isinstance(extend, dict) and extend.get("class"):
                extra["class"] = extend["class"]
            html = self._get(path + (("?" + urllib.parse.urlencode(extra)) if extra else ""))
            lst = self._parse_list(html)
            pagecount = 50 if lst else 1
            if re.search(r"page=%s" % (int(pg) + 1), html) or len(lst) >= 20:
                pagecount = max(int(pg) + 1, 50)
            return {
                "list": lst,
                "page": int(pg),
                "pagecount": pagecount,
                "limit": 24,
                "total": pagecount * 24,
            }
        except Exception:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 24, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        try:
            html = self._get("/search.html?wd=%s" % urllib.parse.quote(key))
            return {"list": self._parse_list(html), "page": int(pg or 1)}
        except Exception:
            return {"list": [], "page": 1}

    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, list) else ids
            if ":" in raw:
                kind, vid = raw.split(":", 1)
            else:
                kind, vid = "movie", raw
            path = "/%s/%s.html" % (kind, vid)
            html = self._get(path)
            name = ""
            mt = re.search(r"<title>《?([^》|<]+)", html)
            if mt:
                name = mt.group(1).strip()
            pic = ""
            pm = re.search(r'property="og:image"\s+content="([^"]+)"', html)
            if pm:
                pic = self._abs(pm.group(1))
            content = ""
            dm = re.search(r'<meta name="description" content="([^"]+)"', html)
            if dm:
                content = dm.group(1)
            # 线路 origins（详情页切换片源）
            origins = []
            for o in re.findall(r"origin=([^&\"']+)", html):
                o = urllib.parse.unquote(o.replace("&amp;", "").split("&")[0])
                if not o or o in origins or "\\u" in o or len(o) > 30:
                    continue
                if o in ("", "null"):
                    continue
                origins.append(o)
            if not origins:
                origins = ["超级线路"]

            # 集数：p=0..N 或 单集电影
            p_vals = sorted(set(int(x) for x in re.findall(r"[?&]p=(\d+)", html)))
            if not p_vals:
                p_vals = [0]

            # 播放页路径中的 ep 段：/movie/hash/num.html
            ep_seg = None
            m = re.search(r"/%s/([a-f0-9]+)/(\d+)\.html" % kind, html)
            if m:
                hash_id, ep_seg = m.group(1), m.group(2)
            else:
                # vid = hash-num
                parts = vid.rsplit("-", 1)
                hash_id = parts[0]
                ep_seg = parts[1] if len(parts) > 1 else "1"

            play_from = []
            play_url = []
            for origin in origins:
                play_from.append(origin)
                eps = []
                for p in p_vals:
                    title = "第%02d集" % (p + 1) if len(p_vals) > 1 else "正片"
                    # id 编码：kind|hash|ep_seg|origin|p
                    flag = "%s|%s|%s|%s|%s" % (kind, hash_id, ep_seg, origin, p)
                    eps.append("%s$%s" % (title, flag))
                play_url.append("#".join(eps))

            vod = {
                "vod_id": raw,
                "vod_name": name or vid,
                "vod_pic": pic,
                "vod_content": content,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self._ua,
            "Referer": self.base + "/",
        }
        try:
            parts = id.split("|")
            if len(parts) < 5:
                return {"parse": 1, "url": id, "header": headers}
            kind, hash_id, ep_seg, origin, p = parts[0], parts[1], parts[2], parts[3], parts[4]
            path = "/%s/%s/%s.html?origin=%s&p=%s" % (
                kind,
                hash_id,
                ep_seg,
                urllib.parse.quote(origin),
                p,
            )
            html = self._get(path)
            # JSON.parse('{...url...}')
            play = None
            for m in re.finditer(r"JSON\.parse\('(\{.*?\})'\)", html):
                raw = m.group(1)
                try:
                    # unicode escapes
                    s = raw.encode("utf-8").decode("unicode_escape")
                except Exception:
                    s = raw.replace("\\/", "/")
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                u = obj.get("url") or ""
                if not u:
                    continue
                if u.startswith("/api/m3u8"):
                    # 相对接口 → 拼完整，可被播放器直接拉
                    play = self._url(u.replace("&amp;", "&"))
                elif u.startswith("http"):
                    play = u
                if play:
                    break
            # fallback: /api/m3u8 链接
            if not play:
                apis = re.findall(r"/api/m3u8\?[^\"']+", html)
                if apis:
                    play = self._abs(apis[0].replace("&amp;", "&"))
            if play:
                return {"parse": 0, "url": play, "header": headers}
            return {"parse": 1, "url": self._url(path), "header": headers}
        except Exception:
            return {"parse": 1, "url": id, "header": headers}

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4)(\?|$)", url or "", re.I) or "/api/m3u8" in (url or ""))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return []
