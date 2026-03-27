import streamlit as st
from copy import deepcopy
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import *
import os, time, traceback, shutil
from utils.Variables import root_path
from concurrent.futures import ThreadPoolExecutor
from utils.DataUtils import load_config_with_types
from utils.ImageUtils import generate_single_image

def st_generate_b30_images(placeholder, save_paths):
    b50_data = load_config(save_paths['data_file'])
    image_path = f"{save_paths['image_dir']}/background"
    
    # 确保图片目录存在
    os.makedirs(image_path, exist_ok=True)
    
    def check_image_exists(record_detail):
        """检查图片是否已存在"""
        prefix, index = record_detail['clip_id'].split('_', 1)
        # 构建预期的图片文件名（根据你的命名规则调整）
        expected_filename = f"{prefix}_{index}.png"  # 或其他扩展名
        expected_path = os.path.join(image_path, expected_filename)
        return os.path.exists(expected_path), expected_filename
    
    def worker(index, record_detail):
        # 先检查图片是否已存在
        exists, filename = check_image_exists(record_detail)
        if exists:
            print(f"图片 {filename} 已存在，跳过生成")
            return "skipped"
        
        prefix, index = record_detail['clip_id'].split('_', 1)
        custom_data = load_config(current_paths['custom_style'])
        try:
            generate_single_image(
                record_detail,
                custom_data,
                image_path,
                # prefix,
                # int(index)
            )
            return "success"
        except Exception as e:
            print(f"在生成 {prefix} 图片 {index} 失败: {e}")
            return "failed"

    with placeholder.container(border=False):
        start_time = datetime.now()
        
        # 预处理：检查哪些需要生成
        total_items = len(b50_data)
        existing_count = 0
        to_generate = []
        
        for i, d in enumerate(b50_data):
            exists, filename = check_image_exists(d)
            if exists:
                existing_count += 1
            else:
                to_generate.append((i, deepcopy(d)))
        
        # 显示初始状态
        if existing_count > 0:
            st.toast(f"将跳过已发现的 {existing_count} 张图片", icon="ℹ️")
        
        if not to_generate:
            st.toast("所有图片已存在，无需生成", icon="✅")
            return
        
        # 创建进度条
        pb = st.progress(0, text=f"准备生成 {len(to_generate)} 张图片...")
        
        # 统计数据 - 初始化时只包含跳过的
        stats = {
            'success': 0,
            'failed': 0,
            'skipped': existing_count
        }
        
        # 记录已完成的任务，避免重复统计
        completed_tasks = set()
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(worker, i, d): i for i, d in to_generate}
            
            completed = 0
            total_to_generate = len(to_generate)
            
            while completed < total_to_generate:
                # 检查新完成的任务
                for future in list(futures.keys()):
                    if future.done() and future not in completed_tasks:
                        completed += 1
                        completed_tasks.add(future)
                        
                        # 统计结果
                        result = future.result()
                        if result == "success":
                            stats['success'] += 1
                        elif result == "failed":
                            stats['failed'] += 1
                        # skipped 已经包含在初始统计中
                        
                        # 计算进度
                        elapsed = (datetime.now() - start_time).total_seconds()
                        speed = completed / max(elapsed, 1e-3)
                        remaining = (total_to_generate - completed) / max(speed, 1e-3)
                        
                        # 更新进度条显示
                        progress_text = (
                            f"进度: {completed} / {total_to_generate} | "
                            f"成功: {stats['success']} | "
                            f"失败: {stats['failed']} | "
                            f"剩余: {remaining:.1f} 秒"
                        )
                        
                        pb.progress(
                            min(completed / total_to_generate, 1.0),
                            text=progress_text
                        )
                
                time.sleep(0.01)
            
            # 生成完成后显示总结
            pb.empty()
            
            # 显示最终统计
            summary = []
            if stats['success'] > 0:
                summary.append(f"成功生成: {stats['success']} 张")
            if stats['skipped'] > 0:
                summary.append(f"已跳过: {stats['skipped']} 张")
            if stats['failed'] > 0:
                summary.append(f"失败: {stats['failed']} 张")
            
            st.info(" | ".join(summary), icon="ℹ️")
            
            if stats['failed'] == 0:
                st.toast("所有图片处理完成！", icon="✅")
            else:
                st.toast(f"处理完成，但有 {stats['failed']} 张生成失败", icon="⚠️")
            time.sleep(5)
            st.rerun()

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
    else:
        st.warning("未索引到存档，请先加载存档数据！", icon="⚠️")

    with st.expander("更换 Best50 存档", icon="💾"):
        st.info("""
                要更换不同用户的存档，请回到存档管理页指定其他用户名
                - 请确保编辑区域未加载任何数据。
                """, icon="ℹ️")
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
                        st.error("无效的存档路径！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
            st.stop()
### Savefile Management - End ###

custom_dir = current_paths['custom_style']
if not os.path.exists(custom_dir):
    st.toast("无法找到存档内的样式文件，已复制默认样式文件至存档。", icon="✅️")
    shutil.copy2(f"{root_path}/themes/default.json", custom_dir)

### Data Viewing Section - Start ###
st.divider()
with st.container(border=True):
    if data_loaded:
        st.subheader("📊 查看 Best50 数据")
        
        # 简化会话状态，只保留必要的数据加载状态
        if 'viewing_data_loaded' not in st.session_state:
            st.session_state.viewing_data_loaded = False
        
        # 数据管理按钮 - 简化，只保留加载和卸载
        col1, col2 = st.columns(2)
        
        if not st.session_state.viewing_data_loaded:
            if st.button("加载数据", width='stretch', type="primary", icon="📥", help="加载数据以供查看"):
                st.session_state.viewing_data_loaded = True
                st.rerun()
        else:
            with col1:
                if st.button("卸载数据", width='stretch', icon="📤", help="卸载当前查看的数据"):
                    st.session_state.viewing_data_loaded = False
                    if 'viewing_b50_data' in st.session_state:
                        del st.session_state.viewing_b50_data
                    if 'processed_data' in st.session_state:
                        del st.session_state.processed_data
                    st.rerun()
            
            with col2:
                if st.button("刷新数据", width='stretch', icon="🔄", help="从文件重新加载最新数据"):
                    if 'viewing_b50_data' in st.session_state:
                        del st.session_state.viewing_b50_data
                    if 'processed_data' in st.session_state:
                        del st.session_state.processed_data
                    st.rerun()
        
        # 状态提示
        if not st.session_state.viewing_data_loaded:
            st.info("点击「加载数据」以查看当前存档的 Best50 数据。", icon="💡")
        
        # 只有在加载了数据时才显示表格
        if st.session_state.viewing_data_loaded:
            try:
                # 加载数据
                if 'viewing_b50_data' not in st.session_state:
                    st.session_state.viewing_b50_data = load_config_with_types(current_paths['data_file'])
                    st.session_state.processed_data = st.session_state.viewing_b50_data.copy()
                
                b50_data = st.session_state.viewing_b50_data
                
                # ========== 数据查看表格（只读模式）==========
                with st.expander("查看您的 Best50 数据", expanded=True, icon="📋"):
                    st.info("""
                            以下是您当前存档的 Best50 数据，所有字段均为只读，无法修改，请前往「自定义 Best50 数据」页进行修改。
                            
                            **数据字段说明：**
                            - **曲目 ID**：曲目的唯一标识，影响生成的文件名
                            - **曲名/曲师**：歌曲的基本信息
                            - **等级**：歌曲难度等级（1.0-20.0）
                            - **等级索引**：2=EXPERT(红), 3=MASTER(紫), 4=ULTIMA(黑)
                            - **下版本等级**：下一版本中的难度等级（如使用国际服数据则此参数与当前定数相同）
                            - **分数**：您的成绩（0-1010000）
                            - **Rating**：单曲Rating值
                            - **Combo 类型**：fullcombo 或 alljustice
                            - **Chain 类型**：fullchain 或 fullchain2
                            - **剪辑 ID**：格式为 [类型]_[序号]，如 Best_1
                            - **游玩次数**：游玩该曲目的次数
                            """, icon="ℹ️")
                    
                    # 显示数据表格（只读模式）
                    st.dataframe(
                        st.session_state.processed_data,
                        column_config={
                            "id": st.column_config.NumberColumn("曲目 ID", width="small", help="曲目的唯一标识", disabled=True),
                            "song_name": st.column_config.TextColumn("曲名", width="medium", disabled=True),
                            "artist": st.column_config.TextColumn("曲师", width="medium", disabled=True),
                            "level": st.column_config.NumberColumn("等级", min_value=1.0, max_value=20.0, step=0.1, format="%.1f", width="small", disabled=True),
                            "level_index": st.column_config.NumberColumn("等级索引", min_value=2, max_value=4, step=1, width="small", help="2=EXPERT(红), 3=MASTER(紫), 4=ULTIMA(黑)", disabled=True, format="%d"),
                            "level_next": st.column_config.NumberColumn("下版本等级", min_value=1.0, max_value=20.0, step=0.1, format="%.1f", width="small", disabled=True),
                            "score": st.column_config.NumberColumn("分数", min_value=0, max_value=1010000, step=100, width="small", disabled=True, format="%d"),
                            "rating": st.column_config.NumberColumn("Rating", min_value=0.0, max_value=20.0, step=0.01, format="%.2f", width="small", disabled=True),
                            "full_combo": st.column_config.TextColumn("Combo 类型", width="small", disabled=True),
                            "full_chain": st.column_config.TextColumn("Chain 类型", width="small", disabled=True),
                            "clip_id": st.column_config.TextColumn("剪辑 ID", width="small", disabled=True),
                            "play_count": st.column_config.NumberColumn("游玩次数", width="small", min_value=0, step=1, disabled=True, format="%d")
                        },
                        hide_index=True,  # 不显示行号
                        width='stretch'
                    )
                
                # 数据统计卡片（始终显示）
                st.caption("📈 数据概览")
                current_data = st.session_state.processed_data
                stats_col1, stats_col2, stats_col3, stats_col4, stats_col5, stats_col6 = st.columns(6)
                
                with stats_col1:
                    total_records = len(current_data)
                    st.metric("总记录数", total_records)
                
                with stats_col2:
                    expert_count = sum(1 for item in current_data if item.get('level_index') == 2)
                    st.metric("EXPERT 数", expert_count)
                
                with stats_col3:
                    master_count = sum(1 for item in current_data if item.get('level_index') == 3)
                    st.metric("MASTER 数", master_count)
                        
                with stats_col4:
                    ultima_count = sum(1 for item in current_data if item.get('level_index') == 4)
                    st.metric("ULTIMA 数", ultima_count)
                    
                with stats_col5:
                    hardest_level = max((item.get('level', 0) for item in current_data), default=0)
                    st.metric("最难曲目等级", f"{hardest_level:.1f}")
                    
                with stats_col6:
                    highest_rating = max((item.get('rating', 0) for item in current_data), default=0)
                    st.metric("最高单曲 ra", f"{highest_rating:.2f}")
                        
            except Exception as e:
                st.error(f"加载数据失败: {e}", icon="❌")
### Data Viewing Section - End ###

    st.divider()
    if data_loaded:
        image_path = current_paths['image_dir']
        with st.container(border=False):
            st.text("确认存档数据无误后，即可生成您的 Best50 显示图像（将用您上面的数据生成）")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("生成成绩图底图", help="使用 1920 × 1080 生成", icon="🔄️", width='stretch'):
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
                            """, width='stretch', icon="📂"):
                    open_file_explorer(absolute_path)

            col1, col2 = st.columns([2, 1], vertical_alignment="center")
            with col1:
                st.info("如果已经生成过底图，且无需更新，可以跳过。", icon="ℹ️")
            
            with col2:
                if st.button("下一步", icon="➡️", width='stretch'):
                    st.switch_page("st_pages/2_Search_For_Videos.py")