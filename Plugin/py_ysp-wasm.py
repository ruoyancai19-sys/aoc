"""央视频 TV 直播"""

import hashlib
import json
import os
import io
import platform
import tarfile
import random
import shutil
import struct
import string
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from base.spider import Spider as BaseSpider


HOST = "https://www.yangshipin.cn"
PLAYER_URL = "https://player-api.yangshipin.cn/v1/player/"
OPEN_TOKEN_URL = "https://h5access.yangshipin.cn/web/open/token"

YSP_APP_ID = "519748109"
APP_VERSION = "V1.0.0"
PLATFORM = "5910204"
AUTH_SALT = "n@7QKk%YeSjfw%22"
REQUEST_SALT = "0f$IVHi9Qno?G"
OPEN_VAPP_ID = "59306155"
OPEN_VSECRET = "b42702bf7309a179d102f3d51b1add2fda0bc7ada64cb801"

#  XOR ticket 兜底用
TICKET_KEYSTREAM = bytes.fromhex(
    "6a70e9ac007ccc384c28a88dfd2211decb66494bca83bd6178f85732b2eacc959"
    "4e4e5ab720ec3a43e87b3c72b86192ff0dfea8fa8f47794d8792668438c"
)
TICKET_SUFFIX = "bSCz8SqH8T"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# ---- 超时与预算 ----
HTTP_TIMEOUT = 15  # 单次 HTTP 请求上限
PLAYER_BUDGET = 25  # auth + open_token + get_live_info 整链预算
SEGMENT_BUDGET = 30  # 单个 segment 下载 + 解密预算
PREDECRYPT_BUDGET = 8  # 预解密前序 segment 的尽力预算
M3U8_TIMEOUT = 15  # m3u8 manifest 抓取上限（固定，不继承 deadline）

PLAY_CACHE_SECONDS = 60  # 播放地址缓存时长
COPYRIGHT_CACHE_SECONDS = 600  # 版权受限频道缓存，避免反复"加载失败"
PROCESSED_MAX = 48  # 明文段缓存条数
PROCESSED_TTL_SECONDS = 300.0  # 明文段缓存 TTL；过期即丢弃
SEG_CACHE_HARD_CAP = 500  # (slug, sid) 元信息硬上限
SEG_CACHE_KEEP = 300  # 超过硬上限后保留的最新条数

PREDECRYPT_MAX = 11

# 预解密：开启可在换台/拖进度条时提前解密前序分片，加快首屏。
ENABLE_PREDECRYPT = True

# 直通频道：m3u8 中的分片直接原样代理，不做 CMG 解密。
PASSTHROUGH_SLUGS = frozenset({"cetv1"})

# 直播分组显示名
GROUP_NAMES = {
    "央视": "央视",
    "卫视": "卫视",
    "数字": "数字",
    "CGTN": "CGTN",
}

COPYRIGHT_MARKERS = (
    "应版权方要求",
    "地区因版权原因",
    "因版权原因",
    "版权受限",
    "所在区域无法观看",
    "当前国家或地区",
    "暂无法在当前",
    "区域限制",
)

# ---- 日志 ----
ENABLE_LOG = True  # False 则 _log() 立即返回，完全不写盘
_DEBUG_LOG = "/sdcard/ysp-debug.log"
_LOG_READY = False
_LOG_LOCK = threading.Lock()
_LOG_MAX_BYTES = 2 * 1024 * 1024

# 轮转检查节流：距上次检查 >= 10s，或累计写入 >= 200 行，才真正做 stat
_LOG_ROTATE_INTERVAL = 10.0
_LOG_ROTATE_EVERY = 200
_log_last_check = 0.0
_log_lines_since = 0

_OPENER = urllib.request.build_opener()


# ============================================================
# 日志
# ============================================================
def _init_log():
    global _LOG_READY
    if not ENABLE_LOG:
        return
    with _LOG_LOCK:
        if _LOG_READY:
            return
        try:
            os.makedirs(os.path.dirname(_DEBUG_LOG), exist_ok=True)
        except Exception:
            pass
        try:
            with open(_DEBUG_LOG, "w", encoding="utf-8") as f:
                f.write("[{}] === 日志开始 ===\n".format(
                    time.strftime("%Y-%m-%d %H:%M:%S")))
        except Exception:
            pass
        _LOG_READY = True


def _log(msg):
    global _LOG_READY, _log_last_check, _log_lines_since
    if not ENABLE_LOG:
        return
    if not _LOG_READY:
        _init_log()
    line = "[{}] {}\n".format(time.strftime("%H:%M:%S"), msg)
    with _LOG_LOCK:
        now = time.monotonic()
        _log_lines_since += 1
        if (now - _log_last_check) >= _LOG_ROTATE_INTERVAL or \
           _log_lines_since >= _LOG_ROTATE_EVERY:
            _log_last_check = now
            _log_lines_since = 0
            try:
                if os.path.getsize(_DEBUG_LOG) > _LOG_MAX_BYTES:
                    backup = _DEBUG_LOG + ".1"
                    try:
                        if os.path.exists(backup):
                            os.remove(backup)
                        os.replace(_DEBUG_LOG, backup)
                    except Exception:
                        pass
            except OSError:
                pass
        try:
            with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            try:
                sys.stderr.write("[ysp] {}\n".format(msg))
            except Exception:
                pass


def _is_copyright_msg(text):
    if not text:
        return False
    return any(marker in text for marker in COPYRIGHT_MARKERS)


# ============================================================
# 错误与超时
# ============================================================
class _ProxyError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class _CopyrightError(_ProxyError):
    def __init__(self, message):
        super().__init__(451, message)


def _remaining(deadline, stage):
    if deadline is None:
        return HTTP_TIMEOUT
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _ProxyError(504, "{}: 取址逾时".format(stage))
    return remaining


def _capped_timeout(deadline, stage, cap):
    if deadline is None:
        return cap
    return max(0.1, min(cap, _remaining(deadline, stage)))


def _is_client_disconnect(exc):
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (32, 104):
        return True
    return False


def _http(opener, url, headers=None, deadline=None, data=None, method=None,
    stage="网络请求", cap=HTTP_TIMEOUT):
    timeout = _capped_timeout(deadline, stage, cap)
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        _log("HTTP {} {}: {}".format(e.code, url[:120], body[:400]))
        status = e.code if 400 <= e.code < 600 else 502
        raise _ProxyError(status, "{}: HTTP {}".format(stage, e.code)) from None
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        _log("HTTP 失败 {} -> {}".format(url[:120], reason))
        lowered = reason.lower()
        status = 504 if ("timed out" in lowered or "timeout" in lowered) else 502
        raise _ProxyError(status, "{}: {}".format(stage, reason)) from None
    except Exception as e:
        msg = "{}: {}".format(type(e).__name__, e)
        _log("HTTP 失败 {} -> {}".format(url[:120], msg))
        raise _ProxyError(502, "{}: {}".format(stage, msg)) from None


# ============================================================
# 图标 / 频道表
# ============================================================
LOGO_BASE = "https://static.tv.darwinchow.com/logo/"
LOGO_MAP = {
    "cctv1": "CCTV1.png", "cctv2": "CCTV2.png", "cctv3": "CCTV3.png",
    "cctv4": "CCTV4.png", "cctv5": "CCTV5.png", "cctv5p": "CCTV5+.png",
    "cctv6": "CCTV6.png", "cctv7": "CCTV7.png", "cctv8": "CCTV8.png",
    "cctv9": "CCTV9.png", "cctv10": "CCTV10.png", "cctv11": "CCTV11.png",
    "cctv12": "CCTV12.png", "cctv13": "CCTV13.png", "cctv14": "CCTV14.png",
    "cctv15": "CCTV15.png", "cctv16": "CCTV16.png", "cctv164k": "CCTV16.png",
    "cctv17": "CCTV17.png", "cctv4k": "CCTV4K.png", "cctv8k": "CCTV8K.png",
    "cgtn": "CGTN.png", "cgtnfr": "CGTN法语.png", "cgtnru": "CGTN俄语.png",
    "cgtnar": "CGTN阿语.png", "cgtnes": "CGTN西语.png", "cgtndoc": "CGTNDoc.png",
    "fyjc": "风云剧场.png", "dyjc": "第一剧场.png", "hjjc": "怀旧剧场.png",
    "bjws": "北京卫视.png", "dfws": "东方卫视.png", "jsws": "江苏卫视.png",
    "zjws": "浙江卫视.png", "hnws": "湖南卫视.png", "hbws": "湖北卫视.png",
    "gdws": "广东卫视.png", "gxws": "广西卫视.png", "hljws": "黑龙江卫视.png",
    "hainanws": "海南卫视.png", "cqws": "重庆卫视.png", "szws": "深圳卫视.png",
    "scws": "四川卫视.png", "henanws": "河南卫视.png", "dnws": "东南卫视.png",
    "gzws": "贵州卫视.png", "jxws": "江西卫视.png", "lnws": "辽宁卫视.png",
    "ahws": "安徽卫视.png", "hebws": "河北卫视.png", "sdws": "山东卫视.png",
    "tjws": "天津卫视.png", "jlws": "吉林卫视.png", "saxws": "陕西卫视.png",
    "nxws": "宁夏卫视.png", "nmgws": "内蒙古卫视.png", "ynws": "云南卫视.png",
    "shanxiws": "山西卫视.png", "qhws": "青海卫视.png", "xizangws": "西藏卫视.png",
    "xjws": "新疆卫视.png", "gansuws": "甘肃卫视.png", "gsws": "甘肃卫视.png",
    "btws": "兵团卫视.png", "cetv1": "中国教育1台.png", "guoxue": "国学.png",
}


def logo_for(slug):
    fn = LOGO_MAP.get(str(slug) or "")
    if not fn:
        return ""
    return LOGO_BASE + urllib.parse.quote(fn)


CHANNELS = {
    "cctv1": {"name": "CCTV-1 综合", "cnlid": "2024078201", "livepid": "600001859", "defn": "fhd"},
    "cctv2": {"name": "CCTV-2 财经", "cnlid": "2024075401", "livepid": "600001800", "defn": "fhd"},
    "cctv3": {"name": "CCTV-3 综艺", "cnlid": "2024068501", "livepid": "600001801", "defn": "fhd"},
    "cctv4": {"name": "CCTV-4 中文国际", "cnlid": "2029797101", "livepid": "600001814", "defn": "fhd"},
    "cctv5": {"name": "CCTV-5 体育", "cnlid": "2024078401", "livepid": "600001818", "defn": "fhd"},
    "cctv5p": {"name": "CCTV-5+ 体育赛事", "cnlid": "2024078001", "livepid": "600001817", "defn": "fhd"},
    "cctv6": {"name": "CCTV-6 电影", "cnlid": "2013693901", "livepid": "600108442", "defn": "fhd"},
    "cctv7": {"name": "CCTV-7 国防军事", "cnlid": "2024072001", "livepid": "600004092", "defn": "fhd"},
    "cctv8": {"name": "CCTV-8 电视剧", "cnlid": "2029793001", "livepid": "600001803", "defn": "fhd"},
    "cctv9": {"name": "CCTV-9 纪录", "cnlid": "2024078601", "livepid": "600004078", "defn": "fhd"},
    "cctv10": {"name": "CCTV-10 科教", "cnlid": "2024078701", "livepid": "600001805", "defn": "fhd"},
    "cctv11": {"name": "CCTV-11 戏曲", "cnlid": "2027248701", "livepid": "600001806", "defn": "fhd"},
    "cctv12": {"name": "CCTV-12 社会与法", "cnlid": "2027248801", "livepid": "600001807", "defn": "fhd"},
    "cctv13": {"name": "CCTV-13 新闻", "cnlid": "2029797201", "livepid": "600001811", "defn": "fhd"},
    "cctv14": {"name": "CCTV-14 少儿", "cnlid": "2027248901", "livepid": "600001809", "defn": "fhd"},
    "cctv15": {"name": "CCTV-15 音乐", "cnlid": "2027249001", "livepid": "600001815", "defn": "fhd"},
    "cctv16": {"name": "CCTV-16 奥林匹克", "cnlid": "2027249101", "livepid": "600098637", "defn": "fhd"},
    "cctv164k": {"name": "CCTV-16 4K", "cnlid": "2027249301", "livepid": "600099502", "defn": "fhd"},
    "cctv17": {"name": "CCTV-17 农业农村", "cnlid": "2027249401", "livepid": "600001810", "defn": "fhd"},
    "cctv4k": {"name": "CCTV-4K 超高清", "cnlid": "2029810301", "livepid": "600002264", "defn": "fhd"},
    "cctv8k": {"name": "CCTV-8K 超高清", "cnlid": "2026774101", "livepid": "600156816", "defn": "fhd"},
    "cgtn": {"name": "CGTN", "cnlid": "2024181701", "livepid": "600014550", "defn": "fhd"},
    "cgtnfr": {"name": "CGTN 法语", "cnlid": "2024181801", "livepid": "600084704", "defn": "fhd"},
    "cgtnru": {"name": "CGTN 俄语", "cnlid": "2024181901", "livepid": "600084758", "defn": "fhd"},
    "cgtnar": {"name": "CGTN 阿拉伯语", "cnlid": "2024182001", "livepid": "600084782", "defn": "fhd"},
    "cgtnes": {"name": "CGTN 西班牙语", "cnlid": "2024182101", "livepid": "600084744", "defn": "fhd"},
    "cgtndoc": {"name": "CGTN 纪录", "cnlid": "2024182301", "livepid": "600084781", "defn": "fhd"},
    "fyjc": {"name": "CCTV 风云剧场", "cnlid": "2025637102", "livepid": "600099658", "defn": "shd"},
    "dyjc": {"name": "CCTV 第一剧场", "cnlid": "2026874202", "livepid": "600099655", "defn": "shd"},
    "hjjc": {"name": "CCTV 怀旧剧场", "cnlid": "2026874302", "livepid": "600099620", "defn": "shd"},
    "bjws": {"name": "北京卫视", "cnlid": "2024052703", "livepid": "600002309", "defn": "fhd"},
    "jsws": {"name": "江苏卫视", "cnlid": "2024171103", "livepid": "600002521", "defn": "fhd"},
    "dfws": {"name": "东方卫视", "cnlid": "2024054503", "livepid": "600002483", "defn": "fhd"},
    "zjws": {"name": "浙江卫视", "cnlid": "2024054703", "livepid": "600002520", "defn": "fhd"},
    "hnws": {"name": "湖南卫视", "cnlid": "2024054803", "livepid": "600002475", "defn": "fhd"},
    "hbws": {"name": "湖北卫视", "cnlid": "2024171203", "livepid": "600002508", "defn": "fhd"},
    "gdws": {"name": "广东卫视", "cnlid": "2024060903", "livepid": "600002485", "defn": "fhd"},
    "gxws": {"name": "广西卫视", "cnlid": "2024060703", "livepid": "600002509", "defn": "fhd"},
    "hljws": {"name": "黑龙江卫视", "cnlid": "2029797003", "livepid": "600002498", "defn": "fhd"},
    "hainanws": {"name": "海南卫视", "cnlid": "2024055603", "livepid": "600002506", "defn": "fhd"},
    "cqws": {"name": "重庆卫视", "cnlid": "2024061103", "livepid": "600002531", "defn": "fhd"},
    "szws": {"name": "深圳卫视", "cnlid": "2024061303", "livepid": "600002481", "defn": "fhd"},
    "scws": {"name": "四川卫视", "cnlid": "2024061403", "livepid": "600002516", "defn": "fhd"},
    "henanws": {"name": "河南卫视", "cnlid": "2029797303", "livepid": "600002525", "defn": "fhd"},
    "dnws": {"name": "东南卫视", "cnlid": "2024061503", "livepid": "600002484", "defn": "fhd"},
    "gzws": {"name": "贵州卫视", "cnlid": "2024061603", "livepid": "600002490", "defn": "fhd"},
    "jxws": {"name": "江西卫视", "cnlid": "2024061703", "livepid": "600002503", "defn": "fhd"},
    "lnws": {"name": "辽宁卫视", "cnlid": "2024171303", "livepid": "600002505", "defn": "fhd"},
    "ahws": {"name": "安徽卫视", "cnlid": "2024171403", "livepid": "600002532", "defn": "fhd"},
    "hebws": {"name": "河北卫视", "cnlid": "2024171503", "livepid": "600002493", "defn": "fhd"},
    "sdws": {"name": "山东卫视", "cnlid": "2029787903", "livepid": "600002513", "defn": "fhd"},
    "tjws": {"name": "天津卫视", "cnlid": "2019927003", "livepid": "600152137", "defn": "fhd"},
    "jlws": {"name": "吉林卫视", "cnlid": "2025561503", "livepid": "600190405", "defn": "fhd"},
    "saxws": {"name": "陕西卫视", "cnlid": "2029795103", "livepid": "600190400", "defn": "fhd"},
    "nxws": {"name": "宁夏卫视", "cnlid": "2025608503", "livepid": "600190737", "defn": "fhd"},
    "nmgws": {"name": "内蒙古卫视", "cnlid": "2025561203", "livepid": "600190401", "defn": "fhd"},
    "ynws": {"name": "云南卫视", "cnlid": "2025561303", "livepid": "600190402", "defn": "fhd"},
    "shanxiws": {"name": "山西卫视", "cnlid": "2025560803", "livepid": "600190407", "defn": "fhd"},
    "gsws": {"name": "甘肃卫视", "cnlid": "2025561703", "livepid": "600190408", "defn": "fhd"},
    "qhws": {"name": "青海卫视", "cnlid": "2025559103", "livepid": "600190406", "defn": "fhd"},
    "xizangws": {"name": "西藏卫视", "cnlid": "2025558003", "livepid": "600190403", "defn": "fhd"},
    "xjws": {"name": "新疆卫视", "cnlid": "2019927403", "livepid": "600152138", "defn": "fhd"},
    "cetv1": {"name": "中国教育电视台1频道", "cnlid": "2022823801", "livepid": "600171827", "defn": "fhd"},
    "guoxue": {"name": "国学频道", "cnlid": "2029360403", "livepid": "600213139", "defn": "fhd"},
    "btws": {"name": "兵团卫视", "cnlid": "2025990501", "livepid": "600193252", "defn": "fhd"},
}

def _android_abi():
    """返回当前设备对应的 Rust target 三元组，用于在 tar 包中选择二进制。
        aarch64-linux-android
        armv7-linux-androideabi
        i686-linux-android
        x86_64-linux-android
    无法识别时默认返回 aarch64。
    """
    machine = ""
    try:
        machine = platform.machine().lower()
    except Exception:
        pass

    if machine in ("aarch64", "arm64", "arm64-v8a", "armv8a"):
        return "aarch64-linux-android"
    if machine.startswith("arm"):
        # armv7l / armv8l / armeabi-v7a / armeabi
        return "armv7-linux-androideabi"
    if machine in ("i386", "i486", "i586", "i686", "x86", "ia32"):
        return "i686-linux-android"
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64-linux-android"
    return "aarch64-linux-android"

def _is_tar_path(path):
    """判断路径是否是 tar 包（.tar.gz / .tgz / .tar）。"""
    lowered = str(path or "").lower().split("?", 1)[0]
    return lowered.endswith((".tar.gz", ".tgz", ".tar"))

def _is_writable_dir(path):
    """通过实际创建临时文件来验证目录是否可写。"""
    if not path or not os.path.isdir(path):
        return False
    probe = os.path.join(path, ".ysp-write-test-{}".format(os.getpid()))
    try:
        with open(probe, "wb") as f:
            f.write(b"ok")
        os.remove(probe)
        return True
    except Exception:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except Exception:
            pass
        return False

# ============================================================
# 签名
# ============================================================
def _md5(value):
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _canonical_query(params):
    return "&".join("{}={}".format(k, params[k]) for k in sorted(params))


def _signature(params, salt):
    return _md5(_canonical_query(params) + salt)


def _random_text(length=10):
    alphabet = "ABCDEFGHIJKlMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(random.choice(alphabet) for _ in range(length))


def _ticket_fallback(pid, timestamp, guid):
    """旧版简单 XOR ticket，仅在 helper 不可用或 ticket 调用失败时兜底。"""
    payload = "{}&{}&{}&{}&{}".format(
        pid, timestamp, guid, YSP_APP_ID, TICKET_SUFFIX,
    ).encode("utf-8")
    if len(payload) > len(TICKET_KEYSTREAM):
        raise ValueError("无效的 ticket 载荷")
    return bytes(v ^ TICKET_KEYSTREAM[i] for i, v in enumerate(payload)).hex()


# ============================================================
# ysp-helper RPC
# ============================================================
CMD_KEYGEN_RND = 0x01
CMD_KEYGEN_SIGN = 0x02
CMD_TICKET = 0x03
CMD_DECRYPT_TS = 0x04
CMD_PING = 0x05

STATUS_OK = 0x00
STATUS_ERROR = 0x01


class YspHelperError(RuntimeError):
    pass


class YspHelper:
    def __init__(self, binary_path):
        self.binary = binary_path
        self.proc = None
        self.lock = threading.RLock()

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            [self.binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def stop(self):
        with self.lock:
            if not self.proc:
                return
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            finally:
                self.proc = None

    def _ensure_alive(self):
        if not self.proc or self.proc.poll() is not None:
            self.start()

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.proc.stdout.read(n - len(buf))
            if not chunk:
                raise YspHelperError("ysp-helper 已关闭 stdout")
            buf += chunk
        return buf

    def _call(self, cmd, payload):
        with self.lock:
            self._ensure_alive()
            frame = bytes([cmd]) + payload
            self.proc.stdin.write(struct.pack("<I", len(frame)))
            self.proc.stdin.write(frame)
            self.proc.stdin.flush()

            len_buf = self._read_exact(4)
            length = struct.unpack("<I", len_buf)[0]
            if length < 1:
                raise YspHelperError("响应为空")
            body = self._read_exact(length)
            status = body[0]
            data = body[1:]
            if status != STATUS_OK:
                raise YspHelperError(data.decode("utf-8", "replace"))
            return data

    def ping(self):
        return self._call(CMD_PING, b"")

    def keygen_rnd(self, guid, ts):
        req = json.dumps({"guid": guid, "ts": ts}).encode("utf-8")
        return self._call(CMD_KEYGEN_RND, req).decode("utf-8")

    def keygen_sign(self, guid, token, input_, ts):
        req = json.dumps({
            "guid": guid, "token": token, "input": input_, "ts": ts,
        }).encode("utf-8")
        return self._call(CMD_KEYGEN_SIGN, req).decode("utf-8")

    def ticket(self, pid, auth_ts, cnlid, guid):
        req = json.dumps({
            "pid": pid, "auth_ts": auth_ts, "cnlid": cnlid, "guid": guid,
        }).encode("utf-8")
        return self._call(CMD_TICKET, req).decode("utf-8")

    def decrypt_ts(self, cache_key, page_url, raw_ts, sequence=None):
        def blob(b):
            if isinstance(b, str):
                b = b.encode("utf-8")
            return struct.pack("<I", len(b)) + b
        payload = blob(cache_key) + blob(page_url) + blob(raw_ts)
        if sequence is not None:
            payload += blob(str(sequence))
        return self._call(CMD_DECRYPT_TS, payload)


# ============================================================
# 会话
# ============================================================
class _Session:
    def __init__(self, guid):
        self.guid = guid
        self.cookie = self._cookie(guid)
        self.opener = _OPENER

    def request(self, url, headers=None, deadline=None, data=None,
        method=None, stage="网络请求", cap=HTTP_TIMEOUT):
        merged = dict(headers or {})
        merged.setdefault("Cookie", self.cookie)
        return _http(self.opener, url, merged, deadline=deadline,
            data=data, method=method, stage=stage, cap=cap)

    @staticmethod
    def _cookie(guid):
        cookies = {
            "guid": guid, "versionName": "99.99.99", "versionCode": "999999",
            "vplatform": "109", "platformVersion": "Chrome",
            "deviceModel": "148", "newLogin": "1", "nseqId": "1",
        }
        return "; ".join("{}={}".format(k, v) for k, v in cookies.items())


# ============================================================
# 播放接口
# ============================================================
class _PlayerApi:

    def __init__(self, helper):
        self.helper = helper

    def resolve(self, pid, cnlid, deadline, defn="fhd"):
        guid = "{}_{}".format(self._base36(int(time.time() * 1000)),
            _random_text(11))
        session = _Session(guid)
        auth = self._auth(session, pid, guid, deadline)

        timestamp = str(int(time.time() + 0.5))
        params = {
            "cnlid": cnlid, "livepid": pid, "stream": "2",
            "guid": guid, "cKey": self._ckey(cnlid, timestamp, guid),
            "adjust": 1, "sphttps": "1", "platform": PLATFORM,
            "cmd": "2", "encryptVer": "8.1", "dtype": "1", "devid": "devid",
            "otype": "ojson", "appVer": APP_VERSION, "app_version": APP_VERSION,
            "channel": "ysp_tx", "defn": defn,
        }
        headers = self._sdk_headers(session, guid, params, deadline)
        headers["yspPlayerToken"] = str(auth["token"])

        try:
            headers["yspticket"] = self.helper.ticket(
                pid, str(auth["ts"]), cnlid, guid
            )
        except Exception as e:
            _log("helper.ticket 失败，使用兜底方案: {}".format(e))
            headers["yspticket"] = _ticket_fallback(
                pid, str(auth["ts"]), guid
            )

        params["rand_str"] = _random_text()
        params["signature"] = _signature(params, REQUEST_SALT)

        _log("resolve: guid={} ckey_head={}".format(guid, params["cKey"][:16]))

        _status, raw = session.request(
            PLAYER_URL + "get_live_info", headers,
            deadline=deadline, stage="取得播放信息",
            data=json.dumps(params, separators=(",", ":")).encode("utf-8"),
            method="POST",
        )
        text = raw.decode("utf-8", "replace")
        _log("live_info: 响应体={}".format(text[:400]))

        try:
            result = json.loads(text)
        except Exception as e:
            raise _ProxyError(502, "live_info 解析失败: {} | 响应体={}".format(
                e, text[:300])) from None

        top_msg = str(result.get("msg") or "")
        if result.get("code") != 0:
            if _is_copyright_msg(top_msg):
                _log("版权受限（顶层消息）: {}".format(top_msg))
                raise _CopyrightError(top_msg)
            raise _ProxyError(502, "live_info 被拒绝 code={} msg={} 响应体={}".format(
                result.get("code"), top_msg, text[:300]))

        data = result.get("data") or {}
        errinfo = str(data.get("errinfo") or "")
        iretcode = data.get("iretcode")

        if errinfo and _is_copyright_msg(errinfo):
            _log("版权受限（data.errinfo）: {}".format(errinfo))
            raise _CopyrightError(errinfo)

        if iretcode not in (None, 0):
            raise _ProxyError(502, "live_info iretcode={} errinfo={}".format(
                iretcode, errinfo))

        candidates = data.get("backurl_list") or []
        locations = [item.get("url") for item in candidates if isinstance(item, dict)]
        locations.append(data.get("playurl"))
        for location in locations:
            if isinstance(location, str) and location.startswith("https://"):
                return location
        raise _ProxyError(502, "live_info 缺少 hls manifest，响应体={}".format(
            text[:300]))

    def _auth(self, session, pid, guid, deadline):
        params = {
            "pid": pid, "guid": guid, "appid": "ysp_pc",
            "rand_str": _random_text(),
        }
        params["signature"] = _signature(params, AUTH_SALT)
        headers = self._headers({
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        })
        _status, raw = session.request(
            PLAYER_URL + "auth", headers,
            deadline=deadline, stage="播放授权",
            data=urllib.parse.urlencode(params).encode("utf-8"),
            method="POST",
        )
        text = raw.decode("utf-8", "replace")
        _log("auth: 响应体={}".format(text[:400]))

        try:
            result = json.loads(text)
        except Exception as e:
            raise _ProxyError(502, "auth 解析失败: {} | 响应体={}".format(
                e, text[:300])) from None

        data = result.get("data") or {}
        if result.get("code") != 0 or not data.get("token") or not data.get("ts"):
            raise _ProxyError(502, "auth 被拒绝 code={} msg={} 响应体={}".format(
                result.get("code"), result.get("msg"), text[:300]))
        return data

    def _sdk_headers(self, session, guid, params, deadline):
        sdk_input = _md5(_canonical_query(params))
        sequence = "1"
        request_id = "999999{}{}".format(_random_text(), int(time.time() * 1000))
        composite = "{}-{}-{}-{}".format(sdk_input, guid, sequence, request_id)

        state_ts = str(int(time.time() * 1000))
        token_random = self.helper.keygen_rnd(guid=guid, ts=state_ts)

        query = {
            "yspappid": YSP_APP_ID, "guid": guid,
            "vappid": OPEN_VAPP_ID, "vsecret": OPEN_VSECRET,
            "raw": 1, "version": "v1",
            "ts": state_ts, "rnd": token_random,
        }
        _status, raw = session.request(
            OPEN_TOKEN_URL + "?" + urllib.parse.urlencode(query),
            self._headers(), deadline=deadline, stage="签名授权", method="GET",
        )
        text = raw.decode("utf-8", "replace")
        _log("open_token: 响应体={}".format(text[:300]))

        try:
            result = json.loads(text)
        except Exception as e:
            raise _ProxyError(502, "open_token 解析失败: {} | 响应体={}".format(
                e, text[:300])) from None
        data = result.get("data") or {}
        if not data.get("token"):
            raise _ProxyError(502, "open_token 被拒绝 msg={} 响应体={}".format(
                result.get("msg"), text[:300]))

        sdk_signature = self.helper.keygen_sign(
            guid=guid, token=data["token"], input_=composite, ts=state_ts,
        ) + "-" + composite

        headers = self._headers()
        headers.update({
            "Content-Type": "application/json;charset=UTF-8",
            "yspsdkinput": sdk_input,
            "yspsdksign": sdk_signature,
            "seqId": sequence,
            "request-id": request_id,
            "yspappid": YSP_APP_ID,
        })
        return headers

    @staticmethod
    def _ckey(cnlid, timestamp, guid):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
        except ImportError:
            raise _ProxyError(500, "需要 pycryptodome: pip install pycryptodome")
        raw = (
            "|{}|{}|mg3c3b04ba|{}|{}|{}|https://www.yangshipin.c|"
            "mozilla/5.0 (windows nt ||Mozilla|Netscape|Win32|"
        ).format(cnlid, timestamp, APP_VERSION, guid, PLATFORM)
        value = 0
        for ch in raw:
            value = ((value << 5) - value + ord(ch)) & 0xFFFFFFFF
        if value >= 0x80000000:
            value -= 0x100000000
        source = ("|{}{}".format(value, raw)).encode("utf-8")
        cipher = AES.new(
            bytes.fromhex("48e5918a74ae21c972b90cce8af6c8be"),
            AES.MODE_CBC,
            bytes.fromhex("9a7e7d23610266b1d9fbf98581384d92"),
        )
        return "--01" + cipher.encrypt(pad(source, 16)).hex().upper()

    @staticmethod
    def _headers(extra=None):
        base = {
            "Origin": HOST,
            "Referer": HOST + "/",
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "sec-ch-ua": '"Chromium";v="148", "Not=A?Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "yspappid": YSP_APP_ID,
        }
        if extra:
            base.update(extra)
        return base

    @staticmethod
    def _base36(value):
        alphabet = string.digits + string.ascii_lowercase
        result = ""
        while value:
            value, rem = divmod(value, 36)
            result = alphabet[rem] + result
        return result or "0"


# ============================================================
# m3u8 解析
# ============================================================
def _sid_for_url(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def _parse_m3u8(text, base_url):
    if base_url.endswith("/"):
        base = base_url
    else:
        base = base_url.rsplit("/", 1)[0] + "/"
    media_seq = 0
    duration = 5.0
    last_pdt = None
    out = []
    idx = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_seq = int(line.split(":", 1)[1].strip())
            except Exception:
                pass
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            last_pdt = line.split(":", 1)[1].strip()
        elif line.startswith("#EXTINF:"):
            try:
                duration = float(line[8:].split(",")[0])
            except Exception:
                duration = 5.0
        elif line.startswith("#"):
            continue
        elif ".m3u8" in line:
            url = line if line.startswith("http") else urllib.parse.urljoin(base_url, line)
            out.append(("__playlist__", url, duration, media_seq + idx, None))
            idx += 1
        else:
            url = line if line.startswith("http") else base + line
            sid = _sid_for_url(url)
            out.append((sid, url, duration, media_seq + idx, last_pdt))
            idx += 1
    return out


def _split_m3u8(parsed):
    segs = [x for x in parsed if x[0] != "__playlist__"]
    pls = [x[1] for x in parsed if x[0] == "__playlist__"]
    return segs, pls


def _fetch_m3u8_with_headers(url):
    timeout = M3U8_TIMEOUT
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Referer": HOST + "/",
        "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, */*",
    })
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.geturl()


def _resolve_hls_segments(hls_url, depth=0):
    if depth > 3:
        _log("resolve_hls: 达到深度限制 {}".format(hls_url))
        return []
    try:
        text, final_url = _fetch_m3u8_with_headers(hls_url)
    except _ProxyError as e:
        _log("resolve_hls 拉取失败: {} -> {}".format(hls_url, e))
        return []
    except Exception as e:
        _log("resolve_hls 拉取失败: {} -> {}: {}".format(
            hls_url, type(e).__name__, e))
        return []
    parsed = _parse_m3u8(text, final_url)
    segs, pls = _split_m3u8(parsed)
    if segs:
        _log("resolve_hls 成功: {} 分片数={}".format(hls_url[:80], len(segs)))
        return segs
    if pls:
        _log("resolve_hls: 主播放列表，{} 个子列表".format(len(pls)))
        return _resolve_hls_segments(pls[-1], depth + 1)
    _log("resolve_hls: 空播放列表: {}".format(hls_url[:120]))
    return []


# ============================================================
# 段缓存 / 状态
# ============================================================
_SEG_LOCK = threading.Lock()
_SEGS = {}
_PROCESSED = {}
_LAST_SEQ = {}

# per-slug 锁：串行化同一频道的 segment 请求，避免 CMG 状态被并发交错推进
_SEGMENT_LOCKS = {}
_SEGMENT_LOCKS_GUARD = threading.Lock()


def _channel_lock(slug):
    with _SEGMENT_LOCKS_GUARD:
        lock = _SEGMENT_LOCKS.get(slug)
        if lock is None:
            lock = threading.Lock()
            _SEGMENT_LOCKS[slug] = lock
        return lock


def _prune_processed_locked():
    now = time.monotonic()
    # 先按 TTL 淘汰过期条目
    expired = [
        key for key, (_, stored_at) in _PROCESSED.items()
        if now - stored_at > PROCESSED_TTL_SECONDS
    ]
    for key in expired:
        _PROCESSED.pop(key, None)
    if len(_PROCESSED) <= PROCESSED_MAX:
        return
    # 再按最近写入时间淘汰，保留最新
    excess = len(_PROCESSED) - PROCESSED_MAX
    oldest = sorted(_PROCESSED.items(), key=lambda item: item[1][1])
    for key, _ in oldest[:excess]:
        _PROCESSED.pop(key, None)


# ============================================================
# 本地 HTTP 代理
# ============================================================
class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    spider = None

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        try:
            _log("send_error: {} {}".format(code, message or ""))
        except Exception:
            pass
        try:
            super().send_error(code, message, explain)
        except Exception:
            pass

    def _safe_write(self, data):
        try:
            self.wfile.write(data)
        except Exception as e:
            if _is_client_disconnect(e):
                _log("写入时客户端断开连接（{} 字节）".format(len(data)))
            else:
                raise

    def do_HEAD(self):
        try:
            if self.path.startswith("/live/"):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", "0")
                self.send_header("Accept-Ranges", "none")
                self.end_headers()
            elif self.path.startswith("/segment/"):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp2t")
                self.send_header("Content-Length", "0")
                self.send_header("Accept-Ranges", "none")
                self.end_headers()
            elif self.path.startswith("/blocked/"):
                self.send_response(451, "Restricted")
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            else:
                self.send_error(404)
        except Exception as e:
            if not _is_client_disconnect(e):
                _log("do_HEAD 异常: {}".format(e))

    def do_GET(self):
        try:
            if self.path.startswith("/live/"):
                self._handle_playlist()
            elif self.path.startswith("/segment/"):
                self._handle_segment()
            elif self.path.startswith("/blocked/"):
                self._handle_blocked()
            else:
                self.send_error(404)
        except _CopyrightError as e:
            _log("代理版权错误: {} ({})".format(e, self.path[:120]))
            try:
                self._send_plain_error(e.status, str(e))
            except Exception:
                pass
        except _ProxyError as e:
            _log("代理错误: {} {} ({})".format(e.status, e, self.path[:120]))
            try:
                self._send_plain_error(e.status, str(e))
            except Exception:
                pass
        except Exception as e:
            if _is_client_disconnect(e):
                _log("客户端断开连接: {}".format(self.path[:80]))
                return
            _log("代理处理器异常: {}: {}".format(type(e).__name__, e))
            try:
                self.send_error(500, "handler_error")
            except Exception:
                pass

    def _send_plain_error(self, status, message):
        """用纯文本 body 回错误，避免 HTML 错误页；直播播放器更容易带上原文。"""
        text = str(message or "error")
        body = text.encode("utf-8")
        # reason 仅允许 latin-1，中文放 body
        try:
            self.send_response(status, "Restricted")
        except Exception:
            self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Ysp-Error", text[:200])
        self.end_headers()
        self._safe_write(body)

    def _handle_blocked(self):
        """直播模式：已判定版权/区域限制的频道，直接回限制文案，不再取流。"""
        slug = self.path.rsplit("/", 1)[-1].split("?", 1)[0]
        meta = CHANNELS.get(slug)
        if not meta:
            raise _ProxyError(404, "未找到频道")
        key = "{}:{}".format(meta["livepid"], meta["cnlid"])
        msg = "应版权方要求，暂无法提供此频道"
        spider = self.spider
        if spider is not None:
            with spider._cache_lock:
                cached = spider._copyright_cache.get(key)
                if cached is not None:
                    message, expiry = cached
                    if expiry > time.monotonic():
                        msg = message
        raise _CopyrightError(msg)

    def _handle_playlist(self):
        slug = self.path.rsplit("/", 1)[-1].replace(".m3u8", "")
        meta = CHANNELS.get(slug)
        if not meta:
            raise _ProxyError(404, "未找到频道")

        deadline = time.monotonic() + PLAYER_BUDGET
        try:
            hls_url = self.spider._resolve(
                meta["livepid"], meta["cnlid"], meta.get("defn", "fhd"), deadline)
        except _CopyrightError as e:
            # 版权/区域限制：清掉该频道分片缓存，避免播放器继续拉旧 segment
            _log("playlist: 版权/区域限制 slug={} err={}".format(slug, e))
            with _SEG_LOCK:
                for k in [k for k in list(_SEGS) if k[0] == slug]:
                    _SEGS.pop(k, None)
                    _PROCESSED.pop(k, None)
                _LAST_SEQ.pop(slug, None)
            raise
        except _ProxyError as e:
            _log("playlist: _resolve 失败 slug={} err={}".format(slug, e))
            raise

        _log("playlist: {} 上游地址={}".format(slug, hls_url[:120]))

        segs = _resolve_hls_segments(hls_url)
        if not segs:
            raise _ProxyError(502, "无可用分片")

        with _SEG_LOCK:
            for sid, url, dur, seq, pdt in segs:
                _SEGS[(slug, sid)] = {
                    "url": url, "duration": dur, "sequence": seq, "pdt": pdt,
                }
            keys = [k for k in _SEGS if k[0] == slug]
            if len(keys) > SEG_CACHE_HARD_CAP:
                # 按 sequence 排序后再裁剪，避免误删最新分片
                entries = [(k, _SEGS[k]) for k in keys]
                entries.sort(key=lambda kv: kv[1].get("sequence", 0))
                remove_count = len(entries) - SEG_CACHE_KEEP
                for k, _ in entries[:remove_count]:
                    _SEGS.pop(k, None)
                    _PROCESSED.pop(k, None)

        base = "http://127.0.0.1:{}/".format(self.spider._port)
        durations = [d for _s, _u, d, _q, _p in segs if d > 0]
        target = max(1, int(max(durations) + 0.999)) if durations else 6

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            "#EXT-X-ALLOW-CACHE:NO",
            "#EXT-X-TARGETDURATION:{}".format(target),
            "#EXT-X-MEDIA-SEQUENCE:{}".format(segs[0][3]),
        ]
        for sid, _url, dur, _seq, pdt in segs:
            if pdt:
                lines.append("#EXT-X-PROGRAM-DATE-TIME:{}".format(pdt))
            lines.append("#EXTINF:{:.3f},".format(dur if dur > 0 else 5.0))
            lines.append(base + "segment/{}/{}.ts".format(slug, sid))
        body = ("\n".join(lines) + "\n").encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        self._safe_write(body)

    def _handle_segment(self):
        parts = self.path.split("/")
        if len(parts) < 4:
            raise _ProxyError(404, "无效的分片路径")
        slug = parts[2]
        sid = parts[3].replace(".ts", "")

        meta = CHANNELS.get(slug)
        if not meta:
            raise _ProxyError(404, "未找到频道")

        # 直通频道：直接代理上游分片，不做预解密 / CMG 解密
        if slug in PASSTHROUGH_SLUGS:
            self._handle_passthrough_segment(slug, sid)
            return

        # 先查缓存，拿到 sequence 用于后续序列判断
        with _SEG_LOCK:
            info = _SEGS.get((slug, sid))
            if not info:
                _log("分片未命中: {} {}".format(slug, sid[:12]))
                raise _ProxyError(404, "分片不在缓存中")
            sequence = info.get("sequence") if isinstance(info, dict) else None
            if sequence is None:
                raise _ProxyError(500, "分片序号未知")
            cached = _PROCESSED.get((slug, sid))

        if cached is not None:
            _log("分片缓存命中: {} {} seq={}".format(
                slug, sid[:12], sequence))
            self._write_segment(cached[0])
            return

        # 串行化同一频道的 segment 处理
        lock = _channel_lock(slug)
        with lock:
            with _SEG_LOCK:
                cached = _PROCESSED.get((slug, sid))
                last_seq = _LAST_SEQ.get(slug)

            if cached is not None:
                self._write_segment(cached[0])
                return

            if last_seq is not None and sequence < last_seq:
                raise _ProxyError(
                    409,
                    "分片 seq={} 早于运行时 seq={} 且未被缓存".format(
                        sequence, last_seq),
                )

            # 预解密连续前驱
            if ENABLE_PREDECRYPT:
                self._decrypt_predecessors(slug, meta, sequence)

            # 解密当前 segment
            plain = self._decrypt_one(slug, sid, meta, sequence)

        self._write_segment(plain)

    def _handle_passthrough_segment(self, slug, sid):
        """直通：按上游 m3u8 里登记的 URL 拉取原始分片并原样返回。"""
        with _SEG_LOCK:
            info = _SEGS.get((slug, sid))
            if not info:
                _log("分片未命中（直通）: {} {}".format(slug, sid[:12]))
                raise _ProxyError(404, "分片不在缓存中")
            seg_url = info["url"] if isinstance(info, dict) else info

        deadline = time.monotonic() + SEGMENT_BUDGET
        raw = self._fetch_segment(seg_url, deadline)
        _log("分片直通: {} {} {} 字节".format(
            slug, sid[:12], len(raw)))
        self._write_segment(raw)

    def _decrypt_one(self, slug, sid, meta, sequence):
        """下载并解密单个 segment；写入 _PROCESSED / _LAST_SEQ。"""
        with _SEG_LOCK:
            cached = _PROCESSED.get((slug, sid))
            if cached is not None:
                return cached[0]
            info = _SEGS.get((slug, sid))
            if not info:
                raise _ProxyError(404, "分片不在缓存中")
            seg_url = info["url"] if isinstance(info, dict) else info

        deadline = time.monotonic() + SEGMENT_BUDGET
        raw = self._fetch_segment(seg_url, deadline)
        _log("分片下载成功: {} seq={} {} 字节".format(
            sid[:12], sequence, len(raw)))

        if self.spider.helper is None:
            raise _ProxyError(500, "helper 未启动")

        page_url = "https://www.yangshipin.cn/tv/home?pid={}".format(
            meta["livepid"])
        t0 = time.time()
        try:
            plain = self.spider.helper.decrypt_ts(
                cache_key=meta["livepid"],
                page_url=page_url,
                raw_ts=raw,
                sequence=sequence,
            )
        except YspHelperError as e:
            raise _ProxyError(502, "解密失败: {}".format(e)) from None
        except _ProxyError:
            raise
        except Exception as e:
            raise _ProxyError(500, "解密异常: {}: {}".format(
                type(e).__name__, e)) from None
        finally:
            del raw

        cost_ms = int((time.time() - t0) * 1000)
        _log("分片成功: {} seq={} -> {} 字节 ({}ms)".format(
            sid[:12], sequence, len(plain), cost_ms))

        with _SEG_LOCK:
            _PROCESSED[(slug, sid)] = (plain, time.monotonic())
            _LAST_SEQ[slug] = sequence
            _prune_processed_locked()

        return plain

    def _decrypt_predecessors(self, slug, meta, current_seq):
        """与 Rust media.rs::process_segment 的前序补齐逻辑对齐。

        - last_seq is None              : 从 current_seq-1 向前取连续前驱（最多 PREDECRYPT_MAX 个）
        - current_seq <= last_seq + 1   : 无 gap，无需预解密
        - current_seq >  last_seq + 1   : 检查 last_seq+1 .. current_seq-1 是否全部可用
                                          - 全部可用且长度 <= PREDECRYPT_MAX : 按顺序预解密
                                          - 否则留给 helper 触发 runtime reset
        """
        if self.spider.helper is None:
            return

        with _SEG_LOCK:
            last_seq = _LAST_SEQ.get(slug)
            by_seq = {}
            for (s, sid), info in _SEGS.items():
                if s != slug:
                    continue
                if not isinstance(info, dict):
                    continue
                seq = info.get("sequence")
                if seq is None or seq >= current_seq:
                    continue
                if (s, sid) in _PROCESSED:
                    continue
                by_seq[seq] = sid

        to_process = []

        if last_seq is None:
            expected = current_seq - 1
            while expected in by_seq and len(to_process) < PREDECRYPT_MAX:
                to_process.append((expected, by_seq[expected]))
                expected -= 1
            to_process.reverse()
        elif current_seq <= last_seq + 1:
            return
        else:
            gap = current_seq - last_seq - 1
            if gap > PREDECRYPT_MAX:
                # gap 太大，交给 helper 触发 reset
                return
            for seq in range(last_seq + 1, current_seq):
                if seq not in by_seq:
                    # 不可填补，交给 helper 触发 reset
                    return
                to_process.append((seq, by_seq[seq]))

        if not to_process:
            return

        for seq, sid in to_process:
            try:
                self._decrypt_one(slug, sid, meta, seq)
            except Exception as e:
                _log("预解密跳过: {} seq={} err={}".format(
                    sid[:12], seq, e))
                # 中断预解密；后续当前 segment 的请求会让 helper 触发 reset
                return

    def _write_segment(self, plain):
        """一次性写出。段通常 1-3MB，socket 本身有缓冲，分块只会增加 Python 开销。"""
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Content-Length", str(len(plain)))
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        self._safe_write(plain)

    def _fetch_segment(self, seg_url, deadline):
        timeout = _capped_timeout(deadline, "分片下载", 20)
        req = urllib.request.Request(seg_url, headers={
            "User-Agent": USER_AGENT, "Referer": HOST + "/",
        })
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            status = e.code if 400 <= e.code < 600 else 502
            raise _ProxyError(status, "分片下载: HTTP {}".format(e.code)) from None
        except _ProxyError:
            raise
        except Exception as e:
            raise _ProxyError(502, "分片下载: {}: {}".format(
                type(e).__name__, e)) from None


# ============================================================
# Spider
# ============================================================
class Spider(BaseSpider):

    def init(self, extend=""):
        _init_log()
        _log("=" * 40)
        _log("Spider.init 开始, ext={!r}".format(extend))

        # 重启时先清掉壳内残留的旧 ysp-helper（进程 + 落地文件/缓存目录）
        self._cleanup_stale_helpers()

        src_path = self._resolve_helper_path(extend)
        _log("解析到源路径: {}".format(src_path))
        self.helper_path = self._ensure_executable(src_path)
        _log("可执行的 helper 路径: {}".format(self.helper_path))

        self.helper = None
        self.helper_error = None
        try:
            if not self.helper_path:
                raise RuntimeError(
                    "无法定位可执行的 ysp-helper (ext={!r})".format(extend))
            self.helper = YspHelper(self.helper_path)
            self.helper.start()
            resp = self.helper.ping()
            if resp != b"pong":
                raise RuntimeError("ping 返回: {!r}".format(resp))
            _log("helper 启动成功")
        except Exception as e:
            self.helper_error = e
            self.helper = None
            _log("helper 启动失败: {}".format(e))

        self.player = None
        self.player_error = None
        self.destroyed = False
        self.player_lock = threading.RLock()
        self.player_ready = threading.Event()
        self._cache = {}
        self._copyright_cache = {}
        self._cache_lock = threading.Lock()

        handler = type("Handler", (_ProxyHandler,), {"spider": self})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._port = self._httpd.server_address[1]
        _log("代理端口: {}".format(self._port))
        threading.Thread(
            target=self._httpd.serve_forever,
            name="ysp-proxy", daemon=True,
        ).start()

        if self.helper is not None:
            threading.Thread(
                target=self._warm_player,
                name="ysp-player-warmup", daemon=True,
            ).start()
        else:
            self.player_ready.set()
            self.player_error = self.helper_error

    def _resolve_helper_path(self, extend):
        raw = str(extend or "").strip()
        if not raw:
            return self._try_same_dir()

        # 1. 本地直存路径优先；若为 tar 包，先解包再返回
        if os.path.exists(raw):
            if _is_tar_path(raw):
                return self._install_local_tar(raw)
            return raw

        # 2. 映射到本地路径
        url_prefixes = [
            "http://127.0.0.1:9978/file/",
            "http://localhost:9978/file/",
            "http://127.0.0.1:9978/",
            "http://localhost:9978/",
        ]
        for pfx in url_prefixes:
            if raw.startswith(pfx):
                relative = raw[len(pfx):].lstrip("/")
                if not relative:
                    break
                roots = [
                    "/storage/emulated/0/",
                    "/sdcard/",
                    "/storage/self/primary/",
                    "/data/data/com.layaboxhmhz.gamehmhz.okys/files/",
                    "/data/user/0/com.layaboxhmhz.gamehmhz.okys/files/",
                    "/data/data/com.fongmi.android.tv/files/",
                    "/data/user/0/com.fongmi.android.tv/files/",
                    "/data/data/com.fongmi2.android.tv/files/",
                    "/data/user/0/com.fongmi2.android.tv/files/",
                ]
                local_path = None
                for root in roots:
                    cand = os.path.join(root, relative)
                    if os.path.exists(cand):
                        local_path = cand
                        break
                if local_path is None:
                    # 未找到：把 root[0] 下的预期路径作为默认
                    local_path = os.path.join(roots[0], relative)

                if os.path.exists(local_path) and _is_tar_path(local_path):
                    # tar 包：解到可执行分区，返回解出的二进制
                    resolved = self._install_local_tar(local_path)
                    if resolved:
                        return resolved
                    # 解包失败则退化为远程下载（如果 file URL 本身可用）
                    # Fongmi 的 file API 是 HTTP 服务，走远程下载也通
                    return self._download_remote_helper(raw)
                return local_path

        # 3. 真正的远程 URL：下载后按后缀分流
        if raw.startswith("http://") or raw.startswith("https://"):
            return self._download_remote_helper(raw)

        # 4. 回退到同目录
        fallback = self._try_same_dir()
        if fallback:
            return fallback
        return raw

    def _install_local_tar(self, tar_path):
        """从本地 tar 文件安装 ysp-helper，按当前设备 ABI 选择。"""
        try:
            with open(tar_path, "rb") as f:
                data = f.read()
        except Exception as e:
            _log("本地 helper 包读取失败: {}: {}".format(type(e).__name__, e))
            return ""

        if not data:
            _log("本地 helper 包内容为空")
            return ""

        _log("本地 helper 包读取完成，共 {} 字节".format(len(data)))

        cache_id = hashlib.sha1(tar_path.encode("utf-8")).hexdigest()[:12]
        return self._install_tar_helper_bytes(data, cache_id)

    def _download_remote_helper(self, url):
        """从远程 URL 下载 ysp-helper 并落地到可执行目录。

        支持两种 URL：
          - *.tar.gz / *.tgz / *.tar：按 tar 包处理，解包后按设备 ABI 自动选择；
          - 其它：按单个 ELF 处理，原样落地。

        缓存：
          - tar 包：落地在 <cache_dir>/ysp-helper-<sha1>/<abi>/ysp-helper，
            同 URL 复用；同 URL 但换了 ABI 会重新解包到新子目录。
          - 单二进制：落地在 <cache_dir>/ysp-helper-<sha1>。

        返回可执行的本地路径，失败返回空字符串。
        """
        lowered = url.lower().split("?", 1)[0]
        is_tar = lowered.endswith((".tar.gz", ".tgz", ".tar"))

        candidates = self._helper_candidates()

        if is_tar:
            return self._download_remote_helper_tar(url, candidates)
        return self._download_remote_helper_binary(url, candidates)

    def _helper_candidates(self):
        """返回可以落地 ysp-helper 的目录候选列表。

        过滤规则：
          - 必须是可执行分区（排除 /sdcard、/storage/emulated、/mnt/sdcard）；
          - 必须可写（通过实际创建临时文件验证，排除只读分区如 /system/bin）；
        """
        raw = []

        # 1. Python 解释器所在目录（通常不可写，只作兜底）
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            if exe_dir:
                raw.append(exe_dir)
        except Exception:
            pass

        # 2. 本脚本所在目录
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here:
                raw.append(here)
        except Exception:
            pass

        # 3. 各 App 的私有 files 目录（首选落地位置）
        for pkg in ("com.layaboxhmhz.gamehmhz.okys",
            "com.fongmi.android.tv",
            "com.fongmi2.android.tv"):
            for base in (
                "/data/data/{}/files".format(pkg),
                "/data/user/0/{}/files".format(pkg),
            ):
                raw.append(base)

        # 4. 系统兜底目录（若可写）
        raw.append("/data/local/tmp")

        # 去重 + 过滤：可执行分区 + 可写
        seen = set()
        candidates = []
        for d in raw:
            if not d:
                continue
            d_abs = os.path.abspath(d)
            if d_abs in seen:
                continue
            seen.add(d_abs)
            if not self._is_exec_partition(d_abs):
                continue
            if not _is_writable_dir(d_abs):
                continue
            candidates.append(d_abs)

        return candidates

    def _download_remote_helper_tar(self, url, candidates=None):
        cache_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        abi = _android_abi()
        if candidates is None:
            candidates = self._helper_candidates()

        _log("远程 helper ABI: {}".format(abi))

        # 缓存命中
        for d in candidates:
            target = os.path.join(d, "ysp-helper-" + cache_id, abi, "ysp-helper")
            if os.path.exists(target) and self._quick_ping(target):
                _log("远程 helper 缓存命中: {}".format(target))
                return target

        # 下载
        _log("开始下载远程 helper 包: {}".format(url))
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/gzip, application/octet-stream, */*",
            })
            with _OPENER.open(req, timeout=120) as r:
                data = r.read()
        except Exception as e:
            _log("远程 helper 下载失败: {}: {}".format(type(e).__name__, e))
            return ""

        if not data:
            _log("远程 helper 包内容为空")
            return ""

        _log("远程 helper 包下载完成，共 {} 字节".format(len(data)))
        return self._install_tar_helper_bytes(data, cache_id, candidates)

    def _install_tar_helper_bytes(self, data, cache_id, candidates=None):
        """按 ABI 解包 tar 数据并落地；返回可执行路径或空字符串。"""
        abi = _android_abi()
        if candidates is None:
            candidates = self._helper_candidates()

        for d in candidates:
            if not os.path.isdir(d):
                continue
            extract_dir = os.path.join(d, "ysp-helper-" + cache_id)
            try:
                os.makedirs(extract_dir, exist_ok=True)
                if not self._extract_tar_safely(data, extract_dir):
                    continue

                target = os.path.join(extract_dir, abi, "ysp-helper")
                if not os.path.exists(target):
                    _log("helper 包内未找到 {} 对应文件".format(abi))
                    continue
                try:
                    os.chmod(target, 0o755)
                except Exception:
                    pass
                if self._quick_ping(target):
                    _log("helper 落地成功: {}".format(target))
                    return target
                _log("helper 落地后 ping 失败: {}".format(target))
            except Exception as e:
                _log("helper 解包到 {} 失败: {}: {}".format(
                    extract_dir, type(e).__name__, e))
                continue

        _log("helper 无法落地到任何可执行目录")
        return ""

    @staticmethod
    def _extract_tar_safely(data, extract_dir):
        """安全解包：拒绝绝对路径 / .. / 符号链接逃逸。

        返回 True 表示解包成功，False 表示内容有问题（跳过该候选目录）。
        """
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
                members = tar.getmembers()
                if not members:
                    return False
                extract_dir_abs = os.path.abspath(extract_dir) + os.sep
                for member in members:
                    name = member.name
                    if name.startswith("/") or name.startswith("\\"):
                        return False
                    normalized = os.path.normpath(name)
                    if normalized == ".." or normalized.startswith(".." + os.sep):
                        return False
                    # 符号链接/硬链接：只允许指向包内相对路径
                    if member.issym() or member.islnk():
                        link = member.linkname or ""
                        if link.startswith("/"):
                            return False
                        joined = os.path.normpath(
                            os.path.join(os.path.dirname(normalized), link))
                        if joined == ".." or joined.startswith(".." + os.sep):
                            return False
                        continue
                    # 普通文件/目录：确认最终落地路径没跑出 extract_dir
                    final_path = os.path.abspath(
                        os.path.join(extract_dir, normalized))
                    if not final_path.startswith(extract_dir_abs):
                        return False
                # 通过检查后再解包
                tar.extractall(extract_dir)
            return True
        except (tarfile.TarError, OSError, ValueError):
            return False

    def _download_remote_helper_binary(self, url, candidates):
        """单二进制落地路径（保留原有逻辑，供 .tar.gz 之外的 URL 使用）。"""
        cache_name = "ysp-helper-" + hashlib.sha1(
            url.encode("utf-8")).hexdigest()[:12]

        for d in candidates:
            target = os.path.join(d, cache_name)
            if os.path.exists(target) and self._quick_ping(target):
                _log("远程 helper 缓存命中: {}".format(target))
                return target

        _log("开始下载远程 helper: {}".format(url))
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/octet-stream, */*",
            })
            with _OPENER.open(req, timeout=60) as r:
                data = r.read()
        except Exception as e:
            _log("远程 helper 下载失败: {}: {}".format(type(e).__name__, e))
            return ""

        if not data:
            _log("远程 helper 内容为空")
            return ""

        _log("远程 helper 下载完成，共 {} 字节".format(len(data)))

        for d in candidates:
            if not os.path.isdir(d):
                continue
            target = os.path.join(d, cache_name)
            try:
                with open(target, "wb") as f:
                    f.write(data)
                try:
                    os.chmod(target, 0o755)
                except Exception:
                    pass
                if self._quick_ping(target):
                    _log("远程 helper 落地成功: {}".format(target))
                    return target
                _log("远程 helper 落地后 ping 失败: {}".format(target))
            except Exception as e:
                _log("远程 helper 写入 {} 失败: {}: {}".format(
                    target, type(e).__name__, e))
                continue

        _log("远程 helper 无法落地到任何可执行目录")
        return ""

    def _cleanup_stale_helpers(self):
        """重启时清除壳内旧的 ysp-helper：先杀残留进程，再删落地文件/缓存目录。

        不删除用户通过 ext 传入的源路径本身（远程下载前尚未落地；
        本地 tar/二进制源若在候选目录外也会保留）。
        """
        killed = self._kill_stale_helper_procs()
        if killed:
            _log("已终止残留 ysp-helper 进程: {}".format(killed))

        removed = []
        # 候选落地目录 + 常见私有 files（即使当前不可写也尝试列一下已存在的）
        dirs = list(self._helper_candidates())
        for pkg in ("com.layaboxhmhz.gamehmhz.okys",
            "com.fongmi.android.tv",
            "com.fongmi2.android.tv"):
            for base in (
                "/data/data/{}/files".format(pkg),
                "/data/user/0/{}/files".format(pkg),
            ):
                if base not in dirs and os.path.isdir(base):
                    dirs.append(base)
        for extra in ("/data/local/tmp",):
            if extra not in dirs and os.path.isdir(extra):
                dirs.append(extra)
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here and here not in dirs:
                dirs.append(here)
        except Exception:
            pass
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            if exe_dir and exe_dir not in dirs:
                dirs.append(exe_dir)
        except Exception:
            pass

        for d in dirs:
            if not d or not os.path.isdir(d):
                continue
            try:
                names = os.listdir(d)
            except Exception:
                continue
            for name in names:
                # ysp-helper（单文件）或 ysp-helper-<hash>（tar 解包目录）
                if name != "ysp-helper" and not name.startswith("ysp-helper-"):
                    continue
                path = os.path.join(d, name)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                        if not os.path.exists(path):
                            removed.append(path)
                    elif os.path.isfile(path):
                        os.remove(path)
                        removed.append(path)
                except Exception as e:
                    _log("清理 helper 失败 {}: {}".format(path, e))

        if removed:
            _log("已清除旧 helper 文件: {}".format(
                ", ".join(removed[:12]) + ("…" if len(removed) > 12 else "")))
        else:
            _log("无旧 helper 文件需要清除")

    @staticmethod
    def _kill_stale_helper_procs():
        """尽力终止本机残留的 ysp-helper 进程，返回终止数量。"""
        killed = 0
        my_pid = os.getpid()
        # 1) pidof
        try:
            out = subprocess.check_output(
                ["pidof", "ysp-helper"],
                stderr=subprocess.DEVNULL, timeout=3,
            ).decode("utf-8", "replace").strip()
            pids = [int(x) for x in out.split() if x.isdigit()]
        except Exception:
            pids = []

        # 2) 扫 /proc 兜底（部分设备无 pidof）
        if not pids:
            try:
                for ent in os.listdir("/proc"):
                    if not ent.isdigit():
                        continue
                    pid = int(ent)
                    if pid == my_pid:
                        continue
                    cmdline = ""
                    try:
                        with open("/proc/{}/cmdline".format(pid), "rb") as f:
                            cmdline = f.read().replace(b"\x00", b" ").decode(
                                "utf-8", "replace")
                    except Exception:
                        continue
                    if "ysp-helper" in cmdline:
                        pids.append(pid)
            except Exception:
                pass

        for pid in pids:
            if pid == my_pid:
                continue
            try:
                os.kill(pid, 9)
                killed += 1
            except Exception:
                pass
        return killed

    def _try_same_dir(self):
        try:
            here = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return ""
        for name in ("ysp-helper",):
            p = os.path.join(here, name)
            if os.path.exists(p):
                return p
        return ""

    def _ensure_executable(self, src_path):
        if not src_path or not os.path.exists(src_path):
            return ""
        if self._quick_ping(src_path):
            return src_path

        targets = []
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            if exe_dir and os.path.isdir(exe_dir) and self._is_exec_partition(exe_dir):
                targets.append(os.path.join(exe_dir, "ysp-helper"))
        except Exception:
            pass
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here and os.path.isdir(here) and self._is_exec_partition(here):
                targets.append(os.path.join(here, "ysp-helper"))
        except Exception:
            pass
        for pkg in ("com.layaboxhmhz.gamehmhz.okys", "com.fongmi.android.tv", "com.fongmi2.android.tv"):
            for base in (
                "/data/data/{}/files".format(pkg),
                "/data/user/0/{}/files".format(pkg),
            ):
                if os.path.isdir(base):
                    targets.append(os.path.join(base, "ysp-helper"))
        if os.path.isdir("/data/local/tmp"):
            targets.append("/data/local/tmp/ysp-helper")

        for dst in targets:
            try:
                dstdir = os.path.dirname(dst)
                if not os.path.isdir(dstdir):
                    continue
                if os.path.exists(dst) and self._quick_ping(dst):
                    return dst
                shutil.copyfile(src_path, dst)
                try:
                    os.chmod(dst, 0o755)
                except Exception:
                    pass
                if self._quick_ping(dst):
                    return dst
            except Exception:
                continue
        return ""

    @staticmethod
    def _is_exec_partition(path):
        p = str(path or "")
        for bad in ("/sdcard", "/storage/emulated", "/mnt/sdcard"):
            if p.startswith(bad):
                return False
        return True

    @staticmethod
    def _quick_ping(path):
        if not path or not os.path.isfile(path):
            return False
        try:
            proc = subprocess.Popen(
                [path, "ping"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                out, _err = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                return False
            return proc.returncode == 0 and out.strip() == b"pong"
        except Exception:
            return False

    def _warm_player(self):
        try:
            player = _PlayerApi(self.helper)
            with self.player_lock:
                if not self.destroyed:
                    self.player = player
            _log("预热播放器成功")
        except Exception as error:
            with self.player_lock:
                if not self.destroyed:
                    self.player_error = error
            _log("预热播放器失败: {}".format(error))
        finally:
            self.player_ready.set()

    # ---- 目录接口 ----
    def getName(self):
        return "央视频"

    def homeContent(self, filter):
        classes = [
            {"type_id": "央视", "type_name": "央视"},
            {"type_id": "卫视", "type_name": "卫视"},
            {"type_id": "CGTN", "type_name": "CGTN"},
            {"type_id": "数字", "type_name": "数字"},
        ]
        items = [self._card(s, m["name"], "央视")
            for s, m in CHANNELS.items() if self._group_of(s) == "央视"]
        return {"class": classes, "filters": {}, "list": items}

    def homeVideoContent(self):
        items = [self._card(s, m["name"], "央视")
            for s, m in CHANNELS.items() if self._group_of(s) == "央视"]
        return {"list": items}

    def categoryContent(self, tid, pg, filter, extend):
        items = [self._card(s, m["name"], tid)
            for s, m in CHANNELS.items() if self._group_of(s) == tid]
        return {
            "list": items, "page": 1, "pagecount": 1,
            "limit": max(1, len(items)), "total": len(items),
        }

    def searchContent(self, key, quick, pg="1"):
        q = str(key or "").strip().casefold()
        if not q:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 1, "total": 0}
        items = [self._card(s, m["name"], self._group_of(s))
            for s, m in CHANNELS.items()
            if q in m["name"].casefold() or q in s.casefold()]
        return {
            "list": items, "page": 1, "pagecount": 1,
            "limit": max(1, len(items)), "total": len(items),
        }

    def detailContent(self, ids):
        slug = self._strip(str(ids[0] if ids else ""))
        meta = CHANNELS.get(slug)
        if not meta:
            return {"list": [], "msg": "找不到此频道"}

        ordered = [slug] + [s for s in CHANNELS if s != slug]
        entries = [
            "{}${}".format(CHANNELS[s]["name"], "live/" + s)
            for s in ordered
        ]
        play_url = "#".join(entries)

        return {"list": [{
            "vod_id": "ch/" + slug,
            "vod_name": meta["name"],
            "vod_pic": logo_for(slug),
            "vod_remarks": self._group_of(slug),
            "type_name": self._group_of(slug),
            "vod_content": meta["name"],
            "vod_play_from": "WASM",
            "vod_play_url": play_url,
        }]}

    # ---- 直播模式 ----
    def liveContent(self, url):
        groups = OrderedDict()
        for number, (slug, meta) in enumerate(CHANNELS.items(), 1):
            group = GROUP_NAMES.get(self._group_of(slug), "其他频道")
            groups.setdefault(group, []).append(
                self._live_item(slug, meta, number))
        return [{"name": name, "channel": items}
            for name, items in groups.items()]

    def _live_item(self, slug, meta, number):
        name = meta["name"]
        cp_msg = self._copyright_msg_for(meta)
        if cp_msg:
            # 直播列表直接标出限制原因；URL 走 /blocked/ 立即回文案、不取流
            short = cp_msg if len(cp_msg) <= 24 else (cp_msg[:22] + "…")
            name = "{} [{}]".format(name, short)
            urls = [self._blocked_url(slug)]
        else:
            urls = [self._live_url(slug)]
        return {
            "name": name,
            "tvgName": meta["name"],
            "tvgId": slug,
            "number": "{:02d}".format(number),
            "logo": logo_for(slug),
            "format": "application/x-mpegURL",
            "ua": USER_AGENT,
            "urls": urls,
        }

    def _copyright_msg_for(self, meta):
        key = "{}:{}".format(meta["livepid"], meta["cnlid"])
        with self._cache_lock:
            cached = self._copyright_cache.get(key)
            if cached is None:
                return None
            message, expiry = cached
            if expiry <= time.monotonic():
                self._copyright_cache.pop(key, None)
                return None
            return str(message)

    def _live_url(self, slug):
        port = getattr(self, "_port", None)
        if not port:
            raise ValueError("代理服务未启动")
        return "http://127.0.0.1:{}/live/{}.m3u8".format(port, slug)

    def _blocked_url(self, slug):
        port = getattr(self, "_port", None)
        if not port:
            raise ValueError("代理服务未启动")
        return "http://127.0.0.1:{}/blocked/{}".format(port, slug)

    # ---- 播放 ----
    def playerContent(self, flag, id, vipFlags):
        slug = self._strip(str(id or ""))
        if slug not in CHANNELS:
            return {"parse": 0, "msg": "找不到频道"}
        if self.helper is None:
            return {
                "parse": 0,
                "msg": "ysp-helper 未启动: {}".format(
                    str(self.helper_error)[:200] if self.helper_error else "unknown"
                ),
            }

        meta = CHANNELS[slug]
        key = "{}:{}".format(meta["livepid"], meta["cnlid"])
        with self._cache_lock:
            cached_cp = self._copyright_cache.get(key)
            if cached_cp is not None:
                message, expiry = cached_cp
                if expiry > time.monotonic():
                    _log("playerContent 版权缓存命中: {} -> {}".format(
                        slug, message))
                    return {"parse": 0, "msg": message}
                self._copyright_cache.pop(key, None)

        # 主动探测：版权/区域限制时直接返回 msg，不把代理 URL 交给播放器，
        # 避免播放器开始取流后才因 451 失败、反复重试或空白画面。
        deadline = time.monotonic() + PLAYER_BUDGET
        try:
            self._resolve(meta["livepid"], meta["cnlid"],
                meta.get("defn", "fhd"), deadline)
        except _CopyrightError as e:
            _log("playerContent 版权/区域限制: {} -> {}".format(slug, e))
            return {"parse": 0, "msg": str(e)}
        except _ProxyError as e:
            _log("playerContent 取址失败: {} -> {}".format(slug, e))
            return {"parse": 0, "msg": str(e)}
        except Exception as e:
            _log("playerContent 异常: {} -> {}: {}".format(
                slug, type(e).__name__, e))
            return {"parse": 0, "msg": "取址失败: {}".format(e)}

        return {
            "parse": 0, "jx": 0,
            "url": "http://127.0.0.1:{}/live/{}.m3u8".format(self._port, slug),
            "header": "", "format": "application/x-mpegURL",
        }

    def _resolve(self, pid, cnlid, defn, deadline):
        key = "{}:{}".format(pid, cnlid)
        now = time.monotonic()

        with self._cache_lock:
            cached_cp = self._copyright_cache.get(key)
            if cached_cp is not None:
                message, expiry = cached_cp
                if expiry > now:
                    raise _CopyrightError(message)
                self._copyright_cache.pop(key, None)

            entry = self._cache.get(key)
            if entry is not None:
                url, expiry = entry
                if expiry > now:
                    return url
                self._cache.pop(key, None)

        if not self.player_ready.wait(_remaining(deadline, "player 初始化")):
            raise _ProxyError(504, "player 初始化: 等待逾时")

        try:
            with self.player_lock:
                if self.player is None:
                    if self.player_error is not None:
                        err = self.player_error
                        self.player_error = None
                        raise _ProxyError(502, "player 未就绪: {}".format(err))
                    self.player = _PlayerApi(self.helper)
                url = self.player.resolve(pid, cnlid, deadline, defn)
        except _CopyrightError as e:
            with self._cache_lock:
                self._copyright_cache[key] = (
                    str(e), time.monotonic() + COPYRIGHT_CACHE_SECONDS)
            raise

        with self._cache_lock:
            self._cache[key] = (url, time.monotonic() + PLAY_CACHE_SECONDS)
        return url

    def isVideoFormat(self, url):
        p = urllib.parse.urlsplit(str(url or ""))
        return p.scheme in ("http", "https") and bool(p.netloc)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        with self.player_lock:
            self.destroyed = True
            self.player = None
        if getattr(self, "_httpd", None):
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        if getattr(self, "helper", None):
            self.helper.stop()

    @staticmethod
    def _group_of(slug):
        if slug.startswith("cctv"):
            return "央视"
        if slug.startswith("cgtn"):
            return "CGTN"
        if slug in ("cetv1", "guoxue"):
            return "卫视"
        if slug in ("fyjc", "dyjc", "hjjc"):
            return "数字"
        return "卫视"

    @staticmethod
    def _card(slug, name, group):
        return {
            "vod_id": "ch/" + slug,
            "vod_name": name,
            "vod_pic": logo_for(slug),
            "vod_remarks": group,
        }

    @staticmethod
    def _strip(ident):
        s = str(ident or "").strip()
        for prefix in ("ch/", "live/"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        if "/" in s:
            s = s.split("/", 1)[0]
        if s.endswith(".m3u8"):
            s = s[:-5]
        return s