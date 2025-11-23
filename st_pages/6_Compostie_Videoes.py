import shutil, time
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from utils.VideoUtils import render_all_video_clips, combine_full_video_direct, generate_complete_video
from utils.Utils import format_time_difference, get_ffmpeg_version
from utils.Variables import ui_font_path, HARD_RENDER_METHOD

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
            with st.container(border=True):
                selected_save_id = st.selectbox(
                    "选择存档",
                    versions,
                    # label_visibility="collapsed",
                    format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
                )
                if st.button("使用此存档", help="（只需要点击一次！）", use_container_width=True, icon="▶️"):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        st.rerun()
                    else:
                        st.error("存档路径无效！")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！")
            st.stop()
    if not save_id:
        st.stop()
### Savefile Management - End ###

st.write("基础设置")

_mode_index = 0 if G_config['ONLY_GENERATE_CLIPS'] else 1
_video_res = G_config['VIDEO_RES']
_trans_enable = G_config['VIDEO_TRANS_ENABLE']
_trans_time = G_config['VIDEO_TRANS_TIME']
os.makedirs('./videos/temp_generated', exist_ok=True)

options = ["仅每个片段", "完整视频"]
with st.container(border=True):
    mode_str = st.radio("渲染模式",
                        options=options,
                        index=_mode_index,
                        horizontal=True,
                        captions=["仅渲染所有片段（包括开头结尾）不拼接", "拼接所有片段（包括开头结尾）并同步渲染"]
                        )
    
    col1, col2 = st.columns([.75, 1.25])
    use_hardware_acceleration = False
    acceleration_method = "libx264"
    with col1:
        force_render_clip = st.checkbox("覆盖已存在的视频", value=False, help="强制对所有片段重新渲染，不论其是否存在。")

    with col2:
        use_hardware_acceleration = st.checkbox("使用 GPU 硬件加速(GPU Hardware Acceleration)", value=False, help="一定程度上可提升渲染速度和分担 CPU 负载，但画质可能会降低")
    
    if use_hardware_acceleration:
        acceleration_method = st.radio("选择您的加速方案", ["NVIDIA", "AMD", "Intel"],
            captions=["CUDA + NVENCoder(NVENC)", "Advanced Media Framework(含集显)", "Quick Sync Video(含集显)"],
            horizontal=True, index=0, label_visibility="collapsed"
        )
    
    encoder_param = {"encoder": None, "cq_set": None, "preset_type": None} 
    hardware_encoder = ["h264", "hevc", "av1", "vp9"]
    software_encoder = ["libx264", "libx265", "libaom-av1", "libsvtav1", "librav1e", "libvpx", "libvpx-vp9"]
    encoder = st.selectbox(f"编码类型（{'硬编' if use_hardware_acceleration else '软编'}）", 
                        software_encoder if not use_hardware_acceleration else hardware_encoder,
                        index=0, key="select_encode_type_fast", 
                        help="""
                        部分编码可能无法使用，如果您不知道哪个能用，请保持默认
                        - `lib` 均为软件编码前缀，硬件编码**仅显示对口专用编码器**
                            - 不显示非专用图形 API 的编码器（如 `Vulkan 和 VAAPI` 等）
                        - 软件编码：`h264 + h265 + av1(三种) + vp9(两种)`
                            - 太旧的 CPU 有可能无法支持新编码
                            - 不建议使用`除 h264 / 265 之外`的任何编码
                                - 这可能会导致渲染进程非常缓慢！
                        - 硬件编码：`h264 + h265 + av1 + vp9(仅 Intel 支持)`
                            - 已知 `av1` 仅在 40 系及以上 N 卡支持，A 卡信息不详
                        """)
    encoder_param["encoder"] = encoder
    if encoder == "vp9" and acceleration_method != "Intel":
        st.error(f"{encoder.upper()} 编码器不支持 {acceleration_method} 硬件加速，您无法使用此加速方案。", icon="❌")
    elif encoder == "vp9":
        st.warning(f"{encoder.upper()} 编码器仅支持生成片段，无法对其添加过渡，将重新编码为 h264_{HARD_RENDER_METHOD[acceleration_method]['codec']}。", icon="⚠️")
    elif not use_hardware_acceleration:
        st.warning("为保证视频片段可拼接，任何非 libx264 视频在拼接时将重新编码为 libx264", icon="⚠️")
    
    st.divider()
    st.write("画面设置（仅【生成完整视频】可用，已生成片段不受到影响）")
    # st.warning("仅【生成完整视频】可用，已生成的片段进行拼接不受到影响", icon="⚠️")
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
    if mode_str == "完整视频":
        st.divider()
        # with trans_config_placeholder.container(border=True):
        st.write("片段过渡（仅渲染完整视频时有效）")
        col1, col2 = st.columns([1, 2])
        with col1:    
            trans_enable = st.checkbox("启用，过渡时间为（秒）：", value=_trans_enable)
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

v_mode_index = options.index(mode_str)
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
    G_config['ONLY_GENERATE_CLIPS'] = v_mode_index == 0
    G_config['VIDEO_RES'] = (v_res_width, v_res_height)
    G_config['VIDEO_BITRATE'] = v_bitrate or selected_bitrate
    G_config['VIDEO_TRANS_ENABLE'] = trans_enable
    G_config['VIDEO_TRANS_TIME'] = trans_time
    write_global_config(G_config)
    st.toast("配置已保存！", icon="✅")

if use_hardware_acceleration:
    opt_encoder = f"{encoder}_{HARD_RENDER_METHOD[acceleration_method]['codec']}"
else:
    opt_encoder = encoder
col1, col2 = st.columns(2)
with col1:
    if st.button("开始渲染", help=f"""
                        您的参数（除路径和文件名外，其他参数请于上方调整）：
                        - 输出路径: `{video_output_path}`
                        - 文件名：`{username}_Best50.mp4`
                        - 分辨率: `{res_display}`
                        - 码率和编码器: `{bitrate_display} / {opt_encoder}`
                        
                        因依赖库特性，此渲染无法提升性能，请考虑使用【快速/极速】生成模式
                        """,
                 disabled=button_disable_stat or (encoder == "vp9" and acceleration_method != "Intel"),
                 use_container_width=True, icon="▶️"):
        save_video_render_config()
        video_res = (v_res_width, v_res_height)
        st.session_state.global_rendering = True
        st.session_state.current_render_mode = "main"  # 添加这行
        st.rerun()  # 只设置状态，不执行渲染
with col2:
    abs_path = os.path.abspath(video_output_path)
    if st.button("打开视频输出文件夹", help=abs_path, use_container_width=True, icon="📂"):
        open_file_explorer(abs_path)
        st.toast(f"若没有跳转，请手动访问输出文件夹【鼠标指着“打开”就会显示】", icon="ℹ️")
    # st.write(f"已渲染视频存储在【{abs_path}】")

if mode_str == "完整视频":
    st.divider()
    st.write("其他方案")
    # st.warning("功能未经非常充分的测试，我们无法保证实际输出视频的效果，请酌情选择。", icon="⚠️")
    
    with st.container(border=True):
        # 方案选择
        scheme_option = st.radio(
            "选择渲染方案",
            ["快速模式（时间换稳定性）", "极速模式（稳定性换时间）"],
            captions=["只使用 MoviePy 渲染，再使用 FFmpeg 拼接", " FFmpeg + MoviePy 混合渲染，再使用 FFmpeg 拼接"],
            horizontal=True,
            help="选择不同的视频渲染方案",
            label_visibility="collapsed"
        )

        # 根据方案显示不同内容
        if scheme_option == "快速模式（时间换稳定性）":
            # st.write("【快速模式】先渲染所有视频片段，再拼接为完整视频")
            # 快速模式
            st.info("""
                    **相较于完整渲染：**  
                    - 有效降低渲染时内存占用，减少渲染所需时间
                    - 全部片段分离，可单独提取用于二次制作
                    - 不会因机器断电等问题，丢失已生成进度
                        - 如果已有文件占位符，需手动检查后删除
                    """, icon="ℹ️")
            st.warning("""
            **注意事项：**
            - 无论是哪种选项，片段之间都将只有黑屏过渡，且无法更改
                - 【实验性】考虑使用 FFmpeg 的 chromakey 做绿幕抠像过渡
            - 尽可能保证所有片段分辨率一致，否则会出现部分片段无法播放的问题
            - 成片大小 ≠ 所有片段总大小（相差很大）时请重新渲染，这是重复拼接导致的
            - 如果您的机器性能不足，使用快速模式可能也无法降低渲染时间
            """, icon="⚠️")

            if st.button("开始渲染", key="render_fast_mode",
                        use_container_width=True, icon="▶️",
                        disabled=button_disable_stat or (encoder == "vp9" and acceleration_method != "Intel"),
                        help=f"""
                        您的参数（除路径和文件名外，其他参数请于上方调整）：
                        - 输出路径: `{video_output_path}`
                        - 文件名：`{username}_Best50_fast.mp4`
                        - 分辨率: `{res_display}`
                        - 码率和编码器: `{bitrate_display} / {opt_encoder}`
                        """):
                st.session_state.global_rendering = True
                st.session_state.current_render_mode = "fast"
                st.rerun()

        # 极速模式
        else:
            st.info("""
                **相较于快速模式：**
                - 减少 70% 片段渲染时间【2 ~ 3min/片段 → 30s ~ 1min/片段】
                    - 和完整渲染相比，极速模式渲染时间减少 80%（已在 3060 笔本测试）
                    - 将 `MoviePy` 谱面确认主体 *（不含头尾）* 分离处理
                    - 生成平均时间会因片段长度之间不同分辨率和码率而变化
                        - 如果您单个片段很长，渲染时间也会变久，这是不会改变的事实
                - 设置上限码率【两倍】和缓冲区【四倍】，提升渲染效率
                """, icon="ℹ️")
            st.warning(f"""
                    **注意事项：**
                    - 无论是哪种选项，片段之间都将只有黑屏过渡，且无法更改
                        - 【实验性】考虑使用 `FFmpeg `的` chromakey` 做绿幕抠像过渡
                    - 此模式生成的叠加层（谱面确认）有概率掉帧
                    - 若 GPU （或驱动）太旧而不支持当前 FFmpeg 版本将无法使用此模式
                        - 当前 FFmpeg 版本 = `{get_ffmpeg_version()}`
                        - 生成器会自动降为快速模式继续为您生成
                    """, icon="⚠️")
            st.error("""
            **一些警告和 Bug 修复日志：**  
            - 如果您发现有以下情况，请立即终止生成并检查素材（或反馈问题）：
                - 某个片段生成时间过长（超过其本身长度或不显示进度）
                - 生成时（由非机器本身性能原因所引起的）异常卡顿
                    - 包括 GPU 占用，生成时 GPU 不会持续高占，它只会跳这么一小会。
            - 渲染依赖 CPU 和 GPU 性能（主要为 GPU），建议您使用较好的设备进行
                - 已适配 NVIDIA CUDA + NVENC、Intel QSV，AMD 的 AMF 需要测试
            """, icon="❌")
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                cq_set = st.number_input("cq(量化参数)值", min_value=0, max_value=63,
                                value=33, step=1, key="cq_range",
                                help="此项会影响编码文件大小和画面质量")
                encoder_param["cq_set"] = cq_set
            with col2:
                preset_type = st.selectbox("预设编码参数", ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"],
                            index=3, key="select_preset", help="往上生成越快，往下文件越小"
                            )
                encoder_param["preset_type"] = preset_type
            
            if st.button("开始渲染", key="render_ffmpeg_mode",
                        use_container_width=True, icon="▶️",
                        disabled=button_disable_stat or (encoder == "vp9" and acceleration_method != "Intel"),
                        help=f"""
                        您的参数（除路径和文件名外，其他参数请于上方调整）：
                        - 输出路径: `{video_output_path}`
                        - 文件名：`{username}_Best50_ffmpeg.mp4`
                        - 分辨率、量化参数: `{res_display} / {encoder_param.get("cq_set")}`
                        - 码率、编码器和编码预设: `{bitrate_display} / {opt_encoder} / {encoder_param.get("preset_type")}`
                        """):
                st.session_state.global_rendering = True
                st.session_state.current_render_mode = "ffmpeg"
                st.rerun()

# 统一的渲染控制器
if st.session_state.global_rendering:
    render_mode = st.session_state.get('current_render_mode', 'main')
    start_time = time.time()  # 记录开始时间
    print("开始记录生成时间。")
    st.warning("渲染进行中，所有渲染操作已被禁用。", icon="🚫")
    st.info("请在控制台窗口查看详细进度，不要刷新页面或进行其他任何操作", icon="ℹ️")
    
    try:
        if render_mode == 'main':
            # 主要渲染逻辑
            video_res = (v_res_width, v_res_height)
            if v_mode_index == 0:
                render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps, 
                                    font_path=ui_font_path, auto_add_transition=False,
                                    trans_time=trans_time, force_render=force_render_clip,
                                    use_hardware_acceleration=use_hardware_acceleration,
                                    acceleration_method=acceleration_method)
            else:
                generate_complete_video(configs=video_configs, username=username,
                                      video_output_path=video_output_path, video_res=video_res,
                                      video_bitrate=v_bitrate_kbps, video_trans_enable=trans_enable,
                                      video_trans_time=trans_time, full_last_clip=False,
                                      use_hardware_acceleration=use_hardware_acceleration,
                                      acceleration_method=acceleration_method, encoder_param=encoder_param)
                
        elif render_mode == 'fast':
            # 快速模式渲染逻辑
            start_time = time.time()
            save_video_render_config()
            video_res = (v_res_width, v_res_height)
            
            render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps,
                                 font_path=ui_font_path, encoder_param=encoder_param,
                                 auto_add_transition=trans_enable, trans_time=trans_time,
                                 force_render=force_render_clip, classic_fast_render=True,
                                 use_hardware_acceleration=use_hardware_acceleration,
                                 acceleration_method=acceleration_method)
            
            combine_full_video_direct(video_output_path, username=username, classic_fast_render=True)
            
        elif render_mode == 'ffmpeg':
            # 极速模式渲染逻辑  
            start_time = time.time()
            save_video_render_config()
            video_res = (v_res_width, v_res_height)
            
            render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps,
                                 font_path=ui_font_path, encoder_param=encoder_param,
                                 auto_add_transition=trans_enable, trans_time=trans_time,
                                 force_render=force_render_clip, classic_fast_render=False,
                                 use_hardware_acceleration=use_hardware_acceleration,
                                 acceleration_method=acceleration_method)
            
            combine_full_video_direct(video_output_path, username=username)
            
        # 渲染成功
        duration = time.time() - start_time  # 用完成的当前时间减去开始时间获取生成时长
        formatted_total_time = format_time_difference(duration)
        print(f"生成操作完成，总耗时{formatted_total_time}")
        st.success("渲染完成！", icon="✅")
        
    except Exception as e:
        st.error(f"渲染失败: {str(e)}", icon="❌")
        
    finally:
        # 清理和恢复状态
        try:
            shutil.rmtree('./videos/temp_generated')
            os.makedirs('./videos/temp_generated', exist_ok=True)
        except:
            pass
            
        # 恢复所有按钮
        st.session_state.global_rendering = False
        if 'current_render_mode' in st.session_state:
            del st.session_state.current_render_mode
            
        # 延迟后刷新
        time.sleep(2)
        st.rerun()