import time
import random
import traceback
import os
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from pre_gen import download_one_video
from gene_images import diff_bg_change

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
    st.error("请先获取指定用户名的B30存档！")
    st.stop()

if save_id:
    # load save data
    current_paths = get_data_paths(username, save_id)
    data_loaded = True
    st.write(f"当前存档【用户名：{username}，存档时间：{save_id}】")

else:
    st.warning("未索引到存档，请先加载存档数据！")

with st.expander("更换B30存档"):
    st.info("如果要更换，请回到存档管理页指定其他用户名。")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            selected_save_id = st.selectbox(
                "选择存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y-%m-%d')})"
            )
            if st.button("使用此存档（只需要点击一次！）", use_container_width=True, icon="▶️"):
                if selected_save_id:
                    st.session_state.save_id = selected_save_id
                    st.rerun()
                else:
                    st.error("无效的存档路径！")
    else:
        st.warning("未找到任何存档，请先在存档管理页面获取存档！")
        st.stop()
### Savefile Management - End ###

def st_download_video(placeholder, dl_instance, G_config, b30_config):
    search_wait_time = G_config['SEARCH_WAIT_TIME']
    download_high_res = G_config['DOWNLOAD_HIGH_RES']
    video_download_path = f"./videos/downloads"
    with placeholder.container(border=True):
        with st.spinner("正在下载视频……"):
            progress_bar = st.progress(0)
            write_container = st.container(border=True, height=400)
            i = 0
            for song in b30_config:
                i += 1
                if 'video_info_match' not in song or not song['video_info_match']:
                    st.warning(f"没有找到({i}/30): {song['song_name']} 的视频信息，无法下载，请检查前置步骤是否完成")
                    write_container.write(f"跳过({i}/30): {song['song_name']} ，没有视频信息")
                    continue
                
                video_info = song['video_info_match']
                progress_bar.progress(i / 30, text=f"正在下载视频({i}/30): {video_info['title']}")
                
                result = download_one_video(dl_instance, song, video_download_path, download_high_res)
                write_container.write(f"【{i}/30】{result['info']}")

                # 等待几秒，以减少被检测为bot的风险
                if search_wait_time[0] > 0 and search_wait_time[1] > search_wait_time[0]:
                    time.sleep(random.randint(search_wait_time[0], search_wait_time[1]))

            st.success("下载完成！请点击下一步按钮核对视频素材的详细信息。", icon="✅")

# 在显示数据框之前，将数据转换为兼容的格式
def convert_to_compatible_types(data):
    if isinstance(data, list):
        return [{k: str(v) if isinstance(v, (int, float)) else v for k, v in item.items()} for item in data]
    elif isinstance(data, dict):
        return {k: str(v) if isinstance(v, (int, float)) else v for k, v in data.items()}
    return data

def update_editor(placeholder, config, current_index, dl_instance=None):
    def show_video_info(video_info: dict) -> None:
        """
        展示视频信息的函数，自动处理多页数据并忽略不存在的字段
        
        Args:
            video_info(dict): 包含视频信息的字典，可能包含多页数据
        """
        # 定义需要展示的字段及其翻译
        FIELD_MAPPING = {
            "id": "YouTube ID / BV号",
            "title": "标题",
            "url": "视频地址",
            "duration": "总时长(秒)",
            "page": "分P序号",
            "page_title": "分P标题",
            "page_url": "分P地址",
            "page_duration": "分P时长(秒)"
        }
        
        # 确定数据是单页还是多页格式
        is_multi_page = 'pages' in video_info and isinstance(video_info['pages'], list)
        
        if is_multi_page:
            # 处理多页视频数据
            for i, page in enumerate(video_info['pages']):
                st.subheader(f"分P {i+1} 信息")
                
                # 合并基础信息和分P信息
                combined_info = {
                    **{k: video_info.get(k) for k in ['id', 'title', 'url', 'duration']},
                    'page': i+1,
                    'page_title': page.get('title'),
                    'page_url': page.get('url'),
                    'page_duration': page.get('duration')
                }
                
                # 过滤并展示有效字段
                display_data = {
                    FIELD_MAPPING[k]: str(v) if v is not None else "无"
                    for k, v in combined_info.items() 
                    if k in FIELD_MAPPING and v is not None
                }
                
                st.json(display_data)
        else:
            # 处理单页视频数据
            display_data = {
                FIELD_MAPPING[k]: str(v) if v is not None else "无"
                for k, v in video_info.items()
                if k in FIELD_MAPPING and v is not None
            }
            
            st.json(display_data)

    def update_match_info(placeholder, v_info_match):
        with placeholder.container(border=True):
            st.markdown(f"""<p style="color: #00BFFF;">当前记录的谱面信息 : {song['song_name']} [{diff_bg_change(song['level_index'])}]</p>"""
                        , unsafe_allow_html=True)
            # 使用markdown添加带颜色的标题
            st.markdown("""<p style="color: #28a745;">当前匹配的视频信息 :</p>""", unsafe_allow_html=True)
            # 使用封装的函数展示视频信息
            show_video_info(v_info_match)

    with placeholder.container(border=True):
        song = config[current_index]
        # 获取当前匹配的视频信息
        st.subheader(f"片段ID: {song['clip_id']}")

        match_info_placeholder = st.empty()
        update_match_info(match_info_placeholder, song['video_info_match'])

        # 获取当前所有搜索得到的视频信息
        st.write("请检查上述视频信息与谱面是否匹配。如果有误，请从下方备选结果中选择正确的视频。")
        to_match_videos = song['video_info_list']
        
        # 为每个视频创建一个格式化的标签，包含可点击的链接
        video_options = [
            f"[{i+1}] 【{video['title']}】({video['duration']}秒) [🔗{video['id']}]({video['url']})"
            for i, video in enumerate(to_match_videos)
        ]
        
        selected_index = st.radio(
            "备选结果：",
            options=range(len(video_options)),
            format_func=lambda x: video_options[x],
            key=f"radio_select_{song['clip_id']}",
            label_visibility="visible"
        )

        # 显示选中视频的详细信息
        if selected_index is not None:
            with st.expander("查看已选项的详细信息"):
                show_video_info(to_match_videos[selected_index])

        if st.button("确定使用该信息", key=f"confirm_selected_match_{song['clip_id']}"):
            song['video_info_match'] = to_match_videos[selected_index]
            save_config(b30_config_file, config)
            st.toast("配置已保存！")
            update_match_info(match_info_placeholder, song['video_info_match'])
        
        # 如果搜索结果均不符合，手动输入地址：
        with st.container(border=True):
            st.markdown('<p style="color: #ffc107;">以上都不对？手动搜索正确的谱面确认视频：</p>', unsafe_allow_html=True)
            replace_id = st.text_input("搜索关键词 (建议为谱面确认视频的 youtube ID 或 BV号)", 
                                       key=f"replace_id_{song['clip_id']}")

            # 搜索手动输入的id
            to_replace_video_info = None
            extra_search_button = st.button("搜索并替换", 
                                            key=f"search_replace_id_{song['clip_id']}",
                                            disabled=dl_instance is None or replace_id == "")
            if extra_search_button:
                videos = dl_instance.search_video(replace_id.replace("BV", ""))
                if len(videos) == 0:
                    st.error("未找到有效的视频，请重试")
                else:
                    to_replace_video_info = videos[0]
                    st.success(f"已使用视频{to_replace_video_info['id']}替换匹配信息，详情：")
                    st.markdown(f"【{to_replace_video_info['title']}】({to_replace_video_info['duration']}秒) [🔗{to_replace_video_info['id']}]({to_replace_video_info['url']})")
                    song['video_info_match'] = to_replace_video_info
                    save_config(b30_config_file, config)
                    st.toast("配置已保存！")
                    update_match_info(match_info_placeholder, song['video_info_match'])



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

if b30_config:
    for song in b30_config:
        if not song['video_info_match'] or not song['video_info_list'] or not song['clip_id']:
            st.error(f"未找到有效视频下载信息，请检查上一步骤是否完成！", icon="❌")
            st.stop()

    # 获取所有视频片段的ID
    record_ids = [f"{item['clip_id']}: {item['song_name']} [{diff_bg_change(item['level_index'])}]" for item in b30_config]
    # 使用session_state来存储当前选择的视频片段索引
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0

    # 快速跳转组件的容器
    selector_container = st.container(border=True)

    # 片段预览和编辑组件，使用empty容器
    link_editor_placeholder = st.empty()
    update_editor(link_editor_placeholder, b30_config, st.session_state.current_index, dl_instance)

    # 快速跳转组件的实现
    def on_jump_to_record():
        target_index = record_ids.index(clip_selector)
        if target_index != st.session_state.current_index:
            st.session_state.current_index = target_index
            update_editor(link_editor_placeholder, b30_config, st.session_state.current_index, dl_instance)
        else:
            st.toast("已经是当前记录！", icon="ℹ️")
    
    with selector_container: 
        # 显示当前视频片段的选择框
        clip_selector = st.selectbox(
            label="快速跳转到B30记录", 
            options=record_ids, 
            key="record_selector"  # 添加唯一的key
        )
        if st.button("确定"):
            on_jump_to_record()

    # 上一个和下一个按钮
    col1, col2, col3 = st.columns([0.9, 0.9, 0.9])
    with col1:
        if st.button("上一个"):
            if st.session_state.current_index > 0:
                # # 保存当前配置
                # save_config(b30_config_file, b30_config)
                # st.toast("配置已保存！")
                # 切换到上一个视频片段
                st.session_state.current_index -= 1
                update_editor(link_editor_placeholder, b30_config, st.session_state.current_index, dl_instance)
            else:
                st.toast("到顶啦！", icon="❗")
    with col2:
        if st.button("下一个"):
            if st.session_state.current_index < len(record_ids) - 1:
                # # 保存当前配置
                # save_config(b30_config_file, b30_config)
                # st.toast("配置已保存！")
                # 切换到下一个视频片段
                st.session_state.current_index += 1
                update_editor(link_editor_placeholder, b30_config, st.session_state.current_index, dl_instance)
            else:
                st.toast("到底啦！", icon="❗")
    with col3: 
        # 保存配置按钮
        if st.button("保存当前配置"):
            save_config(b30_config_file, b30_config)
            st.toast("已保存当前配置！", icon="✅")

    download_info_placeholder = st.empty()
    st.session_state.download_completed = False
    if st.button("确认当前配置并开始下载视频", disabled=not dl_instance):
        try:
            st_download_video(download_info_placeholder, dl_instance, G_config, b30_config)
            st.session_state.download_completed = True  # Reset error flag if successful
        except Exception as e:
            st.session_state.download_completed = False
            st.error(f"下载过程中出现错误: {e}, 请尝试重新下载", icon="⚠️")
            st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❌")

    if st.button("下一步", disabled=not st.session_state.download_completed):
        st.switch_page("st_pages/4_Edit_Video_Content.py")
