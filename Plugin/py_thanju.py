# -*- coding: utf-8 -*-
"""
依賴：僅標準庫（urllib / re / json / ssl）

配置示例：
{
  "key": "thanju",
  "name": "韩剧网",
  "type": 3,
  "api": "thanju",
  "searchable": 1,
  "quickSearch": 1,
  "filterable": 1,
  "ext": ""
}

ext 可選（& 分隔）：
  host=https://www.thanju.com
  ua=Mozilla/5.0 ...
"""
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

HOST = "https://www.thanju.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# type_id → 站內分類 id（list-select-id-N）
CATALOG = (
    ("1", "韩剧"),
    ("2", "电影"),
    ("3", "综艺"),
)

YEARS = [str(y) for y in range(2026, 2009, -1)]
ORDERS = (
    ("addtime", "最新"),
    ("hits", "人气"),
    ("score", "评分"),
)


def _abs(url, base=HOST):
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urllib.parse.urljoin(base.rstrip("/") + "/", url.lstrip("/"))


def _clip(s, n=80):
    s = re.sub(r"[\r\n\t#$]+", " ", str(s or "")).strip()
    return s[:n] if n > 0 else s


def _safe_label(s):
    return _clip(s, 40).replace("$", "＄").replace("#", "＃")


class Spider(_BaseSpider):
    def __init__(self):
        self.host = HOST
        self.ua = UA
        self._cache = {}

    def init(self, extend=""):
        opts = {}
        if isinstance(extend, dict):
            opts = {str(k): str(v) for k, v in extend.items()}
        elif extend:
            s = str(extend).strip()
            if s.startswith("{"):
                try:
                    opts = json.loads(s)
                except Exception:
                    opts = {}
            else:
                for kv in re.split(r"[&\n;]+", s):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        opts[k.strip()] = v.strip()
        self.host = (opts.get("host") or HOST).rstrip("/")
        self.ua = opts.get("ua") or UA
        self._cache = {}

    def getName(self):
        return "韩剧网"

    def destroy(self):
        self._cache = {}

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".mkv", ".flv", ".ts"))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [404, "text/plain", "", {}]

    # ---------------- 入口 ----------------
    def homeContent(self, filter=False):
        classes = [{"type_id": tid, "type_name": name} for tid, name in CATALOG]
        result = {"class": classes}
        if filter:
            result["filters"] = {
                tid: [
                    {
                        "key": "year",
                        "name": "年份",
                        "init": "",
                        "value": [{"n": "全部", "v": ""}]
                        + [{"n": y, "v": y} for y in YEARS],
                    },
                    {
                        "key": "order",
                        "name": "排序",
                        "init": "addtime",
                        "value": [{"n": n, "v": v} for v, n in ORDERS],
                    },
                ]
                for tid, _ in CATALOG
            }
        return result

    def homeVideoContent(self):
        try:
            html = self._get(self.host + "/")
            items = self._parse_cards(html)
            return {"list": items[:24]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            page = max(1, int(str(pg or "1")))
        except Exception:
            page = 1
        extend = extend if isinstance(extend, dict) else {}
        tid = str(tid or "1").strip()
        year = str(extend.get("year") or "").strip()
        order = str(extend.get("order") or "addtime").strip() or "addtime"
        if order not in {v for v, _ in ORDERS}:
            order = "addtime"
        if tid not in {t for t, _ in CATALOG}:
            tid = "1"
        url = self._list_url(tid, year=year, order=order, page=page)
        try:
            html = self._get(url)
            items = self._parse_cards(html)
            pagecount = self._pagecount(html, page)
            return {
                "list": items,
                "page": page,
                "pagecount": pagecount,
                "limit": 30,
                "total": pagecount * 30,
            }
        except Exception as e:
            return {
                "list": [],
                "page": page,
                "pagecount": 1,
                "limit": 30,
                "total": 0,
                "msg": "%s %s" % (type(e).__name__, e),
            }

    def searchContent(self, key, quick=False, pg="1"):
        del quick
        try:
            page = max(1, int(str(pg or "1")))
        except Exception:
            page = 1
        key = (key or "").strip()
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            items = self._search(key, page)
            more = len(items) >= 20
            return {
                "list": items,
                "page": page,
                "pagecount": page + 1 if more else page,
                "limit": 20,
                "total": len(items),
            }
        except Exception as e:
            return {
                "list": [],
                "page": page,
                "pagecount": 1,
                "limit": 20,
                "total": 0,
                "msg": "%s %s" % (type(e).__name__, e),
            }

    def detailContent(self, ids):
        raw = str((ids or [""])[0] if isinstance(ids, (list, tuple)) else (ids or ""))
        raw = raw.strip()
        m = re.search(r"(\d+)", raw)
        if not m:
            return {"list": [], "msg": "无效 ID"}
        vid = m.group(1)
        try:
            html = self._get("%s/detail/%s.html" % (self.host, vid))
            vod = self._parse_detail(html, vid)
            return {"list": [vod]}
        except Exception as e:
            return {"list": [], "msg": "%s %s" % (type(e).__name__, e)}

    def playerContent(self, flag, id, vipFlags=None):
        del flag, vipFlags
        pid = (id or "").strip()
        head = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Origin": self.host,
        }
        if pid.startswith("http://") or pid.startswith("https://"):
            return {"parse": 0, "url": pid, "header": head}
        # play path: /play/{id}/{sid}-{eid}.html  or  id/sid-eid
        path = pid
        if not path.startswith("/"):
            if re.match(r"^\d+/\d+-\d+$", path):
                path = "/play/%s.html" % path
            elif re.match(r"^\d+$", path):
                path = "/play/%s/1-1.html" % path
            else:
                path = "/" + path.lstrip("/")
        if not path.endswith(".html"):
            path = path + ".html"
        try:
            html = self._get(self.host + path)
            url = self._extract_play_url(html)
            if not url:
                return {"parse": 1, "url": self.host + path, "header": head}
            parse = 0 if self.isVideoFormat(url) else 1
            return {"parse": parse, "url": url, "header": head}
        except Exception as e:
            return {"parse": 0, "url": "", "header": {}, "error": "%s %s" % (type(e).__name__, e)}

    # ---------------- 网络 ----------------
    def _get(self, url, ttl=120):
        ck = "G:" + url
        now = time.time()
        if ttl > 0 and ck in self._cache and now - self._cache[ck][0] < ttl:
            return self._cache[ck][1]
        body = self._request(url)
        if ttl > 0:
            self._cache[ck] = (now, body)
        return body

    def _post(self, url, data, ttl=60):
        ck = "P:" + url + "|" + str(data)
        now = time.time()
        if ttl > 0 and ck in self._cache and now - self._cache[ck][0] < ttl:
            return self._cache[ck][1]
        body = self._request(url, data=data)
        if ttl > 0:
            self._cache[ck] = (now, body)
        return body

    def _request(self, url, data=None, timeout=20):
        headers = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if data is not None:
            if isinstance(data, dict):
                data = urllib.parse.urlencode(data).encode("utf-8")
            elif isinstance(data, str):
                data = data.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers)
        ctx = ssl._create_unverified_context()
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
        except TypeError:
            resp = urllib.request.urlopen(req, timeout=timeout)
        try:
            raw = resp.read()
        finally:
            resp.close()
        for enc in ("utf-8", "gbk", "gb2312"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", "replace")

    # ---------------- 列表 / 筛选 URL ----------------
    def _list_url(self, tid, year="", order="addtime", page=1):
        # /list-select-id-{tid}-type--area--year-{year}-star--state--order-{order}.html
        # 分页：...-order-{order}-p-{page}.html
        year = year or ""
        base = (
            "/list-select-id-%s-type--area--year-%s-star--state--order-%s"
            % (tid, year, order)
        )
        if page and int(page) > 1:
            base += "-p-%d" % int(page)
        return self.host + base + ".html"

    def _pagecount(self, html, current):
        pages = [int(x) for x in re.findall(r"-p-(\d+)\.html", html)]
        if not pages:
            # 无分页链接则只有一页或看是否还有下一页字样
            if re.search(r"下一页|page-next", html):
                return current + 1
            return max(1, current)
        return max(pages + [current])

    # ---------------- 解析列表卡片 ----------------
    def _parse_cards(self, html):
        items = []
        seen = set()
        # 首页 / 分类：thumb + background url 或 data-original
        for m in re.finditer(
            r'<a\s+([^>]*class="[^"]*myui-vodlist__thumb[^"]*"[^>]*)>([\s\S]{0,400}?)</a>',
            html,
            re.I,
        ):
            attrs, inner = m.group(1), m.group(2)
            href = self._attr(attrs, "href")
            title = self._attr(attrs, "title")
            if not href or "/detail/" not in href:
                continue
            mid = re.search(r"/detail/(\d+)\.html", href)
            if not mid:
                continue
            vid = mid.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            pic = ""
            bg = re.search(r"url\(([^)]+)\)", attrs)
            if bg:
                pic = bg.group(1).strip(" '\"")
            if not pic:
                pic = self._attr(attrs, "data-original") or self._attr(attrs, "src")
            remark = ""
            rm = re.search(r'pic-text[^>]*>([^<]+)', inner)
            if not rm:
                # 备注可能在 a 后的兄弟节点，取后续一小段
                tail = html[m.end() : m.end() + 280]
                rm = re.search(r'pic-text[^>]*>([^<]+)', tail)
            if rm:
                remark = rm.group(1).strip()
            items.append(
                {
                    "vod_id": vid,
                    "vod_name": _clip(title or ("影片" + vid)),
                    "vod_pic": _abs(pic, self.host),
                    "vod_remarks": _clip(remark, 20),
                }
            )
        # 搜索列表：media 横向卡
        if not items:
            for m in re.finditer(
                r'<li class="active[^"]*"[\s\S]{0,1200}?</li>', html, re.I
            ):
                block = m.group(0)
                mid = re.search(r"/detail/(\d+)\.html", block)
                if not mid:
                    continue
                vid = mid.group(1)
                if vid in seen:
                    continue
                seen.add(vid)
                title = ""
                tm = re.search(r'title=[\'"]([^\'"]+)[\'"]', block)
                if tm:
                    title = tm.group(1)
                pic = ""
                pm = re.search(
                    r'(?:data-original|src)=[\'"]([^\'"]+)[\'"]', block
                )
                if pm:
                    pic = pm.group(1)
                remark = ""
                rm = re.search(r'pic-text[^>]*>([^<]+)', block)
                if rm:
                    remark = rm.group(1).strip()
                items.append(
                    {
                        "vod_id": vid,
                        "vod_name": _clip(title or ("影片" + vid)),
                        "vod_pic": _abs(pic, self.host),
                        "vod_remarks": _clip(remark, 20),
                    }
                )
        return items

    @staticmethod
    def _attr(attrs, name):
        m = re.search(
            r'\b' + re.escape(name) + r'\s*=\s*[\'"]([^\'"]*)[\'"]',
            attrs,
            re.I,
        )
        return m.group(1).strip() if m else ""

    # ---------------- 搜索 ----------------
    def _search(self, key, page=1):
        # POST 表单（站內實際用法）
        data = {"wd": key, "submit": "submit"}
        html = self._post(self.host + "/index.php?s=vod-search", data, ttl=90)
        items = self._parse_cards(html)
        if items:
            return items
        # 回退 GET /search/kw.html
        url = "%s/search/%s.html" % (self.host, urllib.parse.quote(key))
        if page > 1:
            # 若站有搜索分页，常见 -p-N；无则忽略
            url = "%s/search/%s-p-%d.html" % (
                self.host,
                urllib.parse.quote(key),
                page,
            )
        html = self._get(url, ttl=90)
        return self._parse_cards(html)

    # ---------------- 详情 ----------------
    def _parse_detail(self, html, vid):
        title = ""
        m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        if m:
            title = m.group(1).strip()
        pic = ""
        m = re.search(
            r'myui-content__thumb[\s\S]{0,400}?(?:data-original|src)=[\'"]([^\'"]+)[\'"]',
            html,
            re.I,
        )
        if m:
            pic = m.group(1)
        if not pic:
            m = re.search(r'content__thumb[\s\S]{0,200}?url\(([^)]+)\)', html)
            if m:
                pic = m.group(1).strip(" '\"")

        def meta(label):
            pat = (
                r">\s*"
                + re.escape(label)
                + r"\s*[:：]?\s*<[\s\S]{0,120}?>([^<]{1,80})<"
            )
            mm = re.search(pat, html)
            return _clip(mm.group(1), 60) if mm else ""

        director = meta("导演")
        actor = meta("主演")
        tname = meta("类型") or meta("分類")
        area = meta("地区") or meta("地區")
        year = meta("年份") or meta("上映")
        remarks = meta("更新") or meta("状态") or meta("狀態")
        content = ""
        # 1) <strong>剧情：</strong>正文</span>
        mm = re.search(
            r"<strong>\s*剧情\s*[:：]?\s*</strong>\s*([\s\S]{15,2000}?)</(?:span|div|p)>",
            html,
            re.I,
        )
        if mm:
            content = mm.group(1)
        if len(content) < 20:
            # 2) span.sketch 整块
            mm = re.search(
                r'<span[^>]+class="[^"]*sketch[^"]*"[^>]*>([\s\S]{15,2000}?)</span>',
                html,
                re.I,
            )
            if mm:
                content = mm.group(1)
        if len(content) < 20:
            # 3) meta description
            mm = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
                html,
                re.I,
            )
            if not mm:
                mm = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
                    html,
                    re.I,
                )
            if mm:
                content = mm.group(1)
                # 去掉「片名 / 英文，剧情:」前缀
                content = re.sub(r"^.*?剧情\s*[:：]\s*", "", content)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
        # 避免只抓到栏目标题
        if content in ("剧情介绍", "剧情简介", "简介", "介紹", "劇情介紹"):
            content = ""

        tabs = re.findall(r'href="#playlist(\d+)"[^>]*>([^<]+)</a>', html)
        if not tabs:
            tabs = re.findall(
                r'data-target="#playlist(\d+)"[^>]*>([^<]+)</a>', html
            )

        froms, urls = [], []
        used = set()
        for sid, sname in tabs:
            block_m = re.search(
                r'id="playlist%s"[\s\S]*?<ul[^>]*>([\s\S]*?)</ul>'
                % re.escape(sid),
                html,
                re.I,
            )
            if not block_m:
                continue
            eps = re.findall(
                r"<a[^>]+title=['\"]([^'\"]*)['\"][^>]+href=['\"]([^'\"]+)['\"][^>]*>"
                r"|<a[^>]+href=['\"]([^'\"]+)['\"][^>]+title=['\"]([^'\"]*)['\"][^>]*>",
                block_m.group(1),
            )
            parts = []
            for g in eps:
                if g[0] and g[1]:
                    name, href = g[0], g[1]
                elif g[2] and g[3]:
                    href, name = g[2], g[3]
                else:
                    continue
                if "/play/" not in href:
                    continue
                play_val = href if href.startswith("/") else "/" + href
                parts.append("%s$%s" % (_safe_label(name or "正片"), play_val))
            if not parts:
                continue
            flag = _safe_label(sname) or ("线路" + sid)
            if flag in used:
                flag = "%s%s" % (flag, sid)
            used.add(flag)
            froms.append(flag)
            urls.append("#".join(parts))

        if not froms:
            all_eps = re.findall(
                r"href=['\"](/play/%s/(\d+)-(\d+)\.html)['\"][^>]*"
                r"(?:>([^<]+)<|title=['\"]([^'\"]+)['\"])"
                % re.escape(vid),
                html,
            )
            by = {}
            for href, sid, eid, t1, t2 in all_eps:
                name = (t1 or t2 or eid).strip()
                by.setdefault(sid, []).append(
                    "%s$%s" % (_safe_label(name), href)
                )
            for sid in sorted(by.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                froms.append("线路" + sid)
                # 去重保序
                seen = set()
                ordered = []
                for p in by[sid]:
                    if p not in seen:
                        seen.add(p)
                        ordered.append(p)
                urls.append("#".join(ordered))

        return {
            "vod_id": vid,
            "vod_name": _clip(title) or ("影片" + vid),
            "vod_pic": _abs(pic, self.host),
            "vod_year": _clip(year, 10),
            "vod_area": _clip(area, 20),
            "vod_actor": _clip(actor, 80),
            "vod_director": _clip(director, 40),
            "vod_content": _clip(content, 400),
            "vod_remarks": _clip(remarks, 30),
            "type_name": _clip(tname, 30),
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }

    # ---------------- 播放地址 ----------------
    def _extract_play_url(self, html):
        # var cms_player = {...}
        m = re.search(
            r"cms_player\s*=\s*(\{.*?})\s*;", html, re.S
        )
        if m:
            try:
                # 允许非严格 JSON：替换
                raw = m.group(1)
                obj = json.loads(raw)
                url = (obj.get("url") or "").strip()
                if url:
                    return url.replace("\\/", "/")
            except Exception:
                um = re.search(r'"url"\s*:\s*"([^"]+)"', m.group(1))
                if um:
                    return um.group(1).replace("\\/", "/")
        # 直接 m3u8 / mp4
        m = re.search(
            r'(https?://[^\'"\s<>]+?\.(?:m3u8|mp4)[^\'"\s<>]*)', html, re.I
        )
        if m:
            return m.group(1).replace("\\/", "/")
        # iframe
        m = re.search(r'<iframe[^>]+src=[\'"]([^\'"]+)[\'"]', html, re.I)
        if m:
            return _abs(m.group(1), self.host)
        return ""
