import streamlit as st

st.set_page_config(
    page_title="chu-gen-videob30",
    page_icon="🐧",
    layout="wide"
)

# homepage = st.Page("st_pages/0_homepage.py",
#                 title="首页",
#                 icon=":material/home:")
# setup = st.Page("st_pages/1_Setup_Achivments.py",
#                 title="获取 / 管理存档",
#                 icon=":material/leaderboard:")
# img_gen = st.Page("st_pages/Generate_Pic_Resources.py",
#                 title="生成 Best50 图 / 编辑数据",
#                 icon=":material/photo_library:")

# custom_style = st.Page("st_pages/Custom_Video_Style.py",
#                     title="（可选）视频样式编辑器",
#                     icon=":material/palette:")

# custom_save = st.Page("st_pages/Make_Custom_Save.py",
#                     title="（可选）自定义 Best50 数据",
#                     icon=":material/leaderboard:")

# search = st.Page("st_pages/2_Search_For_Videos.py",
#                 title="搜索谱面确认视频信息",
#                 icon=":material/video_search:")
# download = st.Page("st_pages/3_Confirm_Videos.py",
#                 title="检查和下载视频",
#                 icon=":material/video_settings:")
# edit_comment = st.Page("st_pages/4_Edit_Video_Content.py",
#                 title="编辑 Best50 视频片段",
#                 icon=":material/movie_edit:")
# edit_intro_ending = st.Page("st_pages/5_Edit_OpEd_Content.py",
#                 title="编辑开场和结尾",
#                 icon=":material/edit_note:")
# composite = st.Page("st_pages/6_Compostie_Videos.py",
#                 title="合成视频",
#                 icon=":material/animated_images:")

# pg = st.navigation(
#     {
#         "Home": [homepage, setup],
#         "Customization": [custom_save, custom_style],
#         "Pre-generation": [img_gen, search, download],
#         "Edit-video": [edit_comment, edit_intro_ending],
#         "Run-generation": [composite]
#     }, expanded=False
# )

# pg.run()

# ========== 初始化会话状态 ==========
if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False
if 'data_updated_step1' not in st.session_state:
    st.session_state.data_updated_step1 = False
if 'save_id' not in st.session_state:
    st.session_state.save_id = None
if 'username' not in st.session_state:
    st.session_state.username = None

# ========== 检查存档状态 ==========
def has_valid_save():
    """检查是否有有效存档"""
    return (st.session_state.get('config_saved', False) and 
            st.session_state.get('save_id') is not None and
            st.session_state.get('data_updated_step1', False))

# ========== 定义所有页面（根据状态设置 visibility）==========
homepage = st.Page("st_pages/0_homepage.py",
                title="首页",
                icon=":material/home:")

setup = st.Page("st_pages/1_Setup_Achivments.py",
                title="获取 / 管理存档",
                icon=":material/leaderboard:")

# 需要存档的页面 - 根据状态决定是否可见
img_gen = st.Page("st_pages/Generate_Pic_Resources.py",
                title="生成 Best50 图 / 编辑数据",
                icon=":material/photo_library:",
                visibility="visible" if has_valid_save() else "hidden")

custom_style = st.Page("st_pages/Custom_Video_Style.py",
                    title="（可选）视频样式编辑器",
                    icon=":material/palette:",
                    visibility="visible" if has_valid_save() else "hidden")

custom_save = st.Page("st_pages/Make_Custom_Save.py",
                    title="（可选）自定义 Best50 数据",
                    icon=":material/leaderboard:",
                    visibility="visible" if has_valid_save() else "hidden")

search = st.Page("st_pages/2_Search_For_Videos.py",
                title="搜索谱面确认视频信息",
                icon=":material/video_search:",
                visibility="visible" if has_valid_save() else "hidden")

download = st.Page("st_pages/3_Confirm_Videos.py",
                title="检查和下载视频",
                icon=":material/video_settings:",
                visibility="visible" if has_valid_save() else "hidden")

edit_comment = st.Page("st_pages/4_Edit_Video_Content.py",
                title="编辑 Best50 视频片段",
                icon=":material/movie_edit:",
                visibility="visible" if has_valid_save() else "hidden")

edit_intro_ending = st.Page("st_pages/5_Edit_OpEd_Content.py",
                title="编辑开场和结尾",
                icon=":material/edit_note:",
                visibility="visible" if has_valid_save() else "hidden")

composite = st.Page("st_pages/6_Compostie_Videos.py",
                title="合成视频",
                icon=":material/animated_images:",
                visibility="visible" if has_valid_save() else "hidden")

# ========== 创建导航 ==========
nav_dict = {
    "Home & Pre-setup": [homepage, setup],
    "Customization": [custom_save, custom_style],
    "Pre-generation": [img_gen, search, download],
    "Edit-video": [edit_comment, edit_intro_ending],
    "Run-generation": [composite]
}

pg = st.navigation(nav_dict, expanded=False)

# ========== 运行页面 ==========
pg.run()