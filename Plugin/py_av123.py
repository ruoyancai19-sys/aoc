# -*- coding: utf-8 -*-
"""123AV (123av.com/ja) — 頂部分類：最新/最熱/有碼/無碼/無碼洩漏/片商；
片商從 /ja/makers 動態獲取；片商頁篩選對齊站內（類型/年份/演員/排序）。"""

import html as html_mod
import json
import re
from urllib.parse import urlencode, urlparse, parse_qs

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def getName(self):
            return ""

        def init(self, extend=""):
            pass


HOST = "https://123av.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# -------------------------------------------------------------------
# 推薦 → /ja/new（新發布）
# 有碼 / 無碼 / 無碼洩漏 / 片商
# ---------------------------------------------------------------------------
CATE_MAP = [
    ("recommend", "最新", "/ja/new"),
    ("hot", "最熱", "/ja/hot"),
    ("censored", "有碼", "/ja/censored"),
    ("uncensored", "無碼", "/ja/uncensored"),
    ("leaked", "無碼洩漏", "/ja/uncensored-leaked"),
    ("makers", "片商", "/ja/makers"),
]

# 影片列表排序（對齊站內）
SORT_FILTER = [
    {"n": "默認", "v": ""},
    {"n": "發布日期", "v": "release"},
    {"n": "最近新增", "v": "recent"},
    {"n": "熱門", "v": "hot"},
    {"n": "今日觀看", "v": "today"},
    {"n": "本週觀看", "v": "week"},
    {"n": "本月觀看", "v": "month"},
    {"n": "最受歡迎", "v": "popular"},
    {"n": "最多關注", "v": "most_followed"},
    {"n": "最長", "v": "longest"},
]

# 片商列表頁排序（/ja/makers）
MAKER_LIST_SORT = [
    {"n": "影片數量", "v": ""},
    {"n": "姓名 (A–Z)", "v": "name"},
    {"n": "最受歡迎", "v": "popular"},
    {"n": "今日觀看", "v": "today"},
    {"n": "每週觀看", "v": "week"},
    {"n": "每月觀看", "v": "month"},
]

# 年份（對齊站內 2000–2026）
YEAR_FILTER = [
    {"n": "全部", "v": ""},
] + [{"n": str(y), "v": str(y)} for y in range(2026, 1999, -1)]

# 類型（有碼/無碼/無碼洩漏，對齊站內 type 參數）
TYPE_FILTER = [
    {"n": "全部", "v": ""},
    {"n": "有碼", "v": "censored"},
    {"n": "無碼", "v": "uncensored"},
    {"n": "無碼洩漏", "v": "uncensored-leaked"},
]

# 常用類別
GENRE_FILTER = [
    {"n": "全部", "v": ""},
    {"n": "中出", "v": "creampie"},
    {"n": "大胸部", "v": "big-tits"},
    {"n": "人妻", "v": "married-womanhousewife"},
    {"n": "業餘", "v": "amateur"},
    {"n": "美麗的女孩", "v": "beautiful-girl"},
    {"n": "美麗的乳房", "v": "beautiful-breasts"},
    {"n": "苗條", "v": "slender"},
    {"n": "口交", "v": "e22f5b4c15"},
    {"n": "NTR", "v": "cuckold-cuckolded-ntr"},
    {"n": "3P/4P", "v": "threesome-foursome"},
    {"n": "女學生", "v": "schoolgirl"},
    {"n": "大屁股", "v": "big-ass"},
    {"n": "無套", "v": "bareback"},
    {"n": "顏射", "v": "bukkake"},
    {"n": "角色扮演", "v": "7889ef8307"},
    {"n": "亂倫", "v": "incest"},
    {"n": "肛門", "v": "anal"},
    {"n": "OL", "v": "ol"},
    {"n": "制服", "v": "uniform"},
    {"n": "狂歡", "v": "orgy"},
    {"n": "巨乳戀物癖", "v": "big-breast-fetish"},
    {"n": "噴出", "v": "squirting"},
    {"n": "女牛仔", "v": "cowgirl"},
    {"n": "乳交", "v": "titjob"},
    {"n": "姊妹", "v": "older-sister"},
    {"n": "紀錄片", "v": "documentary"},
    {"n": "深喉", "v": "deep-throat"},
]

# 業餘常用標籤
AMATEUR_FILTER = [
    {"n": "全部", "v": ""},
    {"n": "SIRO", "v": "tag:siro"},
    {"n": "LUXU", "v": "tag:259luxu"},
    {"n": "200GANA", "v": "tag:200gana"},
    {"n": "PRESTIGE", "v": "tag:prestige-premium"},
    {"n": "ORECO", "v": "tag:230oreco"},
    {"n": "ARA", "v": "tag:261ara"},
    {"n": "390JAC", "v": "tag:390jac"},
    {"n": "S-CUTE", "v": "maker:s-cute"},
    {"n": "Moody's", "v": "maker:moodys"},
    {"n": "SOD Create", "v": "maker:sod-create"},
    {"n": "Madonna", "v": "maker:madonna"},
    {"n": "Prestige", "v": "maker:prestige"},
    {"n": "S1", "v": "maker:s1-number-one-style"},    
]

# 無碼常用製作商（快速篩選，完整列表見「片商」分類）
MAKER_FILTER = [
    {"n": "全部", "v": ""},
    {"n": "FC2", "v": "maker:fc2"},
    {"n": "HEYZO", "v": "maker:heyzo"},
    {"n": "一本道", "v": "maker:1pondo"},
    {"n": "加勒比", "v": "maker:caribbeancom"},
    {"n": "Caribbeancompr", "v": "maker:caribbeancompr"},
    {"n": "天然素人", "v": "maker:10musume"},
    {"n": "人妻・熟女", "v": "maker:pacopacomama"},
    {"n": "東京熱", "v": "maker:tokyo-hot"},
    {"n": "XXX-AV", "v": "maker:xxx-av"},
    {"n": "人妻斬", "v": "maker:c0930"},
    {"n": "H0930", "v": "maker:h0930"},
    {"n": "H4610", "v": "maker:h4610"},
    {"n": "ガチん娘", "v": "maker:gachinco"},       
]

# 演員人數
ACTRESS_FILTER = [
    {"n": "全部", "v": ""},
    {"n": "單人", "v": "solo"},
    {"n": "多人", "v": "multiple"},
]


class Spider(BaseSpider):
    def getName(self):
        return "123AV"

    def init(self, extend=""):
        self.host = HOST
        self.headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-ja,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
            "Referer": self.host + "/ja",
        }
        self._last_err = ""

    def homeContent(self, filter):
        del filter
        classes = [{"type_id": t, "type_name": n} for t, n, _ in CATE_MAP]

        # 一般分類篩選（最新/最熱/有碼/無碼/無碼洩漏）
        common_filters = [
            {"key": "sort", "name": "排序", "value": SORT_FILTER},
            {"key": "year", "name": "年份", "value": YEAR_FILTER},
            {"key": "genre", "name": "類別", "value": GENRE_FILTER},
            {"key": "amateur", "name": "業餘標籤", "value": AMATEUR_FILTER},
            {"key": "maker", "name": "製作商", "value": MAKER_FILTER},
            {"key": "actress", "name": "演員", "value": ACTRESS_FILTER},
        ]
        # 片商列表頁：僅列表排序
        makers_list_filters = [
            {"key": "sort", "name": "排序", "value": MAKER_LIST_SORT},
        ]
        # 進入某個片商後的篩選（對齊站內：類型/年份/女演員/排序）
        maker_detail_filters = [
            {"key": "type", "name": "類型", "value": TYPE_FILTER},
            {"key": "year", "name": "年份", "value": YEAR_FILTER},
            {"key": "actress", "name": "演員", "value": ACTRESS_FILTER},
            {"key": "sort", "name": "排序", "value": SORT_FILTER},
        ]

        filters = {}
        for t, _n, _p in CATE_MAP:
            if t == "makers":
                filters[t] = makers_list_filters
            else:
                filters[t] = common_filters
        # 動態片商 type_id（maker:slug）使用片商詳情篩選
        # 客戶端通常只會對 class 裡的 type_id 取 filters，進入後用 extend 傳參即可
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        return self.categoryContent("recommend", "1", False, {})

    def categoryContent(self, tid, pg, filter, extend):
        del filter
        tid = str(tid or "recommend").strip()
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        path = "/ja/new"
        for t, _n, p in CATE_MAP:
            if t == tid:
                path = p
                break
        if tid.startswith("/ja/"):
            path = tid
        elif tid.startswith("maker:"):
            # 片商詳情：maker:fc2 → /ja/makers/fc2
            path = "/ja/makers/%s" % tid[6:]
        elif tid.startswith("makers/"):
            path = "/ja/" + tid

        ex = self._parse_extend(extend)
        sort = str(ex.get("sort") or "").strip()
        year = str(ex.get("year") or "").strip()
        genre = str(ex.get("genre") or "").strip()
        amateur = str(ex.get("amateur") or "").strip()
        maker = str(ex.get("maker") or "").strip()
        actress = str(ex.get("actress") or "").strip()
        vtype = str(ex.get("type") or "").strip()  # censored / uncensored / uncensored-leaked

        # 業餘標籤 / 製作商篩選優先改 path
        if amateur:
            if amateur.startswith("tag:"):
                path = "/ja/tags/%s" % amateur[4:]
            elif amateur.startswith("maker:"):
                path = "/ja/makers/%s" % amateur[6:]
            else:
                path = "/ja/tags/%s" % amateur
        elif maker:
            if maker.startswith("maker:"):
                path = "/ja/makers/%s" % maker[6:]
            else:
                path = "/ja/makers/%s" % maker
        elif genre:
            path = "/ja/genres/%s" % genre

        is_makers_list = path.rstrip("/") == "/ja/makers" or (
            tid == "makers" and not (amateur or maker or genre)
        )
        is_maker_detail = path.startswith("/ja/makers/") and path.rstrip("/") != "/ja/makers"

        qs = {}
        if sort:
            qs["sort"] = sort
        if year and year.isdigit():
            qs["year"] = year
        if actress:
            qs["actress"] = actress

        # 片商詳情頁：類型篩選
        if is_maker_detail and vtype:
            qs["type"] = vtype
        # 從有碼/無碼/無碼洩漏進入 genres/makers/tags 時帶 type
        if path.startswith(("/ja/genres/", "/ja/makers/", "/ja/tags/")):
            if not is_maker_detail or not vtype:
                if tid == "censored":
                    qs["type"] = "censored"
                elif tid == "uncensored":
                    qs["type"] = "uncensored"
                elif tid == "leaked":
                    qs["type"] = "uncensored-leaked"
                elif vtype:
                    qs["type"] = vtype

        if page > 1:
            qs["page"] = str(page)

        url = self.host + path
        if qs:
            url += "?" + urlencode(qs)

        html = self._get(url)

        if is_makers_list:
            items = self._parse_makers(html)
            pagecount = page
            if re.search(r"[?&]page=%d\b" % (page + 1), html or "") or re.search(
                r'href="[^"]*[?&]page=%d"' % (page + 1), html or ""
            ):
                pagecount = page + 1
            elif items and len(items) >= 50:
                pagecount = page + 1
            return {
                "list": items,
                "page": page,
                "pagecount": max(1, pagecount),
                "limit": 60,
                "total": max(1, pagecount) * 60,
            }

        items = self._parse_list(html)
        pagecount = page
        if re.search(r"[?&]page=%d\b" % (page + 1), html or ""):
            pagecount = page + 1
        elif items and len(items) >= 12:
            pagecount = page + 1
        return {
            "list": items,
            "page": page,
            "pagecount": max(1, pagecount),
            "limit": 24,
            "total": max(1, pagecount) * 24,
        }

    def searchContent(self, key, quick, pg="1"):
        del quick
        key = str(key or "").strip()
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        if not key:
            return {"list": [], "page": page}
        qs = {"keyword": key}
        if page > 1:
            qs["page"] = str(page)
        url = "%s/ja/search?%s" % (self.host, urlencode(qs))
        html = self._get(url)
        return {"list": self._parse_list(html), "page": page}

    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)) and ids:
            vid = str(ids[0] or "")
        else:
            vid = str(ids or "")
        vid = vid.strip().lstrip("/")
        if not vid:
            return {"list": []}

        # 片商入口：展開為該片商影片列表（由 category 處理更佳）
        if vid.startswith("maker:"):
            slug = vid[6:]
            return self.categoryContent("maker:" + slug, "1", False, {})

        if vid.startswith("ja/v/"):
            code = vid.split("/")[-1]
        elif vid.startswith("http"):
            m = re.search(r"/ja/v/([^/?#]+)", vid)
            code = m.group(1) if m else vid.rstrip("/").split("/")[-1]
        else:
            code = vid

        url = "%s/ja/v/%s" % (self.host, code)
        html = self._get(url)
        if not html:
            return {"list": [], "msg": self._last_err or "詳情失敗"}

        meta = self._parse_detail(html, code)
        play_from, play_url = self._build_play(html, code)
        return {
            "list": [
                {
                    "vod_id": code,
                    "vod_name": meta.get("title") or code,
                    "vod_pic": meta.get("pic") or "",
                    "vod_remarks": meta.get("remarks") or "",
                    "vod_year": meta.get("year") or "",
                    "vod_area": meta.get("area") or "日本",
                    "vod_director": meta.get("director") or "",
                    "vod_actor": meta.get("actor") or "",
                    "vod_content": meta.get("content") or "",
                    "type_name": meta.get("genre") or "",
                    "vod_play_from": play_from,
                    "vod_play_url": play_url,
                }
            ]
        }

    def playerContent(self, flag, id, vipFlags):
        del flag, vipFlags
        play = str(id or "").strip()
        if not play:
            return {"parse": 0, "msg": "無效播放 ID"}

        if play.startswith("http") and self.isVideoFormat(play):
            return self._play_result(play)

        if play.startswith("http") and "/e/" in play:
            media = self._resolve_embed(play)
            if media:
                return self._play_result(media, referer=play)
            return {
                "parse": 1,
                "jx": 0,
                "url": play,
                "header": self._play_headers(play),
            }

        code = play
        if "/ja/v/" in play:
            code = play.rstrip("/").split("/")[-1]
        url = "%s/ja/v/%s" % (self.host, code)
        html = self._get(url)
        embeds = self._extract_embed_urls(html) if html else []
        for emb in embeds:
            media = self._resolve_embed(emb)
            if media:
                return self._play_result(media, referer=emb)
        if embeds:
            return {
                "parse": 1,
                "jx": 0,
                "url": embeds[0],
                "header": self._play_headers(embeds[0]),
            }
        return {
            "parse": 1,
            "jx": 0,
            "url": url,
            "header": self._play_headers(url),
        }

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".flv", "/video.m3u8"))

    def manualVideoCheck(self):
        return False

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_extend(extend):
        if not extend:
            return {}
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str) and extend.strip():
            try:
                obj = json.loads(extend)
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
        return {}

    def _play_result(self, url, referer=None):
        return {
            "parse": 0,
            "jx": 0,
            "url": url,
            "header": self._play_headers(referer or self.host + "/ja"),
            "format": "application/x-mpegURL"
            if ".m3u8" in url
            else ("video/mp4" if ".mp4" in url else ""),
        }

    def _play_headers(self, referer=None):
        return {
            "User-Agent": UA,
            "Referer": referer or (self.host + "/ja"),
            "Origin": self.host,
        }

    def _parse_makers(self, html):
        """解析 /ja/makers 片商列表，vod_id 用 maker:slug 以便 categoryContent 進入詳情。"""
        if not html:
            return []
        items = []
        seen = set()
        for m in re.finditer(
            r'<a\s+class="mcard"\s+href="(/ja/makers/([^"]+))"[^>]*>(.*?)</a>',
            html,
            re.S | re.I,
        ):
            slug = m.group(2).strip()
            if not slug or slug in seen:
                continue
            inner = m.group(3)
            name_m = re.search(r'class="mcard__name"[^>]*>([^<]+)', inner, re.I)
            meta_m = re.search(r'class="mcard__meta"[^>]*>([^<]+)', inner, re.I)
            name = html_mod.unescape(name_m.group(1).strip()) if name_m else slug
            remarks = html_mod.unescape(meta_m.group(1).strip()) if meta_m else ""
            # 部分 logo 可能有圖片，優先文字 logo
            pic = ""
            img_m = re.search(
                r'(?:src|data-src)="(https?://[^"]+)"',
                inner,
                re.I,
            )
            if img_m:
                pic = img_m.group(1)
            seen.add(slug)
            items.append(
                {
                    "vod_id": "maker:" + slug,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                    "vod_tag": "folder",  # 提示為資料夾（若客戶端支援）
                }
            )
        # 後備：僅 href 匹配
        if not items:
            for m in re.finditer(r'href="(/ja/makers/([^"/?#]+))"', html):
                slug = m.group(2).strip()
                if not slug or slug in seen or slug.isdigit():
                    continue
                seen.add(slug)
                items.append(
                    {
                        "vod_id": "maker:" + slug,
                        "vod_name": slug,
                        "vod_pic": "",
                        "vod_remarks": "",
                    }
                )
        return items

    def _parse_list(self, html):
        """以整張 card 為單位解析，避免 href 出現兩次導致標題/封面錯位（順延到下一部）。"""
        if not html:
            return []
        items = []
        seen = set()

        # 優先：依 class="card" 切塊，保證 id / 標題 / 封面 / 時長同屬一卡
        card_iter = list(re.finditer(r'class="card"[^>]*>', html, re.I))
        for i, cm in enumerate(card_iter):
            start = cm.start()
            end = card_iter[i + 1].start() if i + 1 < len(card_iter) else min(len(html), start + 2500)
            block = html[start:end]

            hm = re.search(r'href="(/ja/v/([^"?#]+))"', block)
            if not hm:
                continue
            code = hm.group(2).strip()
            if not code or code in seen:
                continue

            # 標題（card__title 內的 a）
            title = code.upper()
            tm = re.search(
                r'class="card__title"[^>]*>[\s\S]*?<a[^>]*>([^<]+)</a>',
                block,
                re.I,
            )
            if tm and tm.group(1).strip():
                title = html_mod.unescape(tm.group(1).strip())
            else:
                tm = re.search(
                    r'class="card__link"[^>]*>([^<]+)</a>',
                    block,
                    re.I,
                )
                if tm and tm.group(1).strip():
                    title = html_mod.unescape(tm.group(1).strip())

            # 封面
            pic = ""
            img = re.search(
                r'(?:src|data-src)="([^"]*(?:cover|img2)[^"]*)"',
                block,
                re.I,
            )
            if not img:
                img = re.search(
                    r'(?:src|data-src)="(https?://icdn\.123av[^"]+)"',
                    block,
                    re.I,
                )
            if img:
                pic = img.group(1)

            # 時長
            remarks = ""
            dm = re.search(
                r'class="[^"]*card__dur[^"]*"[^>]*>\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\s*<',
                block,
                re.I,
            )
            if not dm:
                dm = re.search(
                    r'class="[^"]*dur(?:ation)?[^"]*"[^>]*>\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\s*<',
                    block,
                    re.I,
                )
            if dm:
                remarks = dm.group(1).strip()

            seen.add(code)
            items.append(
                {
                    "vod_id": code,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                }
            )

        # 後備：若站內改版沒有 card class，仍用 href 掃描（取標題那次匹配，窗口改為向後為主）
        if not items:
            for m in re.finditer(r'href="(/ja/v/([^"?#]+))"', html):
                code = m.group(2)
                if code in seen:
                    continue
                # 標題通常在 href 之後，向後多取、向前少取
                window_b = html[max(0, m.start() - 200) : m.end() + 900]
                img = re.search(
                    r'(?:src|data-src)="([^"]*(?:cover|img2)[^"]*)"',
                    window_b,
                    re.I,
                )
                if not img:
                    img = re.search(
                        r'(?:src|data-src)="(https?://icdn\.123av[^"]+)"',
                        window_b,
                        re.I,
                    )
                pic = img.group(1) if img else ""
                title = code.upper()
                for pat in (
                    r'class="card__title"[^>]*>[\s\S]*?>([^<]+)</a>',
                    r'class="card__link"[^>]*>([^<]+)</a>',
                    r'class="[^"]*title[^"]*"[^>]*>([^<]{2,120})<',
                ):
                    tm = re.search(pat, window_b, re.I)
                    if tm and tm.group(1).strip():
                        title = html_mod.unescape(tm.group(1).strip())
                        break
                remarks = ""
                dm = re.search(
                    r'class="[^"]*card__dur[^"]*"[^>]*>\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\s*<',
                    window_b,
                    re.I,
                )
                if dm:
                    remarks = dm.group(1).strip()
                seen.add(code)
                items.append(
                    {
                        "vod_id": code,
                        "vod_name": title,
                        "vod_pic": pic,
                        "vod_remarks": remarks,
                    }
                )
        return items

    def _parse_detail(self, html, code):
        meta = {
            "title": "",
            "pic": "",
            "actor": "",
            "director": "",
            "genre": "",
            "area": "日本",
            "year": "",
            "remarks": "",
            "content": "",
        }
        m = re.search(r"<h1[^>]*>([^<]+)</h1>", html, re.I)
        if m:
            meta["title"] = m.group(1).strip()
        if not meta["title"]:
            m = re.search(r"<title>([^|<]+)", html)
            if m:
                meta["title"] = m.group(1).replace("123AV", "").strip(" —-_")

        m = re.search(
            r"background-image:url\(['\"]?(https?://icdn\.123av[^'\")]+cover[^'\")]+)",
            html,
            re.I,
        )
        if m:
            meta["pic"] = m.group(1)
        if not meta["pic"]:
            m = re.search(
                r'(?:src|data-src)="(https?://icdn\.123av[^"]*cover[^"]*)"',
                html,
                re.I,
            )
            if m:
                meta["pic"] = m.group(1)

        def dd(label):
            m = re.search(
                rf"<dt>\s*{label}\s*</dt>\s*<dd[^>]*>([\s\S]*?)</dd>",
                html,
                re.I,
            )
            if not m:
                return ""
            names = re.findall(r">([^<]+)</a>", m.group(1))
            names = [n.strip() for n in names if n.strip()]
            if names:
                return ",".join(dict.fromkeys(names))
            text = re.sub(r"<[^>]+>", "", m.group(1))
            return re.sub(r"\s+", " ", text).strip()

        meta["actor"] = dd("演員") or dd("女优") or dd("女優")
        if not meta["actor"] and "—" in (meta.get("title") or ""):
            tail = meta["title"].split("—")[-1].strip()
            if 1 < len(tail) < 40 and not re.search(r"\d{2,}", tail):
                meta["actor"] = tail

        meta["director"] = dd("製作商") or dd("片商") or dd("Maker")

        g1 = dd("類型")
        g2 = dd("類別")
        g3 = dd("標籤")
        parts = [x for x in (g1, g2, g3) if x]
        meta["genre"] = ",".join(parts)

        date = dd("發布日期")
        if date:
            ym = re.search(r"((?:19|20)\d{2})", date)
            if ym:
                meta["year"] = ym.group(1)
        duration = dd("時長")
        if not duration:
            dm = re.search(
                r'class="[^"]*(?:card__dur|duration)[^"]*"[^>]*>\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\s*<',
                html,
                re.I,
            )
            if dm:
                duration = dm.group(1).strip()
        code_s = dd("代碼") or code.upper()
        remarks = []
        if duration:
            remarks.append(duration)
        if code_s:
            remarks.append(code_s)
        meta["remarks"] = " · ".join(remarks)

        meta["content"] = meta.get("title") or ""
        m = re.search(r'property="og:description"\s+content="([^"]*)"', html)
        if m and len(m.group(1)) > 20:
            if len(meta["content"]) < 30:
                meta["content"] = m.group(1).strip()
        for pat in (
            r'class="[^"]*watch__desc[^"]*"[^>]*>([\s\S]{10,500}?)</div>',
            r'class="[^"]*description[^"]*"[^>]*>([\s\S]{10,500}?)</',
        ):
            m = re.search(pat, html, re.I)
            if m:
                text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if len(text) > 20:
                    meta["content"] = text[:400]
                    break
        return meta

    def _extract_embed_urls(self, html):
        if not html:
            return []
        urls = []
        m = re.search(r"player\(JSON\.parse\('(\[.*?\])'\)", html)
        if m:
            raw = m.group(1)
            try:
                decoded = bytes(raw, "utf-8").decode("unicode_escape")
                decoded = decoded.replace("\\/", "/")
                data = json.loads(decoded)
                for ep in data:
                    u = str(ep.get("url") or "").replace("\\/", "/")
                    if u.startswith("http") and "/e/" in u:
                        urls.append(u)
            except Exception:
                pass
            if not urls:
                mm = re.search(
                    r"https:(?:\\+/)+jav-master[^\\]+/e/[A-Za-z0-9_]+", raw
                )
                if mm:
                    u = mm.group(0).replace("\\/", "/")
                    if u.startswith("http"):
                        urls.append(u)
        out, seen = [], set()
        for u in urls:
            u = u.replace("\\/", "/")
            if "/e/" in u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _build_play(self, html, code):
        """選集改為「第?集」格式。"""
        embeds = self._extract_embed_urls(html)
        if not embeds:
            return "123AV", "第1集$%s" % code
        parts = []
        for i, emb in enumerate(embeds):
            parts.append("第%d集$%s" % (i + 1, emb))
        return "123AV", "#".join(parts)

    def _resolve_embed(self, embed_url):
        try:
            m = re.search(r"/e/([A-Za-z0-9_]+)", embed_url)
            if not m:
                return ""
            hash_id = m.group(1)
            parsed = urlparse(embed_url)
            origin = "%s://%s" % (parsed.scheme, parsed.netloc)
            qs = parse_qs(parsed.query)
            params = {"id": hash_id}
            for k, v in qs.items():
                if k != "id" and v:
                    params[k] = v[0]
            stream_api = origin + "/stream?" + urlencode(params)
            headers = {
                "User-Agent": UA,
                "Referer": embed_url,
                "Origin": origin,
                "Accept": "application/json,text/plain,*/*",
            }
            body = self._get(stream_api, headers=headers)
            if not body:
                return ""
            data = json.loads(body)
            media = data.get("media") or {}
            stream = str(media.get("stream") or "").strip()
            if stream.startswith("http"):
                return stream
        except Exception as e:
            self._last_err = str(e)[:100]
        return ""

    def _get(self, url, headers=None):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        try:
            if hasattr(self, "fetch"):
                rsp = self.fetch(url, headers=h)
                if isinstance(rsp, str) and rsp:
                    return rsp
                if rsp is not None:
                    text = getattr(rsp, "text", None)
                    if text:
                        return str(text)
                    c = getattr(rsp, "content", None)
                    if isinstance(c, (bytes, bytearray)):
                        return c.decode("utf-8", "ignore")
        except Exception as e:
            self._last_err = str(e)[:100]
        try:
            from com.github.catvod.net import OkHttp
            from java.util import HashMap

            hm = HashMap()
            for k, v in h.items():
                hm.put(str(k), str(v))
            out = OkHttp.string(url, hm)
            if out is not None:
                return str(out)
        except Exception as e:
            self._last_err = str(e)[:100]
        try:
            from urllib.request import Request, urlopen

            req = Request(url, headers=h)
            with urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            self._last_err = str(e)[:100]
            return ""
