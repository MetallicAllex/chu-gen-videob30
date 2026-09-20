import re, subprocess
import shutil, streamlit as st
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


# ============================================================================
# 片头/片尾文本内联标记
# ============================================================================

# 内联标记关键字 → 对应的片段配置键。写在片头/片尾的文本内容区，
# 用方括号（或中文方括号）整组包裹，如 [静音] [无底图] 或 [静音,无底图]。
# 标记**保留在文本中**（可见、可随时增删），由调用方在保存/渲染时解析。
_OPED_MARKER_KEYWORDS = {
    '静音': 'no_sound',
    '无底图': 'no_overlay',
}
_OPED_MARKER_GROUP_RE = re.compile(r'(\[([^\[\]]*)\]|【([^【】]*)】)')


def parse_oped_text_markers(text: str):
    """解析片头/片尾文本里的内联开关标记，返回 (clean_text, flags)。

    语法：方括号/中文方括号整组包裹的关键字列表，分隔符支持逗号/顿号/
    分号/空白，如 ``[静音]``、``[无底图]``、``[静音,无底图]``。

    规则：
    - 组内每一项都必须是已知关键字，整组才算标记；含任何未知内容
      （如 ``[Chorus]``）的原样保留，不影响正常方括号文本
    - 多组标记取并集；flags 里的布尔值 = 该关键字是否在全文出现
      （未出现 = False，即移除关键字即关闭对应行为）
    - clean_text 为剥离标记后的文本（用于渲染展示图——标记绝不上图）；
      **标记本身保留在原文本中**，调用方按需决定存取
    - 文本里没有任何标记组时，flags 为 None
    """
    if not text:
        return text, None
    found = set()

    def _consume(m: "re.Match") -> str:
        inner = m.group(2) if m.group(2) is not None else m.group(3)
        parts = [p.strip() for p in re.split(r'[,，、;；\s]+', inner) if p.strip()]
        if parts and all(p in _OPED_MARKER_KEYWORDS for p in parts):
            found.update(parts)
            return ''
        return m.group(0)

    clean = _OPED_MARKER_GROUP_RE.sub(_consume, text)
    if not found:
        return text, None
    return clean, {
        'no_overlay': '无底图' in found,
        'no_sound': '静音' in found,
    }

def get_ffmpeg_version():
    try:
        # 调用 ffmpeg -version 命令
        try:  # 没装 GPU 后端时也要能报出版本，这只是个展示用的探测
            from utils.Quadrants.RenderIO import get_ffmpeg_binary
            ffmpeg_bin = get_ffmpeg_binary('ffmpeg')
        except Exception:
            ffmpeg_bin = shutil.which('ffmpeg') or 'ffmpeg'
        result = subprocess.run([ffmpeg_bin, '-version'], 
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

def assign_clip_ids(b50_data, best_or_new, clip_prefixes=None):
    """
    给每条成绩分配 clip_id。

    传入 clip_prefixes（"Best" / "New" / "Select"）时，在各前缀内按原顺序连续编号；
    未传入时沿用旧的全局下标规则，外服上传与历史调用方行为逐字不变。

    旧规则用 `i < 30` 判 b30/n20 边界，依据的是全局下标而非各组实际条数，
    所以一经筛选（b30 只剩 12 条）就会错号 —— 国服筛选链路必须显式传前缀列表。
    """
    if clip_prefixes is None:
        return [
            f"Best_{i + 1}" if best_or_new == "仅旧曲"
            else f"New_{i + 1}" if best_or_new == "仅新曲"
            else (f"Best_{i + 1}" if i < 30 else f"New_{i - 29}")
            for i in range(len(b50_data))
        ]

    counters = {}
    clip_ids = []
    for prefix in clip_prefixes:
        counters[prefix] = counters.get(prefix, 0) + 1
        clip_ids.append(f"{prefix}_{counters[prefix]}")
    return clip_ids

def build_song_indexes(song_db, jp_song_db, intl_song_db):
    """三份曲库的查表索引。国服按 id 对齐（成绩里的 id 与曲库同源），日服与国际服只有曲名可对齐。"""
    return {
        "CN": {str(s.get("id")): s for s in song_db or []},
        "JP": {s["meta"]["title"]: s for s in jp_song_db or [] if isinstance(s.get("meta"), dict)},
        "INT": {s.get("title"): s for s in intl_song_db or []},
    }


def lookup_song_fields(song_id, song_name, level_index, indexes):
    """按当前曲库算出 (artist, levels)。建档与存档回填共用这一份口径，两边不许各写一套匹配规则。"""
    artist = None
    levels = {"CN": None, "JP": None, "INT": None}

    cn_song = indexes["CN"].get(str(song_id))
    if cn_song:
        artist = cn_song["artist"]
        for diff in cn_song.get("difficulties", []):
            if diff.get("difficulty") == level_index:
                level_value = diff["level_value"]
                levels["CN"] = float(level_value) if isinstance(level_value, int) else level_value
                break
    else:
        print(f"提示：未找到［{song_name}］的国服（曲师，难度）信息")

    label = REVERSE_LEVEL_LABELS.get(level_index)
    if label:
        jp_song = indexes["JP"].get(song_name)
        if jp_song and label in jp_song.get("data", {}):
            levels["JP"] = jp_song["data"][label]["const"]
        intl_song = indexes["INT"].get(song_name)
        if intl_song and label in intl_song.get("difficulty", {}):
            try:
                levels["INT"] = float(intl_song["difficulty"][label])
            except (ValueError, TypeError):
                pass

    return artist, levels


def _process_cn_data(b50_data, fields, best_or_new, song_db, jp_song_db, intl_song_db, clip_prefixes=None):
    """处理国服数据（水鱼/落雪）- 保持原有逻辑不变"""
    processed_data = []
    clip_ids = assign_clip_ids(b50_data, best_or_new, clip_prefixes)
    indexes = build_song_indexes(song_db, jp_song_db, intl_song_db)
    
    def process_song(song, i, clip_id):
        try:
            # 基础信息提取
            processed_song = {
                "clip_id": clip_id,
                "id": song[fields["id"]],
                "song_name": song[fields["song_name"]],
                "artist": None,
                "score": song[fields["score"]],
                "rating": song[fields["rating"]],  # 直接使用API返回的rating
                "levels": {"CN": None, "JP": None, "INT": None},  # 三服定数
                "level_index": song[fields["level_index"]],
                "full_combo": song.get(fields["fc"], None),
                "full_chain": song.get(fields["fchain"], None) if song.get(fields["fchain"]) not in [None, ""] else None,  # 国服暂不支持full_chain
                "play_count": None
            }

            # 从曲库补曲师与三服定数（只用于补充信息，不影响rating）
            processed_song["artist"], processed_song["levels"] = lookup_song_fields(
                processed_song["id"], processed_song["song_name"], processed_song["level_index"], indexes)

            return processed_song
            
        except Exception as e:
            print(f"处理国服曲目 {i} 时出错: {e}")
            return None
    
    # 多线程处理
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_song, song, i, clip_ids[i]) for i, song in enumerate(b50_data)]
        for future in futures:
            if result := future.result():
                processed_data.append(result)
    
    return processed_data

def _process_intl_data(b50_data, fields, best_or_new, song_db, jp_song_db, intl_song_db, clip_prefixes=None):
    """处理国际服数据 - 优先使用国服定数，其次使用日服定数"""
    processed_data = []
    clip_ids = assign_clip_ids(b50_data, best_or_new, clip_prefixes)
    
    def process_intl_song(song, i, clip_id):
        try:
            # 基础信息提取
            processed_song = {
                "clip_id": clip_id,
                "id": song[fields["id"]],
                "song_name": song[fields["song_name"]],
                "artist": None,      # 曲师：优先国服，其次日服
                "score": song[fields["score"]],
                "rating": None,      # 需要计算
                "levels": {"CN": None, "JP": None, "INT": None},  # 三服定数
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
                        cn_level = float(level_value) if isinstance(level_value, (int, float, str)) and str(level_value).replace('.', '').isdigit() else level_value
                        processed_song["levels"]["CN"] = cn_level
                        print(f"［国际服］使用国服数据 - 《{processed_song['song_name']}》【曲师: {processed_song['artist']}, 定数: {cn_level}】")
                        break

            # 2. 如果国服匹配失败，尝试日服数据库
            if processed_song["artist"] is None or processed_song["levels"]["CN"] is None:
                jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
                if jp_song_info:
                    # 匹配曲师（日服曲师信息可能在meta中）
                    if processed_song["artist"] is None:
                        processed_song["artist"] = jp_song_info["meta"].get("artist")

                    # 匹配定数
                    if processed_song["levels"]["CN"] is None:
                        level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
                        if level_label and level_label in jp_song_info["data"]:
                            jp_level = jp_song_info["data"][level_label]["const"]
                            processed_song["levels"]["JP"] = jp_level
                            print(f"［国际服］使用日服数据 - 《{processed_song['song_name']}》【曲师: {processed_song['artist']}, 定数: {jp_level}】")
                        else:
                            print(f"警告：《{processed_song['song_name']}》未找到 {level_label} 难度")
                else:
                    print(f"警告：未找到《{processed_song['song_name']}》的日服信息")

            # 3. 查找国际服定数
            level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
            intl_song_info = next((item for item in intl_song_db if item["title"] == processed_song["song_name"]), None)
            if intl_song_info and level_label and level_label in intl_song_info.get("difficulty", {}):
                try:
                    processed_song["levels"]["INT"] = float(intl_song_info["difficulty"][level_label])
                except (ValueError, TypeError):
                    pass

            # 4. 计算rating（使用国服定数，没有则尝试日服）
            ref_level = processed_song["levels"]["CN"] or processed_song["levels"]["JP"]
            if ref_level is not None:
                processed_song["rating"] = calculate_rating(song[fields["score"]], ref_level)
            else:
                print(f"错误：无法获取【{processed_song['song_name']}】的定数，rating设为0")
                processed_song["rating"] = 0

            return processed_song
            
        except Exception as e:
            print(f"处理国际服曲目 {i} 时出错: {e}")
            return None
    
    # 多线程处理
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_intl_song, song, i, clip_ids[i]) for i, song in enumerate(b50_data)]
        for future in futures:
            if result := future.result():
                processed_data.append(result)
    
    return processed_data