import time, os, json, traceback
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from utils.DataUtils import st_gen_resource_config
from utils.chuni_extension import REVERSE_LEVEL_LABELS

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
        st.info("要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
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
old_video_config_file = current_paths['old_video_config']
video_download_path = f"./videos/downloads"

def refresh_main_image_paths(config_path, username, save_id, max_order_id=50):
    """
    更新 video_config.json 中 main_image 字段的路径，使用当前的 username 和 save_id。

    Args:
        config_path: video_config.json 的完整路径
        username: 当前存档用户名
        save_id: 当前存档时间 ID（如 '20250410_123456'）
        max_order_id: 最大处理数 [50 条]
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
                    raise overflowErr(f"您的 Best50 曲目数据存在问题（序号错误：{order_id}）")
                
            except overflowErr as e:
                # 在出现 overflowErr 错误时，继续调整顺序 ID
                order_id = max_order_id  # 从最大顺序 ID 开始递减
                max_order_id -= 1  # 递减，准备处理下一个顺序 ID
                print(f"{e}，调整为 {order_id}")
                if max_order_id < 1:  # 防止递减到小于1
                    max_order_id = 1

            # 构建新的路径
            new_image_path = os.path.join(new_base_path, f"{clip['clip_id'].split('_')[0]}_{order_id}.png")
            clip["main_image"] = os.path.normpath(new_image_path)

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

    print(f"已根据您的当前存档【用户名：{username}，存档时间：{save_id}】更新")
    return config_data

def copy_video_args(config_path, old_config_path):
    """
    复制旧存档的 start, end, duration, text 到新存档

    Args:
        config_path: 新的 video_config.json 完整路径
        old_config_path: 旧的 video_config.json 完整路径
        username: 用户名
        save_id: 存档 ID

    Raises:
        FileNotFoundError: 未找到存档数据

    Returns:
        dict: 更新后的配置数据
    """
    if not os.path.exists(config_path) or not os.path.exists(old_config_path):
        missing_file = config_path if not os.path.exists(config_path) else old_config_path
        raise FileNotFoundError("找不到配置文件：" + missing_file)

    # 读取配置文件
    with open(old_config_path, 'r', encoding='utf-8') as f:
        old_config_data = json.load(f)
    with open(config_path, 'r', encoding='utf-8') as f:
        new_config_data = json.load(f)

    updated_count = 0
    skipped_count = 0

    # 获取对应的记录列表
    try:
        old_records = old_config_data["main"]
        new_records = new_config_data["main"]
    except KeyError as e:
        raise FileNotFoundError(f"在配置中找不到对应的数据: {e}")

    # 遍历所有记录进行匹配和更新
    for old_record in old_records:
        for new_record in new_records:
            # 检查匹配条件：id, song_name, artist, level_index
            if (old_record.get('id') == new_record.get('id') and
                old_record.get('song_name') == new_record.get('song_name') and
                old_record.get('artist') == new_record.get('artist') and
                old_record.get('level_index') == new_record.get('level_index')):
                
                # 检查需要更新的字段是否相同
                need_update = False
                fields_to_check = ['start', 'end', 'duration', 'text']
                
                for field in fields_to_check:
                    if old_record.get(field) != new_record.get(field):
                        need_update = True
                        break
                
                if need_update:
                    # 更新剪辑参数
                    new_record['start'] = old_record.get('start')
                    new_record['end'] = old_record.get('end')
                    new_record['duration'] = old_record.get('duration')
                    new_record['text'] = old_record.get('text')
                    updated_count += 1
                else:
                    skipped_count += 1
                
                break  # 找到匹配后跳出内层循环

    # 保存更新后的配置
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(new_config_data, f, ensure_ascii=False, indent=4)

    print(f"已成功更新 {updated_count} 条记录的剪辑参数，跳过 {skipped_count} 条无需更新的记录")
    return new_config_data

# 通过向empty容器添加新的container，更新预览
def update_preview(preview_placeholder, config, current_index):
    with preview_placeholder.container(border=True):
        # 快速跳转组件 - 现在放在框内但在大标题上方
        def on_jump_to_clip():
            target_index = video_ids.index(clip_selector)
            if target_index != st.session_state.current_index:
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                # 更新session_state
                st.session_state.current_index = target_index
                st.rerun()
                # update_preview(preview_placeholder, video_config, st.session_state.current_index)
            else:
                st.toast("已经是当前视频片段！", icon="ℹ️")
        
        # 快速跳转选择框 - 放在框内最上方
        col1, col2, col3 = st.columns([0.5, 3, .85], vertical_alignment="center")
        with col1:
            st.write("**快速跳转**")
        with col2:
            clip_selector = st.selectbox(
                label="快速跳转到指定曲目", 
                options=video_ids, 
                key=f"video_selector_{current_index}",
                index=current_index,
                label_visibility="collapsed"
            )
        with col3:
            if st.button("跳转", key=f"jump_btn_inside_{current_index}", use_container_width=True, icon="🔜"):
                on_jump_to_clip()

        # 获取当前视频的配置信息
        item = config['main'][current_index]

        # 检查是否存在图片和视频：
        if not os.path.exists(item['main_image']):
            st.error(f"图片 {item['main_image']} 不存在，请检查前置步骤是否完成！")
            return

        # 显示当前视频片段的内容
        # st.subheader(f"正在编写: {item['song_name']}")
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            st.write(f"**谱面与难度：** {item['song_name']} {[REVERSE_LEVEL_LABELS.get(item['level_index'])]}")
        with info_col2:
            absolute_path = os.path.abspath(os.path.dirname(item['video']))
            st.write(f"**谱面确认视频文件：** {os.path.basename(item['video'])}")


        @st.dialog("删除视频确认")
        def delete_video_dialog():
            st.warning("""
                       真的要删除这个视频吗？此操作不可撤销！
                       - 删除片段后可在上一步重新搜索新的谱面确认。
                       """, icon="⚠️")
            st.success(f"""如果您只是替换，请记下它本来的名称（底下的框）
                       \n - 要与原视频名称相同才可被使用
                       \n - 必须为 mp4 类型 + 后缀\n
                       {os.path.basename(item['video'])}
                       """, icon="💬")
            if st.button("是的！我确定", key=f"confirm_delete_{item['id']}", use_container_width=True, icon="☑️"):
                try:
                    os.remove(item['video'])
                    st.toast("视频已删除！", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"删除失败：{traceback.format_exc()}")

        main_col1, main_col2 = st.columns(2)
        with main_col1:
            st.image(item['main_image'], caption="成绩图（中间的视频预览窗是透明的）")
            if st.button("打开视频存储文件夹", key=f"open_folder_{item['id']}", help=absolute_path, use_container_width=True, icon="📂"):
                open_file_explorer(absolute_path)
        with main_col2:
            if os.path.exists(item['video']):
                st.video(item['video'])
                # st.write("")
                # st.write("")
                if st.button("直接删除！", key=f"delete_btn_{item['id']}", 
                             help=f"不是你喜欢的谱面确认？",
                             use_container_width=True,
                             icon="🗑️"
                             ):
                    delete_video_dialog()
            else:
                st.warning(f"""
                           文件不存在，请检查是否已下载！
                           - 如替换请命名为 {item['id']}-{REVERSE_LEVEL_LABELS.get(item['level_index'])}.mp4
                           """, icon="⚠️")
        # 显示当前视频片段的评论
        item['text'] = st.text_area("编辑评论", value=item.get('text', ''), key=f"text_{item['id']}_{current_index}",placeholder="请填写 Best50 评价")

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
        
        show_start_minutes = int(start_time // 60)
        show_start_seconds = int(start_time % 60)
        show_end_minutes = int(end_time // 60)
        show_end_seconds = int(end_time % 60)
        
        scol1, scol2, scol3 = st.columns(3, vertical_alignment="bottom")
        with scol1:
            st.subheader("于此时开始：")
        with scol2:
            start_min = st.number_input("分钟", min_value=0, value=show_start_minutes, step=1, key=f"start_min_{item['id']}_{current_index}")
        with scol3:
            start_sec = st.number_input("秒", min_value=0, max_value=59, value=show_start_seconds, step=1, key=f"start_sec_{item['id']}_{current_index}")
            
        ecol1, ecol2, ecol3 = st.columns(3, vertical_alignment="bottom")
        with ecol1:
            st.subheader("于此时结束：")
        with ecol2:
            end_min = st.number_input("分钟", min_value=0, value=show_end_minutes, step=1, key=f"end_min_{item['id']}_{current_index}")
        with ecol3:
            end_sec = st.number_input("秒", min_value=0, max_value=59, value=show_end_seconds, step=1, key=f"end_sec_{item['id']}_{current_index}")

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
            st.subheader(f"开始于 {minutes(start_time):02d}:{seconds(start_time):02d}")
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
    st.error(f"未找到配置文件【{b30_config_file}】，请检查 Best50 存档数据完整性！", icon="⚠️")
    st.stop()
b30_config = load_config(b30_config_file)
video_config = load_config(video_config_output_file)

if not video_config or 'main' not in video_config:
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        st.warning("该存档还没有配置，请生成后再编辑。", icon="⚠️")
    with col2:
        if st.button("生成视频内容配置", icon="⏬", use_container_width=True):
            st.toast("正在生成……", icon="ℹ️")
            try:
                video_config = st_gen_resource_config(b30_config, 
                                                image_output_path, video_download_path, video_config_output_file,
                                                G_config['CLIP_START_INTERVAL'], G_config['CLIP_PLAY_TIME'], G_config['DEFAULT_COMMENT_PLACEHOLDERS']
                                                # username=username, save_id=save_id
                                                )
                st.success("视频配置已生成！", icon="✅")
                st.rerun()
            except Exception as e:
                st.toast(f"视频配置生成失败，请检查步骤 1-3 是否正常完成！", icon="❌")
                st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❗")
                video_config = None

if video_config:
    # 获取所有视频片段的ID
    video_ids = [f"[{item['clip_id'].split('_', 1)[0]}#{item['clip_id'].split('_', 1)[1]},{REVERSE_LEVEL_LABELS.get(item['level_index'])}] - {item['song_name']}" for item in video_config['main']]
    # 使用session_state来存储当前选择的视频片段索引
    if 'current_index' not in st.session_state:
        st.session_state.current_index = 0

    # 片段预览和编辑组件，使用empty容器
    preview_placeholder = st.empty()
    update_preview(preview_placeholder, video_config, st.session_state.current_index)

    should_skip = video_config['main'][st.session_state.current_index].get("skip", False)
    # 上一个和下一个按钮
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("上一片段", icon="⏮️", use_container_width=True):
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
        if st.button("下一片段", icon="⏭️", use_container_width=True):
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
            if st.button("取消跳过", use_container_width=True, icon="⤵️"):
                video_config['main'][st.session_state.current_index]['skip'] = False
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                st.rerun()
        else:
            if st.button("跳过", use_container_width=True, icon="⤴️"):
                if st.session_state.current_index < len(video_ids) - 1:
                    video_config['main'][st.session_state.current_index]['skip'] = True
                    # 保存当前配置
                    save_config(video_config_output_file, video_config)
                    st.toast("配置已保存！", icon="✅")
                    # 切换到下一个视频片段
                    st.session_state.current_index += 1
                    update_preview(preview_placeholder, video_config, st.session_state.current_index)
                    st.rerun()
                else:
                    st.toast("到底啦！", icon="❗")
    # 更新状态
    should_skip = video_config['main'][st.session_state.current_index].get("skip", False)

    with col4:
        # 保存配置按钮
        if st.button("保存", use_container_width=True, icon="💾"):
            save_config(video_config_output_file, video_config)
            st.toast("配置已保存！", icon="✅")

with st.container(border=True):
    video_config_file = current_paths['video_config']
    video_download_path = f"./videos/downloads"
    absolute_path = os.path.abspath(os.path.dirname(video_config_file))
    # st.write("若因手动更新 b50 等原因需要检查和修改配置，点击下方按钮打开配置文件夹。")
    with st.expander("因手动更新 Best50 或替换谱面确认等原因，需要检查和修改配置？", icon="❓️"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("打开配置文件夹", key=f"open_folder_video_config", icon="📂",
                        help=f"""
                        {absolute_path}
                        - `images` 为 Best50 图像，`videos` 为生成片段
                        """, use_container_width=True):
                open_file_explorer(absolute_path)
        
        with col2:
            download_folder_path = os.path.abspath(video_download_path)
            if video_config is not None and st.button("打开谱面确认下载文件夹", key=f"open_folder_video_downloaded", icon="🎥",
                        help=f"""
                        {download_folder_path}
                        - 将谱面确认以 [ID]-[难度] 命名，拷贝至此目录，例如 `{video_config['main'][0]['id']}-{REVERSE_LEVEL_LABELS.get(video_config['main'][0]['level_index'])}.mp4`
                        """, use_container_width=True):
                open_file_explorer(download_folder_path)
    
    with st.expander("需要从旧的（或者别人的）存档迁移 / 更新数据？", icon="💾"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("更新成绩图存档路径", icon="🔄", help="如果您拷贝了其他用户的配置文件，需点击此按钮更新", use_container_width=True):
                try:
                    refresh_main_image_paths(video_config_output_file, username, save_id)
                    st.toast("配置路径已更新，3 秒后刷新", icon="✅")
                    time.sleep(3)
                    st.rerun()
                except Exception as e:
                    st.error(f"更新失败：{e}", icon="❌")
        with col2:
            if st.button("迁移旧存档剪辑数据", icon="⏫", help=f"""
                         如果您需要迁移剪辑数据，请使用此项
                         - 将旧存档命名为 `old_video_config.json`
                         - 放置在当前存档 `{save_id}` 下
                         """, use_container_width=True):
                try:
                    copy_video_args(video_config_output_file, old_video_config_file)
                    st.toast("数据迁移成功！3 秒后刷新", icon="✅")
                    time.sleep(3)
                    st.rerun()
                except Exception as e:
                    st.error(f"迁移失败：{e}", icon="❌")
    st.info(f"`b30_configs_{downloader_type}.json` 是当前平台 b30 数据，`video_configs.json` 是视频生成配置", icon="ℹ️")
    with st.expander("危险区域 Danger Zone", icon="❗"):
        st.warning("若已填写内容，则操作前必须备份 `video_configs.json`", icon="⚠️")
        # st.write("如果无法正常读取图片、视频或评论，请尝试强制刷新配置文件。")
        # st.warning("将清空所有已填写评论和时长数据，如有需要请备份 `video_configs.json`", icon="⚠️")
        col1, col2 = st.columns(2)
        with col1:
            @st.dialog("删除配置确认")
            def delete_video_config_dialog(file):
                st.warning("""
                        真的要强制刷新吗？
                        - 此操作需删除您的配置文件，且不可撤销！
                        """, icon="⚠️")
                if st.button("是的！请删掉吧", key=f"confirm_delete_video_config", icon="🗑️", use_container_width=True):
                    try:
                        os.remove(file)
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除当前配置文件失败：{traceback.format_exc()}", icon="❌")

            if os.path.exists(video_config_file):
                if st.button("强制刷新视频配置文件", key=f"delete_btn_video_config", icon="↩️", use_container_width=True, help="仅限于无法正常读取图片、视频或评论时使用"):
                    delete_video_config_dialog(video_config_file)
            else:
                st.info("当前还没有视频生成配置文件", icon="ℹ️")

        with col2: 
            @st.dialog("删除视频确认")
            def delete_videoes_dialog(file_path):
                st.warning("真的要删除所有视频吗？此操作不可撤销！", icon="⚠️")
                if st.button("是的！我确定要删除所有视频", key=f"confirm_delete_videoes", icon="🗑️", use_container_width=True):
                    try:
                        for file in os.listdir(file_path):
                            os.remove(os.path.join(file_path, file))
                        st.toast("所有已下载视频已清空！", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除视频失败：{traceback.format_exc()}", icon="❗")

            if os.path.exists(video_download_path):
                if st.button("删除所有已下载视频", key=f"delete_btn_videoes", icon="🗑️", use_container_width=True, help="如果你的全部视频在编辑过程中损坏，请使用此项后前往上一步重新下载视频"):
                    delete_videoes_dialog(video_download_path)
            else:
                st.info("当前还没有下载任何视频")

if st.button("下一步", icon="➡️", use_container_width=True):
    st.switch_page("st_pages/5_Edit_OpEd_Content.py")