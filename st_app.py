import sys
import streamlit as st
from utils import DataUtils as DU

# 控制台默认代码页不是 UTF-8 时（手工 `streamlit run st_app.py`，未走 start.bat 的
# chcp 65001），渲染里 print 曲名中的 `・` 等字符会抛 UnicodeEncodeError 打断整条
# 渲染。只放宽错误处理、不改编码，输出内容照常。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(errors='replace')
        except Exception:
            pass

st.set_page_config(
    page_title="chu-gen-videob30",
    page_icon="🐧",
    layout="wide"
)

# ========== 初始化会话状态 ==========
# 曲库交给后台补齐：新包体默认不带谱面数据，而"点首页那个按钮才能解锁下一步"等于把
# 程序自己知道的该加载什么推给了人。全量最慢实测 56 秒，所以不挡首次渲染。
if not st.session_state.get("music_data_started"):
    st.session_state.music_data_started = True
    DU.start_music_data_update()

# 每轮重算，不能只算一次：后台线程把曲库拉回来后，"获取 / 管理存档"要自己冒出来。
st.session_state.has_data = DU.music_data_state()["core_ready"]
if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False
if 'data_updated_step1' not in st.session_state:
    st.session_state.data_updated_step1 = False
if 'save_id' not in st.session_state:
    st.session_state.save_id = None
if 'username' not in st.session_state:
    st.session_state.username = None

# ========== 检查存档状态 ==========
def has_datas():
    return st.session_state.get('has_data', False)

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
                icon=":material/leaderboard:",
                visibility="visible" if has_datas() else "hidden"
                )

# 需要存档的页面 - 根据状态决定是否可见
img_gen = st.Page("st_pages/Generate_Pic_Resources.py",
                title="生成 Best50 图 / 查看数据",
                icon=":material/photo_library:",
                visibility="visible" if has_valid_save() else "hidden")

custom_style = st.Page("st_pages/Custom_Video_Style.py",
                    title="视频样式编辑器",
                    icon=":material/palette:",
                    visibility="visible" if has_valid_save() else "hidden")

custom_save = st.Page("st_pages/Make_Custom_Save.py",
                    title="编辑 Best50 数据",
                    icon=":material/leaderboard:",
                    visibility="visible" if has_valid_save() else "hidden")

download = st.Page("st_pages/3_Confirm_Videos.py",
                title="搜索、检查和下载视频",
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
    "主页 & 存档准备": [homepage, setup],
    "[可选]个性化 & 自定义": [custom_save, custom_style],
    "预生成": [img_gen, download],
    "内容编辑": [edit_comment, edit_intro_ending],
    "最终生成": [composite]
}

pg = st.navigation(nav_dict, expanded=False)

# ========== 运行页面 ==========
pg.run()