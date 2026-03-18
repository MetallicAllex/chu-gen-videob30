import streamlit as st
from datetime import datetime
from utils.PathUtils import *
import os, time, shutil, random, traceback
from utils.Variables import REVERSE_LEVEL_LABELS
from utils.DataUtils import search_one_video, merge_b50_data
from utils.video_crawler import PurePytubefixDownloader, BilibiliDownloader, load_credential, streamlit_login_bilibili

G_config = read_global_config()
_downloader = G_config.get('DOWNLOADER', 'bilibili')
_use_proxy = G_config.get('USE_PROXY', False)
_proxy_address = G_config.get('PROXY_ADDRESS', '127.0.0.1:7890')
_no_credential = G_config.get('NO_BILIBILI_CREDENTIAL', False)
_use_custom_po_token = G_config.get('USE_CUSTOM_PO_TOKEN', False)
_use_auto_po_token = G_config.get('USE_AUTO_PO_TOKEN', False)
_use_oauth = G_config.get('USE_OAUTH', False)
_customer_po_token = G_config.get('CUSTOMER_PO_TOKEN', '')
# 新增 YouTube API 配置
_use_youtube_api = G_config.get('USE_YOUTUBE_API', False)
_youtube_api_key = G_config.get('YOUTUBE_API_KEY', '')

st.header("Step 2: 谱面确认视频搜索和抓取")

### Savefile Management - Start ###
if "username" in st.session_state:
    st.session_state.username = st.session_state.username

if "save_id" in st.session_state:
    st.session_state.save_id = st.session_state.save_id

username = st.session_state.get("username", None)
save_id = st.session_state.get("save_id", None)
current_paths = None
data_loaded = False

if not username:
    st.error("请先获取 Best50 存档！", icon="❌")
    st.stop()

with st.container(border=True):
    if save_id:
        # load save data
        current_paths = get_data_paths(username, save_id)
        data_loaded = True
        # st.write(f"当前存档【用户名：{username}，存档时间：{save_id}】")
        # 方案2：指标卡片式显示
        info_col1, info_col2 = st.columns([1.15, .85])
        with info_col1:
            st.metric(
                label="👤 当前用户",
                value=username
            )
        with info_col2:
            st.metric(
                label="⏰ 存档时间", 
                value=save_id
            )
    else:
        st.warning("未索引到存档，请先加载存档数据！", icon="⚠️")

    with st.expander("更换 Best50 存档", icon="💾"):
        st.info("如果要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
        versions = get_user_versions(username)
        if versions:
            save_col1, save_col2 = st.columns([1.25, .75])
            with save_col1:
                selected_save_id = st.selectbox(
                    "选择存档", versions, label_visibility="collapsed",
                    # format_func=lambda x: f"{x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
                    format_func=lambda x: f"{x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
                )
            with save_col2:
                if st.button("使用此存档", help="（只需要点击一次！）", width='stretch', icon="▶️"):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        st.rerun()
                    else:
                        st.error("存档路径无效！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
            st.stop()
### Savefile Management - End ###

st.divider()
st.write("视频抓取设置")
# 初始化下载器变量
no_credential = _no_credential
use_oauth = _use_oauth
use_custom_po_token = _use_custom_po_token
use_auto_po_token = _use_auto_po_token
po_token = _customer_po_token.get('po_token', '')
visitor_data = _customer_po_token.get('visitor_data', '')
# 新增 YouTube API 变量
use_youtube_api = _use_youtube_api
youtube_api_key = _youtube_api_key

extra_setting_container = st.container(border=True)
with extra_setting_container:
    st.write("下载设置")
    # 选择下载器
    col1, col2, col3 = st.columns([1, 0.35, 1.35], vertical_alignment="bottom")
    with col1:
        default_index = ["bilibili", "youtube"].index(_downloader)
        downloader = st.selectbox("谱面确认视频来源", ["bilibili", "youtube"], index=default_index)
    with col2:
        # 选择是否启用代理
        use_proxy = st.checkbox("使用代理", value=_use_proxy, help="在搜索时使用代理，某些情况下可以概率绕过风控")
    with col3:
        # 输入代理地址，默认值为127.0.0.1:7890
        proxy_address = st.text_input("输入代理地址", value=_proxy_address, disabled=not use_proxy, placeholder="默认 127.0.0.1:7890")
    
    if downloader == "bilibili":
        bili_col1, bili_col2 = st.columns([.35, 1.65], vertical_alignment="center")
        with bili_col1:
            _download_high_res = G_config.get('DOWNLOAD_HIGH_RES', True)
            download_high_res = st.checkbox("下载高分辨率视频", value=_download_high_res, disabled=no_credential, help="下载 720P+ 或 60FPS 的视频，这可让您的谱面确认视频更流畅" if not no_credential else "游客无法下载超过 480P+ 的视频（因为您当前选择了[不登录 B 站账号]）")
        
        # with bili_col2:
            no_credential = st.checkbox("不登录 B 站账号", value=_no_credential, help="不登录账号搜索（游客），某些情况下可以概率绕过风控")
    
        with bili_col2:
            # 登录状态管理
            if 'bilibili_logged_in' not in st.session_state:
                # 检查是否有缓存的凭证
                cached_cred = load_credential("./cred_datas/bilibili_cred.pkl")
                st.session_state.bilibili_logged_in = cached_cred is not None
            
            if not no_credential:
                # st.markdown("---")
                if st.session_state.bilibili_logged_in:
                    st.success("已登录 Bilibili 账号", icon="✅")
                    if st.button("登出", key="bilibili_logout", icon="🚪", width="stretch"):
                        # 删除凭证文件
                        cred_path = "./cred_datas/bilibili_cred.pkl"
                        if os.path.exists(cred_path):
                            os.remove(cred_path)
                        st.session_state.bilibili_logged_in = False
                        st.rerun()
                else:
                    st.error("未登录 Bilibili 账号", icon="❎")
                    if st.button("登入", key="bilibili_login_btn", type="primary", icon="🔐", width="stretch"):
                        st.session_state.bilibili_show_qr = True
                        st.rerun()
                    
                    # 显示二维码登录流程
                    if st.session_state.get('bilibili_show_qr', False):
                        success, credential, message, username = streamlit_login_bilibili("./cred_datas/bilibili_cred.pkl")
                        
                        if success:
                            st.session_state.bilibili_logged_in = True
                            st.session_state.bilibili_show_qr = False
                            st.session_state.bilibili_username = username
                            st.success(message, icon="✅")
                            st.rerun()
                        elif credential is None and ("等待" in message or "扫描" in message or "确认" in message):
                            # 需要继续轮询
                            st.rerun()
                        else:
                            # 出错或超时
                            if "过期" in message or "失败" in message:
                                st.session_state.bilibili_show_qr = False
                                st.error(message, icon="❌")
                                st.info("请重新点击登录按钮", icon="ℹ️")

        # with bili_col2:
        #     _download_high_res = G_config.get('DOWNLOAD_HIGH_RES', True)
        #     download_high_res = st.checkbox("下载高分辨率视频", value=_download_high_res, disabled=no_credential, help="下载 720P+ 或 60FPS 的视频，这可让您的谱面确认视频更流畅" if not no_credential else "游客无法下载超过 480P+ 的视频（因为您当前选择了[不登录 B 站账号]）")
        if no_credential:
            st.info("二维码首次无法登录，请在弹出后关闭，待重新登录的二维码弹出后再扫描登录。", icon="ℹ️")
    elif downloader == "youtube":
        # 新增 YouTube API 选项
        ytb_col1, ytb_col2 = st.columns(2)
        with ytb_col1:
            use_youtube_api = st.checkbox(
                "使用 YouTube Data API v3 搜索", 
                value=_use_youtube_api,
                help="使用官方 API 进行搜索，更稳定可靠。需要配置 API Key。"
            )
        
        if use_youtube_api:
            youtube_api_key = st.text_input(
                "YouTube API Key",
                value=_youtube_api_key,
                type="password",
                help="在 Google Cloud Console 创建 API Key"
            )
            if not youtube_api_key:
                st.warning("⚠️ 请配置 YouTube API Key 以使用 API 搜索功能")
        else:
            youtube_api_key = ''
            with ytb_col2:
                use_oauth = st.checkbox("使用 OAuth 登录", value=_use_oauth)
            
            token_col1, token_col2 = st.columns([.5178, 1.491])
            with token_col1:
                po_token_mode = st.radio(
                    "PO Token 设置",
                    options=["不使用", "自定义", "自动获取"],
                    captions=["不使用 Token", "自定义 Token 和 Data", ""],
                    index=0 if not (_use_custom_po_token or _use_auto_po_token) 
                        else 1 if _use_custom_po_token 
                        else 2,
                    disabled=use_oauth
                )
                use_custom_po_token = (po_token_mode == "自定义")
                use_auto_po_token = (po_token_mode == "自动获取")
            if use_custom_po_token:
                _po_token = _customer_po_token.get('po_token', '')
                _visitor_data = _customer_po_token.get('visitor_data', '')
                with token_col2:
                    po_token = st.text_input("输入自定义 PO Token", value=_po_token)
                    visitor_data = st.text_input("输入自定义 Visitor Data", value=_visitor_data)

    st.divider()
    st.write("搜索设置")
    _search_max_results = G_config.get('SEARCH_MAX_RESULTS', 3)
    _search_wait_time = G_config.get('SEARCH_WAIT_TIME', [5, 10])
    search_col1, search_col2 = st.columns([.5, 1.5])
    with search_col1:
        search_max_results = st.number_input("备选搜索结果数", value=_search_max_results, min_value=1, max_value=10)
    with search_col2:
        search_wait_time = st.select_slider("搜索间隔时间", options=range(1, 60), value=_search_wait_time, help="在此范围内的随机一个数。有概率绕过风控")

col1, col2 = st.columns([1, 1], gap="small")
with col1:
    if st.button("保存配置", width='stretch', icon="💾"):
        G_config['DOWNLOADER'] = downloader
        G_config['USE_PROXY'] = use_proxy
        G_config['PROXY_ADDRESS'] = proxy_address
        G_config['NO_BILIBILI_CREDENTIAL'] = no_credential
        
        # YouTube 相关配置
        if downloader == "youtube":
            G_config['USE_YOUTUBE_API'] = use_youtube_api
            G_config['YOUTUBE_API_KEY'] = youtube_api_key
            if not use_youtube_api:
                G_config['USE_OAUTH'] = use_oauth
                if not use_oauth:
                    G_config['USE_CUSTOM_PO_TOKEN'] = use_custom_po_token
                    G_config['USE_AUTO_PO_TOKEN'] = use_auto_po_token
                    G_config['CUSTOMER_PO_TOKEN'] = {
                        'po_token': po_token,
                        'visitor_data': visitor_data
                    }
        
        G_config['SEARCH_MAX_RESULTS'] = search_max_results
        G_config['SEARCH_WAIT_TIME'] = search_wait_time
        G_config['DOWNLOAD_HIGH_RES'] = download_high_res
        
        write_global_config(G_config)
        st.toast("配置已保存！", icon="✅")
        st.session_state.config_saved_step2 = True  # 添加状态标记
        st.session_state.downloader_type = downloader

def st_init_downloader():
    global downloader, no_credential, use_oauth, use_custom_po_token, use_auto_po_token, po_token, visitor_data
    global use_youtube_api, youtube_api_key  # 新增

    if downloader == "youtube":
        st.toast("正在初始化 YouTube 下载器...", icon="ℹ️")
        
        if use_youtube_api:
            st.toast("使用 YouTube Data API v3 进行搜索...", icon="ℹ️")
            dl_instance = PurePytubefixDownloader(
                proxy=proxy_address if use_proxy else None,
                use_potoken=False,
                use_oauth=False,
                auto_get_potoken=False,
                search_max_results=search_max_results,
                use_api=True,                    # 新增：启用 API
                api_key=youtube_api_key          # 新增：API Key
            )
        else:
            use_potoken = use_custom_po_token or use_auto_po_token
            if use_oauth and not use_potoken:
                st.toast("使用 OAuth 登录...请点击控制台窗口输出的链接进行登录", icon="ℹ️")
            dl_instance = PurePytubefixDownloader(
                proxy=proxy_address if use_proxy else None,
                use_potoken=use_potoken,
                use_oauth=use_oauth,
                auto_get_potoken=use_auto_po_token,
                search_max_results=search_max_results,
                use_api=False,                   # 明确关闭 API
                api_key=None                     # 无 API Key
            )

    elif downloader == "bilibili":
        st.toast("正在初始化 Bilibili 下载器...", icon="ℹ️")
        if not no_credential:
            st.toast("正在尝试登录... 如弹出二维码窗口，请使用 哔哩哔哩 客户端扫描进行登录", icon="ℹ️")
        dl_instance = BilibiliDownloader(
            proxy=proxy_address if use_proxy else None,
            no_credential=no_credential,
            credential_path="./cred_datas/bilibili_cred.pkl",
            search_max_results=search_max_results
        )
        bilibili_username = dl_instance.get_credential_username()
        if bilibili_username:
            st.toast(f"登录成功，当前登录账号为：{bilibili_username}", icon="✅")
    else:
        st.error(f"未配置正确的下载器，请重新确定上方配置！", icon="❌")
        return None
    
    return dl_instance

# b50 config文件位置
b50_data_file = current_paths['data_file']
# 根据下载器类型的b30_config副本
if downloader == "youtube":
    b50_config_file = current_paths['config_yt']
elif downloader == "bilibili":
    b50_config_file = current_paths['config_bi']

if not os.path.exists(b50_data_file):
    st.error("未找到 b50 数据文件，请检查 Best50 存档的数据完整性！", icon="❌")
    st.stop()

if not os.path.exists(b50_config_file):
    # 复制b30_data_file到b30_config_file
    shutil.copy(b50_data_file, b50_config_file)
    st.toast(f"已生成 {downloader} 的 Best50 索引文件", icon="ℹ️")

# 对比以及合并 b30_data_file 和 b30_config_file
b50_data = load_config(b50_data_file)
b50_config = load_config(b50_config_file)
merged_b50_config, update_count = merge_b50_data(b50_data, b50_config)
save_config(b50_config_file, merged_b50_config)
if update_count > 0:
    st.toast(f"已加载 {downloader} 的 Best50 索引，共更新 {update_count} 条数据", icon="✅")

def search_b50_videos(dl_instance, placeholder, search_wait_time):
    # read b50_data
    b50_config = load_config(b50_config_file)
    total_songs = len(b50_config)  # 获取实际歌曲数量

    with placeholder.container(border=False, height=450):
        with st.spinner(f"正在搜索 b{total_songs} 视频信息..."):
            progress_bar = st.progress(0)
            write_container = st.container(border=True)
            
            for i, song in enumerate(b50_config, 1):  # 从1开始计数
                # 使用 min() 确保进度值不超过 1.0
                progress_value = min(i / total_songs, 1.0)
                progress_bar.progress(progress_value, text=f"正在搜索［{i}/{total_songs}］ → {song['song_name']} [{REVERSE_LEVEL_LABELS.get(song['level_index'])}]")
                
                if 'video_info_match' in song and song['video_info_match']:
                    write_container.write(f"({i}/{total_songs}[跳过])：{song['song_name']}（已储存有相关视频信息）")
                    continue
                
                song_data, ouput_info = search_one_video(dl_instance, song)
                write_container.write(f"［{i}/{total_songs}］{ouput_info}")
                # write_container.write(f"{song_data}") # debug

                # 每次搜索后都写入b50_data_file
                save_config(b50_config_file, b50_config)
                
                # 等待几秒，以减少被检测为bot的风险
                if search_wait_time[0] > 0 and search_wait_time[1] > search_wait_time[0]:
                    time.sleep(random.randint(search_wait_time[0], search_wait_time[1]))
            
            # 搜索完成后显示100%
            progress_bar.progress(1.0, text="搜索完成！")

# 仅在配置已保存时显示搜索控件
if st.session_state.get('config_saved_step2', False):
    # 添加跳过搜索的提示和按钮
    with st.expander("跳过自动搜索", icon="⤴️"):
        st.warning("""
                   如果您遇到自动搜索失败 / 大多数谱面搜索不正确的问题
                   - 多半与第三方查询接口有关，**难以立刻修复**
                        - 请考虑到下一页 *手动输入谱面视频 BV 号*
                        - 或者提供几个应对办法：
                            - 等待至少 24 小时 / 拉宽搜索间隔时间
                            - 尝试不登录账号搜索（很玄学但有时也可行）
                            - 更换当前网络环境（任何方法都行，有 IPv6 更好）
                   """, icon="⚠️")
        if st.button("跳过自动搜索", icon="⤴️", width='stretch'):
            dl_instance = st_init_downloader()
            # 缓存downloader对象
            st.session_state.downloader = dl_instance
            st.switch_page("st_pages/3_Confirm_Videoes.py")
            
    st.session_state.search_completed = False
    if st.button("开始搜索", width='stretch', icon="🔍", type="primary"):
        info_container = st.expander("搜索日志", icon="🔍")
        # with info_container:
        #     info_placeholder = st.empty()
        try:
            dl_instance = st_init_downloader()
            # 缓存downloader对象
            st.session_state.downloader = dl_instance
            search_b50_videos(dl_instance, info_container, search_wait_time)
            st.session_state.search_completed = True  # Reset error flag if successful
            st.toast("搜索完成！请前往下一步检查视频信息，以及下载视频。", icon="✅")
            st.toast("如果站点存在此视频，但下载器未找到，请尝试重新搜索多几次。", icon="⚠️")
        except Exception as e:
            st.session_state.search_completed = False
            st.toast(f"发生错误：{e}, 请尝试重新搜索（详细错误信息显示在页面底部）", icon="❌")
            st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❗")
    
    with col2:
        if st.button("下一步", disabled=not st.session_state.search_completed, width='stretch', icon="➡️"):
            st.switch_page("st_pages/3_Confirm_Videos.py")
else:
    st.warning("请先保存配置！", icon="⚠️")  # 如果未保存配置，给出提示