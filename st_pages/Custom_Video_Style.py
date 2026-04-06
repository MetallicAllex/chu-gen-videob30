import streamlit as st
import os, shutil, time
from utils.PathUtils import *
from utils.ImageUtils import generate_single_image
from utils.Variables import root_path, bgclips_path, audios_path, image_root_path, thumbnails_dir

# 页面标题
st.set_page_config(
    page_title="自定义视频样式",
    page_icon="🎨"
)

G_config = read_global_config()  # 读取全局配置

st.title("🎨 自定义视频样式")

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
    if not save_id:
        st.stop()
### Savefile Management - End ###

# 添加悬停效果CSS（从5_Edit_OpEd_Content.py复制）
st.markdown("""
<style>
/* 基础tabs样式 */
.stTabs {
    width: 100%;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    padding: 2px;
    border-radius: 8px;
}

.stTabs [data-baseweb="tab"] {
    flex: 1;
    text-align: center;
    padding: 10px 0;
    font-weight: 600;
    background-color: transparent;
    color: #666;
    position: relative;
    border: none;
    overflow: hidden;
    z-index: 1;
    transition: color 0.3s ease;
}

/* 当前选中状态 */
.stTabs [aria-selected="true"] {
    color: #ff4b4b;
}

/* 悬停效果 - 从底部填充 */
.stTabs [data-baseweb="tab"]::before {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 0;
    background-color: #ff4b4b;
    z-index: -1;
    transition: height 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    border-radius: 4px 4px 0 0;
}

.stTabs [data-baseweb="tab"]:hover::before {
    height: 100%;
}

.stTabs [data-baseweb="tab"]:hover {
    color: white;
}
</style>
""", unsafe_allow_html=True)

# def update_preview_images(style_config, placeholder, test_string):

#     record_template = {
#         "clip_id": "Best_1",
#         "id": 2401,
#         "song_name": "オンソクデイズ!!",
#         "artist": "cosMo＠暴走P",
#         "score": 1008529,
#         "rating": 17.0029,
#         "level": 14.9,
#         "level_next": 14.9,
#         "level_index": 3,
#         "full_combo": "fullcombo",
#         "full_chain": None,
#         "play_count": None
#     }

#     intro_template = {
#         "id": "intro_1",
#         "duration": 2,
#         "text": test_string,
#         "bg_page": True
#     }
    
#     video_template = {
#         "id": 2401,
#         "clip_id": "Best_1",
#         "song_name": "オンソクデイズ!!",
#         "artist": "cosMo＠暴走P",
#         "level": 14.9,
#         "level_next": 14.9,
#         "level_index": 3,
#         "score": 1008529,
#         "rating": 17.0029,
#         "full_combo": "fullcombo",
#         "full_chain": None,
#         "main_image": None,
#         "video": "videos\\downloads\\2401-MASTER.mp4",
#         "duration": 2,
#         "start": 121,
#         "end": 123,
#         "text": test_string
#     }
    
#     with placeholder.container(border=True):
#         st.info("提示：此效果仅供预览您的自定义样式修改，需要点击下方按钮保存方可生效！")

#         # Render Preview 1
#         pil_img1 = get_video_preview_frame(
#             clip_config=intro_template,
#             style_config=style_config,
#             resolution=G_config.get("VIDEO_RES", (1920, 1080)),
#             part="intro"
#         )
#         st.image(pil_img1, caption="预览图1(片头)")

#         # Render Preview 2
#         # generate test image
#         test_image_path = os.path.join(f"{root_path}/thumbnails", "test_achievement.png")
#         video_template['main_image'] = test_image_path
#         # BUG: CHECK GENERATE IMAGE
#         generate_single_image(record_template, test_image_path, "TEST", 1)

#         # get preivew video frame
#         pil_img2 = get_video_preview_frame(
#             clip_config=intro_template,
#             style_config=style_config,
#             resolution=G_config.get("VIDEO_RES", (1920, 1080)),
#             part="content"
#         )
#         st.image(pil_img2, caption="预览图2(正片)")

custom_dir = current_paths['custom_style']
# if not os.path.exists(custom_dir):
#     st.toast("无法找到存档内的样式文件，已复制默认样式文件至存档。", icon="✅️")
#     shutil.copy2(f"{root_path}/themes/default.json", custom_dir)

# 初始化 session state
# if 'preset_style' not in st.session_state:
#     st.session_state.preset_style = "default"  # 设置默认值

# sel_preset_style = st.radio("选择预设模版", options=["default", "init"], key="preset_style",
#             horizontal=True, help="仅更改画面图像，不会修改字体等参数", captions=["由 mai-gen 官方制作的默认模版", "由哔哩哔哩 @init_ 制作的 PPT 模版"])

# 预设样式选择
preset_col1, preset_col2 = st.columns([3, 1])
with preset_col1:
    sel_preset_style = st.selectbox(
        "选择要复制的预设模板", options=["default", "init"],
        key="preset_style_selector",
        help="""
default: 由 mai-gen 官方制作的默认模版\n
init: 由哔哩哔哩 @init_ 制作的 PPT 模版
        """ if not os.path.exists(custom_dir) else "❌ 当前已存在样式文件，无法再次应用预设模板！（如需要，请删除此文件重新复制）",
        disabled=os.path.exists(custom_dir)
    )
with preset_col2:
    apply_preset = st.button("应用模板", icon="✅️", help="❌ 当前已存在样式文件，无法再次应用预设模板！（如需要，请删除此文件重新复制）", use_container_width=True, type="primary", disabled=os.path.exists(custom_dir))
    if apply_preset:
        if sel_preset_style == "default":
            st.session_state.preset_style = "default"
            shutil.copy2(f"{root_path}/themes/default.json", custom_dir)
        elif sel_preset_style == "init":
            st.session_state.preset_style = "init"
            shutil.copy2(f"{root_path}/themes/init.json", custom_dir)
        else:
            st.toast("请选择预设模板！", icon="⚠️")
# 原有的 radio 可以移除或改为只读显示
# sel_preset_style = st.radio(...)  # 这行可以删除或注释掉

custom_col1, custom_col2 = st.columns(2)
with custom_col1:
    # 背景素材上传区域（用于替换曲目背景图和难度框图像）
    with st.expander("前景素材", icon="🖼️"):
            tab_bg, tab_frames = st.tabs(["🎨 谱面确认框架", "🖼️ 难度框"])
            with tab_bg:
                st.info("上传谱面确认框架（.png，分辨率 1920 × 1080）")
                
                # 初始化状态
                if "bg_image_upload_info" not in st.session_state:
                    st.session_state.bg_image_upload_info = None
                
                # 检查备份文件是否存在
                bg_image_bak_path = os.path.join(f"{image_root_path}/Base/content", "content_base-bak.png")
                has_bg_image_backup = os.path.exists(bg_image_bak_path)
                
                # 显示当前图片信息
                current_bg_image_path = os.path.join(f"{image_root_path}/Base/content", "content_base.png")
                if current_bg_image_path and os.path.exists(current_bg_image_path):
                    st.image(current_bg_image_path, caption="素材预览窗") # 添加窗口预览
                    bginfo_col1, bginfo_col2 = st.columns([.45, .55])
                    with bginfo_col1:
                        file_size = os.path.getsize(current_bg_image_path) / (1024 * 1024)  # MB
                        st.caption(f"当前使用 content_base.png ({file_size:.2f} MB)")
                    with bginfo_col2:
                        # 显示备份文件信息（如果有）
                        if has_bg_image_backup:
                            bak_size = os.path.getsize(bg_image_bak_path) / (1024 * 1024)  # MB
                            st.caption(f"原始备份 content_base-bak.png ({bak_size:.2f} MB)", help="如果自动还原失败，请手动复制 content_base-bak.png 修改为 content_base.png 还原")
                
                # 如果已经有上传信息，显示上传状态
                if st.session_state.bg_image_upload_info:
                    bg_col1, bg_col2, bg_col3 = st.columns([1, .5, .5], vertical_alignment="center")
                    with bg_col1:
                        st.success(f"✅ 图片已更新为：{st.session_state.bg_image_upload_info['name']}")
                    with bg_col2:
                        if st.button("上传新图片", key="upload_new_bg_image", icon="📤", width='stretch'):
                            st.session_state.bg_image_upload_info = None
                            st.rerun()
                    with bg_col3:
                        # 只有存在备份文件时才显示还原按钮
                        if has_bg_image_backup:
                            if st.button("还原图片", key="restore_bg_image", icon="🔄️", width='stretch'):
                                try:
                                    # 还原操作：用备份文件替换当前文件
                                    if current_bg_image_path:
                                        # 删除当前文件
                                        if os.path.exists(current_bg_image_path):
                                            os.remove(current_bg_image_path)
                                        # 复制备份文件
                                        shutil.copy2(bg_image_bak_path, current_bg_image_path)
                                        st.toast("✅ 图片已还原为原始素材！", icon="✅")
                                        st.session_state.bg_image_upload_info = None
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"还原失败：{str(e)}", icon="❌")
                        else:
                            st.button("还原背景图片", key="restore_bg_image_disabled", icon="🔄️", 
                                    width='stretch', disabled=True, 
                                    help="没有找到原始备份文件")
                else:
                    # 显示文件上传器
                    bg_image_file = st.file_uploader(
                        "选择自定义背景图片", type="png",key="bg_image_uploader", disabled=sel_preset_style != "自定义", 
                        help="❌️ 仅自定义样式可修改" if sel_preset_style != "自定义" else "将替换现有的 content_base.png 文件（将应用到所有谱面确认）"
                    )
                    
                    # 如果选择了文件，显示文件信息和确认按钮
                    if bg_image_file is not None:
                        with st.container(border=True):
                            st.write("**上传文件信息**")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write(f"📁 文件名：{bg_image_file.name}")
                                st.write(f"📊 大小：{bg_image_file.size / (1024 * 1024):.2f} MB")
                            
                            with col2:
                                confirm_col1, confirm_col2 = st.columns(2)
                                with confirm_col1:
                                    if st.button("确认替换", type="primary", key="confirm_bg_image", width='stretch'):
                                        if current_bg_image_path:
                                            try:
                                                # 备份当前文件（如果存在且没有备份）
                                                if os.path.exists(current_bg_image_path) and not has_bg_image_backup:
                                                    shutil.copy2(current_bg_image_path, bg_image_bak_path)
                                                
                                                # 保存新文件
                                                with open(current_bg_image_path, "wb") as f:
                                                    f.write(bg_image_file.getbuffer())
                                                
                                                # 存储上传信息
                                                st.session_state.bg_image_upload_info = {
                                                    "name": bg_image_file.name,
                                                    "size": bg_image_file.size
                                                }
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"替换失败：{str(e)}", icon="❌")
                                        else:
                                            st.error("无法保存：未找到有效的图片路径", icon="❌")
                                
                                with confirm_col2:
                                    if st.button("取消", key="cancel_bg_image", width='stretch'):
                                        # 清除上传的文件状态
                                        st.session_state.pop("bg_image_uploader", None)
                                        st.rerun()
            
            with tab_frames:
                st.info("上传难度框图像（.png，对应不同难度等级的边框）")
                
                # 难度等级选择
                frame_levels = {
                    "0": "BASIC",
                    "2": "EXPERT", 
                    "3": "MASTER",
                    "4": "ULTIMA"
                }
                
                selected_level = st.selectbox(
                    "选择要替换的难度等级",
                    options=list(frame_levels.keys()),
                    format_func=lambda x: f"{frame_levels[x]} (等级 {x})",
                    help="选择要替换的难度边框图片"
                )
                
                # 初始化状态
                frame_state_key = f"frame_{selected_level}_upload_info"
                if frame_state_key not in st.session_state:
                    st.session_state[frame_state_key] = None
                
                # 检查备份文件是否存在
                frame_bak_path = os.path.join(image_root_path, f"Frames/{selected_level}-bak.png")
                has_frame_backup = os.path.exists(frame_bak_path)
                
                # 显示当前图片信息
                current_frame_path = os.path.join(image_root_path, f"Frames/{selected_level}.png")
                if current_frame_path and os.path.exists(current_frame_path):
                    st.image(current_frame_path, caption="素材预览窗")
                    frameinfo_col1, frameinfo_col2 = st.columns(2)
                    with frameinfo_col1:
                        file_size = os.path.getsize(current_frame_path) / 1024  # KB
                        st.caption(f"当前使用 {selected_level}.png ({file_size:.2f} KB)")
                    
                    with frameinfo_col2:
                        # 显示备份文件信息（如果有）
                        if has_frame_backup:
                            bak_size = os.path.getsize(frame_bak_path) / 1024  # KB
                            st.caption(f"原始备份 {selected_level}-bak.png ({bak_size:.2f} KB)", help="如果自动还原失败，请手动复制备份文件还原")
                
                # 如果已经有上传信息，显示上传状态
                if st.session_state[frame_state_key]:
                    frame_col1, frame_col2, frame_col3 = st.columns([1, .5, .5], vertical_alignment="center")
                    with frame_col1:
                        st.success(f"✅ {frame_levels[selected_level]} 边框已更新为：{st.session_state[frame_state_key]['name']}")
                    with frame_col2:
                        if st.button("上传新边框", key=f"upload_new_frame_{selected_level}", icon="📤", width='stretch'):
                            st.session_state[frame_state_key] = None
                            st.rerun()
                    with frame_col3:
                        # 只有存在备份文件时才显示还原按钮
                        if has_frame_backup:
                            if st.button("还原边框图片", key=f"restore_frame_{selected_level}", icon="🔄️", width='stretch'):
                                try:
                                    # 还原操作：用备份文件替换当前文件
                                    if current_frame_path:
                                        # 删除当前文件
                                        if os.path.exists(current_frame_path):
                                            os.remove(current_frame_path)
                                        # 复制备份文件
                                        shutil.copy2(frame_bak_path, current_frame_path)
                                        st.toast(f"✅ {frame_levels[selected_level]} 边框已还原为原始素材！", icon="✅")
                                        st.session_state[frame_state_key] = None
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"还原失败：{str(e)}", icon="❌")
                        else:
                            st.button("还原边框图片", key=f"restore_frame_{selected_level}_disabled", icon="🔄️", 
                                    width='stretch', disabled=True, 
                                    help="没有找到原始备份文件")
                else:
                    # 显示文件上传器
                    frame_file = st.file_uploader(
                        f"选择 {frame_levels[selected_level]} 边框", type="png",
                        key=f"frame_uploader_{selected_level}", disabled=sel_preset_style != "自定义",
                        help="❌️ 仅自定义样式可修改" if sel_preset_style != "自定义" else f"将替换现有的 {selected_level}.png 文件（{frame_levels[selected_level]} 难度边框）"
                    )
                    
                    # 如果选择了文件，显示文件信息和确认按钮
                    if frame_file is not None:
                        with st.container(border=True):
                            st.write("**上传文件信息**")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write(f"📁 文件名：{frame_file.name}")
                                st.write(f"📊 大小：{frame_file.size / 1024:.2f} KB")
                            
                            with col2:
                                confirm_col1, confirm_col2 = st.columns(2)
                                with confirm_col1:
                                    if st.button("确认替换", type="primary", key=f"confirm_frame_{selected_level}", width='stretch'):
                                        if current_frame_path:
                                            try:
                                                # 备份当前文件（如果存在且没有备份）
                                                if os.path.exists(current_frame_path) and not has_frame_backup:
                                                    shutil.copy2(current_frame_path, frame_bak_path)
                                                
                                                # 保存新文件
                                                with open(current_frame_path, "wb") as f:
                                                    f.write(frame_file.getbuffer())
                                                
                                                # 存储上传信息
                                                st.session_state[frame_state_key] = {
                                                    "name": frame_file.name,
                                                    "size": frame_file.size
                                                }
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"替换失败：{str(e)}", icon="❌")
                                        else:
                                            st.error("无法保存：未找到有效的图片路径", icon="❌")
                                
                                with confirm_col2:
                                    if st.button("取消", key=f"cancel_frame_{selected_level}", width='stretch'):
                                        # 清除上传的文件状态
                                        st.session_state.pop(f"frame_uploader_{selected_level}", None)
                                        st.rerun()

with custom_col2:
    # 背景素材上传区域（用于替换）
    with st.expander("背景素材", icon="🪟"):
        tab_video, tab_audio = st.tabs(["🎬 背景视频", "🎵 背景音乐"])
        # 添加悬停效果CSS（和上面共用）
        with tab_video:
            st.info("上传视频背景素材（.mp4，分辨率 1080p 或更高）")
            
            # 初始化状态
            if "video_upload_info" not in st.session_state:
                st.session_state.video_upload_info = None
            
            # 检查备份文件是否存在
            video_bak_path = os.path.join(bgclips_path, "bg_bak.mp4") if bgclips_path else None
            has_video_backup = os.path.exists(video_bak_path) if video_bak_path else False
            
            # 显示背景视频的预览窗口
            st.video(video_bak_path, format="video/mp4", start_time=0, width=520)
            st.caption("背景视频预览窗", text_alignment="center")
            
            # 显示当前视频信息（始终显示）
            current_video_path = os.path.join(bgclips_path, "bg.mp4") if bgclips_path else None
            if current_video_path and os.path.exists(current_video_path):
                bginfo_col1, bginfo_col2 = st.columns(2)
                with bginfo_col1:
                    file_size = os.path.getsize(current_video_path) / (1024 * 1024)  # MB
                    st.caption(f"当前视频：bg.mp4 ({file_size:.2f} MB)")
                
                with bginfo_col2:
                    # 显示备份文件信息（如果有）
                    if has_video_backup:
                        bak_size = os.path.getsize(video_bak_path) / (1024 * 1024)  # MB
                        st.caption(f"原始备份：bg_bak.mp4 ({bak_size:.2f} MB)", help="如果自动还原失败，请手动复制 bg_bak.mp4 修改为 bg.mp4 还原")
            
            # 如果已经有上传信息，显示上传状态
            if st.session_state.video_upload_info:
                bg_col1, bg_col2, bg_col3 = st.columns([1, .5, .5], vertical_alignment="center")
                with bg_col1:
                    st.success(f"✅ 视频已更新为：{st.session_state.video_upload_info['name']}")
                with bg_col2:
                    if st.button("上传新视频", key="upload_new_video", icon="📤", width='stretch'):
                        st.session_state.video_upload_info = None
                        st.rerun()
                with bg_col3:
                    # 只有存在备份文件时才显示还原按钮
                    if has_video_backup:
                        if st.button("还原背景素材", key="restore_video", icon="🔄️", width='stretch'):
                            try:
                                # 还原操作：用备份文件替换当前文件
                                if current_video_path:
                                    # 删除当前文件
                                    if os.path.exists(current_video_path):
                                        os.remove(current_video_path)
                                    # 复制备份文件
                                    shutil.copy2(video_bak_path, current_video_path)
                                    st.toast("✅ 视频已还原为原始素材！", icon="✅")
                                    st.session_state.video_upload_info = None
                                    st.rerun()
                            except Exception as e:
                                st.error(f"还原失败：{str(e)}", icon="❌")
                    else:
                        st.button("还原背景素材", key="restore_video_disabled", icon="🔄️", 
                                width='stretch', disabled=True, 
                                help="没有找到原始备份文件")
            else:
                # 显示文件上传器
                video_file = st.file_uploader(
                    "选择视频文件",
                    type="mp4", disabled=sel_preset_style != "自定义",
                    key="bg_video_uploader",
                    help="❌️ 仅自定义样式可修改" if sel_preset_style != "自定义" else "将替换现有的 bg.mp4 文件（将应用到整个分表视频）"
                )
                
                # 如果选择了文件，显示文件信息和确认按钮
                if video_file is not None:
                    with st.container(border=True):
                        st.write("**上传文件信息**")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"📁 文件名：{video_file.name}")
                            st.write(f"📊 大小：{video_file.size / (1024 * 1024):.2f} MB")
                        
                        with col2:
                            confirm_col1, confirm_col2 = st.columns(2)
                            with confirm_col1:
                                if st.button("确认替换", type="primary", key="confirm_video", width='stretch'):
                                    if bgclips_path and current_video_path:
                                        try:
                                            # 备份当前文件（如果存在且没有备份）
                                            if os.path.exists(current_video_path) and not has_video_backup:
                                                shutil.copy2(current_video_path, video_bak_path)
                                            
                                            # 保存新文件
                                            with open(current_video_path, "wb") as f:
                                                f.write(video_file.getbuffer())
                                            
                                            # 存储上传信息
                                            st.session_state.video_upload_info = {
                                                "name": video_file.name,
                                                "size": video_file.size
                                            }
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"替换失败：{str(e)}", icon="❌")
                                    else:
                                        st.error("无法保存：未找到有效的存档路径", icon="❌")
                            
                            with confirm_col2:
                                if st.button("取消", key="cancel_video", width='stretch'):
                                    # 清除上传的文件状态
                                    st.session_state.pop("bg_video_uploader", None)
                                    st.rerun()

        with tab_audio:
            st.info("上传背景音乐（.mp3 格式）")
            
            # 初始化状态
            if "audio_upload_info" not in st.session_state:
                st.session_state.audio_upload_info = None
            
            # 检查备份文件是否存在
            audio_bak_path = os.path.join(audios_path, "bgm_bak.mp3") if audios_path else None
            has_audio_backup = os.path.exists(audio_bak_path) if audio_bak_path else False
            
            # 显示音频预览条
            st.audio(audio_bak_path, format="audio/mp3", start_time=0)
            st.caption("背景音乐试听", text_alignment="center")
            
            # 显示当前音频信息（始终显示）
            current_audio_path = os.path.join(audios_path, "bgm.mp3") if audios_path else None
            if current_audio_path and os.path.exists(current_audio_path):
                bgminfo_col1, bgminfo_col2 = st.columns(2)
                with bgminfo_col1:
                    file_size = os.path.getsize(current_audio_path) / (1024 * 1024)  # MB
                    st.caption(f"当前音频：bgm.mp3 ({file_size:.2f} MB)")
                
                with bgminfo_col2:
                    # 显示备份文件信息（如果有）
                    if has_audio_backup:
                        bak_size = os.path.getsize(audio_bak_path) / (1024 * 1024)  # MB
                        st.caption(f"原始备份：bgm_bak.mp3 ({bak_size:.2f} MB)", help="如果自动还原失败，请手动复制 bgm_bak.mp3 修改为 bgm.mp3 还原")
            
            # 如果已经有上传信息，显示上传状态
            if st.session_state.audio_upload_info:
                bgm_col1, bgm_col2, bgm_col3 = st.columns([1, .5, .5], vertical_alignment="center")
                with bgm_col1:
                    st.success(f"✅ 音频已更新为：{st.session_state.audio_upload_info['name']}")
                with bgm_col2:
                    if st.button("上传新音频", key="upload_new_audio", icon="📤", width='stretch'):
                        st.session_state.audio_upload_info = None
                        st.rerun()
                with bgm_col3:
                    # 只有存在备份文件时才显示还原按钮
                    if has_audio_backup:
                        if st.button("还原背景音乐", key="restore_audio", icon="🔄️", width='stretch', help="如果自动还原失败，请手动复制 bgm_bak.mp4 修改为 bgm.mp4 还原"):
                            try:
                                # 还原操作
                                if current_audio_path:
                                    # 删除当前文件
                                    if os.path.exists(current_audio_path):
                                        os.remove(current_audio_path)
                                    # 复制备份文件
                                    shutil.copy2(audio_bak_path, current_audio_path)
                                    st.toast("✅ 音频已还原为原始素材！", icon="✅")
                                    st.session_state.audio_upload_info = None
                                    st.rerun()
                            except Exception as e:
                                st.error(f"还原失败：{str(e)}", icon="❌")
                    else:
                        st.button("还原背景音乐", key="restore_audio_disabled", icon="🔄️", 
                                width='stretch', disabled=True,
                                help="没有找到原始备份文件")
            else:
                # 显示文件上传器
                audio_file = st.file_uploader(
                    "选择音频文件",
                    type="mp3", disabled=sel_preset_style != "自定义",
                    key="bgm_audio_uploader",
                    help="❌️ 仅自定义样式可修改" if sel_preset_style != "自定义" else "将替换现有的 bgm.mp3 文件（只影响开头结尾）"
                )
                
                # 如果选择了文件，显示文件信息和确认按钮
                if audio_file is not None:
                    with st.container(border=True):
                        st.write("**上传文件信息**")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"📁 文件名：{audio_file.name}")
                            st.write(f"📊 大小：{audio_file.size / (1024 * 1024):.2f} MB")
                        
                        with col2:
                            confirm_col1, confirm_col2 = st.columns(2)
                            with confirm_col1:
                                if st.button("确认替换", type="primary", key="confirm_audio", width='stretch'):
                                    if audios_path and current_audio_path:
                                        try:
                                            # 备份当前文件（如果存在且没有备份）
                                            if os.path.exists(current_audio_path) and not has_audio_backup:
                                                shutil.copy2(current_audio_path, audio_bak_path)
                                            
                                            # 保存新文件
                                            with open(current_audio_path, "wb") as f:
                                                f.write(audio_file.getbuffer())
                                            
                                            # 存储上传信息
                                            st.session_state.audio_upload_info = {
                                                "name": audio_file.name,
                                                "size": audio_file.size
                                            }
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"替换失败：{str(e)}", icon="❌")
                                    else:
                                        st.error("无法保存：未找到有效的存档路径", icon="❌")
                            
                            with confirm_col2:
                                if st.button("取消", key="cancel_audio", width='stretch'):
                                    # 清除上传的文件状态
                                    st.session_state.pop("bgm_audio_uploader", None)
                                    st.rerun()

custom_data = load_config(current_paths['custom_style'])

# 递归处理坐标输入框
def render_coordinates(key_prefix, data, base_path="", name_mapping=None, use_expander=True):
    """
    递归处理坐标输入框
    Args:
        key_prefix: 基础路径前缀（如 "position"）
        data: 要处理的JSON数据
        base_path: 当前处理的路径（用于生成唯一key）
        name_mapping: 键名到显示名称的映射字典
        use_expander: 是否对当前层的字典使用expander（默认为True）
    """
    if name_mapping is None:
        name_mapping = {}
    
    idx = 0
    for key, value in data.items():
        # 构建当前路径
        current_path = f"{base_path}.{key}" if base_path else key
        # 构建唯一key（包含基础前缀）
        unique_key = f"{key_prefix}.{current_path}" if key_prefix else current_path
        
        # 获取显示名称（如果有映射则使用映射，否则使用原键名）
        display_name = name_mapping.get(key, key)
        
        if isinstance(value, list) and len(value) == 2:  # 处理坐标 [x, y]
            # 判断是否为浮点数（比例系数）
            is_ratio_x = isinstance(value[0], float) and not value[0].is_integer()
            is_ratio_y = isinstance(value[1], float) and not value[1].is_integer()
            is_ratio = is_ratio_x or is_ratio_y
            
            title, col1, col2 = st.columns(3, vertical_alignment="center")
            
            with title:
                st.header(display_name)  # 使用显示名称
            with col1:
                # 检查原始值是否为整数，或者浮点数是否等于整数
                original_x = value[0]
                is_int_x = isinstance(original_x, int) or (isinstance(original_x, float) and original_x.is_integer())
                
                # 根据数据类型设置标签
                x_label = "X 比例系数" if is_ratio else "X 坐标(px)"
                x = st.number_input(
                    x_label, disabled=sel_preset_style != "自定义",
                    value=original_x, help="❌️ 仅自定义样式可修改" if sel_preset_style != "自定义" else None,
                    step=1 if is_int_x else 0.1,
                    format="%d" if is_int_x else "%f",
                    key=f"{unique_key}_x",
                )
            with col2:
                # 检查原始值是否为整数，或者浮点数是否等于整数
                original_y = value[1]
                is_int_y = isinstance(original_y, int) or (isinstance(original_y, float) and original_y.is_integer())
                
                # 根据数据类型设置标签
                y_label = "Y 比例系数" if is_ratio else "Y 坐标(px)"
                y = st.number_input(
                    y_label, disabled=sel_preset_style != "自定义",
                    value=original_y, help="❌️ 仅自定义样式可修改" if sel_preset_style != "自定义" else None,
                    step=1 if is_int_y else 0.1,
                    format="%d" if is_int_y else "%f",
                    key=f"{unique_key}_y",
                )
            
            # 根据原始数据类型决定返回整数还是浮点数
            if is_int_x and is_int_y:
                data[key] = [int(x), int(y)]
            else:
                data[key] = [float(x), float(y)]
                
            idx += 1
        
        elif isinstance(value, dict):  # 处理嵌套字典
            # 判断是否使用expander
            if use_expander:
                with st.expander(f"{display_name}"):
                    # 对下一级决定是否使用expander
                    # level 下面的 integer、current、next 可能也需要expander？根据需求调整
                    next_use_expander = key == "level"  # 如果是level，则它的子项也使用expander
                    render_coordinates(key_prefix, value, base_path=current_path, 
                                     name_mapping=name_mapping, use_expander=next_use_expander)
            else:
                # 不使用expander，直接渲染内容
                render_coordinates(key_prefix, value, base_path=current_path, 
                                 name_mapping=name_mapping, use_expander=True)  # 内层默认使用expander


# 在文件开头添加通用配置渲染函数
def render_simple_config(data, config_type, display_names, columns_per_row=4):
    """
    渲染简单的配置项（大小、宽度、对齐等）
    
    Args:
        data: 配置数据字典
        config_type: 配置类型 ('size', 'maxWidth', 'align')
        display_names: 键名到显示名称的映射字典
        columns_per_row: 每行显示的列数
    """
    # 根据类型设置不同的提示和选项
    config_info = {
        'size': {
            'info': "调整字体大小（单位：像素）",
            'help': "❌️ 仅自定义样式可修改",
            'widget': 'number_input',
            'params': {'min_value': 1, 'step': 1}
        },
        'maxWidth': {
            'info': "调整最大宽度（单位：像素）",
            'help': "❌️ 仅自定义样式可修改",
            'widget': 'number_input',
            'params': {'min_value': 1, 'step': 1}
        },
        'align': {
            'info': "调整文本对齐方式",
            'help': "❌️ 仅自定义样式可修改",
            'widget': 'selectbox',
            'params': {'options': ["left", "center", "right"]}
        }
    }
    
    info = config_info[config_type]
    st.info(info['info'])
    
    # 将字典项转换为列表
    items = list(data.items())
    
    # 计算需要的行数
    rows = (len(items) + columns_per_row - 1) // columns_per_row
    
    for row_idx in range(rows):
        cols = st.columns(columns_per_row)
        start_idx = row_idx * columns_per_row
        end_idx = min(start_idx + columns_per_row, len(items))
        
        for col_idx, (key, value) in enumerate(items[start_idx:end_idx]):
            with cols[col_idx]:
                display_name = display_names.get(key, key)
                display_name_config = {
                    'size': f"{display_name} 字体大小",
                    'maxWidth': f"{display_name} 最大宽度",
                    'align': f"{display_name} 对齐方式"
                }[config_type]
                if info['widget'] == 'number_input':
                    new_value = st.number_input(
                        display_name_config,
                        value=value,
                        key=f"{config_type}_{key}",
                        # disabled=sel_preset_style != "自定义",
                        help=info['help'],
                        **info['params']
                    )
                    data[key] = new_value
                    
                elif info['widget'] == 'selectbox':
                    options = info['params']['options']
                    current_index = options.index(value) if value in options else 0
                    new_value = st.selectbox(
                        display_name_config,options,
                        index=current_index,
                        key=f"{config_type}_{key}",
                        # disabled=sel_preset_style != "自定义",
                        help=info['help']
                    )
                    data[key] = new_value

if os.path.exists(current_paths['custom_style']):
    # 在调用时指定要解析的标签和名称映射
    with st.expander("画面参数", icon="📝"):
        st.error("此区域仍在开发中！", icon="⚠️")
        
        coords, size, color, maxWidth, align = st.tabs(["坐标", "字体大小", "字体颜色", "最大宽度", "对齐"])
        with coords:
            # 定义名称映射
            image_name_mapping = {
                "frame": "难度边框",
                "level": "等级信息",
                "integer": "整数等级",
                "current": "当前等级",
                "next": "下版本等级",
                "score": "分数",
                "rating": "定数",
                "combo": "连击数",
                "chain": "Chain 数",
                "title": "曲名",
                "artist": "艺术家",
                "bestNum": "Best 序号",
                "playCount": "游玩次数",
                "base": "背景位置",
                "text": "文本位置",
                "combined": "角标位置"  # init 模板特有
            }
            
            # 只解析 "image" 标签下的内容
            if "image" in custom_data["position"]:
                image_data = {"image": custom_data["position"]["image"]}
                # 设置 use_expander=False 让 image 本身不使用 expander
                render_coordinates("image", image_data, name_mapping=image_name_mapping, use_expander=False)
            
    col1, col2, col3, col4 = st.columns(4, vertical_alignment="center")
    # with col1:
        # if st.button("保存所有修改", icon="💾", width='stretch', disabled=sel_preset_style != "自定义"):
            # try:
            #     # 备份当前文件（可选）
            #     if os.path.exists(custom_dir):
            #         backup_path = custom_dir + ".bak"
            #         shutil.copy2(custom_dir, backup_path)
                
            #     # 保存新配置
            #     save_config(custom_dir, custom_data)
                
            #     st.toast("配置保存成功！", icon="✅")
            #     st.balloons()
                
            # except Exception as e:
            #     st.error(f"保存失败：{str(e)}", icon="❌")
    with col1:
        if st.button("💾 保存所有修改", width='stretch', disabled=sel_preset_style != "自定义"):
            try:
                # 备份当前文件
                if os.path.exists(custom_dir):
                    backup_path = custom_dir + ".bak"
                    shutil.copy2(custom_dir, backup_path)
                
                # 加载预设配置
                preset_configs = load_config("path/to/default.json")
                default_preset = preset_configs.get("default", {})
                init_preset = preset_configs.get("init", {})
                
                # 获取当前配置（排除 themes）
                current_config = {k: v for k, v in custom_data.items() if k != 'themes'}
                
                # 使用 JSON 序列化对比（自动处理嵌套和顺序）
                current_json = json.dumps(current_config, sort_keys=True)
                default_json = json.dumps(default_preset, sort_keys=True)
                init_json = json.dumps(init_preset, sort_keys=True)
                
                # 对比
                is_same_as_default = current_json == default_json
                is_same_as_init = current_json == init_json
                
                # 根据对比结果设置 themes
                if is_same_as_default:
                    custom_data['themes'] = 'custom_default'
                    st.success("✓ 配置与「chu-gen 默认」完全一致，已标记为 custom_default", icon="✅")
                elif is_same_as_init:
                    custom_data['themes'] = 'custom_init'
                    st.success("✓ 配置与「init_ 模版」完全一致，已标记为 custom_init", icon="✅")
                else:
                    # 可选：显示相似度提示（不额外函数）
                    same_keys = sum(1 for k in set(current_config.keys()) & set(default_preset.keys()) 
                                if current_config.get(k) == default_preset.get(k))
                    total_keys = len(set(current_config.keys()) | set(default_preset.keys()))
                    similarity = (same_keys / total_keys * 100) if total_keys > 0 else 0
                    
                    if custom_data.get('themes') in ['default', 'init', None]:
                        custom_data['themes'] = 'custom_original'
                    st.info(f"🎨 已保存为独立自定义配置（与默认模板相似度 {similarity:.0f}%）", icon="✨")
                
                # 保存新配置
                save_config(custom_dir, custom_data)
                
                st.toast("配置保存成功！", icon="✅")
                st.balloons()
                
            except Exception as e:
                st.error(f"保存失败：{str(e)}", icon="❌")


    with col2:
        if st.button("恢复默认配置", icon="🔄", width='stretch', help="将删除您的 customization.json 文件。"):
            try:
                custom_config_path = os.path.join(custom_dir, "customization.json")
                
                # 如果有备份文件，从备份恢复
                backup_path = custom_config_path + ".bak"
                if os.path.exists(backup_path):
                    shutil.copy2(backup_path, custom_config_path)
                    
                    # 重新加载配置
                    original_data = load_config(current_paths['custom_style'], use_cache=True)
                    
                    custom_data.clear()
                    custom_data.update(original_data[sel_preset_style])
                    
                    st.success("已恢复默认配置！", icon="✅")
                    time.sleep(3)
                    st.rerun()
                else:
                    st.warning("未找到备份文件", icon="⚠️")
                    
            except Exception as e:
                st.error(f"恢复失败：{str(e)}", icon="❌")
                
    with col3:
        if st.button("刷新坐标数据", width='stretch', icon="🔄"):
            try:
                # 1. 清理所有相关的 session_state 键（这些是输入框存储的值）
                keys_to_clear = []
                for key in st.session_state.keys():
                    # 找出所有坐标相关的输入框键
                    if any(x in key for x in ['_x', '_y', 'image.']):
                        keys_to_clear.append(key)
                
                # 删除这些键
                for key in keys_to_clear:
                    del st.session_state[key]
                
                # 2. 重新读取配置文件
                fresh_data = load_config(current_paths['custom_style'])
                
                # 3. 清空并更新 custom_data
                custom_data.clear()
                if fresh_data and 'position' in fresh_data:
                    custom_data.update(fresh_data)
                    st.toast("坐标数据已刷新！", icon="✅")
                else:
                    st.toast("配置文件格式错误", icon="❌")
                
                time.sleep(3)
                # 4. 强制重新渲染页面
                st.rerun()
                
            except Exception as e:
                st.error(f"刷新失败：{str(e)}", icon="❌")
        
    with col4:
        preview_btn = st.button("生成预览图", type="primary", help="⚠️ 修改配置后，需要先保存，再重新生成 Best50 图像才能看到效果", width='stretch', icon="🖼️")

        # test_str = """
        # 啊🤪～啊🤪～啊咦😬啊咦😬啊→啊↑啊↓😨啊😰～嗯💥哎哎🤗哎哦哎嗯😋～哦哎🥳爱爱爱爱爱😍
        # 啊🤪～啊🤪～啊咦😬啊咦😬啊→啊↑啊↓😨啊😰～嗯💥嗯嗯👿滴嘚滴嘚😈唔😱嘟⬅️嘟↖️嘟⬆️嘟↗️嘟➡️嘟↘️嘟⬇️
        # """
    def update_preview_image(placeholder):
        b50_datas = load_config(current_paths['data_file'])
        # generate_single_image(b50_datas[0], custom_data, thumbnails_dir, "BEST", 1)
        generate_single_image(b50_datas[0], custom_data, thumbnails_dir)
        with placeholder:
            st.image(f"{thumbnails_dir}/BEST_1.png")

    if preview_btn:
        preview_image_placeholder = st.expander("预览图", expanded=False)
        update_preview_image(preview_image_placeholder)

        with color:
            # 获取 color 字典
            image_data = custom_data['color']
            st.info("调整字体颜色")
            
            display_names = {
                "title": "曲名",
                "artist": "曲师",
                "bestNum": "Best 序号",
                "playCount": "游玩次数",
                "level": "等级",
                "integer": "等级（整数）",
                "current": "当前等级",
                "next": "下版本等级"
            }
            
            def collect_color_items(data, prefix="", items=None):
                """收集所有颜色项"""
                if items is None:
                    items = []
                
                for key, value in data.items():
                    if isinstance(value, dict):
                        collect_color_items(value, f"{prefix}{key}.", items)
                    elif isinstance(value, list) and len(value) == 3:
                        # 获取显示名称：优先使用映射，否则使用路径的最后一部分
                        display_name = display_names.get(key, key)
                        items.append({
                            'path': prefix + key,
                            # 'display': f"{prefix}{key}".strip('.'),
                            'display': display_name,
                            'color': value
                        })
                return items

            # 使用
            image_data = custom_data['color']

            # 收集所有颜色项
            color_items = collect_color_items(image_data)

            # 使用列布局显示
            if color_items:
                cols_per_row = 7
                for i in range(0, len(color_items), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for j, item in enumerate(color_items[i:i+cols_per_row]):
                        with cols[j]:
                            hex_color = f"#{item['color'][0]:02x}{item['color'][1]:02x}{item['color'][2]:02x}"
                            new_color_hex = st.color_picker(
                                item['display'],
                                hex_color,
                                key=f"color_{item['path'].replace('.', '_')}",
                                disabled=sel_preset_style != "自定义",
                                help="❌️ 仅自定义样式可修改"
                            )
                            
                            if new_color_hex:
                                r = int(new_color_hex[1:3], 16)
                                g = int(new_color_hex[3:5], 16)
                                b = int(new_color_hex[5:7], 16)
                                
                                # 更新原始数据
                                parts = item['path'].split('.')
                                target = image_data
                                for part in parts[:-1]:
                                    target = target[part]
                                target[parts[-1]] = [r, g, b]
                                
        display_names = {
            "title": "曲名",
            "artist": "曲师",
            "bestNum": "Best 序号",
            "playCount": "游玩次数",
            "level": "等级",
            "integer": "等级（整数）",
            "current": "当前版本等级",
            "next": "下版本等级"
        }
        
        with size:
            size_data = custom_data['size']
            render_simple_config(size_data, 'size', display_names, columns_per_row=len(size_data))

        with maxWidth:
            if sel_preset_style == "default" and 'maxWidth' in custom_data:
                width_data = custom_data['maxWidth']
                render_simple_config(width_data, 'maxWidth', display_names, columns_per_row=len(width_data))
            else:
                st.error("init 模版中未使用 maxWidth 配置项", icon="❌️")
        with align:
            align_data = custom_data["align"]
            render_simple_config(align_data, 'align', display_names, columns_per_row=len(align_data))
else:
    st.error("未找到自定义样式文件", icon="❌️")

# 使用说明
st.divider()
st.info("""
**使用说明**:
1. 当前页面显示已应用的视频样式效果
2. 点击"编辑样式配置"可以修改样式设置
3. 使用"刷新预览"更新预览图像
4. 样式更改后需要在视频生成页面重新生成才能生效
""")

# 页面导航
# st.divider()
col_nav1, col_nav2 = st.columns(2)
with col_nav1:
    if st.button("⬅️ 返回首页", width='stretch'):
        st.switch_page("st_pages/0_homepage.py")

with col_nav2:
    if st.button("🎬 继续视频生成", width='stretch'):
        # 根据当前流程决定跳转到哪个页面
        if st.session_state.get('data_updated_step1', False):
            st.switch_page("st_pages/Generate_Pic_Resources.py")
        else:
            st.switch_page("st_pages/1_Setup_Achivments.py")