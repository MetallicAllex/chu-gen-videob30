import streamlit as st
from update_music_data import fetch_music_data
# from utils.PageUtils import change_theme
# from utils.themes import THEME_COLORS



st.title("Chu-gen Best30视频生成器")

st.write("当前版本: v0.4.0")

st.markdown("请按照下列引导步骤操作，以生成您的B30视频。")

st.info("缓存数据均保存在本地，如在编辑过程中意外退出，可加载已有存档继续编辑。", icon="ℹ️")
st.info("使用时请不要随意刷新，这可能会导致索引丢失。如果发生此情况建议重新加载存档并检查数据完整性。", icon="ℹ️")
st.success("使用过程中遇到任何问题，前往 [GitHub 发起 issue](https://github.com/MetallicAllex/chu-gen-videob30/issues)", icon="✅")

st.write("单击下面的按钮开始")

col1, col2 = st.columns(2)

with col1:
    if st.button("开始使用"):
        st.switch_page("st_pages/1_Setup_Achivments.py")

with col2:
    if st.button("更新乐曲数据"):
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
