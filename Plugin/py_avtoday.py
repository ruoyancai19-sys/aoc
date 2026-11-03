# -*- coding: utf-8 -*-
"""AVToday (avtoday.io) 點播爬蟲。

依範本契約實作：home / category / search / detail / player。
播放源來自 /player?s={code} 頁面的 video_link（簽名 MP4，有時效，播放時現取）。

配置範例：
{
  "key": "AVToday",
  "name": "AVToday",
  "type": 3,
  "api": "./vod/avtoday.py",
  "searchable": 1,
  "quickSearch": 1,
  "filterable": 0,
  "changeable": 0,
  "style": {"type": "rect", "ratio": 1.78},
  "ext": ""
}
"""

import json
import re
from urllib.parse import quote

from base.spider import Spider as BaseSpider


HOST = "https://avtoday.io"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
PAGE_SIZE = 24

# type_id -> (顯示名, 路徑；路徑可含 {pg})
CLASSES = (
    ("latest", "最新", "/cht/index.html"),
    ("no-mosaic", "無碼專區", "/cht/no-mosaic.html"),
    ("中文字幕", "中文字幕", "/cht/catalog/中文字幕.html"),
    ("無碼", "無碼", "/cht/catalog/無碼.html"),
    ("FC2", "FC2", "/cht/catalog/FC2.html"),
    ("素人", "素人", "/cht/catalog/素人.html"),
    ("巨乳", "巨乳", "/cht/catalog/巨乳.html"),
    ("人妻", "人妻", "/cht/catalog/人妻.html"),
    ("熟女", "熟女", "/cht/catalog/熟女.html"),
    ("制服", "制服", "/cht/catalog/制服.html"),
    ("絲襪", "絲襪", "/cht/catalog/絲襪.html"),
    ("長腿", "長腿", "/cht/catalog/長腿.html"),
    ("痴女", "痴女", "/cht/catalog/痴女.html"),
    ("多人", "多人", "/cht/catalog/多人.html"),
    ("潮吹", "潮吹", "/cht/catalog/潮吹.html"),
    ("自慰", "自慰", "/cht/catalog/自慰.html"),
    ("足交", "足交", "/cht/catalog/足交.html"),
    ("蘿莉型", "蘿莉型", "/cht/catalog/蘿莉型.html"),
    ("貧乳", "貧乳", "/cht/catalog/貧乳.html"),
    ("素股", "素股", "/cht/catalog/素股.html"),
    ("泡泡浴", "泡泡浴", "/cht/catalog/泡泡浴.html"),
    ("及膝襪", "及膝襪", "/cht/catalog/及膝襪.html"),
)


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = HOST
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": self.host + "/cht/index.html",
        }
        self._class_map = {tid: (name, path) for tid, name, path in CLASSES}
        if extend:
            try:
                options = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(options, dict) and options.get("host"):
                    self.host = str(options["host"]).rstrip("/")
                    self.headers["Referer"] = self.host + "/cht/index.html"
            except Exception:
                pass

    def getName(self):
        return "AVToday"

    def homeContent(self, filter):
        return {
            "class": [
                {"type_id": tid, "type_name": name}
                for tid, name, _ in CLASSES
            ]
        }

    def homeVideoContent(self):
        return self.categoryContent("latest", "1", False, {})

    def categoryContent(self, tid, pg, filter, extend):
        del filter, extend
        tid = str(tid or "").strip()
        page = self._page_num(pg)

        if tid in self._class_map:
            path = self._class_map[tid][1]
        elif tid.startswith("catalog/"):
            path = "/cht/catalog/%s.html" % tid.split("/", 1)[1]
        else:
            path = "/cht/catalog/%s.html" % tid

        if page <= 1:
            url = self.host + path
        else:
            sep = "&" if "?" in path else "?"
            url = self.host + path + sep + "page=%s" % page

        html = self._get(url)
        items = self._parse_list(html)
        pagecount = self._parse_pagecount(html, page, bool(items))
        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": PAGE_SIZE,
            "total": pagecount * PAGE_SIZE,
        }

    def searchContent(self, key, quick, pg="1"):
        del quick
        query = str(key or "").strip()
        page = self._page_num(pg)
        if not query:
            return self._empty_page(page)

        # 長標題時先抽出前面番號，搜尋與 fallback 都用純番號
        code_hint = self._extract_code(query)
        search_q = code_hint or query

        url = "%s/cht/search?s=%s" % (self.host, quote(search_q))
        if page > 1:
            url += "&page=%s" % page

        html = self._get(url)
        if html and self._is_challenge(html):
            html = ""

        items = self._parse_list(html) if html else []

        if not items and page == 1:
            code = self._normalize_code(code_hint or query)
            if self._looks_like_code(code):
                item = self._item_from_detail(code)
                if item:
                    items = [item]

        pagecount = self._parse_pagecount(html, page, bool(items)) if html else 1
        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": PAGE_SIZE,
            "total": pagecount * PAGE_SIZE,
        }

    def detailContent(self, ids):
        code = str(ids[0] if ids else "").strip()
        if not code:
            return {"list": []}

        code = code.replace("/cht/video/", "").replace(".html", "").strip("/")
        # 只取番號
        extracted = self._extract_code(code)
        if extracted:
            code = extracted
        code = self._normalize_code(code) or code

        html, code = self._fetch_detail_html(code)
        if not html:
            return {"list": [], "msg": "無法取得影片頁面"}

        name = self._meta_title(html) or code
        if "404" in name or "找不到" in name:
            return {"list": [], "msg": "找不到此影片"}

        pic = self._meta_pic(html, code)
        remarks = self._meta_duration(html)

        item = {
            "vod_id": code,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remarks,
            "vod_content": name,
            "vod_play_from": "AVToday",
            "vod_play_url": "正片$%s" % code,
        }
        return {"list": [item]}

    def playerContent(self, flag, id, vipFlags):
        del flag, vipFlags
        code = str(id or "").strip()
        if not code:
            return {"parse": 0, "msg": "無效的播放 ID"}

        if code.startswith("http") and (
            ".mp4" in code or ".m3u8" in code or "workers.dev" in code
        ):
            return self._play_result(code)

        code = code.replace("/cht/video/", "").replace(".html", "").strip("/")
        extracted = self._extract_code(code)
        if extracted:
            code = extracted
        code = self._normalize_code(code) or code

        media = self._fetch_media(code)
        if not media and not code.endswith("-C") and re.match(r"^[A-Z0-9]+-\d+$", code):
            media = self._fetch_media(code + "-C")
            if media:
                code = code + "-C"

        if media:
            return self._play_result(media)

        return {
            "parse": 1,
            "jx": 0,
            "url": "%s/player?s=%s" % (self.host, code),
            "header": {
                "User-Agent": USER_AGENT,
                "Referer": "%s/cht/video/%s.html" % (self.host, code),
            },
        }

    def manualVideoCheck(self):
        return True

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        if not u.startswith("http"):
            return False
        if "preview.xdmm" in u:
            return False
        if any(x in u for x in (".mp4", ".m3u8", "workers.dev", "video.")):
            if any(x in u for x in ("/ad/", "doubleclick", "googlesyndication")):
                return False
            return True
        return False

    def destroy(self):
        pass

    # -------------------------------------------------------------------------
    # helpers
    # -------------------------------------------------------------------------

    def _play_result(self, url):
        return {
            "parse": 0,
            "jx": 0,
            "url": url,
            "header": {
                "User-Agent": USER_AGENT,
                "Referer": self.host + "/",
                "Accept": "*/*",
            },
            "format": "video/mp4" if ".mp4" in url else (
                "application/x-mpegURL" if ".m3u8" in url else ""
            ),
        }

    def _fetch_media(self, code):
        """從 /player?s=CODE 解析 video_link / m3u8_url（簽名有時效）。"""
        url = "%s/player?s=%s" % (self.host, code)
        headers = dict(self.headers)
        headers["Referer"] = "%s/cht/video/%s.html" % (self.host, code)
        html = self._get(url, headers=headers)
        if not html or self._is_challenge(html):
            return ""

        m = re.search(r"""var\s+video_link\s*=\s*['"]([^'"]+)['"]""", html)
        if m and m.group(1).startswith("http") and "preview." not in m.group(1):
            return m.group(1).strip()

        m = re.search(r"""var\s+m3u8_url\s*=\s*['"]([^'"]+)['"]""", html)
        if m and m.group(1).startswith("http"):
            return m.group(1).strip()

        for m in re.finditer(
            r"""https?://(?!preview\.)[^"'<>\s]+workers\.dev[^"'<>\s]+\.mp4[^"'<>\s]*""",
            html,
            re.I,
        ):
            return m.group(0).strip()

        for m in re.finditer(
            r"""https?://[^"'<>\s]+\.m3u8[^"'<>\s]*""",
            html,
            re.I,
        ):
            return m.group(0).strip()

        return ""

    def _get(self, url, headers=None):
        hdrs = headers or self.headers
        try:
            if hasattr(self, "fetch"):
                rsp = self.fetch(url, headers=hdrs)
                if rsp is None:
                    return ""
                if isinstance(rsp, str):
                    return rsp
                text = getattr(rsp, "text", None) or getattr(rsp, "content", None)
                if isinstance(text, bytes):
                    return text.decode("utf-8", errors="ignore")
                return str(text or "")
        except Exception:
            pass
        try:
            from com.github.catvod.net import OkHttp
            from java.util import HashMap
            from java.util.concurrent import TimeUnit

            headers_map = HashMap()
            for k, v in hdrs.items():
                headers_map.put(k, v)
            call = OkHttp.newCall(url, headers_map)
            call.timeout().timeout(15, TimeUnit.SECONDS)
            response = call.execute()
            try:
                body = response.body()
                return str(body.string()) if body is not None else ""
            finally:
                response.close()
        except Exception:
            return ""

    @staticmethod
    def _is_challenge(html):
        if not html:
            return False
        return (
            "Just a moment" in html
            or "cf-browser-verification" in html
            or "challenge-platform" in html
            or "Performing security verification" in html
        )

    @staticmethod
    def _extract_code(text):
        """從長字串（標題）中抽出開頭番號。
        例：FC2PPV-4992466 一位面板白皙... → FC2PPV-4992466
            SSIS-001 巨乳美女... → SSIS-001
            300MIUM-123 素人... → 300MIUM-123
        """
        s = str(text or "").strip()
        if not s:
            return ""
        # FC2 系列（優先）
        m = re.match(
            r"(FC2-?PPV-?\d{5,10}|FC2PPV-?\d{5,10})",
            s,
            re.I,
        )
        if m:
            return m.group(1)
        # 一般番號：ABC-123 / ABCD-123 / 300MIUM-001 / SSIS-001-C 等
        m = re.match(
            r"([A-Za-z0-9]{2,12}-\d{2,6}(?:-C)?)",
            s,
            re.I,
        )
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def _normalize_code(query):
        """整理為站點常用番號格式。"""
        s = str(query or "").strip().upper()
        s = s.replace("－", "-").replace("—", "-").replace("_", "-")
        s = re.sub(r"\s+", "", s)
        # 若還夾雜中文等，再抽一次
        m = re.match(
            r"(FC2-?PPV-?\d+|FC2PPV-?\d+|[A-Z0-9]+-\d+(?:-C)?)",
            s,
        )
        if m:
            s = m.group(1)
        # FC2 統一成 FC2PPV-1234567
        if s.startswith("FC2"):
            s = re.sub(r"^FC2-?PPV-?", "FC2PPV-", s)
            s = re.sub(r"^FC2PPV(?=\d)", "FC2PPV-", s)
        return s

    @staticmethod
    def _looks_like_code(code):
        if not code:
            return False
        if code.startswith("FC2"):
            return True
        if re.match(r"^[A-Z0-9]+-\d+", code):
            return True
        return False

    def _fetch_detail_html(self, code):
        """取詳情 HTML，必要時嘗試常見變體。回傳 (html, final_code)。"""
        if not code:
            return "", code

        candidates = [code]
        if not code.endswith("-C") and re.match(r"^[A-Z0-9]+-\d+$", code):
            candidates.append(code + "-C")
        if code.startswith("FC2PPV-"):
            candidates.append(code.replace("FC2PPV-", "FC2-PPV-", 1))
        elif code.startswith("FC2-PPV-"):
            candidates.append(code.replace("FC2-PPV-", "FC2PPV-", 1))

        for c in candidates:
            page_url = "%s/cht/video/%s.html" % (self.host, c)
            html = self._get(page_url)
            if not html or self._is_challenge(html):
                continue
            head = html[:1500]
            if "404" in head or "找不到" in head:
                continue
            title = self._meta_title(html)
            if title and "404" not in title and "找不到" not in title:
                return html, c
        return "", code

    def _item_from_detail(self, code):
        """用詳情頁補齊搜尋 fallback 的名稱與封面。確認存在才回傳。"""
        html, final_code = self._fetch_detail_html(code)
        if not html:
            return None
        name = self._meta_title(html) or final_code
        if "404" in name or "找不到" in name:
            return None
        pic = self._meta_pic(html, final_code)
        remarks = self._meta_duration(html)
        return {
            "vod_id": final_code,
            "vod_name": name,
            "vod_pic": pic or "",
            "vod_remarks": remarks or "",
        }

    @staticmethod
    def _page_num(pg):
        try:
            return max(1, int(pg))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _empty_page(page):
        return {
            "list": [],
            "page": page,
            "pagecount": 1,
            "limit": PAGE_SIZE,
            "total": 0,
        }

    def _parse_list(self, html):
        if not html:
            return []
        items = []
        seen = set()

        for m in re.finditer(
            r'<div class="video-card real-card" data-spcode="([^"]+)">',
            html,
            re.I,
        ):
            code = m.group(1).strip()
            if code in seen:
                continue
            seen.add(code)
            block = html[m.start(): m.start() + 1800]

            title = ""
            tm = re.search(
                r'class="video-title[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>',
                block,
                re.I,
            )
            if not tm:
                tm = re.search(
                    r'<a href="/cht/video/%s\.html"[^>]*>([^<]+)</a>' % re.escape(code),
                    block,
                    re.I,
                )
            if not tm:
                block2 = html[m.start(): m.start() + 2800]
                tm = re.search(
                    r'class="video-title[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>',
                    block2,
                    re.I,
                )
            if tm:
                title = self._html_text(tm.group(1))
            if not title:
                continue
            if title.startswith("[AD]") or title.startswith("【AD】") or title.startswith("[廣告]"):
                continue

            pic = self._pic_from_block(block, code)
            if not pic:
                pic = self._pic_from_block(html[m.start(): m.start() + 2800], code)

            duration = ""
            dm = re.search(
                r'class="video-duration"[^>]*>\s*([^<$]+?)\s*<',
                block,
            )
            if dm:
                duration = dm.group(1).strip()
                if "${" in duration:
                    duration = ""

            items.append({
                "vod_id": code,
                "vod_name": title or code,
                "vod_pic": pic,
                "vod_remarks": duration,
            })

        if items:
            return items

        for m in re.finditer(
            r'data-spcode="([^"]+)"[\s\S]{0,1500}?class="video-title[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>',
            html,
            re.I,
        ):
            code, title = m.group(1).strip(), self._html_text(m.group(2))
            if code in seen or not title:
                continue
            if title.startswith("[AD]") or title.startswith("【AD】"):
                continue
            seen.add(code)
            pos = m.start()
            ctx = html[max(0, pos - 200): pos + 1000]
            pic = self._pic_from_block(ctx, code)
            items.append({
                "vod_id": code,
                "vod_name": title or code,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return items

    def _pic_from_block(self, block, code=""):
        if not block:
            return ""
        pm = re.search(
            r"""url\s*\(\s*['"]?(/pic/[^'")\s]+)['"]?\s*\)""",
            block,
            re.I,
        )
        if pm:
            return self.host + pm.group(1)
        if code:
            pm = re.search(
                r"""(/pic/\d{4}/\d{2}/%s[^'")\s]*)""" % re.escape(code),
                block,
                re.I,
            )
            if pm:
                return self.host + pm.group(1)
            pm = re.search(
                r"""(/pic/[^'")\s]*%s[^'")\s]*\.(?:jpg|jpeg|png|webp)[^'")\s]*)""" % re.escape(code),
                block,
                re.I,
            )
            if pm:
                return self.host + pm.group(1)
        pm = re.search(
            r"""(/pic/[^'")\s]+\.(?:jpg|jpeg|png|webp)[^'")\s]*)""",
            block,
            re.I,
        )
        if pm:
            return self.host + pm.group(1)
        pm = re.search(
            r"""(?:src|data-original|data-src)=["'](https?://[^"']+\.(?:jpg|jpeg|png|webp)[^"']*)["']""",
            block,
            re.I,
        )
        if pm and "preview." not in pm.group(1):
            return pm.group(1)
        return ""

    @staticmethod
    def _html_text(s):
        t = str(s or "")
        t = (
            t.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&nbsp;", " ")
        )
        return t.strip()

    @staticmethod
    def _parse_pagecount(html, current, has_items):
        if not html:
            return 1 if not has_items else current
        nums = re.findall(r'[?&]page=(\d+)', html)
        if nums:
            try:
                return max(int(n) for n in nums)
            except ValueError:
                pass
        if has_items and re.search(r'page-link(?! active)[^>]*>\s*\d+', html):
            return max(current + 1, current)
        if has_items:
            return max(current, 1)
        return max(1, current)

    @staticmethod
    def _meta_title(html):
        m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.I)
        if m:
            t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if t:
                return t
        m = re.search(r"<title>([^|<]+)", html)
        if m:
            return (
                m.group(1)
                .replace("AVToday", "")
                .replace("今日AV", "")
                .replace("免費高清成人影片線上看", "")
                .strip(" -_|")
            )
        return ""

    def _meta_pic(self, html, code=""):
        m = re.search(
            r"""(?:property|name)=["']og:image["'][^>]+content=["'](https?://[^"']+)["']"""
            r"""|content=["'](https?://[^"']+)["'][^>]+(?:property|name)=["']og:image["']""",
            html,
            re.I,
        )
        if m:
            pic = (m.group(1) or m.group(2) or "").strip()
            if pic and "favicon" not in pic:
                return pic
        m = re.search(
            r"""(/pic/\d{4}/\d{2}/%s[^"']*\.(?:jpg|jpeg|png|webp))""" % re.escape(code or "X"),
            html,
            re.I,
        ) if code else None
        if m:
            return self.host + m.group(1)
        return self._pic_from_block(html[:12000], code)

    @staticmethod
    def _meta_duration(html):
        for m in re.finditer(
            r'class="video-duration"[^>]*>\s*([^<$]+?)\s*<',
            html or "",
        ):
            val = m.group(1).strip()
            if val and "${" not in val and "info[" not in val:
                return val
        return ""
