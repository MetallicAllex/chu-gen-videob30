import os, time
import streamlit as st
from utils.Utils import fetch_music_data, should_update_metadata, get_ffmpeg_version
from utils.DataUtils import music_info_path, jp_music_info_path

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
    st.image("md_res/icon.png", width=300)
    
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
        <h2 class="ruby-container">中二节奏 Best30 生成器</h2>
    </div>
    
    <div style="text-align: left; margin-top: 15px;">
        <div class="version-info">版本：<span style="font-weight: bold;">[基于 mai-gen-videob30 修改] v0.5-bugfix3</span></div>
        <div class="guide-info">请按照引导操作以生成您的 Best30 视频。</div>
    </div>
    """, unsafe_allow_html=True)
    st.write(f"ffmpeg 版本：`{get_ffmpeg_version()}`")
    # st.markdown("请按照下列引导步骤操作，以生成您的 Best30 视频。")

st.info("""
        在开始使用前，请先阅读以下注意事项：
        - 缓存数据均保存在本地，如在编辑过程中意外退出，可加载已有存档继续编辑。
        - 使用时请不要随意刷新，这可能会导致索引丢失。
            - 发生此情况时，请重新加载存档并检查数据完整性。""", icon="ℹ️")
st.success("使用过程中遇到任何问题，前往 [GitHub 发起 issue](https://github.com/MetallicAllex/chu-gen-videob30/issues) 或 [加入 QQ 群](https://qm.qq.com/q/nFriOm4ZlS) 反馈", icon="✅")
# st.error("""
#          【落雪用户】本项目中部分操作会涉及您的查分器 Token，请注意以下四点：
#          - 该密钥对你查分器账号绑定的游戏数据拥有完全访问权限
#          - 该密钥无视查分器账号的隐私设置
#          - 不要分享该密钥给不信任的第三方（本查分器仅用于获取游戏数据）
#          - 如果该密钥被泄露，请及时重新生成密钥
#          """, icon="❗")
metadata_status = os.path.exists(music_info_path) and os.path.exists(jp_music_info_path)
if not metadata_status:
    st.warning("""
               注意！您的包体（目前）未拥有谱面数据
               - 刚下载的新包体**默认未携带谱面数据**，请先下载后再开始
               - **已经使用过但未存在谱面数据**，可能是被误删除，请重新下载
               """, icon="⚠️")
    
col1, col2 = st.columns([.45, 1], vertical_alignment="center")
with col1:
    st.write("准备好时，单击右边按钮开始")

with col2:
    if st.button("开始使用", icon="▶️", disabled=not metadata_status, help="请确保您已拥有谱面数据", use_container_width=True):
        st.switch_page("st_pages/1_Setup_Achivments.py")

st.divider()
with st.expander("附加选项（谱面数据更新）"):
    st.warning("""
               若谱面数据不正确或已经修改（如游戏更新添加了新数据等），请及时更新
               - 此时间是基于生成器上次启动时间计算的，请以实际为准。
               """, icon="⚠️")
    update_status = should_update_metadata(24)
    update_help_text = "最近更新在 24 小时内" if update_status == False else "最近更新时间已超 24 小时"
    # col1, col2 = st.columns(2, vertical_alignment="center")
    # with col1:
    #     if update_status == False:
    #         st.success("最近一次更新在 24 小时内", icon="☑️") 
    #     else:
    #         st.error("最近一次更新已超过 24 小时", icon="⚠️")
    # with col2:
    if st.button(f"更新谱面数据（{update_help_text}）", help=update_help_text, icon="🔄️", use_container_width=True):
        fetch_music_data()
        st.toast("谱面数据更新完成！3 秒后刷新", icon="✅")
        time.sleep(3)
        st.rerun()