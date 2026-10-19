import streamlit as st
from datetime import datetime
from utils.PathUtils import *
import time, traceback
from utils.ImageUtils import render_all_images
from utils.Variables import ENCODER_BY_CODEC, encoder_choices
from utils.PageUtils import get_ffmpeg_version

from utils.Quadrants.SafeRender import (RENDER_STATUS, submit_render,
                                        cancel_render, gpu_preflight)
from utils.Quadrants.RenderIO import (detect_hw_encoder, probe_hw_encoders,
                                      probe_software_encoders, clear_av1_hw_decode_cache)

# 后端的展示名。'quadrants_cpu' 是实测出来的状态：本机没有可用 GPU 后端时
# （独显休眠/驱动掉线，nvidia-smi 直接 NVML: Not Found）Quadrants 会回退到自己的
# x64 后端——渲染照样成功，但那不是 GPU，界面不能写「Quadrants GPU」。
_BACKEND_LABEL = {'': '尚未开始',
                  'segmentutils': '经典路径（CPU）',
                  'quadrants': 'Quadrants GPU',
                  'quadrants_cpu': 'Quadrants（CPU 后端，本机无可用 GPU 后端）'}


def _backend_label(name: str) -> str:
    return _BACKEND_LABEL.get(name or '', name or _BACKEND_LABEL[''])

st.header("Step 5: 视频渲染")


def quad_status_header():
    """渲染状态 → 浏览器标签页标题。

    RENDER_STATUS 是进程级对象——即使切走窗口导致浮窗消失，回到本页点
    「打开任务浮窗」仍可重新调出模态进度窗；渲染进展看标签页标题即可。

    写标签标题的技术约束：Streamlit 没有动态改标签标题的
    官方 API，且前端 react-helmet 会在每次 delta 提交时把 title 重置回
    set_page_config 的值——所以用 st.components.v1.html 渲染一个同源
    iframe，在其中执行 `window.parent.document.title = ...`（iframe 加载
    晚于 helmet 提交，我们的写入是最后生效的）。

    ⚠️ 本函数**故意不做成 run_every 定时 fragment**：定时片段的自动重跑
    会关闭未被重新调用的 st.dialog（模态必须在每次整页重跑中被重新调用
    才能存活——实测 5s 定时器一触发浮窗就被掐，连带残留标记弹出误导性的
    「渲染任务已结束」）。标签标题的持续刷新由浮窗自身的「每秒整页重跑」
    带动：浮窗打开期间本函数随整页重跑每秒执行一次，标题实时更新；浮窗
    关闭后标题静止，页面上任意交互（如点「打开任务浮窗」）即刷新。
    """
    import streamlit.components.v1 as components

    try:
        s = RENDER_STATUS.snapshot()
    except Exception:
        return

    app_title = "chu-gen-videob30"
    if s['running']:
        # 经典路（CPU 逐段编码）没有逐帧回调，total_frames 恒为 0。以前这里把
        # total_frames 当成必要条件，结果经典路整场只显示"渲染中"——段号明明在走
        # （[2/6]）却不上标题，看起来像没反应。没有帧粒度时按段算就好。
        if s['total_clips']:
            frac = s['clip_idx'] / s['total_clips']
            if s['total_frames']:
                frac = (s['clip_idx'] + s['frame'] / s['total_frames']) / s['total_clips']
            tail = f"（总体 {frac:.0%}）"
            tab_title = f"[{s['clip_idx'] + 1}/{s['total_clips']}] {s['clip_name']}{tail} — {app_title}"
        else:
            tab_title = f"渲染中 — {app_title}"
    else:
        tab_title = app_title

    # 写浏览器标签标题：components iframe 与主页面同源，可通过 window.parent
    # 修改父页 document.title；height=0 完全隐藏。JSON 转义防注入。
    import json as _json
    safe_title = _json.dumps(tab_title, ensure_ascii=False)
    components.html(
        f"<script>window.parent.document.title = {safe_title};</script>",
        height=0,
    )


quad_status_header()

# 渲染进行中：提供「调出任务浮窗」的入口（浮窗可能因切窗口/刷新而消失）
if RENDER_STATUS.running:
    if st.button("🧪 打开渲染任务浮窗", key="quad_open_task",
                 help="重新打开模态进度浮窗，查看实时进度并可在底部取消任务"):
        st.session_state.quad_show_task = True

st.info("渲染视频前，请确保已完成 4-1 和 4-2，并且所有配置无误。", icon="ℹ️")
st.error("请勿在渲染过程中修改任何参数，这可能会导致渲染过程意外中断或素材损坏！", icon="❗")
G_config = read_global_config()

# 渲染跑在常驻工作线程 + 模态进度浮窗（见页尾）：并发防护由 RENDER_STATUS.running
# 与 SafeRender 的进程级互斥锁承担（刷新/换页签均安全）。
# 这里以前读 st.session_state.global_rendering——那个标记是同步渲染时代的产物：
# 脚本线程被渲染占满时根本不会有下一趟重跑来把它复位，页面看着就是"卡死"。
# 现在提交即返回，按钮禁用与否直接看任务状态。
button_disable_stat = RENDER_STATUS.running

### Savefile Management - Start ###
if "username" in st.session_state:
    st.session_state.username = st.session_state.username

if "save_id" in st.session_state:
    st.session_state.save_id = st.session_state.save_id

username = st.session_state.get("username", None)
save_id = st.session_state.get("save_id", None)
# 声明成 dict 而不是 None：这是模块级变量，函数与 @st.fragment 里读到的是它的
# **声明类型**，判空守卫的窄化带不进那些作用域——保持 None 的话每处
# current_paths['x'] 都要再摊一条"None 不可下标"（实测 7 页 37 条）。
# get_data_paths 永远返回非空 dict，所以拿不到存档时它就是下面的空 dict，
# 各页的 `not current_paths` 守卫照样拦得住。
current_paths: dict = {}
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
    if not save_id or not current_paths:
        # current_paths 只在上面 `if save_id:` 分支里赋值。这里把它一起判：
        # "save_id 为真 ⇒ current_paths 已赋值"本来只是两处代码的隐式约定，
        # 静态分析连不上这两个独立变量，于是下面每一处 current_paths['...'] 都判
        # "None 不可下标"（实测页 6 因此摊出 42 条）。写进代码比让人记住更可靠。
        st.stop()
### Savefile Management - End ###

@st.fragment
def video_settings_widget(config, config_file_path):
    """视频参数设置组件"""
    styles = load_config(config_file_path)
    position = styles['position']['video']
    with st.expander("视频画面参数", icon="📺"):
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
os.makedirs(TEMP_GENERATED_DIR, exist_ok=True)
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
        # 这里原来是一个"使用 GPU 硬件加速"复选框：disabled=True 且恒 False，而下面的
        # 【加速方案】又把 disabled 挂在它身上 → 那个下拉框永远点不动，SegmentUtils 里
        # "勾选了就以用户选的品牌为准（同机多卡时自动探测可能挑错）"这条分支根本进不去。
        # 现在两件事合并成下面这一个选择，不再留一个点不动的开关。
        # 这一格原来放那个点不动的复选框；现在改成读一条本机状态（探测结果进程级缓存，
        # 与下方下拉框共用同一份答案），让"为什么只有这几个牌子可选"当场看得见。
        _got = probe_hw_encoders()
        st.caption("本机实探可用硬件编码器：" + (
            "、".join(_n for _c, _n in _got) if _got else "无（自动档将用 CPU 软编）"))

    with col4:
        preset_bitrate = st.checkbox("使用预设的码率", True, help="均为常用值，如自定义可删除填入的数值查看范围")

    # 画面设置代码（分辨率部分优化）
    display_col1, display_col2, display_col3 = st.columns(3, vertical_alignment="center")

    with display_col1:
        # 硬件档只列**实探可用**的品牌（probe_hw_encoders 会真编一帧 nullsrc 验证，驱动
        # 不认的不列出来）：`-encoders` 里有不等于能编，让人点一个必然失败的选项更糟。
        # 软件档同样实探（libx265 不是每个 ffmpeg 构建都带），libx264 是兜底永远保留。
        # 选项与标签→编码器的映射在 utils.Variables.encoder_choices 里，那样才测得到。
        _opts = encoder_choices(probe_hw_encoders(), probe_software_encoders())
        _enc_choice = st.selectbox("编码器方案", [o[0] for o in _opts], 0,
            disabled=button_disable_stat,
            help="两个按钮共用这一个选择（判据只有一份）：选「自动」按本机实探结果编；"
                 "也可以点名【硬件】品牌或【软件】CPU 档（AVC 就是 H.264，HEVC 即 H.265）。"
                 "硬件档只列实探可用的，运行期仍可能编不动；软件档始终在列，随时可改回 CPU 渲染。"
                 "H.265 同画质下体积更小，但纯 CPU 编码明显更慢，老播放器也可能不认；"
                 "真编不动时渲染器会退回 libx264 重试，不会因此丢片段。")
        # selectbox 回的是"选中的那个字符串"，不是下标：写成 _opts[_enc_choice] 会把标签
        # 当索引用（旧引擎直接报 __getitem__ 重载不匹配，新引擎也一样会崩在运行时）。
        # 按标签查回编码器名即可；查不到就是第一项「自动」，None → 交给实探。
        chosen_codec = dict(_opts).get(_enc_choice)
        encoder_param["codec"] = chosen_codec
        encoder_param["brand"] = ((ENCODER_BY_CODEC.get(chosen_codec) or {}).get('brand')
                                  if chosen_codec else None)
        # 这个键的历史含义是「硬件加速」，但 resolve_encoder 用它表示"用户明确点名了
        # 编码器"——软件档也必须为 True，否则点名的 libx264 会被自动探测覆盖。
        encoder_param["hwaccel"] = bool(chosen_codec)

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
            encoder_param["bitrate"] = v_bitrate
            bitrate_display = selected_bitrate  # 直接使用预设的完整字符串
        else:
            st.toast("高码率可使您的视频更清晰，但视频生成时间会变得更长，且输出文件大小也会变的更大", icon="⚠️")
            v_bitrate = st.number_input("输入自定义码率 (kbps)",1000,20000, None, 100,
                help="将添加上限【两倍码率】和缓冲区【四倍码率】，防止因超限导致生成时间变长",
                placeholder="1000 ≤ 码率 ≤ 20000"
            )
            # 两条路线都必须把码率落到 encoder_param：旧写法只在预设分支赋值，
            # 自定义那一路填多少都没进 ffmpeg 命令（-b:v 一直用着默认的 5000k）。
            if v_bitrate:
                encoder_param["bitrate"] = v_bitrate
                bitrate_display = f"自定义（{v_bitrate}kbps）"
            else:
                # 没填就用默认值，但要把"你的输入没生效"说破，别让人以为已经按自定义编码了
                bitrate_display = f"自定义（未填，按默认 {encoder_param['bitrate']}kbps）"
                st.warning(f"自定义码率还没有值，本次按默认 {encoder_param['bitrate']}kbps 编码。",
                           icon="⚠️")

    decode_col1, decode_col2 = st.columns([1, 2], vertical_alignment="center")
    with decode_col1:
        # 解码后端不给选项：能不能硬解由实探决定，用户唯一需要能做的，是清掉
        # 可能过期的探测结果（换了驱动/显卡后重试）。
        if st.button("重新探测", disabled=button_disable_stat,
                     help="清除本进程已缓存的 AV1 硬解探测结果，下次渲染对每条 AV1 源"
                          "重新实探（约 0.2 秒/文件）。"):
            clear_av1_hw_decode_cache()
            st.toast("已清除探测缓存，下次渲染会重新探测", icon="🔍")
    with decode_col2:
        st.caption("AV1 解码后端：自动——本机对该 AV1 流能硬解时用 MSMF，否则 FFMPEG；"
                   "H.264 始终 FFMPEG。")


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
            trans_params["enabled"] = trans_enable
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

# 上一次渲染的失败原因要留在页面上：旧实现弹 10 秒错误后立刻 st.rerun()，
# 状态复位、错误消失，用户只看到"渲染自己停了"，无从判断是失败还是被中断。
if st.session_state.get('render_error'):
    with st.expander("上次渲染失败，点击查看原因", icon="❌", expanded=True):
        st.code(st.session_state.render_error, language='text')
        if st.button("我已读过，清掉这条提示", key="clear_render_error"):
            del st.session_state.render_error


def save_video_render_config():
    # 保存配置
    G_config['ONLY_GENERATE_CLIPS'] = clips_only
    G_config['VIDEO_RES'] = (v_res_width, v_res_height)
    G_config['VIDEO_BITRATE'] = encoder_param['bitrate']
    G_config['VIDEO_TRANS_ENABLE'] = trans_enable
    G_config['VIDEO_TRANS_TIME'] = trans_time
    write_global_config(G_config)
    st.toast("配置已保存！", icon="✅")

if encoder_param.get('codec'):
    # 点名了（硬件品牌或软件档）就按点名的算——背面 resolve_encoder 读的也是同一个值。
    opt_encoder = encoder_param['codec']
else:
    # 「自动」不等于 libx264：SegmentUtils 在没有点名时走 detect_hw_encoder()
    # （本机实测是 h264_nvenc）。旧写法在这里写死 "libx264"，于是按钮 tooltip 和渲染
    # 指纹里的 codec 都是一个**从来没被用过**的编码器——换了显卡或驱动，旧片段仍然
    # 被判"新鲜"继续用。探测结果与渲染侧共用同一份缓存，不会各挑各的。
    opt_encoder, _ = detect_hw_encoder()
encoder_param['codec'] = opt_encoder

_trans_display = ("启用，淡入淡出 %.1f 秒" % float(trans_time or 0)) if trans_enable else "不启用"
st.error(f"""
        **注意事项：**
        - 生成平均时间会因片段长度之间不同码率而变化
            - 如果您单个片段很长，渲染时间也会变久，这是事实
        - 片段之间的过渡：本次{_trans_display}
            - 「开始渲染」把淡变**烘焙进片段两端**（观感像经过一次黑），
              「Quadrants GPU 渲染」改在拼接阶段做 xfade 交叉淡化；两者会互相作废对方渲好的片段
            - 时长可在上方改；过渡**类型**目前固定为淡化(fade)，没有多种转场可选
        - 本次参数：编码器 `{opt_encoder}`（自动档=本机实探结果；也可点名硬件品牌或
          软件 H.264/AVC、H.265/HEVC 档；这就是两个按钮实际会用、也是渲染指纹会记下的
          那一个），分辨率 {res_display}，码率 {bitrate_display}
            - 帧率没有控件：经典路固定 60fps；Quadrants 路在渲染前探测本批全部 main 源，
              取其中**最高**帧率（上限 60fps）。低帧率源按时间基重复帧，时长不变
            - AV1 解码后端：自动探测（仅 Quadrants 路；缓存可点「重新探测」清除；
              H.264 固定走 FFMPEG）
            - H.265/HEVC 在同画质下通常更小，但纯 CPU 编码更慢，部分老播放器/网页预览
              可能不认；上传前请确认目标平台接受 HEVC
            - 编码器（含点名的硬件品牌或软件档）在某台机器上编不动时，渲染器会退回
              libx264 再试一次，片段不会因为选错编码器而丢失；这时清单改记 libx264，
              下次会按软编重渲
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
            # 提交给常驻工作线程，本脚本立即返回：以前这里是在脚本线程里直接跑完整场渲染，
            # 页面冻结到渲染结束——浏览器里既没有进度也点不动任何控件，「取消」无从下手。
            st.session_state.pop('render_error', None)
            st.session_state.render_start_requested = True
            st.rerun()

# ===== 独立的 Quadrants GPU 渲染按钮（实验，不与上面「开始渲染」合并）=====
# 灰化与否交给 gpu_preflight()，不再无条件写死禁用：它看发行包里 quadrants 和它的
# 两个传递依赖在不在、上一次渲染的探针结果，以及那一次**真实跑在哪个后端**（CUDA/Metal/
# Vulkan/AMDGPU 都不可用时 Quadrants 会自己回退 CPU，此时不应再把它当成 GPU 加速）。页面这一侧**绝不做
# GPU 初始化**——
# Quadrants 上下文有线程亲和性，脚本线程探针会把上下文建错线程（实测就是「渲到 4-5 段死亡」的成因）。
_gpu_ok, _gpu_reason = gpu_preflight()
if st.button("Quadrants GPU 渲染（实验）", "quad_render", width='stretch',
             icon="🧪", disabled=not _gpu_ok,
             help=f"""
             走 `utils/Quadrants` 的 Quadrants GPU 合成 + transition-island 低内存拼接。
             - 提交到常驻工作线程执行，刷新/关闭页面不影响渲染
             - 点击后弹出模态进度浮窗（无关闭按钮），浮窗打开期间页面不可交互
             - 若 Quadrants 不可用或渲染失败，会自动回退到 SegmentUtils
             - 渲染后端在常驻工作线程内初始化：qd.gpu（CUDA/Metal/Vulkan/AMDGPU）优先，
               不可用时尝试 Vulkan，最后回退 Quadrants 的 CPU 后端；这与上方【编码器方案】
               无关——选【软件】只换 FFmpeg 编码器，不会关掉 GPU 合成
             - 共用上方参数（分辨率 / 码率 / 过渡 / 覆盖已存在 / 仅渲染片段）
             - 编码器与「开始渲染」用同一个选择（判据只有一份），帧率则由本路跟随谱面源
             - 输出帧率取本批谱面源的最高值（≤60fps，低帧率源按时间基重复帧），
               与经典路的固定 60fps 会互相作废片段缓存
             {"" if _gpu_ok else f"当前不可用：{_gpu_reason}"}
             """):
    st.session_state.quad_start_requested = True
    st.rerun()

if not _gpu_ok:
    st.caption(f"🧪 GPU 渲染暂不可用：{_gpu_reason}")
else:
    st.caption("🧪 Quadrants 后端在渲染线程内自动初始化：qd.gpu（CUDA/Metal/Vulkan/AMDGPU）"
               "→ Vulkan → CPU；"
               "与上方编码器选择无关（软件编码只影响 FFmpeg 码流）。")


# ===== 渲染请求统一交给常驻工作线程 =====
# 旧写法是在这里同步跑 render_all_video_clips + combine：Streamlit 脚本线程被占满，
# 整场渲染期间页面不重跑、不响应任何控件，浏览器里看不到进度，也没有"取消"可言
# （进度只在控制台里，而 start.bat 以外启动的用户常常根本没有控制台）。
# 现在两条路（经典 / Quadrants）都提交到 quad-render-worker，页面只轮询 RENDER_STATUS。
def _prepare_and_submit(prefer: str) -> bool:
    """定格当前页面参数并提交渲染任务；返回是否真的提交成功。"""
    if RENDER_STATUS.running:
        st.warning("已有渲染在进行中，本次请求已忽略（同一应用同时只允许一个渲染任务）。")
        return False
    save_video_render_config()

    # 成绩板 / 底板图像预渲染：放在页面线程里做，带 UI 反馈
    image_root = current_paths['image_dir']
    fullbg_dir = os.path.join(image_root, 'fullbg')
    if not os.path.exists(fullbg_dir):
        print("正在预先渲染背景板图像。")
        render_all_images(video_config_file, current_paths['custom_style'], current_paths)

    return submit_render(
        video_configs=video_configs,
        video_output_path=video_output_path,
        trans_param=trans_params,
        encoder_param=encoder_param,
        style_config=style_config,
        username=username,
        force_render=force_render_clip,
        clips_only=clips_only,
        prefer=prefer,
    )


if st.session_state.pop('render_start_requested', False):
    if _prepare_and_submit('classic'):
        st.toast("渲染已在后台启动，刷新页面不影响任务", icon="🚀")
        st.session_state.quad_show_task = True
    st.rerun()

# 点击渲染按钮：校验并发后提交到常驻工作线程（本脚本线程立即解放）
_start_requested = st.session_state.pop('quad_start_requested', False)
if _start_requested:
    if _prepare_and_submit('quadrants'):
        st.toast("渲染已在后台启动，刷新页面不影响任务", icon="🚀")
        # 提交成功：本轮结束时自动弹出一次任务浮窗（之后可用页首按钮调出）
        st.session_state.quad_show_task = True
    else:
        st.warning("已有渲染在进行中，本次请求已忽略。")


@st.dialog("渲染进度", width="small", dismissible=False)
def quad_progress_dialog():
    """模态进度浮窗：dismissible=False 彻底移除右上角关闭按钮（Esc/点击
    外部也无效），渲染期间整页不可交互，唯一出口是底部的「取消当前任务」。

    两条渲染路径（页 6 的经典路 / Quadrants 实验路）共用这一个浮窗——它们现在
    都跑在同一个常驻工作线程里，状态统一走 RENDER_STATUS。

    进度更新采用 **整页每秒重跑** 模型：每趟渲染一次状态快照，running 时
    sleep(1) 后 st.rerun()（app scope）。之所以不用 fragment 自重跑——
    st.rerun(scope="fragment") 只在 fragment rerun 中合法，而本浮窗是页面
    主脚本（full-app rerun）调用的，第一趟就会抛 StreamlitAPIException，
    这正是此前「看不到取消按钮」的原因。整页重跑的附带好处：按钮点击在
    下一趟开头被处理（on_click → cancel_render），取消延迟 ≤1s；页面很轻
    （配置有缓存），每秒重跑无感。
    """
    s = RENDER_STATUS.snapshot()
    st.caption(f"任务 {s['job_id'][:12] or '…'} · 后端 {_backend_label(s['backend'])} · "
               "渲染在常驻工作线程执行；本浮窗期间页面已锁定，"
               "刷新不会中断渲染，重新进入会自动接续进度。")

    running = RENDER_STATUS.running
    if running:
        # 同上：经典路只有段级进度，total_frames 恒为 0，不能让百分比算式把它当必要条件
        # （实测浮窗整场停在「总体 0.0%」「当前片段 0/0 帧」，像卡住一样）
        overall_pct = s['clip_idx'] / s['total_clips'] if s['total_clips'] else 0.0
        if s['total_clips'] and s['total_frames']:
            overall_pct = (s['clip_idx'] + s['frame'] / s['total_frames']) / s['total_clips']
        clip_pct = (s['frame'] / s['total_frames'] if s['total_frames'] else 0.0)
        st.progress(min(max(overall_pct, 0.0), 1.0),
                    text=f"总体 {overall_pct:.1%} · [{s['clip_idx'] + 1}/{s['total_clips']}] {s['phase']}")
        if s['total_frames']:
            st.progress(min(max(clip_pct, 0.0), 1.0),
                        text=f"当前片段 {clip_pct:.1%} · {s['clip_name']} · "
                             f"{s['frame']}/{s['total_frames']} 帧")
        else:
            # CPU 逐段编码没有逐帧回调：这条不画假进度条，只报在渲哪一段
            st.text(f"当前片段：{s['clip_name']}（CPU 逐段编码，完成一段才推进）")

    # 取消按钮：按用户要求固定在浮窗最下面；on_click 回调在下一趟整页重跑
    # 开头被处理（≤1s），cancel_render 只终止本 job 登记的子进程，不按名称查杀。
    def _cancel_current_job():
        cancel_render(RENDER_STATUS.snapshot()['job_id'])

    if running:
        st.button("取消当前任务", key="quad_cancel", icon="⏹️", type="secondary",
                  width='stretch', on_click=_cancel_current_job,
                  disabled=s['cancel_requested'],
                  help="终止当前渲染任务：仅结束本任务登记的 ffmpeg 子进程，不影响其他程序")
        if s['cancel_requested']:
            st.warning("正在取消：已向当前任务登记的子进程发送终止信号…", icon="⏹️")
        time.sleep(1)
        st.rerun()  # 整页重跑：接续进度 + 处理排队的取消点击（app scope 在此合法）

    # —— 运行结束：终态展示，停留片刻后浮窗自动关闭 ——
    _final = RENDER_STATUS.snapshot()
    if _final['phase'] == '完成':
        _elapsed = max(_final['end_ts'] - _final['start_ts'], 0)
        _mins, _secs = divmod(int(_elapsed), 60)
        st.progress(1.0, text=f"渲染完成（后端 {_backend_label(_final['backend'])}），耗时 {_mins} 分 {_secs} 秒")
        print(f"[Quad] 渲染完成，后端={_final['backend']}，总耗时 {_mins} 分 {_secs} 秒")
        # 秒级「完成」= 没有片段需要渲染（片段文件都已存在且未勾选强制重渲）。
        # 必须明确说明原因：否则浮窗一闪就关，看起来就像状态窗口坏了。
        _note = _final.get('note') or ''
        _nothing = _note.startswith("未渲染任何片段") or _elapsed < 3
        if _nothing:
            st.warning(_note or (f"任务在 {_secs} 秒内结束，没有片段需要渲染。"
                                 "如需重新渲染，请勾选「强制重新渲染」。"), icon="⚠️")
            st.toast("没有片段需要渲染（详见浮窗说明）", icon="⚠️")
        else:
            if _note:
                st.caption(f"片段结果：{_note}")
            st.toast(f"渲染完成（后端 {_backend_label(_final['backend'])}）！", icon="✅")
        time.sleep(6 if _nothing else 2)   # 无片段可渲时多停几秒，让原因能看清
    elif _final['phase'] == '已取消':
        st.warning(f"任务已取消：{_final['error'] or '用户请求取消'}。已渲染的片段保留，"
                   "重新点击渲染会跳过已完成部分续做。", icon="⏹️")
        time.sleep(2)
    elif _final['phase'] == '失败':
        st.error(f"渲染失败：{_final['error'] or '详见控制台'}", icon="❌")
        # 浮窗一关就没了，而失败原因必须留到用户回来看：worker 线程不能直接写
        # st.session_state，所以在这里（页面线程）把快照里的错误转存一份
        if _final['error']:
            st.session_state.render_error = _final['error']
        time.sleep(10)
    # 浮窗对 RENDER_STATUS 只读——running 的生命周期归工作线程，这里绝不复位。
    # 收尾：清掉打开标记再整页重跑，下一趟入口不再调用本浮窗 → 模态关闭。
    # 三分终态展示完落到这里；phase 处于未知中间态（既非 running 也非终态，
    # 如 worker 刚复位的空窗）也在此立即收口，避免模态无出口地卡死。
    st.session_state.quad_show_task = False
    st.rerun()  # 整页重跑：标记已清，浮窗不再被调用（app scope 在此合法）


# 打开任务浮窗的两个入口：① 页首「打开渲染任务浮窗」按钮；② 提交成功后的
# 首次自动弹出。浮窗以模态阻塞到渲染结束/取消；期间状态由页首状态条兜底展示。
# 标记用 get 不用 pop：浮窗内部靠「整页每秒重跑」推进度，而 Streamlit 的模态
# 在整页重跑后只有弹窗函数被再次调用才会保留——一次性 pop 会让浮窗在第一次
# 自刷新（约 1s）后就被关掉，这正是「渲染中浮窗打不开/几秒就消失」的根因
# （1_Setup 的授权浮窗正是靠标记常驻 + 每趟重跑重新调用才存活的）。
# 标记由浮窗自身在终态收尾时清除（见 quad_progress_dialog 尾部）。
# 注意判定条件必须把「终态」也算作要展示：任务可能在浮窗的 sleep(1) 期间就结束
# （实测：片段全部已存在且未勾选强制重渲时，render_all_clips 逐个 continue 跳过，
# 整个任务不到 1 秒就返回 —— 若此处只判 running，下一趟就落进 else 分支把浮窗
# 抢占关掉，用户既看不到「完成」也看不到耗时，表现得就像"状态窗口坏了"）。
_TERMINAL_PHASES = ('完成', '已取消', '失败')
if st.session_state.get('quad_show_task', False):
    if RENDER_STATUS.running or RENDER_STATUS.phase in _TERMINAL_PHASES:
        # running：实时进度；终态：结果展示（浮窗展示完自身清标记并自关闭）
        quad_progress_dialog()
    else:
        # 标记在但任务既不在跑也无终态：上一轮浮窗被意外掐掉（定时片段/断连）
        # 留下的残留标记，静默清理。
        st.session_state.quad_show_task = False