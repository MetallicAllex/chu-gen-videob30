import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime
from utils.PathUtils import *
from concurrent.futures import ThreadPoolExecutor
import json, random, os, base64, hashlib, requests
from utils.Variables import music_info_path, jp_music_info_path
from utils.PageUtils import _process_cn_data, _process_intl_data
from utils.video_crawler import PurePytubefixDownloader, BilibiliDownloader, get_keyword
from utils.Variables import LEVEL_LABELS, REVERSE_LEVEL_LABELS, CHUNI_DATA_TYPE, CHUNI_COMBO_TYPES, CHUNI_CHAIN_TYPES

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
    
# def _process_b50_data(raw_data, source_type: str, b50_raw_file, b50_data_file, best_or_new: str):
#     """
#     Best50 数据清洗
    
#     Args:
#         raw_data: 请求获取的原始数据
#         source_type(str): 数据源类型：[水鱼 / 落雪 / 国际服]
#         b50_raw_file: Best50 原始数据存储文件名
#         b50_data_file: Best50 清洗数据存储文件名
#         best_or_new(str): 数据类型: [全都要(b30 + n20), 仅新曲(n20), 仅旧曲(b30)]
        
#     Returns:
#         processed_data: 已经过清洗的 Best50 数据
        
#     Raises:
#         Exception: 当数据无效或处理失败时抛出异常
#     """
    
#     # 检查数据是否包含错误
#     if isinstance(raw_data, dict):
#         if "error" in raw_data:
#             raise Exception(f"API 返回错误: {raw_data['error']}")
#         if "message" in raw_data and "error" in raw_data["message"].lower():
#             raise Exception(f"API 返回错误: {raw_data['message']}")
#         if "code" in raw_data and raw_data.get("code") != 200:
#             raise Exception(f"API 返回错误码: {raw_data.get('code')} - {raw_data.get('message', '')}")
    
#     # 1. 加载本地曲目数据库
#     song_db = load_config(music_info_path, use_cache=True)  # 国服数据库
#     jp_song_db = load_config(jp_music_info_path, use_cache=True)  # 日服数据库

#     # 2. 根据数据源类型提取字段映射规则
#     field_map = {
#         "lxns": {
#             "id": "id",
#             "song_name": "song_name",
#             "level": None,
#             "level_index": "level_index",
#             "score": "score",
#             "rating": "rating",
#             "fc": "full_combo",
#             "fchain": "full_chain",
#             "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
#         },
#         "fish": {
#             "id": "mid",
#             "song_name": "title", 
#             "level": "ds",
#             "level_index": "level_index",
#             "score": "score",
#             "rating": "ra",
#             "fc": "fc",
#             "fchain": None,
#             "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
#         },
#         "intr": {  # 国际服 - 从日服数据库获取数据
#             "id": "idx",
#             "song_name": "title", 
#             "level": None,  # 从日服数据库获取
#             "level_index": "difficulty",  # 难度名称
#             "score": "score",
#             "rating": None,  # 需要从日服数据库获取定数后计算
#             "fc": None,  # 在 process_song 中处理
#             "fchain": "fullChainLv",
#             "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
#         }
#     }
    
#     if source_type not in field_map:
#         error_msg = f"错误：不支持的源类型 '{source_type}'"
#         print(error_msg)
#         raise Exception(error_msg)
        
#     fields = field_map[source_type]

#     def get_nested_field(data, field_paths):
#         """从嵌套字典中获取字段值"""
#         if isinstance(field_paths, str):
#             field_paths = [field_paths]
        
#         result = []
        
#         for field_path in field_paths:
#             try:
#                 keys = field_path.split('.')
#                 current = data
#                 for key in keys:
#                     current = current[key]
                
#                 print(f"字段路径 '{field_path}' 找到数据: {type(current)}, 长度: {len(current) if isinstance(current, list) else 'N/A'}")
                
#                 if current is not None:
#                     if isinstance(current, list):
#                         if current:  # 只添加非空列表
#                             result.extend(current)
#                     else:
#                         result.append(current)
#             except (KeyError, TypeError, AttributeError) as e:
#                 print(f"提取 '{field_path}' 时出错: {e}")
#                 continue
        
#         return result

#     # 3. 提取原始 B50 数据
#     print(f"=== 开始提取数据 ===")
#     b50_data = get_nested_field(raw_data, fields["data_field"])
#     print(f"提取到的 best_data 总长度: {len(b50_data)}")
    
#     # 如果还是没有数据，抛出异常
#     if len(b50_data) == 0:
#         error_msg = "无法提取到任何有效数据"
#         print(f"错误：{error_msg}")
        
#         # 保存原始数据用于调试
#         try:
#             save_config(b50_raw_file, raw_data)
#             print(f"已保存原始数据到 {b50_raw_file} 用于调试")
#         except:
#             pass
            
#         raise Exception(error_msg)

#     # 4. 缓存原始数据
#     save_config(b50_raw_file, raw_data)

#     # 5. 多线程处理每条曲目数据
#     processed_data = []
    
#     # 国际服专用：难度映射（从字符串到标签）
#     if source_type == "intr":
#         intr_difficulty_to_label = {
#             "Basic": "BASIC",
#             "Advanced": "ADVANCED", 
#             "Expert": "EXPERT",
#             "Master": "MASTER",
#             "Ultima": "ULTIMA"
#         }
    
#     def process_song(song, i):
#         try:
#             print(f"处理第 {i} 首曲目: {song.get(fields['song_name'], 'Unknown')}")
            
#             # 检查必要字段（根据源类型有所不同）
#             if source_type == "intr":
#                 # 国际服检查
#                 required_fields = ['id', 'song_name', 'level_index', 'score']
#                 missing_fields = []
#                 for field in required_fields:
#                     field_name = fields[field]
#                     if field_name not in song:
#                         missing_fields.append(field_name)
                
#                 if missing_fields:
#                     print(f"错误：字段 {missing_fields} 不存在于曲目数据中")
#                     return None
#             else:
#                 # 国服检查（lxns/fish）
#                 required_fields = ['id', 'song_name', 'level_index', 'score', 'rating', 'fc']
#                 missing_fields = []
#                 for field in required_fields:
#                     field_name = fields[field]
#                     if field_name not in song:
#                         missing_fields.append(field_name)
                
#                 if missing_fields:
#                     print(f"错误：字段 {missing_fields} 不存在于曲目数据中")
#                     return None
            
#             # ========== 国际服特殊处理 ==========
#             if source_type == "intr":
#                 # 处理连击类型
#                 fc_value = None
#                 is_aj = song.get("isAllJustice", False)
#                 is_fc = song.get("isFullCombo", False)
#                 if is_aj:
#                     fc_value = CHUNI_COMBO_TYPES[2]  # 使用 CHUNI_COMBO_TYPES 中的值
#                 elif is_fc:
#                     fc_value = CHUNI_COMBO_TYPES[1]   # 使用 CHUNI_COMBO_TYPES 中的值
                
#                 # 获取全连等级
#                 full_chain_lv = song.get("fullChainLv", 0)
#                 if full_chain_lv == 2:
#                     fchain_value = CHUNI_CHAIN_TYPES[2]  # FC+
#                 elif full_chain_lv == 1:
#                     fchain_value = CHUNI_CHAIN_TYPES[1]   # FC
#                 else:
#                     fchain_value = None          # 未达成
                
#                 # 处理难度索引（从字符串转换为标签）
#                 difficulty_str = song[fields["level_index"]]
#                 level_index_label = intr_difficulty_to_label.get(difficulty_str, difficulty_str.upper())
#             else:
#                 # 国服直接使用已有字段
#                 fc_value = song.get(fields["fc"]) if fields["fc"] else None
#                 fchain_value = song.get(fields["fchain"]) if fields["fchain"] else None
#                 level_index_label = song[fields["level_index"]]
            
#             # 基础数据
#             processed_song = {
#                 "clip_id": f"Best_{i + 1}" if i < 30 else f"New_{i - 29}",
#                 "id": song[fields["id"]],
#                 "song_name": song[fields["song_name"]],
#                 "artist": None,
#                 "score": song[fields["score"]],
#                 "rating": None,  # 需要从数据库获取定数后计算
#                 "level": None,  # 从数据库获取
#                 "level_next": None,  # 从数据库获取
#                 # "level_index": LEVEL_LABELS.get(level_index_label.upper()) if source_type == "intr",
#                 "level_index": LEVEL_LABELS.get(level_index_label.upper()) if source_type == "intr" else REVERSE_LEVEL_LABELS.get(level_index_label),
#                 "full_combo": fc_value,
#                 "full_chain": fchain_value,
#                 "play_count": None
#             }

#             print(f"【处理后】曲目基础信息: {processed_song['song_name']} - ID: {processed_song['id']}")

#             # ========== 国际服：优先从日服数据库获取数据 ==========
#             if source_type == "intr":
#                 jp_difficulty_key = level_index_label  # 直接使用标签，因为日服用的是 "MASTER" 而不是 "MAS"
#                 # 从日服数据库匹配曲目信息
#                 jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
#                 if jp_song_info:
#                     print(f"检索到日服曲库匹配: {jp_song_info['meta']['title']}")
#                     processed_song["artist"] = jp_song_info["meta"].get("artist", "Unknown")
                    
#                     # 获取对应难度的定数
#                     if jp_difficulty_key in jp_song_info["data"]:
#                         difficulty_data = jp_song_info["data"][jp_difficulty_key]
#                         processed_song["level_next"] = difficulty_data["const"]
#                         processed_song["level"] = processed_song["level_next"]  # 使用日服定数
                        
#                         # 计算 rating
#                         if processed_song["score"] is not None and processed_song["level"] is not None:
#                             from utils.PageUtils import calculate_rating
#                             processed_song["rating"] = calculate_rating(
#                                 processed_song["score"], 
#                                 float(processed_song["level"])
#                             )
                        
#                         print(f"更新日服难度等级: {processed_song['level']}, rating: {processed_song['rating']}")
#                     else:
#                         print(f"警告：［{processed_song['song_name']}］在日服数据库中未找到 {jp_difficulty_key} 难度")
#                 else:
#                     print(f"警告：未在日服数据库中找到［{processed_song['song_name']}］的信息")
#                     # 从国服数据库尝试匹配（作为备用）
#                     song_info = next((item for item in song_db if item["id"] == processed_song["id"]), None)
#                     if song_info:
#                         print(f"从国服数据库找到备用匹配: {song_info['title']}")
#                         processed_song["artist"] = song_info["artist"]
#                         for diff in song_info.get("difficulties", []):
#                             if diff.get("difficulty") == processed_song["level_index"]:
#                                 level_value = diff["level_value"]
#                                 processed_song["level"] = float(level_value) if isinstance(level_value, (int, float, str)) and str(level_value).replace('.', '').isdigit() else level_value
#                                 processed_song["level_next"] = processed_song["level"]
                                
#                                 # 计算 rating
#                                 if processed_song["score"] is not None and processed_song["level"] is not None:
#                                     from utils.PageUtils import calculate_rating
#                                     processed_song["rating"] = calculate_rating(
#                                         processed_song["score"], 
#                                         float(processed_song["level"])
#                                     )
#                                 print(f"使用国服备用定数: {processed_song['level']}")
#                                 break
                
#                 # 如果还是没有定数，使用默认定数
#                 if processed_song["level"] is None:
#                     level_defaults = {
#                         "BASIC": 7.0,
#                         "ADVANCED": 10.0,
#                         "EXPERT": 12.0,
#                         "MASTER": 13.5,
#                         "ULTIMA": 14.5
#                     }
#                     processed_song["level"] = level_defaults.get(processed_song["level_index"], 12.0)
#                     processed_song["level_next"] = processed_song["level"]
                    
#                     # 计算 rating
#                     if processed_song["score"] is not None:
#                         from utils.PageUtils import calculate_rating
#                         processed_song["rating"] = calculate_rating(
#                             processed_song["score"], 
#                             float(processed_song["level"])
#                         )
#                     print(f"使用默认定数: {processed_song['level']}")
            
#             else:  # 国服处理逻辑（lxns/fish）
#                 # 从国服数据库匹配曲目信息
#                 song_info = next((item for item in song_db if item["id"] == processed_song["id"]), None)
#                 if song_info:
#                     print(f"检索到国服数据库匹配: {song_info['title']}")
#                     processed_song["artist"] = song_info["artist"]
                    
#                     # 查找对应难度的定数
#                     for diff in song_info.get("difficulties", []):
#                         if diff.get("difficulty") == processed_song["level_index"]:
#                             level_value = diff["level_value"]
#                             processed_song["level"] = float(level_value) if isinstance(level_value, (int, float, str)) and str(level_value).replace('.', '').isdigit() else level_value
                            
#                             # 计算 rating
#                             if processed_song["score"] is not None and processed_song["level"] is not None:
#                                 from utils.PageUtils import calculate_rating
#                                 processed_song["rating"] = calculate_rating(
#                                     processed_song["score"], 
#                                     float(processed_song["level"])
#                                 )
                            
#                             print(f"更新难度等级: {processed_song['level']}, rating: {processed_song['rating']}")
#                             break
#                     else:
#                         print(f"警告：［{processed_song['song_name']}］未找到 {processed_song['level_index']} 难度")
#                 else:
#                     print(f"警告：未找到［{processed_song['song_name']}］的信息")

#                 # 从日服数据库匹配日服曲目信息（用于 level_next）
#                 jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
#                 if jp_song_info:
#                     print(f"检索到日服曲库的相同匹配: {jp_song_info['meta']['title']}")
#                     level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
#                     print(f"难度索引: {processed_song['level_index']} -> 标签: {level_label}")
#                     if level_label and level_label in jp_song_info["data"]:
#                         difficulty_data = jp_song_info["data"][level_label]
#                         processed_song["level_next"] = difficulty_data["const"]
#                         print(f"国服 - [{processed_song['level']}], 日服 - [{processed_song['level_next']}]")
#                     else:
#                         print(f"警告：【{processed_song['song_name']}】未找到 {level_label} 难度")
#                 else:
#                     print(f"警告：未找到【{processed_song['song_name']}】的信息")
                
#                 # 备用方案
#                 if processed_song["level_next"] is None:
#                     processed_song["level_next"] = processed_song.get("level", "N/A")
#                     print(f"使用备用定数: {processed_song['level_next']}")
            
#             print(f"曲目处理完成: {processed_song['song_name']}")
#             return processed_song
            
#         except Exception as e:
#             import traceback
#             error_msg = f"处理曲目 {i} 时出错: {str(e)}\n{traceback.format_exc()}"
#             print(error_msg)
#             return None

#     print(f"=== 开始处理 {len(b50_data)} 首曲目 ===")
#     with ThreadPoolExecutor() as executor:
#         futures = [executor.submit(process_song, song, i) for i, song in enumerate(b50_data)]
#         for future in futures:
#             if result := future.result():
#                 processed_data.append(result)

#     # 检查处理后的数据是否为空
#     if len(processed_data) == 0:
#         error_msg = "处理后的数据为空，没有成功处理任何曲目"
#         print(f"错误：{error_msg}")
#         raise Exception(error_msg)

#     print(f"=== 处理完成，成功处理 {len(processed_data)} 首曲目 ===\n若需要添加 PickUp 曲目，请按照 b50_config.json 中的格式编写")
    
#     # 6. 保存处理后的数据
#     save_config(b50_data_file, processed_data)
#     return processed_data






# def _process_b50_data(raw_data, source_type: str, b50_raw_file, b50_data_file, best_or_new: str):
#     """
#     Best50 数据清洗
    
#     Args:
#         raw_data: 请求获取的原始数据
#         source_type(str): 数据源类型：[水鱼 / 落雪 / 国际服]
#         b50_raw_file: Best50 原始数据存储文件名
#         b50_data_file: Best50 清洗数据存储文件名
#         best_or_new(str): 数据类型: [全都要(b30 + n20), 仅新曲(n20), 仅旧曲(b30)]
        
#     Returns:
#         processed_data: 已经过清洗的 Best50 数据
        
#     Raises:
#         NoSuchFileExceptions: 未找到原始文件
#         KeyErrorExceptions: 字段不存在
#     """
    
#     # 调试：打印原始数据结构
#     # print(f"=== 数据调试信息 ===")
#     # print(f"原始数据类型: {type(raw_data)}")
#     # if isinstance(raw_data, dict):
#     #     print(f"原始数据顶层键: {list(raw_data.keys())}")
#     #     if "records" in raw_data:
#     #         print(f"records 键: {list(raw_data['records'].keys())}")
#     #         print(f"b30 数据长度: {len(raw_data['records'].get('b30', []))}")
#     #         print(f"n20 数据长度: {len(raw_data['records'].get('n20', []))}")
#     #         print(f"r10 数据长度: {len(raw_data['records'].get('r10', []))}")

#     # 1. 加载本地曲目数据库
#     song_db = load_config(music_info_path, use_cache=True)
#     jp_song_db = load_config(jp_music_info_path, use_cache=True)

#     # 2. 根据数据源类型提取字段映射规则
#     field_map = {
#         "lxns": {
#             "id": "id",
#             "song_name": "song_name",
#             "level": None,
#             "level_index": "level_index",
#             "score": "score",
#             "rating": "rating",
#             "fc": "full_combo",
#             "fchain": "full_chain",
#             "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
#         },
#         "fish": {
#             "id": "mid",
#             "song_name": "title", 
#             "level": "ds",
#             "level_index": "level_index",
#             "score": "score",
#             "rating": "ra",
#             "fc": "fc",
#             "fchain": None,
#             "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
#         },
#         "intr": {
#             "id": "idx",
#             "song_name": "title", 
#             "level": None,
#             "level_index": "difficulty", # 下面已经处理这个字段的信息了，这里不需要处理
#             "score": "score",
#             "rating": None,
#             "fc": CHUNI_COMBO_TYPES[2] if "isAllJustice" else (CHUNI_COMBO_TYPES[1] if "isFullCombo" else CHUNI_COMBO_TYPES[0]),
#             "fchain": "fullChainLv",
#             "data_field": CHUNI_DATA_TYPE[source_type][best_or_new]
#         }
#     }
    
#     if source_type not in field_map:
#         print(f"错误：不支持的源类型 '{source_type}'")
#         return []
        
#     fields = field_map[source_type]

#     def get_nested_field(data, field_paths):
#         """从嵌套字典中获取字段值"""
#         if isinstance(field_paths, str):
#             field_paths = [field_paths]
        
#         result = []
        
#         for field_path in field_paths:
#             try:
#                 keys = field_path.split('.')
#                 current = data
#                 for key in keys:
#                     current = current[key]
                
#                 print(f"字段路径 '{field_path}' 找到数据: {type(current)}, 长度: {len(current) if isinstance(current, list) else 'N/A'}")
                
#                 if current is not None:
#                     if isinstance(current, list):
#                         if current:  # 只添加非空列表
#                             result.extend(current)
#                     else:
#                         result.append(current)
#             except (KeyError, TypeError, AttributeError) as e:
#                 print(f"提取 '{field_path}' 时出错: {e}")
#                 continue
        
#         return result

#     # 3. 提取原始 B50 数据
#     print(f"=== 开始提取数据 ===")
#     b50_data = get_nested_field(raw_data, fields["data_field"])
#     print(f"提取到的 best_data 总长度: {len(b50_data)}")
    
#     # 备用方案：如果嵌套提取失败，尝试直接提取
#     # if len(b50_data) == 0:
#     #     print("=== 尝试备用提取方案 ===")
#     #     if isinstance(raw_data, dict) and "records" in raw_data:
#     #         records = raw_data["records"]
#     #         b30_data = records.get("b30", [])
#     #         n20_data = records.get("n20", [])
#     #         print(f"直接提取 b30: {len(b30_data)} 条")
#     #         print(f"直接提取 n20: {len(n20_data)} 条")
#     #         b50_data = b30_data + n20_data
#     #         print(f"合并后 b50_data 长度: {len(b50_data)}")

#     # 如果还是没有数据，直接返回空列表
#     if len(b50_data) == 0:
#         print("错误：无法提取到任何有效数据")
#         # 保存原始数据用于调试
#         save_config(b50_raw_file, raw_data)
#         return []

#     # 4. 缓存原始数据
#     save_config(b50_raw_file, raw_data)

#     # 5. 多线程处理每条曲目数据
#     processed_data = []
#     # print_lock = threading.Lock()
    
#     def process_song(song, i):
#         try:
#             print(f"处理第 {i} 首曲目: {song.get(fields['song_name'], 'Unknown')}")
#             # print(f"曲目数据: {song}")  # 打印完整曲目数据
            
#             # 检查必要字段是否存在
#             required_fields = ['id', 'song_name', 'level_index', 'score', 'rating', 'fc']
#             for field in required_fields:
#                 field_name = fields[field]
#                 if field_name not in song:
#                     print(f"错误：字段 '{field_name}' 不存在于曲目数据中")
#                     return None
#                 # print(f"  {field}: {song[field_name]}")
            
#             processed_song = {
#                 "clip_id": f"{"Best"}_{i + 1}" if i < 30 else f"New_{i - 29}",
#                 "id": song[fields["id"]],
#                 "song_name": song[fields["song_name"]],
#                 "artist": None,
#                 "score": song[fields["score"]],
#                 "rating": song[fields["rating"]],
#                 "level": song[fields["level"]] if fields["level"] is not None else None,
#                 "level_next": None,
#                 "level_index": LEVEL_LABELS[song[fields["level_index".upper()]]] if source_type == "intr" else song[fields["level_index"]],
#                 "full_combo": song.get(fields["fc"]) if fields["fc"] is not None else None,
#                 "full_chain": song.get(fields["fchain"]) if fields["fchain"] is not None else None,
#                 "play_count": None
#             }

#             print(f"【处理后】曲目基础信息: {processed_song['song_name']} - ID: {processed_song['id']}")

#             # 从国服数据库匹配曲目信息
#             song_info = next((item for item in song_db if item["id"] == processed_song["id"]), None)
#             if song_info or source_type != "intr":
#                 print(f"检索到国服数据库匹配: {song_info['title']}")
#                 processed_song["artist"] = song_info["artist"]
#                 for diff in song_info.get("difficulties", []):
#                     if diff.get("difficulty") == processed_song["level_index"]:
#                         level_value = diff["level_value"]
#                         processed_song["level"] = float(level_value) if isinstance(level_value, (int, float, str)) and str(level_value).replace('.', '').isdigit() else level_value
#                         print(f"更新难度等级: {processed_song['level']}")
#                         break
#                 else:
#                     print(f"警告：［{processed_song['song_name']}］未找到 {processed_song['level_index']} 难度")
#             else:
#                 print(f"警告：未找到［{processed_song['song_name']}］的信息")

#             # 从日服数据库匹配日服曲目信息
#             jp_song_info = next((item for item in jp_song_db if item["meta"]["title"] == processed_song["song_name"]), None)
#             if jp_song_info:
#                 print(f"检索到日服曲库的相同匹配: {jp_song_info['meta']['title']}")
#                 level_label = REVERSE_LEVEL_LABELS.get(processed_song["level_index"])
#                 print(f"难度索引: {processed_song['level_index']} -> 标签: {level_label}")
#                 if level_label and level_label in jp_song_info["data"]:
#                     difficulty_data = jp_song_info["data"][level_label]
#                     processed_song["level_next"] = difficulty_data["const"]
#                     print(f"国服 - [{processed_song['level']}], 日服 - [{processed_song['level_next']}]")
#                 else:
#                     print(f"警告：【{processed_song['song_name']}】未找到 {level_label} 难度")
#             else:
#                 print(f"警告：未找到【{processed_song['song_name']}】的信息")
            
#             # 备用方案
#             if processed_song["level_next"] is None:
#                 processed_song["level_next"] = processed_song.get("level", "N/A")
#                 print(f"使用备用定数: {processed_song['level_next']}")
            
#             print(f"曲目处理完成: {processed_song['song_name']}")
#             return processed_song
            
#         except Exception as e:
#             import traceback
#             error_msg = f"处理曲目 {i} 时出错: {str(e)}\n{traceback.format_exc()}"
#             print(error_msg)
#             return None

#     print(f"=== 开始处理 {len(b50_data)} 首曲目 ===")
#     with ThreadPoolExecutor() as executor:
#         futures = [executor.submit(process_song, song, i) for i, song in enumerate(b50_data)]
#         for future in futures:
#             if result := future.result():
#                 processed_data.append(result)

#     print(f"=== 处理完成，成功处理 {len(processed_data)} 首曲目 ===\n若需要添加 PickUp 曲目，请按照 b50_config.json 中的格式编写")
#     # 6. 保存处理后的数据
#     save_config(b50_data_file, processed_data)
#     return processed_data

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
        print(f"Error: 视频开始时间区间设置错误，请检查global_config.yaml文件中的CLIP_START_INTERVAL配置。")
        clip_start_interval = (clip_start_interval[1], clip_start_interval[1])

    # 遍历 b50_data 来构建视频配置数据
    for song in b50_data:
        if not song['clip_id']:
            print(f"Error: 没有找到 {song['title']}-{song['level_label']}-{song['type']} 的 clip_id，请检查数据格式，跳过该片段。")
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

# def update_b50_data_lxns(b50_raw_file, b50_data_file, friend_code, data_type):
#     lxns = get_b50_data(friend_code, "lxns")
#     # if "data" not in lxns:
#     #     raise Exception("落雪 API 未传回 Best50 数据，您可能需要检查好友码或账号设置")
#     if 'message' in lxns:
#         raise ConnectionError(f"请求 Best50 数据失败: {lxns['message']}")
#     return _process_b50_data(lxns, "lxns", b50_raw_file, b50_data_file, data_type)

# def update_b50_data_fish(b50_raw_file, b50_data_file, username, data_type):
#     try:
#         fish = get_b50_data(username, "fish")
#         if 'message' in fish:
#             raise ConnectionError(f"请求 Best50 数据失败: {fish['message']}")
#         return _process_b50_data(fish, "fish", b50_raw_file, b50_data_file, data_type)
#     except json.JSONDecodeError:
#         raise Exception("Error: 返回数据非有效 JSON 格式")

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