import pandas as pd
import streamlit as st
from datetime import datetime
from utils.Variables import REVERSE_LEVEL_LABELS
from utils.PathUtils import get_data_paths, get_user_versions, load_config
from utils.PageUtils import render_song_form, calculate_rating
from utils.DataUtils import load_config_with_types, music_info_path, save_config_with_types, save_song_data

st.title("Step 1: 生成 Best50 成绩底图")

# 添加悬停效果CSS（从5_Edit_OpEd_Content.py复制）
st.markdown("""
<style>
/* 基础tabs样式 */
.stTabs {
    width: 100%;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    padding: 2px;
    border-radius: 8px;
}

.stTabs [data-baseweb="tab"] {
    flex: 1;
    text-align: center;
    padding: 10px 0;
    font-weight: 600;
    background-color: transparent;
    color: #666;
    position: relative;
    border: none;
    overflow: hidden;
    z-index: 1;
    transition: color 0.3s ease;
}

/* 当前选中状态 */
.stTabs [aria-selected="true"] {
    color: #ff4b4b;
}

/* 悬停效果 - 从底部填充 */
.stTabs [data-baseweb="tab"]::before {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 0;
    background-color: #ff4b4b;
    z-index: -1;
    transition: height 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    border-radius: 4px 4px 0 0;
}

.stTabs [data-baseweb="tab"]:hover::before {
    height: 100%;
}

.stTabs [data-baseweb="tab"]:hover {
    color: white;
}
</style>
""", unsafe_allow_html=True)

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
                        st.session_state.viewing_data_loaded = False
                        st.session_state.editing_data_loaded = False
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
                        
                        simple_edit, advanced_edit = st.tabs(["简单编辑", "高级编辑"])
                        with simple_edit:
                            # 添加Rating计算器行
                            title, calc_col1, calc_col2, calc_col3 = st.columns([2, 1.25, 1.5, .85], vertical_alignment="center")
                            with title:
                                st.markdown("### 🎵 [Rating 计算器 & 曲目管理](https://public.cm-tea.top/Rating_Calculator_CHUNITHM.html)", unsafe_allow_html=True)
                            with calc_col1:
                                calc_level = st.number_input(
                                    "等级",
                                    min_value=1.0,
                                    max_value=20.0,
                                    value=13.0,
                                    step=0.1,
                                    key="rating_calc_level",
                                    help="输入曲目等级"
                                )
                            
                            with calc_col2:
                                calc_score = st.number_input(
                                    "分数",
                                    min_value=0,
                                    max_value=1010000,
                                    value=1000000,
                                    step=1000,
                                    key="rating_calc_score",
                                    help="输入分数 (0-1010000)"
                                )
                            
                            with calc_col3:
                                # 计算Rating
                                calculated_rating = calculate_rating(calc_score, calc_level)
                                st.metric(
                                    "Rating 值",
                                    f"{calculated_rating:.2f}",
                                    help="根据等级和分数计算出的Rating值"
                                )
                            
                            st.divider()
                            
                            # 获取当前数据
                            current_data = st.session_state.processed_data if 'processed_data' in st.session_state else []
                            
                            if not current_data:
                                st.info("请先在「数据编辑器」标签页加载数据", icon="ℹ️")
                            else:
                                # ========== 1. 添加新曲目 ==========
                                with st.expander("添加新曲目", expanded=False, icon="➕"):
                                    st.markdown("##### 填写新曲目信息（`其中 * 为必填项`）")
                                    # 使用表单组件（添加模式）
                                    form_result = render_song_form(
                                        song_data=None, 
                                        is_edit=False, 
                                        form_key="add_song",
                                        button_text="✅ 添加曲目",
                                        # songs_db=load_config(music_info_path)
                                    )
                                    
                                    if form_result["submitted"]:
                                        new_song_data = form_result["data"]
                                        
                                        # 验证必填字段
                                        if not new_song_data['song_name'] \
                                            and not new_song_data['artist'] \
                                            and not new_song_data['id']\
                                                and not new_song_data['level']\
                                                and not new_song_data['score']\
                                                and not new_song_data['rating']:
                                            st.error("曲名、曲师、 ID、难度等级、分数、rating为必填项！", icon="❌")
                                        else:
                                            # 添加到数据中
                                            current_data.append(new_song_data)
                                            
                                            # 保存数据
                                            save_song_data(
                                                current_data,
                                                current_paths,
                                                f"✅ 成功添加曲目: {new_song_data['song_name']}",
                                                "⚠️ 当前处于只读模式，曲目已添加到内存但未保存，请「解锁」后保存"
                                            )
                                
                                # ========== 2. 修改曲目 ==========
                                with st.expander("修改曲目", expanded=False, icon="✏️"):
                                    st.markdown("##### 选择要修改的曲目")
                                    
                                    # 创建曲目选择器
                                    song_options = [f"《{item.get('song_name', '未知')}》 - {item.get('artist', '未知')} (难度：{REVERSE_LEVEL_LABELS[item.get('level_index', '2')]})" 
                                                for item in current_data]
                                    
                                    if song_options:
                                        # 使用 session_state 来跟踪当前选中的曲目
                                        if 'selected_song_idx' not in st.session_state:
                                            st.session_state.selected_song_idx = 0
                                        
                                        # 确保索引有效
                                        if st.session_state.selected_song_idx >= len(current_data):
                                            st.session_state.selected_song_idx = 0
                                        
                                        selected_song_idx = st.selectbox(
                                            "选择曲目",
                                            range(len(song_options)),
                                            format_func=lambda x: song_options[x],
                                            key="edit_song_select",
                                            index=st.session_state.selected_song_idx
                                        )
                                        
                                        # 更新 session_state
                                        st.session_state.selected_song_idx = selected_song_idx
                                        
                                        if selected_song_idx is not None and 0 <= selected_song_idx < len(current_data):
                                            selected_song = current_data[selected_song_idx]
                                            
                                            st.markdown("##### 修改曲目信息（`其中 * 为基础项`）")
                                            
                                            # 使用表单组件（编辑模式）
                                            # 使用曲目ID和名称作为表单key的一部分，确保唯一性
                                            form_key = f"edit_song_{selected_song_idx}_{selected_song.get('id', 0)}"
                                            form_result = render_song_form(
                                                song_data=selected_song,
                                                is_edit=True, 
                                                form_key=form_key,
                                                button_text="💾 保存修改"
                                            )
                                            
                                            if form_result["submitted"]:
                                                edited_song_data = form_result["data"]
                                                
                                                if not edited_song_data['song_name'] or not edited_song_data['artist']:
                                                    st.error("曲名和曲师不能为空！", icon="❌")
                                                else:
                                                    # 更新曲目信息
                                                    current_data[selected_song_idx] = edited_song_data
                                                    
                                                    # 保存数据
                                                    save_song_data(
                                                        current_data,
                                                        current_paths,
                                                        f"✅ 成功修改曲目: {edited_song_data['song_name']}",
                                                        "⚠️ 当前处于只读模式，修改已应用到内存但未保存，请「解锁」后保存"
                                                    )
                                    else:
                                        st.info("暂无曲目数据", icon="ℹ️")
                                
                                act_col3, act_col4 = st.columns(2)
                                with act_col3:
                                    # ========== 3. 删除曲目 ==========
                                    with st.expander("删除曲目", expanded=False, icon="🗑️"):
                                        st.warning("删除操作不可撤销，请谨慎操作！", icon="⚠️")
                                        
                                        if song_options:
                                            # 多选框支持批量删除
                                            selected_delete_indices = st.multiselect(
                                                "选择要删除的曲目", range(len(song_options)),
                                                placeholder="选择要删除的曲目（支持多选）",
                                                format_func=lambda x: song_options[x], disabled=not st.session_state.editing_enabled,
                                                key="delete_song_select", label_visibility="collapsed"
                                            )
                                            
                                            if selected_delete_indices:
                                                # 显示选中的曲目详情
                                                st.markdown("##### 将删除以下曲目：")
                                                for idx in selected_delete_indices:
                                                    if 0 <= idx < len(current_data):
                                                        song = current_data[idx]
                                                        st.write(f"《**{song.get('song_name')}**》 - {song.get('artist')} (难度：{REVERSE_LEVEL_LABELS[song.get('level_index', '2')]})")
                                                
                                                # 删除按钮
                                                col_del_btn1, col_del_btn2, col_del_btn3 = st.columns([1, 2, 1])
                                                with col_del_btn2:
                                                    if st.button("确认删除", icon="🗑️", width='stretch', type="primary", use_container_width=True, disabled=not st.session_state.editing_enabled):
                                                        try:
                                                            # 从后往前删除，避免索引错误
                                                            valid_indices = [idx for idx in selected_delete_indices if 0 <= idx < len(current_data)]
                                                            for idx in sorted(valid_indices, reverse=True):
                                                                del current_data[idx]
                                                            
                                                            # 重置选中的曲目索引
                                                            if 'selected_song_idx' in st.session_state:
                                                                st.session_state.selected_song_idx = 0
                                                            
                                                            # 保存数据
                                                            save_song_data(
                                                                current_data,
                                                                current_paths,
                                                                f"✅ 成功删除 {len(valid_indices)} 首曲目",
                                                                "⚠️ 当前处于只读模式，删除已应用到内存但未保存，请「解锁」后保存"
                                                            )
                                                        except Exception as e:
                                                            st.error(f"删除失败: {e}", icon="❌")
                                        else:
                                            st.info("暂无曲目数据", icon="ℹ️")
                                
                                with act_col4:
                                    # ========== 批量操作提示 ==========
                                    with st.expander("批量操作提示", expanded=False, icon="💡"):
                                        st.markdown("""
                                        1. **快速添加多首曲目**：
                                        - 在「数据编辑器」标签页使用表格编辑功能
                                        - 可以复制粘贴多行数据
                                        
                                        2. **批量修改**：
                                        - 在「数据编辑器」标签页可以同时编辑多个字段
                                        - 支持Excel风格的批量操作
                                        
                                        3. **数据导入导出**：
                                        - 如需批量导入，请在「数据编辑器」中操作
                                        - 可以从其他文件复制数据后粘贴
                                        
                                        4. **注意事项**：
                                        - 修改后记得点击「保存修改」按钮
                                        - 只读模式下无法保存，请先「解锁」
                                        - 曲目ID建议保持唯一性
                                        """)
                                    
                        with advanced_edit:
                            # 简化会话状态，只保留必要的数据加载状态
                            if 'viewing_data_loaded' not in st.session_state:
                                st.session_state.viewing_data_loaded = False
                            
                            # 只有在加载了数据时才显示表格
                            if st.session_state.viewing_data_loaded:
                                # 加载数据
                                if 'viewing_b50_data' not in st.session_state:
                                    st.session_state.viewing_b50_data = load_config_with_types(current_paths['data_file'])
                                    st.session_state.processed_data = st.session_state.viewing_b50_data.copy()
                                
                                b50_data = st.session_state.viewing_b50_data
                                
                            st.info(f"""
                                    在表格中直接编辑数据，编辑完成后记得「保存修改」。
                                    
                                    **排序说明：**
                                    - 当前使用上方选择的排序方式
                                    - 如需精细调整顺序，请选择"手动拖拽"
                                    - 保存时将按当前显示的顺序存储
                                    
                                    **数据字段说明请指向列头标签查看。**
                                    - 计算 Rating 请在简单编辑页计算，或访问[此页](https://public.cm-tea.top/Rating_Calculator_CHUNITHM.html)
                                    """, icon="ℹ️")
                            
                            # 显示数据编辑器
                            edited_data = st.data_editor(
                                b50_data,
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
                                    "clip_id": st.column_config.TextColumn("剪辑 ID", width="small", required=True, default="PickUp_1", help="按照 [类型]_[序号] 格式添加，如 Best_1", pinned=True, validate="^[a-zA-Z]+_[0-9]+$"),
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
                    # st.caption("📈 数据概览")
                    # current_data = st.session_state.processed_data
                    # stats_col1, stats_col2, stats_col3, stats_col4, stats_col5, stats_col6 = st.columns(6)
                    
                    # with stats_col1:
                    #     total_records = len(current_data)
                    #     st.metric("总记录数", total_records)
                    
                    # with stats_col2:
                    #     expert_count = sum(1 for item in current_data if item.get('level_index') == 2)
                    #     st.metric("EXPERT 数", expert_count)
                    
                    # with stats_col3:
                    #     master_count = sum(1 for item in current_data if item.get('level_index') == 3)
                    #     st.metric("MASTER 数", master_count)
                            
                    # with stats_col4:
                    #     ultima_count = sum(1 for item in current_data if item.get('level_index') == 4)
                    #     st.metric("ULTIMA 数", ultima_count)
                        
                    # with stats_col5:
                    #     hardest_level = max((item.get('level', 0) for item in current_data), default=0)
                    #     st.metric("最难曲目等级", f"{hardest_level:.1f}")
                        
                    # with stats_col6:
                    #     highest_rating = max((item.get('rating', 0) for item in current_data), default=0)
                    #     st.metric("最高单曲 ra", f"{highest_rating:.2f}")
                            
            except Exception as e:
                st.error(f"加载数据失败: {e}", icon="❌")
### Data Editing Section - End ###

# 页面导航
# st.divider()
col_nav1, col_nav2 = st.columns(2)
with col_nav1:
    if st.button("⬅️ 返回首页", width='stretch'):
        st.switch_page("st_pages/0_homepage.py")

with col_nav2:
    if st.button("🎬 继续视频生成", width='stretch'):
        # 根据当前流程决定跳转到哪个页面
        if st.session_state.get('data_updated_step1', False):
            st.switch_page("st_pages/Generate_Pic_Resources.py")
        else:
            st.switch_page("st_pages/1_Setup_Achivments.py")