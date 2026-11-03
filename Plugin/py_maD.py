# -*- coding: utf-8 -*-
import json
from urllib.parse import quote

from base.spider import Spider as BaseSpider


HOME_URL = "https://19q.cc"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.6261.95 Safari/537.36"
)


class Spider(BaseSpider):
    def init(self, extend=""):
        self.home_url = HOME_URL
        if extend:
            try:
                if isinstance(extend, dict):
                    opt = extend
                else:
                    opt = json.loads(extend)
                if isinstance(opt, dict) and opt.get("home_url"):
                    self.home_url = str(opt["home_url"]).rstrip("/")
            except Exception:
                pass

    def getName(self):
        return "麻豆"

    def homeContent(self, filter):
        data = self._get("/api.php/provide/vod/?ac=list")
        classes = []
        for item in data.get("class") or []:
            tid = item.get("type_id")
            name = item.get("type_name")
            if tid is not None and name:
                classes.append({
                    "type_id": str(tid),
                    "type_name": str(name),
                })
        result = {"class": classes}
        if filter:
            result["filters"] = {}
        return result

    def homeVideoContent(self):
        data = self._get("/api.php/provide/vod/?ac=detail")
        items = []
        for item in data.get("list") or []:
            card = self._card(item)
            if card["vod_name"]:
                items.append(card)
        return {"list": items}

    def categoryContent(self, tid, pg, filter, extend):
        page = self._page(pg)
        data = self._get(
            "/api.php/provide/vod/?ac=detail&t=%s&pg=%s" % (quote(str(tid)), page)
        )
        items = [self._card(item) for item in data.get("list") or []]
        return self._result(items, page, data)

    def searchContent(self, key, quick, pg="1"):
        query = str(key or "").strip()
        if not query:
            return self._result([], 1, {})
        page = self._page(pg)
        data = self._get(
            "/api.php/provide/vod/?ac=detail&wd=%s&pg=%s" % (quote(query), page)
        )
        items = [self._card(item) for item in data.get("list") or []]
        return self._result(items, page, data)

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = str(ids[0]).strip()
        if vid.startswith("vod/"):
            vid = vid[4:]
        data = self._get("/api.php/provide/vod/?ac=detail&ids=%s" % quote(vid))
        lst = data.get("list") or []
        if not lst:
            return {"list": []}
        item = lst[0]
        vod = self._card(item)
        play_from = str(item.get("vod_play_from") or "麻豆").strip() or "麻豆"
        play_url = str(item.get("vod_play_url") or "").strip()
        vod.update({
            "type_name": str(item.get("type_name") or ""),
            "vod_year": str(item.get("vod_year") or ""),
            "vod_area": str(item.get("vod_area") or ""),
            "vod_actor": str(item.get("vod_actor") or ""),
            "vod_director": str(item.get("vod_director") or ""),
            "vod_content": str(item.get("vod_content") or item.get("vod_blurb") or ""),
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        })
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        if "$" in url:
            url = url.split("$")[-1].strip()
        if not url.startswith(("http://", "https://")):
            return {"parse": 0, "url": "", "msg": "無效播放地址"}
        return {
            "parse": 0,
            "jx": 0,
            "url": url,
            "header": {
                "User-Agent": UA,
                "Referer": self.home_url + "/",
            },
        }

    def manualVideoCheck(self):
        return True

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return u.startswith("http") and ".m3u8" in u and "/ad/" not in u

    def destroy(self):
        pass

    # -------------------- 內部方法 --------------------

    def _get(self, path):
        url = self.home_url + path
        headers = {
            "User-Agent": UA,
            "Referer": self.home_url + "/",
            "Accept": "application/json, text/plain, */*",
        }
        try:
            rsp = self.fetch(url, headers=headers, timeout=12)
            content = rsp.text if hasattr(rsp, "text") else str(rsp or "")
            if not content:
                return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _page(pg):
        try:
            return max(1, int(pg))
        except Exception:
            return 1

    @staticmethod
    def _result(items, page, data):
        try:
            pagecount = max(1, int(data.get("pagecount") or 1))
        except Exception:
            pagecount = 1
        try:
            limit = int(data.get("limit") or 30)
        except Exception:
            limit = 30
        try:
            total = int(data.get("total") or len(items))
        except Exception:
            total = len(items)
        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    @staticmethod
    def _card(item):
        name = str(item.get("vod_name") or "").strip()
        pic = item.get("vod_pic")
        if not pic or str(pic).lower() in ("null", "none"):
            pic = ""
        else:
            pic = str(pic).strip()
        remarks = str(item.get("vod_remarks") or "").strip()
        return {
            "vod_id": str(item.get("vod_id") or ""),
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remarks,
            "style": {"type": "rect", "ratio": 0.75},
        }
