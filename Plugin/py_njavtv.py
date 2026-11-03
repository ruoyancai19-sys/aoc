#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nJAVTV (njavtv.com) — 日文 /cn/
TLS 過盾（同 MissAV）+ 精簡分類 + 獨立篩選 + 屏蔽頁腳雜訊。
分類：最近更新 / 新作上市 / 女優一覽 / 女優排行 / 發行商 / VR / 素人 / 無碼影片 / 亞洲AV
"""

import re
import json
import html as html_lib
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
import gzip
import zlib
import ssl
import socket

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        def getCache(self, key):
            return None

        def setCache(self, key, value):
            return "fail"

        def delCache(self, key):
            return "fail"


# 頁腳/導航雜訊 slug（出現在列表中的非影片連結）
BANNED_SLUGS = frozenset({
    "contact", "terms", "privacy", "dmca", "about", "faq", "login", "register",
    "upload", "advertise", "advertis", "sitemap", "rss", "feed", "api",
    "cn", "en", "ja", "zh", "id", "de", "fr", "es", "pt", "ko", "th",
    "new", "release", "genres", "makers", "actresses", "search", "ranking",
    "uncensored-leak", "uncensored", "vr", "fc2", "heyzo", "page",
})

# 標題雜訊（站務 + 分類名誤入列表；廣告主依「無封面」過濾）
BANNED_TITLE_KW = (
    "お問い合わせ", "利用規約", "広告", "動畫をアップ", "動画をアップ",
    "お問い合わせ", "广告查询", "聯繫", "服務條款", "上傳", "問い合わせ",
    "Contact", "Terms", "Advertis", "Upload", "Privacy", "DMCA",
    # 分類/標籤名誤當影片
    "中文字幕", "MARRIEDSLASH", "NAUGHTY4610", "NAUGHTY0930", "GACHINCO",
    "MADOU", "TWAV", "FURUKE", "SIRO", "LUXU", "GANA", "SCUTE", "ARA",
    "MAAN", "1PONDO", "CARIBBEANCOM", "CARIBBEANCOMPR", "TOKYOHOT",
    "PACOPACOMAMA", "XXXAV", "10MUSUME",
)

# 素人子分類 → 路徑（併入篩選）
AMATEUR_FILTERS = [
    {"n": "全部", "v": ""},
    {"n": "FC2", "v": "fc2"},
    {"n": "SIRO", "v": "siro"},
    {"n": "LUXU", "v": "luxu"},
    {"n": "GANA", "v": "gana"},
    {"n": "S-CUTE", "v": "scute"},
    {"n": "ARA", "v": "ara"},
    {"n": "PRESTIGE PREMIUM", "v": "maan"},
    {"n": "人妻斬", "v": "marriedslash"},
    {"n": "H4610", "v": "naughty4610"},
    {"n": "H0930", "v": "naughty0930"},
]

# 無碼子分類 → 路徑
UNCENSORED_FILTERS = [
    {"n": "全部", "v": ""},
    {"n": "無碼洩漏", "v": "uncensored_leak"},
    {"n": "FC2", "v": "fc2"},
    {"n": "HEYZO", "v": "heyzo"},
    {"n": "一本道", "v": "1pondo"},
    {"n": "加勒比", "v": "caribbeancom"},
    {"n": "Caribbeancompr", "v": "caribbeancompr"},
    {"n": "東京熱", "v": "tokyohot"},
    {"n": "天然素人", "v": "10musume"},
    {"n": "人妻・熟女", "v": "pacopacomama"},
    {"n": "Gachinco", "v": "gachinco"},
    {"n": "XXX-AV", "v": "xxxav"},
    {"n": "人妻斬", "v": "marriedslash"},
    {"n": "H4610", "v": "naughty4610"},
    {"n": "H0930", "v": "naughty0930"},
]

# 亞洲AV 子分類
ASIA_FILTERS = [
    {"n": "全部", "v": ""},
    {"n": "麻豆傳媒", "v": "madou"},
    {"n": "TWAV", "v": "twav"},
    {"n": "Furuke", "v": "furuke"},
]

SORT_FILTER = [
    {"n": "默認排序", "v": "default"},
    {"n": "發布日期", "v": "released_at"},
    {"n": "最近更新", "v": "published_at"},
    {"n": "今日觀看", "v": "today_views"},
    {"n": "本週觀看", "v": "weekly_views"},
    {"n": "本月觀看", "v": "monthly_views"},
    {"n": "總觀看", "v": "views"},
    {"n": "收藏數", "v": "saved"},
]

TYPE_FILTER = [
    {"n": "全部", "v": "all"},
    {"n": "單人作品", "v": "individual"},
    {"n": "多人作品", "v": "multiple"},
]


class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.primaryHost = "https://njavtv.com"
        self.baseHost = self.primaryHost
        self._ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
        self.options = {}

        # 路徑表（子分類共用）
        self.routes = {
            "new": "/dm539/cn/new",
            "release": "/dm635/cn/release",
            "uncensored_leak": "/dm817/cn/uncensored-leak",
            "actresses": "/cn/actresses",
            "actresses_ranking": "/cn/actresses/ranking",
            "makers": "/cn/makers",
            "vr": "/cn/genres/VR",
            "fc2": "/dm597/cn/fc2",
            "heyzo": "/dm2208642/cn/heyzo",
            "tokyohot": "/dm42/cn/tokyohot",
            "1pondo": "/dm5199603/cn/1pondo",
            "caribbeancom": "/dm7704788/cn/caribbeancom",
            "caribbeancompr": "/dm91887/cn/caribbeancompr",
            "10musume": "/dm7208981/cn/10musume",
            "pacopacomama": "/dm3600557/cn/pacopacomama",
            "gachinco": "/dm150/cn/gachinco",
            "xxxav": "/dm42/cn/xxxav",
            "marriedslash": "/dm37/cn/marriedslash",
            "naughty4610": "/dm33/cn/naughty4610",
            "naughty0930": "/dm37/cn/naughty0930",
            "siro": "/dm36/cn/siro",
            "luxu": "/dm34/cn/luxu",
            "gana": "/dm34/cn/gana",
            "scute": "/dm38/cn/scute",
            "ara": "/dm34/cn/ara",
            "maan": "/dm1004/cn/maan",
            "madou": "/dm63/cn/madou",
            "twav": "/dm31/cn/twav",
            "furuke": "/dm15/cn/furuke",
            # 頂層分類預設入口
            "amateur": "/dm597/cn/fc2",
            "uncensored": "/dm817/cn/uncensored-leak",
            "asia": "/dm63/cn/madou",
        }

        self.color_palette = [
            ("1e3a8a", "60a5fa"), ("14532d", "4ade80"), ("701a75", "f472b6"),
            ("7c2d12", "fb923c"), ("1f2937", "38bdf8"), ("312e81", "818cf8"),
            ("831843", "fb7185"), ("064e3b", "34d399"), ("3b0764", "c084fc"),
        ]

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.cj = http.cookiejar.CookieJar()
        self._build_opener()

    def _build_opener(self):
        handlers = [
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx),
        ]
        for port in [7890, 7897, 10808, 10809, 7891, 1080]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.15)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    handlers.append(
                        urllib.request.ProxyHandler({
                            "http": "http://127.0.0.1:%d" % port,
                            "https": "http://127.0.0.1:%d" % port,
                        })
                    )
                    s.close()
                    break
                s.close()
            except Exception:
                pass
        self.opener = urllib.request.build_opener(*handlers)

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        return True

    def getName(self):
        return "nJAVTV"

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".mpd"))

    def manualVideoCheck(self):
        return False

    # ------------------------------------------------------------------
    def _fix_text(self, s):
        """還原 HTML 實體並盡量修正常見亂碼/雙重編碼。"""
        if not s:
            return ""
        s = html_lib.unescape(str(s))
        s = re.sub(r"\s+", " ", s).strip()
        # 常見：UTF-8 被當成 latin-1/cp1252 解讀後的雙重編碼
        if re.search(r"[\u00c0-\u00ff]{2,}", s) and not re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", s):
            for enc in ("latin-1", "cp1252", "iso-8859-1"):
                try:
                    fixed = s.encode(enc).decode("utf-8")
                    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", fixed):
                        s = fixed
                        break
                except Exception:
                    pass
        # 再解一次實體（有些頁面雙重 escape）
        s = html_lib.unescape(s)
        return s.strip()

    def _clean_pic_url(self, raw_pic, fallback_id=""):
        p = str(raw_pic or "").strip()
        if p.startswith("//"):
            p = "https:" + p
        elif p.startswith("/"):
            p = urllib.parse.urljoin(self.baseHost, p)
        if not p and fallback_id:
            p = "https://fourhoi.com/%s/cover-t.jpg" % fallback_id.lower()
        if not p:
            return "https://dummyimage.com/640x360/1e293b/ffffff.png&text=NO_COVER"
        if "@Referer=" in p:
            p = p.split("@Referer=")[0]
        return p

    def _raw_fetch(self, target_url, host_ctx=""):
        cur_host = host_ctx or self.baseHost
        headers = {
            "User-Agent": self._ua,
            "Referer": cur_host + "/",
            "Origin": cur_host,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ja,ja-JP;q=0.9,zh-TW;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        try:
            req = urllib.request.Request(target_url, headers=headers)
            with self.opener.open(req, timeout=12) as resp:
                raw = resp.read()
                enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                elif enc == "deflate":
                    try:
                        raw = zlib.decompress(raw)
                    except Exception:
                        try:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                        except Exception:
                            pass
                text = raw.decode("utf-8", errors="ignore")
                return {"code": resp.getcode(), "text": text, "final_url": resp.geturl()}
        except urllib.error.HTTPError as e:
            return {"code": e.code, "text": ""}
        except Exception:
            return {"code": -1, "text": ""}

    def _fetch(self, target_url):
        real_url = target_url
        if real_url.startswith("//"):
            real_url = "https:" + real_url
        elif real_url.startswith("/"):
            real_url = self.baseHost + real_url
        res = self._raw_fetch(real_url, self.baseHost)
        text = res.get("text", "")
        if (
            res.get("code") in (403, 451, 503, -1)
            or "Just a moment" in text
            or len(text) < 1500
        ):
            res2 = self._raw_fetch(real_url, self.baseHost)
            if res2.get("code") == 200 and len(res2.get("text", "")) > 1500:
                return res2
        return res

    # ------------------------------------------------------------------
    def homeContent(self, filter):
        classes = [
            {"type_name": "最近更新", "type_id": "new"},
            {"type_name": "新作上市", "type_id": "release"},
            {"type_name": "女優一覽", "type_id": "actresses"},
            {"type_name": "女優排行", "type_id": "actresses_ranking"},
            {"type_name": "發行商", "type_id": "makers"},
            {"type_name": "VR", "type_id": "vr"},
            {"type_name": "素人", "type_id": "amateur"},
            {"type_name": "無碼影片", "type_id": "uncensored"},
            {"type_name": "亞洲AV", "type_id": "asia"},
        ]
        result = {"class": classes}
        if not filter:
            return result

        # 各分類獨立篩選
        f_sort = {"key": "sort", "name": "排序", "init": "default", "value": SORT_FILTER}
        f_type = {"key": "filters", "name": "作品", "init": "all", "value": TYPE_FILTER}
        f_amateur = {"key": "sub", "name": "子分類", "init": "", "value": AMATEUR_FILTERS}
        f_uncen = {"key": "sub", "name": "子分類", "init": "", "value": UNCENSORED_FILTERS}
        f_asia = {"key": "sub", "name": "子分類", "init": "", "value": ASIA_FILTERS}

        height_ranges = [
            "131-135", "136-140", "141-145", "146-150", "151-155",
            "156-160", "161-165", "166-170", "171-175", "176-180",
            "181-185", "186-190",
        ]
        f_height = {
            "key": "height", "name": "身高", "init": "all",
            "value": [{"n": "全部", "v": "all"}] + [{"n": "%scm" % r, "v": r} for r in height_ranges],
        }
        cups = list("ABCDEFGHIJKLMNOPQ")
        f_cup = {
            "key": "cup", "name": "罩杯", "init": "all",
            "value": [{"n": "全部", "v": "all"}] + [{"n": "%s罩杯" % c, "v": c} for c in cups],
        }
        f_age = {
            "key": "age", "name": "年齡", "init": "all",
            "value": [
                {"n": "全部", "v": "all"},
                {"n": "<20", "v": "<20"},
                {"n": "20-30", "v": "20-30"},
                {"n": "30-40", "v": "30-40"},
                {"n": "40-50", "v": "40-50"},
                {"n": "50-60", "v": "50-60"},
                {"n": ">60", "v": ">60"},
            ],
        }
        f_actress_sort = {
            "key": "sort", "name": "排序", "init": "default",
            "value": [
                {"n": "默認", "v": "default"},
                {"n": "影片最多", "v": "videos"},
            ],
        }

        filters_dict = {
            "new": [f_sort, f_type],
            "release": [f_sort, f_type],
            "vr": [f_sort, f_type],
            "amateur": [f_amateur, f_sort, f_type],
            "uncensored": [f_uncen, f_sort, f_type],
            "asia": [f_asia, f_sort, f_type],
            "actresses": [f_actress_sort, f_height, f_cup, f_age],
            # makers / actresses_ranking 無額外篩選
        }
        result["filters"] = filters_dict
        return result

    def homeVideoContent(self):
        res = self._fetch(self.primaryHost + self.routes["new"])
        return {"list": self._parse_cards(res.get("text", ""), "video")[:16]}

    def categoryContent(self, tid, pg, filter, extend):
        del filter
        slug = str(tid).strip()
        page = int(pg) if str(pg).isdigit() else 1
        extend = extend if isinstance(extend, dict) else {}

        if slug.startswith("folder@"):
            target_url = slug.replace("folder@", "")
            parse_mode = "video"
        else:
            # 子分類覆寫路徑
            sub = str(extend.get("sub") or "").strip()
            route_key = sub if sub and sub in self.routes else slug
            if route_key not in self.routes:
                route_key = "new"
            target_url = self.primaryHost + self.routes[route_key]

            if slug == "actresses":
                parse_mode = "actress"
            elif slug == "actresses_ranking":
                parse_mode = "actress_ranking"
            elif slug == "makers":
                parse_mode = "makers"
            else:
                parse_mode = "video"

        qs = []
        if page > 1:
            qs.append("page=%d" % page)

        if parse_mode == "actress":
            for k in ("height", "cup", "age"):
                v = extend.get(k)
                if v and v != "all":
                    qs.append("%s=%s" % (k, urllib.parse.quote(str(v))))
            sort_v = extend.get("sort")
            if sort_v and sort_v != "default":
                qs.append("sort=%s" % sort_v)
        elif parse_mode == "video":
            sort_v = extend.get("sort", "default")
            if sort_v and sort_v != "default":
                qs.append("sort=%s" % sort_v)
            filt = extend.get("filters", "all")
            if filt and filt != "all":
                qs.append("filters=%s" % filt)

        if qs:
            sep = "&" if "?" in target_url else "?"
            target_url = target_url + sep + "&".join(qs)

        res = self._fetch(target_url)
        vod_list = self._parse_cards(res.get("text", ""), parse_mode)
        return {
            "page": page,
            "pagecount": (page + 1) if len(vod_list) >= 12 else page,
            "limit": len(vod_list) if vod_list else 24,
            "total": 999,
            "list": vod_list,
        }

    def searchContent(self, key, quick, pg="1"):
        del quick
        page = int(pg) if str(pg).isdigit() else 1
        q = urllib.parse.quote(str(key).strip())
        # 多種搜尋 URL（站方曾用 query / path 兩種）
        candidates = [
            "%s/cn/search?keyword=%s" % (self.primaryHost, q),
            "%s/cn/search/%s" % (self.primaryHost, q),
            "%s/dm539/cn/search?keyword=%s" % (self.primaryHost, q),
            "%s/search?keyword=%s" % (self.primaryHost, q),
        ]
        vod_list = []
        for base in candidates:
            url = base
            if page > 1:
                sep = "&" if "?" in url else "?"
                url = url + sep + "page=%d" % page
            res = self._fetch(url)
            html = res.get("text", "") or ""
            if not html or res.get("code") in (403, 451, 503, -1):
                continue
            if len(html) < 400 and "Just a moment" in html:
                continue
            vod_list = self._parse_cards(html, "video")
            if vod_list:
                break
            # 搜尋頁結構若不同，放寬：直接掃所有影片連結
            vod_list = self._parse_search_fallback(html)
            if vod_list:
                break
        return {
            "page": page,
            "pagecount": (page + 1) if len(vod_list) >= 8 else page,
            "limit": len(vod_list) if vod_list else 24,
            "total": 999,
            "list": vod_list,
        }

    def _parse_search_fallback(self, html):
        """搜尋頁備援解析：不依賴卡片完整結構。"""
        if not html:
            return []
        body = html
        if "</nav>" in body:
            body = body.split("</nav>", 1)[1]
        vod_list, seen = [], set()
        href_re = (
            r"href=[\"\']((?:https?://[^\"\']+)?"
            r"/(?:dm\d+/)?(?:[a-z]{2}/)?"
            r"([A-Za-z0-9][A-Za-z0-9._-]{2,100}))[\"\']"
        )
        for m in re.finditer(href_re, body, re.I):
            full_href, dvd_id = m.group(1), m.group(2)
            if self._is_external_ad_href(full_href):
                continue
            dvd_low = dvd_id.lower()
            if dvd_low in seen or self._is_junk(dvd_low):
                continue
            if any(x in dvd_low for x in (
                "page", "sort", "filter", "actresses", "genres", "makers",
                "search", "login", "register", "ranking", "contact", "privacy",
            )):
                continue
            if not re.search(r"[a-z]{2,}\d|[a-z]{2,}-\d|\d{5,}|ppv|fc2", dvd_low):
                continue
            seen.add(dvd_low)
            start_w = max(0, m.start() - 400)
            end_w = min(len(body), m.end() + 500)
            window = body[start_w:end_w]
            title = ""
            alt_m = re.search(r'alt=["\']([^"\']+)["\']', window)
            if alt_m:
                title = html_lib.unescape(alt_m.group(1).strip())
            if not title:
                after = body[m.end(): m.end() + 300]
                tm = re.search(r">\s*([^<]{4,120})\s*<", after)
                if tm:
                    title = html_lib.unescape(tm.group(1).strip())
            if not title or self._is_junk(dvd_low, title):
                title = dvd_id.upper()
            pic_m = re.search(
                r'(?:data-src|data-original|src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
                window, re.I,
            )
            # 全局：HTML 無封面圖 → 視為廣告
            if not pic_m:
                continue
            pic = self._clean_pic_url(pic_m.group(1).strip(), dvd_id)
            if not self._has_valid_pic(pic):
                continue
            dur = self._extract_duration(window)
            href = full_href if full_href.startswith("http") else urllib.parse.urljoin(self.baseHost, full_href)
            vod_id = "%s@@%s" % (dvd_id, href)
            if dur:
                vod_id = "%s@@%s" % (vod_id, dur)
            if not self._has_valid_pic(pic):
                continue
            vod_list.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": dur,
                "style": {"type": "rect", "ratio": 1.78},
            })

        return vod_list


    # ------------------------------------------------------------------
    def _is_junk(self, slug, title=""):
        s = (slug or "").lower().strip()
        t = title or ""
        for kw in BANNED_TITLE_KW:
            if kw and kw in t:
                return True
        if not s:
            return False
        if s in BANNED_SLUGS:
            return True
        if len(s) < 3:
            return True
        if re.fullmatch(r"[\u3040-\u30ff\u4e00-\u9fff]{1,8}", s):
            return True
        return False

    def _is_external_ad_href(self, href):
        """外站導流連結視為廣告。"""
        if not href:
            return False
        h = str(href).strip()
        if h.startswith("/") or h.startswith("#") or h.startswith("?"):
            return False
        if not re.match(r"https?://", h, re.I):
            return False
        try:
            host = urllib.parse.urlparse(h).netloc.lower().split(":")[0]
        except Exception:
            return True
        allow_parts = (
            "njavtv.com", "njav.tv", "missav", "fourhoi.com", "surrit.com",
            "cloudfront.net", "googleusercontent.com",
        )
        if any(a in host for a in allow_parts):
            return False
        return True

    def _has_valid_pic(self, pic):
        """無有效封面 → 視為廣告/無效卡片。"""
        if not pic:
            return False
        p = str(pic).strip()
        if not p or p in ("null", "undefined", "none", "n/a"):
            return False
        if p.startswith("data:"):
            return False
        # 需像圖片 URL
        if re.search(r"\.(jpg|jpeg|png|webp|gif)(\?|$)", p, re.I):
            return True
        if re.search(r"/(cover|thumb|poster|preview|screenshot)", p, re.I):
            return True
        if p.startswith("http") and len(p) > 20:
            return True
        return False


    def _duration_to_seconds(self, s):
        """將 1:23:45 / 23:45 / 90(分) / 929(秒) 轉成秒數，失敗回 -1。"""
        if not s:
            return -1
        s = str(s).strip()
        if re.fullmatch(r"\d+", s):
            try:
                n = int(s)
                # 純數字：<=600 視為分鐘；>600 視為秒（播放器常見）
                if 0 < n <= 600:
                    return n * 60
                if 600 < n <= 8 * 3600:
                    return n
                return -1
            except ValueError:
                return -1
        parts = s.split(":")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return -1
        if len(nums) == 2:
            a, b = nums
            if a > 59 or b > 59:
                return -1
            return a * 60 + b
        if len(nums) == 3:
            h, mi, sec = nums
            if mi > 59 or sec > 59 or h > 24:
                return -1
            return h * 3600 + mi * 60 + sec
        return -1

    def _format_duration(self, total_sec):
        if total_sec <= 0:
            return ""
        h, rem = divmod(total_sec, 3600)
        mi, sec = divmod(rem, 60)
        if h:
            return "%d:%02d:%02d" % (h, mi, sec)
        return "%d:%02d" % (mi, sec)

    def _extract_duration(self, text, prefer_long=True):
        """從 HTML/文字片段抓時長，回傳如 1:23:45 或 23:45。
        優先取最長合理片長（排除預告/進度條短時長），並統一格式。"""
        if not text:
            return ""
        candidates = []
        for pat in (
            r'(?:data-duration|data-length|data-time|data-runtime)=["\'](\d{1,2}:\d{2}(?::\d{2})?)["\']',
            r'(?:class|id)=["\'][^"\']*(?:duration|runtime|length|time-label|video-time|badge-time)[^"\']*["\'][^>]*>\s*(\d{1,2}:\d{2}(?::\d{2})?)',
            r'(?:収録時間|収錄時間|時長|时长|片長|片长|Duration|Runtime)\s*[:：]?\s*(\d{1,2}:\d{2}(?::\d{2})?)',
            r'(?:収録時間|収錄時間|時長|时长|片長|片长|Duration|Runtime)\s*[:：]?\s*(\d+)\s*(?:分|分钟|分鐘|min)',
            r'<(?:span|div|p|time)[^>]*>\s*(\d{1,2}:\d{2}:\d{2})\s*</(?:span|div|p|time)>',
            r'<(?:span|div|p|time)[^>]*>\s*(\d{1,2}:\d{2})\s*</(?:span|div|p|time)>',
            r'>(\d{1,2}:\d{2}:\d{2})<',
            r'>(\d{1,2}:\d{2})<',
            r'(?<![0-9:])(\d{1,2}:\d{2}:\d{2})(?![0-9])',
            r'(?<![0-9:])(\d{1,2}:\d{2})(?![0-9:])',
            r"(?:duration|length|runtime)\s*[:=]\s*['\"]?(\d{1,2}:\d{2}(?::\d{2})?)",
            r"(?:duration|length)\s*[:=]\s*(\d{2,5})\b",
        ):
            for m in re.finditer(pat, text, re.I):
                candidates.append(m.group(1).strip())

        scored = []
        seen_sec = set()
        for c in candidates:
            if c in ("0:00", "00:00", "0:00:00", "00:00:00"):
                continue
            sec = self._duration_to_seconds(c)
            if sec < 90 or sec > 8 * 3600:
                continue
            if sec in seen_sec:
                continue
            seen_sec.add(sec)
            scored.append((sec, self._format_duration(sec)))

        if not scored:
            for c in candidates:
                sec = self._duration_to_seconds(c)
                if sec < 30 or sec > 8 * 3600:
                    continue
                if sec in seen_sec:
                    continue
                seen_sec.add(sec)
                scored.append((sec, self._format_duration(sec)))

        if not scored:
            return ""
        if prefer_long:
            # 先取典型區間（15分～3.5小時）內最長，避免推薦區 5h+ 雜訊
            typical = [(s, f) for s, f in scored if 900 <= s <= int(3.5 * 3600)]
            pool = typical if typical else scored
            pool.sort(key=lambda x: x[0], reverse=True)
            return pool[0][1]
        return scored[0][1]


    def _uncen_tag(self, code, window=""):
        """僅品番/路徑含 uncensored、leak 時標記；不掃全頁避免導航「無碼影片」誤觸。"""
        del window
        c = (code or "").lower()
        if "uncensored" in c or "uncensor" in c or "-leak" in c or "_leak" in c:
            return "無碼"
        return ""

    def _parse_cards(self, html, mode="video"):
        if not html:
            return []
        body = html
        if "</nav>" in body:
            body = body.split("</nav>", 1)[1]
        elif "</header>" in body:
            body = body.split("</header>", 1)[1]

        vod_list = []
        seen = set()

        if mode in ("actress", "actress_ranking"):
            is_rank = mode == "actress_ranking"
            # 寬鬆掃描所有女優連結（不依賴固定外層 div 結構）
            for m in re.finditer(
                r'href=["\']((?:https?://[^"\']+)?/(?:dm\d+/)?(?:[a-z]{2}/)?actresses/([^"\'?#/]+))["\']',
                body, re.I,
            ):
                full_href, slug = m.group(1), m.group(2)
                if not slug or slug.lower() in ("ranking", "rank"):
                    continue
                key = slug.lower()
                if key in seen:
                    continue
                seen.add(key)

                start = max(0, m.start() - 400)
                end = min(len(body), m.end() + 500)
                window = body[start:end]

                pic_m = re.search(
                    r'(?:data-src|data-original|src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
                    window, re.I,
                )
                pic = self._clean_pic_url(pic_m.group(1).strip() if pic_m else "")

                title = ""
                alt_m = re.search(r'alt=["\']([^"\']+)["\']', window)
                if alt_m:
                    title = html_lib.unescape(alt_m.group(1).strip())
                if not title:
                    # 連結後文字 / 卡片內純文字
                    after = body[m.end(): m.end() + 300]
                    for tc in re.findall(r">\s*([^<]{2,40})\s*<", after):
                        t = tc.strip()
                        if t and not t.isdigit() and not any(
                            k in t for k in (
                                "影片", "部", "出道", "第", "名", "Ranking", "条", "條",
                                "videos", "Debut", "排名", "Peringkat", "Rang",
                            )
                        ):
                            title = html_lib.unescape(t)
                            break
                if not title:
                    title = urllib.parse.unquote(slug).replace("-", " ")
                title = title.strip() or "女優"
                if self._is_junk("", title):
                    continue

                remarks = ""
                if is_rank:
                    rm = re.search(
                        r"(?:第\s*(\d+)\s*名|排名\s*[#：: ]*\s*(\d+)|Rank(?:ing)?\s*[#：: ]*\s*(\d+)|#\s*(\d+))",
                        window, re.I,
                    )
                    if rm:
                        num = next(g for g in rm.groups() if g)
                        remarks = "第%s名" % num
                else:
                    cm = re.search(
                        r"(\d+)\s*(?:条影片|條影片|部影片|部|本|videos?)",
                        window, re.I,
                    )
                    if cm:
                        remarks = "%s部" % cm.group(1)

                href = full_href if full_href.startswith("http") else urllib.parse.urljoin(self.baseHost, full_href)
                vod_list.append({
                    "vod_id": "folder@" + href,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                    "vod_tag": "folder",
                    "style": {"type": "oval", "ratio": 1.0},
                })
            return vod_list

        if mode == "makers":
            for idx, m in enumerate(re.finditer(
                r'href=["\']((?:https?://[^"\']+)?/(?:dm\d+/)?(?:[a-z]{2}/)?makers/([^"\'?#/]+))["\']',
                body, re.I,
            )):
                full_href, slug = m.group(1), m.group(2)
                if not slug or slug.lower() in ("makers",):
                    continue
                key = slug.lower()
                if key in seen:
                    continue
                seen.add(key)

                start = max(0, m.start() - 200)
                end = min(len(body), m.end() + 300)
                window = body[start:end]

                title = ""
                # a 標籤內文字
                tm = re.search(
                    r'href=["\'][^"\']*/makers/[^"\']+["\'][^>]*>([\s\S]*?)</a>',
                    window, re.I,
                )
                if tm:
                    title = html_lib.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
                if not title:
                    after = body[m.end(): m.end() + 200]
                    for tc in re.findall(r">\s*([^<]{2,60})\s*<", after):
                        t = tc.strip()
                        if t and not t.isdigit() and not any(
                            k in t for k in ("影片", "部", "条", "條", "videos")
                        ):
                            title = html_lib.unescape(t)
                            break
                if not title:
                    title = urllib.parse.unquote(slug).replace("-", " ")
                title = title.strip()
                if not title or self._is_junk("", title):
                    continue

                cm = re.search(
                    r"(\d+)\s*(?:条影片|條影片|部影片|部|本|videos?)",
                    window, re.I,
                )
                remarks = ("%s部" % cm.group(1)) if cm else ""
                bg, fg = self.color_palette[idx % len(self.color_palette)]
                pic = "https://dummyimage.com/640x360/%s/%s.png&text=%s" % (
                    bg, fg, urllib.parse.quote(title[0] if title else "?"),
                )
                href = full_href if full_href.startswith("http") else urllib.parse.urljoin(self.baseHost, full_href)
                vod_list.append({
                    "vod_id": "folder@" + href,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                    "vod_tag": "folder",
                    "style": {"type": "rect", "ratio": 1.78},
                })
            return vod_list

        # ---- 影片 ----
        # njavtv / missav 同源：時長在 <a href=".../cn/id"> 內的 <span class="text-xs">H:MM:SS</span>
        for m in re.finditer(
            r'<a[^>]+href=["\']((?:https?://[^"\']+)?/(?:dm\d+/)?(?:[a-z]{2}/)?([A-Za-z0-9][A-Za-z0-9._-]{2,100}))["\'][^>]*>([\s\S]{0,2500}?)</a>',
            body, re.I,
        ):
            full_href, dvd_id, inner = m.group(1), m.group(2), m.group(3)
            if self._is_external_ad_href(full_href):
                continue
            dvd_low = dvd_id.lower()
            if dvd_low in seen or self._is_junk(dvd_low):
                continue
            if any(x in dvd_low for x in (
                "page=", "sort=", "filter", "actresses", "genres", "makers",
                "search", "login", "register", "ranking",
            )):
                continue
            # 必須像影片頁連結（含常見番號形態或足夠長）
            if not re.search(r"[a-z]{2,}-\d|\d{5,}|ppv|fc2|siro|luxu", dvd_low):
                # 仍允許一般 id，但排除純語言碼
                if dvd_low in ("cn", "en", "ja", "zh", "new", "release", "vr"):
                    continue

            # 時長：優先 span.text-xs（missav/njavtv 卡片角標），其次任意 span 內時長
            dur = ""
            for pat in (
                r'<span[^>]*class=["\'][^"\']*text-xs[^"\']*["\'][^>]*>\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*<',
                r'<span[^>]*>\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*</span>',
                r'(?:data-duration|data-length)=["\'](\d{1,2}:\d{2}(?::\d{2})?)["\']',
            ):
                dm = re.search(pat, inner, re.I)
                if dm:
                    sec = self._duration_to_seconds(dm.group(1))
                    if 30 <= sec <= 8 * 3600:
                        dur = self._format_duration(sec)
                        break
            if not dur:
                for tm in re.finditer(
                    r"(?<![0-9:])(\d{1,2}:\d{2}(?::\d{2})?)(?![0-9:])",
                    inner,
                ):
                    sec = self._duration_to_seconds(tm.group(1))
                    if 30 <= sec <= 8 * 3600:
                        dur = self._format_duration(sec)
                        break
            if not dur:
                # 再備援：連結後鄰近節點
                after = body[m.end(): m.end() + 280]
                for tm in re.finditer(
                    r"(?<![0-9:])(\d{1,2}:\d{2}(?::\d{2})?)(?![0-9:])",
                    after,
                ):
                    sec = self._duration_to_seconds(tm.group(1))
                    if 30 <= sec <= 8 * 3600:
                        dur = self._format_duration(sec)
                        break

            # 同一品番：已收過則若本次有時長且舊的沒有，補上時長
            if dvd_low in seen:
                if dur:
                    for item in vod_list:
                        if item.get("vod_id", "").split("@@")[0].lower() == dvd_low:
                            if not item.get("vod_remarks"):
                                item["vod_remarks"] = dur
                                if "@@" in item["vod_id"] and item["vod_id"].count("@@") < 2:
                                    item["vod_id"] = "%s@@%s" % (item["vod_id"], dur)
                            break
                continue
            seen.add(dvd_low)

            # 標題
            title = ""
            alt_m = re.search(r'alt=["\']([^"\']+)["\']', inner)
            if alt_m:
                title = html_lib.unescape(alt_m.group(1).strip())
            if not title:
                for tc in re.findall(r">\s*([^<]{4,160})\s*<", inner + body[m.end(): m.end() + 200]):
                    t = html_lib.unescape(tc.strip())
                    if t and t.lower() != dvd_low and not re.match(r"^\d{1,2}:\d{2}", t):
                        title = t
                        break
            if not title:
                title = dvd_id.upper()
            if self._is_junk(dvd_low, title):
                continue

            pic_m = re.search(
                r'(?:data-src|data-original|src|data-preview|poster)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
                inner, re.I,
            )
            # 全局：HTML 無封面圖 → 視為廣告
            if not pic_m:
                continue
            pic = self._clean_pic_url(pic_m.group(1).strip(), dvd_id)
            if not self._has_valid_pic(pic):
                continue

            vod_id = "%s@@%s" % (dvd_id, full_href if full_href.startswith("http") else urllib.parse.urljoin(self.baseHost, full_href))
            if dur:
                vod_id = "%s@@%s" % (vod_id, dur)

            if not self._has_valid_pic(pic):
                continue
            vod_list.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": dur,
                "style": {"type": "rect", "ratio": 1.78},
            })


        return vod_list

    def _extract_surrit_uuid(self, html):
        if not html:
            return ""
        hls = re.search(
            r'hls\.loadSource\(["\']https?://[^/]+/([a-f0-9-]{36})/playlist\.m3u8["\']\)',
            html,
        )
        if hls:
            return hls.group(1)
        ub = re.search(r'urls:\s*\[\s*["\']([^"\']+)["\']', html)
        if ub and "sample" not in ub.group(1):
            um = re.search(r"([a-f0-9-]{36})", ub.group(1))
            if um:
                return um.group(1)
        for sc in re.findall(r"<script[^>]*>([\s\S]*?)</script>", html):
            if ("surrit.com" in sc or "sixyik.com" in sc) and "sample" not in sc:
                for u in re.findall(
                    r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", sc
                ):
                    pos = sc.find(u)
                    surround = sc[max(0, pos - 40): pos + 60]
                    if not any(b in surround for b in ("user_uuid", "sample", "preview", "thumbnail", "recombee")):
                        return u
        for c in re.findall(
            r"https?://(?:surrit\.com|sixyik\.com)/([a-f0-9-]{36})/(?:playlist\.m3u8)?", html
        ):
            pos = html.find(c)
            if "sample" not in html[max(0, pos - 30): pos + 60]:
                return c
        return ""

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else str(ids)
        list_duration = ""  # 列表封面帶過來的時長
        if "@@" in str(raw_id):
            parts = str(raw_id).split("@@")
            vid = parts[0]
            origin_href = parts[1] if len(parts) > 1 else ""
            # 第三段為列表時長（如 1:23:45 / 58:25）
            if len(parts) > 2 and re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", parts[2].strip()):
                list_duration = parts[2].strip()
        else:
            vid = str(raw_id).replace("vod@", "").strip("/")
            origin_href = "%s/cn/%s" % (self.baseHost, vid)

        cand = [
            origin_href if origin_href.startswith("http") else urllib.parse.urljoin(self.baseHost, origin_href),
            "%s/cn/%s" % (self.primaryHost, vid),
            "%s/dm539/cn/%s" % (self.primaryHost, vid),
        ]
        html, used = "", ""
        for u in cand:
            res = self._fetch(u)
            if res.get("code") == 200 and len(res.get("text", "")) > 2000:
                html, used = res.get("text", ""), u
                break

        def field(*labels):
            for lab in labels:
                m = re.search(
                    r"(?:%s)\s*[:：]\s*(?:</[^>]+>)?\s*([^<\n]+)" % re.escape(lab),
                    html, re.I,
                )
                if m:
                    return html_lib.unescape(m.group(1).strip())
                m = re.search(
                    r"<span[^>]*>\s*%s\s*[:：]?\s*</span>\s*([\s\S]*?)</div>" % re.escape(lab),
                    html, re.I,
                )
                if m:
                    val = re.sub(r"<[^>]+>", " ", m.group(1))
                    return re.sub(r"\s+", " ", html_lib.unescape(val)).strip()
            return ""

        code = self._fix_text(field("品番", "コード", "Code", "番号") or vid.upper())
        # 標題優先順序：og:title → h1 → タイトル欄位 → <title>
        title = ""
        for pat in (
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
            r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
        ):
            om = re.search(pat, html, re.I)
            if om:
                title = om.group(1).strip()
                break
        if not title:
            hm = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.I)
            if hm:
                title = re.sub(r"<[^>]+>", "", hm.group(1)).strip()
        if not title:
            title = field("タイトル", "Title", "标题", "標題")
        if not title:
            tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.I)
            if tm:
                title = tm.group(1).split("|")[0].split("-")[0].strip()
        title = self._fix_text(title) or code
        # 去掉站名後綴
        for sep in (" | nJAV", " | njav", " - nJAV", " – nJAV"):
            if sep in title:
                title = title.split(sep)[0].strip()

        actor = field("女優", "Actress", "女优")
        if not actor:
            acts = []
            for a in re.findall(
                r'<a[^>]+href=["\'][^"\']*/actresses/[^"\']+["\'][^>]*>([\s\S]*?)</a>', html
            ):
                name = re.sub(r"<[^>]+>", "", a).strip()
                if name and not any(k in name for k in ("排行", "Ranking", "一覧", "一览", "202")):
                    if name not in acts:
                        acts.append(name)
            actor = ", ".join(acts)

        director = field("監督", "Director", "导演")
        maker = field("メーカー", "Maker", "发行商", "片商")
        label = field("レーベル", "Label", "廠牌")
        genre = field("ジャンル", "Genre", "类型", "類型")
        release = field("配信開始日", "Release date", "发行日期", "發布日期")
        series = field("シリーズ", "Series", "系列")
        duration = field("収録時間", "収錄時間", "Duration", "時長", "时长", "片長", "片长")
        # 詳情頁：優先標籤欄位；全文掃描僅在主內容區，且不盲目取全站最長（避免吃到推薦影片）
        main_html = html
        for cut in (
            "相關推薦", "相关推荐", "相關影片", "相关影片", "Recommended", "More like",
            "あなたへのおすすめ", "関連作品", "Similar",
        ):
            pos = main_html.find(cut)
            if pos > 2000:
                main_html = main_html[:pos]
                break
        for cut in ('id="related"', "id='related'", 'class="related', "class='related"):
            pos = main_html.lower().find(cut.lower())
            if pos > 2000:
                main_html = main_html[:pos]
                break
        # 再截掉頁尾
        for cut in ("</main>", "<footer", 'id="footer"', "id='footer'"):
            pos = main_html.lower().find(cut.lower())
            if pos > 2000:
                main_html = main_html[:pos]
                break

        extracted = self._extract_duration(main_html)
        # 也從播放器區塊附近再抓一次（時長常在 video 控件旁）
        player_chunk = ""
        for pm in re.finditer(
            r"(?:id|class)=[\"'][^\"']*(?:player|video-player|vjs|jwplayer|plyr)[^\"']*[\"']",
            html, re.I,
        ):
            player_chunk = html[max(0, pm.start() - 200): min(len(html), pm.end() + 1500)]
            break
        if player_chunk:
            p_dur = self._extract_duration(player_chunk)
            if p_dur:
                extracted = p_dur  # 播放器附近優先

        def _reasonable(sec):
            # 典型 AV：約 15 分～3.5 小時；過短當預告、過長當推薦/錯誤 meta
            return 900 <= sec <= int(3.5 * 3600)

        sec_f = self._duration_to_seconds(duration) if duration else -1
        sec_e = self._duration_to_seconds(extracted) if extracted else -1

        # 優先合理區間內的值；欄位與掃描都合理時以欄位為準
        if _reasonable(sec_f) and _reasonable(sec_e):
            duration = self._format_duration(sec_f)
        elif _reasonable(sec_f):
            duration = self._format_duration(sec_f)
        elif _reasonable(sec_e):
            duration = extracted
        elif sec_e > 0 and (sec_f <= 0 or abs(sec_e - 5400) < abs(sec_f - 5400)):
            # 都不在典型區間：選較接近 90 分鐘者
            duration = extracted
        elif sec_f > 0:
            duration = self._format_duration(sec_f)
        else:
            duration = ""

        # 列表封面時長優先（與封面一致）
        if list_duration:
            sec_list = self._duration_to_seconds(list_duration)
            if sec_list >= 30:
                duration = self._format_duration(sec_list)
        else:
            # 無列表時長時：丟棄過短的錯誤值（如常見的 8:00 雜訊）
            sec_d = self._duration_to_seconds(duration) if duration else -1
            if 0 < sec_d < 900:
                duration = ""

        if not genre:

            gs = re.findall(
                r'href=["\'][^"\']*/genres/[^"\']+["\'][^>]*>([^<]+)</a>', html, re.I
            )
            if gs:
                genre = ", ".join(dict.fromkeys(g.strip() for g in gs if g.strip()))

        # 影片簡介：優先完整正文，meta description 作備援
        desc = ""
        # 1) 常見簡介區塊（中/日/英）
        for pat in (
            r'(?:劇情簡介|剧情简介|影片簡介|影片简介|簡介|简介|あらすじ|Synopsis|Description)\s*[:：]?\s*</[^>]+>\s*<[^>]+>([\s\S]*?)</(?:div|p|section)>',
            r'<div[^>]*(?:class|id)=["\'][^"\']*(?:description|synopsis|plot|intro|summary)[^"\']*["\'][^>]*>([\s\S]*?)</div>',
            r'<p[^>]*(?:class|id)=["\'][^"\']*(?:description|synopsis|plot|intro|summary)[^"\']*["\'][^>]*>([\s\S]*?)</p>',
        ):
            dm = re.search(pat, html, re.I)
            if dm:
                raw = re.sub(r'<[^>]+>', ' ', dm.group(1))
                raw = html_lib.unescape(re.sub(r'\s+', ' ', raw)).strip()
                if len(raw) > 20:
                    desc = raw
                    break
        # 2) meta description（站方常截斷加 ...）
        if not desc or desc.endswith('...') or desc.endswith('…'):
            desc_m = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
                html, re.I,
            )
            if not desc_m:
                desc_m = re.search(
                    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
                    html, re.I,
                )
            if desc_m:
                meta_d = html_lib.unescape(desc_m.group(1).strip())
                # 若正文更長且非空則保留正文；否則用 meta
                if not desc or len(meta_d) > len(desc):
                    desc = meta_d
        # 去掉尾部被截斷的省略號後多餘空白
        if desc:
            desc = desc.strip()

        # 語言
        lang = "日語"
        if "chinese" in (vid or "").lower() or "中文字幕" in html or "chinese-subtitle" in html:
            lang = "中文字幕"
        elif "english" in (vid or "").lower() or "english-subtitle" in html:
            lang = "英語字幕"

        uncen = self._uncen_tag(vid, html)
        area = "日本"
        if any(x in (vid or "").lower() for x in ("madou", "twav", "furuke")):
            area = "亞洲"

        # 播放詳情簡介：僅影片簡介（不拼 meta 欄位）
        vod_content = desc.strip() if desc else ""

        # 詳情頁不顯示時長與無碼（列表封面已有時長；無碼易誤標）
        remarks = ""

        uuid = self._extract_surrit_uuid(html)
        play_from, play_url = "nJAVTV", "正片$" + (used or cand[0])
        if uuid:
            play_url = "正片$https://surrit.com/%s/playlist.m3u8" % uuid

        pic = self._clean_pic_url("", vid)
        pm = re.search(
            r'(?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, re.I
        )
        if not pm:
            pm = re.search(
                r'content=["\']([^"\']+)["\'][^>]+(?:og:image|twitter:image)', html, re.I
            )
        if pm:
            pic = self._clean_pic_url(pm.group(1), vid)
        else:
            pic = "https://fourhoi.com/%s/cover-n.jpg" % vid.lower()

        title = self._fix_text(title)
        code = self._fix_text(code)
        vod_name = title if title else code
        if code and code.upper() not in vod_name.upper():
            vod_name = "%s %s" % (code, vod_name)
        vod_name = self._fix_text(vod_name)

        return {
            "list": [{
                "vod_id": raw_id,
                "vod_name": vod_name,
                "vod_pic": pic,
                "vod_actor": actor,
                "vod_director": director or maker,
                "vod_area": area,
                "vod_lang": lang,
                "type_name": genre,
                "vod_year": release[:4] if release and len(release) >= 4 else "",
                "vod_remarks": remarks,
                "vod_content": vod_content,
                "vod_play_from": play_from,
                "vod_play_url": play_url,
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        del flag, vipFlags
        url = str(id).strip()
        if url.startswith("http") and not self.isVideoFormat(url):
            res = self._fetch(url)
            uuid = self._extract_surrit_uuid(res.get("text", ""))
            if uuid:
                url = "https://surrit.com/%s/playlist.m3u8" % uuid
        return {
            "parse": 0 if self.isVideoFormat(url) else 1,
            "jx": 0,
            "url": url,
            "header": {
                "User-Agent": self._ua,
                "Referer": self.baseHost + "/",
                "Origin": self.baseHost,
                "Accept": "*/*",
                "Connection": "keep-alive",
            },
        }

    def action(self, action):
        return {"msg": "ok"}

    def liveContent(self):
        return ""

    def localProxy(self, param):
        return [404, "text/plain", b"not support"]

    def destroy(self):
        self.options = {}
