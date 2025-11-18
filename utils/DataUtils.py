import json, threading, random, os
import streamlit as st
import pandas as pd
from update_music_data import music_info_path, jp_music_info_path
from utils.chuni_extension import REVERSE_LEVEL_LABELS
from concurrent.futures import ThreadPoolExecutor

# BUCKET_ENDPOINT = "https://nickbit-maigen-images.oss-cn-shanghai.aliyuncs.com"
# DATA_ENDPOINT = "https://maimai.lxns.net"
# FC_PROXY_ENDPOINT = "https://fish-usta-proxy-efexqrwlmf.cn-shanghai.fcapp.run"

# def download_metadata(data_type):
#     url = f"{DATA_ENDPOINT}/api/v0/{data_type}/song/list"
#     response = requests.get(url)
#     if response.status_code == 200:
#         return response.json()
#     else:
#         raise FileNotFoundError(f"从 {url} 下载元数据时出错. 状态码: {response.status_code}")


# def download_image_data(image_path):
#     url = f"{BUCKET_ENDPOINT}/{image_path}"
#     response = requests.get(url, stream=True)
#     if response.status_code == 200:
#         img = Image.open(response.raw)
#         return img
#     else:
#         print(f"Failed to download image from {url}. Status code: {response.status_code}")
#         raise FileNotFoundError

def _process_b50_data(raw_data, source_type: str, b50_raw_file, b50_data_file):
    """Best50 数据清洗"""
    
    # 调试：打印原始数据结构
    # print(f"=== 数据调试信息 ===")
    # print(f"原始数据类型: {type(raw_data)}")
    # if isinstance(raw_data, dict):
    #     print(f"原始数据顶层键: {list(raw_data.keys())}")
    #     if "records" in raw_data:
    #         print(f"records 键: {list(raw_data['records'].keys())}")
    #         print(f"b30 数据长度: {len(raw_data['records'].get('b30', []))}")
    #         print(f"n20 数据长度: {len(raw_data['records'].get('n20', []))}")
    #         print(f"r10 数据长度: {len(raw_data['records'].get('r10', []))}")

    # 1. 加载本地曲目数据库
    with open(music_info_path, 'r', encoding='utf-8') as f:
        song_db = json.load(f)
    
    with open(jp_music_info_path, 'r', encoding='utf-8') as j:
        jp_song_db = json.load(j)

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
            "data_field": ["data.bests", "data.new_bests"]
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
            "data_field": ["records.b30", "records.n20"]  # 使用 b30 和 n20
        }
    }
    
    if source_type not in field_map:
        print(f"错误：不支持的源类型 '{source_type}'")
        return []
        
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
                
                print(f"字段路径 '{field_path}' 找到数据: {type(current)}, 长度: {len(current) if isinstance(current, list) else 'N/A'}")
                
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
    print(f"提取到的 b50_data 总长度: {len(b50_data)}")
    
    # 备用方案：如果嵌套提取失败，尝试直接提取
    if len(b50_data) == 0:
        print("=== 尝试备用提取方案 ===")
        if isinstance(raw_data, dict) and "records" in raw_data:
            records = raw_data["records"]
            b30_data = records.get("b30", [])
            n20_data = records.get("n20", [])
            print(f"直接提取 b30: {len(b30_data)} 条")
            print(f"直接提取 n20: {len(n20_data)} 条")
            b50_data = b30_data + n20_data
            print(f"合并后 b50_data 长度: {len(b50_data)}")

    # 如果还是没有数据，直接返回空列表
    if len(b50_data) == 0:
        print("错误：无法提取到任何有效数据")
        # 保存原始数据用于调试
        with open(b50_raw_file, 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=4)
        return []

    # 4. 缓存原始数据
    with open(b50_raw_file, 'w', encoding='utf-8') as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=4)

    # 5. 多线程处理每条曲目数据
    processed_data = []
    print_lock = threading.Lock()
    
    def process_song(song, i):
        try:
            print(f"处理第 {i} 首曲目: {song.get(fields['song_name'], 'Unknown')}")
            # print(f"曲目数据: {song}")  # 打印完整曲目数据
            
            # 检查必要字段是否存在
            required_fields = ['id', 'song_name', 'level_index', 'score', 'rating', 'fc']
            for field in required_fields:
                field_name = fields[field]
                if field_name not in song:
                    print(f"错误：字段 '{field_name}' 不存在于曲目数据中")
                    return None
                # print(f"  {field}: {song[field_name]}")
            
            processed_song = {
                "clip_id": f"Best_{i + 1}" if i < 30 else f"New_{i - 29}",
                "id": song[fields["id"]],
                "song_name": song[fields["song_name"]],
                "artist": None,
                "score": song[fields["score"]],
                "rating": song[fields["rating"]],
                "level": song[fields["level"]] if fields["level"] is not None else None,
                "level_next": None,
                "level_index": song[fields["level_index"]],
                "full_combo": song.get(fields["fc"]) if fields["fc"] is not None else None,
                "full_chain": song.get(fields["fchain"]) if fields["fchain"] is not None else None,
                "play_count": None
            }

            print(f"【处理后】曲目基础信息: {processed_song['song_name']} - ID: {processed_song['id']}")

            # 从本地数据库匹配曲目信息
            song_info = next((item for item in song_db if item["id"] == processed_song["id"]), None)
            if song_info:
                print(f"找到本地数据库匹配: {song_info['title']}")
                processed_song["artist"] = song_info["artist"]
                for diff in song_info.get("difficulties", []):
                    if diff.get("difficulty") == processed_song["level_index"]:
                        level_value = diff["level_value"]
                        processed_song["level"] = float(level_value) if isinstance(level_value, (int, float, str)) and str(level_value).replace('.', '').isdigit() else level_value
                        print(f"更新难度等级: {processed_song['level']}")
                        break
                else:
                    print(f"警告：【{processed_song['song_name']}】未找到 {processed_song['level_index']} 难度")
            else:
                print(f"警告：未找到【{processed_song['song_name']}】的信息")

            # 从日服数据库匹配日服曲目信息
            jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
            if jp_song_info:
                print(f"检索到日服曲库的相同匹配: {jp_song_info['meta']['title']}")
                level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
                print(f"难度索引: {processed_song['level_index']} -> 标签: {level_label}")
                if level_label and level_label in jp_song_info["data"]:
                    difficulty_data = jp_song_info["data"][level_label]
                    processed_song["level_next"] = difficulty_data["const"]
                    print(f"国服 - [{processed_song['level']}], 日服 - [{processed_song['level_next']}]")
                else:
                    print(f"警告：【{processed_song['song_name']}】未找到 {level_label} 难度")
            else:
                print(f"警告：未找到【{processed_song['song_name']}】的信息")
            
            # 备用方案
            if processed_song["level_next"] is None:
                processed_song["level_next"] = processed_song.get("level", "N/A")
                print(f"使用备用定数: {processed_song['level_next']}")
            
            print(f"曲目处理完成: {processed_song['song_name']}")
            return processed_song
            
        except Exception as e:
            import traceback
            error_msg = f"处理曲目 {i} 时出错: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return None

    print(f"=== 开始处理 {len(b50_data)} 首曲目 ===")
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_song, song, i) for i, song in enumerate(b50_data)]
        for future in futures:
            if result := future.result():
                processed_data.append(result)

    print(f"=== 处理完成，成功处理 {len(processed_data)} 首曲目 ===\n若需要添加 PickUp 曲目，请按照 b30_config.json 中的格式编写")
    # 6. 保存处理后的数据
    with open(b50_data_file, 'w', encoding='utf-8') as f:
        json.dump(processed_data, f, ensure_ascii=False, indent=4)
    return processed_data

def st_gen_resource_config(b50_data, images_path, videoes_path, output_file,
                            clip_start_interval, clip_play_time, default_comment_placeholders):
    """生成视频配置文件，合并了 `st_gen_resource_config` 和 `gene_resource_config`
    
    Args:
        b50_data: b30 数据列表
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
        # "version": "LUMINOUS"
    }

    ending_clip_data = {
        "id": "ending_1",
        "duration": 10,
        "text": "【请填写后记部分】" if default_comment_placeholders else "",
        # "version": "LUMINOUS"
    }

    video_config_data = {
        "enable_re_modify": False,
        "intro": [intro_clip_data],
        "ending": [ending_clip_data],
        "main": [],
    }

    main_clips = []

    # 检查视频开始时间区间
    if clip_start_interval[0] > clip_start_interval[1]:
        print(f"Error: 视频开始时间区间设置错误，请检查global_config.yaml文件中的CLIP_START_INTERVAL配置。")
        clip_start_interval = (clip_start_interval[1], clip_start_interval[1])

    # 遍历 b50_data 来构建视频配置数据
    for song in b50_data:
        if not song['clip_id']:
            print(f"Error: 没有找到 {song['title']}-{song['level_label']}-{song['type']} 的clip_id，请检查数据格式，跳过该片段。")
            continue
        id = song['clip_id']
        # video_name = f"{song['id']}-{song['song_name']}"
        video_name = f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"
        __image_path = os.path.join(images_path, id + ".png")
        __image_path = os.path.normpath(__image_path)
        if not os.path.exists(__image_path):
            print(f"Error: 没有找到 {id}.png 图片，请检查本地缓存数据。")
            __image_path = ""

        __video_path = os.path.join(videoes_path, video_name + ".mp4")
        __video_path = os.path.normpath(__video_path)
        if not os.path.exists(__video_path):
            print(f"Error: 没有找到 {video_name} 视频，请检查本地缓存数据。")
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
            "text": "【请填写 Best50 评价】" if default_comment_placeholders else "",
        }
        main_clips.append(main_clip_data)

    # 倒序排列（b30在前，b1在后）
    main_clips.reverse()

    video_config_data["main"] = main_clips

    # 写入到输出文件
    with open(output_file, 'w', encoding="utf-8") as file:
        json.dump(video_config_data, file, ensure_ascii=False, indent=4)

    return video_config_data

def load_config_with_types(file_path):
    """加载配置并确保正确的数据类型"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
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
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        st.error(f"保存数据失败: {e}")
        return False

# if __name__ == "__main__":
#     img_path = "jackets/maimaidx/Jacket_1103.jpg"
#     img = download_image_data(img_path)
#     img.show()