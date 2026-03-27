import streamlit as st
import time, os, traceback
from datetime import datetime
from utils.PathUtils import *
from utils.DataUtils import gen_video_config
from utils.Variables import REVERSE_LEVEL_LABELS

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
        st.info("要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
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
    if not save_id:
        st.stop()
### Savefile Management - End ###

image_output_path = f"{current_paths['image_dir']}/background"
video_config_output_file = current_paths['video_config']
old_video_config_file = current_paths['old_video_config']
video_download_path = f"./videos/downloads"

def refresh_main_image_paths(config_path, username, save_id, max_order_id):
    """
    更新 video_config.json 中 main_image 字段的路径，使用当前的 username 和 save_id。

    Args:
        config_path: video_config.json 的完整路径
        username: 当前存档用户名
        save_id: 当前存档时间 ID（如 '20250410_123456'）
        max_order_id: 最大处理数
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError("找不到配置文件：" + config_path)

    config_data = load_config(config_path)

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

    save_config(config_path, config_data)

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
        new_config_data(dict): 更新后的配置数据
    """
    if not os.path.exists(config_path) or not os.path.exists(old_config_path):
        missing_file = config_path if not os.path.exists(config_path) else old_config_path
        raise FileNotFoundError("找不到配置文件：" + missing_file)

    # 读取配置文件
    old_config_data = load_config(old_config_path)
    new_config_data = load_config(config_path)

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
    save_config(config_path, new_config_data)

    print(f"已成功更新 {updated_count} 条记录的剪辑参数，跳过 {skipped_count} 条无需更新（不符合）的记录")
    return new_config_data

# 通过向empty容器添加新的container，更新预览
def update_preview(preview_placeholder, config, current_index):
    with preview_placeholder.container(border=True):
        # 快速跳转组件 - 现在放在框内但在大标题上方
        def on_jump_to_clip():
            # 添加安全检查
            if not video_ids or clip_selector not in video_ids:
                st.toast("无效的选择！", icon="⚠️")
                return
                
            target_index = video_ids.index(clip_selector)
            if target_index != st.session_state.current_index:
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                # 更新session_state
                st.session_state.current_index = target_index
                st.rerun()
            else:
                st.toast("已经是当前视频片段！", icon="ℹ️")
        
        # 快速跳转选择框 - 放在框内最上方
        col1, col2, col3 = st.columns([0.5, 3, .85], vertical_alignment="center")
        with col1:
            st.write("**快速跳转**")
        with col2:
            # 添加索引安全检查
            safe_index = current_index
            if video_ids:  # 确保选项列表不为空
                safe_index = min(current_index, len(video_ids) - 1)
                safe_index = max(0, safe_index)  # 确保索引非负
            else:
                safe_index = 0
                
            clip_selector = st.selectbox(
                label="快速跳转到指定曲目", 
                options=video_ids, 
                key=f"video_selector_{current_index}",
                index=safe_index,
                label_visibility="collapsed"
            )
        with col3:
            if st.button("跳转", key=f"jump_btn_inside_{current_index}", width='stretch', icon="🔜"):
                on_jump_to_clip()

        # 获取当前视频的配置信息
        # 添加额外的安全检查
        if not config or 'main' not in config or current_index >= len(config['main']):
            st.error("配置数据无效或索引超出范围！")
            return
            
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
            if st.button("是的！我确定", key=f"confirm_delete_{item['id']}", width='stretch', icon="☑️"):
                try:
                    os.remove(item['video'])
                    st.toast("视频已删除！", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"删除失败：{traceback.format_exc()}")

        main_col1, main_col2 = st.columns(2)
        with main_col1:
            st.image(item['main_image'], caption="成绩图（中间的视频预览窗是透明的）")
            if st.button("打开视频存储文件夹", key=f"open_folder_{item['id']}", help=absolute_path, width='stretch', icon="📂"):
                open_file_explorer(absolute_path)
        with main_col2:
            if os.path.exists(item['video']):
                st.video(item['video'])
                # st.write("")
                # st.write("")
                if st.button("直接删除！", key=f"delete_btn_{item['id']}", 
                             help=f"不是你喜欢的谱面确认？",
                             width='stretch',
                             icon="🗑️"
                             ):
                    delete_video_dialog()
            else:
                st.warning(f"""
                           文件不存在，请检查是否已下载！
                           - 替换则命名为 {item['id']}-{REVERSE_LEVEL_LABELS.get(item['level_index'])}.mp4
                           - 随后重新加载存档，如果没生效请手动修改配置文件
                           """, icon="⚠️")
        # 显示当前视频片段的评论
        item['text'] = st.text_area("编辑评论",
                                    value=item.get('text', ''),
                                    key=f"text_{item['id']}_{current_index}",
                                    placeholder="填写 Best50 评论（emoji 无法被渲染，请尽可能不要输入 emoji）",
                                    help="每超过 12 行将多分 1 个平均时长的评论页"
                                    )

        # 从文件中获取视频的时长
        video_path = item['video']
        if os.path.exists(video_path):
            video_duration = int(get_video_duration(video_path))
        else:
            video_duration = DEFAULT_VIDEO_MAX_DURATION

        def get_valid_time_range(config_item, video_duration=DEFAULT_VIDEO_MAX_DURATION):
            start = config_item.get('start', 0)
            end = config_item.get('end', video_duration)
            
            # 确保值有效
            start = max(0, min(start, video_duration - 1))
            end = max(1, min(end, video_duration))
            
            # 确保结束时间大于起始时间
            if end <= start:
                # 自动步进值，用于处理时间超界
                end = min(start + 1, video_duration)
                # start = max(0, end - 1)
            
            return start, end

        # 工具函数定义（放在时间部分的最前面）
        def format_time(seconds: int) -> tuple:
            """将秒数转换为(分钟, 秒)元组"""
            return int(seconds // 60), int(seconds % 60)

        def to_seconds(minutes: int, seconds: int) -> int:
            """将分钟和秒转换为总秒数"""
            return minutes * 60 + seconds

        # 在使用select_slider之前，先获取有效的时间范围
        start_time, end_time = get_valid_time_range(config['main'][current_index])
        show_start_minutes, show_start_seconds = format_time(start_time)
        show_end_minutes, show_end_seconds = format_time(end_time)
        # show_start_minutes = int(start_time // 60)
        # show_start_seconds = int(start_time % 60)
        # show_end_minutes = int(end_time // 60)
        # show_end_seconds = int(end_time % 60)
        minutes = lambda x: int(x // 60)
        seconds = lambda x: int(x % 60)
        
        # 计算分钟的最大值
        max_minutes = video_duration // 60

        # 保存原始的结束时间（用户设置的值）
        original_end_time = end_time

        scol1, scol2, scol3 = st.columns(3, vertical_alignment="bottom")
        with scol1:
            st.subheader("于此时开始：")
        with scol2:
            start_min = st.number_input("分钟", min_value=0, max_value=max_minutes, value=show_start_minutes, step=1, help="下同", key=f"start_min_{item['id']}_{current_index}")
        with scol3:
            # 根据分钟数动态计算最大秒数
            # if start_min == max_minutes:
            #     max_start_sec = video_duration % 60  # 最后一分钟的剩余秒数
            # else:
            #     max_start_sec = 59
            
            max_start_sec = seconds(video_duration) if start_min == max_minutes else 59
            
            # 确保当前值不超过最大秒数
            current_start_sec = min(show_start_seconds, max_start_sec)
            
            start_sec = st.number_input("秒", min_value=0, max_value=max_start_sec, value=current_start_sec, step=1, help="下同", key=f"start_sec_{item['id']}_{current_index}")

        # 计算开始时间总秒数
        current_start_time = start_min * 60 + start_sec

        ecol1, ecol2, ecol3 = st.columns(3, vertical_alignment="bottom")
        with ecol1:
            st.subheader("于此时结束：")
        with ecol2:
            # 结束分钟的最小值
            min_end_min = start_min  # 不能小于开始分钟
            
            # 尝试保持用户原本设置的结束分钟，但要确保不小于开始分钟
            preferred_end_min = show_end_minutes
            # if preferred_end_min < min_end_min:
            #     preferred_end_min = min_end_min
            
            preferred_end_min = min_end_min if preferred_end_min < min_end_min else show_end_minutes
            
            end_min = st.number_input(
                "分钟", 
                min_value=min_end_min,  # 动态最小值
                max_value=max_minutes, 
                value=preferred_end_min,  # 优先使用用户原本设置的值
                step=1, label_visibility="collapsed",
                key=f"end_min_{item['id']}_{current_index}"
            )
        with ecol3:
            # 根据分钟数动态计算最大秒数
            # if end_min == max_minutes:
            #     max_end_sec = seconds(video_duration)
            # else:
            #     max_end_sec = 59
            
            max_end_sec = seconds(video_duration) if end_min == max_minutes else 59
            
            # 计算结束秒数的最小值
            # min_end_sec = 0
            # if end_min == start_min:
            #     # 同一分钟，结束秒数必须大于开始秒数
            #     min_end_sec = min(start_sec + 1, max_end_sec)
            
            min_end_sec = min(start_sec + 1, max_end_sec) if end_min == start_min else 0
            
            # 优先使用用户原本设置的结束秒数，但要确保在有效范围内
            preferred_end_sec = show_end_seconds
            # if end_min == start_min:
            #     # 同一分钟时，确保不小于最小值
            #     preferred_end_sec = max(preferred_end_sec, min_end_sec)
            preferred_end_sec = max(preferred_end_sec, min_end_sec) if end_min == start_min else show_end_seconds
            
            # 确保不超过最大值
            preferred_end_sec = min(preferred_end_sec, max_end_sec)
            
            end_sec = st.number_input(
                "秒", 
                min_value=min_end_sec,  # 动态最小值
                max_value=max_end_sec, 
                value=preferred_end_sec,  # 优先使用用户原本设置的值
                step=1, label_visibility="collapsed",
                key=f"end_sec_{item['id']}_{current_index}"
            )

        # 计算结束时间
        end_time = to_seconds(end_min, end_sec)

        # 如果结束时间小于等于开始时间，显示警告但不自动调整（让用户手动调整）
        if end_time <= current_start_time:
            st.error("⚠️ 结束时间必须大于开始时间")
            # 这里不自动调整，让用户手动修改结束时间
            # 只设置一个合理的默认值，但保留用户原本的意图
            if end_time == current_start_time:
                # 如果恰好相等，自动加1秒
                end_time = min(current_start_time + 1, video_duration)
                # 更新显示
                end_min, end_sec = format_time(end_time)
                # end_min = minutes(end_time)
                # end_sec = seconds(end_time)

        # 确保结束时间不超过视频时长
        if end_time > video_duration:
            st.warning(f"结束时间已调整为视频末尾: {minutes(video_duration)} 分 {seconds(video_duration)} 秒")
            end_time = video_duration
            end_min, end_sec = format_time(end_time)
            end_min = minutes(end_time)
            end_sec = seconds(end_time)

        # 计算总秒数并更新config
        item['start'] = current_start_time
        item['end'] = end_time
        item['duration'] = end_time - current_start_time

        time_col1, time_col2, time_col3 = st.columns(3)
        with time_col1:
            st.subheader(f"开始于 {minutes(current_start_time):02d}:{seconds(current_start_time):02d}", help="仅为当前片段的开始时间")
        with time_col2:
            st.subheader(f"结束于 {minutes(end_time):02d}:{seconds(end_time):02d}", help="仅为当前片段的结束时间")
        with time_col3:
            st.subheader(f"长度为 {item['duration']} 秒", help="仅为当前片段的长度")
    
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
video_config = load_config(video_config_output_file, use_cache=False) if os.path.exists(video_config_output_file) else None

if not video_config or 'main' not in video_config:
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        st.warning("该存档还没有配置，请生成后再编辑。", icon="⚠️")
    with col2:
        if st.button("生成视频内容配置", icon="⏬", width='stretch'):
            st.toast("正在生成……", icon="ℹ️")
            try:
                video_config = gen_video_config(b30_config, image_output_path, video_download_path, video_config_output_file,
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
    vid_col1, vid_col2, vid_col3 = st.columns(3)
    with vid_col1:
        if st.button("上一片段", icon="⏮️", width='stretch'):
            if st.session_state.current_index > 0:
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                # 切换到上一个视频片段
                st.session_state.current_index -= 1
                update_preview(preview_placeholder, video_config, st.session_state.current_index)
            else:
                st.toast("到顶啦！", icon="❗")

    with vid_col2:
        if st.button("下一片段", icon="⏭️", width='stretch'):
            if st.session_state.current_index < len(video_ids) - 1:
                # 保存当前配置
                save_config(video_config_output_file, video_config)
                st.toast("配置已保存！", icon="✅")
                # 切换到下一个视频片段
                st.session_state.current_index += 1
                update_preview(preview_placeholder, video_config, st.session_state.current_index)
            else:
                st.toast("到底啦！", icon="❗")

    # with col3:
    #     if should_skip:
    #         if st.button("取消跳过", width='stretch', icon="⤵️", help="如果又想写这首曲子的评价，可以取消跳过"):
    #             video_config['main'][st.session_state.current_index]['skip'] = False
    #             # 保存当前配置
    #             save_config(video_config_output_file, video_config)
    #             st.toast("配置已保存！", icon="✅")
    #             st.rerun()
    #     else:
    #         if st.button("跳过", width='stretch', icon="⤴️", help="如果暂时不想写这首曲子的评价，可以跳过（渲染不会跳过）"):
    #             if st.session_state.current_index < len(video_ids) - 1:
    #                 video_config['main'][st.session_state.current_index]['skip'] = True
    #                 # 保存当前配置
    #                 save_config(video_config_output_file, video_config)
    #                 st.toast("配置已保存！", icon="✅")
    #                 # 切换到下一个视频片段
    #                 st.session_state.current_index += 1
    #                 update_preview(preview_placeholder, video_config, st.session_state.current_index)
    #                 st.rerun()
    #             else:
    #                 st.toast("到底啦！", icon="❗")
    # 更新状态
    # should_skip = video_config['main'][st.session_state.current_index].get("skip", False)

    with vid_col3:
        # 保存配置按钮
        if st.button("保存", width='stretch', icon="💾"):
            save_config(video_config_output_file, video_config)
            st.toast("配置已保存！", icon="✅")

if st.button("下一步", icon="➡️", width='stretch'):
    st.switch_page("st_pages/5_Edit_OpEd_Content.py")
    
st.header("⚙️附加设置", divider="rainbow")
with st.container(border=False):
    video_config_file = current_paths['video_config']
    video_download_path = f"./videos/downloads"
    absolute_path = os.path.abspath(os.path.dirname(video_config_file))
    additional_setting1, additional_setting2 = st.columns(2)
    # st.write("若因手动更新 b50 等原因需要检查和修改配置，点击下方按钮打开配置文件夹。")
    with additional_setting1:
        with st.expander("因手动更新 Best50 或替换谱面确认等原因，需要检查和修改配置？", icon="❓️"):
            col1, col2 = st.columns(2)
            with col1:
                if st.button("打开配置文件夹", key=f"open_folder_video_config", icon="📂",
                            help=f"""
                            {absolute_path}
                            - `images` 为 Best50 图像，`videos` 为生成片段
                            """, width='stretch'):
                    open_file_explorer(absolute_path)
            
            with col2:
                download_folder_path = os.path.abspath(video_download_path)
                if video_config is not None and st.button("打开谱面确认下载文件夹", key=f"open_folder_video_downloaded", icon="🎥",
                            help=f"""
                            {download_folder_path}
                            - 将谱面确认以 [ID]-[难度] 命名，拷贝至此目录，例如 `{video_config['main'][0]['id']}-{REVERSE_LEVEL_LABELS.get(video_config['main'][0]['level_index'])}.mp4`
                            """, width='stretch'):
                    open_file_explorer(download_folder_path)
    
    with additional_setting2:
        with st.expander("需要（从其他的、别人的存档）迁移 / 更新数据？", icon="💾"):
            st.warning("""
            如果存档中有数据需要修改，请在生成配置之前，前往【生成成绩图】页修改
            - 配置生成后将难于修改，若已经生成，请（迁移）剪辑数据
            - 要迁移的数据若均不在新数据内，请（刷新配置）重新生成
                - 请注意**先备份原来的配置文件，再进行操作**！
            - ［仍要强制迁移］将新数据中要迁移曲目的以下字段，复制到对应旧数据：
                - `id`(曲目 ID), `song_name`(曲名), `artist`(曲师), `level_index`(难度)
                - 两份数据中以上字段需相互符合才会被复制，请确保其内部无任何变化。
            """, icon="💬")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("更新成绩图存档路径", icon="🔄", help="""
                            如果您对本存档的配置文件执行了以下这些操作，需更新路径：
                            - 您 `拷贝了` 其他玩家的配置文件来使用
                            - 您的配置文件 `在生成后提示图片/视频路径不存在`
                                - 请确定图片和视频文件均已存在后再执行。
                            """, width='stretch'):
                    try:
                        refresh_main_image_paths(video_config_output_file, username, save_id, len(video_config_output_file))
                        st.toast("配置路径已更新，3 秒后刷新", icon="✅")
                        time.sleep(3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新失败：{e}", icon="❌")
            with col2:
                if st.button("迁移旧存档剪辑数据", icon="⏫", help=f"""
                            如果您需要迁移剪辑数据，请完成以下操作后，使用此项
                             - 将旧存档的配置文件命名为 `old_video_configs.json`
                             - 放置在当前存档 `{save_id}` 配置文件相同位置下
                            """, width='stretch'):
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
        col1, col2 = st.columns(2, vertical_alignment="center")
        with col1:
            @st.dialog("删除配置确认")
            def delete_video_config_dialog(file):
                st.warning("""
                        真的要强制刷新吗？
                        - 此操作需删除您的配置文件，且不可撤销！
                        """, icon="⚠️")
                if st.button("是的！请删掉吧", key=f"confirm_delete_video_config", icon="🗑️", width='stretch'):
                    try:
                        os.remove(file)
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除当前配置文件失败：{traceback.format_exc()}", icon="❌")

            if os.path.exists(video_config_file):
                if st.button("强制刷新视频配置文件", key=f"delete_btn_video_config", icon="↩️", width='stretch', help="仅限于无法正常读取图片、视频或评论时使用"):
                    delete_video_config_dialog(video_config_file)
            else:
                st.info("当前还没有视频生成配置文件", icon="ℹ️")

        with col2: 
            @st.dialog("删除视频确认")
            def delete_videoes_dialog(file_path):
                st.warning("真的要删除所有视频吗？此操作不可撤销！", icon="⚠️")
                if st.button("是的！我确定要删除所有视频", key=f"confirm_delete_videoes", icon="🗑️", width='stretch'):
                    try:
                        for file in os.listdir(file_path):
                            os.remove(os.path.join(file_path, file))
                        st.toast("所有已下载视频已清空！", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"删除视频失败：{traceback.format_exc()}", icon="❗")

            if os.path.exists(video_download_path):
                if st.button("删除所有已下载视频", key=f"delete_btn_videoes", icon="🗑️", width='stretch', help="如果你的全部视频在编辑过程中损坏，请使用此项后前往上一步重新下载视频"):
                    delete_videoes_dialog(video_download_path)
            else:
                st.info("当前还没有下载任何视频")
