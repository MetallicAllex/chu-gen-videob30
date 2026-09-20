import time
import streamlit as st
import os, json, traceback
from collections import Counter
from html import escape as escape_html
import streamlit.components.v1 as st_components
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import *
from utils.DataUtils import (_process_b50_data, st_init_cache_pathes, update_b50_data,
                             build_cn_pool, cn_filter_assets, cn_filter_options, fetch_cn_pool_raw,
                             POOL_BRIEF, POOL_FULL, MODE_SERVER, MODE_LOCAL, PART_BEST, PART_NEW,
                             PART_ORDER, EmptyFilterResult, music_data_state, MUSIC_DATA_FILTER_ONLY)
from utils.FilterUtils import FIELD_LABELS
from utils.Variables import (jp_music_info_path, music_info_path, image_root_path, CN_FILTER_RANGES,
                             CHUNI_LEVEL_NAMES, CHUNI_FULL_CHAIN_TYPES, CHUNI_CLEAR_TYPES,
                             CHUNI_RANK_TYPES)
from utils import OAuthUtils

st.set_page_config(
    page_title="获取 / 管理 Best50 成绩与存档",
    page_icon="💾",
)

st.header("获取 / 管理 Best50 成绩与存档")

# 展示授权结果（换票由 OAuthUtils 的本地回环监听完成，下面的等待 fragment 取到结果后整页重绘）
if "oauth_callback_msg" in st.session_state:
    msg_type, msg_text = st.session_state.pop("oauth_callback_msg")
    if msg_type == "success":
        st.success(msg_text, icon="✅")
    else:
        st.error(msg_text, icon="❌")

# ========== 国服查分器参数表 ==========
# 两家均已切到官方 OAuth 接口：取数只需要令牌，不需要用户名 / 好友码，
# 因此下面「我玩国服」的授权区按这张表渲染，两种查分器共用同一套控件。
CN_SERVER_PROVIDERS = {
    "水鱼查分器": {
        "server": "fish",
        "name": "水鱼",
        "icon": "🐟",
        "is_authorized": OAuthUtils.is_fish_logged_in,
        "clear_token": OAuthUtils.clear_fish_token,
    },
    "落雪查分器": {
        "server": "lxns",
        "name": "落雪",
        "icon": "❄️",
        "is_authorized": OAuthUtils.is_lxns_logged_in,
        "clear_token": OAuthUtils.clear_lxns_token,
    },
}


@st.fragment(run_every=1.0)
def oauth_wait_status(server, name, auth_url, started_at, icon=None):
    """
    浮窗下半部分：等待期间每秒轮询一次本地监听的回调结果，取到结果就交给整页重绘
    （浮窗随之关闭，页面刷新为已授权 / 错误提示）。
    超过 OAUTH_WAIT_SECONDS 后不再轮询也不给可点的链接 —— 监听端已经作废了这次 state，
    再点只会得到「授权请求已失效」，所以把链接禁掉、只留重新发起。
    """
    waited = int(time.time() - started_at)
    left = OAuthUtils.OAUTH_WAIT_SECONDS - waited
    expired = left <= 0
    if not expired:
        result = OAuthUtils.pop_auth_result(server)
        if result is not None:
            st.session_state.oauth_callback_msg = (
                "success" if result["ok"] else "error", result["message"])
            _close_oauth_dialog()
        st.info(f"正在等待 {name} 返回授权结果（还剩 {left} 秒）", icon="ℹ️")
        # 不接返回值：点浮窗内的控件本身就触发一次本片段重跑，等于立刻再轮询一次，不用等下一跳
        st.button("立即刷新状态", width="stretch", icon="🔄️")
    else:
        st.warning(f"超过 {OAuthUtils.OAUTH_WAIT_SECONDS} 秒未收到授权结果，该授权链接已失效。", icon="⚠️")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("重新发起" if expired else "取消授权",
                     width="stretch", type="primary" if expired else "secondary"):
            if expired:
                restart_oauth_auth(server)
            else:
                _close_oauth_dialog()
    with col2:
        open_auth_tab_button(auth_url, "进入授权页", icon, disabled=expired)
    if expired and st.button("关闭", width="stretch"):
        _close_oauth_dialog()


def _close_oauth_dialog():
    """结束等待：浮窗随之消失（结果由监听端处理，这里只是不再接手）"""
    st.session_state.pop("oauth_pending", None)
    st.rerun(scope="app")


def restart_oauth_auth(server):
    """重新发起授权：换一对全新的 PKCE 参数与 state，浮窗回到等待态"""
    auth_url, error = OAuthUtils.begin_auth(server)
    if error:
        st.session_state.oauth_callback_msg = ("error", error)
        st.session_state.pop("oauth_pending", None)
    else:
        st.session_state.oauth_auth_url = auth_url
        st.session_state.oauth_started_at = time.time()
    st.rerun(scope="app")


def open_auth_tab_button(auth_url, label, icon=None, disabled=False):
    """
    用 window.open 打开授权页。st.link_button 会带 rel="noreferrer"，新标签拿不到
    opener，浏览器就拒绝结果页自行关闭、也无法把焦点送回本页；components.html 是
    同源 srcdoc 框架，其 sandbox 允许弹窗，脚本以用户手势打开的标签才有 opener。
    弹窗被拦（window.open 返回 null）时退回普通链接跳转。

    disabled=True 时渲染成没有 href 的灰色块：超时后那条链接的 state 已作废。
    """
    text = escape_html(f"{(icon + ' ') if icon else ''}{label}")
    shape = ("flex:1;display:flex;align-items:center;justify-content:center;gap:.45em;"
             "padding:.5rem .87rem;border-radius:.5rem;box-sizing:border-box;"
             "font:600 16px/1.6 'Source Sans Pro','Microsoft YaHei',sans-serif")
    if disabled:
        st_components.html(
            f"<style>body{{margin:0;background:transparent;display:flex}}"
            f"span{{{shape};background:#d0d7de;color:#57606a;cursor:not-allowed;"
            f"text-decoration:line-through}}</style><span>{text}</span>",
            height=44,
        )
        return
    href = escape_html(auth_url, quote=True)
    st_components.html(
        f"<style>body{{margin:0;background:transparent;display:flex}}"
        f"a{{{shape};background:#ff4b4b;color:#fff;text-decoration:none;cursor:pointer}}"
        f"a:hover{{filter:brightness(.9)}}</style>"
        f'<a id="go" href="{href}" target="_blank">{text}</a>'
        "<script>var a=document.getElementById('go');"
        "a.onclick=function(e){if(window.open(a.href,'_blank'))e.preventDefault();};</script>",
        height=44,
    )


@st.dialog("完成授权", icon="🔑", width="small", dismissible=False)
def oauth_auth_dialog(server, name, auth_url, started_at, icon=None):
    """
    授权进行中的浮窗。设为不可手动关闭：点掉浮窗会连带停掉里面的轮询，
    授权回来就没人接手了，因此只留「取消授权 / 关闭」这个明确出口。
    """
    st.write(f"点击下方「进入授权页」，在新标签页中完成 {name} OAuth 授权。")
    oauth_wait_status(server, name, auth_url, started_at, icon)


def check_username(input_username):
    # 用户名要作为本地存档目录名，含非法字符时转义
    if any(char in input_username for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
        return escape_markdown_text(input_username)
    return input_username
    
# ========== 新增：自动加载用户配置 ==========
def load_user_info_from_file(username):
    """从 user_info.json 加载用户数据到 session_state"""
    if not username:
        return False
    
    user_info_path = os.path.join(get_user_base_dir(username), "user_info.json")
    if os.path.exists(user_info_path):
        try:
            user_info = load_config(user_info_path)
            # 更新 session_state
            st.session_state.update({
                "username": user_info.get("username", username),
                "config_saved": True
            })
            return True
        except Exception as e:
            return False
    return False

# 初始化会话状态
if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False

# ========== 新增：自动加载已存在用户的配置 ==========
username = st.session_state.get("username", None)
# 如果有用户名但没有标记为已配置，尝试从文件加载
if username and not st.session_state.get('config_saved', False):
    load_user_info_from_file(username)

# 重新获取更新后的值
username = st.session_state.get("username", None)
save_id = st.session_state.get('save_id', None)

with st.container(border=True):
    input_username = st.text_input(
        "用户名（用于命名本地存档目录）",
        value=username if username else "",
        placeholder="水鱼国服数据由 OAuth 令牌确定，建议填写与查分器账号一致的用户名（尽可能不要有特殊符号）"
    )
    
    # 显示"确定"按钮
    if st.button("确定", width='stretch', icon="✔️"):
        if not input_username:
            st.error("用户名不能为空！", icon="❌")
            st.session_state.config_saved = False
        else:  
            # 输入的 username 作为文件夹路径，需要去除非法字符
            username = check_username(input_username)
            root_save_dir = get_user_base_dir(username)
            if not os.path.exists(root_save_dir):
                os.makedirs(root_save_dir, exist_ok=True)
            
            # 创建或更新 JSON 文件用于保存用户数据
            userinfo_file = os.path.join(root_save_dir, "user_info.json")
            user_info = {}
            
            # 如果用户信息文件已存在，先加载现有数据
            if os.path.exists(userinfo_file):
                user_info = load_config(userinfo_file)
            
            # 更新用户信息（保留旧字段如 friend_code，兼容老存档）
            user_info["username"] = username

            # 保存用户信息
            save_config(userinfo_file, user_info)

            st.toast("用户信息已保存！", icon="✅")
            st.session_state.update({
                "username": username,
                "config_saved": True
            })

# ===== 国服筛选面板 =====
# 这些条件只在"建这一份存档"的当下生效，筛完直接固化进存档，之后没有重筛入口。

# 水鱼返回体里没有的原生字段：置灰并说明，而不是静默藏掉
FISH_ABSENT_FIELDS = ("chain", "clear", "rank", "over_power_range")

CN_FC_LABELS = {
    "fish": {"未达成": "none", "FULL COMBO": "fullcombo", "ALL JUSTICE": "alljustice"},
    "lxns": {"未达成": "none", "FULL COMBO": "fullcombo", "ALL JUSTICE": "alljustice",
             "ALL JUSTICE CRITICAL": "alljusticecritical"},
}


def _cn_reverse(mapping):
    return {value: label for label, value in mapping.items()}


def _cn_range_control(spec_key, label, disabled=False, help=None):
    """
    区间滑块。滑到端点＝该侧不限，整段都没动时返回 None。
    必须如此：否则"没碰过的默认全区间"会成为一条真条件，把缺该字段的记录无声剔掉。
    """
    lo, hi, step = CN_FILTER_RANGES[spec_key]
    cast = type(lo)
    low, high = st.slider(label, min_value=cast(lo), max_value=cast(hi),
                          value=(cast(lo), cast(hi)), step=cast(step),
                          key=f"cnflt_{spec_key}", disabled=disabled, help=help)
    if disabled:
        return None
    lower = None if low <= cast(lo) else low
    upper = None if high >= cast(hi) else high
    return None if lower is None and upper is None else [lower, upper]


def _cn_choice(label, options, key, mapping=None, disabled=False, help=None, default=None, fmt=None):
    """多选：mapping 是「界面文案 -> spec 取值」，没给就原样返回；fmt 只管显示。"""
    format_func = fmt or ((lambda x: mapping.get(x, x)) if mapping else None)
    picked = st.multiselect(label, list(options), default=default, key=key,
                            disabled=disabled or not options, help=help,
                            **({"format_func": format_func} if format_func else {}))
    if disabled or not picked:
        return None
    return [_cn_reverse(mapping)[x] for x in picked] if mapping else picked


def _cn_frames_ready():
    """底图素材实际齐了哪几个难度编号——素材缺一个，选中它的筛选结果就到生成阶段才炸。"""
    return {i for i in CHUNI_LEVEL_NAMES if os.path.exists(f"{image_root_path}/Frames/{i}.png")}


def cn_filter_panel(server, name, assets, options, pool_source, best_or_new,
                    grouped=True, flat_cap=None):
    """
    渲染筛选项，返回 {"filters","caps","include_selections","filter_mode","new_versions","group_parts"}。

    两家支持的字段不同：水鱼没有链条/达成/评级/OverPower/时间，落雪的定数是曲库推导的。
    不支持的照旧画出来但置灰，让用户看见"这里筛不了、为什么"。

    grouped=False 时不分新旧：筛完就是最终名单，全部编成 Best_i，只有一个总条数上限，
    「哪些版本算新曲」那种只为切新旧而存在的控件不再出现。
    """
    spec = {}
    is_fish = server == "fish"
    full_history = pool_source == POOL_FULL
    support = (lambda key: not (is_fish and key in FISH_ABSENT_FIELDS))
    meta_reason = None
    if not options:
        gaps = [label for label, _ in MUSIC_DATA_FILTER_ONLY
                if label in music_data_state()["missing"]] or ["曲库"]
        meta_reason = "这一列筛不了：缺 " + "、".join(gaps) + "（启动时会自动补齐，稍后刷新本页）"
    row = st.columns(2)

    with row[0]:
        levels = _cn_choice("难度", list(CHUNI_LEVEL_NAMES), "cnflt_level",
                            fmt=lambda i: f"{i} {CHUNI_LEVEL_NAMES[i]}",
                            help="按谱面难度筛选；不含 WORLD'S END（素材与渲染均不支持）")
        if levels:
            spec["level_index"] = [int(v) for v in levels]
        lacking = sorted(set(int(v) for v in (levels or [])) - _cn_frames_ready())
        if lacking:
            st.warning("、".join(f"{i} {CHUNI_LEVEL_NAMES[i]}" for i in lacking)
                       + " 的底图素材缺失，筛选能命中但生成底图时会失败。", icon="⚠️")
    with row[1]:
        rng = _cn_range_control("ds_range", "定数区间",
                                help=None if is_fish else "水鱼直接返回定数；落雪由本地曲库按难度推导")
        if rng:
            spec["ds_range"] = rng

    row = st.columns(2)
    with row[0]:
        genre = _cn_choice("曲风", options["genre"] if options else [], "cnflt_genre",
                           disabled=not options, help=meta_reason)
        if genre:
            spec["genre"] = genre
    with row[1]:
        version = _cn_choice("版本", options["version"] if options else [], "cnflt_version",
                             disabled=not options,
                             help=meta_reason or "国服「一个版本」在数据里占两档（主版本 + 它的 PLUS），"
                                                 "这里按一代整体勾选，选中即两档一起算。",
                             fmt=(options or {}).get("version_group_labels", {}).get)
        if version:
            # 一代展开成它覆盖的每一档，谓词与服务端翻译都只认具体档位
            members = (options or {}).get("version_members") or {}
            spec["version"] = [v for gen in version for v in members.get(gen, [gen])]

    row = st.columns(2)
    with row[0]:
        fc = _cn_choice("全连状态", CN_FC_LABELS[server].keys(), "cnflt_fc",
                        mapping=CN_FC_LABELS[server],
                        help="「未达成」与 FC 混选时只在本机筛，不发服务端参数（服务端语义未证实）")
        if fc:
            spec["fc"] = fc
    with row[1]:
        chain = _cn_choice("链条状态", CHUNI_FULL_CHAIN_TYPES.keys(), "cnflt_chain",
                           mapping=CHUNI_FULL_CHAIN_TYPES, disabled=not support("chain"),
                           help=None if support("chain") else "水鱼不返回链条状态")
        if chain:
            spec["chain"] = chain

    keyword = st.text_input("曲名关键字（任一命中即可）", key="cnflt_keyword",
                            placeholder="支持别名；子串匹配，忽略大小写", width='stretch')
    if keyword.strip():
        spec["title_keyword"] = [keyword.strip()]

    # --- 更多条件：查分器界面上没有的这些，默认收起来 ---
    with st.expander("更多条件（查分器界面没有，多为完整历史那一路准备）", icon="⚙️"):
        st.caption("落雪 / 水鱼的筛选面板都提供不到这些条件；标灰的是该数据源根本不返回这个字段。")
        row = st.columns(2)
        with row[0]:
            rng = _cn_range_control("score_range", "分数区间")
            if rng:
                spec["score_range"] = rng
        with row[1]:
            rng = _cn_range_control("rating_range", "单曲 Rating 区间",
                                    help=None if is_fish else "落雪的 rating 与水鱼的 ra 不是同一套算法，数值不可横向比较")
            if rng:
                spec["rating_range"] = rng

        row = st.columns(2)
        with row[0]:
            clear = _cn_choice("达成状态", CHUNI_CLEAR_TYPES.keys(), "cnflt_clear",
                               mapping=CHUNI_CLEAR_TYPES, disabled=not support("clear"),
                               help=None if support("clear") else "水鱼不返回达成状态；想筛 FAIL 可用分数区间近似")
            if clear:
                spec["clear"] = clear
        with row[1]:
            rank = _cn_choice("评级", CHUNI_RANK_TYPES.keys(), "cnflt_rank",
                              mapping=CHUNI_RANK_TYPES, disabled=not support("rank"),
                              help=None if support("rank") else "水鱼不返回评级；评级本质上就是分数区间，用上面的分数滑块更直接")
            if rank:
                spec["rank"] = rank

        rng = _cn_range_control("over_power_range", "Over Power 区间",
                                disabled=not support("over_power_range"),
                                help=None if support("over_power_range") else "水鱼不返回 Over Power")
        if rng:
            spec["over_power_range"] = rng

        if not options:
            st.caption("曲库还没到位，下面曲师 / 谱师 / BPM 三项已置灰；程序启动时会自动补齐，稍后刷新本页即可。")
        row = st.columns(3)
        with row[0]:
            artist = _cn_choice("曲师", options["artist"] if options else [], "cnflt_artist",
                                disabled=not options, help=meta_reason)
            if artist:
                spec["artist"] = artist
        with row[1]:
            charter = _cn_choice("谱师", options["charter"] if options else [], "cnflt_charter",
                                 disabled=not options, help=meta_reason)
            if charter:
                spec["charter"] = charter
        with row[2]:
            rng = _cn_range_control("bpm_range", "BPM 区间", disabled=not options, help=meta_reason)
            if rng:
                spec["bpm_range"] = rng

    result = {"filters": spec, "caps": None, "include_selections": False,
              "filter_mode": MODE_LOCAL, "new_versions": None}

    # --- 筛选执行位置：只有水鱼 + 完整历史有得选 ---
    if is_fish and full_history:
        result["filter_mode"] = st.radio(
            "筛选执行位置", [MODE_SERVER, MODE_LOCAL], horizontal=True, key="cnflt_mode",
            help="服务端预筛先把候选集缩小再由本机精筛收尾；两种模式的结果一致（已按水鱼过滤语义逐条验证）。"
                 "拿不准能否精确翻译的条件一律不发参数，只在本机筛。")
    elif is_fish:
        st.caption("水鱼的简略成绩接口不支持过滤参数，这一档固定在本机筛。")
    else:
        st.caption("落雪的个人成绩接口没有查询参数，这一档固定在本机筛。")

    # --- 组上限与分组形状 ---
    result["group_parts"] = grouped
    if not grouped:
        result["caps"] = {PART_BEST: flat_cap}
        st.caption(f"不分新旧组：筛后按单曲 Rating 从高到低取前 {flat_cap} 条，全部编成 Best_i。")
    elif full_history:
        col_a, col_b = st.columns(2)
        caps = {}
        if best_or_new in ("全都要", "仅旧曲"):
            caps[PART_BEST] = col_a.number_input("旧曲组上限", 0, 100, 30, key="cnflt_cap_best")
        if best_or_new in ("全都要", "仅新曲"):
            caps[PART_NEW] = col_b.number_input("新曲组上限", 0, 100, 20, key="cnflt_cap_new")
        result["caps"] = caps
        st.caption("各组按单曲 Rating 从高到低截断，因此存档里的 Best_1 就是筛后最强的一条。")
        if not is_fish:
            auto = (assets or {}).get("new_versions") or []
            chosen = _cn_choice("哪些版本算新曲", (options or {}).get("version_flat", []), "cnflt_newver",
                                disabled=not options, default=auto,
                                fmt=(options or {}).get("version_labels", {}).get,
                                help="查分器口径里的「新曲」是最近两个版本，不是只有最新版 —— 水鱼服务端写死的"
                                     "当前版本表与落雪自己标的 New 20 都是这两档。默认照抄它；只勾最新一档"
                                     "会得到一个明显偏空的 New 组。")
            result["new_versions"] = chosen if chosen is not None else auto
            if not (assets or {}).get("new_versions_authoritative"):
                st.warning("未能与水鱼版本表交叉核对，新曲窗口退回了「本地曲库最高的两个版本」，请确认上面的选择。",
                           icon="⚠️")
            ahead = (assets or {}).get("new_versions_ahead") or []
            if ahead:
                names = "、".join(f"{v} {(options or {}).get('version_labels', {}).get(v, '')}".strip()
                                for v in ahead)
                st.info(f"落雪曲库里已有比当前窗口更新的版本（{names}），水鱼的版本表还没跟上 —— 这些曲子"
                        f"会落进旧曲组。关掉上面的「分成 Best / New 两组」就不受这个口径影响。", icon="ℹ️")
    if not full_history:
        if not is_fish:
            result["include_selections"] = st.toggle(
                "把 Selections（落雪额外 10 首）纳入候选", key="cnflt_select",
                help="落雪口径是 Best30 + Select10 + New20 共 60 首，水鱼是 b30 + n20 共 50 首。"
                     + ("打开后筛剩的 Selections 会以 Select_1.. 单独成组。" if grouped
                        else "打开后这一层一起进候选，按 Rating 参与同一份名单排序。"))
        else:
            st.caption("水鱼的简略成绩只有 b30 与 n20，没有第三个分组可纳入。")
    return result


def cn_pool_preview(server, name, best_or_new, pool_source, panel, assets, can_fetch):
    """
    一次未过滤请求 + 之后零请求实时预览。返回可复用的原始响应（未缓存时 None）。

    缓存的是「未筛选」的整份响应，所以改条件不再花配额；服务端预筛模式复用同一份缓存
    也安全 —— 两条链路都以同一套本机谓词收尾，结果一致。
    """
    cache_key = f"{server}|{pool_source}"
    cache = st.session_state.get("cn_pool_cache")
    if not cache or cache.get("key") != cache_key:
        cache = None

    col_btn, col_hint = st.columns([0.3, 0.7], vertical_alignment="center")
    with col_btn:
        if st.button("重新拉取候选池" if cache else "拉取候选池", icon="🔎", width="stretch",
                     disabled=not can_fetch):
            with st.spinner(f"正在向{name}拉取未筛选的成绩…"):
                raw, error = fetch_cn_pool_raw(server, pool_source)
            if error:
                st.error(error, icon="❌")
            else:
                cache = {"key": cache_key, "raw": raw, "at": datetime.now().strftime("%H:%M:%S")}
                st.session_state["cn_pool_cache"] = cache
    with col_hint:
        if not can_fetch:
            st.caption("完成授权后才能拉取候选池。")
        elif not cache:
            st.caption("拉一次未筛选的候选池（1 次请求），之后改条件只实时重算，不再发请求。")
        else:
            st.caption(f"候选池已缓存于 {cache['at']}，条件变化即时重算、零请求。")

    if not cache:
        return None

    pool = build_cn_pool(server, best_or_new, pool_source=pool_source,
                         filter_mode=panel["filter_mode"], spec=panel["filters"], caps=panel["caps"],
                         include_selections=panel["include_selections"],
                         new_versions=panel["new_versions"], assets=assets, raw=cache["raw"],
                         group_parts=panel.get("group_parts", True))
    _cn_render_stats(pool, server)
    return cache["raw"]


def _cn_render_stats(pool, server):
    """候选/符合/入库三个数分开报，命中原因、缺失说明、被忽略的条件一次说清。"""
    stats = pool["stats"]
    counts = Counter(pool["prefixes"])
    kept = len(pool["hits"])
    line = f"候选 {stats['total']} 条　·　符合条件 {stats['hits']} 条"
    if kept != stats["hits"]:
        line += f"　·　组上限截断后入库 **{kept}** 条"
    else:
        line += f"　·　入库 **{kept}** 条"
    line += ("（" + "　".join(f"{part} {counts[part]}" for part in PART_ORDER if counts.get(part)) + "）"
             if counts else "（一条都不剩）")
    st.markdown(line)

    if stats["excluded_by"]:
        st.caption("首个不满足的条件淘汰："
                   + "　".join(f"{FIELD_LABELS.get(k, k)} {v}" for k, v in stats["excluded_by"].items()))
    if stats.get("grouped", True) and stats.get("no_version"):
        st.warning(f"有 {stats['no_version']} 条成绩在本地曲库里查不到，判不出新旧，一律按旧曲留下了。"
                   f"曲库补齐后可以解出一部分（程序启动时自动进行，也可到首页手动强制一次）。", icon="⚠️")
    if stats["missing"]:
        st.warning("因缺信息被排除："
                   + "　".join(f"{FIELD_LABELS.get(k, k)} {v} 条" for k, v in stats["missing"].items())
                   + "（曲库未覆盖该曲，或该数据源不返回这个字段。前者会随曲库自动补齐）", icon="⚠️")
    if stats["ignored"]:
        st.info("以下条件该数据源不支持，已忽略："
                + "　".join(FIELD_LABELS.get(k, k) for k, _ in stats["ignored"]), icon="ℹ️")

    if pool["params"]:
        st.caption("本次发给服务端的粗筛参数：" + "　".join(f"{k}={v}" for k, v in pool["params"].items()))
    if pool["dropped"]:
        st.caption("以下条件只在本机筛："
                   + "　".join(f"{FIELD_LABELS.get(k, k)}（{reason}）" for k, reason in pool["dropped"]))

    if pool["hits"]:
        fc_labels = _cn_reverse(CN_FC_LABELS[server])
        # 数值列里混进字符串会让 arrow 转换直接失败（日志里一坨 traceback），缺失一律留 None 显示成空格
        st.dataframe(
            [{
                "组": item["_part"],
                "曲目": item["_title"],
                "难度": CHUNI_LEVEL_NAMES.get(item["_level_index"], "—"),
                "定数": item["_ds"],
                "分数": item["_score"],
                "Rating": item["_rating"],
                "达成": fc_labels.get(item["_fc"], "未达成" if not item["_fc"] else (item["_fc"] or "—")),
            } for item in pool["hits"][:20]],
            width="stretch", hide_index=True)
        if len(pool["hits"]) > 20:
            st.caption(f"仅显示前 20 行，实际入库 {len(pool['hits'])} 条。")


def _discard_save_dir(save_paths):
    """本次没建成的存档目录要收掉：留着它，存档列表里就是一份点不开的坏存档。"""
    save_dir = os.path.dirname(save_paths['data_file'])
    if os.path.exists(save_dir):
        try:
            import shutil
            shutil.rmtree(save_dir)
            st.toast("已删除本次获取的存档文件夹", icon="🗑️")
        except Exception as rm_error:
            print(f"删除存档文件夹失败: {rm_error}")


def update_b50(update_function, local_username, save_paths, query_param):
    # raw 可能是整份未筛选响应，直接打印会刷屏，只看条件本身
    print({key: (f"<{len(value)} 个键>" if key == "raw" else value) for key, value in query_param.items()})
    try:
        # 1. 强制加载用户名（OAuth 取数不含查询凭据，这里只用于提示文案）
        def get_safe_display_name():
            """从 session_state 或 user_info.json 取展示用的用户名"""
            # 优先从session获取
            safe_name = st.session_state.get("username", None)
            if safe_name: 
                return safe_name
                
            # 次之从user_info.json获取
            user_info_path = os.path.join(get_user_base_dir(local_username), "user_info.json")
            if os.path.exists(user_info_path):
                user_info = load_config(user_info_path)
                return user_info.get("username", "用户")
            return "用户"  # 最终回退

        safe_name = get_safe_display_name()

        # 2. 执行数据获取（原逻辑不变）
        b50_data = update_function(save_paths['raw_file'], save_paths['data_file'], query_param)
        
        # 3. 绝对安全显示
        if "error" not in b50_data:
            st.toast(f"已获取 {safe_name} 的游戏数据", icon="✅")
            st.toast("请检查 b50_config.json 是否有内容，如没有则为清洗失败", icon="⚠️")
            st.session_state.data_updated_step1 = True
            st.session_state.config_saved = True
            return b50_data
        else:
            st.error(f"获取 {safe_name} 的游戏数据失败: {b50_data['error']}", icon="❌")
            time.sleep(5)
            st.rerun()

    except EmptyFilterResult as e:
        # 条件太严不是程序故障，弹 traceback 只会让人以为生成器坏了
        st.session_state.data_updated_step1 = False
        _discard_save_dir(save_paths)
        st.session_state.pop("save_id", None)  # 目录已经回收，别留一个指向空气的存档号
        st.error(f"没有成绩满足这些条件：{e}\n\n"
                 f"- 可以先「拉取候选池」看看实际有哪些成绩，再放宽条件\n"
                 f"- 提示「因缺信息被排除」的条目，通常是曲库落后于线上，等曲库自动补齐（或到首页强制更新一次）即可",
                 icon="🔍")
        return None

    except Exception as e:
        st.session_state.data_updated_step1 = False
        _discard_save_dir(save_paths)

        # 4. 错误信息核级过滤
        error_msg = str(e)
        filtered_msg = error_msg.replace(local_username, "[已过滤]")  # 暴力替换所有可能泄露
        
        st.toast(filtered_msg, icon="❌")
        st.expander("详细错误信息（请将这部分内容拷贝或截图发给开发者）：", icon="⚠️").write(traceback.format_exc())  # 确保traceback也过滤
        return None


def fetch_and_create_save(username, data_params):
    """创建新存档并从已授权的查分器获取数据（身份取自 OAuth 令牌，无需用户名 / 好友码）"""
    # 存档号只精确到秒。同一秒内点两次会算出同一个目录，而第二次失败时的清理会把整个目录
    # 回收掉 —— 连带删掉第一次刚建好的存档。先等到一个没人占用的存档号再往下走。
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    while os.path.exists(get_user_version_dir(username, timestamp)):
        time.sleep(1)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_paths = get_data_paths(username, timestamp=timestamp)
    save_dir = os.path.dirname(current_paths['data_file'])
    save_id = os.path.basename(save_dir)
    if save_id:
        os.makedirs(save_dir, exist_ok=True)
        st.session_state.save_id = save_id
        with st.spinner("正在获取数据。"):
            update_b50(update_b50_data, username, current_paths, data_params)


@st.dialog("删除存档？", width="medium")
def delete_save_data(username, save_id):
    version_dir = get_user_version_dir(username, save_id)
    st.warning(f"""
               您是要删除【{username} - {save_id}】吗？
               - 将清除所有已生成 Best50 底图和视频，且不可撤销！
               """, icon="⚠️")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("是的！我要删除它！", icon="✔️", width='stretch'):
            # 迭代地删除文件夹version_dir下的所有文件和子文件夹
            for root, dirs, files in os.walk(version_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(version_dir)
            st.toast(f"已删除存档【{username} - {save_id}】", icon="✅")
            st.rerun()
    with col2:
        if st.button("不了，也许哪天会用？", icon="✖️", width='stretch'):
            st.rerun()

def load_user_info(username):
    """从 user_info.json 加载用户数据到 session_state"""
    user_info_path = os.path.join(get_user_base_dir(username), "user_info.json")
    if os.path.exists(user_info_path):
        try:
            user_info = load_config(user_info_path)
            # 更新 session_state
            st.session_state.update({
                "username": user_info.get("username", username),
            })
            return True
        except Exception as e:
            st.error(f"加载用户信息失败: {e}", icon="❌")
            return False
    return False

st.divider()
if st.session_state.get('config_saved', False):
    st_init_cache_pathes()

    st.write("b50 存档读取 / 编辑")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            st.info(f"新存档可能无法立刻显示，单击其他存档即可刷新。", icon="ℹ️")
            selected_save_id = st.selectbox(
                "选择一份已保存的存档",
                versions,
                format_func=lambda x: f"{x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
            )
            col1, col2, col3 = st.columns(3, gap="small")
            with col1:
                if st.button("加载此存档", icon="▶️", width='stretch'):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        if load_user_info(username):
                            st.toast("已加载您的存档。", icon="✅")
                        else:
                            st.warning("存档加载成功，但未找到用户信息。", icon="⚠️")
                        st.session_state.data_updated_step1 = True
                        st.session_state.config_saved = True
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("未指定有效的存档路径！", icon="❌")
            with col2:
                version_dir = get_user_version_dir(username, selected_save_id)
                if st.button("打开文件夹", icon="📂", help=version_dir, width='stretch'):
                    if os.path.exists(version_dir):
                        absolute_path = os.path.abspath(version_dir)
                    else:
                        absolute_path = os.path.abspath(os.path.dirname(version_dir))
                    open_file_explorer(absolute_path)
            with col3:
                if st.button("删除存档", icon="🗑️", width='stretch'):
                    delete_save_data(username, selected_save_id)

    else:
        st.warning(f"{username} 还没有历史存档，请从下方获取新的 Best30 数据。", icon="⚠️")

    st.divider()
    st.write(f"新建 / 获取 b50 数据")
    st.info("""
            从下面选择您使用的查分器获取 Best50 数据，系统将为您创建存档。
            - 【水鱼】与【落雪】都需先授权对应查分器账号（官方 OAuth 接口），无需填写用户名或好友码
            - 授权后取到的是令牌主人自己的成绩；水鱼的（禁止其他人查询我的成绩）隐私设置不影响 OAuth 读取
            """, icon="ℹ️")
    with st.container(border=True):
        metadata_status = music_data_state()["core_ready"]
        if not metadata_status:
            st.error("""
                    谱面数据尚未就绪。程序启动时已在后台自动补齐，稍等片刻后刷新本页即可；
                    长时间未就绪通常是网络不通，请联网后重新打开。
                    - 生成器任何操作**均基于此数据完成**，您*必须*要有这份数据后才能继续
                    """, icon="❗")
        with st.expander("我玩国服", icon="🔴"):
            # ===== 查分器选择（两种数据源均需 OAuth 授权） =====
            data_server_selected = st.radio(
                "查分器", list(CN_SERVER_PROVIDERS), index=0, horizontal=True,
                key="select_data_server_main", width="stretch",
                captions=["需授权水鱼账号（官方 OAuth 接口）", "需授权落雪账号（官方 OAuth 接口）"])
            provider = CN_SERVER_PROVIDERS[data_server_selected]
            authorized = provider["is_authorized"]()

            # ===== OAuth 授权区 =====
            oauth_col1, oauth_col2 = st.columns([0.68, 0.32], vertical_alignment="center")
            with oauth_col1:
                if authorized:
                    st.success(f"✅ 已授权{provider['name']}账号，数据走官方 OAuth 接口（令牌过期自动续期）", icon="🔓")
                else:
                    st.warning(f"尚未授权{provider['name']}账号，请先完成授权再获取数据。", icon="⚠️")
            with oauth_col2:
                if authorized:
                    if st.button("断开连接", icon="🚪", width="stretch",
                                 help=f"仅删除本地的{provider['name']}令牌（断开连接）。如需彻底撤销授权，请到{provider['name']}官网账号设置中管理已授权应用。"):
                        provider["clear_token"]()
                        st.toast(f"已断开{provider['name']}授权连接。彻底撤销授权请前往{provider['name']}官网账号设置。", icon="🔌")
                        st.rerun()
                elif st.button(f"授权{provider['name']}账号", icon=provider["icon"], width="stretch"):
                    # 起本地回环监听并生成 PKCE 参数；回调由监听线程完成换票，本页面不跳转
                    auth_url, error = OAuthUtils.begin_auth(provider["server"])
                    if error:
                        st.session_state.oauth_pending = None
                        st.error(error, icon="❌")
                    else:
                        st.session_state.oauth_pending = provider["server"]
                        st.session_state.oauth_auth_url = auth_url
                        st.session_state.oauth_started_at = time.time()
                        st.rerun()

            # 只要发起过授权就得让浮窗跑起来：结果取不走会丢提示，pending 也会一直挂着
            if st.session_state.get("oauth_pending") == provider["server"]:
                oauth_auth_dialog(
                    provider["server"], provider["name"],
                    st.session_state["oauth_auth_url"],
                    st.session_state.get("oauth_started_at", time.time()),
                    provider["icon"])

            # ===== 存档形状：分不分新旧两组 =====
            grouped = st.toggle("分成 Best / New 两组", value=False, disabled=not metadata_status,
                                key="cnflt_grouped",
                                help="关掉时筛出来的就是最终名单：不分新旧，一律编成 Best_1..Best_N，"
                                     "按单曲 Rating 从高到低取前 N 条。打开后才有 b30/n20 那套分组、"
                                     "各自的组上限，以及「哪些版本算新曲」。")
            flat_cap = None
            if grouped:
                best_or_new = st.radio(
                    "获取数据类型", ["全都要", "仅旧曲", "仅新曲"], index=0,
                    disabled=not metadata_status, horizontal=True, key="select_cn_data_type",
                    captions=["Best30 + New20", "Only Best30", "Only New20"])
            else:
                # 单组下"仅旧曲/仅新曲"没有对象可表达，取前几条就是唯一的上限
                best_or_new = "全都要"
                flat_cap = st.number_input("取前几条（按单曲 Rating 降序）", 1, 300, 50,
                                           disabled=not metadata_status, key="cnflt_cap_flat",
                                           help="50 是现在 Best30 + New20 的总量；只想做纯 Best30 就填 30。")

            # ===== 成绩来源：查分器切好的 b50，还是每谱面一条的完整历史 =====
            pool_source = st.radio(
                "成绩来源", [POOL_BRIEF, POOL_FULL], index=0,
                disabled=not metadata_status, horizontal=True, key="select_cn_pool_source",
                captions=["查分器按自己的规则切好的 b50，一次请求",
                          "每个谱面的历史最佳，取哪几条由这次筛选决定"])

            assets = cn_filter_assets(provider["server"]) if metadata_status else None
            options = cn_filter_options(provider["server"], assets) if assets else None

            with st.expander("筛选条件（仅在本次建存档时生效）", icon="🔎"):
                st.caption("筛完的结果直接固化进这份存档，之后不再有重筛入口——要换条件就再建一份。")
                panel = cn_filter_panel(provider["server"], provider["name"], assets, options,
                                        pool_source, best_or_new, grouped, flat_cap)
                cached_raw = cn_pool_preview(provider["server"], provider["name"], best_or_new,
                                             pool_source, panel, assets,
                                             can_fetch=authorized and metadata_status)
                reuse_cache = st.checkbox(
                    "获取数据时复用上面缓存的候选池（省 1 次请求）", key="cnflt_reuse",
                    disabled=cached_raw is None,
                    help="缓存的是未筛选的完整响应。服务端预筛与本机精筛收尾于同一套谓词，"
                         "复用这份缓存只是省掉一次请求，不改变结果。")

            data_params = {
                "data_server": provider["server"],
                "best_or_new": best_or_new,
                "pool_source": pool_source,
                "filter_mode": panel["filter_mode"],
                "filters": panel["filters"],
                "caps": panel["caps"],
                "include_selections": panel["include_selections"],
                "new_versions": panel["new_versions"],
                "group_parts": panel["group_parts"],
            }
            if reuse_cache and cached_raw is not None:
                data_params["raw"] = cached_raw

            if st.button("获取数据", icon="🔻", width='stretch',
                         disabled=not metadata_status or not authorized):
                try:
                    fetch_and_create_save(username, data_params)
                except Exception as e:
                    st.error(f"获取数据时发生错误: {e}", icon="❌")
                        
        with st.expander("我玩外服", icon="🔵"):
            st.info(f"""
                    请按照以下步骤，完成您的创建存档操作：
                    - 上传您的游戏数据文件（扩展名以 .json 结尾）
                    - 在数据预览内，检查您的前几条数据是否正常
                    - 选择解析类型，点击 “解析并创建存档” 以开始解析
                    """, icon="ℹ️")
            uploaded_file = st.file_uploader(
                "选择数据文件", 
                type=["json"], 
                disabled=not metadata_status,
                key="intr_uploader"
            )
            
            if uploaded_file is not None and metadata_status:
                try:
                    # 读取文件
                    content = uploaded_file.read()
                    raw_data = json.loads(content.decode('utf-8'))
                    
                    # ========== 检查必要键值是否存在 ==========
                    missing_keys = []
                    if "best" not in raw_data:
                        missing_keys.append("best")
                    if "new" not in raw_data:
                        missing_keys.append("new")
                    
                    if missing_keys:
                        st.error(f"文件中缺少必要的键值: {', '.join(missing_keys)}", icon="❌")
                        st.caption("请确保文件包含 best 和 new 数组")
                        
                        # 显示文件中的实际键值供参考
                        available_keys = list(raw_data.keys())
                        if available_keys:
                            st.info(f"文件中现有的键值: {', '.join(available_keys)}")
                        
                        # 显示数据预览
                        with st.expander("查看文件内容预览"):
                            preview_data = {}
                            for key in available_keys[:5]:  # 只预览前5个键，避免数据太大
                                if isinstance(raw_data[key], list):
                                    preview_data[key] = raw_data[key][:3] if raw_data[key] else []
                                else:
                                    preview_data[key] = raw_data[key]
                            st.json(preview_data)
                        
                        st.stop()  # 停止执行
                    
                    # ========== 显示数据统计（不限制长度） ==========
                    best_count = len(raw_data["best"])
                    new_count = len(raw_data["new"])
                    
                    # 不再警告长度异常，只显示信息
                    st.caption(f"注：文件包含 {best_count} 首 Best 曲目，{new_count} 首 New 曲目")
                    
                    # 显示数据预览（只显示前几条作为示例）
                    with st.expander("数据预览（各自显示前 5 条）"):
                        preview = {}
                        if best_count > 0:
                            preview["best_sample"] = raw_data["best"][:5]
                        if new_count > 0:
                            preview["new_sample"] = raw_data["new"][:5]
                        st.json(preview)
                    
                    intr_act_col1, intr_act_col2 = st.columns(2, vertical_alignment="center")
                    with intr_act_col1:
                        # 让用户选择数据类型
                        data_type = st.radio(
                            "选择要解析的数据类型", disabled=not metadata_status,
                            options=["全都要", "仅旧曲", "仅新曲"], horizontal=True, 
                            captions=["Best30 + New20", "Only Best30", "Only New20"], key="intr_data_type",
                            help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "国服与外服的设置相互分离"
                        )
                    
                    # 根据数据类型检查数据是否存在（不检查长度）
                    if data_type in ["仅旧曲", "全都要"] and best_count == 0:
                        st.error("您选择了解析 旧曲目 数据，但文件中没有 旧曲目 数据", icon="❌")
                        st.stop()
                    if data_type in ["仅新曲", "全都要"] and new_count == 0:
                        st.error("您选择了解析 新曲目 数据，但文件中没有 新曲目 数据", icon="❌")
                        st.stop()
                    
                    # 准备存档路径
                    current_paths = get_data_paths(username, timestamp=None)
                    save_dir = os.path.dirname(current_paths['data_file'])
                    save_id = os.path.basename(save_dir)
                    
                    with intr_act_col2:
                        if st.button("解析并创建存档", use_container_width=True, icon="🔄", disabled=not metadata_status):
                            try:
                                os.makedirs(save_dir, exist_ok=True)
                                st.session_state.save_id = save_id
                                
                                with st.spinner("正在解析数据..."):
                                    # 根据数据类型决定传哪些键值
                                    filtered_data = {}
                                    if data_type in ["仅旧曲", "全都要"]:
                                        filtered_data["best"] = raw_data["best"]
                                    if data_type in ["仅新曲", "全都要"]:
                                        filtered_data["new"] = raw_data["new"]
                                    
                                    # 直接调用 _process_b50_data
                                    processed_data = _process_b50_data(
                                        filtered_data,
                                        "intr",
                                        current_paths['raw_file'],
                                        current_paths['data_file'],
                                        data_type
                                    )
                                
                                # 成功
                                st.toast(f"成功解析 {len(processed_data)} 首曲目", icon="✅")
                                st.session_state.data_updated_step1 = True
                                st.session_state.config_saved = True
                                
                            except Exception as e:
                                # 失败时清理
                                if os.path.exists(save_dir):
                                    import shutil
                                    shutil.rmtree(save_dir)
                                
                                st.toast(f"❌ 解析失败: {str(e)}", icon="❌")
                                with st.expander("错误详情"):
                                    st.code(traceback.format_exc())
                                
                                if 'save_id' in st.session_state:
                                    del st.session_state.save_id
                                    
                except json.JSONDecodeError:
                    st.error("文件格式错误，请上传有效的 JSON 文件", icon="❌")
                except Exception as e:
                    st.error(f"读取文件失败: {str(e)}", icon="❌")


        col1, col2 = st.columns([.3, 1.7], gap="small", vertical_alignment="center")
        with col1:
            st.markdown("或者，您也可以")
        
        with col2:
            if st.button("新建空白存档", key="int_create_new_save", icon="📄", width='stretch', disabled=not metadata_status,
                         help="您的包体（目前）未拥有谱面数据，请回到首页下载！" if not metadata_status else "如果您目前没有可用于生成存档的数据，可生成空白存档（作为占位）"):
                current_paths = get_data_paths(username, timestamp=None)
                save_dir = os.path.dirname(current_paths['data_file'])
                save_id = os.path.basename(save_dir)
                os.makedirs(save_dir, exist_ok=True)
                new_data = {
                    "clip_id": "Best_1",
                    "id": 1,
                    "song_name": "koko",
                    "artist": "先辈",
                    "score": 114514,
                    "rating": 1.919,
                    "level": 8.1,
                    "level_next": 8.2,
                    "level_index": 3,
                    "full_combo": None,
                    "full_chain": None,
                    "play_count": 0
                }
                with open(f'{save_dir}/b30_config.json', 'w', encoding='utf-8') as f:
                    print(f'[{json.dumps(new_data, ensure_ascii=False)}]', file=f)
                st.session_state.save_id = save_id
                st.session_state.data_updated_step1 = True
                st.session_state.config_saved = True
                st.success(f"已新建空白存档！用户名：{username}，存档时间：{save_id}", icon="✅")
                st.rerun()
        
    if st.session_state.get('data_updated_step1', False):
        st.divider()
        col1, col2 = st.columns(2, gap="small", vertical_alignment="center")
        with col1:
            st.write("确认数据无误后，前往下一步准备生成底图。")
        
        with col2:
            if st.button("下一步", icon="➡️", help="您需要获取谱面数据后才能继续，因为您的存档依靠此数据生成" if not metadata_status else "", width='stretch', disabled=not metadata_status):
                st.switch_page("st_pages/Generate_Pic_Resources.py")
else:
    st.warning("请先确定用户名！", icon="⚠️")