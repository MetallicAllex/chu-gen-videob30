import streamlit as st
from update_music_data import fetch_music_data
# from utils.PageUtils import change_theme
# from utils.themes import THEME_COLORS

col1, col2 = st.columns([.65, 1.35])
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
        animation: scaleIn 2s ease-in-out both;
    }
    </style>
    """, unsafe_allow_html=True)
    st.image("md_res/icon.png", width=256)
    
with col2:
    st.markdown("""
    <style>
    @keyframes spacingAnimation {
        from { margin-top: 0px; letter-spacing: 0px; font-size: 0px; }
        50% { letter-spacing: 20px; }
        to { margin-top: 20px; font-size: 16px; letter-spacing: 14px; }
    }
    
    .rt-text {
        margin-top: 20px;
        font-size: 16px;
        color: gray;
        letter-spacing: 14px;
        animation: spacingAnimation 3s ease-in-out 3s both;
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
        animation: fadeInDown 1s ease-in-out 4.5s both;
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
        margin-top: 15px;
        animation: slideInLeft 1s ease-in-out 6s both;
    }
    
    .guide-info {
        text-align: left;
        margin-top: 25px;
        animation: slideInLeft 1s ease-in-out 6.5s both;
    }
    </style>

    <div style="text-align: center;">
        <div class="rt-text">chu-gen-videob30</div>
        <h2 class="ruby-container">中二节奏 Best30 分表生成器</h2>
    </div>
    
    <div style="text-align: left; margin-top: 15px;">
        <div class="version-info">版本：<span style="font-weight: bold;">[基于 mai-gen-videob30 修改的] v0.4-2026modified-pre1</span></div>
        <div class="guide-info">请按照下列引导步骤操作，以生成您的 Best30 视频。</div>
    </div>
    """, unsafe_allow_html=True)
    # st.write("当前版本：[基于 mai-gen-videob30 修改的] v0.4-2026modified-pre1")
    # st.markdown("请按照下列引导步骤操作，以生成您的 Best30 视频。")

st.info("""
        - 缓存数据均保存在本地，如在编辑过程中意外退出，可加载已有存档继续编辑。
        - 使用时请不要随意刷新，这可能会导致索引丢失。
            - 发生此情况时，请重新加载存档并检查数据完整性。""", icon="ℹ️")
st.success("使用过程中遇到任何问题，前往 [GitHub 发起 issue](https://github.com/MetallicAllex/chu-gen-videob30/issues) 或 [加入 QQ 群](https://qm.qq.com/q/nFriOm4ZlS) 反馈", icon="✅")
st.error("""
         【落雪用户】本项目中部分操作会涉及您的查分器 Token，请注意以下四点：
         - 该密钥对你查分器账号绑定的游戏数据拥有完全访问权限
         - 该密钥无视查分器账号的隐私设置
         - 不要分享该密钥给不信任的第三方（本查分器仅用于获取游戏数据）
         - 如果该密钥被泄露，请及时重新生成密钥
         """, icon="❗")
st.write("当你准备好时，单击下面的按钮开始")

col1, col2 = st.columns(2)

with col1:
    if st.button("开始使用", icon="▶️", use_container_width=True):
        st.switch_page("st_pages/1_Setup_Achivments.py")

with col2:
    if st.button("更新乐曲数据", help="如果你认为曲目数据不正确或已经修改，点击此按钮更新", icon="🔄️", use_container_width=True):
        fetch_music_data()

# st.write("外观选项")
# with st.container(border=True):
#     if 'theme' not in st.session_state:
#         st.session_state.theme = "Default"
#     @st.dialog("刷新主题")
#     def refresh_theme():
#         st.info("主题已更改，要刷新并应用主题吗？")
#         if st.button("刷新并应用", key=f"confirm_refresh_theme"):
#             st.toast("新主题已应用！")
#             st.rerun()
        
#     options = ["Default", "Festival", "Buddies", "Prism"]
#     theme = st.segmented_control("更改页面主题",
#                                  options, 
#                                  default=st.session_state.theme,
#                                  selection_mode="single")
#     if st.button("确定"):
#         st.session_state.theme = theme
#         change_theme(THEME_COLORS.get(theme, None))
#         refresh_theme()
