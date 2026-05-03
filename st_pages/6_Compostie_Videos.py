import streamlit as st
from datetime import datetime
from utils.PathUtils import *
import shutil, time, traceback
from utils.ImageUtils import render_all_images
from utils.Variables import ACCEL_BRAND, HARD_RENDER_METHOD
from utils.PageUtils import format_time_difference, get_ffmpeg_version
from utils.Taichi.AccelRenderer2 import render_all_clips_accel2
# from utils.VideoUtils import render_all_video_clips, combine_full_video_direct
from utils.SegmentUtils import render_all_video_clips, combine_full_video_direct

st.header("Step 5: 视频渲染")

st.info("渲染视频前，请确保已完成 4-1 和 4-2，并且所有配置无误。", icon="ℹ️")
st.error("请勿在渲染过程中修改任何参数，这可能会导致渲染过程意外中断或素材损坏！", icon="❗")
G_config = read_global_config()

if 'global_rendering' not in st.session_state:
    st.session_state.global_rendering = False

# 所有按钮共享这个状态
button_disable_stat = st.session_state.global_rendering

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

@st.fragment
def video_settings_widget(config, config_file_path):
    """视频参数设置组件"""
    styles = load_config(config_file_path)
    position = styles['position']['video']
    with st.expander("视频画面参数", expanded=True, icon="📺"):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 背景压暗
            new_darkness = st.number_input(f"背景亮度[当前 {config['darkness'] * 100:.0f} %]", -1.0, 1.0, config["darkness"], 0.01, help="（- 变暗，+ 变亮，0 则不修改）")
            styles["darkness"] = new_darkness
        
        with col2:
            # Overlay
            overlay = position["overlay"]
            new_overlay_x = st.number_input(
                "【谱面确认】X 比例系数",
                0.0, 1.0,
                overlay[0], 0.0001, "%.4f", 
                help=f"在 1080p（图像分辨率）下为 {int(overlay[0] * 1080)}px（取整）"
            )
        
        with col3:
            new_overlay_y = st.number_input(
                "【谱面确认】Y 比例系数", 
                0.0, 1.0,
                overlay[1],
                0.0001,
                "%.4f",
                help=f"在 1080p（图像分辨率）下为 {int(overlay[1] * 1080)}px（取整）"
            )
            position["overlay"] = [new_overlay_x, new_overlay_y]
        
        # 保存按钮
        if st.button("保存视频参数", key="save_video_config", icon="💾", use_container_width=True):
            try:
                save_config(config_file_path, styles)
                st.toast("视频参数已保存！", icon="✅")
                time.sleep(3)
                st.rerun()
            except Exception as e:
                st.toast(f"保存失败：{str(e)}", icon="❌")
                st.error(traceback.format_exc())

st.divider()
style_config = load_config(current_paths['custom_style'])
video_settings_widget(style_config, current_paths['custom_style'])

_video_res = G_config['VIDEO_RES']
_trans_enable = G_config['VIDEO_TRANS_ENABLE']
_trans_time = G_config['VIDEO_TRANS_TIME']
os.makedirs('./videos/temp_generated', exist_ok=True)
# 定义默认值
trans_enable = _trans_enable
trans_time = _trans_time

trans_params = {
    'enabled': G_config['VIDEO_TRANS_ENABLE'],
    'duration': G_config['VIDEO_TRANS_TIME']
}

with st.container(border=True):
    st.write("渲染设置")
    st.info("已生成的片段不会受到影响，除非您重新渲染它们", icon="ℹ️")
    encoder_param = {
        "hwaccel": False,
        "brand": None,
        # "cq": None,
        # "preset": None,
        "bitrate": 5000,
        "resolution": [1920, 1080]
    } 
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        force_render_clip = st.checkbox("覆盖已存在的视频", value=False, help="强制对所有片段重新渲染，不论其是否存在。")

    with col2:
        clips_only = st.checkbox("仅渲染每个片段", help="只渲染片段，不拼接为完整视频。", key='clips_only')

    with col3:
        hwaccel = st.checkbox("使用 GPU 硬件加速", value=False, help="一定程度上可提升渲染速度和分担 CPU 负载，但画质可能会降低")
        encoder_param["hwaccel"] = hwaccel
    
    with col4:
        preset_bitrate = st.checkbox("使用预设的码率", True, help="均为常用值，如自定义可删除填入的数值查看范围")

    # 画面设置代码（分辨率部分优化）
    display_col1, display_col2, display_col3 = st.columns(3, vertical_alignment="center")

    with display_col1:
        accel_brand = st.selectbox("设备 GPU 品牌", ACCEL_BRAND, 0,
            help="d3d12va 为自动选择（可能不准确），如果有问题请根据机器 GPU 品牌选择",
            disabled=button_disable_stat or not hwaccel
        )
        encoder_param["brand"] = accel_brand

    with display_col2:
        res_presets = {
            "480p (640 × 480)": (640, 480),
            "720p (1280 × 720)": (1280, 720),
            "1080p (1920 × 1080)": (1920, 1080),
            "2K (2560 × 1440)": (2560, 1440),
            "4K (3840 × 2160)": (3840, 2160)
        }
        selected_preset_res = st.selectbox("生成清晰度与分辨率", list(res_presets.keys()), 
                                           list(res_presets.values()).index(tuple(_video_res)), 
                                           help="不再支持自定义分辨率，这会导致排版错位")
        v_res_width, v_res_height = res_presets[selected_preset_res]
        encoder_param["resolution"] = res_presets[selected_preset_res]
        res_display = selected_preset_res  # 使用完整预设字符串

    # 码率设置部分（关键优化）
    # bitrate_col1, bitrate_col2 = st.columns([1, 3])
    with display_col3:
        if preset_bitrate:
            bitrate_presets = {
                "低（1500kbps）": 1500,
                "标准（2500kbps）": 2500,
                "中等（5000kbps）": 5000,
                "高（6000kbps）": 6000,
                "超高（8000kbps）": 8000,
                "极高（10000kbps）": 10000
            }
            selected_bitrate = st.selectbox("选择预设值码率 (kbps)", list(bitrate_presets.keys()), 2,
                placeholder="选择一个预设的码率",
                help="不会影响视频长度，且越大越不容易糊，但文件大小和生成时间也会随之增加"
            )
            v_bitrate = bitrate_presets[selected_bitrate]
            encoder_param["bitrate"] = bitrate_presets[selected_bitrate]
            bitrate_display = selected_bitrate  # 直接使用预设的完整字符串
        else:
            st.toast("高码率可使您的视频更清晰，但视频生成时间会变得更长，且输出文件大小也会变的更大", icon="⚠️")
            v_bitrate = st.number_input("输入自定义码率 (kbps)",1000,20000, None, 100,
                help="将添加上限【两倍码率】和缓冲区【四倍码率】，防止因超限导致生成时间变长",
                placeholder="1000 ≤ 码率 ≤ 20000"
            )
            bitrate_display = f"自定义（{v_bitrate}kbps）"  # 自定义码率的显示格式
            

# trans_config_placeholder = st.empty()
# 仅当选择 "完整视频" 时才显示过渡选项
    if not clips_only:
        st.divider()
        trans_params = {
            'enabled': G_config['VIDEO_TRANS_ENABLE'],
            'duration': G_config['VIDEO_TRANS_TIME']
        }
        st.write("片段过渡（仅渲染完整视频时有效）")
        col1, col2, col3 = st.columns([1, 2, .15], vertical_alignment="center")
        with col1:
            trans_enable = st.checkbox("启用，过渡时间为：", value=_trans_enable, help="勾选此设置但不自定义过渡效果时，默认使用 fade")
            trans_params["enable"] = trans_enable
        with col2:
            trans_time = st.number_input("过渡时间", 0.5, 10.0, _trans_time, 0.5,
                placeholder="过渡时间(s)",
                disabled=not trans_enable,
                label_visibility="collapsed"
            )
            trans_params["duration"] = trans_time
        with col3:
            st.write("秒")

v_mode_index = clips_only
v_bitrate_kbps = f"{v_bitrate}"

video_output_path = current_paths['output_video_dir']
if not os.path.exists(video_output_path):
    os.makedirs(video_output_path)

# 读取存档的video config文件
video_config_file = current_paths['video_config']
if not os.path.exists(video_config_file):
    st.error(f"未找到视频内容配置文件 {video_config_file} ，请检查前置步骤是否完成，以及b30存档的数据完整性！")
    st.stop()
video_configs = load_config(video_config_file)

def save_video_render_config():
    # 保存配置
    G_config['ONLY_GENERATE_CLIPS'] = clips_only
    G_config['VIDEO_RES'] = (v_res_width, v_res_height)
    G_config['VIDEO_BITRATE'] = v_bitrate or selected_bitrate
    G_config['VIDEO_TRANS_ENABLE'] = trans_enable
    G_config['VIDEO_TRANS_TIME'] = trans_time
    write_global_config(G_config)
    st.toast("配置已保存！", icon="✅")

if hwaccel:
    opt_encoder = f"h264_{HARD_RENDER_METHOD[accel_brand]['codec']}"
    encoder_param['codec'] = opt_encoder
else:
    opt_encoder = "libx264"
    encoder_param['codec'] = opt_encoder

st.error(f"""
        **注意事项：**
        - 生成平均时间会因片段长度之间不同码率而变化
            - 如果您单个片段很长，渲染时间也会变久，这是事实
        - 片段之间只有黑屏过渡，且无法更改
            - ［开发者］正在尝试编写自定义过渡支持
        - 若 GPU （或驱动）太旧而不支持当前 FFmpeg 版本将无法使用硬件加速
            - 当前 FFmpeg 版本为 `{get_ffmpeg_version()}`
        - 如有以下情况，请立即终止生成并检查素材（或同时反馈问题）：
            - 某个片段生成时间过长（超过其本身长度或不显示进度）
            - 生成时（非机器本身性能原因所引起）的异常卡顿和占用
                - 包括 GPU 占用，生成时 GPU 不会持续高占，它只会跳这么一小会。
        """, icon="❗")
btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    abs_path = os.path.abspath(video_output_path)
    if st.button("打开视频输出文件夹", help=abs_path, width='stretch', icon="📂"):
        open_file_explorer(abs_path)
        st.toast(f"若没有跳转，请手动访问输出文件夹【鼠标指着“打开”就会显示】", icon="ℹ️")

    with btn_col2:
        if st.button("开始渲染", "render", width='stretch', icon="▶️", disabled=button_disable_stat,
                    help=f"""
                    您的参数（除路径和文件名外，其他参数请于上方调整）：
                    - 输出路径: `{video_output_path}`
                    - 文件名和编码器：`{username}_Best50.mp4（{opt_encoder}）`
                    - 分辨率、码率: `{res_display} / {bitrate_display}`
                    """):
            st.session_state.global_rendering = True
            # st.session_state.current_render_mode = "fast"
            st.rerun()

    def cleanup_after_render():
        """清理渲染后的临时文件和状态"""
        try:
            shutil.rmtree('./videos/temp_generated')
            os.makedirs('./videos/temp_generated', exist_ok=True)
        except:
            pass
            
        # 恢复状态
        st.session_state.global_rendering = False
        # if 'current_render_mode' in st.session_state:
        #     del st.session_state.current_render_mode
        
        # 延迟后刷新
        time.sleep(2)
        st.rerun()

# 统一的渲染控制器
if st.session_state.global_rendering:
    # render_mode = st.session_state.get('current_render_mode', 'standard')
    # clips_only = st.session_state.get('clips_only', False)
    start_time = time.time()  # 记录开始时间
    print("开始记录生成时间。")
    st.info("""
            渲染进行中，请在控制台窗口查看详细进度。
            - 不要刷新页面或进行任何操作，这可能会导致进度提前终止。
            """, icon="ℹ️")
    
    try:
        start_time = time.time()
        save_video_render_config()
        video_res = (v_res_width, v_res_height)

        image_root = current_paths['image_dir']
        fullbg_dir = os.path.join(image_root, 'fullbg')
        if not os.path.exists(fullbg_dir):
            print("正在预先渲染背景板图像。")
            render_all_images(video_config_file, current_paths['custom_style'], current_paths)
        
        # 合并渲染逻辑：只有 classic_fast_render 参数不同
        # classic_fast_render = (render_mode == 'standard')

        # render_all_video_clips(video_configs, 
        #                        video_output_path, 
        #                        video_res, 
        #                        v_bitrate_kbps,
        #                       trans_params,
        #                       encoder_param, 
        #                       force_render_clip, 
        #                       classic_fast_render)
        
        # render_all_video_clips(video_configs,
        #                        video_output_path,
        #                        trans_params,
        #                        encoder_param,
        #                        style_config,
        #                        force_render_clip)
        
        # if not clips_only:
        #     # 合并视频拼接逻辑：只有 classic_fast_render 参数不同
        #     combine_full_video_direct(video_output_path, username)
        
        # 定义进度回调函数
        # def progress_callback(clip_index, total_clips, frame, total_frames, clip_name):
        #     """进度回调
        #     Args:
        #         clip_index: 当前是第几个片段（从0开始）
        #         total_clips: 总片段数
        #         frame: 当前帧（从1开始）
        #         total_frames: 当前片段总帧数
        #         clip_name: 片段名称
        #     """
        #     clip_progress = frame / total_frames * 100
        #     # overall_progress = (clip_index + frame / total_frames) / total_clips * 100
        #     print(f"正在渲染 ID 为 {clip_name} 的第 {clip_index} 个片段：当前已完成 {clip_progress:.0f} %（{frame}/{total_frames} 帧）")
        
        # # 在调用前初始化 GPU（放在 try 块开始处，第 241 行附近）
        # # init_taichi()  # 自动选择最佳 GPU 后端

        # render_all_clips_accel2(
        #     video_configs,
        #     video_output_path,
        #     encoder_param,
        #     trans_params,
        #     style_config,
        #     force_render_clip,
        #     progress_callback
        # )
        
        render_all_video_clips(
            video_configs,           # 视频配置数据
            video_output_path,     # 最终片段存储目录（如 './videos/clips'）
            trans_params,         # 过渡参数 {'enabled': True, 'duration': 1}
            encoder_param,       # 编码参数 {'resolution': (1920,1080), 'bitrate': 5000, ...}
            style_config,        # 样式配置 {'darkness': 0.3, 'position': {...}}
            force_render_clip   # 是否强制重新渲染
        )
        
        if not clips_only:
            combine_full_video_direct(video_output_path, username)
        
        # 渲染成功
        duration = time.time() - start_time  # 用完成的当前时间减去开始时间获取生成时长
        formatted_total_time = format_time_difference(duration)
        print(f"生成操作完成，总耗时{formatted_total_time}")
        st.toast("渲染完成！", icon="✅")
        
    except Exception as e:
        st.error(f"渲染失败（显示 10 秒）: {str(e)}", icon="❌")
        time.sleep(10)
        
    finally:
        # 清理和恢复状态
        cleanup_after_render()