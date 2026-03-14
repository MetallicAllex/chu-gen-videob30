import os, traceback
import streamlit as st
from datetime import datetime
from utils.PathUtils import *

st.header("Step 4-2: 片头/片尾内容编辑")

G_config = read_global_config()

### Savefile Management - Start ###
if "username" in st.session_state:
    st.session_state.username = st.session_state.username

if "save_id" in st.session_state:
    st.session_state.save_id = st.session_state.save_id

username = st.session_state.get("username", None)
save_id = st.session_state.get("save_id", None)
current_paths = None
data_loaded = False

@st.fragment
def edit_context_widget(name, config, config_file_path):
    # 创建一个container来容纳所有组件
    container = st.container(border=True)
    
    # 在session_state中存储当前配置列表
    if f"{name}_items" not in st.session_state:
        st.session_state[f"{name}_items"] = config[name]
    
    items = st.session_state[f"{name}_items"]
    
    with container:
        # 为每个元素创建编辑组件
        for idx, item in enumerate(items):
            with st.expander(f"{name} 展示：第 {idx + 1} 页", expanded=True, icon="⏮️" if name == "intro" else "⏭️"):
                # 添加版本选择器
                # list_versions = G_config.get("AVAILABLE_VERSION", [])
                # sel_version = st.radio(
                #     "选择背景播放的游戏版本",
                #     options=list_versions,
                #     index=list_versions.index(item["version"]) if item["version"] in list_versions else 0,
                #     key=f"{item['id']}_version",
                #     horizontal=True
                # )
                # 文本编辑框
                info_page = st.checkbox("此页为背景板", help="可在此页展示您需要额外编辑的内容", key=f"{item['id']}_bg_page", value=item["bg_page"])
                new_text = st.text_area(
                    "文本内容",
                    value=item["text"],
                    key=f"{item['id']}_text",
                    help="每超过 16 行将多分 1 个平均时长的文本页" if not info_page else "背景板页不可输入任何内容，若要添加其他内容请多留空白区域",
                    placeholder="输入要展示的文本（emoji 无法被渲染，请不要输入，其他内容请查看右上角的问号）",
                    disabled=info_page
                )
                # items[idx]["text"] = new_text
                # items[idx]["bg_page"] = info_page
                # items[idx]['version'] = sel_version

                scol1, scol2 = st.columns(2, vertical_alignment="bottom")
                with scol1:
                    st.subheader("时长(s)")
                with scol2:
                    new_duration = st.number_input("秒", min_value=0, max_value=30, value=item["duration"], step=1, key=f"{item['id']}_duration", label_visibility="collapsed")
                # 持续时间滑动条
                # new_duration = st.slider(
                #     "持续时间（秒）",
                #     min_value=5,
                #     max_value=30,
                #     value=item["duration"],
                #     key=f"{item['id']}_duration"
                # )
                items[idx]["text"] = new_text
                items[idx]["bg_page"] = info_page
                items[idx]["duration"] = new_duration
                
        # 删除按钮（只有当列表长度大于 1 时才显示）
        if len(items) > 1:
            if st.button(f"删除第 {idx + 1} 页", key=f"delete_{name}", icon="🗑️", width='stretch'):
                items.pop()
                st.session_state[f"{name}_items"] = items
                st.rerun(scope="fragment")

        st.divider()

        col1, col2 = st.columns(2, vertical_alignment="bottom")
        with col1:
            # 添加新元素的按钮
            if st.button(f"添加一页", key=f"add_{name}", icon="➕", width='stretch'):
                new_item = {
                    "id": f"{name}_{len(items) + 1}",
                    "duration": 10,
                    "text": "",
                    "bg_page": False
                    # "version": "LUMINOUS"
                }
                items.append(new_item)
                st.session_state[f"{name}_items"] = items
                st.rerun(scope="fragment")

        with col2:
            # 保存按钮
            if st.button("保存", key=f"save_{name}", icon="💾", width='stretch'):
                try:
                    # 更新配置
                    config[name] = items
                    ## 保存当前配置
                    save_config(config_file_path, config)
                    st.toast("配置已保存！", icon="✅")
                except Exception as e:
                    st.toast(f"保存失败：{str(e)}", icon="❌")
                    st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❗")

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

        # 为了实现实时的小组件更新，文本框数据存储在session_state中，
        # 因此需要在读取存档的过程中更新
        video_config_file = current_paths['video_config']
        if not os.path.exists(video_config_file):
            st.error(f"未找到 {video_config_file} ，请检查前置步骤是否完成，以及 b30 存档数据完整性！", icon="❌")
            config = None
        else:
            config = load_config(video_config_file)
            for name in ["intro", "ending"]:
                st.session_state[f"{name}_items"] = config[name]
    else:
        st.warning("未索引到存档，请先加载存档数据！", icon="⚠️")

    with st.expander("更换 Best50 存档", icon="💾"):
        st.info("要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
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
    if not save_id:
        st.stop()
### Savefile Management - End ###

if config:
    st.write("添加想要展示的文字内容，每一页最多可以展示约 250 字")
    st.info("""
            左右两侧填写完毕后，需要分别点击保存才可生效！
            - 文本页（展示页内文本）显示时长将按画面页（整个展示页）时长平均切分
            """, icon="ℹ️")

    # 分为两栏，左栏读取intro部分的配置，右栏读取outro部分的配置
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("片头")
        edit_context_widget("intro", config, video_config_file)
    with col2:
        st.subheader("片尾")
        edit_context_widget("ending", config, video_config_file)
    
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        st.write("配置完毕后，即可准备生成您的 Best30 视频")
    with col2:
        if st.button("下一步", width='stretch', icon="➡️"):
            st.switch_page("st_pages/6_Compostie_Videos.py")
else:
    st.warning("未找到视频生成生成配置！请检查是否完成了4-1！", icon="⚠️")

