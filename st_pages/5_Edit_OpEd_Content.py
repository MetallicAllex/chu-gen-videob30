import streamlit as st
import os
import json
import traceback
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import get_data_paths, get_user_versions

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
        # 添加新元素的按钮
        if st.button(f"添加一页", key=f"add_{name}"):
            new_item = {
                "id": f"{name}_{len(items) + 1}",
                "duration": 10,
                "text": "【请填写内容】"
            }
            items.append(new_item)
            st.session_state[f"{name}_items"] = items
            st.rerun(scope="fragment")
        
        # 为每个元素创建编辑组件
        for idx, item in enumerate(items):
            with st.expander(f"{name} 展示：第 {idx + 1} 页", expanded=True):
                # 文本编辑框
                new_text = st.text_area(
                    "文本内容",
                    value=item["text"],
                    key=f"{item['id']}_text"
                )
                items[idx]["text"] = new_text
                
                scol1, scol2 = st.columns(2, vertical_alignment="bottom")
                with scol1:
                    st.subheader("持续(s)")
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
                items[idx]["duration"] = new_duration
                
        # 删除按钮（只有当列表长度大于1时才显示）
        if len(items) > 1:
            if st.button("删除此页", key=f"delete_{name}", icon="🗑️"):
                items.pop()
                st.session_state[f"{name}_items"] = items
                st.rerun(scope="fragment")

        
        # 保存按钮
        if st.button("保存", key=f"save_{name}"):
            try:
                # 更新配置
                config[name] = items
                ## 保存当前配置
                save_config(config_file_path, config)
                st.success("配置已保存！", icon="✅")
            except Exception as e:
                st.error(f"保存失败：{str(e)}", icon="❌")
                st.error(traceback.format_exc())

if not username:
    st.error("请先获取指定用户名的 B30 存档！", icon="❗")
    st.stop()

if save_id:
    # load save data
    current_paths = get_data_paths(username, save_id)
    data_loaded = True
    st.write(f"当前存档【用户名：{username}，存档时间：{save_id}】")


    # 为了实现实时的小组件更新，文本框数据存储在session_state中，
    # 因此需要在读取存档的过程中更新
    video_config_file = current_paths['video_config']
    if not os.path.exists(video_config_file):
        st.error(f"未找到{video_config_file}，请检查前置步骤是否完成，以及b30存档的数据完整性！", icon="❌")
        config = None
    else:
        config = load_config(video_config_file)
        for name in ["intro", "ending"]:
            st.session_state[f"{name}_items"] = config[name]
else:
    st.warning("未索引到存档，请先加载存档数据！", icon="⚠️")

with st.expander("更换B30存档"):
    st.info("要更换，请回到存档管理页指定其他用户名。", icon="ℹ️")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            selected_save_id = st.selectbox(
                "选择存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y-%m-%d')})"
            )
            if st.button("使用此存档（只需要点击一次！）"):
                if selected_save_id:
                    st.session_state.save_id = selected_save_id
                    st.rerun()
                else:
                    st.error("无效的存档路径！", icon="❌")
    else:
        st.warning("未找到任何存档，请先在存档管理页获取存档！", icon="⚠️")
        st.stop()
if not save_id:
    st.stop()
### Savefile Management - End ###

if config:
    st.write("添加想要展示的文字内容，每一页最多可以展示约250字")
    st.info("左右两侧填写完毕后，需要分别点击保存才可生效！", icon="ℹ️")

    # 分为两栏，左栏读取intro部分的配置，右栏读取outro部分的配置
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("片头")
        edit_context_widget("intro", config, video_config_file)
    with col2:
        st.subheader("片尾")
        edit_context_widget("ending", config, video_config_file)

    st.write("配置完毕后，即可进入视频生成步骤")
    if st.button("下一步"):
        st.switch_page("st_pages/6_Compostie_Videoes.py")
else:
    st.warning("未找到视频生成生成配置！请检查是否完成了4-1！", icon="⚠️")

