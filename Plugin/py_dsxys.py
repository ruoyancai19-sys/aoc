# -*- coding: utf-8 -*-
"""
配置示例：
{
  "key": "dsxys",
  "name": "大师兄",
  "type": 3,
  "api": "py_dsxys.py",
  "searchable": 1,
  "quickSearch": 1,
  "filterable": 1,
  "changeable": 0
}
"""

import json
import re
import time
import gzip
import ssl
import urllib.request
import urllib.error
import urllib.parse

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


class Spider(_BaseSpider):
    def init(self, extend=""):
        self.extend = extend or ""
        self.crypto = "http://103.36.222.35:9595/wexfnwshinidie/appv7/crypto.php"
        self.host = "http://app2.dsx.ac/ndsx.php"
        self.cfg = {
            "key": "AppV7Dsx",
            "version": "4.0.0",
            "version_number": "4000",
            "pk_id": "com.qdsj.zxt.hzjc",
            "build_time": "1786613938967",
            "sign_md5": "56a4bb80bd67422e9c5b48f003d445c8",
            "apk_length": 59954699,
            "user_agent": "Dart/3.11 (dart:io)",
            "platform": "android",
            "platform_version": "TP1A.220624.014",
        }
        self._nav = None
        self._timeout = 15
        self._ssl = ssl._create_unverified_context()
        if self.extend:
            try:
                ext = json.loads(self.extend) if str(self.extend).strip().startswith("{") else {}
                if isinstance(ext, dict):
                    self.crypto = ext.get("crypto", self.crypto)
                    self.host = ext.get("host", self.host)
                    if ext.get("timeout"):
                        self._timeout = int(ext["timeout"])
                    self.cfg.update(ext.get("cfg") or {})
            except Exception:
                pass

    def getName(self):
        return "大师兄"

    def destroy(self):
        pass

    # ---------------- http ----------------
    def _post(self, url, body, headers, timeout=None):
        timeout = self._timeout if timeout is None else timeout
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=self._ssl, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
        except Exception as e:
            raise RuntimeError("POST %s failed: %s" % (url, e))
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return raw

    def _get(self, url, headers=None, timeout=None):
        timeout = self._timeout if timeout is None else timeout
        h = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://dsxys.com/",
        }
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, context=self._ssl, timeout=timeout) as r:
            raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return raw

    def _encrypt(self, method, data):
        csrf = int(time.time() * 1000)
        payload_data = {
            "token": data.get("token", ""),
            "sign_md5": self.cfg["sign_md5"],
            "apk_path": "/data/app/~~x/%s-x/base.apk" % self.cfg["pk_id"],
            "apk_length": self.cfg["apk_length"],
        }
        for k, v in data.items():
            if k != "token":
                payload_data[k] = v
        raw = {"method": method, "data": payload_data, "csrf": csrf}
        body = {
            "key": self.cfg.get("key", "AppV7Dsx"),
            "raw": json.dumps(raw, separators=(",", ":"), ensure_ascii=False),
        }
        resp = self._post(
            self.crypto + "?action=encrypt",
            json.dumps(body, ensure_ascii=False),
            {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "okhttp/5.3.2",
            },
        )
        j = json.loads(resp.decode("utf-8", "replace"))
        if "body" not in j:
            raise RuntimeError("encrypt fail: %s" % resp[:200])
        return j["body"]

    def _decrypt(self, cipher):
        body = {"key": self.cfg.get("key", "AppV7Dsx"), "body": cipher}
        resp = self._post(
            self.crypto + "?action=decrypt",
            json.dumps(body, ensure_ascii=False),
            {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "okhttp/5.3.2",
            },
            timeout=max(self._timeout, 20),
        )
        j = json.loads(resp.decode("utf-8", "replace"))
        text = j.get("text") or ""
        if text:
            try:
                return json.loads(text)
            except Exception:
                return {"_text": text}
        return j

    def _api(self, method, data=None):
        data = data or {}
        cipher = self._encrypt(method, data)
        headers = {
            "user-agent": self.cfg["user_agent"],
            "version": self.cfg["version"],
            "version-number": str(self.cfg["version_number"]),
            "pk-id": self.cfg["pk_id"],
            "build-time": str(self.cfg["build_time"]),
            "platform": self.cfg["platform"],
            "platform-version": self.cfg["platform_version"],
            "Content-Type": "text/plain; charset=utf-8",
            "Accept-Encoding": "gzip",
        }
        raw = self._post(self.host.rstrip("/") + "/v7/logs", cipher, headers)
        text = raw.decode("utf-8", "replace")
        try:
            return json.loads(text)
        except Exception:
            return self._decrypt(text.strip())

    # ---------------- helpers ----------------
    def _item(self, v):
        return {
            "vod_id": str(v.get("vod_id", "")),
            "vod_name": v.get("vod_name") or "",
            "vod_pic": v.get("vod_pic") or "",
            "vod_remarks": v.get("vod_remarks") or "",
        }

    def _filters_from_nav(self, nav_list):
        filters = {}
        for t in nav_list or []:
            tid = str(t.get("type_id", ""))
            ext = t.get("type_extend") or {}
            fl = []
            for key, label in (
                ("class", "类型"),
                ("area", "地区"),
                ("year", "年份"),
                ("lang", "语言"),
            ):
                vals = [x.strip() for x in str(ext.get(key) or "").split(",") if x.strip()]
                if not vals:
                    continue
                fl.append(
                    {
                        "key": key,
                        "name": label,
                        "value": [{"n": "全部", "v": ""}]
                        + [{"n": x, "v": x} for x in vals],
                    }
                )
            if fl:
                filters[tid] = fl
        return filters

    def _safe_nav(self):
        if self._nav is not None:
            return self._nav
        try:
            j = self._api("nav", {})
            self._nav = j.get("data") or []
        except Exception:
            self._nav = [
                {"type_id": 1, "type_name": "电影"},
                {"type_id": 2, "type_name": "剧集"},
                {"type_id": 3, "type_name": "综艺"},
                {"type_id": 4, "type_name": "动漫"},
                {"type_id": 63, "type_name": "短剧"},
                {"type_id": 64, "type_name": "AI漫剧"},
            ]
        return self._nav

    # ---------------- TVBox API ----------------
    def homeContent(self, filter):
        try:
            nav = self._safe_nav()
            classes = []
            for t in nav:
                classes.append(
                    {
                        "type_id": str(t.get("type_id")),
                        "type_name": t.get("type_name") or "",
                    }
                )
            result = {"class": classes}
            if filter:
                result["filters"] = self._filters_from_nav(nav)
            return result
        except Exception:
            return {
                "class": [
                    {"type_id": "1", "type_name": "电影"},
                    {"type_id": "2", "type_name": "剧集"},
                    {"type_id": "3", "type_name": "综艺"},
                    {"type_id": "4", "type_name": "动漫"},
                ]
            }

    def homeVideoContent(self):
        try:
            j = self._api("video_list", {"tid": 1, "page": 1})
            return {"list": [self._item(x) for x in (j.get("data") or [])]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = str(pg or "1")
            data = {
                "tid": int(tid) if str(tid).isdigit() else tid,
                "page": int(pg) if str(pg).isdigit() else 1,
            }
            if isinstance(extend, dict):
                for k in ("class", "area", "year", "lang"):
                    if extend.get(k):
                        data[k] = extend[k]
            j = self._api("video_list", data)
            lst = [self._item(x) for x in (j.get("data") or [])]
            pagecount = j.get("pagecount") or (999 if lst else 1)
            return {
                "list": lst,
                "page": int(pg) if str(pg).isdigit() else 1,
                "pagecount": int(pagecount),
                "limit": 21,
                "total": int(pagecount) * 21,
            }
        except Exception:
            return {
                "list": [],
                "page": 1,
                "pagecount": 1,
                "limit": 21,
                "total": 0,
            }

    def searchContent(self, key, quick, pg="1"):
        try:
            pg = str(pg or "1")
            j = self._api("search", {"text": key, "page": int(pg) if str(pg).isdigit() else 1})
            lst = [self._item(x) for x in (j.get("data") or [])]
            return {"list": lst, "page": int(pg) if str(pg).isdigit() else 1}
        except Exception:
            return {"list": [], "page": 1}

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else ids
            j = self._api(
                "video_detail",
                {"id": int(vid) if str(vid).isdigit() else vid},
            )
            data = j.get("data") or {}
            vi = data.get("vod_info") or {}
            players = vi.get("vod_url_with_player") or []
            lines = []  # (priority, name, eps_joined)
            for p in players:
                name = (p.get("name") or p.get("code") or "线路").replace("$", "_").replace("#", "_")
                raw = p.get("url") or ""
                parse_api = (p.get("parse_api") or "").strip()
                eps = []
                direct = 0
                ace = 0
                for seg in raw.split("#"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    if "$" in seg:
                        title, link = seg.split("$", 1)
                    else:
                        title, link = "正片", seg
                    title = title.replace("#", "_").replace("$", "_")
                    if link.startswith("http://") or link.startswith("https://"):
                        eps.append("%s$%s" % (title, link))
                        direct += 1
                    else:
                        eps.append("%s$%s|||%s" % (title, parse_api, link))
                        if "ace.php" in parse_api.lower():
                            ace += 1
                if not eps:
                    continue
                # 直链优先，其次 Ace(明文JSON)，其它独家加密线靠后
                if direct:
                    pri = 0
                elif ace:
                    pri = 1
                else:
                    pri = 2
                lines.append((pri, name, "#".join(eps)))
            lines.sort(key=lambda x: x[0])
            play_from = [x[1] for x in lines]
            play_url = [x[2] for x in lines]
            vod = {
                "vod_id": str(vi.get("vod_id") or vid),
                "vod_name": vi.get("vod_name") or "",
                "vod_pic": vi.get("vod_pic") or "",
                "type_name": vi.get("vod_class") or "",
                "vod_year": vi.get("vod_year") or "",
                "vod_area": vi.get("vod_area") or "",
                "vod_remarks": vi.get("vod_remarks") or "",
                "vod_actor": vi.get("vod_actor") or "",
                "vod_director": vi.get("vod_director") or "",
                "vod_content": vi.get("vod_content") or vi.get("vod_blurb") or "",
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def _parse_decrypt(self, cipher_text):
        """Wex parse_decrypt：解开 bt2/xd/za 等解析站密文，得到最终播放地址。"""
        dec = self._post(
            self.crypto + "?action=parse_decrypt",
            json.dumps(
                {"key": self.cfg.get("key", "AppV7Dsx"), "raw": cipher_text},
                ensure_ascii=False,
            ),
            {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "okhttp/5.3.2",
            },
        )
        dj = json.loads(dec.decode("utf-8", "replace"))
        text = dj.get("text") or ""
        if not text:
            return None
        try:
            j = json.loads(text)
            if isinstance(j.get("url"), str) and j["url"].startswith("http"):
                return j["url"]
            if isinstance(j.get("data"), str) and j["data"].startswith("http"):
                return j["data"]
        except Exception:
            if text.startswith("http"):
                return text.splitlines()[0].strip()
        return None

    def _resolve_parse(self, parse_api, token, headers):
        """调用解析站；明文 JSON / 直链直接用；密文走 parse_decrypt。"""
        raw = self._get(parse_api + token)
        text = raw.decode("utf-8", "replace").strip()
        # 1) 明文 JSON（如 Ace）
        try:
            j = json.loads(text)
            if isinstance(j.get("url"), str) and j["url"].startswith("http"):
                return {"parse": 0, "url": j["url"], "header": headers}
            data = j.get("data")
            if isinstance(data, dict) and str(data.get("url", "")).startswith("http"):
                return {"parse": 0, "url": data["url"], "header": headers}
            if isinstance(data, str) and data.startswith("http"):
                return {"parse": 0, "url": data, "header": headers}
        except Exception:
            pass
        # 2) 纯 URL
        if text.startswith("http://") or text.startswith("https://"):
            return {"parse": 0, "url": text.splitlines()[0].strip(), "header": headers}
        # 3) 解析站密文 → parse_decrypt（HAR 验证的关键 action）
        try:
            url = self._parse_decrypt(text)
            if url:
                if url.startswith("http%3A") or url.startswith("https%3A"):
                    url = urllib.parse.unquote(url)
                return {"parse": 0, "url": url, "header": headers}
        except Exception:
            pass
        # 4) 兜底
        return {"parse": 1, "url": parse_api + token, "header": headers}

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self.cfg.get("user_agent", "Dart/3.11 (dart:io)"),
            "Referer": "https://dsxys.com/",
        }
        url = id or ""
        try:
            if "|||" in url:
                parse_api, token = url.split("|||", 1)
                if parse_api and token:
                    try:
                        return self._resolve_parse(parse_api, token, headers)
                    except Exception:
                        return {"parse": 1, "url": parse_api + token, "header": headers}
            if url.startswith("http://") or url.startswith("https://"):
                return {"parse": 0, "url": url, "header": headers}
            return {"parse": 1, "url": url, "header": headers}
        except Exception:
            return {"parse": 1, "url": url, "header": headers}

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|mkv|flv|ts)(\?|$)", url or "", re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return []
