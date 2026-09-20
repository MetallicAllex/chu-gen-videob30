"""抓取设置区与 B 站扫码登录对话框。

搜索页（Step 2）与下载页合并后由视频页复用，避免设置控件和下载器参数映射在两处各写一份。
"""
import streamlit as st
import os, time, pickle
from utils.PathUtils import write_global_config
from utils.video_crawler import (BilibiliDownloader, PurePytubefixDownloader,
                                 BilibiliQrCodeLoginSession, create_downloader, load_credential)
from bilibili_api import sync, user

CREDENTIAL_PATH = "./cred_datas/bilibili_cred.pkl"

# 弹窗内自动轮询扫码结果的节奏。正常情况下轮询会自己走到终点（扫码成功或 B 站返回二维码过期
# 86038），这里的 170 秒只是防止用户走开时无限期等待的安全上限
LOGIN_POLL_SECONDS = 170
LOGIN_POLL_INTERVAL = 2

SETTING_KEYS = ('downloader', 'use_proxy', 'proxy_address', 'no_credential', 'download_high_res',
                'use_oauth', 'use_custom_po_token', 'use_auto_po_token', 'po_token', 'visitor_data',
                'use_youtube_api', 'youtube_api_key', 'search_max_results', 'search_scan_pages',
                'search_wait_time')


@st.dialog("Bilibili 扫码登录", width="small")
def bilibili_login_dialog():
    """Bilibili 二维码登录对话框：打开后自动轮询扫码结果，无需手动刷新"""
    def reset_session():
        for key in ['bili_dlg_session', 'bili_dlg_qr']:
            st.session_state.pop(key, None)

    def status_text(state, message):
        preset = {
            'waiting': '📱请使用哔哩哔哩客户端扫描此二维码',
            'confirmed': '❓️已扫描，请在手机上确认登录',
        }
        return f"当前：[{preset.get(state) or message}]"

    if 'bili_dlg_session' not in st.session_state:
        st.session_state.bili_dlg_session = BilibiliQrCodeLoginSession()

    session = st.session_state.bili_dlg_session

    # 生成二维码（首次打开时）
    if 'bili_dlg_qr' not in st.session_state:
        try:
            st.session_state.bili_dlg_qr = session.generate_qrcode()
        except Exception as e:
            st.error(f"生成二维码失败: {e}")
            return

    state, message = session.check_state()

    if state not in ('success', 'timeout'):
        st.image(st.session_state.bili_dlg_qr)
        status_slot = st.caption(status_text(state, message), text_alignment="center")

        deadline = time.time() + LOGIN_POLL_SECONDS
        while state not in ('success', 'timeout', 'error') and time.time() < deadline:
            time.sleep(LOGIN_POLL_INTERVAL)
            state, message = session.check_state()
            if state not in ('success', 'timeout', 'error'):
                status_slot.markdown(status_text(state, message))

        if state not in ('success', 'timeout', 'error'):
            status_slot.markdown(status_text(state, message) +
                                 "\n\n本轮自动检测到达时间上限。点下方按钮继续等待即可，二维码仍是同一张，无需重新扫码。")
            if st.button("继续检测", use_container_width=True, icon="🔄"):
                st.rerun()
            return

    if state == 'success':
        credential = session.get_credential()
        missing = [name for name, ok in (('SESSDATA', credential.has_sessdata()),
                                        ('bili_jct', credential.has_bili_jct())) if not ok]
        if missing:
            st.error(f"登录完成但未取到 {'、'.join(missing)}，请重新扫码", icon="❌")
            reset_session()
            return
        try:
            username = sync(user.get_self_info(credential))['name']
        except Exception as e:
            st.error(f"读取账号信息失败: {e}", icon="❌")
            reset_session()
            return

        os.makedirs("cred_datas", exist_ok=True)
        with open(CREDENTIAL_PATH, 'wb') as f:
            pickle.dump(credential, f)

        st.session_state.bilibili_logged_in = True
        reset_session()

        st.success(f"登录成功！当前账号：{username}", icon="✅")
        time.sleep(1)
        st.rerun()
    elif state == 'timeout':
        st.error("当前二维码已过期，请【重新获取】", icon="❌")
        if st.button("重新获取", use_container_width=True, icon="🔄", help="重新登入即可显示新的二维码"):
            reset_session()
            st.rerun()
    else:
        st.error(message, icon="❌")
        reset_session()
        if st.button("重新获取", use_container_width=True, icon="🔄"):
            st.rerun()


def credential_state():
    """B 站凭证文件的 (存在, 修改时间)：登录/登出后据此重建下载器，避免实例仍持有旧凭证"""
    if not os.path.exists(CREDENTIAL_PATH):
        return (False, 0)
    return (True, os.path.getmtime(CREDENTIAL_PATH))


def settings_from_config(G_config) -> dict:
    """从 global_config 读出一份默认设置"""
    return {
        'downloader': G_config.get('DOWNLOADER', 'bilibili'),
        'use_proxy': G_config.get('USE_PROXY', False),
        'proxy_address': G_config.get('PROXY_ADDRESS', '127.0.0.1:7890'),
        'no_credential': G_config.get('NO_BILIBILI_CREDENTIAL', False),
        'download_high_res': G_config.get('DOWNLOAD_HIGH_RES', True),
        'use_oauth': G_config.get('USE_OAUTH', False),
        'use_custom_po_token': G_config.get('USE_CUSTOM_PO_TOKEN', False),
        'use_auto_po_token': G_config.get('USE_AUTO_PO_TOKEN', False),
        'po_token': G_config.get('CUSTOMER_PO_TOKEN', {}).get('po_token', ''),
        'visitor_data': G_config.get('CUSTOMER_PO_TOKEN', {}).get('visitor_data', ''),
        'use_youtube_api': G_config.get('USE_YOUTUBE_API', False),
        'youtube_api_key': G_config.get('YOUTUBE_API_KEY', ''),
        'search_max_results': G_config.get('SEARCH_MAX_RESULTS', 5),
        'search_scan_pages': G_config.get('SEARCH_SCAN_PAGES', 2),
        'search_wait_time': G_config.get('SEARCH_WAIT_TIME', [5, 10]),
    }


def render_fetch_settings(G_config, settings=None) -> dict:
    """渲染抓取设置区，返回当前控件值组成的设置字典"""
    base = settings_from_config(G_config) if settings is None else dict(settings)
    with st.container(border=True):
        st.write("下载设置")
        col1, col2, col3 = st.columns([1, 0.35, 1.35], vertical_alignment="bottom")
        with col1:
            base['downloader'] = st.selectbox("谱面确认视频来源", ["bilibili", "youtube"],
                                              index=["bilibili", "youtube"].index(base['downloader']))
        with col2:
            base['use_proxy'] = st.checkbox("使用代理", value=base['use_proxy'],
                                            help="在搜索时使用代理，某些情况下可以概率绕过风控")
        with col3:
            base['proxy_address'] = st.text_input("输入代理地址", value=base['proxy_address'],
                                                  disabled=not base['use_proxy'], placeholder="默认 127.0.0.1:7890")

        if base['downloader'] == "bilibili":
            bili_col1, bili_col2 = st.columns([.35, 1.65], vertical_alignment="center")
            with bili_col1:
                base['download_high_res'] = st.checkbox(
                    "下载高分辨率视频", value=base['download_high_res'], disabled=base['no_credential'],
                    help="下载 720P+ 或 60FPS 的视频，这可让您的谱面确认视频更流畅"
                         if not base['no_credential'] else "游客无法下载超过 480P+ 的视频（因为您当前选择了[不登录 B 站账号]）")
                base['no_credential'] = st.checkbox("不登录 B 站账号", value=base['no_credential'],
                                                    help="不登录账号搜索（游客），某些情况下可以概率绕过风控")

            with bili_col2:
                cred_state = credential_state()
                if st.session_state.get('bilibili_cred_state') != cred_state or 'bilibili_logged_in' not in st.session_state:
                    st.session_state.bilibili_cred_state = cred_state
                    st.session_state.bilibili_logged_in = load_credential(CREDENTIAL_PATH)[0] is not None

                if not base['no_credential']:
                    if st.session_state.bilibili_logged_in:
                        st.success("已登录 Bilibili 账号（如果您的显示状态有问题，请以控制台实际输出为准）", icon="✅")
                        if st.button("登出", key="bilibili_logout", icon="🚪", width="stretch"):
                            if os.path.exists(CREDENTIAL_PATH):
                                os.remove(CREDENTIAL_PATH)
                            st.session_state.bilibili_logged_in = False
                            st.rerun()
                    else:
                        st.error("未登录 Bilibili 账号（本地凭证缺失或已失效），请扫码登录", icon="❎")
                        if st.button("登入", key="bilibili_login_btn", type="primary", icon="🔐", width="stretch"):
                            bilibili_login_dialog()

                if base['no_credential']:
                    st.info("二维码首次无法登录，请在弹出后关闭，待重新登录的二维码弹出后再扫描登录。", icon="ℹ️")

        elif base['downloader'] == "youtube":
            ytb_col1, ytb_col2 = st.columns(2)
            with ytb_col1:
                base['use_youtube_api'] = st.checkbox(
                    "使用 YouTube Data API v3 搜索", value=base['use_youtube_api'],
                    help="使用官方 API 进行搜索，更稳定可靠。需要配置 API Key。")

            if base['use_youtube_api']:
                base['youtube_api_key'] = st.text_input("YouTube API Key", value=base['youtube_api_key'],
                                                        type="password", help="在 Google Cloud Console 创建 API Key")
                if not base['youtube_api_key']:
                    st.warning("请配置 YouTube API Key 以使用 API 搜索功能", icon="⚠️")
            else:
                base['youtube_api_key'] = ''
                with ytb_col2:
                    base['use_oauth'] = st.checkbox("使用 OAuth 登录", value=base['use_oauth'])

                token_col1, token_col2 = st.columns([.5178, 1.491])
                with token_col1:
                    po_token_mode = st.radio(
                        "PO Token 设置", options=["不使用", "自定义", "自动获取"],
                        captions=["不使用 Token", "自定义 Token 和 Data", ""],
                        index=0 if not (base['use_custom_po_token'] or base['use_auto_po_token'])
                            else 1 if base['use_custom_po_token'] else 2,
                        disabled=base['use_oauth'])
                    base['use_custom_po_token'] = (po_token_mode == "自定义")
                    base['use_auto_po_token'] = (po_token_mode == "自动获取")
                if base['use_custom_po_token']:
                    with token_col2:
                        base['po_token'] = st.text_input("输入自定义 PO Token", value=base['po_token'])
                        base['visitor_data'] = st.text_input("输入自定义 Visitor Data", value=base['visitor_data'])

        st.divider()
        st.write("搜索设置")
        search_col1, search_col2, search_col3 = st.columns([.5, .5, 1.3])
        with search_col1:
            base['search_max_results'] = st.number_input(
                "保留候选条数", value=base['search_max_results'], min_value=1, max_value=20,
                help="每次搜索扫描出的候选按曲名与难度排名后，保留前几条作为备选")
        with search_col2:
            base['search_scan_pages'] = st.number_input(
                "扫描页数", value=base['search_scan_pages'], min_value=1, max_value=3,
                help="每页向平台请求 50 条结果；加一页就多一次请求，更容易触发风控")
        with search_col3:
            base['search_wait_time'] = st.select_slider("搜索间隔时间", options=range(1, 60),
                                                        value=base['search_wait_time'],
                                                        help="在此范围内的随机一个数。有概率绕过风控")

    return {key: base[key] for key in SETTING_KEYS}


def settings_fingerprint(settings) -> tuple:
    """控件值与已生效配置的比较指纹：列表统一成元组，避免 [5, 10] 与 (5, 10) 判为不等"""
    fingerprint = []
    for key in SETTING_KEYS:
        value = settings.get(key)
        fingerprint.append(tuple(value) if isinstance(value, list) else value)
    return tuple(fingerprint)


def apply_fetch_settings(G_config, settings) -> dict:
    """把设置字典写回 global_config 并返回更新后的配置"""
    G_config['DOWNLOADER'] = settings['downloader']
    G_config['USE_PROXY'] = settings['use_proxy']
    G_config['PROXY_ADDRESS'] = settings['proxy_address']
    G_config['NO_BILIBILI_CREDENTIAL'] = settings['no_credential']
    G_config['DOWNLOAD_HIGH_RES'] = settings['download_high_res']

    if settings['downloader'] == "youtube":
        G_config['USE_YOUTUBE_API'] = settings['use_youtube_api']
        G_config['YOUTUBE_API_KEY'] = settings['youtube_api_key']
        if not settings['use_youtube_api']:
            G_config['USE_OAUTH'] = settings['use_oauth']
            if not settings['use_oauth']:
                G_config['USE_CUSTOM_PO_TOKEN'] = settings['use_custom_po_token']
                G_config['USE_AUTO_PO_TOKEN'] = settings['use_auto_po_token']
                G_config['CUSTOMER_PO_TOKEN'] = {'po_token': settings['po_token'],
                                                 'visitor_data': settings['visitor_data']}

    G_config['SEARCH_MAX_RESULTS'] = settings['search_max_results']
    G_config['SEARCH_SCAN_PAGES'] = settings['search_scan_pages']
    G_config['SEARCH_WAIT_TIME'] = list(settings['search_wait_time'])
    write_global_config(G_config)
    return G_config


def init_downloader(settings):
    """构造下载器并提示登录账号；失败时抛出异常由调用方展示"""
    if settings['downloader'] == "youtube":
        st.toast("正在初始化 YouTube 下载器...", icon="ℹ️")
        if settings['use_youtube_api']:
            st.toast("使用 YouTube Data API v3 进行搜索...", icon="ℹ️")
        elif settings['use_oauth'] and not (settings['use_custom_po_token'] or settings['use_auto_po_token']):
            st.toast("使用 OAuth 登录...请点击控制台窗口输出的链接进行登录", icon="ℹ️")
    elif settings['downloader'] == "bilibili":
        st.toast("正在初始化 Bilibili 下载器...", icon="ℹ️")
    else:
        st.error("未配置正确的下载器，请重新确定上方配置！", icon="❌")
        return None

    dl_instance = create_downloader(settings)
    if isinstance(dl_instance, BilibiliDownloader):
        bilibili_username = dl_instance.get_credential_username()
        if bilibili_username:
            st.toast(f"登录成功，当前登录账号为：{bilibili_username}", icon="✅")
    return dl_instance
