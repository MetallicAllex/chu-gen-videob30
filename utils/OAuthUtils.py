"""
查分器 OAuth 登录模块（授权码 + PKCE，公开客户端）

支持两家查分器，两者均为公开客户端，换票与刷新都不需要 client_secret：

落雪（参考 lxns-OAuth-test.py，已实测通过）
- 授权端点: https://maimai.lxns.net/oauth/authorize
- 令牌端点: https://maimai.lxns.net/api/v0/oauth/token
- 成绩端点: https://maimai.lxns.net/api/v0/user/chunithm/player/bests

水鱼（参考 OAuth-test.py，已实测通过）
- 授权端点: https://auth.diving-fish.com/oauth/authorize
- 令牌端点: https://auth.diving-fish.com/oauth/token
- 成绩端点: https://www.diving-fish.com/api/chunithmprober/query/player
  （该接口文档标注「无需验证」，但服务端用 oauth_optional_required 装饰，
    带 Bearer 时身份直接取自令牌，请求体只需是合法 JSON、不必含 username/qq）

授权流程不占用 Streamlit 页面：本模块在 OAUTH_CALLBACK_PORT 上起一个只监听
回环地址的小 HTTP 服务专门收回调，换票与落盘都在那个线程里完成，
界面靠 pop_auth_result 轮询结果。这样授权标签页不会再次加载生成器，
正在操作的存档页也不会被跳转或换 session。

状态：
- ./cred_datas/lxns_oauth.json / ./cred_datas/fish_oauth.json  已登录令牌（已被 .gitignore 忽略）
- state / code_verifier 只在内存里存活到回调到达（最长 OAUTH_WAIT_SECONDS 秒），不落盘
"""

import os
import json
import sys
import time
import socket
import secrets
import hashlib
import base64
import threading

import requests
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ==================== 回调监听 ====================
# 必须与两家开发者控制台里登记的回调地址完全一致（水鱼明写：协议、端口、路径、尾斜杠都计入比较）。
# 之所以另起端口而不是复用 Streamlit 的 8501：回调若落在应用首页，会在那个小标签页里
# 再渲染一遍生成器（表现为「重复打开一个存档页」），并且换 session，存档状态容易乱。
OAUTH_CALLBACK_PORT = 8599
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_CALLBACK_PORT}"

# 一次授权等待回调的上限（秒）。水鱼授权码本身 60 秒即过期，超这个时间就该重新发起
OAUTH_WAIT_SECONDS = 300

# ==================== 落雪 OAuth 配置（公开客户端，client_id 可公开） ====================
LXNS_CLIENT_ID = "4153eb3c-2587-4464-b135-62d673c972ab"
LXNS_SCOPE = "read_player"
LXNS_BASE_URL = "https://maimai.lxns.net"

LXNS_AUTHORIZE_URL = f"{LXNS_BASE_URL}/oauth/authorize"
LXNS_TOKEN_URL = f"{LXNS_BASE_URL}/api/v0/oauth/token"
LXNS_BESTS_URL = f"{LXNS_BASE_URL}/api/v0/user/chunithm/player/bests"
# 玩家全部成绩。read_player 的官方描述就是「读取玩家信息、谱面成绩和历史成绩」，
# 所以这个接口在既有授权范围内，老用户无需重新走一遍授权
LXNS_SCORES_URL = f"{LXNS_BASE_URL}/api/v0/user/chunithm/player/scores"

CRED_DIR = "./cred_datas"
LXNS_TOKEN_FILE = os.path.join(CRED_DIR, "lxns_oauth.json")

# ==================== 水鱼 OAuth 配置（公开客户端，client_id 可公开） ====================
FISH_CLIENT_ID = "c1050dcfebca5ceb01dd22e7bbc9437d"
# 只申请只读成绩权限：openid 换来的 id_token 实测仅含 sub（即 Player.id），
# 而 /query/player 顶层已返回 username / nickname，多申请一个 scope 没有收益
FISH_SCOPE = "chunithm.records.read"
FISH_BASE_URL = "diving-fish.com"

FISH_AUTHORIZE_URL = f"https://auth.{FISH_BASE_URL}/oauth/authorize"
FISH_TOKEN_URL = F"https://auth.{FISH_BASE_URL}/oauth/token"
FISH_QUERY_PLAYER_URL = F"https://www.{FISH_BASE_URL}/api/chunithmprober/query/player"
# 每谱面一条历史最佳，支持服务端过滤参数；沿用已授权的 chunithm.records.read
FISH_PLAYER_RECORDS_URL = F"https://www.{FISH_BASE_URL}/api/chunithmprober/player/records"
# 以下两个无需验证，不占水鱼 200 次/日的认证调用配额
FISH_MUSIC_DATA_URL = F"https://www.{FISH_BASE_URL}/api/chunithmprober/music_data"
FISH_LATEST_VERSION_URL = F"https://www.{FISH_BASE_URL}/api/chunithmprober/latest_version"

FISH_TOKEN_FILE = os.path.join(CRED_DIR, "fish_oauth.json")

# access token 过期前的提前量（秒），避免临界时刻使用过期令牌
EXPIRY_MARGIN = 30

# 进程级运行时盒子。Streamlit 的文件监视器（watcher/local_sources_watcher.py）会在
# 本文件源码变化时把它从 sys.modules 里删掉，下次重跑就是一份全新命名空间：模块级全局
# 全部清零，可上一份模块起的监听线程还活着、还绑着 8599 —— 新实例再 bind 就是
# WinError 10048，而且这个端口之后谁都拿不到，只能重启生成器。授权中间态放在这里而不
# 放模块全局，监听与结果才能跨过这次重载继续对接（锁与监听列表取别名安全，因为只原地
# 改；pending / result 会被重新赋值，必须经盒子读写）。
_RUNTIME_KEY = "_chugen_oauth_runtime"
_rt = getattr(sys, _RUNTIME_KEY, None)
if _rt is None:
    _rt = {"refresh_lock": threading.Lock(), "auth_lock": threading.Lock(),
           "servers": [], "pending": None, "result": None}
    setattr(sys, _RUNTIME_KEY, _rt)

# 水鱼刷新令牌每次使用都会轮换，且复用已作废的旧令牌会吊销整条令牌链
# （连新签发的也一起失效），因此同进程内的刷新必须串行。
# Streamlit 每个会话跑在独立线程，多个标签页可能同时触发刷新。
_fish_refresh_lock = _rt["refresh_lock"]


def _ensure_cred_dir():
    os.makedirs(CRED_DIR, exist_ok=True)


# ==================== PKCE 工具 ====================
def generate_code_verifier():
    """生成 code_verifier (43-128 字符)"""
    return secrets.token_urlsafe(64)


def generate_code_challenge(verifier):
    """SHA256 hash + Base64URL encode"""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ==================== 落雪令牌流程 ====================
def exchange_lxns_token(code, verifier):
    """授权码换 token（PKCE，公开客户端不传 client_secret）"""
    response = requests.post(LXNS_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "client_id": LXNS_CLIENT_ID,
        "code_verifier": verifier,
    }, timeout=10)
    response.raise_for_status()
    return response.json()


def refresh_lxns_token(refresh_token):
    """尝试刷新 access token（落雪是否支持刷新以实测为准，失败时抛出）"""
    response = requests.post(LXNS_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": LXNS_CLIENT_ID,
    }, timeout=10)
    response.raise_for_status()
    return response.json()


# ==================== 令牌持久化 ====================
def save_lxns_token(token_data):
    """
    保存令牌，附带本地时间戳用于计算过期时刻。

    注意：落雪换票/刷新响应的令牌字段嵌套在 data 内
    （{success, code, data: {access_token, expires_in, refresh_token, ...}}），
    这里将 data 提升到顶层，保证 get_lxns_access_token 能正确读取。
    """
    if isinstance(token_data.get("data"), dict):
        token_data = {**token_data, **token_data.pop("data")}
    _ensure_cred_dir()
    token_data["saved_at"] = time.time()
    if token_data.get("expires_in"):
        token_data["expires_at"] = time.time() + token_data["expires_in"]
    with open(LXNS_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)


def load_lxns_token():
    """读取令牌信息，不存在或损坏返回 None（兼容旧版嵌套 data 格式）"""
    try:
        with open(LXNS_TOKEN_FILE, encoding="utf-8") as f:
            token_data = json.load(f)
        if isinstance(token_data.get("data"), dict):
            token_data = {**token_data, **token_data.pop("data")}
        return token_data
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def clear_lxns_token():
    """删除已保存的令牌（登出 / 令牌失效时）"""
    if os.path.exists(LXNS_TOKEN_FILE):
        os.remove(LXNS_TOKEN_FILE)


def _usable_lxns_token(token_data, stale_token):
    """磁盘上的令牌是否可用；stale_token 非空时排除掉那个刚吃过 401 的令牌"""
    access_token = token_data.get("access_token")
    expires_at = token_data.get("expires_at")
    if not access_token or not expires_at:
        return None
    if time.time() >= expires_at - EXPIRY_MARGIN:
        return None
    if stale_token is not None and access_token == stale_token:
        return None
    return access_token


def get_lxns_access_token(stale_token=None):
    """
    获取可用的 access token：
    - 未过期 → 直接返回
    - 已过期（或 stale_token 表明它已被服务端拒绝）且保存了 refresh_token → 尝试刷新，成功则持久化新令牌并返回
    - 其余情况 → 清除令牌并返回 None（需重新授权）

    Args:
        stale_token: 调用方刚用这个令牌收到过 401（RFC 6750 语义即「该刷新了」）。
            不传的话时钟未过期就会原样重发，第二次还是 401。
    """
    token_data = load_lxns_token()
    if not token_data:
        return None

    access_token = _usable_lxns_token(token_data, stale_token)
    if access_token:
        return access_token

    # 过期：尝试刷新
    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        try:
            new_data = refresh_lxns_token(refresh_token)
            # 若响应未签发新的 refresh token 则沿用旧的（避免丢失）
            new_data.setdefault("refresh_token", refresh_token)
            save_lxns_token(new_data)
            return new_data.get("access_token")
        except Exception:
            pass  # 刷新失败，走重新授权

    clear_lxns_token()
    return None


def is_lxns_logged_in():
    """是否处于已登录状态（有可用的 access token）"""
    return get_lxns_access_token() is not None


# ==================== 水鱼令牌流程 ====================
def exchange_fish_token(code, verifier):
    """授权码换 token（PKCE，公开客户端不传 client_secret）"""
    response = requests.post(FISH_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "client_id": FISH_CLIENT_ID,
        "code_verifier": verifier,
    }, timeout=10)
    response.raise_for_status()
    return response.json()


def refresh_fish_token(refresh_token):
    """刷新 access token（水鱼实测支持，且每次刷新都会轮换 refresh_token）"""
    response = requests.post(FISH_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": FISH_CLIENT_ID,
    }, timeout=10)
    response.raise_for_status()
    return response.json()


# ==================== 水鱼令牌持久化 ====================
def save_fish_token(token_data):
    """
    保存令牌，附带本地时间戳用于计算过期时刻。
    水鱼响应是扁平结构（access_token / expires_in / refresh_token / scope），无需拆包。

    用临时文件 + os.replace 原子写入：刷新令牌轮换后若写入中途失败，
    旧的已作废、新的没落盘，整条令牌链就废了，用户只能重新走浏览器授权。
    """
    _ensure_cred_dir()
    token_data["saved_at"] = time.time()
    if token_data.get("expires_in"):
        token_data["expires_at"] = time.time() + token_data["expires_in"]
    tmp_file = FISH_TOKEN_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, FISH_TOKEN_FILE)


def load_fish_token():
    """读取令牌信息，不存在或损坏返回 None"""
    try:
        with open(FISH_TOKEN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def clear_fish_token():
    """删除已保存的令牌（登出 / 令牌失效时）"""
    if os.path.exists(FISH_TOKEN_FILE):
        os.remove(FISH_TOKEN_FILE)


def _usable_fish_token(token_data, stale_token):
    """磁盘上的令牌是否可用；stale_token 非空时排除掉那个刚吃过 401 的令牌"""
    access_token = token_data.get("access_token")
    expires_at = token_data.get("expires_at")
    if not access_token or not expires_at:
        return None
    if time.time() >= expires_at - EXPIRY_MARGIN:
        return None
    if stale_token is not None and access_token == stale_token:
        return None
    return access_token


def get_fish_access_token(stale_token=None):
    """
    获取可用的 access token：
    - 未过期 → 直接返回
    - 已过期（或 stale_token 表明它已被服务端拒绝）且有 refresh_token → 刷新、持久化后返回
    - 其余情况 → 清除令牌并返回 None（需重新授权）

    Args:
        stale_token: 调用方刚用这个令牌收到过 401（RFC 6750 语义即「该刷新了」）。
            传它可避免重复刷新：若磁盘上的令牌已被其他线程换成新值，直接复用新值。
    """
    token_data = load_fish_token()
    if not token_data:
        return None

    access_token = _usable_fish_token(token_data, stale_token)
    if access_token:
        return access_token

    with _fish_refresh_lock:
        # 等锁期间可能已有别的线程刷新完成，重读磁盘再判一次，避免重复轮换
        token_data = load_fish_token()
        if not token_data:
            return None
        access_token = _usable_fish_token(token_data, stale_token)
        if access_token:
            return access_token

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            clear_fish_token()
            return None
        try:
            new_data = refresh_fish_token(refresh_token)
        except Exception:
            clear_fish_token()  # 刷新失败说明授权已不可用，清掉让界面回到「去授权」
            return None
        # 响应按理会带轮换后的新 refresh_token；万一缺失就沿用旧的，避免断链
        new_data.setdefault("refresh_token", refresh_token)
        save_fish_token(new_data)
        return new_data.get("access_token")


def is_fish_logged_in():
    """是否处于已登录状态（有可用的 access token）"""
    return get_fish_access_token() is not None


# ==================== 授权流程（本地回环监听接回调） ====================
# 两家的差异只在授权端点、client_id、scope 与换票/落盘函数上
_AUTH_FLOWS = {
    "fish": {
        "name": "水鱼",
        "authorize_url": FISH_AUTHORIZE_URL,
        "client_id": FISH_CLIENT_ID,
        "scope": FISH_SCOPE,
        "exchange": exchange_fish_token,
        "save": save_fish_token,
    },
    "lxns": {
        "name": "落雪",
        "authorize_url": LXNS_AUTHORIZE_URL,
        "client_id": LXNS_CLIENT_ID,
        "scope": LXNS_SCOPE,
        "exchange": exchange_lxns_token,
        "save": save_lxns_token,
    },
}

# 用户在授权页上拒绝时查分器回传的 error 值
_CALLBACK_ERRORS = {
    "access_denied": "您取消了授权。",
    "consent_required": "非法授权：未获得用户同意。",
    "server_error": "查分器服务端出错。",
}

_auth_lock = _rt["auth_lock"]
_callback_servers = _rt["servers"]    # 别名；只能原地 append，整体赋值会让盒子看不到

_CLOSE_JS = (
    "try{if(window.opener){window.opener.focus();}}catch(e){}"
    "window.close();"
    "setTimeout(function(){var t=document.getElementById('hint');"
    "if(t){t.textContent='浏览器不允许本页自行关闭，请手动关闭本标签页。';}},300);"
)

# 结果页按钮文案：点它 = 回到生成器那个标签页 + 关掉本页
_CLOSE_LABEL = "关闭并返回生成器"


def _page(title, text, action=None):
    """
    回调提示页。标题、文案、按钮全部是本模块写死的字符串，不反射任何查询参数。

    action 给出时渲染一个自关按钮：先把生成器那个标签页带回前台，再关掉本页。
    浏览器只允许关闭「由脚本以用户手势打开」的标签页，所以授权入口必须走浮窗里的
    window.open（st.link_button 带 rel="noreferrer"，那样既关不掉也拿不到 opener）；
    仍被拦下时 300 毫秒后换成 fallback 文案，让用户知道得手动关。
    """
    return (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<style>body{font:16px/1.8 system-ui,-apple-system,'Microsoft YaHei',sans-serif;"
        "margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;"
        "justify-content:center;gap:1.1em;background:#f6f8fa;color:#1f2328;text-align:center}"
        "h1{font-size:1.3em;margin:0}p{margin:0;color:#57606a;max-width:30em}"
        "button{font:inherit;padding:.5em 1.4em;border:0;border-radius:.4em;background:#1f883d;"
        "color:#fff;cursor:pointer}button:hover{background:#1a7f37}</style>"
        f"<h1>{title}</h1>\n<p id='hint'>{text}</p>"
        + (f"<button onclick=\"{_CLOSE_JS}\">{action}</button>" if action else "")
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    """接收回调；换票在本线程内同步完成，结果留给界面轮询"""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.endswith("favicon.ico"):
            self.send_response(204)
            self.end_headers()
            return
        status, html = _handle_callback(parse_qs(parsed.query, keep_blank_values=True))
        self._respond(status, html)

    def _respond(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 默认日志会把整条 URL 打出来，里面就带着授权码


class _IPv4CallbackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET
    daemon_threads = True
    # 绝不能开 SO_REUSEADDR：Windows 下它允许第二个进程绑同一个端口并抢走后续连接，
    # 回调就会落进另一个生成器实例里（界面等不到结果，令牌还写到别人那边）
    allow_reuse_address = False


class _IPv6CallbackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True
    allow_reuse_address = False


def _port_holder_hint():
    """端口绑不上时判断是谁在听：能按我们的特征回 204 的，就是另一个生成器实例"""
    try:
        r = requests.get(f"http://127.0.0.1:{OAUTH_CALLBACK_PORT}/favicon.ico",
                         timeout=1, proxies={"http": None, "https": None})
        if r.status_code == 204:
            return "该端口正被另一个生成器实例监听"
    except Exception:
        pass
    return "该端口被其他程序占用"


def _ensure_callback_server():
    """惰性启动回环监听，返回错误说明（None 表示已就绪）"""
    with _auth_lock:
        if _callback_servers:
            return None
        # 浏览器可能把 localhost 解析成 ::1，也可能解析成 127.0.0.1，两个都要监听；
        # 但不能绑双栈通配地址（那会把局域网来的连接一起收下），所以分别绑两个回环地址
        started, failures = [], []
        for server_cls, host in ((_IPv4CallbackServer, "127.0.0.1"), (_IPv6CallbackServer, "::1")):
            try:
                srv = server_cls((host, OAUTH_CALLBACK_PORT), _CallbackHandler)
            except OSError as e:
                failures.append(f"{host}: {e}")
                continue
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            started.append(srv)
        if not started:
            print(f"[OAuth] 回环监听启动失败: {failures}")
            return (f"本地授权回调端口 {OAUTH_CALLBACK_PORT} 无法监听，收不到授权结果："
                    f"{_port_holder_hint()}。请关掉占用该端口的程序后重试。")
        _callback_servers.extend(started)   # 必须原地改，赋值会让盒子与实际脱节
        if failures:
            print(f"[OAuth] 回环监听只启动了一部分: {failures}")
        return None


def _handle_callback(query):
    """回调线程入口：核对 state → 换票落盘 → 决定给小标签页看什么"""
    state = query.get("state", [None])[0]
    with _auth_lock:
        pending = _rt["pending"]
        if not pending or pending["state"] != state or \
                time.time() - pending["created_at"] > OAUTH_WAIT_SECONDS:
            # state 对不上：过期的重放，或有人往这个端口乱发请求
            return 400, _page("授权请求已失效",
                              "本次回调无法对应到一次待完成的授权。请回到生成器重新授权。",
                              _CLOSE_LABEL)
        _rt["pending"] = None
        server, verifier = pending["server"], pending["verifier"]
    name = _AUTH_FLOWS[server]["name"]

    error = query.get("error", [None])[0]
    if error:
        message = _CALLBACK_ERRORS.get(error, "授权未完成。")
        with _auth_lock:
            _rt["result"] = {"server": server, "ok": False, "message": message}
        return 200, _page(f"{name}授权未完成", message + "\n请回到生成器重新授权。",
                          _CLOSE_LABEL)

    code = query.get("code", [None])[0]
    if not code:
        with _auth_lock:
            _rt["result"] = {"server": server, "ok": False, "message": "回调未携带授权码。"}
        return 400, _page(f"{name}授权未完成", "\n未发现授权码。请回到生成器重新授权。",
                          _CLOSE_LABEL)

    flow = _AUTH_FLOWS[server]
    try:
        flow["save"](flow["exchange"](code, verifier))
    except Exception as e:
        # 细节只打到控制台（本项目一贯如此）：异常文本里只有令牌端点 URL，不含授权码
        print(f"[OAuth] {name} 换取令牌失败: {e}\n"
              f"        若为 400/invalid_client，请联系开发者确认控制台登记的回调地址是 {OAUTH_REDIRECT_URI}")
        message = "换取令牌失败，请重新授权。详细原因见终端窗口。"
        with _auth_lock:
            _rt["result"] = {"server": server, "ok": False, "message": message}
        return 200, _page(f"{name}授权未完成",
                          "\n换取令牌失败，请回到生成器重新授权。",
                          _CLOSE_LABEL)

    with _auth_lock:
        _rt["result"] = {"server": server, "ok": True, "message": f"{name}账号授权成功！"}
    return 200, _page(f"{name}授权完成",
                      "\n生成器后续将尝试自动更新授权状态。", _CLOSE_LABEL)


def begin_auth(server):
    """
    发起一次授权：起监听、生成 PKCE 参数、记下待核对的 state，把授权链接交给调用方打开。
    回调到达后由监听线程完成换票与落盘，界面用 pop_auth_result 取结果。

    Args:
        server: "fish" 或 "lxns"

    Returns:
        (auth_url, None) 或 (None, 错误说明)
    """
    error = _ensure_callback_server()
    if error:
        return None, error

    flow = _AUTH_FLOWS[server]
    verifier = generate_code_verifier()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": flow["client_id"],
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": flow["scope"],
        "state": state,
        "code_challenge": generate_code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    with _auth_lock:
        _rt["pending"] = {"server": server, "state": state, "verifier": verifier,
                          "created_at": time.time()}
        _rt["result"] = None
    return f"{flow['authorize_url']}?{urlencode(params)}", None


def pop_auth_result(server):
    """
    取走该查分器的授权结果（取走即清空），供界面轮询。

    Returns:
        None 表示仍在等待；否则 {"ok": bool, "message": str}。
        等待超过 OAUTH_WAIT_SECONDS 直接返回超时结果，免得界面无限转圈。
    """
    with _auth_lock:
        if _rt["result"] and _rt["result"]["server"] == server:
            result, _rt["result"] = _rt["result"], None
            return result
        pending = _rt["pending"]
        if pending and pending["server"] == server and \
                time.time() - pending["created_at"] > OAUTH_WAIT_SECONDS:
            _rt["pending"] = None
            return {"server": server, "ok": False, "message": "等待授权超时，请重试"}
    return None
