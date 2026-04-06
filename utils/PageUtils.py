import re, subprocess
import streamlit as st
from decimal import ROUND_HALF_UP, Decimal
from concurrent.futures import ThreadPoolExecutor
from utils.Variables import CHUNI_CHAIN_TYPES, CHUNI_COMBO_TYPES, LEVEL_LABELS, REVERSE_LEVEL_LABELS

def escape_markdown_text(text: str) -> str:
    # 更全面的转义，包括 Streamlit 可能需要的额外字符
    special_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special_chars)}])', r'\\\1', text)

def remove_html_tags_and_invalid_chars(text: str) -> str:
    """去除字符串中的HTML标记和非法字符"""
    # 去除HTML标记
    clean = re.compile('<.*?>')
    text = re.sub(clean, ' ', text)
    
    # 去除非法字符
    invalid_chars = r'[<>:"/\\|?*【】]'  # 定义非法字符
    text = re.sub(invalid_chars, ' ', text)  # 替换为' '

    return text.strip()  # 去除首尾空白字符

def get_ffmpeg_version():
    try:
        # 调用 ffmpeg -version 命令
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              check=True)
        
        # 从输出中提取版本号
        version_match = re.search(r'ffmpeg version (\S+)', result.stdout)
        if version_match:
            return version_match.group(1)
        else:
            return "未找到版本信息"
            
    except FileNotFoundError:
        return "FFmpeg 未安装或不在 PATH 中"
    except subprocess.CalledProcessError as e:
        return f"命令执行错误: {e}"

def format_time_difference(seconds):
    """
    格式化时间差，隐藏为 0 的单位
    """
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_remaining = seconds % 60
    
    parts = []
    
    if hours > 0:
        parts.append(f" {hours} 小时")
    if minutes > 0:
        parts.append(f" {minutes} 分")
    if seconds_remaining > 0 or not parts:  # 如果没有其他单位，至少显示秒
        # 如果有更高级单位，秒取整；否则显示小数
        if parts:
            parts.append(f" {int(seconds_remaining)} 秒")
        else:
            parts.append(f" {seconds_remaining:.2f} 秒")
    
    return "".join(parts)

# Rating 自动计算功能
def calculate_rating(score: int, constant: float) -> float:
    """ CHUNITHM Rating计算（严格遵循官方Wiki规则） """
    if score >= 1_009_000:  # SSS+
        return _truncate(constant + 2.15)
    elif score >= 1_007_500:  # SSS
        delta = ((score - 1_007_500) // 100) * 0.01
        return _truncate(constant + 2.0 + delta)
    elif score >= 1_005_000:  # SS+
        delta = ((score - 1_005_000) // 50) * 0.01
        return _truncate(constant + 1.5 + delta)
    elif score >= 1_000_000:  # SS
        delta = ((score - 1_000_000) // 100) * 0.01
        return _truncate(constant + 1.0 + delta)
    elif score >= 990_000:  # S+ (实际应为 990,000 ~ 999,999)
        delta = ((score - 990_000) // 250) * 0.01
        return _truncate(constant + 0.6 + delta)
    elif score >= 975_000:  # S (975,000 ~ 989,999)
        delta = ((score - 975_000) // 250) * 0.01
        return _truncate(constant + delta)
    elif score >= 950_000:  # AAA
        return _truncate(constant - 1.5)
    elif score >= 925_000:  # AA
        return _truncate(constant - 3.0)
    elif score >= 900_000:  # A
        return _truncate(constant - 5.0)
    elif score >= 800_000:  # BBB
        return _truncate((constant - 5.0) / 2)
    else:  # C/D级
        return 0.0

def _truncate(value: float) -> float:
    """ 强制保留两位小数（直接截断） """
    return float(Decimal(str(value)).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP))

def _process_cn_data(b50_data, fields, best_or_new, song_db, jp_song_db):
    """处理国服数据（水鱼/落雪）- 保持原有逻辑不变"""
    processed_data = []
    
    def process_song(song, i):
        try:
            # 生成clip_id
            if best_or_new == "仅旧曲":
                clip_id = f"Best_{i + 1}"
            elif best_or_new == "仅新曲":
                clip_id = f"New_{i + 1}"
            else:
                clip_id = f"Best_{i + 1}" if i < 30 else f"New_{i - 29}"
            
            # 基础信息提取
            processed_song = {
                "clip_id": clip_id,
                "id": song[fields["id"]],
                "song_name": song[fields["song_name"]],
                "artist": None,
                "score": song[fields["score"]],
                "rating": song[fields["rating"]],  # 直接使用API返回的rating
                "level": None,  # 国服数据中不包含 level
                "level_next": None,
                "level_index": song[fields["level_index"]],
                "full_combo": song.get(fields["fc"], None),
                "full_chain": song.get(fields["fchain"], None) if song.get(fields["fchain"]) not in [None, ""] else None,  # 国服暂不支持full_chain
                "play_count": None
            }
            
            # 从国服数据库匹配曲师信息（只用于补充信息，不影响rating）
            song_info = next((item for item in song_db if str(item.get("id", "")) == str(processed_song["id"])), None)
            if song_info:
                processed_song["artist"] = song_info["artist"]
                for diff in song_info.get("difficulties", []):
                    if diff.get("difficulty") == processed_song["level_index"]:
                        level_value = diff["level_value"]
                        processed_song["level"] = float(level_value) if isinstance(level_value, int) else level_value
                        break
            else:
                print(f"提示：未找到［{processed_song['song_name']}］的国服（曲师，难度）信息")
            
            # 日服数据仅用于获取level_next（可选信息，不影响主要数据）
            jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
            if jp_song_info:
                level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
                if level_label and level_label in jp_song_info["data"]:
                    processed_song["level_next"] = jp_song_info["data"][level_label]["const"]
            
            return processed_song
            
        except Exception as e:
            print(f"处理国服曲目 {i} 时出错: {e}")
            return None
    
    # 多线程处理
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_song, song, i) for i, song in enumerate(b50_data)]
        for future in futures:
            if result := future.result():
                processed_data.append(result)
    
    return processed_data

def _process_intl_data(b50_data, fields, best_or_new, song_db, jp_song_db):
    """处理国际服数据 - 优先使用国服定数，其次使用日服定数"""
    processed_data = []
    
    def process_intl_song(song, i):
        try:
            # 生成clip_id
            if best_or_new == "仅旧曲":
                clip_id = f"Best_{i + 1}"
            elif best_or_new == "仅新曲":
                clip_id = f"New_{i + 1}"
            else:
                clip_id = f"Best_{i + 1}" if i < 30 else f"New_{i - 29}"
            
            # 基础信息提取
            processed_song = {
                "clip_id": clip_id,
                "id": song[fields["id"]],
                "song_name": song[fields["song_name"]],
                "artist": None,      # 曲师：优先国服，其次日服
                "score": song[fields["score"]],
                "rating": None,      # 需要计算
                "level": -1.0,       # 默认-1，后续会检测替换为"--"
                "level_next": -1.0,  # 默认-1
                "level_index": LEVEL_LABELS[song[fields["level_index"]].upper()],
                "full_combo": CHUNI_COMBO_TYPES[2] if song.get("isAllJustice") else (CHUNI_COMBO_TYPES[1] if song.get("isFullCombo") else None),
                "full_chain": CHUNI_CHAIN_TYPES[song.get(fields["fchain"], None)],   
                "play_count": None
            }
            
            # 1. 优先从国服数据库匹配
            song_info = next((item for item in song_db if item.get("title") == processed_song["song_name"]), None)
            if song_info:
                # 匹配曲师
                processed_song["artist"] = song_info["artist"]
                # 匹配定数
                for diff in song_info.get("difficulties", []):
                    if diff.get("difficulty") == processed_song["level_index"]:
                        level_value = diff["level_value"]
                        processed_song["level"] = float(level_value) if isinstance(level_value, (int, float, str)) and str(level_value).replace('.', '').isdigit() else level_value
                        processed_song["level_next"] = processed_song["level"]
                        print(f"［国际服］使用国服数据 - 《{processed_song['song_name']}》【曲师: {processed_song['artist']}, 定数: {processed_song['level']}】")
                        break
            
            # 2. 如果国服匹配失败，尝试日服数据库
            if processed_song["artist"] is None or processed_song["level"] == -1.0:
                jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
                if jp_song_info:
                    # 匹配曲师（日服曲师信息可能在meta中）
                    if processed_song["artist"] is None:
                        processed_song["artist"] = jp_song_info["meta"].get("artist")
                    
                    # 匹配定数
                    if processed_song["level"] == -1.0:
                        level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
                        if level_label and level_label in jp_song_info["data"]:
                            difficulty_data = jp_song_info["data"][level_label]
                            processed_song["level"] = difficulty_data["const"]
                            processed_song["level_next"] = difficulty_data["const"]
                            print(f"［国际服］使用日服数据 - 《{processed_song['song_name']}》【曲师: {processed_song['artist']}, 定数: {processed_song['level']}】")
                        else:
                            print(f"警告：《{processed_song['song_name']}》未找到 {level_label} 难度")
                else:
                    print(f"警告：未找到《{processed_song['song_name']}》的日服信息")
            
            # 3. 计算rating（只要有定数就计算）
            if processed_song["level"] != -1.0:
                processed_song["rating"] = calculate_rating(song[fields["score"]], processed_song["level"])
            else:
                print(f"错误：无法获取【{processed_song['song_name']}】的定数，rating设为0")
                # level保持-1，后续生成界面时会显示为"--"
                processed_song["rating"] = 0
            
            return processed_song
            
        except Exception as e:
            print(f"处理国际服曲目 {i} 时出错: {e}")
            return None
    
    # 多线程处理
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_intl_song, song, i) for i, song in enumerate(b50_data)]
        for future in futures:
            if result := future.result():
                processed_data.append(result)
    
    return processed_data

def render_song_form(song_data=None, is_edit=False, form_key="", button_text=None, auto_calculate_rating=True):
    """
    使用 st.form 渲染曲目信息表单
    
    Args:
        song_data: 曲目数据字典，如果为None则使用默认值（添加模式）
        is_edit: 是否为编辑模式
        form_key: 表单的唯一标识符
        button_text: 按钮文本，如果不指定则根据 is_edit 自动生成
        auto_calculate_rating: 是否自动计算Rating
    
    Returns:
        dict: 包含 submitted (bool) 和 data (dict) 的字典
    """
    if song_data is None:
        # 添加模式的默认值
        song_data = {
            "id": 9999,
            "song_name": "",
            "artist": "",
            "level": 13.0,
            "level_index": 3,
            "level_next": 13.0,
            "score": 1000000,
            "rating": 15.0,
            "full_combo": None,
            "full_chain": None,
            "clip_id": "PickUp_1",
            "play_count": None
        }
    
    # 设置按钮文本
    if button_text is None:
        button_text = "✅ 添加曲目" if not is_edit else "💾 保存修改"
    
    with st.form(key=f"song_form_{form_key}"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            song_name = st.text_input(
                "曲名*", 
                value=song_data.get('song_name', ''),
                placeholder="请输入曲名",
                key=f"song_name_{form_key}"
            )
            artist = st.text_input(
                "曲师*", 
                value=song_data.get('artist', ''),
                placeholder="请输入曲师",
                key=f"artist_{form_key}"
            )
            level = st.number_input(
                "等级*",
                min_value=1.0,
                max_value=20.0,
                value=float(song_data.get('level', 13.0)),
                step=0.1,
                key=f"level_{form_key}",
                help="当前版本的等级"
            )
        
        with col2:
            song_id = st.number_input(
                "曲目ID*",
                min_value=1,
                value=int(song_data.get('id', 9999)),
                step=1,
                key=f"id_{form_key}"
            )
            
            # 安全地设置等级索引的默认值
            level_index_value = song_data.get('level_index', 3)
            level_index_options = [2, 3, 4]
            if level_index_value in level_index_options:
                level_index_default = level_index_options.index(level_index_value)
            else:
                level_index_default = 1  # 默认为 MASTER (紫)
            
            level_index = st.selectbox(
                "等级索引*",
                options=level_index_options,
                format_func=lambda x: {2: "EXPERT (红)", 3: "MASTER (紫)", 4: "ULTIMA (黑)"}[x],
                index=level_index_default,
                key=f"level_index_{form_key}"
            )
            
            score = st.number_input(
                "分数*",
                min_value=0,
                max_value=1010000,
                value=int(song_data.get('score', 1000000)),
                step=1000,
                key=f"score_{form_key}",
                help="分数范围: 0-1010000"
            )
        
        with col3:
            level_next = st.number_input(
                "下版本等级",
                min_value=1.0,
                max_value=20.0,
                value=float(song_data.get('level_next', level)),
                step=0.1,
                key=f"level_next_{form_key}",
                help="下个版本的等级（如果有变化）"
            )
            clip_id = st.text_input(
                "剪辑ID*",
                value=song_data.get('clip_id', 'PickUp_1'),
                placeholder="如: Best_1, New_1",
                key=f"clip_id_{form_key}"
            )
            rating = st.number_input(
                "Rating*",
                min_value=0.0,
                max_value=20.0,
                value=float(song_data.get('rating', 15.0)),
                step=0.01,
                key=f"rating_{form_key}"
            )

        col4, col5, col6 = st.columns(3)
        with col4:
            # 安全地设置 Combo 类型的默认值
            full_combo_value = song_data.get('full_combo')
            full_combo_options = [None, "fullcombo", "alljustice"]
            if full_combo_value in full_combo_options:
                full_combo_index = full_combo_options.index(full_combo_value)
            else:
                full_combo_index = 0
            
            full_combo = st.selectbox(
                "Combo类型",
                options=full_combo_options,
                format_func=lambda x: "无" if x is None else x,
                index=full_combo_index, placeholder="选择一个合适的",
                key=f"full_combo_{form_key}"
            )
        
        with col5:
            # 安全地设置 Chain 类型的默认值
            full_chain_value = song_data.get('full_chain')
            full_chain_options = [None, "fullchain", "fullchain2"]
            if full_chain_value in full_chain_options:
                full_chain_index = full_chain_options.index(full_chain_value)
            else:
                full_chain_index = 0
            
            full_chain = st.selectbox(
                "Chain类型",
                options=full_chain_options,
                format_func=lambda x: "无" if x is None else x,
                index=full_chain_index, placeholder="选择一个合适的",
                key=f"full_chain_{form_key}"
            )
        
        with col6:
            play_count = st.number_input(
                "游玩次数",
                min_value=0,
                value=song_data.get('play_count', 0) or 0,
                step=1,
                key=f"play_count_{form_key}"
            )
        
        # 按钮区域
        col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
        with col_btn2:
            submitted = st.form_submit_button(
                button_text,
                width='stretch',
                type="primary",disabled=not st.session_state.editing_enabled,
                use_container_width=True
            )
        
        return {
            "submitted": submitted,
            "data": {
                "id": song_id,
                "song_name": song_name,
                "artist": artist,
                "level": level,
                "level_index": level_index,
                "level_next": level_next,
                "score": score,
                "rating": rating,
                "full_combo": full_combo,
                "full_chain": full_chain,
                "clip_id": clip_id,
                "play_count": play_count if play_count > 0 else None
            }
        }

# alternative version
# def render_song_form(song_data=None, is_edit=False, form_key="", button_text=None, auto_calculate_rating=True, songs_db=None):
#     """
#     使用 st.form 渲染曲目信息表单（曲名选择器支持别名搜索）
#     """
#     if song_data is None:
#         song_data = {
#             "id": 9999,
#             "song_name": "",
#             "artist": "",
#             "level": 13.0,
#             "level_index": 3,
#             "level_next": 13.0,
#             "score": 1000000,
#             "rating": 15.0,
#             "full_combo": None,
#             "full_chain": None,
#             "clip_id": "PickUp_1",
#             "play_count": None,
#             "aliases": []
#         }
    
#     if button_text is None:
#         button_text = "✅ 添加曲目" if not is_edit else "💾 保存修改"
    
#     # 构建歌曲选项
#     song_options = {}
#     song_display_list = []
    
#     if songs_db:
#         for song in songs_db:
#             name = song.get("title") or song.get("song_name") or song.get("meta", {}).get("title")
#             artist = song.get("artist") or song.get("meta", {}).get("artist")
#             aliases = song.get("aliases", [])
            
#             # 显示文本包含别名
#             display = f"{name} - {artist}"
#             if aliases:
#                 display += f" [{', '.join(aliases)}]"
            
#             song_options[display] = {
#                 "id": song.get("id"),
#                 "name": name,
#                 "artist": artist,
#                 "aliases": aliases,
#             }
#             song_display_list.append(display)
    
#     # 初始化 session_state
#     select_key = f"song_select_{form_key}"
#     selected_song_key = f"selected_song_{form_key}"
    
#     if select_key not in st.session_state:
#         st.session_state[select_key] = None
#     if selected_song_key not in st.session_state:
#         st.session_state[selected_song_key] = None
    
#     # 在 form 外面放置 selectbox 和选择按钮
#     st.markdown("#### 🎵 选择曲目")
    
#     selected_display = st.selectbox(
#         "曲名（支持别名搜索）",
#         options=[""] + song_display_list,
#         key=select_key,
#         placeholder="输入曲名或别名搜索...",
#         help="可以直接输入曲名、曲师或别名进行搜索"
#     )
    
#     # 选择按钮
#     if st.button("✅ 选择此曲目", key=f"select_btn_{form_key}"):
#         if selected_display and selected_display in song_options:
#             st.session_state[selected_song_key] = song_options[selected_display]
#             st.rerun()
    
#     # 显示当前选中的歌曲
#     selected_song = st.session_state[selected_song_key]
#     if selected_song:
#         st.success(f"✅ 已选择: **{selected_song['name']}** - {selected_song['artist']}")
#         if selected_song["aliases"]:
#             st.info(f"🏷️ **别名:** {', '.join(selected_song['aliases'])}")
#     else:
#         st.info("💡 请在上方选择曲目")
    
#     st.markdown("---")
    
#     # 表单部分 - 使用 selected_song 的值
#     with st.form(key=f"song_form_{form_key}"):
#         st.markdown("#### 📝 曲目信息")
        
#         col1, col2, col3 = st.columns(3)
        
#         with col1:
#             # 根据是否有选中的歌曲决定默认值和是否禁用
#             if selected_song:
#                 default_song_name = selected_song["name"]
#                 default_artist = selected_song["artist"]
#                 default_id = selected_song["id"]
#                 is_disabled = True
#             else:
#                 default_song_name = song_data.get('song_name', '')
#                 default_artist = song_data.get('artist', '')
#                 default_id = song_data.get('id', 9999)
#                 is_disabled = False
            
#             song_name = st.text_input(
#                 "曲名*", 
#                 value=default_song_name,
#                 placeholder="请输入曲名",
#                 key=f"song_name_{form_key}",
#                 disabled=is_disabled
#             )
#             artist = st.text_input(
#                 "曲师*", 
#                 value=default_artist,
#                 placeholder="请输入曲师",
#                 key=f"artist_{form_key}",
#                 disabled=is_disabled
#             )
#             level = st.number_input(
#                 "等级*",
#                 min_value=1.0,
#                 max_value=20.0,
#                 value=float(song_data.get('level', 13.0)),
#                 step=0.1,
#                 key=f"level_{form_key}",
#                 help="当前版本的等级"
#             )
        
#         with col2:
#             song_id = st.number_input(
#                 "曲目ID*",
#                 min_value=1,
#                 value=int(default_id),
#                 step=1,
#                 key=f"id_{form_key}",
#                 disabled=is_disabled
#             )
            
#             level_index_value = song_data.get('level_index', 3)
#             level_index_options = [2, 3, 4]
#             if level_index_value in level_index_options:
#                 level_index_default = level_index_options.index(level_index_value)
#             else:
#                 level_index_default = 1
            
#             level_index = st.selectbox(
#                 "等级索引*",
#                 options=level_index_options,
#                 format_func=lambda x: {2: "EXPERT (红)", 3: "MASTER (紫)", 4: "ULTIMA (黑)"}[x],
#                 index=level_index_default,
#                 key=f"level_index_{form_key}"
#             )
            
#             score = st.number_input(
#                 "分数*",
#                 min_value=0,
#                 max_value=1010000,
#                 value=int(song_data.get('score', 1000000)),
#                 step=1000,
#                 key=f"score_{form_key}",
#                 help="分数范围: 0-1010000"
#             )
        
#         with col3:
#             level_next = st.number_input(
#                 "下版本等级",
#                 min_value=1.0,
#                 max_value=20.0,
#                 value=float(song_data.get('level_next', song_data.get('level', 13.0))),
#                 step=0.1,
#                 key=f"level_next_{form_key}",
#                 help="下个版本的等级（如果有变化）"
#             )
#             clip_id = st.text_input(
#                 "剪辑ID*",
#                 value=song_data.get('clip_id', 'PickUp_1'),
#                 placeholder="如: Best_1, New_1",
#                 key=f"clip_id_{form_key}"
#             )
#             rating = st.number_input(
#                 "Rating",
#                 min_value=0.0,
#                 max_value=20.0,
#                 value=float(song_data.get('rating', 15.0)),
#                 step=0.01,
#                 key=f"rating_{form_key}"
#             )

#         col4, col5, col6 = st.columns(3)
#         with col4:
#             full_combo_value = song_data.get('full_combo')
#             full_combo_options = [None, "fullcombo", "alljustice"]
#             if full_combo_value in full_combo_options:
#                 full_combo_index = full_combo_options.index(full_combo_value)
#             else:
#                 full_combo_index = 0
            
#             full_combo = st.selectbox(
#                 "Combo类型",
#                 options=full_combo_options,
#                 format_func=lambda x: "无" if x is None else x,
#                 index=full_combo_index,
#                 key=f"full_combo_{form_key}"
#             )
        
#         with col5:
#             full_chain_value = song_data.get('full_chain')
#             full_chain_options = [None, "fullchain", "fullchain2"]
#             if full_chain_value in full_chain_options:
#                 full_chain_index = full_chain_options.index(full_chain_value)
#             else:
#                 full_chain_index = 0
            
#             full_chain = st.selectbox(
#                 "Chain类型",
#                 options=full_chain_options,
#                 format_func=lambda x: "无" if x is None else x,
#                 index=full_chain_index,
#                 key=f"full_chain_{form_key}"
#             )
        
#         with col6:
#             play_count = st.number_input(
#                 "游玩次数",
#                 min_value=0,
#                 value=song_data.get('play_count', 0) or 0,
#                 step=1,
#                 key=f"play_count_{form_key}"
#             )
        
#         # 按钮区域
#         col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
#         with col_btn2:
#             submitted = st.form_submit_button(
#                 button_text,
#                 width='stretch',
#                 type="primary",
#                 disabled=not st.session_state.editing_enabled,
#                 use_container_width=True
#             )
        
#         # 返回数据
#         if selected_song:
#             final_id = selected_song["id"]
#             final_song_name = selected_song["name"]
#             final_artist = selected_song["artist"]
#             final_aliases = selected_song["aliases"]
#         else:
#             final_id = song_id
#             final_song_name = song_name
#             final_artist = artist
#             final_aliases = song_data.get('aliases', [])
        
#         return {
#             "submitted": submitted,
#             "data": {
#                 "id": final_id,
#                 "song_name": final_song_name,
#                 "artist": final_artist,
#                 "level": level,
#                 "level_index": level_index,
#                 "level_next": level_next,
#                 "score": score,
#                 "rating": rating,
#                 "full_combo": full_combo,
#                 "full_chain": full_chain,
#                 "clip_id": clip_id,
#                 "play_count": play_count if play_count > 0 else None,
#                 "aliases": final_aliases
#             }
#         }