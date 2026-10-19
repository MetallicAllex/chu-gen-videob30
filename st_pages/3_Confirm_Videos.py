import streamlit as st
from datetime import datetime
from utils.PathUtils import *
import shutil, time, random, traceback, os, re
from typing import cast
from utils.DataUtils import (download_one_video, search_one_video, merge_b50_data,
                            rank_video_candidates, video_match_warning, apply_playlist_matches,
                            migrate_search_args,
                            is_video_cached, load_video_cache_index)
from utils.Variables import REVERSE_LEVEL_LABELS, VIDEO_LISTS
from utils.PageUtils import escape_markdown_text
from utils.fetch_settings import (render_fetch_settings, apply_fetch_settings, settings_from_config,
                                  settings_fingerprint, init_downloader, credential_state)
from utils.video_crawler import Downloader

G_config = read_global_config()

st.header("Step 2: 谱面确认视频搜索、检查与下载")

### Savefile Management - Start ###
if "username" in st.session_state:
    st.session_state.username = st.session_state.username

if "save_id" in st.session_state:
    st.session_state.save_id = st.session_state.save_id

username = st.session_state.get("username", None)
save_id = st.session_state.get("save_id", None)
# 声明成 dict 而不是 None：这是模块级变量，函数与 @st.fragment 里读到的是它的
# **声明类型**，判空守卫的窄化带不进那些作用域——保持 None 的话每处
# current_paths['x'] 都要再摊一条"None 不可下标"（实测 7 页 37 条）。
# get_data_paths 永远返回非空 dict，所以拿不到存档时它就是下面的空 dict，
# 各页的 `not current_paths` 守卫照样拦得住。
current_paths: dict = {}
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
        st.warning("未索引到存档，请先加载存档数据！")

    with st.expander("更换 Best50 存档", icon="💾"):
        st.info("如果要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
        versions = get_user_versions(username)
        if versions:
            save_col1, save_col2 = st.columns([1.25, .75])
            with save_col1:
                selected_save_id = st.selectbox(
                    "选择存档", versions, label_visibility="collapsed",
                    format_func=lambda x: f"{x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
                )
            with save_col2:
                if st.button("使用此存档", help="（只需要点击一次！）", width='stretch', icon="▶️"):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        # 清除旧的匹配状态，强制重新初始化。控件的会话键必须一起清：
                        # record_selector 里存着上一份存档的曲目字符串，新存档的 options 里没有它，
                        # Streamlit 恢复旧值时会直接抛；refresh_cache 是不带 clip_id 的全局键，同理串档。
                        song_status = ['matched_count', 'unmatched_count', 'total_songs', 'current_index',
                                       'download_completed', 'record_selector', 'refresh_cache']
                        for song_key in song_status:
                            st.session_state.pop(song_key, None)
                        st.rerun()
                    else:
                        st.error("存档路径无效！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
            st.stop()
### Savefile Management - End ###

# 后面每一环都要用 current_paths['config_yt'] 之类。以前这里只 warning 不中止，最后崩在
# 对 None 取下标上（TypeError: 'NoneType' object is not subscriptable），用户看到的是整页
# traceback 而不是"先选一份存档"。放在更换存档的折叠栏之后，保证这里仍来得及直接选一份。
if not current_paths:
    st.stop()

def get_web_search_url(song_data, dl_type):
    """生成网页搜索URL"""
    title_name = song_data['song_name']
    difficulty_name = REVERSE_LEVEL_LABELS.get(song_data['level_index'])
    keyword = f"{title_name} {difficulty_name} 谱面确认"
    
    from urllib.parse import quote
    keyword = quote(keyword)
    if dl_type == "youtube":
        return f"https://www.youtube.com/results?search_query={keyword}"
    elif dl_type == "bilibili":
        return f"https://search.bilibili.com/all?keyword={keyword}"
    else:
        return ""

@st.dialog("分p视频指定", width="large")
def change_video_page(cur_song_data, cur_p_index):
    st.info("请选择对应您的曲目的谱面确认分 p，如果没有，请尝试重新搜索。", icon="ℹ️")

    try:
        page_info = dl_instance.get_video_pages(cur_song_data['video_info_match']['id'])
        page_options = []
        for i, page in enumerate(page_info):
            if 'part' in page and 'duration' in page:
                page_options.append(f"P{i + 1}: {page['part']} ({page['duration']}秒)")

        selected_p_index = st.radio(
            "请选择:",
            options=range(len(page_options)),
            format_func=lambda x: page_options[x],
            index=cur_p_index,
            key=f"radio_select_page_{cur_song_data['clip_id']}",
            label_visibility="collapsed"
        )

        if st.button("更新", key=f"confirm_selected_page_{cur_song_data['clip_id']}", width='stretch', icon="🔄️"):
            cur_song_data['video_info_match']['p_index'] = selected_p_index
            cur_song_data['video_info_match']['page_count'] = len(page_info)
            save_config(b30_config_file, b30_config)
            st.rerun()
    except Exception as e:
        st.error(f"获取分P信息失败: {e}", icon="❌")

def video_part_link(video_info):
    """(链接, 文案)：多P视频必须带上 ?p= ，否则跳转只会落到第 1 P

    搜索来的候选没有 page_count，但用户用过「修改分P视频」后会有 p_index，两种都算。
    """
    url = video_info.get('url', '')
    page_count = video_info.get('page_count') or 0
    p_index = video_info.get('p_index') or 0
    if page_count > 1 or p_index > 0:
        return f"{url}/?p={p_index + 1}", f"P{p_index + 1}链接"
    return url, "打开视频"

def update_match_info(placeholder, video_info):
    """增强的视频信息展示"""
    with placeholder.container():
        # 基础信息展示 - 改进的格式
        id = video_info['id']
        title = escape_markdown_text(video_info['title'])
        st.markdown(f"**📺 视频标题：** {title}")
        
        p_index = video_info['p_index'] if 'p_index' in video_info else 0
        link_url, link_label = video_part_link(video_info)
        info_col1, info_col2, info_col3 = st.columns(3)
        with info_col1:
            st.markdown(f"**⏱️ 总时长：** {video_info['duration']} 秒")
        with info_col2:
            page_count = video_info.get('page_count') or 0
            st.markdown(f"**📑 分P序号：** p{p_index + 1}" + (f" / 共 {page_count} P" if page_count > 1 else ""))
        with info_col3:
            st.markdown(f"**🔗 视频链接：** [{link_label}]({link_url})")
        
        # 显示修改分P按钮
        if st.button("修改分P视频", key=f"change_p_{id}", width='stretch'):
            change_video_page({'video_info_match': video_info, 'clip_id': id}, p_index)

def polite_wait(search_wait_time, attempted):
    """向平台发过请求就要隔一段再发下一次；纯缓存命中没发请求，不用等。

    旧写法只在下载成功时等待，于是"连续失败"反而变成零间隔连打接口 —— 恰恰是最需要退避
    的场景（风控期越敲越糟）。区间两端相等时 randint 也能取到该值，所以只看下限。
    """
    if attempted and search_wait_time[0] > 0:
        time.sleep(random.randint(search_wait_time[0], search_wait_time[1]))

def st_download_video(placeholder, dl_instance, settings, b30_config):
    """批量下载。settings 必须是"下载器实际按它构造"的那份（saved_settings）：
    以前这里读 G_config（磁盘），而批量搜索读控件值（可能还没保存），于是间隔时间按新值
    生效、扫描页数与候选条数按旧值生效 —— 同一个页面上两套参数口径，用户以为改了其实没改。
    """
    search_wait_time = settings['search_wait_time']
    download_high_res = settings['download_high_res']
    video_download_path = DOWNLOADS_DIR
    
    os.makedirs(video_download_path, exist_ok=True)
    
    with placeholder.container(border=True):
        with st.spinner("正在下载视频……"):
            progress_bar = st.progress(0)
            write_container = st.container(border=True, height=400)
            total_songs = len(b30_config)
            failed_songs = []
            # 整批共用一份缓存索引：命中判断与下载后的记录更新都作用在这份字典上
            cache_index = load_video_cache_index()
            
            for i, song in enumerate(b30_config, 1):
                progress_value = min(i / total_songs, 1.0)
                
                if 'video_info_match' not in song or not song['video_info_match']:
                    write_container.write(f"❌［{i}/{total_songs}］跳过 →  {song['song_name']}：无视频信息")
                    continue
                
                # video_info = song['video_info_match']
                # title = escape_markdown_text(video_info['title'])
                
                # 更好的进度文本
                progress_bar.progress(progress_value, text=f"下载进度［{i}/{total_songs}］ →  {song['song_name']}")
                
                # 缓存检查：文件在且与当前选定的视频/分P一致才算命中（换候选或改分P后旧文件会自动重下）
                if is_video_cached(song, video_download_path, cache_index):
                    write_container.write(f"☑️［{i}/{total_songs}］已缓存 →  {song['song_name']}")
                    continue
                
                # 下载视频
                result = download_one_video(dl_instance, song, video_download_path, download_high_res,
                                            cache_index=cache_index)
                
                # 更好的结果展示
                if result['status'] == 'success':
                    write_container.write(f"✅［{i}/{total_songs}］下载成功 →  {song['song_name']}")
                else:
                    write_container.write(f"❌［{i}/{total_songs}］下载失败 →  {song['song_name']}: {result['info']}")
                    failed_songs.append((song['song_name'], result['info']))

                # 缓存命中在上面已经 continue，走到这里就是真发过一次下载请求
                polite_wait(search_wait_time, True)

            # 放行判据只认"本地确有可用素材"，不能拿"整批循环没抛异常"当成功：用户机器 PATH 上没有
            # ffmpeg 时，B 站 50 首会全部停在「未生成有效视频文件」，旧写法照样解锁了「下一步」。
            # 复用 is_video_cached 这条正典判据（文件非零字节 + 来源与当前选定一致），与缓存检查、
            # 页 4 的素材扫描同一口径。
            ready_count = sum(1 for song in b30_config
                              if song.get('video_info_match')
                              and is_video_cached(song, video_download_path, cache_index))

            failed_names = '、'.join(name for name, _ in failed_songs)
            if not ready_count:
                st.error(
                    f"下载结束，本地没有任何可用素材（{len(failed_songs)} 首失败），「下一步」保持锁定。\n\n"
                    f"- 首条失败原因：{failed_songs[0][1] if failed_songs else '没有曲目带有可用的视频信息'}\n"
                    f"- 整批全部失败最常见的原因是本机没有可用的 ffmpeg（B 站两条分辨率分支都要过它封装），"
                    f"请把 `utils/video_crawler.py` 更新到最新版，或把 `ffmpeg.exe` 放进应用目录后重试\n"
                    f"- 其余排查见 README「常见问题 - 视频抓取相关」",
                    icon="❌"
                )
            elif failed_songs:
                st.warning(
                    f"下载完成，可用素材 {ready_count}/{total_songs}，有 {len(failed_songs)} 首失败：{failed_names}\n\n"
                    f"可重新点击下载重试（已下载的视频会自动跳过），或在上方编辑器为这些曲目重新搜索、更换候选视频。"
                    f"缺的素材在【编辑 Best50 视频片段】生成配置时会被逐条拦下。",
                    icon="⚠️"
                )
            else:
                st.success("下载完成！请点击下一步按钮核对视频素材的详细信息。", icon="✅")

    return ready_count

def st_search_all_videos(dl_instance, placeholder, search_wait_time, config_file):
    """批量搜索缺少视频信息的曲目，每搜完一首立即落盘，中断后可从下一首继续"""
    b30_config = load_config(config_file)
    total_songs = len(b30_config)

    with placeholder.container(border=True, height=450):
        with st.spinner(f"正在搜索 {total_songs} 首曲目的视频信息..."):
            progress_bar = st.progress(0)

            for i, song in enumerate(b30_config, 1):
                progress_bar.progress(min(i / total_songs, 1.0),
                                      text=f"正在搜索［{i}/{total_songs}］ →  {song['song_name']}"
                                           f" [{REVERSE_LEVEL_LABELS.get(song['level_index'])}]")

                if song.get('video_info_match'):
                    st.write(f"☑️［{i}/{total_songs}］已跳过 →  {song['song_name']}（已有视频信息）")
                    continue

                _, output_info = search_one_video(dl_instance, song)
                st.write(f"🔍［{i}/{total_songs}］{output_info}")

                save_config(config_file, b30_config)

                # 与下载环节同一套等待判定：发过请求就退避
                polite_wait(search_wait_time, True)

            progress_bar.progress(1.0, text="搜索完成！")

def check_matched_songs(config):
    """检查已匹配视频信息的歌曲"""
    matched_count = 0
    unmatched_count = 0
    unmatched_names = []
    
    for song in config:
        if song.get('video_info_match'):
            matched_count += 1
        else:
            unmatched_count += 1
            unmatched_names.append(song['song_name'])
    
    return matched_count, unmatched_count, unmatched_names

def update_editor(placeholder, config, current_index, dl_instance, record_ids):
    with placeholder.container(border=True):
        song = config[current_index]
        
        # 改进的快速跳转UI
        st.markdown("### 🎵 当前曲目")
        # st.warning("如果您不同存档间曲目数量不同，请先回到 Best#1 后再切换存档", icon="⚠️")
        col1, col2 = st.columns([3, 1])
        with col1:
            clip_selector = st.selectbox(
                label="快速跳转到曲目", 
                options=record_ids,
                index=current_index,
                key="record_selector",
                label_visibility="collapsed"
            )
        with col2:
            if st.button("跳转", width='stretch', icon="🚀"):
                target_index = record_ids.index(clip_selector)
                if target_index != current_index:
                    st.session_state.current_index = target_index
                    st.rerun()
                else:
                    st.toast("已经是当前记录！")

        # 当前曲目信息头
        st.info(f"**🎯 片段ID:** {song['clip_id']} &nbsp;&nbsp;|&nbsp;&nbsp; **📝 曲名:** {song['song_name']} &nbsp;&nbsp;|&nbsp;&nbsp; **🎚️ 难度:** {REVERSE_LEVEL_LABELS.get(song['level_index'])}")
        
        # 显示匹配信息 - 添加第二版的提示
        # st.write("该谱面目前已确认的视频信息是: ")
        
        match_info_placeholder = st.empty()
        video_info = song.get('video_info_match', None)
        
        if video_info:
            update_match_info(match_info_placeholder, video_info)
        else:
            match_info_placeholder.warning("未找到匹配的视频信息，请使用下方的手动搜索功能添加视频信息", icon="⚠️")

        # 备选视频选择
        st.divider()
        option_col1, option_col2 = st.columns([3, 1], vertical_alignment="center")
        with option_col1:
            st.markdown("### 🔄 备选视频")
        with option_col2:
            if st.button("重新搜索本曲", key=f"research_{song['clip_id']}", width='stretch', icon="🔍",
                         help="按当前抓取设置重搜该曲目；曲名与难度都对得上的才会自动选中，否则只列出候选等你确认"):
                try:
                    with st.spinner("正在搜索..."):
                        search_one_video(dl_instance, song)
                    save_config(b30_config_file, config)
                    st.rerun()
                except Exception as e:
                    st.error(f"重新搜索失败: {e}", icon="❌")

        to_match_videos = song.get('video_info_list', [])
        ranked_candidates = rank_video_candidates(song, to_match_videos)
        current_match = song.get('video_info_match') or {}

        if to_match_videos and not current_match:
            reason = (video_match_warning(ranked_candidates[0][1]) if ranked_candidates
                      else '标题未出现曲名，或除曲名外缺少谱面/难度语境')
            st.caption(f"🔎 已列出 {len(to_match_videos)} 条候选，但未自动匹配（{reason}）："
                       f"请在下方选定后点「确认使用此视频」")
        elif len(ranked_candidates) > 1:
            best_score, best_flags, best_video = ranked_candidates[0]
            match_warning = video_match_warning(best_flags)
            if match_warning:
                st.caption(f"⚠️ 最可能的候选仍存疑：{match_warning}（置信分 {best_score:.1f}）")
            if current_match and current_match.get('id') != best_video.get('id'):
                st.caption(f"ℹ️ 候选中有更可能的结果：{escape_markdown_text(best_video['title'])}"
                           f"（置信分 {best_score:.1f}），可在下方改选后点确认")

        if to_match_videos:
            video_options = []
            for i, video in enumerate(to_match_videos):
                link_url, link_label = video_part_link(video)
                video_options.append(
                    f"🎬 {i+1}. {escape_markdown_text(video['title'])} "
                    f"({video['duration']}秒) [{link_label}]({link_url})"
                )
            
            selected_index = st.radio(
                "选择备选视频:",
                range(len(video_options)),
                format_func=lambda x: video_options[x],
                key=f"radio_select_{song['clip_id']}",
                label_visibility="collapsed"
            )

            if st.button("确认使用此视频", key=f"confirm_{song['clip_id']}", width='stretch', icon="✅"):
                song['video_info_match'] = to_match_videos[selected_index]
                save_config(b30_config_file, config)
                # toast 会在 rerun 后仍然显示，st.success 会被下面的 rerun 立刻清掉
                st.toast("配置已保存！", icon="✅")
                # 重新检查匹配状态
                matched_count, unmatched_count, _ = check_matched_songs(b30_config)
                st.session_state.matched_count = matched_count
                st.session_state.unmatched_count = unmatched_count
                st.rerun()
        else:
            st.info("暂无备选视频信息，请使用下方的手动搜索功能", icon="ℹ️")

        # 手动搜索区域
        st.divider()
        st.markdown("### 🔍 手动搜索")
        
        # 添加跳转搜索页功能
        search_url = get_web_search_url(song, downloader_type)
        st.info('以上都不对？手动输入谱面确认视频的 ID', icon="ℹ️")
        col1, col2, col3 = st.columns([.5, .5, 1.5])
        with col1:
            search_mode = st.radio(
                "搜索方式",
                ["视频 ID", "列表 ID"],
                captions=["适合单个视频", "适合播放列表/合集"],
                horizontal=True,
                key=f"search_mode_{song['clip_id']}",
            )
        with col2:
            search_platform = st.radio(
                "选择视频所在的平台",
                ["YouTube", "Bilibili"], 0,
                captions=["油管", "哔哩哔哩"],
                key=f"search_platform_{song['clip_id']}",
                horizontal=True
            )
        with col3:
            part_index = 1
            if search_mode == "视频 ID":
                has_cache = False
                refresh_cache = False
                selected_lists = []   # 视频 ID 模式不用列表选择（对面那条分支同样把 replace_id 置空）
                replace_id = st.text_input(
                    f"谱面确认的 { f"{search_platform} ID " if search_platform == 'YouTube' else f"哔哩哔哩 BV 号"}",
                    key=f"replace_id_{song['clip_id']}",
                    placeholder="如'/watch?v=GjARTbhEayo' 的 GjARTbhEayo" if search_platform == 'YouTube' else "如 /video/BV1319DBAErC 的 BV1319DBAErC"
                )
                if search_platform == 'Bilibili':
                    part_index = st.number_input(
                        "分P序号", min_value=1, max_value=200, value=1, step=1,
                        key=f"part_index_{song['clip_id']}",
                        help="搬运者把整套谱面确认放在同一个视频的不同分P时，填这首谱面所在的 P 序号（从 1 开始）；单P视频保持 1。也可先用列表 ID 填 BV 号自动展开分P")
            else:
                replace_id = ""  # 列表模式不用文本输入
                has_cache = False
                selected_lists = []
                platform_lists = VIDEO_LISTS.get(search_platform.lower(), {})
                if platform_lists:
                    authors = list(platform_lists.keys())
                    selected_author = st.selectbox(
                        "谱面确认搬运来源",
                        authors,
                        help="YouTube 下作者名称后面的数字表示谱面流速",
                        key=f"author_{song['clip_id']}",
                    )
                    author_lists = platform_lists.get(selected_author, [])
                    if author_lists:
                        list_options = {f"{search_platform.lower()}:{lid}": title for lid, title in author_lists}
                        selected_lists = st.multiselect(
                            "要搜索的难度等级" if selected_author == "中二熊与迪拉企鹅" else "要搜索的游戏版本",
                            list(list_options.keys()),
                            help="仅包含紫谱和黑谱，不包含红谱" if selected_author == "Mr_Circle" else "可能仍无法包含所有曲目",
                            format_func=lambda x: list_options[x],
                            key=f"selected_lists_{song['clip_id']}",
                        )
                        cache_dir = "./cache/playlist_cache"
                        has_cache = any(is_artifact_valid(os.path.join(cache_dir, f"{k.replace(':', '_')}.json")) for k in selected_lists) if selected_lists else False
                    else:
                        selected_lists = []
                else:
                    st.info("暂无预设列表", icon="ℹ️")
                    selected_lists = []
        
        is_list_mode = search_mode == "列表 ID"

        col1, col2, col3 = st.columns([1, 1, 1.5], vertical_alignment="center")
        with col1:
            st.markdown(f"[➡点击跳转到搜索页]({search_url})", unsafe_allow_html=True)

        with col2:
            refresh_cache = st.checkbox("刷新缓存", key="refresh_cache", disabled=not has_cache,
                                                     help="勾选后重新从平台拉取谱面列表" if has_cache else "暂无缓存或处在不受支持的搜索方式")
            
        with col3:
            btn_disabled = (not selected_lists) if is_list_mode else (not replace_id)
            search_btn = st.button("替换当前选项" if not is_list_mode else "执行批量匹配",
                                   help="替换当前选项的视频 ID 为输入的 ID" if not is_list_mode else "批量匹配选中的难度等级",
                                key=f"search_replace_id_{song['clip_id']}",
                                disabled=btn_disabled,
                                width='stretch',
                                icon="🔍" if not is_list_mode else "📋")

        # 导航按钮区域
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("上一个", width='stretch', icon="⏮️"):
                if st.session_state.current_index > 0:
                    st.session_state.current_index -= 1
                    st.rerun()
                else:
                    st.toast("到顶啦！", icon="❗")
        with col2:
            if st.button("下一个", width='stretch', icon="⏭️"):
                if st.session_state.current_index < len(record_ids) - 1:
                    st.session_state.current_index += 1
                    st.rerun()
                else:
                    st.toast("到底啦！", icon="❗")
        with col3: 
            # 保存配置按钮
            if st.button("保存配置", width='stretch', icon="💾"):
                save_config(b30_config_file, b30_config)
                # 更新匹配状态
                matched_count, unmatched_count, _ = check_matched_songs(b30_config)
                st.session_state.matched_count = matched_count
                st.session_state.unmatched_count = unmatched_count
                st.toast("配置已保存！", icon="✅")

        if search_btn:
            with st.spinner("搜索中..."):
                to_replace_video_info = None
                videos = []
                input_error = False
                print(f"[搜索按钮] search_mode={search_mode!r}, search_platform={search_platform!r}")
                try:
                    if search_mode == "列表 ID":
                        cache_dir = "./cache/playlist_cache"
                        os.makedirs(cache_dir, exist_ok=True)
                        all_playlist_videos = []
                        for key in selected_lists:
                            cache_file = os.path.join(cache_dir, f"{key.replace(':', '_')}.json")
                            if not refresh_cache and is_artifact_valid(cache_file):
                                try:
                                    cached = load_config(cache_file)
                                except (OSError, ValueError) as e:
                                    # 半截缓存以前会让之后每一次批量匹配都在解析处炸掉，而且没有
                                    # 任何自愈路径（命中门只看文件在不在）。读不出就当没缓存，回源重拉。
                                    print(f"[批量] 缓存不可用（{type(e).__name__}: {e}），改为重新拉取: {key}")
                                else:
                                    all_playlist_videos.extend(cached)
                                    print(f"[批量] 缓存命中: {key} ({len(cached)} 个视频)")
                                    continue
                            _, list_id = key.split(":", 1)
                            print(f"[批量] 拉取列表: {key}")
                            videos = dl_instance.search_video_from_playlist(list_id)
                            save_config(cache_file, videos)   # 原子写，不再就地截断别人的缓存
                            all_playlist_videos.extend(videos)
                            print(f"[批量]   → 已获取 {len(videos)} 个视频")
                        print(f"[批量] 共 {len(all_playlist_videos)} 个视频，开始匹配 {len(b30_config)} 首曲目")
                        match_count, kept_count = apply_playlist_matches(b30_config, all_playlist_videos)
                        save_config(b30_config_file, b30_config)
                        matched_count, unmatched_count, _ = check_matched_songs(b30_config)
                        st.session_state.matched_count = matched_count
                        st.session_state.unmatched_count = unmatched_count
                        st.success(f"批量匹配完成！本次新配 {match_count} 首"
                                   + (f"，已有视频信息的 {kept_count} 首未改动" if kept_count else "")
                                   + f"（合计 {matched_count}/{len(b30_config)} 首有源）", icon="✅")
                        if kept_count:
                            st.caption("要换掉已选的视频，请用编辑器里的「重新搜索本曲」或手动输入视频 ID")
                        print(f"[批量] 完成: 新配 {match_count} 首，保留 {kept_count} 首")
                        time.sleep(2)
                        st.rerun()
                    elif search_platform == "YouTube":
                            video_info = dl_instance.get_video_info(replace_id)
                            videos = [video_info]
                    elif search_platform == "Bilibili":
                            bv_match = re.search(r'BV[0-9A-Za-z]{10}', replace_id or '')
                            if not bv_match:
                                input_error = True
                                st.error("未识别到 BV 号。可填 BV1319DBAErC，也可直接粘贴视频链接", icon="❌")
                            else:
                                video_info = dl_instance.get_video_info(bv_match.group())
                                pages = dl_instance.get_video_pages(video_info['id']) \
                                    if (video_info.get('page_count') or 0) > 1 else []
                                total_pages = len(pages) or (video_info.get('page_count') or 1)
                                if part_index > total_pages:
                                    input_error = True
                                    st.error(f"该视频共 {total_pages} 个分P，分P序号 {part_index} 超出范围", icon="❌")
                                else:
                                    video_info['p_index'] = part_index - 1
                                    video_info['page_count'] = total_pages
                                    if pages:
                                        # 以所选分P自己的标题和时长为准，否则界面上看不出选的是哪一首
                                        part = pages[part_index - 1]
                                        video_info['title'] = f"{part['part']}（{video_info['title']} P{part_index}）"
                                        video_info['duration'] = part['duration']
                                        if not rank_video_candidates(song, [video_info]):
                                            st.warning(f"第 {part_index} 个分P的标题「{part['part']}」未命中曲名，"
                                                       f"或除曲名外缺少谱面/难度语境，请核对 P 序号是否填对", icon="⚠️")
                                    videos = [video_info]

                    if len(videos) == 0 and not input_error:
                        st.error("未找到有效的视频，请重试", icon="❌")
                    else:
                        to_replace_video_info = videos[0]

                    if to_replace_video_info:
                        part_note = f"（第 {to_replace_video_info.get('p_index', 0) + 1} P / 共 {to_replace_video_info['page_count']} P）" \
                            if (to_replace_video_info.get('page_count') or 0) > 1 else ""
                        st.success(f"已使用视频{to_replace_video_info['id']}替换匹配信息{part_note}，详情：", icon="✅")
                        st.markdown(f"【{to_replace_video_info['title']}】({to_replace_video_info['duration']}秒)" +
                                f" [🔗{to_replace_video_info['id']}]({to_replace_video_info['url']})")
                        song['video_info_match'] = to_replace_video_info
                        song['video_info_list'] = [to_replace_video_info]  # 同时更新备选列表
                        save_config(b30_config_file, config)
                        print(f"[列表] 已保存到 {b30_config_file}: {to_replace_video_info['id']}")
                        st.toast("配置已保存！", icon="✅")
                        # 重新检查匹配状态
                        matched_count, unmatched_count, _ = check_matched_songs(b30_config)
                        st.session_state.matched_count = matched_count
                        st.session_state.unmatched_count = unmatched_count
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("未找到相关视频", icon="❌")
                except Exception as e:
                    st.error(f"搜索失败: {e}", icon="❌")

### 抓取设置（原 Step 2 并入）###
st.divider()
fetch_settings = render_fetch_settings(G_config)
saved_settings = settings_from_config(G_config)

if st.button("保存配置", key="save_fetch_settings", width='stretch', icon="💾"):
    try:
        apply_fetch_settings(G_config, fetch_settings)
        st.session_state.downloader = init_downloader(fetch_settings)
        st.session_state.downloader_type = fetch_settings['downloader']
        st.session_state.downloader_settings = fetch_settings
        st.session_state.downloader_cred = credential_state()
        st.toast("配置已保存！", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"下载器初始化失败：{e}", icon="❌")

# 控件值随时在变，只以「已保存的配置」为准重建实例，避免每次交互都重建下载器（含登录查询）；
# 但凭证文件变化（扫码登录写入 / 登出删除）必须重建，否则实例仍持有构造时的游客凭证
if st.session_state.get('downloader') is None or \
        settings_fingerprint(st.session_state.get('downloader_settings')) != settings_fingerprint(saved_settings) or \
        st.session_state.get('downloader_cred') != credential_state():
    try:
        st.session_state.downloader = init_downloader(saved_settings)
        st.session_state.downloader_type = saved_settings['downloader']
        st.session_state.downloader_settings = saved_settings
        st.session_state.downloader_cred = credential_state()
    except Exception as e:
        st.error(f"下载器初始化失败：{e}，请检查抓取设置后重新保存", icon="❌")
        st.stop()

if settings_fingerprint(fetch_settings) != settings_fingerprint(st.session_state.get('downloader_settings')):
    st.info("抓取设置已修改但尚未保存，点击「保存配置」后生效", icon="ℹ️")

# session_state 里拿回来的下载器，类型是"下载器或 None"（init_downloader 在下载器名字
# 不认识时就返回 None）。上面那道守卫把它筛成非 None，但光靠守卫不够：本页的 st 被判成
# Unknown —— 第 3 行那句 from utils.PathUtils import * 会把 PathUtils 自己的
# import streamlit as st 一起带进来（PathUtils 没写 __all__），把第 1 行的绑定顶掉；
# st 是 Unknown，st.stop() 在类型系统里就不算"必然中止"，窄化带不进下面那些函数与
# @st.dialog 的作用域（它们读到的是变量的声明类型，同 current_paths: dict 那条）。
# 所以 cast 把守卫后的事实写进签名——cast 只说签名、不改值，运行时该拦的还是这道守卫。
_downloader = st.session_state.downloader
if not _downloader:
    st.error("未找到可用的下载器，请确认抓取设置后点击「保存配置」！", icon="❌")
    st.stop()
dl_instance = cast(Downloader, _downloader)
downloader_type = st.session_state.downloader_type

# 读取存档的b30 config文件
# 先无条件绑定：下面那个 if/elif/else 里 else 虽然 st.stop()，但 pyright 仍把
# 这个变量判成"可能未绑定"（同形状的最小复现却不报，原因未定位），于是后面 9 处
# 使用全红。绑定交给这一行说，else 继续负责给用户可操作的报错。
b30_config_file = ""
if downloader_type == "youtube":
    b30_config_file = current_paths['config_yt']
elif downloader_type == "bilibili":
    b30_config_file = current_paths['config_bi']
else:
    # 原来没有 else：DOWNLOADER 被改成第三个值（或被旧版配置文件带进来）时
    # b30_config_file 根本没绑定，下面第一次用它就是 UnboundLocalError，
    # 用户看到的是一屏 traceback 而不是"这个下载器名字不认识"。
    st.error(f"不支持的下载器【{downloader_type}】，请在设置页选择 bilibili 或 youtube。", icon="❌")
    st.stop()

# 加载旧搜索数据
exported_b30_search_config_file = current_paths['exported_b30_search_config']

b50_data_file = current_paths['data_file']
if not os.path.exists(b50_data_file):
    st.error("未找到 Best50 数据文件，请检查存档的数据完整性！", icon="❌")
    st.stop()

if not os.path.exists(b30_config_file):
    # 首次进入：从成绩数据生成对应平台的索引文件
    shutil.copy(b50_data_file, b30_config_file)
    st.toast(f"已生成 {downloader_type} 的 Best50 索引文件", icon="ℹ️")

# 用最新成绩数据补齐索引，同时保留已有的视频匹配信息。
# 只在确有变化时写盘：这段在页面顶层，每轮 rerun 都会执行，旧写法连"点下一个/动控件"都要
# 原子替换一次全量 JSON —— 既和后台曲库线程抢 os.replace（PathUtils 那 20 次退让就是为此
# 存在），也可能凭空弹一次"已更新 N 条"。
# 注意不能只看 update_count：merge_b50_data 在长短不一致时返回 0 却做的是整份替换。
old_index = load_config(b30_config_file)
merged_b30_config, update_count = merge_b50_data(load_config(b50_data_file), old_index)
if update_count > 0 or len(merged_b30_config) != len(old_index):
    save_config(b30_config_file, merged_b30_config)
    if update_count > 0:
        st.toast(f"已加载 {downloader_type} 的 Best50 索引，共更新 {update_count} 条数据", icon="✅")

### 批量搜索（原 Step 2 主操作降级为工具）###
batch_search_area = st.expander("批量搜索全部未匹配曲目", icon="🔍")
with batch_search_area:
    st.caption("单曲重搜请直接用下方编辑器内的「重新搜索本曲」；这里用于整批补齐还缺视频信息的曲目。")
    st.warning("""
               如果您遇到自动搜索失败 / 大多数谱面搜索不正确的问题
               - 多半与第三方查询接口有关，**难以立刻修复**
                    - 请考虑到下方 *手动输入谱面视频 BV 号*，或对单曲点「重新搜索本曲」
                    - 或者提供几个应对办法：
                        - 等待至少 24 小时 / 拉宽搜索间隔时间
                        - 尝试不登录账号搜索（很玄学但有时也可行）
                        - 更换当前网络环境（任何方法都行，有 IPv6 更好）
               """, icon="⚠️")
    if st.button("开始批量搜索", width='stretch', type="primary", icon="🔍"):
        try:
            st_search_all_videos(dl_instance, batch_search_area,
                                 saved_settings['search_wait_time'], b30_config_file)
            st.toast("搜索完成！请在下方逐条核对候选视频。", icon="✅")
            st.toast("如果站点存在此视频但未找到，请尝试重新搜索多几次。", icon="⚠️")
        except Exception as e:
            st.error(f"发生错误：{e}，可重试（已搜索到的曲目会自动跳过）", icon="❌")
            st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❗")

b30_config = load_config(b30_config_file)

# 匹配计数每轮都按当前 b30_config 重算（换存档、批量搜索、编辑器改动都会让它变化）。
# 以前这里有 20 行：isinstance(..., list) 的清理分支是死代码（check_matched_songs 只会返回
# int），if/else 两个分支算的又是同一件事，unmatched_names 还算两遍然后丢掉。
matched_count, unmatched_count, _ = check_matched_songs(b30_config)
st.session_state.matched_count = matched_count
st.session_state.unmatched_count = unmatched_count
st.session_state.total_songs = len(b30_config)

if b30_config:
    # 显示进度信息
    progress_text = f"进度: {st.session_state.matched_count}/{st.session_state.total_songs} 首曲目已匹配视频信息"
    st.info(progress_text, icon="📊")
    
    # 如果有未匹配的歌曲，显示警告
    if st.session_state.unmatched_count > 0:
        st.warning(f"还有 {st.session_state.unmatched_count} 首曲目缺少视频信息，请使用手动搜索功能补充", icon="⚠️")

    # 获取所有视频片段的ID
    record_ids = [f"[{item['clip_id'].split('_', 1)[0]} #{item['clip_id'].split('_', 1)[1]}, {REVERSE_LEVEL_LABELS.get(item['level_index'])}]: {item['song_name']}" for item in b30_config]
    
    # 使用session_state来存储当前选择的视频片段索引
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0

    # 指针要跟着曲目数钳位：曲目会在【编辑 Best50 数据】里被删或重排，切档只清了 current_index，
    # 从那一页返回时残留的下标会越界（update_editor 里 config[current_index] 直接 IndexError）。
    # 页 4 有同形的 safe_index 处理，这里以前没有。
    if st.session_state.current_index >= len(b30_config):
        st.session_state.current_index = len(b30_config) - 1
    elif st.session_state.current_index < 0:
        st.session_state.current_index = 0

    # 片段预览和编辑组件，使用empty容器
    link_editor_placeholder = st.empty()
    update_editor(link_editor_placeholder, b30_config, st.session_state.current_index, dl_instance, record_ids)

    # 下载区域
    # 检查是否可以下载（至少有一个视频信息）
    has_video_info = any(song.get('video_info_match') for song in b30_config)
    
    if not has_video_info:
        st.warning("当前没有可下载的视频信息，请先为曲目添加视频信息", icon="⚠️")
    
    download_info_placeholder = st.empty()
    # 会话内保持"已下载过"状态：只在新会话初始化为 False，切换存档时在上方清除。
    # 旧实现每轮 rerun 都重置，下载完成后任何其他交互都会把「下一步」重新禁用。
    if 'download_completed' not in st.session_state:
        st.session_state.download_completed = False
    
    if st.button("确认并开始下载视频", disabled=not dl_instance or not has_video_info, width='stretch', icon="⏬"):
        try:
            st.session_state.download_completed = \
                st_download_video(download_info_placeholder, dl_instance, saved_settings, b30_config) > 0
        except Exception as e:
            st.session_state.download_completed = False
            st.error(f"下载过程中出现错误: {e}", icon="⚠️")
            st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❌")

    # 下一步按钮
    st.markdown("---")
    if st.button("下一步", disabled=not st.session_state.download_completed, width='stretch', icon="▶️"):
        st.switch_page("st_pages/4_Edit_Video_Content.py")
    
    with st.expander("附加设置（搜索数据）", icon="ℹ️"):
        st.info("可以从其他搜索文件内导入已完成的搜索数据，方法请悬停在操作按钮上查看", icon="💬")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("迁移存档搜索数据", width='stretch', icon="📥",
                            help=f"""
                            请按照以下操作后，再点击此按钮：
                            - 下载其他人的搜索数据（`exported_b30_search_config.json`）
                            - 放入当前用户（`{username}`）存档（`{save_id}`）下
                            """
                            ):
                try:
                    migrated, same, no_match = migrate_search_args(
                        b30_config_file, exported_b30_search_config_file)
                    # 结果存进 session_state 再刷：只 print 到控制台的话，"更新 0 条"到底是
                    # 存档本来就一样、还是导入件对不上 (id, 难度)，用户分不出来。
                    # 写成 caption 也活不过这次 st.rerun()。
                    st.session_state.migrate_report = (
                        f"导入 {migrated} 条，本就相同 {same} 条，"
                        f"当前存档有 {no_match} 条在导入件里找不到对应"
                        + ("：导入件多半来自另一份成绩" if no_match else ""))
                    st.rerun()
                except Exception as e:
                    st.error(f"迁移失败：{e}", icon="❌")
        
        with col2:
            if st.button("导出存档搜索数据", width='stretch', icon="📤",
                            help=f"""
                            导出的搜索数据文件不要改名（`exported_b30_search_config.json`）
                            - 生成器使用此名称进行数据导入
                            """):
                try:
                    if not os.path.exists(b30_config_file):
                        st.error("找不到搜索数据文件", icon="❌")
                    else:
                        
                        # 复制文件
                        shutil.copy2(b30_config_file, exported_b30_search_config_file)
                        
                        st.success(f"✅ 已创建搜索数据备份：{exported_b30_search_config_file}")
                        
                except Exception as e:
                    st.error(f"导出失败：{e}", icon="❌")

        # 上一次迁移的结果要能撑过 st.rerun()：否则用户点完按钮只看到 3 秒 toast，
        # 之后"到底导入了几条"无处可查
        if st.session_state.get('migrate_report'):
            st.info(f"上次迁移结果：{st.session_state.migrate_report}", icon="📥")
            if st.button("清掉这条结果", key="clear_migrate_report", icon="🧹"):
                del st.session_state.migrate_report
                st.rerun()
else:
    st.error("配置文件加载失败，请检查文件完整性！", icon="❌")