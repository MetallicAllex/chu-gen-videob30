import os
import time
import traceback
import streamlit as st
from copy import deepcopy
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import *
from gene_images import generate_single_image
from concurrent.futures import ThreadPoolExecutor

# def st_generate_b30_images(placeholder, save_paths):
#     # read b30_data
#     b30_data = load_config(save_paths['data_file'])
#     image_path = save_paths['image_dir']
#     with placeholder.container(border=True):
#         pb = st.progress(0, text="正在生成 Best30 成绩底图...")
#         for index, record_detail in enumerate(b30_data):
#             pb.progress((index + 1) / len(b30_data), text=f"正在生成 Best30 成绩底图({index + 1}/{len(b30_data)})")
#             acc_string = f"{record_detail['score']}"
#             record_for_gene_image = deepcopy(record_detail)
#             record_for_gene_image['score'] = acc_string
#             prefix = "Best"
#             image_name_index = index
#             generate_single_image(
#                 # "./images/b30ViedoBase.png",
#                 f"./images/LevelBg/{record_detail['level_index']}.png",
#                 record_for_gene_image,
#                 image_path,
#                 prefix,
#                 image_name_index
#             )

# def st_generate_b30_images(placeholder, save_paths):
#     b30_data = load_config(save_paths['data_file'])
#     image_path = save_paths['image_dir']
        
#     def worker(index, record_detail):
#         try:
#             generate_single_image(
#                 f"./images/LevelBg/{record_detail['level_index']}.png",
#                 {"score": f"{record_detail['score']}", **record_detail},
#                 image_path,
#                 "Best",
#                 index
#             )
#             return True
#         except Exception as e:
#             print(f"生成图片 {index} 失败: {str(e)}")
#             return False
    
#     with placeholder.container(border=True):
#         pb = st.progress(0, text="正在生成 Best30 成绩底图...")
        
#         with ThreadPoolExecutor(max_workers=8) as executor:  # 限制线程数
#             futures = []
#             for index, record_detail in enumerate(b30_data):
#                 futures.append(
#                     executor.submit(worker, index, deepcopy(record_detail))
#                 )
            
#             # 实时更新进度条
#             completed = 0
#             while completed < len(b30_data):
#                 for future in futures:
#                     if future.done() and future.result():
#                         progress_value = max(completed / len(b30_data), 1.0)  # 确保不超过1.0
#                         pb.progress(progress_value)
#                 time.sleep(0.1)  # 避免CPU空转

def st_generate_b30_images(placeholder, save_paths):
    b30_data = load_config(save_paths['data_file'])
    image_path = save_paths['image_dir']
    
    def worker(index, record_detail):
        try:
            generate_single_image(
                f"./images/LevelBg/{record_detail['level_index']}.png",
                {"score": str(record_detail['score']), **record_detail},
                image_path,
                "Best",
                index,
                use_verse
            )
            return True
        except Exception as e:
            print(f"生成图片 {index} 失败: {e}")
            return False

    with placeholder.container(border=False):
        start_time = datetime.now()
        pb = st.progress(0, text="准备开始生成...")
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i, deepcopy(d)) 
                    for i, d in enumerate(b30_data)]
            
            completed = 0
            while completed < len(b30_data):
                new_completed = sum(1 for f in futures if f.done() and f.result())
                if new_completed > completed:
                    completed = new_completed
                    elapsed = (datetime.now() - start_time).total_seconds()
                    speed = completed / max(elapsed, 1e-3)  # 防止除零
                    remaining = (len(b30_data) - completed) / speed
                    
                    pb.progress(
                        min(completed / len(b30_data), 1.0),
                        text=(
                            f"进度: {completed}/{len(b30_data)} | "
                            # f"速度: {speed:.1f} 张/秒 | "
                            f"剩余: {remaining:.1f}秒"
                        )
                    )
                time.sleep(0.01)

            # 生成完成后清除进度条
            pb.empty()  # 这行让进度条消失
            st.success(f"✅ 操作成功完成（{elapsed:.1f} 秒）")

st.title("Step 1: 生成 Best30 成绩底图")

### Savefile Management - Start ###
if "username" in st.session_state:
    st.session_state.username = st.session_state.username

if "save_id" in st.session_state:
    st.session_state.save_id = st.session_state.save_id

username = st.session_state.get("username", None)
save_id = st.session_state.get("save_id", None)
current_paths = None
data_loaded = False

if not username:
    st.error("请先获取 Best30 存档！")
    st.stop()

if save_id:
    # load save data
    current_paths = get_data_paths(username, save_id)
    data_loaded = True
    st.write(f"当前【用户名：{username}，存档时间：{save_id}】")
else:
    st.warning("未索引到存档，请先加载存档数据！")

with st.expander("需要更换存档？"):
    st.info("要更换，请回到存档管理页指定其他用户名。")
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
                    st.error("无效的存档路径！")
    else:
        st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
        st.stop()
### Savefile Management - End ###

if data_loaded:
    image_path = current_paths['image_dir']
    st.text("生成成绩图底图")
    with st.container(border=True):
        st.write("确认你的存档数据无误后，点击 “生成” 按钮开始生成。")
        use_verse = st.checkbox("添加 verse 定数并计算新 Rating", help="定数或 Rating 不变时仅标记后缀【16.15(verse)】")
        if use_verse:
            st.info("示例：MASTER 14.3 将显示为 MASTER[14.3 → 14.6(verse)]", icon="ℹ️")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("生成成绩图底图", help="使用底图分辨率生成"):
                generate_info_placeholder = st.empty()
                try:
                    if not os.path.exists(image_path):
                        os.makedirs(image_path, exist_ok=True)
                    st_generate_b30_images(generate_info_placeholder, current_paths)
                    # st.success("操作成功完成。")
                except Exception as e:
                    st.error(f"生成时发生错误: {e}")
                    st.error(traceback.format_exc())
            if os.path.exists(image_path):
                absolute_path = os.path.abspath(image_path)
            else:
                absolute_path = os.path.abspath(os.path.dirname(image_path))
        with col2:
            if st.button("打开存储文件夹", key=f"open_folder_{username}", help=absolute_path):
                open_file_explorer(absolute_path)
        st.info("如果已经生成过底图，且无需更新，可以跳过。", icon="ℹ️")
        if st.button("下一步"):
            st.switch_page("st_pages/2_Search_For_Videoes.py")