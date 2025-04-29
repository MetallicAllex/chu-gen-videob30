import hashlib
import requests
import json
import os

# # API 端点
url_cn = "https://maimai.lxns.net/api/v0/chunithm/song/list"
url = "https://reiwa.f5.si/chunirec_all.json"

# # 文件路径
music_info_path = './music_datasets/all_music_infos.json'
jp_music_info_path = './music_datasets/jp_songs_info.json'

# 创建目录
os.makedirs(os.path.dirname(music_info_path), exist_ok=True)

def json_hash(obj):
    """生成 JSON 对象的 md5 哈希"""
    return hashlib.md5(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


# def fetch_music_data():
#     try:
#         response = requests.get(url_cn)
#         if response.status_code != 200:
#             print(f"获取谱面数据失败，状态码 {response.status_code}")
#             return

#         remote_data = response.json()
#         remote_songs = remote_data.get("songs", [])

#         if not os.path.exists(music_info_path):
#             # 本地没有，直接写入
#             with open(music_info_path, "w", encoding="utf-8") as file:
#                 json.dump(remote_songs, file, ensure_ascii=False, indent=4)
#             print("✅ （国服）已保存首次获取的谱面数据。")
#             return

#         # 本地有，读取并比较哈希
#         with open(music_info_path, "r", encoding="utf-8") as file:
#             local_songs = json.load(file)

#         if json_hash(remote_songs) != json_hash(local_songs):
#             with open(music_info_path, "w", encoding="utf-8") as file:
#                 json.dump(remote_songs, file, ensure_ascii=False, indent=4)
#             print("🔄 （国服）谱面数据已更新。")
#         else:
#             print("✅ （国服）谱面数据已是最新。")

#     except Exception as e:
#         print(f"❌ （国服）在获取谱面数据时出错：{e}")


# # 难度字段映射
# difficulty_map = {
#     "BAS": "BASIC",
#     "ADV": "ADVANCED",
#     "EXP": "EXPERT",
#     "MAS": "MASTER",
#     "ETR": "ETERNAL"
# }

# def fetch_jp_music_data():
#     try:
#         response_jp = requests.get(url)
#         if response_jp.status_code != 200:
#             print(f"获取谱面数据失败，状态码 {response_jp.status_code}")
#             return

#         remote_data_jp = json.loads(response_jp.content.decode('utf-8-sig'))

#         # 🎯 转换 data 字段下的难度键名
#         for song in remote_data_jp:
#             if "data" in song:
#                 song["data"] = {
#                     difficulty_map.get(diff, diff): detail
#                     for diff, detail in song["data"].items()
#                 }

#         if not os.path.exists(jp_music_info_path):
#             with open(jp_music_info_path, "w", encoding="utf-8") as file:
#                 json.dump(remote_data_jp, file, ensure_ascii=False, indent=4)
#             print(f"✅ （日服）已保存首次获取的谱面数据。")
#             return

#         with open(jp_music_info_path, "r", encoding="utf-8") as file:
#             local_data_jp = json.load(file)

#         if json_hash(remote_data_jp) != json_hash(local_data_jp):
#             with open(jp_music_info_path, "w", encoding="utf-8") as file:
#                 json.dump(remote_data_jp, file, ensure_ascii=False, indent=4)
#             print(f"🔄 （日服）谱面数据已更新。")
#         else:
#             print(f"✅ （日服）谱面数据已是最新。")

#     except Exception as e:
#         print(f"❌ （日服）在获取谱面数据时出错：{e}")

def safe_decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("utf-8")


def _fetch_music_data(name, url, filepath, transformer=None):
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"获取谱面数据失败，状态码 {response.status_code}")
            return

        raw_data = safe_decode(response.content)
        data = json.loads(raw_data)
        # print(f"📦 （{name}）返回内容预览：\n{raw_data[:200]}")
        if transformer:
            data = transformer(data)

        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
            print(f"✅ （{name}）已下载所需的谱面数据[{json_hash(data)}]")
            return

        with open(filepath, "r", encoding="utf-8") as file:
            local_data = json.load(file)

        if json_hash(data) != json_hash(local_data):
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
            print(f"🔄 （{name}）谱面数据成功更新[{json_hash(data)}]")
        else:
            print(f"☑️ （{name}）谱面数据已是最新[{json_hash(local_data)}]")

    except Exception as e:
        print(f"❌ （{name}）获取谱面数据时出错：{e}")

# 包装函数
def fetch_music_data():
    _fetch_music_data(
        name="国服",
        url=url_cn,
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
        url=url,
        filepath=jp_music_info_path,
        transformer=transformer
    )