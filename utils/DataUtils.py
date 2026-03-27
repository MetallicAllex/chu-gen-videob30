import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime
from utils.PathUtils import *
import json, random, os, base64, hashlib, requests
from utils.Variables import music_info_path, jp_music_info_path
from utils.PageUtils import _process_cn_data, _process_intl_data
from utils.Variables import REVERSE_LEVEL_LABELS, CHUNI_DATA_TYPE
from utils.video_crawler import PurePytubefixDownloader, BilibiliDownloader, get_keyword

def _process_b50_data(raw_data, source_type: str, b50_raw_file, b50_data_file, best_or_new: str):
    """
    Best50 数据清洗
    
    Args:
        raw_data: 请求获取的原始数据
        source_type(str): 数据源类型：[水鱼 / 落雪 / 国际服]
        b50_raw_file: Best50 原始数据存储文件名
        b50_data_file: Best50 清洗数据存储文件名
        best_or_new(str): 数据类型: [全都要(b30 + n20), 仅新曲(n20), 仅旧曲(b30)]
        
    Returns:
        processed_data: 已经过清洗的 Best50 数据
        
    Raises:
        Exception: 当数据无效或处理失败时抛出异常
    """
    
    # 1. 加载本地曲目数据库
    song_db = load_config(music_info_path, use_cache=True)  # 国服数据库
    jp_song_db = load_config(jp_music_info_path, use_cache=True)  # 日服数据库
    
    # 检查数据是否包含错误
    if isinstance(raw_data, dict):
        if "error" in raw_data:
            raise Exception(f"API 返回错误: {raw_data['error']}")
        if "message" in raw_data and "error" in raw_data["message"].lower():
            raise Exception(f"API 返回错误: {raw_data['message']}")
        if "code" in raw_data and raw_data.get("code") != 200:
            raise Exception(f"API 返回错误码: {raw_data.get('code')} - {raw_data.get('message', '')}")
    
    # 1. 加载本地曲目数据库
    song_db = load_config(music_info_path, use_cache=True)  # 国服数据库
    jp_song_db = load_config(jp_music_info_path, use_cache=True)  # 日服数据库

    # 2. 根据数据源类型提取字段映射规则
    field_map = {
        "lxns": {
            "id": "id",
            "song_name": "song_name",
            "level": None,
            "level_index": "level_index",
            "score": "score",
            "rating": "rating",
            "fc": "full_combo",
            "fchain": "full_chain",
            "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
        },
        "fish": {
            "id": "mid",
            "song_name": "title", 
            "level": "ds",
            "level_index": "level_index",
            "score": "score",
            "rating": "ra",
            "fc": "fc",
            "fchain": None,
            "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
        },
        "intr": {  # 国际服 - 从日服数据库获取数据
            "id": "idx",
            "song_name": "title", 
            "level": None,  # 从日服数据库获取
            "level_index": "difficulty",  # 难度名称
            "score": "score",
            "rating": None,  # 需要从日服数据库获取定数后计算
            "fc": None,  # 在 process_song 中处理
            "fchain": "fullChainLv",
            "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
        }
    }
    
    if source_type not in field_map:
        error_msg = f"错误：不支持的源类型 '{source_type}'"
        print(error_msg)
        raise Exception(error_msg)
        
    fields = field_map[source_type]

    def get_nested_field(data, field_paths):
        """从嵌套字典中获取字段值"""
        if isinstance(field_paths, str):
            field_paths = [field_paths]
        
        result = []
        
        for field_path in field_paths:
            try:
                keys = field_path.split('.')
                current = data
                for key in keys:
                    current = current[key]
                
                # print(f"字段路径 '{field_path}' 找到数据: {type(current)}, 长度: {len(current) if isinstance(current, list) else 'N/A'}")
                
                if current is not None:
                    if isinstance(current, list):
                        if current:  # 只添加非空列表
                            result.extend(current)
                    else:
                        result.append(current)
            except (KeyError, TypeError, AttributeError) as e:
                print(f"提取 '{field_path}' 时出错: {e}")
                continue
        
        return result
    
    # 3. 提取原始 B50 数据
    print(f"=== 开始提取数据 ===")
    b50_data = get_nested_field(raw_data, fields["data_field"])
    print(f"提取到的 best_data 总长度: {len(b50_data)}")
    
    if len(b50_data) == 0:
        print("错误：无法提取到任何有效数据")
        save_config(b50_raw_file, raw_data)
        return []

    # 4. 缓存原始数据
    save_config(b50_raw_file, raw_data)
    
    if source_type == "intr":
        processed_data = _process_intl_data(b50_data, fields, best_or_new, song_db, jp_song_db)
    else:
        processed_data = _process_cn_data(b50_data, fields, best_or_new, song_db, jp_song_db)
    
    print(f"=== 处理完成，成功处理 {len(processed_data)} 首曲目 ===\n若需要添加 PickUp 曲目，请按照 b50_config.json 中的格式编写")
    save_config(b50_data_file, processed_data)
    return processed_data
    
def gen_video_config(b50_data, images_path, videoes_path, output_file,
                            clip_start_interval, clip_play_time, default_comment_placeholders):
    """生成视频配置文件，合并了 `st_gen_resource_config` 和 `gene_resource_config`
    
    Args:
        b50_data: b50 数据列表
        images_path: 图片路径
        videoes_path: 视频路径
        output_file: 输出配置文件路径
        clip_start_interval: 视频开始时间的区间（可选，默认为 None，使用全局变量）
        clip_play_time: 每个视频片段的时长（可选，默认为 None，使用全局变量）
        default_comment_placeholders: 是否使用默认的评论占位符（可选，默认为 None，使用全局变量）
    
    Returns:
        video_config_data: 生成的视频配置数据字典
    """

    # 如果参数没有传入，则使用全局变量或默认值
    if clip_start_interval is None:
        clip_start_interval = (clip_start_interval[0], clip_start_interval[1])
    
    if clip_play_time is None:
        clip_play_time = 10  # 默认值
    
    if default_comment_placeholders is None:
        default_comment_placeholders = False  # 默认值

    intro_clip_data = {
        "id": "intro_1",
        "duration": 10,
        "text": "【请填写前言部分】" if default_comment_placeholders else "",
        "bg_page": False
        # "version": "LUMINOUS"
    }

    ending_clip_data = {
        "id": "ending_1",
        "duration": 10,
        "text": "【请填写后记部分】" if default_comment_placeholders else "",
        "bg_page": False
        # "version": "LUMINOUS"
    }

    video_config_data = {
        "intro": [intro_clip_data],
        "ending": [ending_clip_data],
        "main": [],
    }

    main_clips = []

    # 检查视频开始时间区间
    if clip_start_interval[0] > clip_start_interval[1]:
        print(f"错误: 视频开始时间区间设置错误，请检查global_config.yaml文件中的CLIP_START_INTERVAL配置。")
        clip_start_interval = (clip_start_interval[1], clip_start_interval[1])

    # 遍历 b50_data 来构建视频配置数据
    for song in b50_data:
        if not song['clip_id']:
            print(f"错误: 没有找到 {song['title']}-{song['level_label']}-{song['type']} 的 clip_id，请检查数据格式，跳过该片段。")
            continue
        id = song['clip_id']
        # video_name = f"{song['id']}-{song['song_name']}"
        video_name = f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"
        __image_path = os.path.join(images_path, id + ".png")
        __image_path = os.path.normpath(__image_path)
        if not os.path.exists(__image_path):
            print(f"错误: 没有找到 {id}.png 图片，请检查本地缓存数据。")
            __image_path = ""

        __video_path = os.path.join(videoes_path, video_name + ".mp4")
        __video_path = os.path.normpath(__video_path)
        if not os.path.exists(__video_path):
            print(f"错误: 没有找到 {video_name} 视频，请检查本地缓存数据。")
            __video_path = ""
        
        duration = clip_play_time
        start = random.randint(clip_start_interval[0], clip_start_interval[1])
        end = start + duration

        main_clip_data = {
            "id": song["id"],
            "clip_id": song["clip_id"],
            "song_name": song["song_name"],
            "artist": song["artist"],
            "level": song["level"],
            "level_next": song["level_next"],
            "level_index": song["level_index"],
            "score": song["score"],
            "rating": song["rating"],
            "full_combo": song["full_combo"],
            "full_chain": song["full_chain"],
            "main_image": __image_path,
            "video": __video_path,
            "duration": duration,
            "start": start,
            "end": end,
            "text": "【请填写 Best50 评价（不支持显示 Emoji）】" if default_comment_placeholders else "",
            # "skip": False
        }
        main_clips.append(main_clip_data)

    # 倒序排列（b30在前，b1在后）
    # main_clips.reverse() # 此行代码已在生成图像的步骤被代替

    video_config_data["main"] = main_clips

    # 写入到输出文件
    save_config(output_file, video_config_data)
    
    return video_config_data

def load_config_with_types(file_path):
    """加载配置并确保正确的数据类型"""
    try:
        data = load_config(file_path, use_cache=True, cache_time=60)
        
        # 数据类型转换
        for item in data:
            # 整型字段
            for int_field in ['id', 'score', 'level_index']:
                if int_field in item and item[int_field] is not None:
                    item[int_field] = int(item[int_field])
            
            # 浮点型字段
            for float_field in ['level', 'level_next', 'rating']:
                if float_field in item and item[float_field] is not None:
                    item[float_field] = float(item[float_field])
            
            # 可选整型字段（允许为null）
            if 'play_count' in item:
                if item['play_count'] is None or pd.isna(item['play_count']):
                    item['play_count'] = None
                else:
                    item['play_count'] = int(item['play_count'])
            
            # 字符串字段 - 确保是字符串类型
            for str_field in ['song_name', 'artist', 'clip_id']:
                if str_field in item and item[str_field] is not None:
                    item[str_field] = str(item[str_field])
            
            # 可选枚举字段 - 处理空值
            for enum_field in ['full_combo', 'full_chain']:
                if enum_field in item and (item[enum_field] is None or pd.isna(item[enum_field])):
                    item[enum_field] = None
            return data
    except Exception as e:
        st.error(f"加载数据失败: {e}", icon="❌")
        return []

def save_config_with_types(file_path, data):
    """保存配置并确保正确的数据类型和null值"""
    try:
        # 深拷贝数据以避免修改原始数据
        data_to_save = []
        
        for item in data:
            cleaned_item = {}
            for key, value in item.items():
                # 处理NaN和空值，转换为None
                if value is None or (isinstance(value, (int, float)) and pd.isna(value)):
                    cleaned_item[key] = None
                else:
                    cleaned_item[key] = value
            
            data_to_save.append(cleaned_item)
        
        # 保存为JSON，确保null值正确序列化
        save_config(file_path, data_to_save)
        
        return True
    except Exception as e:
        st.error(f"保存数据失败: {e}")
        return False


def save_song_data(current_data, current_paths, success_message, warning_message, should_rerun=True):
    """
    保存曲目数据的通用函数
    
    Args:
        current_data: 当前数据列表
        current_paths: 路径配置
        success_message: 成功消息
        warning_message: 警告消息（只读模式）
        should_rerun: 是否在保存后刷新页面
    """
    # 更新数据
    st.session_state.processed_data = current_data
    st.session_state.editing_b50_data = current_data
    
    # 如果处于编辑模式，自动保存
    if st.session_state.editing_enabled:
        if save_config_with_types(current_paths['data_file'], current_data):
            st.success(success_message, icon="✅")
            if should_rerun:
                st.rerun()
            return True
    else:
        st.warning(warning_message, icon="⚠️")
        if should_rerun:
            st.rerun()
        return False
    return False

def merge_b50_data(new_b50_data, old_b50_data):
    """
    合并两份 Best50 数据，使用新数据的基本信息但保留旧数据中的视频相关信息
    
    Args:
        new_b50_data (list): 新的b30数据（不含video_info_list和video_info_match）
        old_b50_data (list): 旧的b30数据（youtube版或bilibili版）
    
    Returns:
        tuple: (合并后的b30数据列表, 更新计数)
    """
    # 检查数据长度是否一致
    if len(new_b50_data) != len(old_b50_data):
        print(f"Warning: 新旧 b50 数据长度不一致，将使用新数据替换旧数据。")
        return new_b50_data, 0
    
    # 创建旧数据的复合键映射表
    old_song_map = {
        (song['id'], song['level_index']): song 
        for song in old_b50_data
    }
    
    # 按新数据的顺序创建合并后的列表
    merged_b50_data = []
    keep_count = 0
    for new_song in new_b50_data:
        song_key = (new_song['id'], new_song['level_index'])
        if song_key in old_song_map:
            # 如果记录已存在，使用新数据但保留原有的视频信息
            cached_song = old_song_map[song_key]
            new_song['video_info_list'] = cached_song.get('video_info_list', [])
            new_song['video_info_match'] = cached_song.get('video_info_match', {})
            if new_song == cached_song:
                keep_count += 1
        else:
            new_song['video_info_list'] = []
            new_song['video_info_match'] = {}
        merged_b50_data.append(new_song)

    update_count = len(new_b50_data) - keep_count
    return merged_b50_data, update_count

def update_b50_data(b50_raw_file, b50_data_file, query_param, best_new, server):
    if server == "intr":
        return _process_b50_data(b50_data, server, b50_raw_file, b50_data_file, best_new)
    else:
        b50_data = get_b50_data(query_param, server)
        if 'message' in b50_data:
            raise ConnectionError(f"请求 Best50 数据失败: {b50_data['message']}")
    return _process_b50_data(b50_data, server, b50_raw_file, b50_data_file, best_new)

def search_one_video(downloader, song_data):
    title_name = song_data['song_name']
    level_index = REVERSE_LEVEL_LABELS.get(song_data['level_index'])
    dl_type = "youtube" if isinstance(downloader, PurePytubefixDownloader) \
                else "bilibili" if isinstance(downloader, BilibiliDownloader) \
                else "None"
    keyword = get_keyword(dl_type, title_name, level_index)

    print(f"搜索关键词: {keyword}")
    videos = downloader.search_video(keyword)

    if len(videos) == 0:
        output_info = f"错误：没有找到{title_name}-({level_index})的视频"
        # output_info = f"Error: 没有找到{title_name}-{difficulty_name}({level_index})-{type}的视频"
        print(output_info)
        song_data['video_info_list'] = []
        song_data['video_info_match'] = {}
        return song_data, output_info

    match_index = 0
    output_info = f"首个搜索结果: {videos[match_index]['title']}, {videos[match_index]['url']}"
    print(f"首个搜索结果: {videos[match_index]['title']}, {videos[match_index]['url']}")

    song_data['video_info_list'] = videos
    song_data['video_info_match'] = videos[match_index]
    return song_data, output_info

def download_one_video(downloader, song, video_download_path, high_res=False):
    """同步版本的视频下载函数"""
    clip_name = f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"
    video_path = os.path.join(video_download_path, f"{clip_name}.mp4")
    
    # 同步检查缓存
    if os.path.exists(video_path):
        message = f"已找到【{song['song_name']}】的缓存: {clip_name}"
        print(message.encode('gbk', errors='replace').decode('gbk'))
        return {"status": "skip", "info": message}
    
    # 原有下载逻辑保持不变
    if 'video_info_match' not in song or not song['video_info_match']:
        print(f"错误: 没有【{song['title']}-{song['level_label']}】的视频信息")
        return {"status": "error", "info": f"错误: 没有【{song['title']}-{song['level_label']}】的视频信息"}
    
    video_info = song['video_info_match']
    v_id = video_info['id'] 
    
    # 获取分P索引（默认为 0）
    p_index = video_info.get('p_index', 0)
    
    # 修复：添加 p_index 参数
    downloader.download_video(v_id, clip_name, video_download_path, high_res=high_res, p_index=p_index)  # 添加 p_index
    
    return {"status": "success", "info": f"下载【{song['song_name']}】（{clip_name}）完成"}

def st_init_cache_pathes():
    cache_pathes = [
        f"./b30_datas",
        f"./videos",
        f"./videos/downloads",
        f"./cred_datas"
    ]
    for path in cache_pathes:
        if not os.path.exists(path):
            os.makedirs(path)

def sort_video_files(files):
    """
    严格检查：只允许完全符合 '数字_描述.mp4' 格式的文件
    不合格的文件会被跳过并记录警告
    """
    sorted_files = []
    encountered_numbers = set()
    skipped_files = []
    
    # print(f"开始严格检查文件列表: {files}")
    
    for filename in files:
        # print(f"检查文件: '{filename}'")
        
        try:
            # 1. 检查文件扩展名
            if not filename.endswith('.mp4'):
                raise ValueError(f"文件扩展名不是 .mp4")
            
            # 2. 分离基础名称和扩展名
            base_name = os.path.splitext(filename)[0]
            
            # 3. 检查是否包含下划线
            if '_' not in base_name:
                raise ValueError(f"文件名缺少下划线分隔符")
            
            # 4. 提取数字部分
            parts = base_name.split('_')
            number_str = parts[0]
            
            # 5. 检查数字部分是否纯数字
            if not number_str.isdigit():
                raise ValueError(f"数字部分包含非数字字符")
            
            # 6. 转换为数字
            number = int(number_str)
            
            # 7. 检查描述部分是否合法（不能包含空格、副本等）
            description = '_'.join(parts[1:])  # 剩余部分作为描述
            if any(char in description for char in [' ', '-', '副本', 'copy']):
                raise ValueError(f"描述部分包含非法字符")
            
            # 8. 检查数字是否重复
            if number in encountered_numbers:
                raise ValueError(f"发现重复的片段编号 {number}")
            
            # 9. 所有检查通过，添加到列表
            sorted_files.append((number, filename))
            encountered_numbers.add(number)
            # print(f"文件通过检查: {filename} -> 编号 {number}")
            
        except (ValueError, IndexError) as e:
            # print(f"跳过: {filename} - {e}")
            skipped_files.append((filename, str(e)))
    
    # 如果没有找到任何合格文件
    if not sorted_files:
        raise ValueError(f"没有找到任何符合格式的视频文件！跳过的文件: {skipped_files}")
    
    # 报告跳过的文件
    if skipped_files:
        print(f"［信息］跳过了 {len(skipped_files)} 个不符合格式的文件：")
        for filename, reason in skipped_files:
            print(f"  - {filename}: {reason}")
    
    # 按数字排序
    sorted_files.sort(key=lambda x: x[0])
    # print(f"排序后的合格文件: {sorted_files}")
    
    # 检查数字序列是否连续
    numbers = [num for num, _ in sorted_files]
    expected_sequence = list(range(numbers[0], numbers[0] + len(numbers)))
    
    if numbers != expected_sequence:
        missing_numbers = set(expected_sequence) - set(numbers)
        if missing_numbers:
            raise ValueError(f"片段编号不连续！缺失的编号: {sorted(missing_numbers)}。当前合格文件: {[f for _, f in sorted_files]}")
        else:
            raise ValueError(f"片段编号序列异常！当前: {numbers}，期望: {expected_sequence}")
    
    result = [filename for _, filename in sorted_files]
    # print(f"最终通过的文件 ({len(result)} 个): {result}")
    return result

def get_b50_data(query_param, server="lxns"):
    from requests.exceptions import HTTPError
    class LXNSBizError(Exception):
        def __init__(self, message):
            self.message = message
    
    fish = "https://www.diving-fish.com/api/chunithmprober/query/player"
    lxns_proxy = f"https://fish-usta-proxy-efexqrwlmf.cn-shanghai.fcapp.run?source=lxns&game=chunithm&query=best&friend_code={query_param}"
    
    try:
        if server == "lxns":
            response = requests.get(lxns_proxy, timeout=10)
        elif server == "fish":
            response = requests.post(fish, json={"username": query_param}, timeout=10)
        
        response.raise_for_status()  # 自动处理 HTTP 错误
        data = response.json()
        
        # 将业务逻辑检查结果作为异常抛出
        if server == "lxns" and not data.get("success", True):
            raise LXNSBizError(data.get('error', '未知错误'))
        
        return data
    except LXNSBizError as e:
        return {"error": f"落雪 API 返回错误: {e.message}"}
    except HTTPError as e:
        return {"error": "好友码无效，请检查您的好友码是否输入正确" if e.response.status_code == 401 
                else f"API 请求失败: {e.response.status_code}"}
    except Exception as e:
        return {"error": f"获取数据时发生意外错误: {str(e)}"}

# API 端点
LXNS_API_ENDPOINT = "https://maimai.lxns.net/api/v0/chunithm"
song_data_cn = f"{LXNS_API_ENDPOINT}/song/list"
alisa_url_cn = f"{LXNS_API_ENDPOINT}/alias/list"
song_data_jp = "aHR0cHM6Ly9yZWl3YS5mNS5zaS9jaHVuaXJlY19hbGwuanNvbg=="

# 创建目录
os.makedirs(os.path.dirname(music_info_path), exist_ok=True)

def json_hash(obj):
    """生成 JSON 对象的 md5 哈希"""
    return hashlib.md5(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()

def safe_decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("utf-8")

def should_update_metadata(threshold_hours=24):
    """
    检查是否需要更新乐曲元数据
    
    Args:
        threshold_hours: 更新的时间阈值（小时）
        
    Returns:
        bool: 是否需要更新
    """
    # 在用户目录下创建配置目录
    config_dir = Path.home() / ".chu-gen-videob30"
    config_dir.mkdir(exist_ok=True)
    
    config_file = config_dir / "metadata_update.json"
    
    current_time = datetime.now()
    
    # 如果配置文件不存在，则创建并立即返回True
    if not config_file.exists():
        # with open(config_file, "w") as f:
        #     json.dump({"last_update": current_time.isoformat()}, f)
        save_config(config_file, {"last_update": current_time.isoformat()})
        return True
    
    # 读取上次更新时间
    try:
        data = load_config(config_file)
        last_update = datetime.fromisoformat(data.get("last_update", "2000-01-01T00:00:00"))
    except (json.JSONDecodeError, ValueError):
        # 文件损坏或格式错误，重新创建
        # with open(config_file, "w") as f:
        #     json.dump({"last_update": current_time.isoformat()}, f)
        save_config(config_file, {"last_update": current_time.isoformat()})
        return True
    
    # 计算时间差
    time_diff = current_time - last_update
    if time_diff.total_seconds() / 3600 >= threshold_hours:
        # 更新时间戳
        save_config(config_file, {"last_update": current_time.isoformat()})
        return True
    
    return False

def _fetch_music_data(name, url, filepath, transformer=None):
    """
    获取并更新音乐数据
    
    Args:
        name: 数据源名称
        url: 数据源URL
        filepath: 本地存储路径
        transformer: 数据转换函数
    """
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"❌ 获取谱面数据失败，状态码 {response.status_code}")
            return

        raw_data = safe_decode(response.content)
        data = json.loads(raw_data)
        # print(f"📦 （{name}）返回内容预览：\n{raw_data[:200]}")
        if transformer:
            data = transformer(data)

        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            save_config(filepath, data)
            print(f"✅ （{name}）已下载所需的谱面数据[{json_hash(data)}]")
            return

        local_data = load_config(filepath)

        if json_hash(data) != json_hash(local_data):
            save_config(filepath, data)
            print(f"🔄［{name}］谱面数据成功更新[{json_hash(data)}]")
        else:
            print(f"☑️［{name}］谱面数据已是最新[{json_hash(local_data)}]")

    except Exception as e:
        print(f"❌［{name}］获取谱面数据时出错：{e}")

# fetch_music_data 函数用于调用（可选检查缓存）
def fetch_music_data(forced, threshold_hours=24):
    """
    直接获取谱面数据（不检查缓存时间）
    """
    # 检查是否需要更新
    if should_update_metadata(threshold_hours) or forced == False:
        print("⏩ 未达到更新阈值，跳过数据更新")
        return
    
    else:
        print("🔄️ 开始更新谱面数据。")
        _fetch_music_data(
            name="国服",
            url=song_data_cn,
            filepath=music_info_path,
            transformer=lambda d: d.get("songs", [])
        )

        difficulty_map = {
            "BAS": "BASIC",
            "ADV": "ADVANCED",
            "EXP": "EXPERT",
            "MAS": "MASTER",
            "ULT": "ULTIMA"
        }

        def transformer(data):
            for song in data:
                if "data" in song:
                    song["data"] = {
                        difficulty_map.get(k, k): v for k, v in song["data"].items()
                    }
            return data
        
        _fetch_music_data(
            name="日服",
            url=base64.b64decode(song_data_jp),
            filepath=jp_music_info_path,
            transformer=transformer
        )
        
        print("✅ 谱面数据更新完成")