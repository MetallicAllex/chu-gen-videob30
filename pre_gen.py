import os
import time
import json
import random
from utils.Utils import get_b30_data_from_lxns, get_b30_data_from_fish, get_keyword, _process_b30_data
from utils.video_crawler import PurePytubefixDownloader, BilibiliDownloader

def merge_b30_data(new_b30_data, old_b30_data):
    """
    合并两份b30数据，使用新数据的基本信息但保留旧数据中的视频相关信息
    
    Args:
        new_b30_data (list): 新的b30数据（不含video_info_list和video_info_match）
        old_b30_data (list): 旧的b30数据（youtube版或bilibili版）
    
    Returns:
        tuple: (合并后的b30数据列表, 更新计数)
    """
    # 检查数据长度是否一致
    if len(new_b30_data) != len(old_b30_data):
        print(f"Warning: 新旧b30数据长度不一致，将使用新数据替换旧数据。")
        return new_b30_data, 0
    
    # 创建旧数据的复合键映射表
    old_song_map = {
        (song['id'], song['level_index']): song 
        for song in old_b30_data
    }
    
    # 按新数据的顺序创建合并后的列表
    merged_b30_data = []
    keep_count = 0
    for new_song in new_b30_data:
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
        merged_b30_data.append(new_song)

    update_count = len(new_b30_data) - keep_count
    return merged_b30_data, update_count

def update_b30_data_lxns(b30_raw_file, b30_data_file, token):
    lxns = get_b30_data_from_lxns(token)
    # if "data" not in lxns:
    #     raise Exception("落雪 API 未传回 Best30 数据，您可能需要检查 Token 或账号")
    if 'message' in lxns:
        raise ConnectionError(f"请求 Best30 数据失败: {lxns['message']}")
    return _process_b30_data(lxns, "lxns", b30_raw_file, b30_data_file)

def update_b30_data_fish(b30_raw_file, b30_data_file, username):
    try:
        fish = get_b30_data_from_fish(username)
        if 'message' in fish:
            raise Exception(f"请求 Best30 数据失败: {fish['message']}")
        return _process_b30_data(fish, "fish", b30_raw_file, b30_data_file)
    except json.JSONDecodeError:
        raise Exception("Error: 返回数据非有效 JSON 格式")

def search_one_video(downloader, song_data):
    title_name = song_data['song_name']
    # difficulty_name = song_data['level_label']
    level_index = song_data['level_index']
    # type = song_data['type']
    dl_type = "youtube" if isinstance(downloader, PurePytubefixDownloader) \
                else "bilibili" if isinstance(downloader, BilibiliDownloader) \
                else "None"
    keyword = get_keyword(dl_type, title_name, level_index)

    print(f"搜索关键词: {keyword}")
    videos = downloader.search_video(keyword)

    if len(videos) == 0:
        output_info = f"Error: 没有找到{title_name}-({level_index})-{type}的视频"
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


def search_b30_videos(downloader, b30_data, b30_data_file, search_wait_time=(0,0)):
    global search_max_results, downloader_type

    i = 0
    for song in b30_data:
        i += 1
        # Skip if video info already exists and is not empty
        if 'video_info_match' in song and song['video_info_match']:
            print(f"跳过({i}/30): {song['title']} ，已储存有相关视频信息")
            continue
        
        print(f"正在搜索视频({i}/30): {song['title']}")
        song_data = search_one_video(downloader, song)

        # 每次搜索后都写入b30_data_file
        with open(b30_data_file, "w", encoding="utf-8") as f:
            json.dump(b30_data, f, ensure_ascii=False, indent=4)
        
        # 等待几秒，以减少被检测为bot的风险
        if search_wait_time[0] > 0 and search_wait_time[1] > search_wait_time[0]:
            time.sleep(random.randint(search_wait_time[0], search_wait_time[1]))
    
    return b30_data


def download_one_video(downloader, song, video_download_path, high_res=False):
    clip_name = f"{song['id']}-{song['level_index']}"
    
    # Check if video already exists
    video_path = os.path.join(video_download_path, f"{clip_name}.mp4")
    if os.path.exists(video_path):
        print(f"已找到 {song['song_name']} 的缓存: {clip_name}".encode('gbk', errors='replace').decode('gbk'))
        return {"status": "skip", "info": f"已找到 {song['song_name']} 的缓存: {clip_name}"}
        
    if 'video_info_match' not in song or not song['video_info_match']:
        print(f"Error: 没有{song['title']}-{song['level_label']}-{song['type']}的视频信息，Skipping………")
        return {"status": "error", "info": f"Error: 没有{song['title']}-{song['level_label']}-{song['type']}的视频信息，Skipping………"}
    
    video_info = song['video_info_match']
    v_id = video_info['id'] 
    downloader.download_video(v_id, 
                              clip_name, 
                              video_download_path, 
                              high_res=high_res)
    return {"status": "success", "info": f"下载{clip_name}完成"}

    
def download_b30_videos(downloader, b30_data, video_download_path, download_wait_time=(0,0)):
    global download_high_res

    i = 0
    for song in b30_data:
        i += 1
        # 视频命名为song['song_id']-song['level_index']-song['type']，以便查找复用
        clip_name = f"{song['id']}-{song['level_index']}"
        
        # Check if video already exists
        video_path = os.path.join(video_download_path, f"{clip_name}.mp4")
        if os.path.exists(video_path):
            print(f"已找到谱面视频的缓存({i}/30): {clip_name}")
            continue
            
        print(f"正在下载视频({i}/30): {clip_name}……")
        if 'video_info_match' not in song or not song['video_info_match']:
            print(f"Error: 没有{song['title']}-{song['level_label']}-{song['type']}的视频信息，Skipping………")
            continue
        video_info = song['video_info_match']
        v_id = video_info['id'] 
        downloader.download_video(v_id, 
                                  clip_name, 
                                  video_download_path, 
                                  high_res=download_high_res)
        
        # 等待几秒，以减少被检测为bot的风险
        if download_wait_time[0] > 0 and download_wait_time[1] > download_wait_time[0]:
            time.sleep(random.randint(download_wait_time[0], download_wait_time[1]))
        print("\n")


# def gene_resource_config(b30_data, images_path, videoes_path, ouput_file):
#     global clip_start_interval, clip_play_time, default_comment_placeholders

#     intro_clip_data = {
#         "id": "intro_1",
#         "duration": 10,
#         "text": "【请填写前言部分】" if default_comment_placeholders else ""
#     }

#     ending_clip_data = {
#         "id": "ending_1",
#         "duration": 10,
#         "text": "【请填写后记部分】" if default_comment_placeholders else ""
#     }

#     video_config_data = {
#         "enable_re_modify": False,
#         "intro": [intro_clip_data],
#         "ending": [ending_clip_data],
#         "main": [],
#     }

#     main_clips = []
    
#     if clip_start_interval[0] > clip_start_interval[1]:
#         print(f"Error: 视频开始时间区间设置错误，请检查global_config.yaml文件中的CLIP_START_INTERVAL配置。")
#         clip_start_interval = (clip_start_interval[1], clip_start_interval[1])

#     for song in b30_data:
#         if not song['clip_id']:
#             print(f"Error: 没有找到 {song['title']}-{song['level_label']} 的clip_id，请检查数据格式，跳过该片段。")
#             continue
#         id = song['clip_id']
#         video_name = f"{song['id']}-{song['song_name']}"
#         __image_path = os.path.join(images_path, id + ".png")
#         __image_path = os.path.normpath(__image_path)
#         if not os.path.exists(__image_path):
#             print(f"Error: 没有找到 {id}.png，请检查本地缓存。")
#             __image_path = ""

#         __video_path = os.path.join(videoes_path, video_name + ".mp4")
#         __video_path = os.path.normpath(__video_path)
#         if not os.path.exists(__video_path):
#             print(f"Error: 没有找到 {video_name}.mp4，请检查本地缓存。")
#             __video_path = ""
        
#         duration = clip_play_time
#         start = random.randint(clip_start_interval[0], clip_start_interval[1])
#         end = start + duration

#         main_clip_data = {
#             "id": song["id"],
#             "song_name": song["song_name"],
#             "level_index": song["level_index"],
#             "score": song["score"],
#             "rating": song["rating"],
#             "full_combo": song["full_combo"],
#             "main_image": __image_path,
#             "video": __video_path,
#             "duration": duration,
#             "start": start,
#             "end": end,
#             "text": "【填写b30评价】" if default_comment_placeholders else "",
#         }
#         main_clips.append(main_clip_data)

#     # 倒序排列（从 b#30 到 b#1）
#     main_clips.reverse()

#     video_config_data["main"] = main_clips

#     with open(ouput_file, 'w', encoding="utf-8") as file:
#         json.dump(video_config_data, file, ensure_ascii=False, indent=4)

#     return video_config_data


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


# def st_gene_resource_config(b30_data, 
#                             images_path, videoes_path, output_file,
#                             clip_start_interval, clip_play_time, default_comment_placeholders):
#     intro_clip_data = {
#         "id": "intro_1",
#         "duration": 10,
#         "text": "【请填写前言部分】" if default_comment_placeholders else ""
#     }

#     ending_clip_data = {
#         "id": "ending_1",
#         "duration": 10,
#         "text": "【请填写后记部分】" if default_comment_placeholders else ""
#     }

#     video_config_data = {
#         "enable_re_modify": False,
#         "intro": [intro_clip_data],
#         "ending": [ending_clip_data],
#         "main": [],
#     }

#     main_clips = []
    
#     if clip_start_interval[0] > clip_start_interval[1]:
#         print(f"Error: 视频开始时间区间设置错误，请检查global_config.yaml文件中的CLIP_START_INTERVAL配置。")
#         clip_start_interval = (clip_start_interval[1], clip_start_interval[1])

#     for song in b30_data:
#         if not song['clip_id']:
#             print(f"Error: 没有找到 {song['title']}-{song['level_label']}-{song['type']} 的clip_id，请检查数据格式，跳过该片段。")
#             continue
#         id = song['clip_id']
#         video_name = f"{song['id']}-{song['song_name']}"
#         __image_path = os.path.join(images_path, id + ".png")
#         __image_path = os.path.normpath(__image_path)
#         if not os.path.exists(__image_path):
#             print(f"Error: 没有找到 {id}.png 图片，请检查本地缓存数据。")
#             __image_path = ""

#         __video_path = os.path.join(videoes_path, video_name + ".mp4")
#         __video_path = os.path.normpath(__video_path)
#         if not os.path.exists(__video_path):
#             print(f"Error: 没有找到 {video_name}.mp4 视频，请检查本地缓存数据。")
#             __video_path = ""
        
#         duration = clip_play_time
#         start = random.randint(clip_start_interval[0], clip_start_interval[1])
#         end = start + duration

#         main_clip_data = {
#             "id": song["id"],
#             "song_name": song["song_name"],
#             "level_index": song["level_index"],
#             "score": song["score"],
#             "rating": song["rating"],
#             "full_combo": song["full_combo"],
#             "main_image": __image_path,
#             "video": __video_path,
#             "duration": duration,
#             "start": start,
#             "end": end,
#             "text": "【请填写b30评价】" if default_comment_placeholders else "",
#         }
#         main_clips.append(main_clip_data)

#     # 倒序排列（b30在前，b1在后）
#     main_clips.reverse()

#     video_config_data["main"] = main_clips

#     with open(output_file, 'w', encoding="utf-8") as file:
#         json.dump(video_config_data, file, ensure_ascii=False, indent=4)

#     return video_config_data


def st_gene_resource_config(b30_data, images_path, videoes_path, output_file,
                            clip_start_interval, clip_play_time, default_comment_placeholders):
    """生成视频配置文件，合并了 `st_gene_resource_config` 和 `gene_resource_config`
    
    Args:
        b30_data: b30 数据列表
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
        "text": "【请填写前言部分】" if default_comment_placeholders else ""
    }

    ending_clip_data = {
        "id": "ending_1",
        "duration": 10,
        "text": "【请填写后记部分】" if default_comment_placeholders else ""
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

    # 遍历 b30_data 来构建视频配置数据
    for song in b30_data:
        if not song['clip_id']:
            print(f"Error: 没有找到 {song['title']}-{song['level_label']}-{song['type']} 的clip_id，请检查数据格式，跳过该片段。")
            continue
        id = song['clip_id']
        video_name = f"{song['id']}-{song['song_name']}"
        __image_path = os.path.join(images_path, id + ".png")
        __image_path = os.path.normpath(__image_path)
        if not os.path.exists(__image_path):
            print(f"Error: 没有找到 {id}.png 图片，请检查本地缓存数据。")
            __image_path = ""

        __video_path = os.path.join(videoes_path, video_name + ".mp4")
        __video_path = os.path.normpath(__video_path)
        if not os.path.exists(__video_path):
            print(f"Error: 没有找到 {video_name}.mp4 视频，请检查本地缓存数据。")
            __video_path = ""
        
        duration = clip_play_time
        start = random.randint(clip_start_interval[0], clip_start_interval[1])
        end = start + duration

        main_clip_data = {
            "id": song["id"],
            "song_name": song["song_name"],
            "level_index": song["level_index"],
            "score": song["score"],
            "rating": song["rating"],
            "full_combo": song["full_combo"],
            "main_image": __image_path,
            "video": __video_path,
            "duration": duration,
            "start": start,
            "end": end,
            "text": "【请填写b30评价】" if default_comment_placeholders else "",
        }
        main_clips.append(main_clip_data)

    # 倒序排列（b30在前，b1在后）
    main_clips.reverse()

    video_config_data["main"] = main_clips

    # 写入到输出文件
    with open(output_file, 'w', encoding="utf-8") as file:
        json.dump(video_config_data, file, ensure_ascii=False, indent=4)

    return video_config_data
