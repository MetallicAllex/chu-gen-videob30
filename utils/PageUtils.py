import re, subprocess
from decimal import ROUND_HALF_UP, Decimal
from concurrent.futures import ThreadPoolExecutor
from utils.Variables import CHUNI_COMBO_TYPES, LEVEL_LABELS, REVERSE_LEVEL_LABELS

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
                "level": song.get(fields["level"], None),
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
            else:
                print(f"提示：未找到［{processed_song['song_name']}］的国服曲师信息")
            
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

# def _process_intl_data(b50_data, fields, best_or_new, song_db, jp_song_db):
#     """处理国际服数据 - 需要计算rating，依赖日服定数"""
#     processed_data = []
    
#     def process_intl_song(song, i):
#         try:
#             # 生成clip_id
#             if best_or_new == "仅旧曲":
#                 clip_id = f"Best_{i + 1}"
#             elif best_or_new == "仅新曲":
#                 clip_id = f"New_{i + 1}"
#             else:
#                 clip_id = f"Best_{i + 1}" if i < 30 else f"New_{i - 29}"
            
#             # 基础信息提取
#             processed_song = {
#                 "clip_id": clip_id,
#                 "id": song[fields["id"]],
#                 "song_name": song[fields["song_name"]],
#                 "artist": None,
#                 "score": song[fields["score"]],
#                 "rating": None,  # 国际服需要计算
#                 "level": None,
#                 "level_next": None,
#                 "level_index": LEVEL_LABELS[song[fields["level_index"]].upper()],
#                 "full_combo": CHUNI_COMBO_TYPES[2] if song.get("isAllJustice") else (CHUNI_COMBO_TYPES[1] if song.get("isFullCombo") else CHUNI_COMBO_TYPES[0]),
#                 "full_chain": song.get(fields["fchain"]),
#                 "play_count": None
#             }
            
#             # 优先从国服数据库匹配曲师信息
#             song_info = next((item for item in song_db if item.get("title") == processed_song["song_name"]), None)
#             if song_info:
#                 processed_song["artist"] = song_info["artist"]
            
#             # 从日服数据库获取定数并计算rating（国际服核心逻辑）
#             jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
#             if jp_song_info:
#                 level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
#                 if level_label and level_label in jp_song_info["data"]:
#                     difficulty_data = jp_song_info["data"][level_label]
#                     processed_song["level"] = difficulty_data["const"]
#                     processed_song["level_next"] = difficulty_data["const"]
#                     processed_song["rating"] = calculate_rating(song[fields["score"]], processed_song["level"])
#                     print(f"［国际服］使用日服定数 {processed_song['level']} 计算 rating = {processed_song['rating']}")
#                 else:
#                     print(f"警告：【{processed_song['song_name']}】未找到 {level_label} 难度")
#             else:
#                 print(f"警告：未找到【{processed_song['song_name']}】的日服信息，无法计算rating")
#                 # 备用方案
#                 processed_song["level"] = "N/A"
#                 processed_song["level_next"] = "N/A"
#                 processed_song["rating"] = 0
            
#             return processed_song
            
#         except Exception as e:
#             print(f"处理国际服曲目 {i} 时出错: {e}")
#             return None
    
#     # 多线程处理
#     with ThreadPoolExecutor() as executor:
#         futures = [executor.submit(process_intl_song, song, i) for i, song in enumerate(b50_data)]
#         for future in futures:
#             if result := future.result():
#                 processed_data.append(result)
    
#     return processed_data

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
                "full_combo": CHUNI_COMBO_TYPES[2] if song.get("isAllJustice") else (CHUNI_COMBO_TYPES[1] if song.get("isFullCombo") else CHUNI_COMBO_TYPES[0]),
                "full_chain": song.get(fields["fchain"]),
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
                        print(f"［国际服］使用国服数据 - 曲师: {processed_song['artist']}, 定数: {processed_song['level']} - {processed_song['song_name']}")
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
                            print(f"［国际服］使用日服数据 - 曲师: {processed_song['artist']}, 定数: {processed_song['level']} - {processed_song['song_name']}")
                        else:
                            print(f"警告：【{processed_song['song_name']}】未找到 {level_label} 难度")
                else:
                    print(f"警告：未找到【{processed_song['song_name']}】的日服信息")
            
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