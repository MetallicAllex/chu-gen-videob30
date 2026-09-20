import re
import zlib
import pandas as pd
import streamlit as st
from datetime import datetime
from utils.PageUtils import calculate_rating
from utils.PathUtils import get_data_paths, get_user_versions, load_config
from utils.DataUtils import load_config_with_types, save_song_data, _load_optional_json
from utils.Variables import REVERSE_LEVEL_LABELS, CHUNI_COMBO_TYPES, CHUNI_CHAIN_TYPES, music_info_path, jp_music_info_path, intl_music_info_path

st.title("编辑 Best50 数据")

SORT_FIELDS = {
    "曲目 ID": "id",
    "等级（当前版本）": "level",
    "等级（下版本）": "level_next",
    "分数": "score",
    "Rating": "rating",
}

def sort_b50_rows(rows, field, descending, group_by_prefix):
    """按所选字段重排。勾选分组时同前缀（Best / New / …）聚成一组，组内按该字段排"""
    key = SORT_FIELDS[field]

    def sort_key(item):
        # 分组只决定"谁跟谁一伙"，组间顺序始终按前缀名顺排（Best → New → PickUp），
        # 跟着方向翻转会让 b30 整组跑到 n20 后面去
        prefix = ()
        if group_by_prefix:
            clip_id = str(item.get('clip_id', ''))
            head, _, tail = clip_id.rpartition('_')
            prefix = (head if tail.isdigit() else clip_id,)
        try:
            value = float(item.get(key) or 0)     # 手填的存档里可能是数字串或空值
        except (TypeError, ValueError):
            value = 0.0
        return (*prefix, -value if descending else value)

    # 稳定排序：数值相同的曲目保持它们原本的相对顺序
    return sorted(rows, key=sort_key)

def difficulty_label(level_index):
    """难度标签：手填或导入的存档里 level_index 可能是字符串、也可能越界，别让一个 KeyError 掀掉整块编辑器"""
    return REVERSE_LEVEL_LABELS.get(level_index, f"#{level_index}")

def duplicate_clip_ids(rows):
    """重复的剪辑 ID 会撞成同一个底图文件名，出图那步「已存在则跳过」会让第二条静默复用第一条"""
    seen, dups = set(), set()
    for row in rows:
        clip_id = row.get('clip_id')
        if clip_id in seen:
            dups.add(clip_id)
        else:
            seen.add(clip_id)
    return sorted(dups)

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
                        # 换存档要连已加载的数据一起丢：只置 editing_data_loaded=False 的话，
                        # 下次「加载数据」会因为 editing_b50_data 还在而直接沿用上一份存档的成绩
                        for stale_key in ('editing_b50_data', 'processed_data', 'viewing_b50_data',
                                          'data_editor', 'sortable_items', 'sort_signature'):
                            st.session_state.pop(stale_key, None)
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
        if 'sortable_items' not in st.session_state:
            st.session_state.sortable_items = []
        
        # 数据管理按钮
        col1, col2, col3 = st.columns(3)
        
        if not st.session_state.editing_data_loaded:
            if st.button("加载数据", width='stretch', type="primary", icon="📥", help="如果您需要修改，请「加载数据」"):
                st.session_state.editing_data_loaded = True
                st.session_state.editing_enabled = False
                st.session_state.sortable_items = []  # 重置 sortable_items
                st.rerun()
        else:
            with col1:
                if st.button("卸载数据", width='stretch', icon="📤", help="如果您已修改完成或不需要修改，请「卸载数据」"):
                    st.session_state.editing_data_loaded = False
                    st.session_state.editing_enabled = False
                    # 排序控件也要一起清：只清 sort_signature 的话，sort_field 还留着上次选的字段，
                    # 下次进到这里就被判定成"组合变了"，在用户没操作的情况下白重排并写盘一次
                    for stale_key in ('editing_b50_data', 'sort_signature',
                                      'sort_field', 'sort_direction', 'group_prefix'):
                        st.session_state.pop(stale_key, None)
                    st.session_state.sortable_items = []  # 清空而不是删除
                    st.rerun()
        
        with col2:
            if st.session_state.editing_data_loaded and st.session_state.editing_enabled:
                if st.button("锁定", width='stretch', icon="🔒", help="将表格设置为只读，防止误修改"):
                    st.session_state.editing_enabled = False
                    st.rerun()
            elif st.session_state.editing_data_loaded and not st.session_state.editing_enabled:
                if st.button("解锁", width='stretch', icon="🔓", help="解除只读状态"):
                    st.session_state.editing_enabled = True
                    st.rerun()
        
        with col3:
            if st.session_state.editing_data_loaded:
                if st.button("重新加载", width='stretch', icon="🔄", help="（如果您的数据已更新或显示异常）"):
                    # viewing_b50_data 也一起作废：图页拿它当自己的缓存，留着就还在显示旧内容
                    for k in ['editing_b50_data', 'processed_data', 'viewing_b50_data',
                              'data_editor', 'sort_signature',
                              'sort_field', 'sort_direction', 'group_prefix']:
                        st.session_state.pop(k, None)
                    st.session_state.sortable_items = []
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
                
                b50_data = st.session_state.editing_b50_data
                
                # ========== 排序控制器（结果直接写入存档文件）==========
                with st.expander("排序设置", expanded=False, icon="↕️"):
                    st.info("""
                            列表顺序就是图像与视频的生成顺序（从下到上）。
                            排序会**立即写入存档文件**，只改变本存档内成绩的先后。
                            没有手工添加过曲目时，[Rating] + [前缀分组] + [降序] 就是建档时的原始顺序；
                            想彻底回到取数那一刻，请到「获取 / 管理存档」重新获取一份存档。
                            """, icon="ℹ️")
                    sort_disabled = not st.session_state.editing_enabled
                    
                    sort_method = st.radio(
                        "排序方法",
                        ["预设排序", "手动拖拽"],
                        captions=["使用您的游戏数据中已定义的字段进行排序", "由您自己拖拽数据中的曲目列表进行手动排序"],
                        help="选择排序的操作方式",
                        key="sort_method",
                        index=0, horizontal=True,
                        disabled=sort_disabled
                    )
                    
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
                                sort_direction = "降序"
                                
                        with col_group:
                            # 如果不是默认模式，显示分组选项
                            if sort_field != "默认（不排序）":
                                group_by_prefix = st.checkbox(
                                    "按前缀分组",
                                    value=True,
                                    help="相同前缀（Best, New 之类）曲目聚在一起，组内仍按所选字段排序",
                                    key="group_prefix",
                                    disabled=sort_disabled
                                )
                            else:
                                st.caption("不分组")
                                group_by_prefix = False

                        # ========== 排序即落盘 ==========
                        # 判断"控件组合变了没有"必须跟一个不绑定 widget 的键比：
                        # 绑定 widget 的键在本轮控件实例化之前就已经是新值了，
                        # 拿它自己跟自己比永远相等（旧代码就是这么失效的）。
                        signature = (sort_field, sort_direction, group_by_prefix)
                        if sort_disabled:
                            st.error("排序设置当前已被禁用，如需修改请「解锁」", icon="🚫")
                        elif sort_field == "默认（不排序）":
                            st.session_state.sort_signature = signature
                            st.caption("💡 保持存档文件里的当前顺序（不进行排序）")
                        elif signature != st.session_state.get('sort_signature'):
                            if save_song_data(
                                    sort_b50_rows(b50_data, sort_field, sort_direction == "降序", group_by_prefix),
                                    current_paths,
                                    f"已按 [{sort_field}] {sort_direction}"
                                    f"{'（前缀分组）' if group_by_prefix else ''}重排并保存",
                                    should_rerun=False):
                                # 签名只代表"文件里现在是这个顺序"：写失败就不记，下次重跑自然重试
                                st.session_state.sort_signature = signature
                        else:
                            col_stat1, col_stat2 = st.columns([1, .65], gap="large")
                            with col_stat1:
                                st.caption(f"💡 存档当前顺序：以 [{sort_field}] 进行 "
                                           f"{'[前缀分组] ' if group_by_prefix else ''}{sort_direction}")
                            with col_stat2:
                                if group_by_prefix:
                                    st.caption("✅ 相同前缀曲目聚为一组，组内按该字段排序")
                                else:
                                    st.caption("⚠️ 不同前缀曲目将穿插排序")
                
                # 排序可能已经换掉了 session_state 里的那份列表，下面的编辑器要用新顺序
                b50_data = st.session_state.editing_b50_data
                
                # ========== 拖拽排序面板（当选择手动拖拽时显示）==========
                if sort_method == "手动拖拽" and not st.session_state.editing_enabled:
                    # 这个分支原本不存在：面板要求已解锁，而下面的编辑器只认"预设排序"，
                    # 锁定 + 手动拖拽 两个条件都不成立，整块编辑器就凭空消失了
                    st.info("拖拽排序属于修改，需要先「解锁」才能使用。", icon="🔒")
                elif sort_method == "手动拖拽":
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
                            for i, item in enumerate(b50_data):
                                song_name = item.get('song_name', f'歌曲{i+1}')
                                level = item.get('level', 0)
                                level_index = item.get('level_index', 3)
                                score = item.get('score', 0)
                                rating = item.get('rating', 0)
                                clip_id = item.get('clip_id', 'Best_1')
                                label = difficulty_label(level_index)
                                
                                display_str = f"#{i+1}({clip_id}) | {song_name}[{label},{level}] | {score:,} | Rating:{rating:.2f}"
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
                                # 处理排序结果：#序号 是建 sortable_items 时写入的下标
                                sorted_records = []
                                for tag in sorted_items:
                                    match = re.search(r'#(\d+)', tag)
                                    if match:
                                        original_index = int(match.group(1)) - 1
                                        if 0 <= original_index < len(b50_data):
                                            sorted_records.append(b50_data[original_index])
                                    else:
                                        st.warning(f"无法解析排序项: {tag}")
                                
                                if len(sorted_records) != len(b50_data):
                                    # 有条目没解析回来的话，"应用"就是拿一份少了曲目的列表去覆盖存档
                                    st.error(f"拖拽结果只有 {len(sorted_records)} 条，与存档的 {len(b50_data)} 条对不上，"
                                             f"已拒绝保存。请点「重置拖拽排序」后重试。", icon="🚫")
                                else:
                                    # 拖拽排序操作按钮
                                    col_drag1, col_drag2 = st.columns([1, 1])
                                    with col_drag1:
                                        if st.button("应用并保存拖拽排序", width='stretch', type="primary", 
                                                help="将拖拽排序结果应用到数据并保存到文件", icon="💾"):
                                            save_song_data(sorted_records, current_paths, "拖拽顺序已保存到文件")
                                            # 现在存档的顺序就是刚拖好的顺序，预设排序那组控件要清回
                                            # "不排序"，否则下次进到这里会拿上次的字段选择把它冲掉
                                            for k in ('sort_signature', 'sort_field', 'sort_direction', 'group_prefix'):
                                                st.session_state.pop(k, None)
                                    
                                    with col_drag2:
                                        if st.button("🔄 重置拖拽排序", width='stretch',
                                                   help="放弃本次未保存的拖动，恢复成存档文件里的当前顺序"):
                                            st.session_state.sortable_items = []
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
                        simple_edit, advanced_edit = st.tabs(["简单编辑", "高级编辑"])
                        with simple_edit:

                            # 列表顺序就是存档文件里的顺序（排序已直接落盘，不再另存一份视图）
                            current_data = b50_data
                            
                            if not current_data:
                                st.info("这份存档文件里没有任何成绩记录，请回到「获取 / 管理存档」重新获取，"
                                        "或在「更换 Best50 存档」里选一份有成绩的存档。", icon="ℹ️")
                            else:
                                # ========== 1. 添加新曲目（简化版）==========
                                with st.expander("添加新曲目", expanded=False, icon="➕"):
                                    songs_db = load_config(music_info_path, use_cache=True)
                                    jp_songs_db = load_config(jp_music_info_path, use_cache=True)
                                    intl_songs_db = _load_optional_json(intl_music_info_path) or []

                                    st.markdown("##### 🎯 从数据库选择曲目")
                                    db_source = st.segmented_control(
                                        "数据源", ["国服", "国际服", "日服"], default="国服", key="add_db_source",
                                        help="从不同服务器的数据库中搜索曲目，查看定数对比", width="stretch",
                                        label_visibility="collapsed", selection_mode="single"
                                    )

                                    song_choices = {}
                                    if db_source == "国服":
                                        for s in songs_db:
                                            if any(d["difficulty"] in [2, 3, 4] for d in s.get("difficulties", [])):
                                                song_choices[f"{s['title']} - {s['artist']}"] = ("cn", s)
                                    elif db_source == "日服":
                                        for s in jp_songs_db:
                                            title = s["meta"]["title"]
                                            artist = s["meta"].get("artist", "")
                                            song_choices[f"{title} - {artist}"] = ("jp", s)
                                    else:
                                        for s in intl_songs_db:
                                            song_choices[f"{s['title']} - {s['artist']}"] = ("intl", s)
                                    choice_list = sorted(song_choices.keys())

                                    selected_label = st.selectbox(
                                        "搜索曲名或曲师", options=choice_list, key="add_song_search",
                                        placeholder="输入曲名或曲师搜索...", label_visibility="collapsed",
                                        index=None
                                    )

                                    if selected_label and selected_label in song_choices:
                                        stype, song = song_choices[selected_label]

                                        cn_song = jp_song = intl_song = None
                                        title = artist = ""
                                        if stype == "cn":
                                            cn_song = song
                                            title, artist = cn_song["title"], cn_song["artist"]
                                            jp_song = next((s for s in jp_songs_db if s["meta"]["title"] == title), None)
                                            intl_song = next((s for s in intl_songs_db if s["title"] == title), None)
                                        elif stype == "jp":
                                            jp_song = song
                                            title = jp_song["meta"]["title"]
                                            artist = jp_song["meta"].get("artist", "")
                                            cn_song = next((s for s in songs_db if s["title"] == title), None)
                                            intl_song = next((s for s in intl_songs_db if s["title"] == title), None)
                                        else:
                                            intl_song = song
                                            title, artist = intl_song["title"], intl_song["artist"]
                                            cn_song = next((s for s in songs_db if s["title"] == title), None)
                                            jp_song = next((s for s in jp_songs_db if s["meta"]["title"] == title), None)

                                        diff_rows = []
                                        for label in ["EXPERT", "MASTER", "ULTIMA"]:
                                            cn_val = None
                                            if cn_song:
                                                li = {"EXPERT": 2, "MASTER": 3, "ULTIMA": 4}[label]
                                                cn_d = next((d for d in cn_song["difficulties"] if d["difficulty"] == li), None)
                                                cn_val = cn_d["level_value"] if cn_d else None
                                            jp_val = jp_song["data"][label]["const"] if jp_song and label in jp_song.get("data", {}) else None
                                            intl_val = float(intl_song["difficulty"][label]) if intl_song and label in intl_song.get("difficulty", {}) else None
                                            if any(v is not None for v in [cn_val, intl_val, jp_val]):
                                                diff_rows.append({
                                                    "难度": label, "国服": cn_val or "—",
                                                    "国际服": intl_val or "—" ,"日服": jp_val or "—"
                                                })

                                        _diff_opts = []
                                        if stype == "cn":
                                            _diff_opts = sorted([d["difficulty"] for d in cn_song["difficulties"] if d["difficulty"] in [2, 3, 4]])
                                        elif stype == "jp":
                                            _m = {"EXPERT": 2, "MASTER": 3, "ULTIMA": 4}
                                            _diff_opts = sorted([_m[k] for k in _m if k in jp_song.get("data", {})])
                                        else:
                                            _m = {"EXPERT": 2, "MASTER": 3, "ULTIMA": 4}
                                            _diff_opts = sorted([_m[k] for k in _m if k in intl_song.get("difficulty", {})])
                                        col_info, col_table = st.columns([1, 1.5], vertical_alignment="center")
                                        with col_info:
                                            st.markdown(f"**{title}**  ")
                                            st.caption(f"曲师: {artist}")
                                            _pv_li = st.session_state.get("qal_li", _diff_opts[0] if _diff_opts else 3)
                                            _pv_sc = st.session_state.get("qal_sc", 1000000)
                                            _pv_lbl = REVERSE_LEVEL_LABELS[_pv_li]
                                            if stype == "cn":
                                                _pv_lv = next((d["level_value"] for d in cn_song["difficulties"] if d["difficulty"] == _pv_li), 13.0)
                                            elif stype == "jp":
                                                _pv_lv = jp_song["data"].get(_pv_lbl, {}).get("const", 13.0)
                                            else:
                                                _pv_intl = intl_song["difficulty"].get(_pv_lbl)
                                                _pv_lv = float(_pv_intl) if _pv_intl else 13.0
                                            st.caption(f"Rating = **{calculate_rating(_pv_sc, _pv_lv):.2f}** @ Lv.{_pv_lv}")
                                        with col_table:
                                            st.dataframe(diff_rows, hide_index=True, width='stretch')

                                        st.divider()
                                        col_a, col_b, col_c = st.columns([1.2, 1.5, 1])
                                        with col_a:
                                            li = st.selectbox(
                                                "难度", _diff_opts, key="qal_li",
                                                format_func=lambda x: REVERSE_LEVEL_LABELS[x]
                                            )
                                        with col_b:
                                            sc = st.number_input("分数", 0, 1010000, 1000000, 1000, key="qal_sc")
                                        with col_c:
                                            pc = st.number_input("游玩次数(可选)", 0, value=0, step=1, key="qal_pc")

                                        max_num = 0
                                        for item in current_data:
                                            cid = item.get('clip_id', '')
                                            parts = cid.split('_')
                                            if len(parts) == 2 and parts[1].isdigit():
                                                max_num = max(max_num, int(parts[1]))
                                        clip_id_default = f"PickUp_{max_num + 1}"
                                        col_d, col_e, col_f = st.columns(3)
                                        with col_d:
                                            clip_id_input = st.text_input(
                                                "剪辑 ID", value=clip_id_default, key="qal_clip_id",
                                                help="格式: 前缀_序号, 如 PickUp_1, Best_1, New_1"
                                            )
                                            if not re.match(r"^[a-zA-Z]+_[0-9]+$", clip_id_input):
                                                st.warning("格式: 前缀_序号", icon="⚠️")
                                        with col_e:
                                            qal_combo = st.selectbox(
                                                "Combo 类型", CHUNI_COMBO_TYPES, key="qal_combo",
                                                format_func=lambda x: "无" if x is None else x, help="AJC 请同时将分数填写为 1010000"
                                            )
                                        with col_f:
                                            qal_chain = st.selectbox(
                                                "Chain 类型", CHUNI_CHAIN_TYPES, key="qal_chain",
                                                format_func=lambda x: "无" if x is None else x, help="fullchain = 拼机全连，fullchain2 = 拼机 AJ(C)"
                                            )

                                        lbl = REVERSE_LEVEL_LABELS[li]
                                        if stype == "cn":
                                            lv = next((d["level_value"] for d in cn_song["difficulties"] if d["difficulty"] == li), 13.0)
                                            lv_next = jp_song["data"][lbl]["const"] if jp_song and lbl in jp_song.get("data", {}) else lv
                                        elif stype == "jp":
                                            jp_d = jp_song["data"].get(lbl, {})
                                            lv = jp_d.get("const", 13.0)
                                            lv_next = next((d["level_value"] for d in cn_song["difficulties"] if d["difficulty"] == li), lv) if cn_song else lv
                                        else:
                                            intl_str = intl_song["difficulty"].get(lbl)
                                            lv = float(intl_str) if intl_str else 13.0
                                            cn_d = next((d for d in cn_song["difficulties"] if d["difficulty"] == li), None) if cn_song else None
                                            lv_next = cn_d["level_value"] if cn_d else lv

                                        auto_rating = calculate_rating(sc, lv)

                                        if st.button("✅ 添加曲目", type="primary", width='stretch',
                                                disabled=not st.session_state.editing_enabled):
                                            if stype == "cn":
                                                song_id = cn_song["id"]
                                            elif stype == "jp":
                                                # 内置 hash() 每个进程带盐（实测同一曲名三次得到三个值），
                                                # 而曲目 ID 决定视频文件名，重启后换名就接不上已下载的视频
                                                song_id = cn_song["id"] if cn_song else \
                                                    zlib.crc32(title.encode("utf-8")) % 9000 + 1000
                                            else:
                                                song_id = int(intl_song["id"])

                                            new_song = {
                                                "id": song_id, "song_name": title,
                                                "artist": artist, "level": lv,
                                                "level_index": li, "level_next": lv_next,
                                                "score": sc, "rating": auto_rating,
                                                "full_combo": qal_combo, "full_chain": qal_chain,
                                                "clip_id": clip_id_input,
                                                "play_count": pc if pc > 0 else None
                                            }
                                            dups = duplicate_clip_ids(current_data + [new_song])
                                            if dups:
                                                st.error(f"剪辑 ID {'、'.join(dups)} 已被其他曲目占用，"
                                                         f"换一个未占用的序号再添加。", icon="🚫")
                                            else:
                                                current_data.append(new_song)
                                                save_song_data(
                                                    current_data, current_paths,
                                                    f"成功添加曲目: {new_song['song_name']} [{REVERSE_LEVEL_LABELS[li]}]"
                                                )
                                
                                # ========== 2. 修改曲目 ==========
                                with st.expander("修改曲目", expanded=False, icon="✏️"):
                                    # 创建曲目选择器
                                    song_options = [f"《{item.get('song_name', '未知')}》 - {item.get('artist', '未知')} (难度：{difficulty_label(item.get('level_index'))})" 
                                                for item in current_data]
                                    
                                    if song_options:
                                        # 使用 session_state 来跟踪当前选中的曲目
                                        if 'selected_song_idx' not in st.session_state:
                                            st.session_state.selected_song_idx = 0
                                        
                                        # 确保索引有效
                                        if st.session_state.get('selected_song_idx') is None or st.session_state.selected_song_idx >= len(current_data):
                                            st.session_state.selected_song_idx = 0
                                        
                                        selected_song_idx = st.selectbox(
                                            "选择曲目",
                                            range(len(song_options)),
                                            placeholder="选择您存档内的曲目",
                                            format_func=lambda x: song_options[x],
                                            key="edit_song_select", index=None
                                        )
                                        
                                        # 更新 session_state
                                        st.session_state.selected_song_idx = selected_song_idx
                                        
                                        if selected_song_idx is not None and 0 <= selected_song_idx < len(current_data):
                                            selected_song = current_data[selected_song_idx]

                                            st.markdown("##### 修改曲目信息")
                                            col_a, col_b, col_c = st.columns([1.2, 1.5, 1])
                                            with col_a:
                                                e_li = st.selectbox(
                                                    "难度", [2, 3, 4], key=f"e_li_{selected_song_idx}",
                                                    format_func=lambda x: REVERSE_LEVEL_LABELS[x],
                                                    index=([2, 3, 4].index(selected_song.get('level_index', 3)) if selected_song.get('level_index') in [2, 3, 4] else 1)
                                                )
                                            with col_b:
                                                e_sc = st.number_input("分数", 0, 1010000, key=f"e_sc_{selected_song_idx}",
                                                    value=int(selected_song.get('score', 1000000)), step=100)
                                            with col_c:
                                                e_lv = st.number_input("等级", 1.0, 20.0, key=f"e_lv_{selected_song_idx}",
                                                    value=float(selected_song.get('level', 13.0)), step=0.1)

                                            col_f, col_g, col_h = st.columns(3)
                                            with col_f:
                                                e_clip = st.text_input("剪辑 ID", key=f"e_clip_{selected_song_idx}",
                                                    value=selected_song.get('clip_id', 'PickUp_1'),
                                                    help="格式: 前缀_序号, 如 PickUp_1")
                                            with col_g:
                                                e_combo = st.selectbox("Combo 类型", CHUNI_COMBO_TYPES, key=f"e_combo_{selected_song_idx}", help="AJC 请同时将分数填写为 1010000",
                                                    index=CHUNI_COMBO_TYPES.index(selected_song.get('full_combo')) if selected_song.get('full_combo') in CHUNI_COMBO_TYPES else 0,
                                                    format_func=lambda x: "无" if x is None else x)
                                            with col_h:
                                                e_chain = st.selectbox("Chain 类型", CHUNI_CHAIN_TYPES, key=f"e_chain_{selected_song_idx}", help="fullchain = 拼机全连，fullchain2 = 拼机 AJ(C)",
                                                    index=CHUNI_CHAIN_TYPES.index(selected_song.get('full_chain')) if selected_song.get('full_chain') in CHUNI_CHAIN_TYPES else 0,
                                                    format_func=lambda x: "无" if x is None else x)

                                            e_rating = calculate_rating(e_sc, e_lv)

                                            if st.button("💾 保存修改", type="primary", width='stretch', help=f"Rating = **{e_rating:.2f} @ Lv.{e_lv}**",
                                                    disabled=not st.session_state.editing_enabled):
                                                edited_song = {
                                                    "id": selected_song.get("id", 9999),
                                                    "song_name": selected_song.get("song_name", ""),
                                                    "artist": selected_song.get("artist", ""),
                                                    "level": e_lv, "level_index": e_li,
                                                    "level_next": float(selected_song.get("level_next", e_lv)),
                                                    "score": e_sc, "rating": e_rating,
                                                    "full_combo": e_combo, "full_chain": e_chain,
                                                    "clip_id": e_clip,
                                                    "play_count": selected_song.get("play_count", None)
                                                }
                                                # 查重得先把这一条换成新值，否则它会跟自己原来的 ID 撞上
                                                preview = (current_data[:selected_song_idx] + [edited_song]
                                                           + current_data[selected_song_idx + 1:])
                                                dups = duplicate_clip_ids(preview)
                                                if dups:
                                                    st.error(f"剪辑 ID {'、'.join(dups)} 与其他曲目重复，请改成一个未占用的。", icon="🚫")
                                                else:
                                                    current_data[selected_song_idx] = edited_song
                                                    save_song_data(
                                                        current_data, current_paths,
                                                        f"成功修改曲目: {edited_song['song_name']}"
                                                    )
                                    else:
                                        st.info("暂无曲目数据", icon="ℹ️")

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
                                                    st.write(f"《**{song.get('song_name')}**》 - {song.get('artist')} (难度：{difficulty_label(song.get('level_index'))})")
                                            
                                            # 删除按钮
                                            col_del_btn1, col_del_btn2, col_del_btn3 = st.columns([1, 2, 1])
                                            with col_del_btn2:
                                                if st.button("确认删除", icon="🗑️", width='stretch', type="primary", disabled=not st.session_state.editing_enabled):
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
                                                            f"成功删除 {len(valid_indices)} 首曲目"
                                                        )
                                                    except Exception as e:
                                                        st.error(f"删除失败: {e}", icon="❌")
                                    else:
                                        st.info("暂无曲目数据", icon="ℹ️")
                                            
                        with advanced_edit:
                            # 表格直接吃 b50_data —— 就是存档文件里那份，与简单编辑同一个列表
                            st.info("""
                                    在表格中直接编辑数据，编辑完成后记得「保存修改」。
                                    
                                    **关于顺序：**
                                    - 表格里的顺序就是存档文件里的顺序（上方「排序设置」一改就写入文件）
                                    - 要逐曲微调顺序请切到"手动拖拽"
                                    - 「排序设置」或简单编辑一落盘，本表格里**还没点「保存修改」的改动会被作废**
                                    - 改了分数或等级后要点「自动计算 Rating」，表格不会替你算
                                    """, icon="ℹ️")
                            
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
                                    "rating": st.column_config.NumberColumn("Rating", min_value=0.0, max_value=20.0, step=0.01, format="%.2f", width="small", required=True, help="计算 Rating 请在简单编辑页计算，或访问[此页](https://public.cm-tea.top/Rating_Calculator_CHUNITHM.html)"),
                                    "full_combo": st.column_config.SelectboxColumn("Combo 类型", width="small", options=[None, "fullcombo", "alljustice"], help="若您的成绩为 1010000，直接选择 alljustice 即可（生成器会自动计算 AJC）"),
                                    "full_chain": st.column_config.SelectboxColumn("Chain 类型", width="small", help="使用水鱼的玩家请自行确定本曲是否已有 Chain（fullchain = 拼机全连，fullchain2 = 拼机 AJ(C)）", options=[None, "fullchain", "fullchain2"]),
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
                                calc_btn, confirm, cancel = st.columns(3)

                                with calc_btn:
                                    if st.button("🧮 自动计算 Rating", width='stretch',
                                            help="根据每首曲目的「分数」和「等级」重新计算 Rating 值"):
                                        if not edited_data:
                                            st.warning("没有可计算的数据", icon="⚠️")
                                        else:
                                            updated = 0
                                            for item in edited_data:
                                                score = item.get('score')
                                                level = item.get('level')
                                                if score is not None and level is not None:
                                                    item['rating'] = calculate_rating(score, level)
                                                    updated += 1
                                            st.session_state.editing_b50_data = edited_data
                                            # 增量状态必须清掉：整表里已经含了新增行，
                                            # 留着 added_rows 会在下一次渲染时把它们再追加一遍
                                            st.session_state.pop("data_editor", None)
                                            st.success(f"已更新 {updated} 首曲目的 Rating！", icon="✅")
                                            st.rerun()

                                with confirm:
                                    if st.button("保存修改", width='stretch', type="primary", icon="💾",
                                            help="保存表格里的数据，顺序按表格当前显示写入存档文件"):
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
                                        
                                        dups = duplicate_clip_ids(cleaned_data)
                                        if dups:
                                            st.error(f"剪辑 ID {'、'.join(dups)} 重复，两条成绩会指向同一张底图。"
                                                     f"请改掉其中一个再保存。", icon="🚫")
                                        else:
                                            # 保存数据
                                            save_song_data(cleaned_data, current_paths, "数据保存成功！")
                                
                                with cancel:
                                    if st.button("放弃修改", width='stretch', icon="🗑️", 
                                            help="丢弃表格里尚未保存的改动，重新读取存档文件"):
                                        st.session_state.editing_b50_data = load_config_with_types(current_paths['data_file'])
                                        st.session_state.pop("data_editor", None)
                                        st.session_state.sortable_items = []  # 清空拖拽缓存
                                        st.success("已放弃未保存的修改", icon="✅")
                                        st.rerun()
                            
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