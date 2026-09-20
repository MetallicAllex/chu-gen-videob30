import pandas as pd
import streamlit as st
from datetime import datetime, timezone
from utils.PathUtils import *
import json, random, os, base64, hashlib, requests, threading, time, re, unicodedata, html
from utils.Variables import (DIFFICULTY_MAP, music_info_path, jp_music_info_path, intl_music_info_path,
                             jp_music_info_url, intl_music_info_url,
                             MUSIC_DATA_USER_AGENT, music_status_dir)
from utils.PageUtils import _process_cn_data, _process_intl_data, build_song_indexes, lookup_song_fields
from utils.Variables import REVERSE_LEVEL_LABELS, CHUNI_DATA_TYPE
from utils.Variables import (fish_music_info_path,
                             fish_latest_version_path, cn_song_meta_path)
from utils.FilterUtils import (EmptyFilterResult, PART_BEST, PART_NEW, PART_ORDER, PART_SELECT,
                               apply_filters,
                               build_alias_index, build_fish_chart_index, build_lxns_song_index,
                               cap_parts, describe_spec, group_by_part, group_versions,
                               normalize_fish_b50, normalize_fish_records, normalize_lxns,
                               spec_is_active, to_fish_params, VERSION_GENERATION, version_sort_key)
from utils.video_crawler import PurePytubefixDownloader, BilibiliDownloader, get_keyword, get_keyword_fallback

def _process_b50_data(raw_data, source_type: str, b50_raw_file, b50_data_file, best_or_new: str,
                      clip_prefixes=None, data_field=None):
    """
    Best50 数据清洗
    
    Args:
        raw_data: 请求获取的原始数据
        source_type(str): 数据源类型：[水鱼 / 落雪 / 国际服]
        b50_raw_file: Best50 原始数据存储文件名
        b50_data_file: Best50 清洗数据存储文件名
        best_or_new(str): 数据类型: [全都要(b30 + n20), 仅新曲(n20), 仅旧曲(b30)]
        clip_prefixes(list[str] | None): 每条成绩所属的分组前缀，用于分组内连续编号；
                                         不传则按旧的全局下标规则编号
        data_field(str | list[str] | None): 覆盖 CHUNI_DATA_TYPE 里的取数路径，
                                         筛选链路带上 data.selections 时用
        
    Returns:
        processed_data: 已经过清洗的 Best50 数据
        
    Raises:
        Exception: 当数据无效或处理失败时抛出异常
    """
    
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
    # 国际服曲库要 Worker 清洗过才拿得到，没部署就是没文件 —— 缺了只是少一服定数，不该挡住建档
    intl_song_db = _load_optional_json(intl_music_info_path) or []  # 国际服数据库

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
    if data_field:
        # 筛选链路重建出的 raw 可能多出一个 data.selections 分组，CHUNI_DATA_TYPE 里没有这一项
        fields = dict(fields, data_field=data_field)

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
    
    if clip_prefixes is not None and len(clip_prefixes) != len(b50_data):
        raise Exception(
            f"分组前缀列表与抽取到的成绩条数不一致（{len(clip_prefixes)} vs {len(b50_data)}），"
            f"本次取数的数据路径与清洗口径对不上，已中止以免生成错号存档")

    if source_type == "intr":
        processed_data = _process_intl_data(b50_data, fields, best_or_new, song_db, jp_song_db, intl_song_db,
                                            clip_prefixes)
    else:
        processed_data = _process_cn_data(b50_data, fields, best_or_new, song_db, jp_song_db, intl_song_db,
                                          clip_prefixes)
    
    # 从 levels 派生 level/level_next 以保持下游兼容（后续由版本选择器决定取哪个）
    for item in processed_data:
        lv = item.get("levels", {})
        item["level"] = lv.get("CN") or lv.get("JP")
        item["level_next"] = lv.get("JP") or lv.get("CN")

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

    # 如果参数没有传入，则使用默认值
    if clip_start_interval is None:
        clip_start_interval = (3, 8)

    if clip_play_time is None:
        clip_play_time = 10  # 默认值

    if default_comment_placeholders is None:
        default_comment_placeholders = False  # 默认值

    intro_clip_data = {
        "id": "intro_1",
        "duration": 10,
        "text": "【请填写前言部分】" if default_comment_placeholders else "",
        "bg_page": False,
        "no_overlay": False,
        "no_sound": False
    }

    ending_clip_data = {
        "id": "ending_1",
        "duration": 10,
        "text": "【请填写后记部分】" if default_comment_placeholders else "",
        "bg_page": False,
        "no_overlay": False,
        "no_sound": False
    }

    video_config_data = {
        "intro": [intro_clip_data],
        "ending": [ending_clip_data],
        "main": [],
    }

    main_clips = []

    # 检查视频开始时间区间
    if clip_start_interval[0] > clip_start_interval[1]:
        clip_start_interval = (clip_start_interval[1], clip_start_interval[1])

    # 遍历 b50_data 来构建视频配置数据
    for song in b50_data:
        if not song.get('clip_id'):
            continue
        clip_tag = song['clip_id']
        video_tag = f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"

        __image_path = os.path.normpath(os.path.join(images_path, clip_tag + ".png"))
        missing_img = not os.path.exists(__image_path)
        if missing_img:
            __image_path = ""

        __video_path = os.path.normpath(os.path.join(videoes_path, video_tag + ".mp4"))
        missing_vid = not os.path.exists(__video_path)
        if missing_vid:
            __video_path = ""
        
        duration = clip_play_time
        start = random.randint(clip_start_interval[0], clip_start_interval[1])
        end = start + duration

        if missing_img:
            st.warning(f"图片不存在: {clip_tag}.png", icon="🖼️")
        if missing_vid:
            st.warning(f"视频不存在: {video_tag}.mp4", icon="🎬")

        lvls = song.get("levels", {})
        main_clip_data = {
            "id": song["id"],
            "clip_id": song["clip_id"],
            "song_name": song["song_name"],
            "artist": song["artist"],
            "levels": lvls,
            "level": lvls.get("CN") or lvls.get("JP") or song["level"],
            "level_next": lvls.get("JP") or lvls.get("CN") or song.get("level_next", song["level"]),
            "level_index": song["level_index"],
            "score": song["score"],
            "rating": song["rating"],
            "full_combo": song["full_combo"],
            "full_chain": song["full_chain"],
            "main_image": __image_path,
            "full_image": None,
            "video": __video_path,
            "duration": duration,
            "start": start,
            "end": end,
            "text": "【请填写 Best50 评价（不支持显示 Emoji）】" if default_comment_placeholders else "",
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
        data = load_config(file_path, use_cache=True)
        
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


def save_song_data(current_data, current_paths, message, should_rerun=True):
    """
    写入 b30_config.json 并同步所有在读它的页面缓存

    调用方只在「解锁」状态下可达（写操作按钮都以 disabled=not editing_enabled 挡住），
    所以这里不再区分只读分支。
    """
    if not save_config_with_types(current_paths['data_file'], current_data):
        return False

    # 更新数据
    st.session_state.processed_data = current_data
    st.session_state.editing_b50_data = current_data
    st.session_state.viewing_b50_data = current_data
    # 清除 data_editor 缓存，强制刷新
    st.session_state.pop("data_editor", None)
    # 落盘顺序变了，拖拽面板里按 #序号 编码下标的缓存必须作废
    st.session_state.sortable_items = []

    st.success(message, icon="✅")
    if should_rerun:
        st.rerun()
    return True

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

def update_b50_data(b50_raw_file, b50_data_file, req_param):
    """
    国服建存档：取数 → 规范化 → 筛选 → 截断 → 清洗。

    命中 0 条时抛 EmptyFilterResult，而且是在写任何文件之前 —— 否则界面上会留下一个
    指向已被 rmtree 的目录的存档号。
    """
    server = req_param['data_server']
    best_new = req_param['best_or_new']
    pool = build_cn_pool(
        server, best_new,
        pool_source=req_param.get('pool_source') or POOL_BRIEF,
        filter_mode=req_param.get('filter_mode') or MODE_LOCAL,
        spec=req_param.get('filters'),
        caps=req_param.get('caps'),
        include_selections=req_param.get('include_selections', False),
        raw=req_param.get('raw'),
        new_versions=req_param.get('new_versions'),
        group_parts=req_param.get('group_parts', True),
    )
    if not pool["prefixes"]:
        raise EmptyFilterResult(describe_spec(req_param.get('filters')))
    return _process_b50_data(pool["raw"], server, b50_raw_file, b50_data_file, best_new,
                             pool["prefixes"], pool["data_field"])


def backfill_pool_fields(b50_data_file, apply_changes=False):
    """
    用当前曲库回填存档里的曲库派生字段，不重建成绩列表。

    存档里的 artist / levels 是**建档那一刻**的曲库快照：曲库后来补齐了某首歌、或官方调过定数，
    已存在的 b30_config.json 不会自动跟上，而空 artist 会让底图渲染直接失败。
    这里只重算这几个字段，成绩本身（曲名、分数、rating、combo、clip_id、手工添加的 PickUp 行）
    一律不碰 —— 从 raw 重建列表会把那些手加行直接删掉。

    返回 (records, changes, skipped)：changes 是逐条字段级 before→after，供界面如实展示。
    """
    records = load_config(b50_data_file)
    if not isinstance(records, list) or not records:
        return [], [], []

    indexes = build_song_indexes(
        load_config(music_info_path, use_cache=True),
        load_config(jp_music_info_path, use_cache=True),
        _load_optional_json(intl_music_info_path) or [],
    )

    changes, skipped = [], []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        clip_id = rec.get('clip_id', f"第 {i + 1} 条")
        cn_song = indexes['CN'].get(str(rec.get('id')))
        if not cn_song:
            skipped.append((clip_id, rec.get('id'), "曲库里查不到这个 id"))
            continue
        # 国际服存档的 id 来自另一套编号，撞上国服 id 也不会是同一首歌，标题对不上就不动它
        if _compact_text(cn_song.get('title')) != _compact_text(rec.get('song_name')):
            skipped.append((clip_id, rec.get('id'), f"该 id 在曲库里是《{cn_song.get('title')}》，与存档曲名不符"))
            continue

        artist, levels = lookup_song_fields(rec.get('id'), rec.get('song_name'),
                                            rec.get('level_index'), indexes)
        updates = {}
        if not rec.get('artist') and artist:
            updates['artist'] = artist

        old_levels = rec.get('levels') if isinstance(rec.get('levels'), dict) else {}
        merged = dict(old_levels)
        for server, value in levels.items():
            # 只刷新或新增，不把已有的非空值降级成 None
            if value is not None and old_levels.get(server) != value:
                merged[server] = value
        if merged != old_levels:
            updates['levels'] = merged

        if rec.get('level') in (None, ''):
            updates['level'] = merged.get('CN') or merged.get('JP')
        if rec.get('level_next') in (None, ''):
            updates['level_next'] = merged.get('JP') or merged.get('CN')

        if updates:
            changes.append((clip_id, {f: (rec.get(f, '（无此字段）'), v) for f, v in updates.items()}))
            if apply_changes:
                rec.update(updates)

    if apply_changes and changes:
        save_config(b50_data_file, records)
    return records, changes, skipped

VIDEO_NAME_WEIGHT = 3.0        # 曲名命中是最强信号
LEVEL_LABEL_WEIGHT = 1.5
LEVEL_NUMBER_WEIGHT = 0.5
CONFIRM_KEYWORD_WEIGHT = 1.5   # 「谱面确认」是区分谱面预览与手元/演奏视频最可靠的信号
DURATION_CLOSE_WEIGHT = 0.5
DURATION_FAR_PENALTY = 1.0
OTHER_GAME_PENALTY = 2.0
MULTI_PART_PENALTY = 2.0
# 搜索接口不给分P数，但多P合集的 duration 是各分P之和（实测 6 个分P 显示 184:51）
MULTI_PART_SUSPECT_SECONDS = 600
OTHER_GAME_MARKERS = ('maimai', '舞萌', 'オンゲキ', 'プロセカ', 'プロジェクトセカイ', '世界计划',
                      'sdvx', 'jubeat', 'beatmania', 'iidx', '太鼓', 'taiko', '音撃')
# 标题带这些词的候选几乎不可能是谱面确认素材（原曲试听、MV 等高热内容），
# 与「标题不含曲名」一样直接丢弃，不进候选列表——否则候选会被这类视频搅浑
NOT_CHART_MARKERS = ('原曲', '音源', '試聴', '试听', '歌ってみた', 'カラオケ', '卡拉', 'mv', 'pv')
# 这些词的候选也可能是谱面确认（如「譜面確認+手元」），不丢弃但降权，
# 且自动匹配按存疑处理（video_match_warning 会给出原因），由人工决定用不用
SOFT_NOISE_MARKERS = ('手元', '演奏', 'プレイ動画', '参考動画', 'ピアノ', 'piano')
NOISE_PENALTY = 1.0

# 游戏语境词与语境门槛。曲名本身可能是普通单词（如 Odin 会撞上陀螺、神话解说、漫威），
# 噪音话题枚举不完，所以改用结构性规则：谱面确认视频的标题几乎必然带「谱(面)」、
# 游戏/系列名或难度信息之一——除曲名外一个语境信号都没有的候选（纯撞名）直接丢弃。
# 单字「谱」也算语境：容纳紫谱/黑谱/彩谱这类社区写法（乐谱/曲谱类误入的会因缺难度
# 信号沉底，且永远不会被自动选中）。
GAME_MARKERS = ('chunithm', 'チュウニズム', '中二节奏')
CHART_WORD_WEIGHT = 0.5
GAME_WORD_WEIGHT = 0.5
# 带这些旗标之一的候选才算「有谱面/游戏语境」，一个都没有的不进候选列表
CONTEXT_FLAGS = {'level_label', 'level_number', 'confirm', 'other_game', 'chart_word', 'game_word'}

def _has_marker(title, markers) -> bool:
    """标记词命中判定：短拉丁词（mv/pv 等）用词边界避免命中普通单词内部，
    其余（含中日文）直接子串匹配。title 需先经 _normalize_match_text 归一化。"""
    for marker in markers:
        if marker.isascii() and len(marker) <= 3:
            if _has_word(title, marker):
                return True
        elif marker in title:
            return True
    return False

def _fold_text(text) -> str:
    """解 HTML 实体 + NFKC 统一全/半角并转小写，之后各归一化都在此基础上做"""
    return unicodedata.normalize('NFKC', html.unescape(str(text))).lower()

def _normalize_match_text(text) -> str:
    """只留字母数字，其余（含全角标点、分隔号）压成单个空格，用于词级比较"""
    return re.sub(r'\s+', ' ', ''.join(ch if ch.isalnum() else ' ' for ch in _fold_text(text))).strip()

def _compact_text(text) -> str:
    """连空格都去掉的压缩串：曲名里的符号被删掉、换成全角、空格数不同都不影响比对"""
    return ''.join(ch for ch in _fold_text(text) if ch.isalnum())

def _symbol_form(text) -> str:
    """仅折叠全半角并去掉空白的原样串，用于曲名里没有任何字母数字的极端情况"""
    return re.sub(r'\s+', '', _fold_text(text))

def _has_word(text: str, word: str) -> bool:
    """词边界判定：前面不能是字母数字（避免 ai 命中 chain），后面允许跟数字（master14+）但不能跟字母"""
    if not word:
        return False
    return re.search(rf'(?<![a-z0-9]){re.escape(word)}(?![a-z])', text) is not None

def _name_in_title(song_name, title) -> bool:
    """曲名命中判定

    《≠彡\"/了→》这类曲名的字母数字残串只剩几个字，逐字符包含会被标点写法卡住，
    所以主判据用压缩串；残串又短又是拉丁或数字时才改用词边界，避免命中无关单词内部。
    """
    name = _compact_text(song_name)
    if not name:
        # 曲名全是符号，只能按原样（忽略空白）比对
        symbol_form = _symbol_form(song_name)
        return bool(symbol_form) and symbol_form in _symbol_form(title)
    if len(name) < 6 and (name.isascii() or name.isdigit()):
        return _has_word(_normalize_match_text(title), name)
    return name in _compact_text(title)

def _level_number_pattern(level):
    """数值难度在标题里的写法：CHUNITHM 用整数加可选的 + 表示 .5 及以上，
    所以 15.1 写作 "15"、14.8 写作 "14+"；也有作者直接写全定数（15.1）"""
    try:
        value = float(level)
    except (TypeError, ValueError):
        return None
    fraction = value % 1
    if not fraction:
        # 整数难度不能命中 "15+" 或 "15.1"
        return re.compile(rf'(?<![\d.]){int(value)}(?![\d.+])')
    tokens = [f'{value:g}', f'{int(value)}+' if fraction >= 0.5 else f'{int(value)}']
    body = '|'.join(re.escape(_fold_text(token)) for token in dict.fromkeys(tokens))
    return re.compile(rf'(?<![\d.])({body})(?![\d.])')

def _difficulty_text(text) -> str:
    """数值难度比对用的形式：保留 + 和 . """
    return re.sub(r'\s+', ' ', ''.join(ch if (ch.isalnum() or ch in '+.') else ' '
                                       for ch in _fold_text(text))).strip()

def score_video_candidate(song, video, median_duration=None):
    """返回 (score, flags)，flags 记录命中的信号，便于界面上说明为什么不确信

    曲名是前提：只有曲名命中的候选才值得看后面的难度、时长等细判。
    """
    title = _normalize_match_text(video.get('title', ''))
    flags = set()
    score = 0.0

    if _name_in_title(song.get('song_name', ''), video.get('title', '')):
        score += VIDEO_NAME_WEIGHT
        flags.add('name')
    if _has_word(title, _compact_text(REVERSE_LEVEL_LABELS.get(song.get('level_index'), ''))):
        score += LEVEL_LABEL_WEIGHT
        flags.add('level_label')
    pattern = _level_number_pattern(song.get('level'))
    if pattern is not None and pattern.search(_difficulty_text(video.get('title', ''))):
        score += LEVEL_NUMBER_WEIGHT
        flags.add('level_number')
    if any(keyword in title for keyword in ('谱面确认', '譜面確認')):
        score += CONFIRM_KEYWORD_WEIGHT
        flags.add('confirm')
    elif any(keyword in title for keyword in ('谱', '譜')):
        # 裸「谱/譜」字（谱面、紫谱、黑谱、譜面 etc.）：弱于「谱面确认」但仍是语境信号
        score += CHART_WORD_WEIGHT
        flags.add('chart_word')
    if _has_marker(title, GAME_MARKERS):
        score += GAME_WORD_WEIGHT
        flags.add('game_word')
    if _has_marker(title, OTHER_GAME_MARKERS):
        score -= OTHER_GAME_PENALTY
        flags.add('other_game')
    if _has_marker(title, SOFT_NOISE_MARKERS):
        # 手元/演奏类视频里有少数其实带谱面画面，不丢弃但压到谱面确认后面
        score -= NOISE_PENALTY
        flags.add('noisy')

    duration = video.get('duration')
    if isinstance(duration, (int, float)) and duration > MULTI_PART_SUSPECT_SECONDS:
        # 自动匹配等于默认取 P1，选到合集就会下回另一首歌，所以宁可标出来让人指定分P
        score -= MULTI_PART_PENALTY
        flags.add('multi_part')
    if median_duration is not None and isinstance(duration, (int, float)):
        delta = abs(duration - median_duration)
        if delta <= 10:
            score += DURATION_CLOSE_WEIGHT
        elif delta >= 60:
            score -= DURATION_FAR_PENALTY
    return score, flags

def rank_video_candidates(song, videos):
    """先按曲名筛出候选，再按难度/时长细判排序；同分时保持搜索引擎给出的原始顺序

    三类候选直接丢弃：标题里没有曲名的（多半是搜索引擎按热度返回的无关视频）、
    标题带原曲/音源/MV/试听这类标记的（几乎不可能是谱面确认，只会把候选列表搅浑）、
    以及除曲名外没有任何谱面/游戏/难度语境的——曲名可能是普通单词（Odin 会撞上
    陀螺、神话解说之类），只靠撞名不足以认定是谱面确认。
    手元/演奏类的疑似候选保留但降权，交由 video_match_warning 标成待确认。
    """
    if not videos:
        return []
    matched = []
    for video in videos:
        if not _name_in_title(song.get('song_name', ''), video.get('title', '')):
            continue
        if _has_marker(_normalize_match_text(video.get('title', '')), NOT_CHART_MARKERS):
            continue
        matched.append(video)
    durations = sorted(v['duration'] for v in matched if isinstance(v.get('duration'), (int, float)))
    # 谱面确认视频时长彼此接近；中位数只在命中曲名的候选里取，否则会被几十条无关结果带偏
    median_duration = durations[len(durations) // 2] if len(durations) >= 3 else None

    scored = []
    for index, video in enumerate(matched):
        score, flags = score_video_candidate(song, video, median_duration)
        if not flags & CONTEXT_FLAGS:
            continue
        scored.append((-score, index, score, flags, video))
    scored.sort()
    return [(item[2], item[3], item[4]) for item in scored]

def video_match_warning(flags):
    """把命中信号翻译成需要人工确认的原因，无告警时返回 None"""
    if 'multi_part' in flags:
        return '疑似分P合集/多曲连播，需在视频 ID 模式指定分P'
    if 'other_game' in flags:
        return '疑似其他音游视频'
    if 'noisy' in flags:
        return '标题更像手元/演奏类视频，请确认是否含有谱面画面'
    if 'name' not in flags:
        return '标题未出现曲名'
    if 'level_label' not in flags:
        return '标题未出现该难度标签'
    if 'level_number' not in flags:
        return '标题数值难度与本谱面不一致'
    return None

def search_one_video(downloader, song_data):
    title_name = song_data['song_name']
    level_index = REVERSE_LEVEL_LABELS.get(song_data['level_index'])
    dl_type = "youtube" if isinstance(downloader, PurePytubefixDownloader) \
                else "bilibili" if isinstance(downloader, BilibiliDownloader) \
                else "None"
    keywords = [get_keyword(dl_type, title_name, level_index),
                get_keyword_fallback(dl_type, title_name, level_index)]

    # 两个关键词的结果合并去重后统一排序：主关键词扫回来的若全是存疑候选
    # （手元/其他音游/多P合集，或干脆没有标题含曲名的），不值得就此定稿，
    # 换备选关键词再补一轮，两轮结果合并后往往是干净的谱面确认在最优位。
    # 首轮就有无争议命中时照旧只发一次请求，最坏情况（两轮都发）与原逻辑相同。
    pool, ranked, scanned = {}, [], 0
    for index, keyword in enumerate(keywords):
        print(f"搜索关键词: {keyword}")
        videos = downloader.search_video(keyword)
        scanned += len(videos)
        for video in videos:
            pool.setdefault(video['id'], video)
        # 标题里没有曲名/明显不是谱面确认/缺谱面语境的候选会被直接丢弃；扫描池远大于保留条数
        ranked = rank_video_candidates(song_data, list(pool.values()))
        if ranked and not video_match_warning(ranked[0][1]):
            break
        if index == 0 and videos:
            print(f"      -- [{len(videos)} 个结果里没有可直接确认的谱面确认，改用备选关键词合并重试]")

    if not ranked:
        if not scanned:
            output_info = f"错误：没有找到{title_name}-({level_index})的视频"
        else:
            output_info = (f"错误：{title_name}-({level_index}) 扫描的 {scanned} 个结果里"
                           f"没有可用的谱面确认候选（标题未含曲名、更像原曲/MV，"
                           f"或除曲名外没有谱面/难度/游戏语境），视为未匹配")
        print(output_info)
        song_data['video_info_list'] = []
        song_data['video_info_match'] = {}
        return song_data, output_info

    ranked = ranked[:max(1, downloader.search_max_results)]

    best_score, best_flags, best_video = ranked[0]
    warning = video_match_warning(best_flags)
    song_data['video_info_list'] = [video for _, _, video in ranked]
    if warning:
        # 难度信息对不上时不自动认定已匹配，避免整批下回错误的谱面
        song_data['video_info_match'] = {}
        output_info = f"待确认[{best_score:.1f}]: {best_video['title']}（{warning}）"
    else:
        song_data['video_info_match'] = best_video
        output_info = f"最优候选[{best_score:.1f}]: {best_video['title']}, {best_video['url']}"
    print(output_info)

    return song_data, output_info

# --- 下载缓存索引 ---
# 缓存文件名（曲ID-难度.mp4）是 README 与下游剪辑环节的既定约定，不能往文件名里塞分P信息；
# 但改选候选视频或改选分P后，同名文件可能是按旧选择下的素材。索引用 <clip_name> ->
# {video_id, p_index} 记录"这个文件当时下的是什么"，放在 ./cache 下避免污染 downloads 目录。

VIDEO_CACHE_INDEX_FILE = os.path.join("./cache", "video_cache_index.json")

def video_clip_name(song):
    """下载缓存与下游剪辑共用的素材文件名（不含扩展名）：曲ID-难度"""
    return f"{song['id']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}"

def load_video_cache_index():
    """读取下载缓存索引；文件缺失或损坏都当作空索引（最多多重下一次，不挡流程）"""
    if not os.path.exists(VIDEO_CACHE_INDEX_FILE):
        return {}
    try:
        return load_config(VIDEO_CACHE_INDEX_FILE)
    except (OSError, ValueError):
        return {}

def is_video_cached(song, video_download_path, cache_index=None):
    """缓存命中 = 视频文件存在，且索引记录与当前选定的视频/分P一致

    索引没有记录的旧缓存：未指定分P（p_index=0）时按旧行为信任文件，避免老用户全部重下；
    指定了分P却查不到记录时宁可重下，防止把别的分P当成已缓存。
    """
    clip_name = video_clip_name(song)
    video_path = os.path.join(video_download_path, f"{clip_name}.mp4")
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return False
    video_info = song.get('video_info_match') or {}
    p_index = video_info.get('p_index') or 0
    if cache_index is None:
        cache_index = load_video_cache_index()
    record = cache_index.get(clip_name)
    if record is None:
        return p_index == 0
    return record.get('video_id') == video_info.get('id') and (record.get('p_index') or 0) == p_index

def mark_video_cached(song, cache_index=None):
    """下载成功后记录缓存来源（视频 ID + 分P），供 is_video_cached 校验是否过期

    传入 cache_index 时直接更新调用方持有的字典（批量循环里避免反复读盘），否则自行加载。
    """
    video_info = song.get('video_info_match') or {}
    if cache_index is None:
        cache_index = load_video_cache_index()
    cache_index[video_clip_name(song)] = {
        'video_id': video_info.get('id'),
        'p_index': video_info.get('p_index') or 0,
        'cached_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    os.makedirs(os.path.dirname(VIDEO_CACHE_INDEX_FILE), exist_ok=True)
    save_config(VIDEO_CACHE_INDEX_FILE, cache_index)
    return cache_index

def download_one_video(downloader, song, video_download_path, high_res=False, cache_index=None):
    """同步版本的视频下载函数

    cache_index: 调用方持有的缓存索引字典（可选）；传入时命中判断与下载后的
    索引更新都直接作用在这份字典上，批量循环里不必逐首重复读盘。
    """
    clip_name = video_clip_name(song)
    video_path = os.path.join(video_download_path, f"{clip_name}.mp4")

    if 'video_info_match' not in song or not song['video_info_match']:
        message = f"错误: 没有【{song['song_name']}-{REVERSE_LEVEL_LABELS.get(song['level_index'])}】的视频信息"
        print(message)
        return {"status": "error", "info": message}

    # 缓存检查：文件在且与当前选定的视频/分P一致才算命中
    if is_video_cached(song, video_download_path, cache_index):
        message = f"已找到【{song['song_name']}】的缓存: {clip_name}"
        print(message.encode('gbk', errors='replace').decode('gbk'))
        return {"status": "skip", "info": message}

    # 缓存过期（换了候选视频或分P）：先清掉旧文件再下。pytubefix 遇到已存在的输出会改名另存，
    # 残留的旧文件也会让下载后的存在性校验失真
    if os.path.exists(video_path):
        try:
            os.remove(video_path)
        except OSError as e:
            message = f"错误: 旧缓存文件被占用无法覆盖（请关闭正在使用它的程序后重试）: {e}"
            print(message)
            return {"status": "error", "info": message}

    video_info = song['video_info_match']
    v_id = video_info['id']

    # 获取分P索引（默认为 0）
    p_index = video_info.get('p_index', 0)

    try:
        downloader.download_video(v_id, clip_name, video_download_path, high_res=high_res, p_index=p_index)
    except Exception as e:
        message = f"错误: 下载【{song['song_name']}】（{clip_name}）失败: {e}"
        print(message)
        return {"status": "error", "info": message}

    # 下载器内部可能吞掉异常，以文件是否真正生成作为成功依据
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        message = f"错误: 【{song['song_name']}】（{clip_name}）未生成有效视频文件"
        print(message)
        return {"status": "error", "info": message}

    mark_video_cached(song, cache_index)
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

def _request_error_message(name, response):
    """尽量把服务端的中文说明透出来 —— 400 的 message 是唯一的线索（例如过滤参数取值不合法）。"""
    try:
        body = response.json() or {}
    except Exception:
        body = {}
    detail = body.get("message") or body.get("error")
    return f"{name} API 请求失败: {response.status_code}" + (f" - {detail}" if detail else "")


def _authorized_request(server, url, method="GET", params=None, json_body=None):
    """
    两家查分器的认证请求，共用同一套规则：没有令牌就提示去授权；收到 401 就强制
    刷新令牌后重发一次。返回 (data, error)，error 为 None 表示成功。

    只重试一次：401 有两种成因 —— 令牌到期（刷新即可续上）与授权被吊销（刷新也会
    失败并清掉令牌）。后者继续发只会白耗水鱼那 200 次/日的配额。
    """
    name = "落雪" if server == "lxns" else "水鱼"
    if server == "lxns":
        from utils.OAuthUtils import get_lxns_access_token
    else:
        from utils.OAuthUtils import get_fish_access_token
    get_access_token = get_lxns_access_token if server == "lxns" else get_fish_access_token

    def send(token):
        return requests.request(method, url, params=params, json=json_body,
                                headers={"Authorization": f"Bearer {token}"}, timeout=10)

    token = get_access_token()
    if not token:
        return None, f"尚未授权{name}账号，请先完成授权"

    try:
        response = send(token)
        if response.status_code == 401:
            # RFC 6750：401 表示这枚令牌已不可用，强制换一枚新的再试
            token = get_access_token(stale_token=token)
            if not token:
                return None, f"{name} OAuth 令牌已失效，请重新授权{name}账号"
            response = send(token)
    except requests.exceptions.RequestException as e:
        # 断网 / 超时不带状态码，包成中文错误而不是把 traceback 抛给界面
        return None, f"请求{name}服务器时出错: {e}"

    if response.status_code != 200:
        return None, _request_error_message(name, response)

    try:
        data = response.json()
    except ValueError:
        return None, f"{name}返回的不是合法 JSON（HTTP {response.status_code}）"
    # 落雪用 success 字段表达业务失败，水鱼直接用 HTTP 状态码
    if server == "lxns" and not data.get("success", True):
        return None, f"落雪 API 返回错误: {data.get('message') or data.get('error') or '未知错误'}"
    return data, None


def _fish_authorized_request(url, method="GET", params=None, json_body=None):
    return _authorized_request("fish", url, method, params, json_body)


def _lxns_authorized_request(url):
    return _authorized_request("lxns", url)


def get_b50_data(server):
    """
    获取国服 Best50 原始数据（水鱼 / 落雪均走查分器官方 OAuth 接口）

    身份取自令牌本身，因此不再需要用户名 / QQ 号 / 好友码等查询参数，
    也就只能取到令牌主人自己的成绩。

    Args:
        server: 数据源，"fish"（水鱼）或 "lxns"（落雪）

    Returns:
        查分器原始响应 dict；未授权或请求失败时返回 {"error": 说明}
    """
    from utils.OAuthUtils import FISH_QUERY_PLAYER_URL, LXNS_BESTS_URL
    if server == "lxns":
        data, error = _lxns_authorized_request(LXNS_BESTS_URL)
    elif server == "fish":
        # 身份取自令牌（服务端直接用 g.user），所以不传 username / qq；
        # 但请求体必须是合法 JSON —— 服务端解析 body 的语句在 OAuth 分支之前执行
        data, error = _fish_authorized_request(FISH_QUERY_PLAYER_URL, method="POST", json_body={})
    else:
        raise ValueError(f"get_b50_data 不支持的数据源: {server}")
    return {"error": error} if error else data


# ==================== 国服筛选：候选池 ====================

POOL_BRIEF = "简略成绩"
POOL_FULL = "完整历史"
MODE_SERVER = "服务端预筛"
MODE_LOCAL = "纯本地"

# 分组 -> 重建 raw 时写入的路径。(数据源, 成绩来源) 为键，因为完整历史的水鱼只有
# 一个 records.best 数组，新旧两组要写进同一份列表里。
_PART_PATHS = {
    ("fish", POOL_BRIEF): {PART_BEST: "records.b30", PART_NEW: "records.n20"},
    ("fish", POOL_FULL): {PART_BEST: "records.best", PART_NEW: "records.best"},
    ("lxns", POOL_BRIEF): {PART_BEST: "data.bests", PART_NEW: "data.new_bests", PART_SELECT: "data.selections"},
    ("lxns", POOL_FULL): {PART_BEST: "data.bests", PART_NEW: "data.new_bests", PART_SELECT: "data.selections"},
}
_RAW_CONTAINER = {"fish": "records", "lxns": "data"}

# 这些条件全靠曲库 join 出来的元数据，曲库缺失时整列都是 None：
# 不报出来的话，"筛完只剩 0 条"看起来像是用户条件太严，实际是数据没到位。
META_DEPENDENT = ("artist", "genre", "version", "charter", "bpm_range")

# 水鱼返回体里压根没有的字段，条件必须整体忽略而不是当"未达成"参与判定
FISH_UNSUPPORTED = ("chain", "clear", "rank", "over_power_range")


def _load_optional_json(filepath, use_cache=True):
    """读一份可能不存在的曲库；缺失只意味着少几个筛选项，不该让建档失败。"""
    try:
        if filepath and os.path.exists(filepath):
            return load_config(filepath, use_cache=use_cache)
    except Exception as e:
        print(f"⚠️ 读取曲库 {filepath} 失败: {e}")
    return None


def cn_version_titles():
    """落雪 version 整数 -> 版本标题（'CHUNITHM VERSE'）。这份表 song/list 有、本地曲库没有。"""
    meta = _load_optional_json(cn_song_meta_path) or {}
    return {entry["version"]: entry["title"] for entry in meta.get("versions") or [] if entry.get("version") is not None}


def cn_filter_assets(server):
    """
    加载补齐派生字段所需的曲库。

    落雪的新曲版本集合优先用「版本标题 ∈ 水鱼 /latest_version」判定 —— 两家是同一个
    事实的两种写法（22500 = CHUNITHM LUMINOUS PLUS），比"取最高两个 version"这个猜测强。
    拿不到水鱼那份时就退回两高版本规则，并标 new_versions_authoritative=False。
    """
    songs = _load_optional_json(music_info_path)
    aliases = build_alias_index(songs)
    if server == "fish":
        music = _load_optional_json(fish_music_info_path)
        latest = _load_optional_json(fish_latest_version_path)
        return {
            "chart_index": build_fish_chart_index(music) if music else None,
            "alias_index": aliases,
            "latest_versions": (latest or {}).get("version") or None,
            # 水鱼的版本是标题字符串，要并成"代"就得靠落雪这份 整数↔标题 表换算；
            # 缺了它，22 个标题会各自成一代，版本筛选一档都并不起来。
            "version_titles": cn_version_titles(),
        }

    versions = sorted({s.get("version") for s in songs or [] if s.get("version") is not None})
    titles = cn_version_titles()
    latest = _load_optional_json(fish_latest_version_path)
    latest_titles = set((latest or {}).get("version") or [])
    authoritative = bool(latest_titles) and bool(titles)
    if authoritative:
        new_versions = [v for v in versions if titles.get(v) in latest_titles]
    else:
        new_versions = versions[-2:]
    # 曲库里有、却比窗口最高档还高的档位：说明水鱼的版本表落后于落雪（上游已出新版本）。
    # 这些曲子会被留在旧曲组 —— 不算错，但必须能说出来，不然像是筛选出了问题。
    ahead = [v for v in versions if new_versions and v > max(new_versions)]
    return {
        "song_index": build_lxns_song_index(songs),
        "alias_index": aliases,
        "new_versions": new_versions,
        "new_versions_ahead": ahead,
        "version_titles": titles,
        "new_versions_authoritative": authoritative,
    }


def cn_filter_options(server, assets):
    """
    曲风 / 版本 / 曲师 / 谱师的下拉选项来自曲库实际值域。
    写死枚举会让用户点到一个必然 0 命中的选项，还看不出原因。
    曲库缺失时返回 None，界面据此把这几项置灰而不是报错。
    """
    if server == "fish":
        entries = (assets or {}).get("chart_index")
        if not entries:
            return None

        def split(entry):
            info = entry.get("basic_info") or {}
            return (info.get("genre"), info.get("from"), info.get("artist"),
                    [chart.get("charter") for chart in entry.get("charts") or []])
    else:
        entries = (assets or {}).get("song_index")
        if not entries:
            return None

        def split(entry):
            return (entry.get("genre"), entry.get("version"), entry.get("artist"),
                    [chart.get("note_designer") for chart in (entry.get("_charts") or {}).values()])

    titles = (assets or {}).get("version_titles") or {}

    def display(value):
        return value if server == "fish" else (titles.get(value) or str(value))

    # 水鱼那份是版本标题，要靠落雪版本表换算成同一个"代"；换算不出的（'中二节奏 2024'
    # 这类国服旧命名）自成一代，绝不错并。
    title_to_generation = {str(title).strip().lower(): int(num // VERSION_GENERATION)
                           for num, title in titles.items() if title}

    genre, version, artist, charter = set(), set(), set(), set()
    for entry in entries.values():
        g, v, a, c = split(entry)
        genre.update(x for x in [g] if x)
        artist.update(x for x in [a] if a)
        version.update(x for x in [v] if v is not None)
        charter.update(x for x in c if x)

    flat = sorted(version, key=version_sort_key)
    groups = group_versions(flat, title_to_generation)
    order = sorted(groups, key=lambda gen: version_sort_key(groups[gen][0]))
    group_labels = {}
    for gen in order:
        names = [display(v) for v in groups[gen]]
        group_labels[gen] = names[0] if len(names) == 1 else f"{names[0]}（含 {'、'.join(names[1:])}）"
    return {
        "genre": sorted(genre),
        "artist": sorted(artist),
        "charter": sorted(charter),
        # 版本按"代"勾：国服的一个版本在数据里是两档（主版本 + 它的 PLUS），
        # 逐档列会让人选一次漏一半。选中后由界面展开成具体档位再交给谓词。
        "version": order,
        "version_members": {gen: groups[gen] for gen in order},
        "version_group_labels": group_labels,
        # 「哪些版本算新曲」必须逐档跟水鱼的版本表对齐，不能用代 —— 它的窗口是
        # LUMINOUS PLUS + VERSE，跨在两代之界上，按代就表达不出来了。
        "version_flat": flat,
        "version_labels": {v: display(v) for v in flat},
    }


def selected_parts(best_or_new, include_selections=False):
    if best_or_new == "仅旧曲":
        return [PART_BEST]
    if best_or_new == "仅新曲":
        return [PART_NEW]
    return [PART_BEST, PART_SELECT, PART_NEW] if include_selections else [PART_BEST, PART_NEW]


def _fetch_cn_pool(server, pool_source, params):
    """取一次候选池原始响应，返回 (raw, error)。"""
    from utils.OAuthUtils import (FISH_QUERY_PLAYER_URL, FISH_PLAYER_RECORDS_URL,
                                  LXNS_BESTS_URL, LXNS_SCORES_URL)
    if server == "fish":
        if pool_source == POOL_FULL:
            # /player/records 是 GET，服务端过滤参数就挂在这里；简略模式没有过滤能力
            return _fish_authorized_request(FISH_PLAYER_RECORDS_URL, params=params or None)
        return _fish_authorized_request(FISH_QUERY_PLAYER_URL, method="POST", json_body={})
    if pool_source == POOL_FULL:
        return _lxns_authorized_request(LXNS_SCORES_URL)
    return _lxns_authorized_request(LXNS_BESTS_URL)


def fetch_cn_pool_raw(server, pool_source):
    """预览用：拉一份未筛选的原始候选池响应，返回 (raw, error)。缓存它才能零请求重算。"""
    return _fetch_cn_pool(server, pool_source, None)


def _normalize_pool(server, pool_source, raw, assets, include_selections=False):
    if server == "fish":
        if pool_source == POOL_FULL:
            return normalize_fish_records(raw, assets["chart_index"], assets["latest_versions"],
                                          assets["alias_index"])
        return normalize_fish_b50(raw, assets["chart_index"], assets["alias_index"])
    # selections 是落雪自己的排名层，扁平完整历史里恢复不出来，只有简略成绩带这个数组
    return normalize_lxns(raw, assets["song_index"], assets["new_versions"],
                          include_selections=include_selections)


def build_cn_pool(server, best_or_new, pool_source=POOL_BRIEF, filter_mode=MODE_LOCAL,
                  spec=None, caps=None, include_selections=False, raw=None, assets=None,
                  new_versions=None, group_parts=True):
    """
    取数 → 规范化 →（服务端模式先粗筛一次）→ 本地精筛 → 分组截断 → 按原形状重建 raw。

    两条链路都以同一套本地谓词收尾：服务端参数只负责把候选集缩小，不承担正确性。
    返回 {"raw", "prefixes", "hits", "data_field", "stats", "params", "dropped", "assets"}，
    raw 交给 _process_b50_data 走原来的清洗，b50_raw.json 溯源照旧。

    Args:
        raw: 已经取好的响应（预览复用缓存时用），传了就不再请求。
        assets: 界面已加载的曲库索引，传了就不重复建。
        new_versions: 覆盖自动判定的落雪"新曲版本集合"（用户手选时传）。
    """
    spec = spec or {}
    assets = assets or cn_filter_assets(server)
    if new_versions is not None and server == "lxns":
        assets = dict(assets, new_versions=list(new_versions))

    params, dropped = ({}, [])
    if filter_mode == MODE_SERVER and server == "fish" and pool_source == POOL_FULL:
        params, dropped = to_fish_params(spec)

    error = None
    if raw is None:
        raw, error = _fetch_cn_pool(server, pool_source, params)
    if error:
        raise Exception(error)

    items = _normalize_pool(server, pool_source, raw, assets, include_selections)
    unsupported = list(FISH_UNSUPPORTED) if server == "fish" else []
    unsupported = [key for key in unsupported if spec_is_active(spec, key)]

    hits, stats = apply_filters(items, spec, unsupported=unsupported)
    if not group_parts:
        # 不分新旧：筛完就是最终名单，一律算 Best 一组，由单一上限按 Rating 降序截断。
        # 版本窗口在这种模式下没有任何用途（它唯一的职责就是切新旧），不读它。
        for item in hits:
            item["_part"] = PART_BEST
    hits = cap_parts(hits, caps)

    wanted = {PART_BEST} if not group_parts else set(selected_parts(best_or_new, include_selections))
    groups = group_by_part(hits)
    ordered = [item for part in PART_ORDER if part in wanted for item in groups.get(part, [])]

    paths = _PART_PATHS[(server, pool_source)]
    rebuilt = dict(raw) if isinstance(raw, dict) else {}
    container_key = _RAW_CONTAINER[server]
    # 落雪的完整历史是扁平 Score[]，没有分层结构可继承，三组要凭分组结果凭空搭出来
    origin = rebuilt.get(container_key)
    container = dict(origin) if isinstance(origin, dict) else {}
    data_field, leaves = [], {}
    # 先给每个入选分组腾出空数组：命中 0 条时 raw 也必须真的是空的，
    # 否则下游会读到原样保留的未筛选响应，做出一份"看起来成功"的错存档。
    for part in PART_ORDER:
        if part not in wanted or part not in paths:
            continue
        path, leaf = paths[part], paths[part].split(".")[1]
        leaves.setdefault(leaf, [])
        if path not in data_field:
            data_field.append(path)
        leaves[leaf].extend(item["_raw"] for item in groups.get(part, []))
    # 未入选的叶子也要清空（"仅旧曲"与不分新旧组时，落雪的 new_bests / 水鱼的 n20
    # 会原样留在这份溯源里，日后按默认路径重读就是筛过和没筛过混在一起）
    for path in paths.values():
        leaves.setdefault(path.split(".")[1], [])
    # 整体替换而不是往原数组上追加：原样保留的分组里还躺着未筛选的整份响应
    container.update(leaves)
    rebuilt[container_key] = container

    stats["pool_source"] = pool_source
    stats["grouped"] = group_parts
    stats["filter_mode"] = filter_mode if (server == "fish" and pool_source == POOL_FULL) else MODE_LOCAL
    if pool_source == POOL_FULL:
        # 曲库查不到的记录没有版本，新旧判定会把它们一律留在旧曲组 —— 不报出来就是静默改变存档内容
        stats["no_version"] = sum(1 for item in items if item["_version"] is None)
    return {
        "raw": rebuilt,
        "prefixes": [item["_part"] for item in ordered],
        "hits": ordered,
        "data_field": data_field if len(data_field) > 1 else data_field[0],
        "stats": stats,
        "params": params,
        "dropped": dropped,
        "assets": assets,
    }


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

# def should_update_metadata(threshold_hours=24):
#     """
#     检查是否需要更新乐曲元数据
    
#     Args:
#         threshold_hours: 更新的时间阈值（小时）
        
#     Returns:
#         bool: 是否需要更新
#     """
#     # 在用户目录下创建配置目录
#     config_dir = Path.home() / ".chu-gen-videob30"
#     config_dir.mkdir(exist_ok=True)
    
#     config_file = config_dir / "metadata_update.json"
    
#     current_time = datetime.now()
    
#     # 如果配置文件不存在，则创建并立即返回True
#     if not config_file.exists():
#         # with open(config_file, "w") as f:
#         #     json.dump({"last_update": current_time.isoformat()}, f)
#         save_config(config_file, {"last_update": current_time.isoformat()})
#         return True
    
#     # 读取上次更新时间
#     try:
#         data = load_config(config_file)
#         last_update = datetime.fromisoformat(data.get("last_update", "2000-01-01T00:00:00"))
#     except (json.JSONDecodeError, ValueError):
#         # 文件损坏或格式错误，重新创建
#         # with open(config_file, "w") as f:
#         #     json.dump({"last_update": current_time.isoformat()}, f)
#         save_config(config_file, {"last_update": current_time.isoformat()})
#         return True
    
#     # 计算时间差
#     time_diff = current_time - last_update
#     if time_diff.total_seconds() / 3600 >= threshold_hours:
#         # 更新时间戳
#         save_config(config_file, {"last_update": current_time.isoformat()})
#         return True
    
#     return False

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
        response = _get_with_retry(url, headers={"User-Agent": MUSIC_DATA_USER_AGENT})
        if response.status_code != 200:
            _note_fetch_failure(name, _blocked_reason(response))
            return

        raw_data = safe_decode(response.content)
        data = json.loads(raw_data)
        # print(f"📦 （{name}）返回内容预览：\n{raw_data[:200]}")
        if transformer:
            data = transformer(data)
        remote_hash = json_hash(data)   # 国服的版本身份：内容哈希（首页表格与日志 [md5] 同源）

        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            save_config(filepath, data)
            _record_data_version(filepath)
            _record_content_hash(filepath, remote_hash)
            print(f"✅ （{name}）已下载所需的谱面数据[{remote_hash}]")
            return

        local_hash = json_hash(load_config(filepath))

        if remote_hash != local_hash:
            save_config(filepath, data)
            _record_data_version(filepath)
            _record_content_hash(filepath, remote_hash)
            print(f"🔄［{name}］谱面数据成功更新[{remote_hash}]")
        else:
            # 内容没变就不重写文件，但要把 mtime 顶上去：启动自动更新拿它当"上次确认新鲜"的时刻，
            # 否则这份没有 ETag 的来源每次开机都会被判定过期、白拉一遍全量。
            os.utime(filepath, None)
            _record_content_hash(filepath, remote_hash)   # 对端确认同版 → "云端上次检查"刷新为这一版
            print(f"☑️［{name}］谱面数据已是最新[{local_hash}]")

    except Exception as e:
        _note_fetch_failure(name, f"取数出错：{e.__class__.__name__} {e}")

# 这条镜像链路实测会在三种 UA 之间随机出现连接重置 / 读超时（不是放行规则，对端就是不稳）。
# 一次抖动就跳过整轮、还要等退避期满，代价太大 —— 同一轮内先短促重试两次。
LIBRARY_RETRY_ATTEMPTS = 3
LIBRARY_RETRY_DELAY = 0.6


def _get_with_retry(url, headers=None, timeout=30):
    """
    只对连接层抖动重试；对方明确回了状态码（403/500/…）就不再敲第二次门。

    异常类实时从 requests 上取、且只取 RequestException：测试替身会整块换掉这个模块，
    按 ConnectionError / Timeout 这些子类名取属性，会让错误处理自己抛 AttributeError。
    """
    last = None
    for attempt in range(LIBRARY_RETRY_ATTEMPTS):
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last = e
            if attempt + 1 < LIBRARY_RETRY_ATTEMPTS:
                time.sleep(LIBRARY_RETRY_DELAY * (attempt + 1))
    raise last


def _blocked_reason(response):
    """
    区分"上游回了一张 HTML 页（挑战页 / 错误页）"与普通的非 200。

    反代、CDN、被限流的源站都可能直接回一段 HTML，状态码还常常是 200。这类响应不能落盘，
    但也要跟"上游 500""响应不是 JSON"分开说 —— 三件事，该给用户的话不一样。
    """
    body = response.content or b""
    head = safe_decode(body[:800]).lower() if body else ""
    challenged = "<html" in head or "just a moment" in head or "attention required" in head \
        or "enable javascript and cookies" in head
    if challenged:
        return f"返回的是验证/错误页而不是数据（HTTP {response.status_code}）"
    return f"获取失败，状态码 {response.status_code}"


def _note_fetch_failure(name, reason):
    """失败原因留给界面看 —— 更新没生效却什么都不说，用户只会反复点同一个按钮。"""
    _music_state["last_error"] = f"{name}：{reason}"
    print(f"⚠️［{name}］{reason}，沿用本地副本")


status_sources_path = f'{music_status_dir}/sources.json'   # 各源的条件请求记账
status_local_path = f'{music_status_dir}/local.json'        # 本机这一轮：云端状态 + 退避记录
status_versions_path = f'{music_status_dir}/versions.json'  # 各源产物的内容变更时刻：只有真的下载到新数据才前进，304 / 比对无变化都不碰它


def _read_status(path):
    """记账必须现读：load_config 的缓存按路径存 60 秒，拿旧 etag 出门会白拉一次全量。"""
    return _load_optional_json(path, use_cache=False) or {}


def _patch_status(path, **sections):
    """按键合并写回。写者只有后台那一轮，且都在同一线程里顺序发生，不做并发锁。"""
    ensure_status_dir()
    current = _read_status(path)
    for key, value in sections.items():
        old = current.get(key)
        current[key] = {**old, **value} if isinstance(value, dict) and isinstance(old, dict) else value
    save_config(path, current)
    return current


# 记账合并成一份后，源名就是文件里的键：写错不会报错、只会多一个孤儿键，所以只认这份名单
STATUS_SOURCE_KEYS = ("jp_songs_info", "intl_songs_info", "fish_music_data")


def _fetch_json_etag(name, url, filepath, source=None, transformer=None, version_time=None):
    """
    带 ETag 的公共 JSON 拉取：200 落盘并记下 etag，304 只刷时间戳，网络失败沿用本地副本。

    这几个端点无需验证，不占认证调用的每日配额；source 为 None 表示该端点不支持条件请求
    （例如 latest_version 不发 ETag），每次都重取。记账统一写在 status/sources.json 的这个键下。
    transformer 用来把原始响应转成落盘形状（日服要重命名难度键、补别名）。
    version_time：落盘数据对应的云端版本时刻（Worker meta 的 written_at）。有它记它，
    没有才退回"到手时刻"；304 分支同样用它对齐版本记账（对端确认了这份就是现役版本）。
    """
    headers = {"User-Agent": MUSIC_DATA_USER_AGENT}   # 便于对端日志认人，不是放行凭据
    if source and source not in STATUS_SOURCE_KEYS:
        # 名字不认识就别写进记账（宁可每轮全量重取，也不要在文件里留孤儿键）
        _note_fetch_failure(name, f"记账源名不合法（{source!r}），本次不记 etag")
        source = None
    stored = _read_status(status_sources_path).get(source) if source else None
    # 产物文件已经不在了就别再发条件请求：304 会让我们以为一切正常，
    # 而那个文件永远没有机会被重建出来。
    if stored and stored.get("etag") and os.path.exists(filepath):
        # 原样带回（含 W/ 前缀与引号），自己再加一层引号就变成双重引号、永远不命中
        headers["If-None-Match"] = stored["etag"]

    try:
        response = _get_with_retry(url, headers=headers)
    except requests.exceptions.RequestException as e:
        _note_fetch_failure(name, f"网络不通（{e.__class__.__name__}，已重试 {LIBRARY_RETRY_ATTEMPTS} 次）")
        return False

    if response.status_code == 304:
        _patch_status(status_sources_path, **{source: {"last_update": datetime.now().isoformat()}})
        # 304 就是"这份本地副本仍然新鲜"的确认，但产物文件没被重写。启动自动更新拿 mtime
        # 当上次确认时刻，不把时间顶上去，每次开机都会把这一份判成过期、天天全量重拉。
        os.utime(filepath, None)
        # 对端确认了我们手里的 etag 就是现役版本 → 版本记账直接对齐到 meta 的 written_at。
        # 不对齐的话，早前任何一轮"meta 读到了新版、产物却没取成"（镜像 403 是常态）都会
        # 让一份其实已是最新的副本，从此永远挂着"⬇️ 有新版"。
        if version_time:
            _record_data_version(filepath, version_time)
        print(f"☑️［{name}］谱面元数据已是最新（304）")
        return False
    if response.status_code != 200:
        _note_fetch_failure(name, _blocked_reason(response))
        return False

    try:
        data = json.loads(safe_decode(response.content))
    except ValueError as e:
        # 镜像也可能被换成一张错误页；解析不动就继续用本地那份，别把整轮更新带走
        _note_fetch_failure(name, "响应非合法 JSON"
                            + ("（HTML 页？）"
                               if (response.content or b"").lstrip()[:1] == b"<" else f"：{e}"))
        return False
    if transformer:
        data = transformer(data)

    try:
        save_config(filepath, data)
    except OSError as e:
        # 后台线程写、前台在读同一份文件时会撞上。这份跳过就行 ——
        # 旧副本仍然完整可读，别让一份被占用把日服、水鱼那几份一起带走。
        print(f"⚠️［{name}］本地副本正被占用，本次跳过更新: {e}")
        return False
    _record_data_version(filepath, version_time)   # 内容真的换了才会走到这里；304 分支另作对齐
    if not version_time:
        # 无云端时间戳的源（水鱼等）：内容哈希就是版本身份，记下"上次对端返回的哈希"
        _record_content_hash(filepath, json_hash(data))
    if source:
        try:
            _patch_status(status_sources_path, **{source: {"etag": response.headers.get("ETag"),
                                                           "last_update": datetime.now().isoformat()}})
        except OSError as e:
            # 数据已经落盘了，记账没写上不该把这一路判成失败（下一轮多拉一次全量而已）
            print(f"⚠️［{name}］etag 记账没写进去，下一轮会重取全文: {e}")
    print(f"✅［{name}］谱面元数据已更新")
    return True


def fetch_intl_music_data():
    """
    国际服曲库：自己维护的 R2 产物（cloudflare/music-db 的 Worker 清洗后写入）。

    上游是 wiki 风格的导出，必须清洗过才能用，所以这里没有"直连兜底"可言 ——
    URL 没配就什么都不做，让国际服定数继续用本地那份副本，别发一次注定失败的请求。
    """
    if not intl_music_info_url:
        print("⏭️ 未配置 INTL_MUSIC_URL，跳过国际服曲库更新")
        return False
    job = (read_upstream_status().get("jobs") or {}).get("intl") or {}
    return _fetch_json_etag("国际服", intl_music_info_url, intl_music_info_path, "intl_songs_info",
                            version_time=job.get("written_at"))


# --- Worker 侧同步状态 --------------------------------------------------------------
# 桶里那两个 meta 对象就是 Worker 每轮写的"上次结果"（等价于 GET /status），读回本地缓存一份，
# 首页就有得显示。它们与产物同源，所以不引入第二个域名；cron 有没有按时跑、有没有 aborted，
# 从这台机器就能看见，不用开 Cloudflare 面板。
# 只缓存界面真要显示的字段。source_url / augment_url 是 Worker 那边的上游地址（在
# wrangler.toml 里），两个 *_etag 是它做条件请求的记账 —— 抄回本地只会多一份没人读、
# 又迟早过期的"第二真相"。
UPSTREAM_FIELDS = ("source_rows", "kept", "joined", "augmented", "degraded",
                   "last_error", "written_at")


def ensure_status_dir():
    """save_config 不创建父目录，status/ 不存在时整轮更新会直接抛错。"""
    os.makedirs(music_status_dir, exist_ok=True)


UPSTREAM_SECTION = "upstream"        # status/local.json 里的这一段：Worker 侧上次结果
R2_WRITE_STALE_DAYS = 40      # cron 是每月一次，超过这么多天没写过就该问一句


def read_upstream_status():
    return _read_status(status_local_path).get(UPSTREAM_SECTION) or {}


def r2_meta_urls():
    """产物键名固定是 <名>.json，meta 就在它旁边 —— 从 URL 推，避免再写一份常量对不上。"""
    out = {}
    for key, url in (("intl", intl_music_info_url), ("jp", jp_music_info_url)):
        if url and url.endswith(".json"):
            out[key] = url[:-len(".json")] + ".meta.json"
    return out


def fetch_r2_status():
    """
    读回 Worker 的 meta 并缓存。只在"真读到"时才更新缓存，且一个都没读到时原封不动 ——
    这份是诊断信息，一次 403 不该把已知的同步历史刷成空白，也不该被算成曲库缺口。
    """
    urls = r2_meta_urls()
    if not urls:
        return None
    fresh = {}
    for key, url in urls.items():
        try:
            response = requests.get(url, headers={"User-Agent": MUSIC_DATA_USER_AGENT}, timeout=15)
            if response.status_code == 200:
                job = json.loads(safe_decode(response.content))
                fresh[key] = {k: job.get(k) for k in UPSTREAM_FIELDS if k in job}
            else:
                print(f"⚠️ [{key}] API 返回 {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"⚠️ [{key}] API 请求失败: {e.__class__.__name__}")
        except ValueError as e:
            print(f"⚠️ [{key}] 返回非合法 JSON: {e}")
    if not fresh:
        return None
    cached = read_upstream_status()
    # 缓存侧也要按同一份白名单过一遍：某个 job 这轮没读到时是把上次记录原样搬回去，
    # 不过一遍的话早年存下的 source_url / etag 会一直赖在文件里。
    jobs = {key: {f: value.get(f) for f in UPSTREAM_FIELDS if f in value}
            for key, value in (cached.get("jobs") or {}).items() if isinstance(value, dict)}
    jobs.update(fresh)
    try:
        _patch_status(status_local_path, **{UPSTREAM_SECTION: {
            "fetched_at": datetime.now().isoformat(), "jobs": jobs}})
    except OSError as e:
        print(f"⚠️ 同步状态缓存写失败: {e}")
    return jobs


def _coerce_cloud_stamp(value):
    """Worker meta 的 written_at（toISOString 生成的 UTC ISO，可能带毫秒和 Z）→ 统一成带时区的 ISO。

    沿用云列显示的同一套解析（截前 19 位按 UTC 理解），保证同步状态下"本地数据版本"
    和"云端数据版本"两列渲染出同一个时刻 —— 两列要可比，就必须是同一口钟的时间。
    """
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _parse_stamp(value):
    """版本时间字符串 → 本机时区的 datetime；解析不动返回 None。

    记账里的新记录都带时区（UTC 的 written_at / 本机的到手时刻）；早期只有 now()
    的 naive 记录按本机时区理解。
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone()
    except (TypeError, ValueError):
        return None


def _fmt_r2_stamp(stamp):
    """meta 里的时间是 UTC ISO；显示成机器本地时间，否则"20:10"和北京时间差 8 小时没人看得出来。"""
    parsed = _parse_stamp(_coerce_cloud_stamp(stamp))
    return parsed.strftime("%m-%d %H:%M") if parsed else "?"


def _r2_age_days(stamp):
    try:
        parsed = datetime.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed).days
    except (TypeError, ValueError):
        return None


def _library_count(path):
    """曲库规模。解析走 _load_optional_json 的 60 秒缓存，不会每次交互都重读几 MB。"""
    data = _load_optional_json(path)
    if data is None:
        return None
    if isinstance(data, dict):
        data = data.get("songs") or data.get("data") or []
    return len(data)


def _local_stamp(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return "—"
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m-%d %H:%M")


def _record_data_version(filepath, version_time=None):
    """记下这份数据的版本时刻，给首页"本地数据版本"列用。

    镜像源（日服/国际服）取数前会先读 Worker meta，把 written_at 一并记下 —— 这样
    "本地这份是云端哪一版"和"云端现在是哪一版"才是同一口钟的时间，表里两列才可比；
    没有云端版本的源（国服/水鱼）退回内容到手时刻，它们的"云端数据版本"本来就是"—"。
    记账写失败只损失显示精度（该行退回文件时间），不该影响取数本身 —— 与 etag 记账同一种容忍度。
    """
    stamp = _coerce_cloud_stamp(version_time) if version_time else None
    stamp = stamp or datetime.now().astimezone().isoformat()
    try:
        _patch_status(status_versions_path, stamps={filepath: stamp})
    except OSError as e:
        print(f"⚠️ 数据版本时间没记上（该行显示会退回文件时间）: {e}")


def _read_data_version(path):
    """versions.json 里这份产物记录的版本时间（ISO 字符串）；没有记录返回 None。"""
    return (_read_status(status_versions_path).get("stamps") or {}).get(path)


def _data_stamp(path):
    """首页"本地数据版本"列：这份副本对应的版本时刻。

    镜像源显示云端 written_at（本地这份是云端哪一版），其余源显示内容到手时刻 ——
    都不是"最近一次保存 / 确认时刻"：304 和"内容没变"只顶 mtime（新鲜度记账），
    不推进版本。升级前落盘的旧数据没有记录，退回 mtime 兜底。
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return "—"
    parsed = _parse_stamp(_read_data_version(path))
    return parsed.strftime("%m-%d %H:%M") if parsed else _local_stamp(path)


def _content_hash(path):
    """无云端版本号的源（国服[落雪]/国服[水鱼]）的版本身份：内容哈希短码。

    与更新日志 ☑️［国服］谱面数据已是最新[md5] 的方括号同一来源（json_hash）——
    内容没变就是同一版，比"到手时刻"更直接地回答"这是哪一版"。数据走
    _load_optional_json 的 60 秒缓存，哈希本身只是一次 dumps+md5，渲染开销可忽略。
    """
    data = _load_optional_json(path)
    if data is None:
        return None
    return json_hash(data)[:8]


def _record_content_hash(filepath, digest):
    """记下"上次取数时对端返回的内容哈希"，给首页"云端数据版本"列用（无云端版本的源）。

    本地副本要么是远端原样落盘、要么被确认与远端同版，成功取数后两者必然同码；
    记账写失败只损失显示（该列退回本地哈希），不影响取数本身。
    """
    try:
        _patch_status(status_versions_path, hashes={filepath: str(digest)})
    except OSError as e:
        print(f"⚠️ 内容哈希没记上（云端列会退回本地哈希）: {e}")


def _read_remote_hash(path):
    """versions.json 里记录的"上次取数时对端返回的内容哈希"；没有记录返回 None。"""
    return (_read_status(status_versions_path).get("hashes") or {}).get(path)


# 首页表格的行：归属、用途、产物路径、缺口名单里的名字、云端 meta 的键（None = 该源没有云端 meta）
LIBRARY_ROWS = (
    ("国服[落雪]", "曲目与别名", music_info_path, "国服曲库", None),
    ("国服[水鱼]", "曲师/曲风/BPM/版本", fish_music_info_path, "水鱼曲库", None),
    ("国际服", "国际服定数", intl_music_info_path, "国际服曲库", "intl"),
    ("日服", "日服定数与版本参照", jp_music_info_path, "日服曲库", "jp"),
)


def music_library_status(local_note=None):
    """
    首页那行曲库状态 + 曲库详情表。返回 {"brief", "table", "summary", "problems", "rows"}。

    拆几样是给页面用的：brief 是正文里那行一句话状态（正常时按服务器归组报曲目数，页面以
    提示框呈现），表格是详情（收进"附加设置"折叠栏），problems 是"要不要在页顶告警"。
    新鲜度只认 music_data_gaps 那一套 mtime 口径，不在这里另算一份；本机这轮取数的结果
    也汇进来（local_note），免得页面自己拼一遍、这里拼一遍，最后两边说法不一致。
    注意"本地数据版本"一列不走 mtime：镜像源记的是云端 written_at（本地这份是云端
    哪一版），无云端版本的源（国服[落雪]/国服[水鱼]）记内容哈希短码 —— 上游不发布
    版本时间，内容哈希就是版本身份（与更新日志 [md5] 同源），云端列同理记"上次取数
    时对端返回的哈希"；mtime 只是新鲜度记账，304 和"内容没变"都会把它顶上去。
    镜像源两列同用 written_at 这一口钟：本地落后于云端现役版本时，同步状态给
    "⬇️ 有新版"（不是故障 —— 16 天窗口内下次启动检查会自动拉平，不进 problems）。
    国服两行的"有新版"探测就是取数时的哈希比对本身（不同即当场下载），不存在
    挂着的待取状态。
    """
    cached = read_upstream_status()
    jobs = cached.get("jobs") or {}
    missing, stale = music_data_gaps()
    problems = ([f"本机：{local_note}"] if local_note else [])
    problems += [f"{name} 收取失败 + 本地无副本" for name in missing]
    problems += [f"{name} 超过 {MUSIC_DATA_STALENESS_HOURS // 24} 天未更新成功" for name in stale]

    rows = []
    for server, source, path, gap_name, job_key in LIBRARY_ROWS:
        name = server        # 归属列自己已写明来源（国服[落雪]），problems 不再重复一遍
        count = _library_count(path)
        job = (jobs.get(job_key) if job_key else None) or {}
        upstream = _fmt_r2_stamp(job["written_at"]) if job.get("written_at") else "—"
        age = _r2_age_days(job.get("written_at")) if job.get("written_at") else None
        state = "⚠️ 偏旧" if gap_name in stale else "✅ 已是最新"
        if count is None:
            state = "⚠️ 缺失"
            if os.path.exists(path) and os.path.getsize(path) > 0:
                # 文件在却解析不动：缺口名单按"文件是否存在"记账，不会报它 —— 不说就是又一个静默
                problems.append(f"{name}：本地数据读取失败（文件可能损坏，可尝试强制更新重建）")
        if job.get("last_error"):
            # 中断那轮不会覆盖产物，meta 里的统计还是上一轮的 —— 不说破就是一组看着很绿的假数
            state = "⚠️ 云端中断"
            problems.append(f"{name}：云端上次中断（{job['last_error']}），统计数据未更新")
        if job.get("degraded"):
            state = "⚠️ 云端降级"
            problems.append(f"{name}：云端降级出货（{job['degraded']}），版本/谱师列可能有缺")
        if age is not None and age > R2_WRITE_STALE_DAYS:
            problems.append(f"{name}：镜像已 {age} 天未更新")
        if state == "✅ 已是最新":
            # 同一口钟的对比：本地这份的版本落后于云端现役版本 → 有新版可拉。
            # 只在"正常"时覆盖 —— 缺失/偏旧/云端问题说的是更要紧的事。
            # 两侧都截到整秒再比：meta 的 written_at 带毫秒（…T20:01:04.853Z），记账归一时
            # 只存到秒，不截的话同一个版本会因这零点几秒被永远判成"⬇️ 有新版"。
            local_dt = _parse_stamp(_read_data_version(path))
            cloud_dt = _parse_stamp(job.get("written_at"))
            if local_dt and cloud_dt and local_dt.replace(microsecond=0) < cloud_dt.replace(microsecond=0):
                state = "⬇️ 有新版"
        if job_key is None:
            # 国服这类源上游不发布版本时间，内容哈希就是版本身份 —— 与更新日志
            # ☑️［国服］谱面数据已是最新[md5] 的方括号同源；没有云端列可对比，
            # "有新版"的探测就是取数时的哈希比对本身（不同即当场下载）。
            # 云端列记"上次取数时对端返回的哈希"；尚未记账时用本地哈希兜底 ——
            # 副本要么是远端原样落盘、要么被确认同版，两者本来就是同一个码。
            local_code = _content_hash(path)
            version_cell = local_code or _data_stamp(path)
            upstream_cell = (_read_remote_hash(path) or "")[:8] or local_code or "—"
        else:
            version_cell = _data_stamp(path)
            upstream_cell = upstream
        rows.append([server, source, str(count) if count is not None else "读取失败",
                     version_cell, upstream_cell, state])

    header = "| 归属 | 用途 | 曲目数 | 本地数据版本 | 云端数据版本 | 同步状态 |"
    rule = "|---|---|---|---|---|---|"
    table = "\n".join([header, rule] + ["| " + " | ".join(r) + " |" for r in rows])
    summary = "曲库状态：一切正常" if not problems else f"曲库状态：{len(problems)} 项需要注意"
    # 正文那行：有问题时页面直接展示 problems，它就退回 summary；正常时报四个数就够。
    # 落雪和水鱼都是国服的数据源，按服务器归组 —— 别让"水鱼"在一行里看起来像第四台服务器
    grouped = []
    for r in rows:
        server, _, bracket = r[0].partition("[")
        source = bracket.rstrip("]") or None   # 名字没带 [来源] 的（国际服/日服）本身就是服务器
        if grouped and grouped[-1][0] == server:
            grouped[-1][1].append((source, r[2]))
        else:
            grouped.append((server, [(source, r[2])]))
    parts = []
    for server, items in grouped:
        if len(items) == 1:
            parts.append(f"{server} {items[0][1]}")
        else:
            parts.append(f"{server}（" + " · ".join(f"{s} {c}" for s, c in items) + "）")
    joined = ""
    for i, part in enumerate(parts):
        # 全角"）"自带右侧留白，后面接"·"时不再补空格
        joined += ("" if i == 0 else "· " if joined.endswith("）") else " · ") + part
    brief = summary if problems else "曲库就绪：" + joined
    return {"table": table, "summary": summary, "problems": problems, "rows": rows, "brief": brief}


def fetch_fish_music_data():
    """水鱼曲库 + 最新版本表。缺了它们筛选面板只是少几个元数据类条件，不硬失败。"""
    from utils.OAuthUtils import FISH_MUSIC_DATA_URL, FISH_LATEST_VERSION_URL
    _fetch_json_etag("水鱼曲库", FISH_MUSIC_DATA_URL, fish_music_info_path, "fish_music_data")
    _fetch_json_etag("水鱼版本表", FISH_LATEST_VERSION_URL, fish_latest_version_path)


def fetch_music_data():
    """
    获取谱面数据
    """
    print("🔄️ 开始更新谱面数据...")
    ensure_status_dir()   # etag 记账都写在 status/ 下，save_config 不会自己建目录
    
    # 1. 获取国服别名数据
    alias_map = {}
    try:
        response = _get_with_retry(f"{LXNS_API_ENDPOINT}/alias/list",
                                   headers={"User-Agent": MUSIC_DATA_USER_AGENT})
        if response.status_code == 200:
            aliases_data = response.json()
            for alias_item in aliases_data.get("aliases", []):
                alias_map[str(alias_item["song_id"])] = alias_item["aliases"]
            print(f"📋 已获取 {len(alias_map)} 条别名数据")
    except Exception as e:
        print(f"⚠️ 获取别名数据失败: {e}")
    
    # 2. 通用函数：为歌曲添加别名
    def add_aliases(songs, id_field):
        for song in songs:
            song_id = str(song.get(id_field, ""))
            song["aliases"] = alias_map.get(song_id, [])
        return songs
    
    # 3. 获取国服数据（使用 id 字段）
    def cn_transformer(data):
        # versions / genres 两张表原本被丢掉，筛选项要拿它们做取值域和"版本标题 -> version 整数"的对照
        meta = {key: data.get(key) for key in ("versions", "genres") if key in data}
        if meta:
            save_config(cn_song_meta_path, meta)
        return add_aliases(data.get("songs", []), "id")

    _fetch_music_data(
        name="国服",
        url=song_data_cn,
        filepath=music_info_path,
        transformer=cn_transformer
    )
    
    def jp_transformer(data):
        # 日服数据直接是列表，不是字典
        songs = data if isinstance(data, list) else data.get("songs", [])
        
        for song in songs:
            # 转换难度名称
            if "data" in song:
                song["data"] = {
                    DIFFICULTY_MAP.get(k, k): v for k, v in song["data"].items()
                }
            
            # 添加别名（使用 meta.idx 或直接使用 idx）
            song_id = str(song.get("meta", {}).get("idx", ""))
            if song_id and song_id in alias_map:
                song["aliases"] = alias_map[song_id]
            else:
                song["aliases"] = []
        
        return songs
    
    # 日服：配了 R2 直链就走镜像，没配照旧直连 chunirec —— R2 是加速层，不是新依赖。
    # 换到带 ETag 的这一路才是本轮真正的收益：chunirec 全量 GET 实测 7.86~56.25 s，
    # 命中 304 只要 0.45~2.11 s。
    # 先读 Worker meta 再取产物：真下到新数据时把 written_at 记进版本记账，首页
    # "本地数据版本"（本地这份是云端哪一版）和"云端数据版本"（云端现在是哪一版）
    # 才是同一口钟的时间。meta 读不到就退回"到手时刻"，失败只留日志。
    fetch_r2_status()
    _fetch_json_etag(
        "日服",
        jp_music_info_url or base64.b64decode(song_data_jp).decode('utf-8'),
        jp_music_info_path,
        "jp_songs_info",
        transformer=jp_transformer,
        version_time=(read_upstream_status().get("jobs") or {}).get("jp", {}).get("written_at"),
    )

    # 4. 水鱼曲库与版本表（国服筛选要用的派生字段来源）
    fetch_fish_music_data()
    fetch_intl_music_data()
    print("✅ 谱面数据更新完成")


# --- 启动时备齐曲库 -----------------------------------------------------------------
# 清单分两档：CORE 缺了应用根本用不了（存档页、渲染都靠它），FILTER_ONLY 缺了只是
# 少一部分功能（筛选少几类条件、国际服定数停在快照）。两档都算缺口、都要报出来 ——
# 缺席原本是静默的（2026-09-09 那次 11 项全绿其实是假绿），只有报出来才知道为什么少。
MUSIC_DATA_CORE = (("国服曲库", music_info_path), ("日服曲库", jp_music_info_path))
MUSIC_DATA_FILTER_ONLY = (("水鱼曲库", fish_music_info_path), ("水鱼版本表", fish_latest_version_path),
                          ("国服版本表", cn_song_meta_path))
# 自动比对的新鲜窗口：跟着 cloudflare/music-db/wrangler.toml 的镜像 cron（每月 1 日 / 16 日
# 20:00 UTC）走 —— 两次 cron 最大间隔 16 天，窗口也取 16 天，保证每次自动检查都落在最近一次
# cron 之后、两次 cron 之间本机至多拉取一轮；镜像没变化的半个月里，日常开机一次请求都不发。
# 国服 / 水鱼不由这个 cron 产出，但更新同样是低频事件，跟随同一窗口即可。
# 手动"强制更新"不受这个窗口限制。
MUSIC_DATA_STALENESS_HOURS = 16 * 24

# 国际服以前不列进来，是因为 URL 空着、产物永远不会出现，列了等于把应用判成缺数据。
# 现在镜像是出厂默认，取没取到就是该报的事（而且它挂在带 Bot 防护的域名上，403 是常态）；
# 仍归"只影响一部分功能"这一档 —— 缺了只是国际服定数停在包里那份快照，不挡开存档。
if intl_music_info_url:
    MUSIC_DATA_FILTER_ONLY += (("国际服曲库", intl_music_info_path),)
MUSIC_DATA_ALL = MUSIC_DATA_CORE + MUSIC_DATA_FILTER_ONLY

_music_lock = threading.Lock()
_music_state = {"running": False, "note": None, "last_error": None, "finished_at": None}
# 上一轮失败要跨会话留下来：短时间高频探测会让这条链路偶发拒绝（本轮排查就把它撞成 403 /
# 连接重置过），每次开应用都重试全套请求只会让它继续拒。只在"文件都在、只是过期"时退避。
# 记录写在 status/local.json 里（和云端状态同一份：同一时刻、同一个写者、同一个读的人）。
RETRY_BACKOFF_HOURS = 6


def _update_state():
    return _read_status(status_local_path)


def _retry_cooldown_left():
    """还要等多久才值得再试（秒）。没有记录、记录读不动、或上一轮其实成功了 → 0。"""
    saved = _update_state()
    if not saved.get("last_error"):
        return 0
    try:
        attempted = datetime.fromisoformat(saved.get("last_attempt")).timestamp()
    except (TypeError, ValueError):
        return 0
    return max(0.0, RETRY_BACKOFF_HOURS * 3600 - (time.time() - attempted))


def music_data_gaps(staleness_hours=MUSIC_DATA_STALENESS_HOURS):
    """返回 (缺失, 过期) 两份名单。mtime 即"这份数据上次到手"的时间，命中 304 也会刷新它。"""
    missing, stale = [], []
    horizon = time.time() - staleness_hours * 3600
    for name, path in MUSIC_DATA_ALL:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            missing.append(name)
        elif os.path.getmtime(path) < horizon:
            stale.append(name)
    return missing, stale


def start_music_data_update(staleness_hours=MUSIC_DATA_STALENESS_HOURS, force=False):
    """
    后台补齐曲库，立刻返回。

    不能在启动时同步等：一次全量最慢实测 56 秒（日服直连 chunirec），而这份数据只有
    存档和渲染用得到，挡在首页前面就是让用户白等。都是公开端点，不碰两家 OAuth 的配额。
    """
    missing, stale = music_data_gaps(staleness_hours)
    if _music_state["running"] or not (missing or stale or force):
        return False

    if not missing and not force:
        left = _retry_cooldown_left()
        if left:
            # 上一轮没取回（多半是镜像那边的人机验证），每次开应用都重试只会把防护撞得更严
            _music_state["note"] = (f"上一轮取数失败（{_update_state().get('last_error') or '原因未知'}），"
                                    f"约 {int(left // 3600) + 1} 小时内不再重试，使用本地副本")
            return False

    if not _music_lock.acquire(blocking=False):
        return True  # 另一个标签页已经在拉了，跟着看它的状态就行

    def run():
        note = None
        try:
            fetch_music_data()
            still_missing, still_stale = music_data_gaps(staleness_hours)
            if still_missing:
                note = f"仍缺 {'、'.join(still_missing)}，对应筛选条件本次不再出现"
            elif still_stale:
                note = f"通讯失败，{'、'.join(still_stale)} 还是旧副本"
        except Exception as e:
            note = f"曲库更新失败：{e}"
        finally:
            # 具体是哪个源、为什么失败，比"还是旧副本"这种汇总有用得多 —— 两个都留下
            detail = _music_state.get("last_error")
            if note and detail and detail not in note:
                note = f"{note}（{detail}）"
            elif note is None and detail:
                # 本地副本还在有效期内，所以没有"缺口"可报 —— 但这个源其实永远取不到更新，
                # 一句"一切正常"会让人以为镜像在工作
                note = f"{detail}；本地副本仍在有效期内"
            try:
                _patch_status(status_local_path, last_attempt=datetime.now().isoformat(),
                              last_error=detail or note)
            except OSError as e:
                # 只是少一次退避依据，不该把已经拿到的曲库丢掉；但要说一声，
                # 否则"为什么下一轮又去撞"查无可查
                print(f"⚠️ 本轮结果没记上账（下次可能重复取数）: {e}")
            # running 最后才落：看到"跑完"的人必须同时看到已落盘的记录，
            # 否则下一轮会读到上一轮的旧原因，误判成还在退避期
            _music_state.update(running=False, note=note, finished_at=time.time())
            _music_lock.release()

    _music_state.update(running=True, note=None, last_error=None)
    threading.Thread(target=run, daemon=True).start()
    return True


def music_data_state(staleness_hours=MUSIC_DATA_STALENESS_HOURS):
    """首页要读的状态：跑不跑着、上次结果怎么说、现在还缺哪几份。"""
    missing, _ = music_data_gaps(staleness_hours)
    core_missing = [name for name in missing if name in dict(MUSIC_DATA_CORE)]
    return dict(_music_state, missing=missing, core_ready=not core_missing)