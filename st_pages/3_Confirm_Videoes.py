import time, random, traceback, os
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from utils.chuni_extension import REVERSE_LEVEL_LABELS
from pre_gen import download_one_video

G_config = read_global_config()

st.header("Step 3: 视频信息检查和下载")

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
        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                label="👤 当前用户",
                value=username
            )
        with col2:
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
        selected_save_id = st.selectbox(
            "选择存档",
            versions,
            format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
        )
        if st.button("使用此存档", help="（只需要点击一次！）", use_container_width=True, icon="▶️"):
            if selected_save_id:
                st.session_state.save_id = selected_save_id
                # 清除旧的匹配状态，强制重新初始化
                if 'matched_count' in st.session_state:
                    del st.session_state.matched_count
                if 'unmatched_count' in st.session_state:
                    del st.session_state.unmatched_count
                if 'total_songs' in st.session_state:
                    del st.session_state.total_songs
                st.rerun()
            else:
                st.error("无效的存档路径！")
    else:
        st.warning("未找到任何存档，请先在存档管理页面获取存档！")
        st.stop()
### Savefile Management - End ###

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
    st.write("分P视频指定")

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
            label_visibility="visible"
        )

        if st.button("确定更新分p", key=f"confirm_selected_page_{cur_song_data['clip_id']}"):
            cur_song_data['video_info_match']['p_index'] = selected_p_index
            save_config(b30_config_file, b30_config)
            st.rerun()
    except Exception as e:
        st.error(f"获取分P信息失败: {e}", icon="❌")

def update_match_info(placeholder, video_info, song_name):
    """增强的视频信息展示"""
    with placeholder.container():
        # 基础信息展示 - 改进的格式
        id = video_info['id']
        title = escape_markdown_text(video_info['title'])
        
        st.markdown(f"**📺 视频标题：** {title}")
        st.markdown(f"**🔗 视频链接：** [打开视频]({video_info['url']})")
        st.markdown(f"**⏱️ 总时长：** {video_info['duration']}秒")
        
        # 分P信息展示
        if 'p_index' in video_info:
            p_index = video_info['p_index']
            st.markdown(f"**📑 分P序号：** P{p_index + 1}")
            
            # 显示修改分P按钮
            if st.button("修改分P视频", key=f"change_p_{id}", use_container_width=True):
                change_video_page({'video_info_match': video_info, 'clip_id': id}, p_index)

def st_download_video(placeholder, dl_instance, G_config, b30_config):
    search_wait_time = G_config['SEARCH_WAIT_TIME']
    download_high_res = G_config['DOWNLOAD_HIGH_RES']
    video_download_path = f"./videos/downloads"
    
    os.makedirs(video_download_path, exist_ok=True)
    
    with placeholder.container(border=True):
        with st.spinner("正在下载视频……"):
            progress_bar = st.progress(0)
            write_container = st.container(border=True, height=400)
            total_songs = len(b30_config)
            
            for i, song in enumerate(b30_config, 1):
                progress_value = min(i / total_songs, 1.0)
                
                if 'video_info_match' not in song or not song['video_info_match']:
                    write_container.write(f"❌ 跳过({i}/{total_songs}): {song['song_name']} - 无视频信息")
                    continue
                
                video_info = song['video_info_match']
                title = escape_markdown_text(video_info['title'])
                
                # 更好的进度文本
                progress_bar.progress(progress_value, 
                                    text=f"下载进度: {i}/{total_songs} - {song['song_name']}")
                
                # 缓存检查
                clip_name = f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"
                video_path = os.path.join(video_download_path, f"{clip_name}.mp4")
                
                if os.path.exists(video_path):
                    write_container.write(f"✅ [{i}/{total_songs}] - 【{song['song_name']}】已缓存")
                    continue
                
                # 下载视频
                result = download_one_video(dl_instance, song, video_download_path, download_high_res)
                
                # 更好的结果展示
                if result['status'] == 'success':
                    write_container.write(f"✅ [{i}/{total_songs}] - 【{song['song_name']}】下载成功")
                else:
                    write_container.write(f"❌ [{i}/{total_songs}] - 【{song['song_name']}】下载失败: {result['info']}")

                # 智能等待
                if result['status'] == 'success' and search_wait_time[0] > 0:
                    wait_time = random.randint(search_wait_time[0], search_wait_time[1])
                    time.sleep(wait_time)

            st.success("下载完成！请点击下一步按钮核对视频素材的详细信息。", icon="✅")

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
            if st.button("🚀 跳转", use_container_width=True):
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
            update_match_info(match_info_placeholder, video_info, song['song_name'])
        else:
            match_info_placeholder.warning("未找到匹配的视频信息，请使用下方的手动搜索功能添加视频信息", icon="⚠️")

        # 备选视频选择
        st.divider()
        st.markdown("### 🔄 备选视频")
        
        to_match_videos = song.get('video_info_list', [])
        if to_match_videos:
            video_options = [
                f"🎬 {i+1}. {escape_markdown_text(video['title'])} ({video['duration']}秒) [链接]({video['url']})"
                for i, video in enumerate(to_match_videos)
            ]
            
            selected_index = st.radio(
                "选择备选视频:",
                options=range(len(video_options)),
                format_func=lambda x: video_options[x],
                key=f"radio_select_{song['clip_id']}",
                label_visibility="collapsed"
            )

            if st.button("确认使用此视频", key=f"confirm_{song['clip_id']}", use_container_width=True, icon="✅"):
                song['video_info_match'] = to_match_videos[selected_index]
                save_config(b30_config_file, config)
                st.success("配置已保存！", icon="✅")
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
        col1, col2 = st.columns([1.5, 0.5])
        with col1:
            replace_id = st.text_input(
                "谱面确认视频的 youtube ID 或 BV 号", 
                key=f"replace_id_{song['clip_id']}",
                placeholder="输入视频 ID 或 BV 号"
            )
        with col2:
            # 添加分P序号输入
            replace_p_index = st.number_input(
                "分P序号（可选）", 
                help="""
                以下条件，请直接填写视频分 P 序号（可从网页端查询，P 数较多时直接输入序号加载更快）：
                - 您选择的谱面确认来源是【哔哩哔哩】
                - 您选择的谱面确认有分 P（一般是合集）
                
                以下条件，请直接忽略：
                - 站内的单个视频（单个视频默认是 0，可以不用管）
                - 非【哔哩哔哩】的视频
                """,
                min_value=0, 
                max_value=999, 
                value=0, 
                key=f"replace_p_index_{song['clip_id']}"
            )
        
        col1, col2 = st.columns([.5, 1.5], vertical_alignment="center")
        with col1:
            st.markdown(f"[➡点击跳转到搜索页]({search_url})", unsafe_allow_html=True)
        with col2:
            search_btn = st.button("搜索并替换", 
                                key=f"search_replace_id_{song['clip_id']}",
                                disabled=not replace_id,
                                use_container_width=True,
                                icon="🔍")
        
        if search_btn:
            with st.spinner("搜索中..."):
                to_replace_video_info = None  # 初始化变量
                try:
                    if downloader_type == "youtube":
                        videos = dl_instance.search_video(replace_id)
                        if len(videos) == 0:
                            st.error("未找到有效的视频，请重试", icon="❌")
                        else:
                            to_replace_video_info = videos[0]
                    elif downloader_type == "bilibili":
                        # 对于B站，直接使用search_video方法
                        videos = dl_instance.search_video(replace_id)
                        if len(videos) == 0:
                            st.error("未找到有效的视频，请重试", icon="❌")
                        else:
                            to_replace_video_info = videos[0]

                    if to_replace_video_info:
                        if replace_p_index > 0:
                            to_replace_video_info['p_index'] = replace_p_index - 1  # 用户输入从1开始，内部从0开始
                        st.success(f"已使用视频{to_replace_video_info['id']}替换匹配信息，详情：", icon="✅")
                        st.markdown(f"【{to_replace_video_info['title']}】({to_replace_video_info['duration']}秒)" + 
                                   (f", p{replace_p_index}" if replace_p_index > 0 else "") + 
                                   f" [🔗{to_replace_video_info['id']}]({to_replace_video_info['url']})")
                        song['video_info_match'] = to_replace_video_info
                        song['video_info_list'] = [to_replace_video_info]  # 同时更新备选列表
                        save_config(b30_config_file, config)
                        st.toast("配置已保存！", icon="✅")
                        # 重新检查匹配状态
                        matched_count, unmatched_count, _ = check_matched_songs(b30_config)
                        st.session_state.matched_count = matched_count
                        st.session_state.unmatched_count = unmatched_count
                        st.rerun()
                    else:
                        st.error("未找到相关视频", icon="❌")
                except Exception as e:
                    st.error(f"搜索失败: {e}", icon="❌")

# 尝试读取缓存下载器
if 'downloader' in st.session_state and 'downloader_type' in st.session_state:
    downloader_type = st.session_state.downloader_type
    dl_instance = st.session_state.downloader
else:
    downloader_type = ""
    dl_instance = None
    st.error("未找到缓存的下载器，无法进行手动搜索和下载视频！请先进行一次搜索！", icon="❌")
    st.stop()

# 读取存档的b30 config文件
if downloader_type == "youtube":
    b30_config_file = current_paths['config_yt']
elif downloader_type == "bilibili":
    b30_config_file = current_paths['config_bi']
    
if not os.path.exists(b30_config_file):
    st.error(f"未找到配置文件{b30_config_file}，请检查B30存档的数据完整性！", icon="❌")
    st.stop()
    
b30_config = load_config(b30_config_file)

# 检查是否有搜索结果的缓存 - 修复：不覆盖已存在的视频信息
search_result = st.session_state.get("search_results", None)
if search_result:
    # 将搜索结果的缓存应用到配置中 - 只对没有视频信息的歌曲应用
    config_updated = False
    for song in b30_config:
        clip_id = song['clip_id']
        if clip_id in search_result:
            ret_data = search_result[clip_id]
            # 只更新备选列表，不覆盖已存在的匹配信息
            if not song.get('video_info_list') or len(song['video_info_list']) == 0:
                song['video_info_list'] = ret_data['video_info_list']
                config_updated = True
            # 只有在完全没有匹配信息时才使用默认搜索结果
            if not song.get('video_info_match'):
                song['video_info_match'] = ret_data['video_info_match']
                config_updated = True
    # 保存更新后的配置
    if config_updated:
        save_config(b30_config_file, b30_config)
        st.success("已应用缓存的搜索结果！", icon="✅")

# 完全重新初始化匹配状态计数 - 删除旧的错误状态
if 'matched_count' in st.session_state and isinstance(st.session_state.matched_count, list):
    del st.session_state.matched_count
if 'unmatched_count' in st.session_state and isinstance(st.session_state.unmatched_count, list):
    del st.session_state.unmatched_count

# 重新初始化匹配状态计数 - 每次加载新存档都重新计算
if 'matched_count' not in st.session_state or 'unmatched_count' not in st.session_state or 'total_songs' not in st.session_state:
    matched_count, unmatched_count, unmatched_names = check_matched_songs(b30_config)
    st.session_state.matched_count = matched_count
    st.session_state.unmatched_count = unmatched_count
    st.session_state.total_songs = len(b30_config)
else:
    # 如果已经存在状态，但存档可能已经变化，重新检查
    matched_count, unmatched_count, unmatched_names = check_matched_songs(b30_config)
    if (st.session_state.matched_count != matched_count or 
        st.session_state.unmatched_count != unmatched_count or
        st.session_state.total_songs != len(b30_config)):
        st.session_state.matched_count = matched_count
        st.session_state.unmatched_count = unmatched_count
        st.session_state.total_songs = len(b30_config)

if b30_config:
    # 显示进度信息
    progress_text = f"进度: {st.session_state.matched_count}/{st.session_state.total_songs} 首曲目已匹配视频信息"
    st.info(progress_text, icon="📊")
    
    # 如果有未匹配的歌曲，显示警告
    if st.session_state.unmatched_count > 0:
        _, _, unmatched_names = check_matched_songs(b30_config)
        st.warning(f"还有 {st.session_state.unmatched_count} 首曲目缺少视频信息，请使用手动搜索功能补充", icon="⚠️")

    # 获取所有视频片段的ID
    record_ids = [f"[{item['clip_id'].split('_', 1)[0]} #{item['clip_id'].split('_', 1)[1]}, {REVERSE_LEVEL_LABELS.get(item['level_index'])}]: {item['song_name']}" for item in b30_config]
    
    # 使用session_state来存储当前选择的视频片段索引
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0

    # 片段预览和编辑组件，使用empty容器
    link_editor_placeholder = st.empty()
    update_editor(link_editor_placeholder, b30_config, st.session_state.current_index, dl_instance, record_ids)

    # 导航按钮区域
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("⏮️ 上一个", use_container_width=True):
            if st.session_state.current_index > 0:
                st.session_state.current_index -= 1
                st.rerun()
            else:
                st.toast("到顶啦！", icon="❗")
    with col2:
        if st.button("⏭️ 下一个", use_container_width=True):
            if st.session_state.current_index < len(record_ids) - 1:
                st.session_state.current_index += 1
                st.rerun()
            else:
                st.toast("到底啦！", icon="❗")
    with col3: 
        # 保存配置按钮
        if st.button("💾 保存配置", use_container_width=True):
            save_config(b30_config_file, b30_config)
            # 更新匹配状态
            matched_count, unmatched_count, _ = check_matched_songs(b30_config)
            st.session_state.matched_count = matched_count
            st.session_state.unmatched_count = unmatched_count
            st.success("配置已保存！", icon="✅")

    # 下载区域
    st.markdown("---")
    st.markdown("### 📥 视频下载")
    
    # 检查是否可以下载（至少有一个视频信息）
    has_video_info = any(song.get('video_info_match') for song in b30_config)
    
    if not has_video_info:
        st.warning("当前没有可下载的视频信息，请先为曲目添加视频信息", icon="⚠️")
    
    download_info_placeholder = st.empty()
    st.session_state.download_completed = False
    
    if st.button("⏬ 确认并开始下载视频", disabled=not dl_instance or not has_video_info, use_container_width=True, icon="⏬"):
        try:
            st_download_video(download_info_placeholder, dl_instance, G_config, b30_config)
            st.session_state.download_completed = True
        except Exception as e:
            st.session_state.download_completed = False
            st.error(f"下载过程中出现错误: {e}", icon="⚠️")
            st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❌")

    # 下一步按钮
    st.markdown("---")
    if st.button("▶️ 下一步", disabled=not st.session_state.download_completed, use_container_width=True, icon="▶️"):
        st.switch_page("st_pages/4_Edit_Video_Content.py")
else:
    st.error("配置文件加载失败，请检查文件完整性！", icon="❌")