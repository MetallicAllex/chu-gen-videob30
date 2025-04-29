import streamlit as st

homepage = st.Page("st_pages/0_homepage.py",
                title="首页",
                icon=":material/home:")
setup = st.Page("st_pages/1_Setup_Achivments.py",
                title="获取 / 管理 B30 成绩与存档",
                icon=":material/leaderboard:")
img_gen = st.Page("st_pages/Generate_Pic_Resources.py",
                title="1. 生成 Best30 成绩图",
                icon=":material/photo_library:")

search = st.Page("st_pages/2_Search_For_Videoes.py",
                title="2. 搜索谱面确认视频信息",
                icon=":material/video_search:")
download = st.Page("st_pages/3_Confrim_Videoes.py",
                title="3. 检查和下载视频",
                icon=":material/video_settings:")
edit_comment = st.Page("st_pages/4_Edit_Video_Content.py",
                title="4-1. 编辑B30视频片段",
                icon=":material/movie_edit:")
edit_intro_ending = st.Page("st_pages/5_Edit_OpEd_Content.py",
                title="4-2. 编辑开场和结尾片段",
                icon=":material/edit_note:")
composite = st.Page("st_pages/6_Compostie_Videoes.py",
                title="5. 合成视频",
                icon=":material/animated_images:")

pg = st.navigation(
    {
        "Home": [homepage, setup],
        "Pre-generation": [img_gen, search, download],
        "Edit-video": [edit_comment, edit_intro_ending],
        "Run-generation": [composite]
    }
)

pg.run()
