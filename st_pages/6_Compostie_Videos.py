import shutil, time
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from utils.VideoUtils import render_all_video_clips, combine_full_video_direct
from utils.Utils import format_time_difference, get_ffmpeg_version
from utils.Variables import ACCEL_BRAND, ui_font_path, HARD_RENDER_METHOD, XFADE_TRANSITIONS, HARDWARE_ENCODER, SOFTWARE_ENCODER
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
                        st.rerun()
                    else:
                        st.error("存档路径无效！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
            st.stop()
    if not save_id:
        st.stop()
### Savefile Management - End ###

st.write("渲染设置")
_video_res = G_config['VIDEO_RES']
_trans_enable = G_config['VIDEO_TRANS_ENABLE']
_trans_time = G_config['VIDEO_TRANS_TIME']
os.makedirs('./videos/temp_generated', exist_ok=True)
# 定义默认值
trans_enable = _trans_enable
trans_time = _trans_time

with st.container(border=True):
    encoder_param = {"hwaccel": False, "brand": None, "encoder": None, "cq": None, "preset": None} 
    col1, col2, col3 = st.columns(3)
    with col1:
        force_render_clip = st.checkbox("覆盖已存在的视频", value=False, help="强制对所有片段重新渲染，不论其是否存在。")

    with col2:
        clips_only = st.checkbox("仅渲染每个片段", help="只渲染片段，不拼接为完整视频，勾选此项则不会再添加过渡效果。", key='clips_only')

    with col3:
        hwaccel = st.checkbox("使用 GPU 硬件加速", value=False, help="一定程度上可提升渲染速度和分担 CPU 负载，但画质可能会降低")
        encoder_param["hwaccel"] = hwaccel
    
    # hwaccel_col1, hwaccel_col2 = st.columns(2)
    # with hwaccel_col1:
    #     if hwaccel:
    #         accel_brand = st.selectbox("选择您的 GPU 品牌", ACCEL_BRAND, index=0,
    #             help="d3d12va 在 Windows 下为自动选择（可能不准确），其他请根据自己机器 GPU 品牌选择"
    #         )
    #         encoder_param["brand"] = accel_brand if hwaccel else "CPU"
    
    # with hwaccel_col2:
    #     vcoder = st.selectbox(f"编码类型（{'硬编' if hwaccel else '软编'}）", 
    #                         SOFTWARE_ENCODER if not hwaccel else HARDWARE_ENCODER,
    #                         index=0, key="select_encode_type", 
    #                         help="""
    #                         部分编码可能无法使用，如果您不知道怎么选，请保持默认！
    #                         - `lib` 均为软件编码前缀，硬件编码**仅显示对口专用编码器**
    #                             - 不显示非专用图形 API 的编码器（如 `Vulkan` 和 `VAAPI` 等）
    #                         - 硬件编码：`h264 + h265`，出现以下问题时，`请考虑使用软件编码`
    #                             - GPU 编码和软件编码速度并无差别
    #                             - 使用 GPU 加速就提示失败
    #                         """ if hwaccel else """
    #                         部分编码可能无法使用，如果您不知道怎么选，请保持默认！
    #                         - `lib` 均为软件编码前缀，硬件编码**仅显示对口专用编码器**
    #                             - 不显示非专用图形 API 的编码器（如 `Vulkan` 和 `VAAPI` 等）
    #                         - 软件编码：`h264 + h265`
    #                         """)
    #     encoder_param["encoder"] = vcoder
    #     if not hwaccel:
    #         st.warning("为保证视频片段可拼接，任何非 libx264 视频在拼接时将重新编码为 libx264", icon="⚠️")
    
    if hwaccel:
        # 如果启用硬件加速，创建两列
        hwaccel_col1, hwaccel_col2 = st.columns(2)
        
        with hwaccel_col1:
            accel_brand = st.selectbox("设备 GPU 品牌", ACCEL_BRAND, index=0,
                help="d3d12va 在 Windows 下为自动选择（可能不准确），如果有问题请根据机器 GPU 品牌选择"
            )
            encoder_param["brand"] = accel_brand
        
        with hwaccel_col2:
            vcoder = st.selectbox(f"编码类型（硬编）", 
                                HARDWARE_ENCODER,
                                index=0, key="select_encode_type_hw", 
                                help="""
                                部分编码可能无法使用，如果您不知道怎么选，请保持默认！
                                - `lib` 均为软件编码前缀，硬件编码**仅显示对口专用编码器**
                                    - 不显示非专用图形 API 的编码器（如 `Vulkan` 和 `VAAPI` 等）
                                - 硬件编码：`h264 + h265`，出现以下问题时，`请考虑使用软件编码`
                                    - GPU 编码和软件编码速度并无差别
                                    - 使用 GPU 加速就提示失败
                                """)
            encoder_param["encoder"] = vcoder
    else:
        # 如果未启用硬件加速，创建单列并占满宽度
        hwaccel_col2 = st.container()  # 使用 container 代替 column，会自动占满宽度
        
        with hwaccel_col2:
            vcoder = st.selectbox(f"编码类型（软编）", 
                                SOFTWARE_ENCODER,
                                index=0, key="select_encode_type_sw", 
                                help="""
                                部分编码可能无法使用，如果您不知道怎么选，请保持默认！
                                - `lib` 均为软件编码前缀，硬件编码**仅显示对口专用编码器**
                                    - 不显示非专用图形 API 的编码器（如 `Vulkan` 和 `VAAPI` 等）
                                - 软件编码：`h264 + h265`
                                """)
            encoder_param["encoder"] = vcoder
    
    st.divider()
    st.write("画质设置")
    st.info("已生成的片段不会受到影响，除非您重新渲染它们", icon="ℹ️")
    # 画面设置代码（分辨率部分优化）
    row1_col1, row1_col2 = st.columns([1, 3])
    with row1_col1:
        use_preset_res = st.checkbox("使用预设分辨率", value=True, help="均为 16:9")

    with row1_col2:
        if use_preset_res:
            res_presets = {
                "480p (640 × 480)": (640, 480),
                "720p (1280 × 720)": (1280, 720),
                "1080p (1920 × 1080)": (1920, 1080),
                "2K (2560 × 1440)": (2560, 1440),
                "4K (3840 × 2160)": (3840, 2160)
            }
            selected_preset_res = st.selectbox(
                "生成清晰度",
                options=list(res_presets.keys()),
                placeholder="选择一个预设分辨率",
                label_visibility="collapsed",
                index=2
            )
            v_res_width, v_res_height = res_presets[selected_preset_res]
            res_display = selected_preset_res  # 使用完整预设字符串
        else:
            if 'prev_use_preset_res' not in st.session_state or st.session_state.prev_use_preset_res:
                st.toast("不建议使用非预设分辨率生成视频，这可能会导致画面与文字排版错位", icon="⚠️")
            col1, col2 = st.columns(2)
            v_res_width = col1.number_input("宽度 (px)", min_value=360, max_value=4096, value=_video_res[0])
            v_res_height = col2.number_input("高度 (px)", min_value=360, max_value=4096, value=_video_res[1])
            res_display = f"自定义 ({v_res_width} × {v_res_height})"
        
        st.session_state.prev_use_preset_res = use_preset_res

    # 码率设置部分（关键优化）
    bitrate_col1, bitrate_col2 = st.columns([1, 3])
    with bitrate_col1:
        preset_bitrate = st.checkbox("使用预设的码率", value=True, help="均为常用值，如自定义可删除填入的数值查看范围")

    with bitrate_col2:
        if preset_bitrate:
            bitrate_presets = {
                "低（1500kbps）": 1500,
                "标准（2500kbps）": 2500,
                "中等（5000kbps）": 5000,
                "高（6000kbps）": 6000,
                "超高（8000kbps）": 8000,
                "极高（10000kbps）": 10000
            }
            selected_bitrate = st.selectbox(
                "码率（以 kbps 为单位）",
                options=list(bitrate_presets.keys()),
                index=2,
                placeholder="选择一个预设的码率",
                label_visibility="collapsed",
                help="不会影响视频长度，且越大越不容易糊，但文件大小和生成时间也会随之增加"
            )
            v_bitrate = bitrate_presets[selected_bitrate]
            bitrate_display = selected_bitrate  # 直接使用预设的完整字符串
        else:
            if 'prev_preset_bitrate' not in st.session_state or st.session_state.prev_preset_bitrate:
                st.toast("高码率可使您的视频更清晰，但视频生成时间会变得更长，且输出文件大小也会变的更大", icon="⚠️")
            v_bitrate = st.number_input(
                "输入自定义码率 (kbps)",
                help="若使用极速模式将添加上限【两倍码率】和缓冲区【四倍码率】，防止因超限导致生成时间变长",
                min_value=1000,
                max_value=20000,
                value=None,
                step=100,
                placeholder="1000 ≤ 码率 ≤ 20000"
            )
            bitrate_display = f"自定义（{v_bitrate}kbps）"  # 自定义码率的显示格式
        
        st.session_state.prev_preset_bitrate = preset_bitrate
        
# trans_config_placeholder = st.empty()
# 仅当选择 "完整视频" 时才显示过渡选项
    if not clips_only:
        st.divider()
        # with trans_config_placeholder.container(border=True):
        trans_params = {
            'enabled': G_config['VIDEO_TRANS_ENABLE'],
            'duration': G_config['VIDEO_TRANS_TIME'],
            'enable_custom': False,
            'effect': 'fade',  # fade, slide（MoviePy 只有这两种能用）
            'range': 'both',  # start, end, both
            'slide_direction': 'right',  # top, bottom, left, right
        }
        st.write("片段过渡（仅渲染完整视频时有效）")
        col1, col2, col3 = st.columns([1, 2, .15], vertical_alignment="center")
        with col1:
            trans_enable = st.checkbox("启用，过渡时间为：", value=_trans_enable, help="勾选此设置但不自定义过渡效果时，默认使用 fade")
            trans_params["enable"] = trans_enable
        with col2:
            trans_time = st.number_input(
                "过渡时间",
                placeholder="过渡时间(s)",
                min_value=0.5,
                max_value=10.0,
                value=_trans_time,
                step=0.5,
                disabled=not trans_enable,
                label_visibility="collapsed"
            )
            trans_params["duration"] = trans_time
        with col3:
            st.write("秒")
        if trans_enable:
            trans_col1, trans_col2 = st.columns(2)
            with trans_col1:
                use_custom_trans_effect = st.checkbox("使用自定义过渡效果，您当前已选择", help="fade【淡入淡出】，slide【滑入滑出】")
                trans_params["enable_custom"] = use_custom_trans_effect
            with trans_col2:
                sel_custom_trans = st.selectbox("选择自定义过渡",
                                                XFADE_TRANSITIONS if hwaccel == True else ["fade", "slide"],
                                                index=0, placeholder="选择一个效果", label_visibility="collapsed", disabled=not use_custom_trans_effect
                                                )
                trans_params["effect"] = sel_custom_trans
            if sel_custom_trans:
                with st.expander("细节设置", icon="🔧"):
                    trans_range = st.radio("应用范围", ["start", "end", "both"],captions=["开头", "结尾", "开头 + 结尾"] , help="设置渲染过渡效果应用的范围（片段开头[start]/结尾[end]/整个[both]）", horizontal=True, disabled=not use_custom_trans_effect)
                    trans_params["range"] = trans_range
                    if sel_custom_trans == "slide":
                        location = st.selectbox("方向",
                                    ["top", "bottom", "left", "right"],
                                    help="滑入滑出的方向",
                                    disabled=not use_custom_trans_effect
                                    )
                        trans_params["slide_direction"] = location
                    elif sel_custom_trans == "自定义（高级）":
                        st.text_input("输入数学表达式", help="""
可用变量：
- X, Y: 当前像素坐标
- W, H: 视频宽度和高度
- P: 过渡进度 (0.0 - 1.0)
- A: 第一个输入的值
- B: 第二个输入的值
- a0(x, y) - a3(x, y): 第一个输入的像素值
- b0(x, y) - b3(x, y): 第二个输入的像素值"""
                    )

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
    opt_encoder = f"{vcoder}_{HARD_RENDER_METHOD[accel_brand]['codec']}"
else:
    opt_encoder = vcoder
    
abs_path = os.path.abspath(video_output_path)
if st.button("打开视频输出文件夹", help=abs_path, width='stretch', icon="📂"):
    open_file_explorer(abs_path)
    st.toast(f"若没有跳转，请手动访问输出文件夹【鼠标指着“打开”就会显示】", icon="ℹ️")

with st.expander("选择渲染模式", icon="⏩"):
    # 方案选择
    scheme_option = st.radio(
        "选择渲染方案",
        ["标准渲染（时间换稳定性）", "快速渲染（稳定性换时间）"],
        captions=["只使用 CPU 完成渲染，再使用 FFmpeg 拼接", "配合上方 GPU 加速渲染，再使用 FFmpeg 拼接"],
        horizontal=True, disabled=button_disable_stat,
        help="选择不同的视频渲染方案", index=0,
        label_visibility="collapsed"
    )

    # 根据方案显示不同内容
    if scheme_option == "标准渲染（时间换稳定性）":
        # st.write("【快速模式】先渲染所有视频片段，再拼接为完整视频")
        # 快速模式
        st.error(f"""
        **注意事项：**
        - ~无论是哪种选项，片段之间都将只有黑屏过渡，且无法更改~
            - ［开发中］正在尝试编写自定义过渡支持
        - 尽可能保证所有片段分辨率一致，否则会出现部分片段无法播放的问题
        - 成片大小 ≠ 所有片段总大小（相差很大）时请重新渲染，这是重复拼接导致的
        """, icon="❗")

        if st.button("开始渲染", key="render_standard",
                    width='stretch', icon="▶️",
                    disabled=button_disable_stat or (vcoder == "vp9" and accel_brand != "Intel") or hwaccel,
                    help=f"""
                    您的参数（除路径和文件名外，其他参数请于上方调整）：
                    - 输出路径: `{video_output_path}`
                    - 文件名：`{username}_Best50.mp4`
                    - 分辨率和码率: `{res_display} / {bitrate_display}`
                    """ if not hwaccel else 
                    """
                    这些设置不允许您使用此渲染模式：
                    
                    - 使用 GPU 硬件加速（`会导致某些参数异常致使渲染失败`）
                    """):
            st.session_state.global_rendering = True
            st.session_state.current_render_mode = "standard"
            st.rerun()

    # 极速模式
    else:
        st.info("""
            **相较于标准渲染：**
            - 减少 70% 片段渲染时间（理论半小时可出片）
                - 原先的【2 ~ 3min/片段】渲染时间降至【30s ~ 1min/片段】
                - 生成平均时间会因片段长度之间不同分辨率和码率而变化
                    - 如果您单个片段很长，渲染时间也会变久，这是不会改变的事实
            - 设置上限码率【两倍】和缓冲区【四倍】，提升渲染效率
            """, icon="ℹ️")
        st.error(f"""
                **注意事项：**
                - ~无论是哪种选项，片段之间都将只有黑屏过渡，且无法更改~
                    - ［开发者］正在尝试编写自定义过渡支持
                - 此模式生成的叠加层（谱面确认）有概率掉帧
                - 若 GPU （或驱动）太旧而不支持当前 FFmpeg 版本将无法使用硬件加速
                    - 当前 FFmpeg 版本为 `{get_ffmpeg_version()}`
                - 如有以下情况，请立即终止生成并检查素材（或同时反馈问题）：
                    - 某个片段生成时间过长（超过其本身长度或不显示进度）
                    - 生成时（非机器本身性能原因所引起）的异常卡顿和占用
                        - 包括 GPU 占用，生成时 GPU 不会持续高占，它只会跳这么一小会。
                """, icon="⚠️")
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            cq = st.number_input("cq(量化参数)", min_value=0, max_value=63,
                            value=33, step=1, key="cq_range", disabled=button_disable_stat or encoder_param["brand"] == 'AMD',
                            help="""
                            此项会影响编码文件大小和画面质量，如果您不知道怎么调，请保持默认
                            
                            `（使用 AMD 加速的此参数对您无效，您无需调整【自动忽略】）`
                            """)
            encoder_param["cq"] = cq
        with col2:
            preset_options_amf = ['speed' ,'balanced', 'quality']
            default_preset = ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
            preset = st.selectbox("预设编码参数", default_preset if encoder_param["brand"] != 'AMD' else preset_options_amf,
                        index=3 if encoder_param["brand"] != 'AMD' else 1, key="select_preset", help="往上生成越快，往下文件越小（AMD 往下为质量越好）", disabled=button_disable_stat)
            encoder_param["preset"] = preset
        
        if st.button("开始渲染", key="render_fast",
                    width='stretch', icon="▶️",
                    disabled=button_disable_stat or (vcoder == "vp9" and encoder_param["brand"] != "Intel"),
                    help=f"""
                    您的参数（除路径和文件名外，其他参数请于上方调整）：
                    - 输出路径: `{video_output_path}`
                    - 文件名：`{username}_Best50_fast.mp4`
                    - 分辨率、量化参数: `{res_display} / {encoder_param.get("cq")}`
                    - 码率、编码器和编码预设: `{bitrate_display} / {opt_encoder} / {encoder_param.get("preset")}`
                    """):
            st.session_state.global_rendering = True
            st.session_state.current_render_mode = "fast"
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
        if 'current_render_mode' in st.session_state:
            del st.session_state.current_render_mode
        
        # 延迟后刷新
        time.sleep(2)
        st.rerun()

# 统一的渲染控制器
if st.session_state.global_rendering:
    render_mode = st.session_state.get('current_render_mode', 'standard')
    clips_only = st.session_state.get('clips_only', False)
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
        
        # 合并渲染逻辑：只有 classic_fast_render 参数不同
        classic_fast_render = (render_mode == 'standard')
        
        render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps,
                             trans_params, font_path=ui_font_path, encoder_param=encoder_param,
                             force_render=force_render_clip, classic_fast_render=classic_fast_render,
                             clips_only=clips_only)
        
        if not clips_only:
            # 合并视频拼接逻辑：只有 classic_fast_render 参数不同
            combine_full_video_direct(video_output_path, 
                                      username, 
                                      trans_params,
                                      v_bitrate_kbps,
                                      classic_fast_render)
            
        # 渲染成功
        duration = time.time() - start_time  # 用完成的当前时间减去开始时间获取生成时长
        formatted_total_time = format_time_difference(duration)
        print(f"生成操作完成，总耗时{formatted_total_time}")
        st.toast("渲染完成！", icon="✅")
        
    except Exception as e:
        st.error(f"渲染失败（显示 5 秒）: {str(e)}", icon="❌")
        time.sleep(5)
        
    finally:
        # 清理和恢复状态
        cleanup_after_render()