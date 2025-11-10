import shutil
import time
import streamlit as st
import traceback
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions
from main_gen import generate_complete_video
from gene_video import render_all_video_clips, combine_full_video_direct

st.header("Step 5: 视频渲染")

st.info("渲染视频前，请确保已完成 4-1 和 4-2，并且所有配置无误。", icon="ℹ️")
st.error("渲染时请勿修改任何参数，这可能会导致渲染过程发生意外！", icon="❗")

G_config = read_global_config()
FONT_PATH = "./font/SOURCEHANSANSSC-BOLD.OTF"

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
    st.info("如果要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            selected_save_id = st.selectbox(
                "选择存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y-%m-%d')})"
            )
            if st.button("使用此存档", help="（只需要点击一次！）", use_container_width=True):
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
_video_bitrate = 5000 # TODO：存储到配置文件中
_trans_enable = G_config['VIDEO_TRANS_ENABLE']
_trans_time = G_config['VIDEO_TRANS_TIME']

options = ["仅每个片段", "完整视频"]
with st.container(border=True):
    mode_str = st.radio("渲染模式",
                        options=options,
                        index=_mode_index,
                        horizontal=True,
                        captions=["仅渲染所有片段（包括开头结尾）不拼接", "拼接所有片段（包括开头结尾）并同步渲染"]
                        )
    force_render_clip = st.checkbox("覆盖已存在的视频", value=False, help="强制对所有片段重新渲染，不论其是否存在。")

    st.divider()
    st.write("画面设置")
    st.warning("仅【生成完整视频 / 勾选二次处理】可用，已生成的片段进行拼接不受到影响", icon="⚠️")
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
        preset_bitrate = st.checkbox("使用预设的码率", value=True, help="均为常用值")

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
                st.toast("高码率可使您的视频更清晰，但视频的生成时间可能会变得更长，且输出的文件大小也会变的更大", icon="⚠️")
            v_bitrate = st.number_input(
                "输入自定义码率 (kbps)",
                min_value=1000,
                max_value=10000,
                value=_video_bitrate,
                step=100,
                placeholder="1000 ≤ 码率 ≤ 10000"
            )
            bitrate_display = f"自定义（{v_bitrate}kbps）"  # 自定义码率的显示格式
        
        st.session_state.prev_preset_bitrate = preset_bitrate
        
trans_config_placeholder = st.empty()
# 仅当选择 "完整视频" 时才显示过渡选项
if mode_str == "完整视频":
    with trans_config_placeholder.container(border=True):
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
else:
    # 否则清空占位符（隐藏过渡选项）
    trans_config_placeholder.empty()
    
# with st.container(border=True):
#     st.write("画面设置")
#     col1, col2 = st.columns(2)
#     v_res_width = col1.number_input("宽度(px)", min_value=360, max_value=4096, value=_video_res[0])
#     v_res_height = col2.number_input("高度(px)", min_value=360, max_value=4096, value=_video_res[1])
#     v_bitrate = st.number_input("码率(kbps)", min_value=1000, max_value=10000, value=_video_bitrate)

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

col1, col2 = st.columns(2)
with col1:
    if st.button("开始渲染", help="输出为 60fps 视频", disabled=button_disable_stat):
        save_video_render_config()
        video_res = (v_res_width, v_res_height)
        st.session_state.global_rendering = True
        placeholder = st.empty()
        if v_mode_index == 0:
            try:
                with placeholder.container(border=True, height=560):
                    st.warning("渲染过程中请不要手动跳转到其他页面，或刷新本页面，否则可能导致渲染失败！", icon="⚠️")
                    with st.spinner("正在渲染所有视频片段，请稍候。"):
                        render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps, 
                                            font_path=FONT_PATH, auto_add_transition=False, trans_time=trans_time,
                                            force_render=force_render_clip)
                        st.toast("已启动批量视频片段渲染，请在控制台窗口查看进度。", icon="ℹ️")
                st.success("渲染成功。", icon="✅")
            except Exception as e:
                st.error(f"渲染失败: {traceback.print_exc()}", icon="❌")
            finally:
                st.session_state.global_rendering = False
                st.rerun()

        else:
            try:
                with placeholder.container(border=True, height=560):
                    st.info("渲染完整视频通常需要一定时间，您可以在控制台窗口中查看进度", icon="ℹ️")
                    st.warning("渲染过程中不要手动跳转 / 刷新页面，可能会导致渲染失败！", icon="⚠️")
                    with st.spinner("正在渲染完整视频中"):
                        output_info = generate_complete_video(configs=video_configs, 
                                                        username=username,
                                                        video_output_path=video_output_path, 
                                                        video_res=video_res, 
                                                        video_bitrate=v_bitrate_kbps,
                                                        video_trans_enable=trans_enable, 
                                                        video_trans_time=trans_time, 
                                                        full_last_clip=False)
                        st.write(f"【{output_info['info']}")
                st.success("渲染成功。点击下方按钮打开视频所在文件夹", icon="✅")
            except Exception as e:
                st.error(f"渲染失败: {traceback.print_exc()}", icon="❌")
            finally:
                st.session_state.global_rendering = False
                st.rerun()
with col2:
    abs_path = os.path.abspath(video_output_path)
    if st.button("打开视频输出文件夹", help=abs_path):
        open_file_explorer(abs_path)
        st.toast(f"若没有跳转，请手动访问输出文件夹【鼠标指着“打开”就会显示】", icon="ℹ️")
    # st.write(f"已渲染视频存储在【{abs_path}】")

# if mode_str == "完整视频":
#     st.divider()
#     st.write("其他方案")
#     st.warning("功能未经任何充分测试，我们无法保证输出视频的效果。", icon="⚠️")
#     with st.container(border=True):
#         st.write("【快速模式】先渲染所有视频片段，再拼接为完整视频")
#         st.info("可有效降低渲染内存占用与所需时间，但片段之间将只有黑屏过渡。", icon="ℹ️")
#         st.error("所有片段总大小 ≠ 成品大小（仅相差很大）时，请重新渲染", icon="⚠️")
#         if st.button("开始渲染", help="输出为 60fps 视频", key="请确保所有文件都没问题的情况下再选择此项"):
#             save_video_render_config()
#             video_res = (v_res_width, v_res_height)
#             with st.spinner("正在批量渲染视频片段，请在控制台查看进度。"):
#                 render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps, 
#                                     font_path=FONT_PATH, auto_add_transition=trans_enable, trans_time=trans_time,
#                                     force_render=force_render_clip)
#             with st.spinner("正在拼接视频，请稍候。"):
#                 combine_full_video_direct(video_output_path)
#             st.success("""
#                 ✅ 视频生成完成！  
#                 - 输出位置: `{video_output_path}`  
#                 - 分辨率: {v_res_width} × {v_res_height}  
#                 - 码率: {v_bitrate_kbps}bps
#                 """.format(**locals()))
            # st.success("拼接完成，若报告【`OSError: [WinError 6] 句柄无效。`】可忽略", icon="✅")

if mode_str == "完整视频":
    st.divider()
    st.write("其他方案")
    st.warning("功能未经非常充分的测试，我们无法保证实际输出视频的效果如何。", icon="⚠️")
    
    with st.container(border=True):
        st.write("【快速模式】先渲染所有视频片段，再拼接为完整视频")
        st.info("可有效降低渲染内存占用与所需时间，但片段之间将只有黑屏过渡", icon="ℹ️")
        st.warning("""
        **快速模式生成需要注意的几个情况：**  
        - 尽可能保证所有片段分辨率一致，否则会出现部分片段无法播放的问题。
            - 这是因为片段间分辨率不同导致播放器解码异常导致的
        - 成片大小 ≠ 所有片段总大小（相差很大）时请重新渲染，这是重复拼接导致的。
        - 如果您的机器性能不足，使用快速模式可能也无法降低渲染时间。
        """, icon="⚠️")
        # 初始化状态（使用唯一键避免多组件冲突）
        render_key = f"render_state_{video_output_path}"
        if render_key not in st.session_state:
            st.session_state[render_key] = {
                'is_rendering': False,
                'show_button': True,
                'message': None
            }
        # - 您需要先使用一次【快速模式】渲染所有片段，才能进行二次处理。
        # 状态管理器
        state = st.session_state[render_key]

        # 条件显示按钮或结果
        col1, col2 = st.columns([.65, 1], gap="small", vertical_alignment="center")
        with col1:
            use_over_process = st.checkbox(
                "对拼接视频进行二次处理",
                value=False,
                help="对拼接后视频重新渲染调整其分辨率和码率",
                disabled=not state['is_rendering']
            )
        
        if state['show_button']:
            with col2:
                if st.button("开始渲染", key="render_full_video", use_container_width=True):
                    state.update({
                        'is_rendering': True,
                        'show_button': False,
                        'message': None
                    })
                    st.rerun()

        else:
            if state['is_rendering']:
                # 渲染任务区
                with st.spinner("开始渲染视频，请在控制台窗口查看进度。"):
                    try:
                        # 保存配置
                        save_video_render_config()
                        video_res = (v_res_width, v_res_height)
                        
                        # 阶段1：渲染片段
                        render_all_video_clips(
                            video_configs, 
                            video_output_path,
                            video_res,
                            v_bitrate_kbps,
                            font_path=FONT_PATH,
                            auto_add_transition=trans_enable,
                            trans_time=trans_time,
                            force_render=force_render_clip
                        )
                        
                        # 阶段2：视频拼接
                        combine_full_video_direct(
                            video_output_path,
                            username=username,
                            video_res=video_res,
                            video_bitrate=v_bitrate_kbps,
                            use_overprocess=use_over_process,
                        )
                        
                        # 显示完成信息
                        st.success(f"""
                        视频生成完成！  
                        - 输出路径: `{video_output_path}`  
                        - 分辨率: {res_display}
                        - 码率: {bitrate_display}
                        """, icon="✅")

                        # 
                    except Exception as e:
                        st.error(f"""
                            生成失败：{str(e)}\n请查看控制台获取详细错误报告（如果有）
                        """, icon="❌")
                        raise
                    finally:
                        # 无论执行成功与否，都清理生成缓存文件夹
                        shutil.rmtree('./videos/temp_generated')
                        os.makedirs('./videos/temp_generated')
                        print("[提示] 已清理 FFmpeg 视频生成缓存。")
                        # 5 秒后重新显示按钮
                        time.sleep(5)
                        state['show_button'] = True
                        st.rerun()

            # 显示结果/错误信息
            if state['message']:
                if state['message']['type'] == 'success':
                    st.success(state['message']['content'])
                else:
                    st.error(state['message']['content'])
                    

    with st.container(border=True):
        st.write("【极速模式】使用 Pipe 管线传输所有视频片段给 FFmpeg 渲染，再拼接为完整视频")
        st.info("""
            显著降低渲染时间【2 ~ 3min/片段 → 20 ~ 30s/片段】
            - *仅指快速模式下 MoviePy 二次处理*
                - 也就是有 `MoviePy` 字段开头的部分
            - 平均时间因片段长度而不同，这里仅供参考
                - 如果您的单个片段很长（t ≥ 45s），渲染时间也会变久
        """, icon="ℹ️")
        st.warning("片段之间将只有黑屏过渡，无法选择其他过渡效果应用", icon="⚠️")
        st.error("""
        **极速模式的一些警告和 Bug 修复日志：**  
        - 我们仍在修复视频画面右侧说明文字偏移的问题。
        - 除开头结尾外，仅曲目片段使用了 FFmpeg 渲染
        - 渲染强依赖 CPU 和 GPU 性能，我们建议您使用较好的设备进行渲染
            - 目前仅适配 NVIDIA 显卡的 GPU 加速，AMD 因无设备无法测试
                - ~~（或许后面合并了可以试试看）~~
        """, icon="❌")
        # 初始化状态（使用唯一键避免多组件冲突）
        render_key = f"render_state_{video_output_path}"
        if render_key not in st.session_state:
            st.session_state[render_key] = {
                'is_rendering': False,
                'show_button': True,
                'message': None
            }

        # 状态管理器
        state = st.session_state[render_key]

        # 条件显示按钮或结果
        
        if state['show_button']:
                if st.button("开始渲染", key="render_full_video_ffmpeg", use_container_width=True):
                    state.update({
                        'is_rendering': True,
                        'show_button': False,
                        'message': None
                    })
                    st.rerun()

        else:
            if state['is_rendering']:
                # 渲染任务区
                with st.spinner("开始渲染视频，请在控制台窗口查看进度。"):
                    try:
                        # 保存配置
                        save_video_render_config()
                        video_res = (v_res_width, v_res_height)
                        
                        # 阶段1：渲染片段
                        render_all_video_clips(
                            video_configs, 
                            video_output_path,
                            video_res,
                            v_bitrate_kbps,
                            font_path=FONT_PATH,
                            auto_add_transition=trans_enable,
                            trans_time=trans_time,
                            force_render=force_render_clip
                        )
                        
                        # 阶段2：视频拼接
                        combine_full_video_direct(
                            video_output_path,
                            username=username,
                            video_res=video_res,
                            video_bitrate=v_bitrate_kbps,
                            use_overprocess=use_over_process,
                        )
                        
                        # 显示完成信息
                        st.success(f"""
                        视频生成完成！  
                        - 输出路径: `{video_output_path}`  
                        - 分辨率: {res_display}
                        - 码率: {bitrate_display}
                        """, icon="✅")

                        
                    except Exception as e:
                        st.error(f"""
                            生成失败：{str(e)}
                        """, icon="❌")
                        raise
                    finally:
                        # 无论执行成功与否，都清理生成缓存文件夹
                        shutil.rmtree('./videos/temp_generated')
                        os.makedirs('./videos/temp_generated')
                        # 5 秒后重新显示按钮
                        time.sleep(5)
                        state['show_button'] = True
                        st.rerun()

            # 显示结果/错误信息
            if state['message']:
                if state['message']['type'] == 'success':
                    st.success(state['message']['content'])
                else:
                    st.error(state['message']['content'])
# with st.container(border=True):
#     st.write("【更多过渡效果】使用ffmpeg concat渲染")
#     st.warning("需先安装ffmpeg concat插件，请务必查看使用说明后进行！", icon="⚠️")
#     @st.dialog("ffmpeg-concat使用说明")
#     def delete_video_config_dialog(file):
#         ### 展示markdown文本
#         # read markdown file
#         with open(file, "r", encoding="utf-8") as f:
#             doc = f.read()
#         st.markdown(doc)

#     if st.button("查看使用说明", key=f"open_ffmpeg_concat_doc"):
#         delete_video_config_dialog("./docs/ffmpeg_concat_Guide.md")

#     with st.container(border=True):
#         st.write("片段过渡效果")
#         trans_name = st.selectbox("选择过渡效果", options=["fade", "circleOpen", "crossWarp", "directionalWarp", "directionalWipe", "crossZoom", "dreamy", "squaresWire"], index=0)
#         if st.button("使用ffmpeg concat渲染视频"):
#             save_video_render_config()
#             video_res = (v_res_width, v_res_height)
#             with st.spinner("正在渲染所有视频片段……"):
#                 render_all_video_clips(video_configs, video_output_path, video_res, v_bitrate_kbps, 
#                                        font_path=FONT_PATH, auto_add_transition=False, trans_time=trans_time,
#                                        force_render=force_render_clip)
#                 st.info("已启动批量视频片段渲染，请在控制台窗口查看进度……")
#             with st.spinner("正在拼接视频……"):
#                 combine_full_video_ffmpeg_concat_gl(video_output_path, video_res, trans_name, trans_time)
#                 st.info("已启动视频拼接任务，请在控制台窗口查看进度……")
#             st.success("拼接完成，所有任务已退出，打开文件夹查看渲染结果")
