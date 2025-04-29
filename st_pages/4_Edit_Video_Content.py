import time
import streamlit as st
import os
import json
import traceback
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from pre_gen import st_gene_resource_config

DEFAULT_VIDEO_MAX_DURATION = 180

class overflowErr(Exception):
    """自定义异常，处理超出顺序 ID 限制的情况"""
    pass

st.header("Step 4-1: 视频内容编辑")

G_config = read_global_config()

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

with st.expander("更换 Best30 存档"):
    st.info("要更换，请回到存档管理页指定其他用户名。")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            selected_save_id = st.selectbox(
                "选择存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y-%m-%d')})"
            )
            if st.button("使用此存档（只需要点击一次！）"):
                if selected_save_id:
                    st.session_state.save_id = selected_save_id
                    st.rerun()
                else:
                    st.error("无效的存档路径！")
    else:
        st.warning("未找到任何存档，请先在存档管理页获取存档！")
        st.stop()
if not save_id:
    st.stop()
### Savefile Management - End ###

image_output_path = current_paths['image_dir']
video_config_output_file = current_paths['video_config']
video_download_path = f"./videos/downloads"

def refresh_main_image_paths(config_path, username, save_id, max_order_id=30):
    """
    更新 video_config.json 中 main_image 字段的路径，使用当前的 username 和 save_id。

    Args:
        config_path: video_config.json 的完整路径
        username: 当前存档用户名
        save_id: 当前存档时间 ID（如 '20250410_123456'）
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError("找不到配置文件：" + config_path)

    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)

    new_base_path = os.path.normpath(f"b30_datas/{username}/{save_id}/images")

    for clip in config_data.get("main", []):
        if "main_image" in clip:
            current_image_path = clip["main_image"]
            # 通过当前路径提取出文件名部分，文件名是 Best_1.png 的格式
            file_name = current_image_path.split("\\")[-1]  # 获取文件名部分（如 Best_1.png）
            
            # 文件名始终是 Best_ + 顺序ID（Best_1.png, Best_2.png）
            # order_id = file_name.split("_")[1].split(".")[0]  # 提取顺序ID
            
            try:
                # 提取顺序ID
                order_id = int(file_name.split("_")[1].split(".")[0])
                if order_id > max_order_id:
                    raise overflowErr(f"您的 Best30 曲目数据存在问题（序号错误：{order_id}）")
                
            except overflowErr as e:
                # 在出现 overflowErr 错误时，继续调整顺序 ID
                order_id = max_order_id  # 从最大顺序 ID 开始递减
                max_order_id -= 1  # 递减，准备处理下一个顺序 ID
                print(f"{e}，调整为 {order_id}")
                if max_order_id < 1:  # 防止递减到小于1
                    max_order_id = 1

            # 构建新的路径
            new_image_path = os.path.join(new_base_path, f"Best_{order_id}.png")
            clip["main_image"] = os.path.normpath(new_image_path)

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

    print(f"已根据您的当前存档【用户名：{username}，存档时间：{save_id}】更新")
    return config_data

# 通过向empty容器添加新的container，更新预览
def update_preview(preview_placeholder, config, current_index):
    with preview_placeholder.container(border=True):
        # 获取当前视频的配置信息
        item = config['main'][current_index]

        # 检查是否存在图片和视频：
        if not os.path.exists(item['main_image']):
            st.error(f"图片 {item['main_image']} 不存在，请检查前置步骤是否完成！")
            return

        # 显示当前视频片段的内容
        st.subheader(f"正在编写: {item['song_name']}")
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            st.text(f"谱面与难度：{item['song_name']} [{LEVEL_LABELS[item['level_index']]}]")
        with info_col2:
            absolute_path = os.path.abspath(os.path.dirname(item['video']))
            st.text(f"谱面确认视频文件：{os.path.basename(item['video'])}")
            if st.button("打开视频存储文件夹", key=f"open_folder_{item['id']}", help=absolute_path):
                open_file_explorer(absolute_path)

        @st.dialog("删除视频确认")
        def delete_video_dialog():
            st.warning("真的要删除这个视频吗？此操作不可撤销！", icon="⚠️")
            st.success("删除片段后可在上一步重新搜索新的谱面确认。", icon="💬")
            if st.button("是的！我确定", key=f"confirm_delete_{item['id']}"):
                try:
                    os.remove(item['video'])
                    st.toast("视频已删除！")
                    st.rerun()
                except Exception as e:
                    st.error(f"删除失败：{traceback.format_exc()}")

        main_col1, main_col2 = st.columns(2)
        with main_col1:
            st.image(item['main_image'], caption="成绩图（中间的视频预览窗是透明的）")
        with main_col2:
            if os.path.exists(item['video']):
                st.video(item['video'])
                col1, col2 = st.columns([3, 1], vertical_alignment="center")
                with col1:
                    st.info(f"不是想要的？", icon="ℹ️")
                with col2:
                    if st.button("删除", key=f"delete_btn_{item['id']}", help="删除此视频"):
                        delete_video_dialog()
            else:
                st.warning("谱面确认视频不存在，请检查是否已完成下载！")
        # 显示当前视频片段的评论
        item['text'] = st.text_area("编辑评论", value=item.get('text', ''), key=f"text_{item['id']}",placeholder="请填写b30评价")

        # 从文件中获取视频的时长
        video_path = item['video']
        if os.path.exists(video_path):
            video_duration = int(get_video_duration(video_path))
        else:
            video_duration = DEFAULT_VIDEO_MAX_DURATION

        def get_valid_time_range(config_item):
            start = config_item.get('start', 0)
            end = config_item.get('end', 0) 
            # 如果起始时间大于等于结束时间，调整起始时间
            if start >= end:
                start = end - 1
            return start, end

        # 在使用select_slider之前，先获取有效的时间范围
        start_time, end_time = get_valid_time_range(config['main'][current_index])
        # # 然后再传入select_slider
        # start_time, end_time = st.select_slider(
        #     "选择视频片段的起始和结束时间",
        #     options=range(0, video_duration),
        #     value=(start_time, end_time)
        # )
        
        show_start_minutes = int(start_time // 60)
        show_start_seconds = int(start_time % 60)
        show_end_minutes = int(end_time // 60)
        show_end_seconds = int(end_time % 60)
        
        scol1, scol2, scol3 = st.columns(3, vertical_alignment="bottom")
        with scol1:
            st.subheader("起始时间")
        with scol2:
            start_min = st.number_input("分钟", min_value=0, value=show_start_minutes, step=1, key=f"start_min_{item['id']}")
        with scol3:
            start_sec = st.number_input("秒", min_value=0, max_value=59, value=show_start_seconds, step=1, key=f"start_sec_{item['id']}")
            
        ecol1, ecol2, ecol3 = st.columns(3, vertical_alignment="bottom")
        with ecol1:
            st.subheader("结束时间")
        with ecol2:
            end_min = st.number_input("分钟", min_value=0, value=show_end_minutes, step=1, key=f"end_min_{item['id']}")
        with ecol3:
            end_sec = st.number_input("秒", min_value=0, max_value=59, value=show_end_seconds, step=1, key=f"end_sec_{item['id']}")

        # 转换为总秒数
        start_time = start_min * 60 + start_sec
        end_time = end_min * 60 + end_sec

        # 确保结束时间大于起始时间
        if end_time <= start_time:
            st.warning("结束时间必须大于起始时间")
            end_time = start_time + 5

        # 确保结束时间不超过视频时长
        if end_time > video_duration:
            st.warning(f"结束时间不能超过视频时长: {int(video_duration // 60)}分{int(video_duration % 60)}秒")
            end_time = video_duration
            start_time = end_time - 5

        # 计算总秒数并更新config
        item['start'] = start_time
        item['end'] = end_time
        item['duration'] = end_time - start_time

        minutes = lambda x: int(x // 60)
        seconds = lambda x: int(x % 60)

        time_col1, time_col2, time_col3 = st.columns(3)
        with time_col1:
            st.subheader(f"起始于 {minutes(start_time):02d}:{seconds(start_time):02d}")
        with time_col2:
            st.subheader(f"结束于 {minutes(end_time):02d}:{seconds(end_time):02d}")
        with time_col3:
            st.subheader(f"长度为 {item['duration']} 秒")

# 读取下载器配置
if 'downloader_type' in st.session_state:
    downloader_type = st.session_state.downloader_type
else:
    downloader_type = G_config['DOWNLOADER']

# 读取存档的b30 config文件
if downloader_type == "youtube":
    b30_config_file = current_paths['config_yt']
elif downloader_type == "bilibili":
    b30_config_file = current_paths['config_bi']
if not os.path.exists(b30_config_file):
    st.error(f"未找到配置文件{b30_config_file}，请检查B30存档的数据完整性！", icon="⚠️")
    st.stop()
b30_config = load_config(b30_config_file)
video_config = load_config(video_config_output_file)

if not video_config or 'main' not in video_config:
    st.warning("该存档还没有视频内容的配置文件。请先生成配置后再编辑。", icon="⚠️")
    if st.button("生成视频内容配置"):
        st.toast("正在生成……", icon="ℹ️")
        try:
            video_config = st_gene_resource_config(b30_config, 
                                            image_output_path, video_download_path, video_config_output_file,
                                            G_config['CLIP_START_INTERVAL'], G_config['CLIP_PLAY_TIME'], G_config['DEFAULT_COMMENT_PLACEHOLDERS'],
                                            username=username, save_id=save_id
                                            )
            st.success("视频配置已生成！", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"视频配置生成失败，请检查步骤 1-3 是否正常完成！", icon="❌")
            st.exception(traceback.format_exc())
            video_config = None

if video_config:
    # 获取所有视频片段的ID
    video_ids = [f"{item['id']}: {item['song_name']} [{LEVEL_LABELS[item['level_index']]}]" \
                 for item in video_config['main']]
    # 使用session_state来存储当前选择的视频片段索引
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0

    # 快速跳转组件的容器
    selector_container = st.container(border=True)

    # 片段预览和编辑组件，使用empty容器
    preview_placeholder = st.empty()
    update_preview(preview_placeholder, video_config, st.session_state.current_index)

    # 快速跳转组件的实现
    def on_jump_to_clip():
        target_index = video_ids.index(clip_selector)
        # print(f"跳转到视频片段: {target_index}")
        if target_index != st.session_state.current_index:
            # 保存当前配置
            save_config(video_config_output_file, video_config)
            st.toast("配置已保存！", icon="✅")
            # 更新session_state
            st.session_state.current_index = target_index
            update_preview(preview_placeholder, video_config, st.session_state.current_index)
        else:
            st.toast("已经是当前视频片段！", icon="ℹ️")
    
    with selector_container: 
        # 显示当前视频片段的选择框
        clip_selector = st.selectbox(
            label="快速跳转到视频片段", 
            options=video_ids, 
            key="video_selector"  # 添加唯一的key
        )
        if st.button("确定"):
            on_jump_to_clip()

    should_skip = video_config['main'][st.session_state.current_index].get("skip", False)
    # 上一个和下一个按钮
    _, col1, col2, col3, col4 = st.columns([0.8, 2, 2, 2, 1])
    with col1:
        if st.button("上一片段"):
            if st.session_state.current_index > 0:
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                # 切换到上一个视频片段
                st.session_state.current_index -= 1
                update_preview(preview_placeholder, video_config, st.session_state.current_index)
            else:
                st.toast("到顶啦！", icon="❗")
    with col2:
        if st.button("下一片段"):
            if st.session_state.current_index < len(video_ids) - 1:
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                # 切换到下一个视频片段
                st.session_state.current_index += 1
                update_preview(preview_placeholder, video_config, st.session_state.current_index)
            else:
                st.toast("到底啦！", icon="❗")
    with col3:
        if should_skip:
            if st.button("取消跳过该片段"):
                video_config['main'][st.session_state.current_index]['skip'] = False
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
        else:
            if st.button("跳过该片段"):
                if st.session_state.current_index < len(video_ids) - 1:
                    video_config['main'][st.session_state.current_index]['skip'] = True
                    # 保存当前配置
                    save_config(video_config_output_file, video_config)
                    st.toast("配置已保存！", icon="✅")
                    # 切换到下一个视频片段
                    st.session_state.current_index += 1
                    update_preview(preview_placeholder, video_config, st.session_state.current_index)
                else:
                    st.toast("到底啦！", icon="❗")
    # 更新状态
    should_skip = video_config['main'][st.session_state.current_index].get("skip", False)
    with col4:
        # 保存配置按钮
        if st.button("保存"):
            save_config(video_config_output_file, video_config)
            st.success("配置已保存！", icon="✅")

with st.container(border=True):
    video_config_file = current_paths['video_config']
    video_download_path = f"./videos/downloads"
    absolute_path = os.path.abspath(os.path.dirname(video_config_file))
    st.write("若因手动更新 b30 等原因需要检查和修改配置，点击下方按钮打开配置文件夹。")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("打开配置文件夹", key=f"open_folder_video_config", help=absolute_path, icon="📂"):
            open_file_explorer(absolute_path)
    with col2:
        if st.button("更新生成配置的存档路径", icon="🔄", help="如果您拷贝了其他用户的配置文件，需点击此按钮更新"):
            try:
                refresh_main_image_paths(video_config_output_file, username, save_id)
                st.toast("配置路径已更新，3 秒后刷新", icon="✅")
                time.sleep(3)
                st.rerun()
            except Exception as e:
                st.error(f"更新失败：{e}", icon="❌")
    st.markdown(f"""注：`b30_configs_{downloader_type}.json` 是你当前使用平台的 b30 数据，
                `video_configs.json` 是视频的生成配置
                """)
    with st.container(border=True):
        st.error("危险区域 Danger Zone", icon="❗")
        st.write("如果无法正常读取图片、视频或评论，请尝试强制刷新配置文件。")
        st.warning("将清空所有已填写评论和时长数据，如有需要请备份 `video_configs.json`", icon="⚠️")
        _, col1, col2 = st.columns([0.5, 2, 2])
        with col1:
            @st.dialog("删除配置确认")
            def delete_video_config_dialog(file):
                st.warning("真的要删除配置并强制刷新吗？此操作不可撤销！", icon="⚠️")
                if st.button("是的！我确认删除并强制刷新", key=f"confirm_delete_video_config"):
                    try:
                        os.remove(file)
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除当前配置文件失败：{traceback.format_exc()}", icon="❌")

            if os.path.exists(video_config_file):
                if st.button("强制删除并刷新视频配置文件", key=f"delete_btn_video_config"):
                    delete_video_config_dialog(video_config_file)
            else:
                st.info("当前还没有视频生成配置文件", icon="ℹ️")

        with col2: 
            @st.dialog("删除视频确认")
            def delete_videoes_dialog(file_path):
                st.warning("真的要删除所有视频吗？此操作不可撤销！", icon="⚠️")
                if st.button("是的！我确定要删除所有视频", key=f"confirm_delete_videoes"):
                    try:
                        for file in os.listdir(file_path):
                            os.remove(os.path.join(file_path, file))
                        st.toast("所有已下载视频已清空！", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除视频失败: 详细错误信息: {traceback.format_exc()}")

            if os.path.exists(video_download_path):
                if st.button("删除所有已下载视频", key=f"delete_btn_videoes"):
                    delete_videoes_dialog(video_download_path)
            else:
                st.info("当前还没有下载任何视频")

if st.button("下一步"):
    st.switch_page("st_pages/5_Edit_OpEd_Content.py")