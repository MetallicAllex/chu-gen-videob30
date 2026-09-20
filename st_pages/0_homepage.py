import streamlit as st
from utils import DataUtils as DU

col1, col2 = st.columns([.7, 1.3])
with col1:
    st.markdown("""
    <style>
    @keyframes scaleIn {
        from {
            opacity: 0;
            transform: scale(0.5);
            transform-origin: top left;
        }
        
        50% {
            transform: scale(1.1);
            transform-origin: top left;
        }
        
        to {
            opacity: 1;
            transform: scale(1);
            transform-origin: top left;
        }
    }

    .stImage {
        animation: scaleIn 3s ease-in-out both;
    }
    </style>
    """, unsafe_allow_html=True)
    st.image("md_res/icon.png", width=400)
    
with col2:
    st.markdown("""
    <style>
    @keyframes spacingAnimation {
        from { margin-top: 0px; letter-spacing: 0px; font-size: 0px; }
        50% { letter-spacing: 20px; }
        to { margin-top: 15px; font-size: 16px; letter-spacing: 14px; }
    }
    
    .rt-text {
        margin-top: 15px;
        font-size: 16px;
        color: gray;
        letter-spacing: 14px;
        animation: spacingAnimation 3s ease-in-out 2.5s both;
    }
    
    @keyframes fadeInDown {
        from {
            opacity: 0;
            transform: translateY(-30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .ruby-container {
        font-size: 24px;
        font-weight: bold;
        text-align: center;
        margin: 15px;
        animation: fadeInDown 1s ease-in-out 3.5s both;
    }
    
    /* 滑入动画 */
    @keyframes slideInLeft {
        from {
            opacity: 0;
            transform: translateX(-50px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }
    
    .version-info {
        text-align: left;
        margin-top: 8px;
        animation: slideInLeft 1s ease-in-out 6s both;
    }
    
    .guide-info {
        text-align: left;
        margin-top: 20px;
        animation: slideInLeft 1s ease-in-out 6.5s both;
        margin-bottom: 15px;
    }
    </style>

    <div style="text-align: center;">
        <div class="rt-text">chu-gen-videob30</div>
        <h2 class="ruby-container">中二节奏 Best30 生成器 v1.2.6</h2>
    </div>
    
    <div style="text-align: left; margin-top: 15px;">
        <div class="guide-info">请按照引导步骤进行操作，以生成您的 Best30 视频。</div>
    </div>
    """, unsafe_allow_html=True)
    st.write("使用过程遇到任何问题，前往 [GitHub 发起 issue](https://github.com/MetallicAllex/chu-gen-videob30/issues) 或 [加入 QQ 群](https://qm.qq.com/q/nFriOm4ZlS) 反馈")
    # st.write(f"当前使用的 FFmpeg 版本为 `{get_ffmpeg_version()}`")
    # st.markdown("请按照下列引导步骤操作，以生成您的 Best30 视频。")

    st.info("""
            在开始使用前，请阅读以下注意事项：（1080p+ 屏幕建议缩放 125% 使用）
            - 缓存数据均保存在本地，如在编辑过程中意外退出，可加载已有存档继续编辑。
            - 使用时请不要随意刷新，这可能会导致索引丢失。
                - 发生此情况时，请重新加载存档并检查数据完整性。""", icon="ℹ️")
# st.success("使用过程中遇到任何问题，前往 [GitHub 发起 issue](https://github.com/MetallicAllex/chu-gen-videob30/issues) 或 [加入 QQ 群](https://qm.qq.com/q/nFriOm4ZlS) 反馈", icon="✅")
# st.error("""
#          【落雪用户】本项目中部分操作会涉及您的查分器 Token，请注意以下四点：
#          - 该密钥对你查分器账号绑定的游戏数据拥有完全访问权限
#          - 该密钥无视查分器账号的隐私设置
#          - 不要分享该密钥给不信任的第三方（本查分器仅用于获取游戏数据）
#          - 如果该密钥被泄露，请及时重新生成密钥
#          """, icon="❗")
# ===== 谱面数据：程序启动时就已经交给后台补齐了，这里只报状态 =====
music_state = DU.music_data_state()


@st.fragment(run_every=1.5)
def watch_music_data():
    if DU.music_data_state()["running"]:
        st.info("正在下载谱面数据（首次约 30s ~ 1min）",
                icon="⏳")
        return
    st.rerun()  # 门槛与侧栏导航都在本片段之外，整页重跑一次才会重算


if music_state["running"]:
    watch_music_data()
elif not music_state["core_ready"]:
    st.error(f"谱面数据未就绪：{music_state['note'] or '本地无曲目数据且后台拉取失败'}。"
             "请确认网络可用后重启程序。", icon="⚠️")

library = DU.music_library_status(music_state["note"])
# 曲库状态压成一行，完整表格收进下方"附加设置"折叠栏 —— 首页正文只回答"能不能开始"
if library["problems"]:
    st.warning("\n".join(f"- {p}" for p in library["problems"]), icon="⚠️")
else:
    st.success(library["brief"], icon="✅")

col1, col2 = st.columns([.45, 1], vertical_alignment="center")
with col1:
    st.write("准备好时，单击右边按钮开始")

with col2:
    if st.button("开始使用", icon="▶️", disabled=not music_state["core_ready"],
                 help="曲库就绪后即可进入" if not music_state["core_ready"] else None,
                 width='stretch'):
        st.switch_page("st_pages/1_Setup_Achivments.py")

st.divider()
with st.expander("（附加设置）更新谱面数据", icon="🔄️"):
    st.markdown(library["table"])
    st.caption("「本地/云端数据版本」：日服/国际服是版本时刻；国服两行是内容哈希短码（与更新日志 [md5] 同源）。")
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        st.caption(f"程序每次启动都会自动比对，超过 {DU.MUSIC_DATA_STALENESS_HOURS // 24} 天尝试重新拉取；")
    with col2:
        if st.button("强制更新谱面数据", icon="🔄️", width='stretch', help="（若谱面数据未自动更新或出现错误时）"):
            DU.start_music_data_update(force=True)
            st.rerun()
