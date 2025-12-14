import os, time, traceback
import pandas as pd
import streamlit as st
from copy import deepcopy
from datetime import datetime
from utils.DataUtils import load_config_with_types, save_config_with_types
from utils.PageUtils import *
from utils.PathUtils import *
from utils.ImageUtils import generate_single_image
from concurrent.futures import ThreadPoolExecutor

def st_generate_b30_images(placeholder, save_paths):
    b50_data = load_config(save_paths['data_file'])
    image_path = save_paths['image_dir']
    
    def worker(index, record_detail):
        prefix, index = record_detail['clip_id'].split('_', 1)
        try:
            generate_single_image(
                # {"score": str(record_detail['score']), **record_detail},
                record_detail,
                image_path,
                # "Best",
                prefix,
                int(index)
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
                    for i, d in enumerate(b50_data)]
            
            completed = 0
            while completed < len(b50_data):
                new_completed = sum(1 for f in futures if f.done() and f.result())
                if new_completed > completed:
                    completed = new_completed
                    elapsed = (datetime.now() - start_time).total_seconds()
                    speed = completed / max(elapsed, 1e-3)  # 防止除零
                    remaining = (len(b50_data) - completed) / max(speed, 1e-3)
                    
                    pb.progress(
                        min(completed / len(b50_data), 1.0),
                        text=(
                            f"进度: {completed}/{len(b50_data)}&nbsp; | &nbsp;"
                            # f"速度: {speed:.1f} 张/秒 | "
                            f"剩余: {remaining:.1f}秒"
                        )
                    )
                time.sleep(0.01)
            
            # 生成完成后清除进度条
            pb.empty()  # 这行让进度条消失
            st.toast(f"操作成功完成", icon="✅")

st.title("Step 1: 生成 Best50 成绩底图")

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
    st.error("请先获取 Best50 存档！", icon="❌")
    st.stop()
    
with st.container(border=True):
    if save_id:
        # load save data
        current_paths = get_data_paths(username, save_id)
        data_loaded = True
        # st.write(f"当前存档【用户名：{username}，存档时间：{save_id}】")
        # 方案2：指标卡片式显示
        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                label="👤 当前用户",
                value=username
            )
        with col2:
            st.metric(
                label="⏰ 存档时间", 
                value=save_id
            )
    else:
        st.warning("未索引到存档，请先加载存档数据！")

    with st.expander("更换 Best50 存档", icon="💾"):
        st.info("要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
        st.warning("若您需要修改存档数据，请确保编辑区域未加载任何存档内的任何数据。", icon="⚠️")
        versions = get_user_versions(username)
        if versions:
            selected_save_id = st.selectbox(
                "选择存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
            )
            if st.button("使用此存档", help="（只需要点击一次！）", use_container_width=True, icon="▶️"):
                if selected_save_id:
                    st.session_state.save_id = selected_save_id
                    st.rerun()
                else:
                    st.error("无效的存档路径！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
            st.stop()
### Savefile Management - End ###

### Data Editing Section - Start ###
st.divider()
with st.container(border=True):
    if data_loaded:
        st.subheader("📊 编辑 Best50 数据")
        
        # 初始化会话状态（只用于编辑部分）
        if 'editing_data_loaded' not in st.session_state:
            st.session_state.editing_data_loaded = False
        if 'editing_enabled' not in st.session_state:
            st.session_state.editing_enabled = False
        
        # 数据管理按钮
        col1, col2, col3 = st.columns(3)
        
        if not st.session_state.editing_data_loaded:
            if st.button("加载数据", use_container_width=True, type="primary", icon="📥", help="如果您需要修改，请「加载数据」"):
                st.session_state.editing_data_loaded = True
                st.session_state.editing_enabled = False
                st.rerun()
        else:
            with col1:
                if st.button("卸载数据", use_container_width=True, icon="📤", help="如果您已修改完成或不需要修改，请「卸载数据」"):
                    st.session_state.editing_data_loaded = False
                    st.session_state.editing_enabled = False
                    if 'editing_b50_data' in st.session_state:
                        del st.session_state.editing_b50_data
                    st.rerun()
        
        with col2:
            if st.session_state.editing_data_loaded and st.session_state.editing_enabled:
                if st.button("锁定", use_container_width=True, icon="🔒", help="将表格设置为只读，防止误修改"):
                    st.session_state.editing_enabled = False
                    st.rerun()
            elif st.session_state.editing_data_loaded and not st.session_state.editing_enabled:
                if st.button("解锁", use_container_width=True, icon="🔓", help="解除只读状态"):
                    st.session_state.editing_enabled = True
                    st.rerun()
        
        with col3:
            if st.session_state.editing_data_loaded:
                if st.button("重新加载", use_container_width=True, icon="🔄", help="（如果您的数据已更新或显示异常）"):
                    if 'editing_b50_data' in st.session_state:
                        del st.session_state.editing_b50_data
                    st.rerun()
        
        # 状态提示
        if not st.session_state.editing_data_loaded:
            st.info("""
                    请先「加载数据」以查看和编辑数据。
                    - 加载后默认只读保护数据不被修改
                        - 请确定您确实需要修改数据时再「解锁」""", icon="💡")
            # 这里不要用 st.stop()，让用户继续看到下面的图像生成部分
        
        elif not st.session_state.editing_enabled:
            st.warning("当前处于只读模式，「解锁」后才能修改", icon="🔒")
        
        # 只有在加载了编辑数据时才显示编辑器
        if st.session_state.editing_data_loaded:
            try:
                # 加载数据（使用缓存，使用独立的session_state键）
                if 'editing_b50_data' not in st.session_state:
                    st.session_state.editing_b50_data = load_config_with_types(current_paths['data_file'])
                
                b50_data = st.session_state.editing_b50_data
                
                with st.expander("编辑您的 Best50 数据", expanded=True, icon="📝"):
                    st.info("""
                            在表格中直接编辑数据，编辑完成后记得「保存修改」。
                            - 等级索引：0（绿）、1（黄）、2（红）、3（紫）、4（黑）
                            - Combo 类型：若您的成绩为 1010000，直接选择 alljustice 即可
                                - 生成图像时会自动根据您的成绩判断是否为 AJC
                            - Chain 类型：水鱼并未在接口中提供 Chain 数据
                                - 本槽留空，使用水鱼的玩家请自行确定本曲是否已有 Chain
                            - 剩余的标注请指向列头表签查看
                            - 如果您需要计算 rating，请[访问此页](https://public.cm-tea.top/Rating_Calculator_CHUNITHM.html)
                            """, icon="ℹ️")
                    
                    # 显示数据预览和编辑，修改为：
                    edited_data = st.data_editor(
                        b50_data,
                        column_config={
                            "id": st.column_config.NumberColumn(
                                "歌曲 ID", 
                                width="small", 
                                required=True,
                                format="%d",  # 强制显示为整数
                            ),
                            "song_name": st.column_config.TextColumn("曲名", width="medium", required=True),
                            "artist": st.column_config.TextColumn("曲师", width="medium", required=True),
                            "level": st.column_config.NumberColumn(
                                "等级", 
                                min_value=1.0, 
                                max_value=20.0, 
                                step=0.1, 
                                format="%.1f", 
                                width="small", 
                                required=True
                            ),
                            "level_index": st.column_config.NumberColumn(
                                "等级索引", 
                                min_value=0, 
                                max_value=4, 
                                step=1, 
                                width="small", 
                                help="0(BASIC)、1(ADVANCED)、2(EXPERT)、3(MASTER)、4(ULTIMA)", 
                                required=True,
                                format="%d"  # 强制显示为整数
                            ),
                            "level_next": st.column_config.NumberColumn(
                                "下版本等级", 
                                min_value=1.0, 
                                max_value=20.0, 
                                step=0.1, 
                                format="%.1f", 
                                width="small", 
                                required=True
                            ),
                            "score": st.column_config.NumberColumn(
                                "分数", 
                                min_value=0, 
                                max_value=1010000, 
                                step=100, 
                                width="small", 
                                required=True,
                                format="%d"  # 强制显示为整数
                            ),
                            "rating": st.column_config.NumberColumn(
                                "Rating", 
                                min_value=0.0, 
                                max_value=20.0, 
                                step=0.01, 
                                format="%.2f", 
                                width="small",
                                required=True
                            ),
                            "full_combo": st.column_config.SelectboxColumn(
                                "Combo 类型",
                                width="small",
                                options=[None, "fullcombo", "alljustice"],
                                help="若您的成绩为 1010000，直接选择 alljustice 即可，生成图像时会自动根据您的成绩判断是否为 AJC"
                            ),
                            "full_chain": st.column_config.SelectboxColumn(
                                "Chain 类型",
                                width="small",
                                help="使用水鱼的玩家请自行确定本曲是否已有 Chain",
                                options=[None, "fullchain", "fullchain2"]
                            ),
                            "clip_id": st.column_config.TextColumn(
                                "剪辑 ID", width="small", required=True, default="PickUp_1",
                                help="若添加歌曲，您只能以 PickUp_*(数字) 格式添加，此命名将用于左下角的播放曲目排名",
                                pinned=True
                            ),
                            "play_count": st.column_config.NumberColumn(
                                "游玩次数", 
                                width="small", 
                                min_value=0, 
                                step=1, 
                                help="如果需要填写游玩次数，请在此填充具体数值", 
                                format="%d",  # 强制显示为整数
                                default=None  # 允许空值
                            )
                        },
                        hide_index=True,
                        num_rows="dynamic",
                        use_container_width=True,
                        key="data_editor",
                        disabled=not st.session_state.editing_enabled
                    )
                    
                    # 操作按钮（只在编辑模式下显示）
                    if st.session_state.editing_enabled:
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            if st.button("保存修改", use_container_width=True, type="primary", icon="💾", help="保存您对自己的数据修改"):
                                # 在保存前进行数据类型清理
                                cleaned_data = []
                                for item in edited_data:
                                    cleaned_item = {}
                                    for key, value in item.items():
                                        # 处理空值和类型
                                        if value is None or (isinstance(value, (int, float)) and pd.isna(value)):
                                            cleaned_item[key] = None
                                        elif key in ['id', 'score', 'level_index', 'play_count'] and value is not None:
                                            cleaned_item[key] = int(value)
                                        elif key in ['level', 'level_next', 'rating'] and value is not None:
                                            cleaned_item[key] = float(value)
                                        # elif key == 'play_count' and value is not None:
                                        #     cleaned_item[key] = int(value)
                                        else:
                                            cleaned_item[key] = value
                                    cleaned_data.append(cleaned_item)
                                
                                # 使用新的保存函数
                                if save_config_with_types(current_paths['data_file'], cleaned_data):
                                    st.session_state.editing_b50_data = cleaned_data  # 更新缓存数据
                                    st.session_state.data_edited = True
                                    st.success("数据保存成功！", icon="✅")
                                    st.rerun()
                        
                        with col2:
                            if st.button("放弃修改", use_container_width=True, icon="🗑️", help="放弃您对自己的数据修改"):
                                # 重新加载原始数据
                                if 'editing_b50_data' in st.session_state:
                                    del st.session_state.editing_b50_data
                                st.success("已放弃所有修改", icon="✅")
                                st.rerun()
                
                # 数据统计卡片
                st.caption("📈 数据概览", help="（包括您手动加入的）")
                stats_col1, stats_col2, stats_col3, stats_col4, stats_col5, stats_col6 = st.columns(6)
                
                with stats_col1:
                    total_records = len(edited_data)
                    st.metric("总记录数", total_records)
                
                with stats_col2:
                    expert_count = sum(1 for item in edited_data if item.get('level_index') == 2)
                    st.metric("EXPERT 数", expert_count)
                
                with stats_col3:
                    master_count = sum(1 for item in edited_data if item.get('level_index') == 3)
                    st.metric("MASTER 数", master_count)
                        
                with stats_col4:
                    ultima_count = sum(1 for item in edited_data if item.get('level_index') == 4)
                    st.metric("ULTIMA 数", ultima_count)
                    
                with stats_col5:
                    hardest_level = max((item.get('level', 0) for item in edited_data), default=0)
                    st.metric("最难曲目等级", f"{hardest_level:.1f}")
                    
                with stats_col6:
                    highest_rating = max((item.get('rating', 0) for item in edited_data), default=0)
                    st.metric("最高单曲 ra", f"{highest_rating:.2f}")
                        
            except Exception as e:
                st.error(f"加载数据失败: {e}", icon="❌")

### Data Editing Section - End ###

st.divider()
if data_loaded:
    image_path = current_paths['image_dir']
    with st.container(border=True):
        st.text("确认存档数据无误后，即可生成您的 Best50 显示图像（将用您上面的数据生成）")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("生成成绩图底图", help="使用 1920 × 1080 生成", icon="🔄️", use_container_width=True):
                generate_info_placeholder = st.empty()
                try:
                    if not os.path.exists(image_path):
                        os.makedirs(image_path, exist_ok=True)
                    st_generate_b30_images(generate_info_placeholder, current_paths)
                    # st.success("操作成功完成。")
                except Exception as e:
                    st.toast(f"生成时发生错误: {e}", icon="❌")
                    st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❗")
            if os.path.exists(image_path):
                absolute_path = os.path.abspath(image_path)
            else:
                absolute_path = os.path.abspath(os.path.dirname(image_path))

        with col2:
            if st.button("打开存储文件夹", key=f"open_folder_{username}",
                         help=f"""
                         {absolute_path}
                         - 图像均以 `clip_id` 命名，如 `Best_1`
                         """, use_container_width=True, icon="📂"):
                open_file_explorer(absolute_path)

        col1, col2 = st.columns([2, 1], vertical_alignment="center")
        with col1:
            st.info("如果已经生成过底图，且无需更新，可以跳过。", icon="ℹ️")
        
        with col2:
            if st.button("下一步", icon="➡️", use_container_width=True):
                st.switch_page("st_pages/2_Search_For_Videoes.py")