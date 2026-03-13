import pandas as pd
import streamlit as st
from copy import deepcopy
import os, time, traceback
from datetime import datetime
from utils.DataUtils import load_config_with_types, save_config_with_types
from utils.PageUtils import *
from utils.PathUtils import *
from utils.ImageUtils import generate_single_image
from utils.Variables import REVERSE_LEVEL_LABELS
from concurrent.futures import ThreadPoolExecutor

# def st_generate_b30_images(placeholder, save_paths):
#     b50_data = load_config(save_paths['data_file'])
#     image_path = save_paths['image_dir']
    
#     def worker(index, record_detail):
#         prefix, index = record_detail['clip_id'].split('_', 1)
#         custom_data = load_config(current_paths['custom_style'])
#         try:
#             generate_single_image(
#                 # {"score": str(record_detail['score']), **record_detail},
#                 record_detail,
#                 custom_data,
#                 image_path,
#                 # "Best",
#                 prefix,
#                 int(index)
#             )
#             return True
#         except Exception as e:
#             print(f"生成图片 {index} 失败: {e}")
#             return False

#     with placeholder.container(border=False):
#         start_time = datetime.now()
#         pb = st.progress(0, text="准备开始生成...")
        
#         with ThreadPoolExecutor(max_workers=8) as executor:
#             futures = [executor.submit(worker, i, deepcopy(d)) 
#                     for i, d in enumerate(b50_data)]
            
#             completed = 0
#             while completed < len(b50_data):
#                 new_completed = sum(1 for f in futures if f.done() and f.result())
#                 if new_completed > completed:
#                     completed = new_completed
#                     elapsed = (datetime.now() - start_time).total_seconds()
#                     speed = completed / max(elapsed, 1e-3)  # 防止除零
#                     remaining = (len(b50_data) - completed) / max(speed, 1e-3)
                    
#                     pb.progress(
#                         min(completed / len(b50_data), 1.0),
#                         text=(
#                             f"进度: {completed}/{len(b50_data)}&nbsp; | &nbsp;"
#                             # f"速度: {speed:.1f} 张/秒 | "
#                             f"剩余: {remaining:.1f}秒"
#                         )
#                     )
#                 time.sleep(0.01)
            
#             # 生成完成后清除进度条
#             pb.empty()  # 这行让进度条消失
#             st.toast(f"操作成功完成", icon="✅")

def st_generate_b30_images(placeholder, save_paths):
    b50_data = load_config(save_paths['data_file'])
    image_path = save_paths['image_dir']
    
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
                prefix,
                int(index)
            )
            return "success"
        except Exception as e:
            print(f"生成图片 {index} 失败: {e}")
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
        
        # 统计数据
        stats = {
            'success': 0,
            'failed': 0,
            'skipped': existing_count
        }
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i, d) for i, d in to_generate]
            
            completed = 0
            total_to_generate = len(to_generate)
            
            while completed < total_to_generate:
                new_completed = sum(1 for f in futures if f.done())
                
                if new_completed > completed:
                    completed = new_completed
                    
                    # 更新统计数据
                    for f in futures[:completed]:
                        if f.done():
                            result = f.result()
                            if result == "success":
                                stats['success'] += 1
                            elif result == "failed":
                                stats['failed'] += 1
                    
                    # 计算进度
                    elapsed = (datetime.now() - start_time).total_seconds()
                    speed = completed / max(elapsed, 1e-3)
                    remaining = (total_to_generate - completed) / max(speed, 1e-3)
                    
                    # 更新进度条显示
                    progress_text = (
                        f"进度: {completed}/{total_to_generate} | "
                        f"成功: {stats['success']} | "
                        f"失败: {stats['failed']} | "
                        f"剩余: {remaining:.1f}秒"
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
                summary.append(f"✅ 成功生成: {stats['success']} 张")
            if stats['skipped'] > 0:
                summary.append(f"⏭️ 已跳过: {stats['skipped']} 张")
            if stats['failed'] > 0:
                summary.append(f"❌ 失败: {stats['failed']} 张")
            
            st.info(" | ".join(summary), icon="ℹ️")
            
            if stats['failed'] == 0:
                st.toast("所有图片处理完成！", icon="✅")
            else:
                st.toast(f"处理完成，但有 {stats['failed']} 张生成失败", icon="⚠️")

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
        st.warning("未索引到存档，请先加载存档数据！")

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

### Data Editing Section - Start ###
st.divider()
with st.container(border=True):
    if data_loaded:
        st.subheader("📊 编辑 Best50 数据")
        
        # 初始化会话状态
        if 'editing_data_loaded' not in st.session_state:
            st.session_state.editing_data_loaded = False
        if 'editing_enabled' not in st.session_state:
            st.session_state.editing_enabled = False
        if 'current_sort_field' not in st.session_state:
            st.session_state.current_sort_field = "默认（不排序）"
        if 'is_manual_sorting' not in st.session_state:
            st.session_state.is_manual_sorting = False
        if 'show_manual_sorting_panel' not in st.session_state:
            st.session_state.show_manual_sorting_panel = False
        if 'sortable_items' not in st.session_state:  # 新增：初始化 sortable_items
            st.session_state.sortable_items = []
        
        # 数据管理按钮
        col1, col2, col3 = st.columns(3)
        
        if not st.session_state.editing_data_loaded:
            if st.button("加载数据", width='stretch', type="primary", icon="📥", help="如果您需要修改，请「加载数据」"):
                st.session_state.editing_data_loaded = True
                st.session_state.editing_enabled = False
                st.session_state.is_manual_sorting = False
                st.session_state.show_manual_sorting_panel = False
                st.session_state.sortable_items = []  # 重置 sortable_items
                st.rerun()
        else:
            with col1:
                if st.button("卸载数据", width='stretch', icon="📤", help="如果您已修改完成或不需要修改，请「卸载数据」"):
                    st.session_state.editing_data_loaded = False
                    st.session_state.editing_enabled = False
                    st.session_state.is_manual_sorting = False
                    st.session_state.show_manual_sorting_panel = False
                    if 'editing_b50_data' in st.session_state:
                        del st.session_state.editing_b50_data
                    if 'processed_data' in st.session_state:
                        del st.session_state.processed_data
                    st.session_state.sortable_items = []  # 清空而不是删除
                    st.rerun()
        
        with col2:
            if st.session_state.editing_data_loaded and st.session_state.editing_enabled:
                if st.button("锁定", width='stretch', icon="🔒", help="将表格设置为只读，防止误修改"):
                    st.session_state.editing_enabled = False
                    st.session_state.is_manual_sorting = False
                    st.session_state.show_manual_sorting_panel = False
                    st.rerun()
            elif st.session_state.editing_data_loaded and not st.session_state.editing_enabled:
                if st.button("解锁", width='stretch', icon="🔓", help="解除只读状态"):
                    st.session_state.editing_enabled = True
                    st.rerun()
        
        with col3:
            if st.session_state.editing_data_loaded:
                if st.button("重新加载", width='stretch', icon="🔄", help="（如果您的数据已更新或显示异常）"):
                    if 'editing_b50_data' in st.session_state:
                        del st.session_state.editing_b50_data
                    if 'processed_data' in st.session_state:
                        del st.session_state.processed_data
                    st.session_state.sortable_items = []  # 清空 sortable_items
                    st.session_state.is_manual_sorting = False
                    st.session_state.show_manual_sorting_panel = False
                    st.rerun()
        
        # 状态提示
        if not st.session_state.editing_data_loaded:
            st.info("""
                    「加载数据」以查看和编辑【只读保护数据不被修改】
                    - 请确定您确实需要修改时「解锁」""", icon="💡")
        
        elif not st.session_state.editing_enabled:
            st.warning("当前处于只读模式，任何修改（包括排序）需「解锁」后才能保存", icon="🔒")
        
        # 只有在加载了编辑数据时才显示编辑器
        if st.session_state.editing_data_loaded:
            try:
                # 加载数据
                if 'editing_b50_data' not in st.session_state:
                    st.session_state.editing_b50_data = load_config_with_types(current_paths['data_file'])
                    st.session_state.processed_data = st.session_state.editing_b50_data.copy()
                
                b50_data = st.session_state.editing_b50_data
                
                # ========== 精简排序控制器 ==========
                with st.expander("排序设置", expanded=False, icon="↕️"):
                    st.info("图像和视频生成顺序为从下到上，若需还原请以 [Rating] 进行 [前缀分组降序]", icon="ℹ️")
                    sort_disabled = not st.session_state.editing_enabled
                    
                    # 检测排序模式变化
                    previous_sort_method = st.session_state.get('sort_method', "预设排序")
                    
                    sort_method = st.radio(
                        "排序方法",
                        ["预设排序", "手动拖拽"],
                        captions=["使用您的游戏数据中已定义的字段进行排序", "由您自己拖拽数据中的曲目列表进行手动排序"],
                        help="选择排序的操作方式",
                        key="sort_method",
                        index=0, horizontal=True,
                        disabled=sort_disabled
                    )
                    
                    # 检测排序方法变化
                    if previous_sort_method != sort_method:
                        if sort_method == "手动拖拽":
                            st.session_state.is_manual_sorting = True
                            st.session_state.show_manual_sorting_panel = True
                            st.session_state.current_sort_field = "手动拖拽"
                            # 初始化拖拽项目（确保 sortable_items 已初始化）
                            if not st.session_state.sortable_items:
                                st.session_state.sortable_items = []
                                for i, item in enumerate(st.session_state.processed_data):
                                    song_name = item.get('song_name', f'歌曲{i+1}')
                                    artist = item.get('artist', '未知艺术家')
                                    level = item.get('level', 0)
                                    level_index = item.get('level_index', 3)
                                    score = item.get('score', 0)
                                    rating = item.get('rating', 0)
                                    
                                    # 创建显示字符串
                                    display_str = f"#{i+1} | {song_name}[{REVERSE_LEVEL_LABELS[level_index]}] | Lv.{level} | {score:,} | Rating:{rating:.2f}"
                                    st.session_state.sortable_items.append(display_str)
                        else:
                            st.session_state.is_manual_sorting = False
                            st.session_state.show_manual_sorting_panel = False
                            st.session_state.current_sort_field = "默认（不排序）"
                    
                    if sort_method == "预设排序":
                        # 第一行：基础排序选项
                        col_sort, col_order, col_group = st.columns([.4, .45, .25], vertical_alignment="center")
                        
                        with col_sort:
                            # 排序字段选择
                            sort_field = st.selectbox(
                                "排序依据",
                                ["默认（不排序）", "曲目 ID", "等级（当前版本）", "等级（下版本）", "分数", "Rating"],
                                help="选择排序所需要依据的字段",
                                key="sort_field",
                                index=0, placeholder="默认不排序",
                                disabled=sort_disabled
                            )
                        
                        # 检测模式切换
                        previous_sort_field = st.session_state.get('current_sort_field', "默认（不排序）")
                        if previous_sort_field != sort_field:
                            st.session_state.current_sort_field = sort_field
                            st.session_state.sortable_items = []  # 清除拖拽缓存
                        
                        with col_order:
                            # 如果不是默认模式，显示排序方向选择
                            if sort_field != "默认（不排序）":
                                sort_direction = st.radio(
                                    "排序方向",
                                    ["降序", "升序"],
                                    captions=["从大到小排序", "从小到大排序"],
                                    horizontal=True,
                                    help="生成顺序为从下往上，因此降序为默认选项",
                                    key="sort_direction",
                                    disabled=sort_disabled
                                )
                            else:
                                st.caption("不排序")
                                
                        with col_group:
                            # 如果不是默认模式，显示分组选项
                            if sort_field != "默认（不排序）":
                                group_by_prefix = st.checkbox(
                                    "按前缀分组",
                                    value=True,
                                    help="相同前缀（Best, New 之类）曲目放在一起排序",
                                    key="group_prefix",
                                    disabled=sort_disabled
                                )
                            else:
                                st.caption("不分组")

                        # ========== 自动排序逻辑 ==========
                        if sort_field != "默认（不排序）":
                            # 执行自动排序
                            reverse_order = (sort_direction == "降序")

                            # 字段映射
                            field_map = {
                                "曲目 ID": "id",
                                "等级（当前版本）": "level",
                                "等级（下版本）": "level_next", 
                                "Rating": "rating",
                                "分数": "score",
                            }

                            field_name = field_map[sort_field]

                            # 处理剪辑ID的特殊分组排序
                            if group_by_prefix:
                                def extract_clip_parts(clip_id):
                                    """提取剪辑ID的前缀和数字部分"""
                                    clip_str = str(clip_id)
                                    if '_' in clip_str:
                                        parts = clip_str.split('_')
                                        # 获取最后一个数字部分
                                        for i in range(len(parts)-1, -1, -1):
                                            if parts[i].isdigit():
                                                prefix = '_'.join(parts[:i])
                                                number = int(parts[i])
                                                return prefix, number
                                        # 没有数字部分
                                        return '_'.join(parts[:-1]), 0
                                    return clip_str, 0
                                
                                def clip_sort_key(item):
                                    prefix, number = extract_clip_parts(item.get('clip_id', ''))
                                    
                                    if reverse_order:
                                        # 降序：前缀按字母逆序，数字按数值逆序
                                        # 通过取反ASCII值来实现前缀降序
                                        neg_prefix = tuple(-ord(c) for c in prefix)
                                        return (neg_prefix, -number)
                                    else:
                                        # 升序：前缀按字母顺序，数字按数值顺序
                                        return (prefix, number)
                                
                                sorted_data = sorted(b50_data, key=clip_sort_key)
                                st.session_state.processed_data = sorted_data
                                
                            else:
                                # 常规排序逻辑
                                if field_name in ['id', 'level', 'level_next', 'rating', 'score']:
                                    sorted_data = sorted(
                                        b50_data,
                                        key=lambda x: x.get(field_name, 0),
                                        reverse=reverse_order
                                    )
                                else:
                                    sorted_data = sorted(
                                        b50_data,
                                        key=lambda x: str(x.get(field_name, '')),
                                        reverse=reverse_order
                                    )
                                st.session_state.processed_data = sorted_data

                            # 显示排序状态
                            sort_status = f"💡 当前以 [{sort_field}] 进行 {'[前缀分组' if group_by_prefix else '['}{sort_direction}]"
                            if not sort_disabled:
                                col_stat1, col_stat2 = st.columns([1, .65], gap="large")
                                with col_stat1:
                                    st.caption(sort_status, help="如果想恢复原先的状态，请以 [Rating] 进行 [前缀分组升序]")
                                with col_stat2:
                                    if group_by_prefix:
                                        st.caption("✅ 相同前缀曲目将分组排序")
                                    else:
                                        st.caption("⚠️ 不同前缀曲目将穿插排序")
                            else:
                                st.error("排序设置当前已被禁用，如需修改请「解锁」", icon="🚫")
                        else:
                            # 默认模式：保持原始顺序
                            st.session_state.processed_data = b50_data.copy()
                            if not sort_disabled:
                                st.caption("💡 保持原始顺序（不进行排序）", help="按照数据文件中的原始顺序显示")
                
                # ========== 拖拽排序面板（当选择手动拖拽时显示）==========
                if sort_method == "手动拖拽" and st.session_state.editing_enabled:
                    with st.container(border=True):
                        st.subheader("🧩 拖拽排序面板", divider="rainbow")
                        
                        st.info("""
                                **拖拽排序模式**
                                在此模式下，您可以精细调整每首曲目的显示顺序。
                                
                                **使用说明：**
                                1. 拖动下面的项目来调整顺序
                                2. 图像生成顺序与此面板显示顺序相反（从上往下）
                                3. 调整完成后点击"应用拖拽排序"更新数据
                                4. 完成后选择"预设排序"返回常规编辑
                                """, icon="ℹ️")
                        
                        # 确保 sortable_items 有内容
                        if not st.session_state.sortable_items:
                            st.session_state.sortable_items = []
                            for i, item in enumerate(st.session_state.processed_data):
                                song_name = item.get('song_name', f'歌曲{i+1}')
                                artist = item.get('artist', '未知艺术家')
                                level = item.get('level', 0)
                                level_index = item.get('level_index', 3)
                                score = item.get('score', 0)
                                rating = item.get('rating', 0)
                                clip_id = item.get('clip_id', 'Best_1')
                                
                                display_str = f"#{i+1}({clip_id}) | {song_name}[{REVERSE_LEVEL_LABELS[level_index]},{level}] | {score:,} | Rating:{rating:.2f}"
                                st.session_state.sortable_items.append(display_str)
                        
                        # 使用streamlit-sortables组件
                        try:
                            from streamlit_sortables import sort_items
                            
                            # 自定义样式
                            custom_style = """
                            .sortable-container-body { background-color: transparent; }
                            .sortable-component {
                                border-radius: 10px;
                                min-height: 400px;
                            }
                            .sortable-item {
                                border-radius: 8px;
                                padding: 15px;
                                cursor: grab;
                                transition: all 0.3s;
                                font-size: 14px;
                                box-shadow: 0 3px 6px rgba(0,0,0,0.08);
                            }
                            .sortable-item:hover {
                                border-color: #4da6ff;
                                padding: 15px;
                                transform: translateX(5px);
                                box-shadow: 0 6px 12px rgba(0,0,0,0.12);
                            }
                            .sortable-item.dragging {
                                /*background-color: #e6f2ff;*/
                                border-color: #007bff;
                                padding: 15px;
                                box-shadow: 0 12px 24px rgba(0,0,0,0.2);
                                cursor: grabbing;
                                opacity: .75;
                            }
                            .item-index {
                                display: inline-block;
                                background-color: #4da6ff;
                                color: white;
                                border-radius: 50%;
                                width: 24px;
                                height: 24px;
                                text-align: center;
                                line-height: 24px;
                                margin-right: 10px;
                                font-weight: bold;
                            }
                            """
                            
                            # 显示拖拽排序组件
                            sorted_items = sort_items(
                                items=st.session_state.sortable_items,
                                direction="vertical",
                                custom_style=custom_style
                            )
                            
                            if sorted_items:
                                # 处理排序结果
                                sorted_records = []
                                for tag in sorted_items:
                                    # 提取原始索引
                                    import re
                                    match = re.search(r'#(\d+)', tag)
                                    if match:
                                        original_index = int(match.group(1)) - 1
                                        if 0 <= original_index < len(st.session_state.processed_data):
                                            sorted_records.append(st.session_state.processed_data[original_index])
                                    else:
                                        st.warning(f"无法解析排序项: {tag}")
                                
                                # 拖拽排序操作按钮
                                col_drag1, col_drag2 = st.columns([1, 1])
                                with col_drag1:
                                    if st.button("应用并保存拖拽排序", width='stretch', type="primary", 
                                            help="将拖拽排序结果应用到数据并保存到文件", icon="💾"):
                                        # 更新处理后的数据
                                        st.session_state.processed_data = sorted_records
                                        st.session_state.sortable_items = sorted_items
                                        
                                        # 更新原始数据（保持数据同步）
                                        st.session_state.editing_b50_data = sorted_records.copy()
                                        
                                        # 保存到文件 - 关键修复！
                                        if save_config_with_types(current_paths['data_file'], sorted_records):
                                            st.session_state.editing_b50_data = sorted_records
                                            st.session_state.processed_data = sorted_records.copy()
                                            st.success("拖拽排序已保存到文件！", icon="✅")
                                            st.rerun()
                                
                                with col_drag2:
                                    if st.button("🔄 重置拖拽排序", width='stretch',
                                               help="重置为进入拖拽模式前的顺序"):
                                        # 重新初始化拖拽项目
                                        st.session_state.sortable_items = []
                                        for i, item in enumerate(st.session_state.processed_data):
                                            song_name = item.get('song_name', f'歌曲{i+1}')
                                            artist = item.get('artist', '未知艺术家')
                                            level = item.get('level', 0)
                                            level_index = item.get('level_index', 3)
                                            score = item.get('score', 0)
                                            rating = item.get('rating', 0)
                                            
                                            display_str = f"#{i+1} | {song_name}[{REVERSE_LEVEL_LABELS[level_index]}] | Lv.{level} | {score:,} | Rating:{rating:.2f}"
                                            st.session_state.sortable_items.append(display_str)
                                        st.info("已重置拖拽排序", icon="🔄")
                                        st.rerun()
                        
                        except ImportError:
                            st.error("请先安装 streamlit-sortables: pip install streamlit-sortables")
                            if st.button("安装依赖", key="install_sortables"):
                                import subprocess
                                import sys
                                result = subprocess.run([sys.executable, "-m", "pip", "install", "streamlit-sortables"])
                                if result.returncode == 0:
                                    st.success("安装成功！请刷新页面")
                                    st.rerun()
                                else:
                                    st.error("安装失败，请手动安装")
                    
                    # 在拖拽模式下显示提示信息
                    st.info("""
                            **数据编辑提示**
                            当前处于拖拽排序模式，常规数据编辑功能暂时不可用。
                            
                            要编辑数据内容：
                            1. 在上方"排序设置"中选择"预设排序"
                            2. 然后即可在下方编辑数据
                            """, icon="💡")
                
                # ========== 数据编辑器（只在预设排序模式下显示）==========
                elif sort_method == "预设排序":
                    with st.expander("编辑您的 Best50 数据", icon="📝"):
                        # # 显示当前排序状态
                        # if st.session_state.current_sort_field == "默认（不排序）":
                        #     sort_status = "🔍 原始顺序"
                        # else:
                        #     sort_status = f"📊 {st.session_state.current_sort_field}排序"
                        
                        st.info(f"""
                                在表格中直接编辑数据，编辑完成后记得「保存修改」。
                                
                                **排序说明：**
                                - 当前使用上方选择的排序方式
                                - 如需精细调整顺序，请选择"手动拖拽"
                                - 保存时将按当前显示的顺序存储
                                
                                **数据字段说明请指向列头标签查看。**
                                - 计算 Rating 请访问[此页](https://public.cm-tea.top/Rating_Calculator_CHUNITHM.html)
                                """, icon="ℹ️")
                        
                        # 显示数据编辑器
                        edited_data = st.data_editor(
                            st.session_state.processed_data,
                            column_config={
                                "id": st.column_config.NumberColumn("曲目 ID", width="small", help="""
如果*不知道具体曲目 ID（或不需要迁移数据）*，可以随便填，它只会影响文件名；

反之，如果有迁移数据的需求，请确保`和你要迁移的数据内曲目对应的 ID 一致`
""", required=True, format="%d"),
                                "song_name": st.column_config.TextColumn("曲名", width="medium", required=True),
                                "artist": st.column_config.TextColumn("曲师", width="medium", required=True),
                                "level": st.column_config.NumberColumn("等级", min_value=1.0, max_value=20.0, step=0.1, format="%.1f", width="small", required=True),
                                "level_index": st.column_config.NumberColumn("等级索引", min_value=2, max_value=4, step=1, width="small", help="可填写：2(EXPERT/红)、3(MASTER/紫)、4(ULTIMA/黑)", required=True, format="%d"),
                                "level_next": st.column_config.NumberColumn("下版本等级", min_value=1.0, max_value=20.0, step=0.1, format="%.1f", width="small", required=True),
                                "score": st.column_config.NumberColumn("分数", min_value=0, max_value=1010000, step=100, width="small", required=True, format="%d"),
                                "rating": st.column_config.NumberColumn("Rating", min_value=0.0, max_value=20.0, step=0.01, format="%.2f", width="small", required=True),
                                "full_combo": st.column_config.SelectboxColumn("Combo 类型", width="small", options=[None, "fullcombo", "alljustice"], help="若您的成绩为 1010000，直接选择 alljustice 即可（生成器会自动计算 AJC）"),
                                "full_chain": st.column_config.SelectboxColumn("Chain 类型", width="small", help="使用水鱼的玩家请自行确定本曲是否已有 Chain", options=[None, "fullchain", "fullchain2"]),
                                "clip_id": st.column_config.TextColumn("剪辑 ID", width="small", required=True, default="PickUp_1", help="按照 [类型]_[序号] 格式添加，如 Best_1", pinned=True, validate="^[a-zA-Z]+_+$"),
                                "play_count": st.column_config.NumberColumn("游玩次数", width="small", min_value=0, step=1, help="如果需要填写游玩次数，请输入具体数值（留空即不填充）", format="%d", default=None)
                            },
                            hide_index=True,  # 不显示行号
                            num_rows="dynamic",
                            width='stretch',
                            key="data_editor",
                            disabled=not st.session_state.editing_enabled
                        )
                        
                        # 操作按钮
                        if st.session_state.editing_enabled:
                            confirm, cancel = st.columns(2)
                            
                            with confirm:
                                if st.button("保存修改", width='stretch', type="primary", icon="💾", 
                                           help="保存数据内容和当前排序顺序"):
                                    # 数据类型清理
                                    cleaned_data = []
                                    for item in edited_data:
                                        cleaned_item = {}
                                        for key, value in item.items():
                                            if value is None or (isinstance(value, (int, float)) and pd.isna(value)):
                                                cleaned_item[key] = None
                                            elif key in ['id', 'score', 'level_index', 'play_count'] and value is not None:
                                                cleaned_item[key] = int(value)
                                            elif key in ['level', 'level_next', 'rating'] and value is not None:
                                                cleaned_item[key] = float(value)
                                            else:
                                                cleaned_item[key] = value
                                        cleaned_data.append(cleaned_item)
                                    
                                    # 保存数据
                                    if save_config_with_types(current_paths['data_file'], cleaned_data):
                                        st.session_state.editing_b50_data = cleaned_data
                                        st.session_state.processed_data = cleaned_data.copy()
                                        st.session_state.sortable_items = []  # 清空拖拽缓存
                                        st.session_state.data_edited = True
                                        st.success("数据保存成功！", icon="✅")
                                        st.rerun()
                            
                            with cancel:
                                if st.button("放弃修改", width='stretch', icon="🗑️", 
                                           help="放弃所有修改，恢复原始数据"):
                                    st.session_state.editing_b50_data = load_config_with_types(current_paths['data_file'])
                                    st.session_state.processed_data = st.session_state.editing_b50_data.copy()
                                    st.session_state.sortable_items = []  # 清空拖拽缓存
                                    st.success("已放弃所有修改", icon="✅")
                                    st.rerun()
                
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
### Data Editing Section - End ###

st.divider()
if data_loaded:
    image_path = current_paths['image_dir']
    with st.container(border=True):
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