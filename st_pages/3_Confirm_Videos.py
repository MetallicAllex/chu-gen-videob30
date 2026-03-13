import shutil
import time, random, traceback, os
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from utils.Variables import REVERSE_LEVEL_LABELS
from utils.DataUtils import download_one_video
from utils.video_crawler import BilibiliDownloader

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
                        # 清除旧的匹配状态，强制重新初始化
                        song_status = ['matched_count', 'unmatched_count', 'total_songs', 'current_index']
                        for song_key in song_status:
                            if song_key in st.session_state:
                                del st.session_state[song_key]
                            # if 'unmatched_count' in st.session_state:
                            #     del st.session_state.unmatched_count
                            # if 'total_songs' in st.session_state:
                            #     del st.session_state.total_songs
                            # if 'current_index' in st.session_state:
                            #     del st.session_state.current_index
                        st.rerun()
                    else:
                        st.error("存档路径无效！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
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
            save_config(b30_config_file, b30_config)
            st.rerun()
    except Exception as e:
        st.error(f"获取分P信息失败: {e}", icon="❌")

def update_match_info(placeholder, video_info):
    """增强的视频信息展示"""
    with placeholder.container():
        # 基础信息展示 - 改进的格式
        id = video_info['id']
        title = escape_markdown_text(video_info['title'])
        st.markdown(f"**📺 视频标题：** {title}")
        
        p_index = video_info['p_index'] if 'p_index' in video_info else 0
        info_col1, info_col2, info_col3 = st.columns(3)
        with info_col1:
            st.markdown(f"**⏱️ 总时长：** {video_info['duration']} 秒")
        with info_col2:
            st.markdown(f"**📑 分P序号：** p{p_index + 1}")
        with info_col3:
            st.markdown(f"**🔗 视频链接：** [打开视频]({video_info['url']}/?p={str(p_index + 1)})")
        
        # 显示修改分P按钮
        if st.button("修改分P视频", key=f"change_p_{id}", width='stretch'):
            change_video_page({'video_info_match': video_info, 'clip_id': id}, p_index)
        
        # 分P信息展示
        # if 'p_index' in video_info:
        #     p_index = video_info['p_index']
        #     info_col1, info_col2, info_col3 = st.columns(3)
        #     with info_col1:
        #         st.markdown(f"**⏱️ 总时长：** {video_info['duration']} 秒")
        #     with info_col2:
        #         st.markdown(f"**📑 分P序号：** p{p_index + 1}")
        #     with info_col3:
        #         st.markdown(f"**🔗 视频链接：** [打开视频]({video_info['url']}/?p={str(p_index + 1)})")
            
        #     # 显示修改分P按钮
        #     if st.button("修改分P视频", key=f"change_p_{id}", width='stretch'):
        #         change_video_page({'video_info_match': video_info, 'clip_id': id}, p_index)

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
                    write_container.write(f"❌［{i}/{total_songs}］跳过 →  {song['song_name']}：无视频信息")
                    continue
                
                # video_info = song['video_info_match']
                # title = escape_markdown_text(video_info['title'])
                
                # 更好的进度文本
                progress_bar.progress(progress_value, text=f"下载进度［{i}/{total_songs}］ →  {song['song_name']}")
                
                # 缓存检查
                clip_name = f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"
                video_path = os.path.join(video_download_path, f"{clip_name}.mp4")
                
                if os.path.exists(video_path):
                    write_container.write(f"☑️［{i}/{total_songs}］已缓存 →  {song['song_name']}")
                    continue
                
                # 下载视频
                result = download_one_video(dl_instance, song, video_download_path, download_high_res)
                
                # 更好的结果展示
                if result['status'] == 'success':
                    write_container.write(f"✅［{i}/{total_songs}］下载成功 →  {song['song_name']}")
                else:
                    write_container.write(f"❌［{i}/{total_songs}］下载失败 →  {song['song_name']}: {result['info']}")

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

# def copy_search_args(config_path, old_config_path):
#     """
#     复制旧存档的 视频候选列表 和 视频匹配列表 到新存档

#     Args:
#         config_path: 新的 b30_config_<平台>.json 完整路径
#         old_config_path: 旧的 old_b30_search_config.json 完整路径

#     Raises:
#         FileNotFoundError: 未找到存档数据

#     Returns:
#         dict: 更新后的配置数据
#     """
#     if not os.path.exists(config_path) or not os.path.exists(old_config_path):
#         missing_file = config_path if not os.path.exists(config_path) else old_config_path
#         raise FileNotFoundError("找不到配置文件：" + missing_file)

#     # 读取配置文件
#     old_config_data = load_config(old_config_path)
#     new_config_data = load_config(config_path)

#     updated_count = 0
#     skipped_count = 0

#     # 获取对应的记录列表
#     try:
#         old_records = old_config_data
#         new_records = new_config_data
#     except KeyError as e:
#         raise FileNotFoundError(f"在配置中找不到对应的数据: {e}")

#     # 遍历所有记录进行匹配和更新
#     for old_record in old_records:
#         for new_record in new_records:
#             # 检查匹配条件：id, song_name, artist, level, level_index
#             if (old_record['id'] == new_record['id'] and
#                 old_record['song_name'] == new_record['song_name'] and
#                 old_record['artist'] == new_record['artist'] and
#                 old_record['level'] == new_record['level'] and
#                 old_record['level_index'] == new_record['level_index']):
                
#                 # 检查需要更新的字段是否相同
#                 need_update = False
#                 fields_to_check = ['video_info_list', 'video_info_match']
                
#                 for field in fields_to_check:
#                     if old_record.get(field) != new_record.get(field):
#                         need_update = True
#                         break
                
#                 if need_update:
#                     # 更新剪辑参数
#                     new_record['video_info_list'] = old_record['video_info_list']
#                     new_record['video_info_match'] = old_record['video_info_match']
#                     updated_count += 1
#                 else:
#                     skipped_count += 1
                
#                 break  # 找到匹配后跳出内层循环

#     # 保存更新后的配置
#     save_config(config_path, new_config_data)

#     print(f"已成功更新 {updated_count} 条记录的搜索参数，跳过 {skipped_count} 条无需更新（不符合）的记录")
#     return new_config_data

def copy_search_args(config_path, old_config_path, debug=True):
    """
    复制旧存档的 视频候选列表 和 视频匹配列表 到新存档

    Args:
        config_path: 新的 b30_config_<平台>.json 完整路径
        old_config_path: 旧的 old_b30_search_config.json 完整路径
        debug: 是否启用调试模式，输出详细的匹配信息

    Raises:
        FileNotFoundError: 未找到存档数据

    Returns:
        dict: 更新后的配置数据
    """
    if debug:
        print(f"[DEBUG] 开始复制搜索参数")
        # print(f"[DEBUG] 新配置文件: {config_path}")
        # print(f"[DEBUG] 旧配置文件: {old_config_path}")
    
    if not os.path.exists(config_path) or not os.path.exists(old_config_path):
        missing_file = config_path if not os.path.exists(config_path) else old_config_path
        if debug:
            print(f"[DEBUG] 文件不存在: {missing_file}")
        raise FileNotFoundError("找不到配置文件：" + missing_file)

    if debug:
        print(f"[DEBUG] 文件存在检查通过，开始读取配置文件")
    
    # 读取配置文件
    old_config_data = load_config(old_config_path)
    new_config_data = load_config(config_path)

    if debug:
        print(f"[DEBUG] 旧配置文件数据条数: {len(old_config_data)}")
        print(f"[DEBUG] 新配置文件数据条数: {len(new_config_data)}")

    updated_count = 0
    skipped_count = 0
    unmatched_count = 0

    # 获取对应的记录列表
    try:
        old_records = old_config_data
        new_records = new_config_data
        
        if debug:
            print(f"[DEBUG] 成功获取记录列表")
    except KeyError as e:
        if debug:
            print(f"[DEBUG] 获取记录列表时出错: {e}")
        raise FileNotFoundError(f"在配置中找不到对应的数据: {e}")

    # 遍历所有记录进行匹配和更新
    for i, old_record in enumerate(old_records):
        if debug:
            print(f"[DEBUG] 处理旧记录 #{i}: {old_record.get('song_name', 'Unknown')} - {old_record.get('level', 'Unknown')}")
        
        matched = False
        
        for j, new_record in enumerate(new_records):
            # 检查匹配条件：id, song_name, artist, level, level_index
            match_conditions = (
                old_record['id'] == new_record['id'] and
                old_record['song_name'] == new_record['song_name'] and
                old_record['artist'] == new_record['artist'] and
                old_record['level'] == new_record['level'] and
                old_record['level_index'] == new_record['level_index']
            )
            
            if debug and match_conditions:
                print(f"[DEBUG]   - 找到匹配的新记录 #{j}")
                print(f"[DEBUG]     歌曲: {old_record['song_name']}")
                print(f"[DEBUG]     难度: {old_record['level']}")
                print(f"[DEBUG]     难度索引: {old_record['level_index']}")
                print(f"[DEBUG]     艺术家: {old_record['artist']}")
                print(f"[DEBUG]     ID: {old_record['id']}")
            
            if match_conditions:
                matched = True
                
                # 检查需要更新的字段是否相同
                need_update = False
                fields_to_check = ['video_info_list', 'video_info_match']
                
                if debug:
                    print(f"[DEBUG]     检查字段是否需要更新:")
                
                for field in fields_to_check:
                    old_value = old_record.get(field)
                    new_value = new_record.get(field)
                    
                    # if debug:
                        # print(f"[DEBUG]       {field}:")
                        # print(f"[DEBUG]         旧值: {old_value}")
                        # print(f"[DEBUG]         新值: {new_value}")
                    
                    if old_value != new_value:
                        need_update = True
                        if debug:
                            print(f"[DEBUG]         → 需要更新")
                
                if need_update:
                    if debug:
                        print(f"[DEBUG]     执行更新操作")
                    
                    # 更新剪辑参数
                    new_record['video_info_list'] = old_record['video_info_list']
                    new_record['video_info_match'] = old_record['video_info_match']
                    
                    if debug:
                        print(f"[DEBUG]         video_info_list 已更新为: {old_record.get('video_info_list')}")
                        print(f"[DEBUG]         video_info_match 已更新为: {old_record.get('video_info_match')}")
                    
                    updated_count += 1
                else:
                    if debug:
                        print(f"[DEBUG]     字段相同，无需更新")
                    skipped_count += 1
                
                break  # 找到匹配后跳出内层循环
        
        if not matched and debug:
            print(f"[DEBUG]   ! 未找到匹配的新记录")
            print(f"[DEBUG]     歌曲: {old_record.get('song_name', 'Unknown')}")
            print(f"[DEBUG]     难度: {old_record.get('level', 'Unknown')}")
            print(f"[DEBUG]     艺术家: {old_record.get('artist', 'Unknown')}")
            print(f"[DEBUG]     可能的匹配条件:")
            print(f"[DEBUG]       ID: {old_record.get('id', 'Unknown')}")
            print(f"[DEBUG]       level_index: {old_record.get('level_index', 'Unknown')}")
            unmatched_count += 1

    if debug:
        print(f"[DEBUG] 统计信息:")
        print(f"[DEBUG]   更新记录数: {updated_count}")
        print(f"[DEBUG]   跳过记录数: {skipped_count}")
        print(f"[DEBUG]   未匹配记录数: {unmatched_count}")

    # 保存更新后的配置
    save_config(config_path, new_config_data)
    
    if debug:
        print(f"[DEBUG] 配置已保存到: {config_path}")

    print(f"已成功更新 {updated_count} 条记录的搜索参数，跳过 {skipped_count} 条无需更新（不符合）的记录")
    
    if unmatched_count > 0 and debug:
        print(f"[DEBUG] 注意: 有 {unmatched_count} 条旧记录未找到匹配项")
    
    return new_config_data

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
        st.markdown("### 🔄 备选视频")
        
        to_match_videos = song.get('video_info_list', [])
        if to_match_videos:
            video_options = [
                f"🎬 {i+1}. {escape_markdown_text(video['title'])} ({video['duration']}秒) [首p链接]({video['url']})"
                for i, video in enumerate(to_match_videos)
            ]
            
            selected_index = st.radio(
                "选择备选视频:",
                options=range(len(video_options)),
                format_func=lambda x: video_options[x],
                key=f"radio_select_{song['clip_id']}",
                label_visibility="collapsed"
            )

            if st.button("确认使用此视频", key=f"confirm_{song['clip_id']}", width='stretch', icon="✅"):
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
        col1, col2 = st.columns([1.35, .65])
        with col1:
            replace_id = st.text_input(
                "谱面确认的 youtube ID 或 BV 号", 
                key=f"replace_id_{song['clip_id']}",
                placeholder="输入视频 ID 或 BV 号"
            )
        with col2:
            # 添加分P序号输入
            replace_p_index = st.number_input(
                "分P序号（可选）", 
                help="""
                以下条件，请填写视频分 P 号（可从网页端查询，P 数较多时直接输入序号加载更快）：
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
        
        col1, col2, col3 = st.columns([.65, .5, 1.35], vertical_alignment="center")
        with col1:
            st.markdown(f"[➡点击跳转到搜索页]({search_url})", unsafe_allow_html=True)
        
        with col2:
            no_search = st.checkbox("直接指定", help="如果您不需要搜索或是搜索出现异常【如 BV 号长度不符等】，请选择此项（仅限 B 站）")    
        
        with col3:
            search_btn = st.button("搜索并替换", 
                                key=f"search_replace_id_{song['clip_id']}",
                                disabled=not replace_id,
                                width='stretch',
                                icon="🔍")
        
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
                st.success("配置已保存！", icon="✅")

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
                        print(replace_id)
                        # 判断是关键词搜索还是BV号直接搜索
                        if replace_id.startswith('BV'):  # 如果是BV号
                            if no_search:
                                # 使用新的BV号搜索方法
                                video_info = dl_instance.get_video_info(replace_id)
                                # video_info = dl_instance.get_video_info(replace_id)
                                videos = [video_info]  # 包装成列表以保持接口一致
                            else:
                                # 如果查不到东西再硬指定
                                video_info = dl_instance.search_video(replace_id)
                                # videos = dl_instance.search_video(replace_id)
                                videos = [video_info]
                        
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
                        time.sleep(10)
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

# 加载旧搜索数据
exported_b30_search_config_file = current_paths['exported_b30_search_config']

if not os.path.exists(b30_config_file):
    st.error(f"未找到配置文件{b30_config_file}，请检查 Best50 数据完整性！", icon="❌")
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

    # 下载区域
    # 检查是否可以下载（至少有一个视频信息）
    has_video_info = any(song.get('video_info_match') for song in b30_config)
    
    if not has_video_info:
        st.warning("当前没有可下载的视频信息，请先为曲目添加视频信息", icon="⚠️")
    
    download_info_placeholder = st.empty()
    st.session_state.download_completed = False
    
    if st.button("确认并开始下载视频", disabled=not dl_instance or not has_video_info, width='stretch', icon="⏬"):
        try:
            st_download_video(download_info_placeholder, dl_instance, G_config, b30_config)
            st.session_state.download_completed = True
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
                    copy_search_args(b30_config_file, exported_b30_search_config_file)
                    st.toast("数据迁移成功！3 秒后刷新", icon="✅")
                    time.sleep(3)
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
else:
    st.error("配置文件加载失败，请检查文件完整性！", icon="❌")