import hashlib, requests, json, os, base64, datetime
from pathlib import Path


# # API 端点
url_cn = "https://maimai.lxns.net/api/v0/chunithm/song/list"
url = "aHR0cHM6Ly9yZWl3YS5mNS5zaS9jaHVuaXJlY19hbGwuanNvbg=="

# # 文件路径
music_info_path = './music_datasets/all_music_infos.json'
jp_music_info_path = './music_datasets/jp_songs_info.json'

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
    
    current_time = datetime.datetime.now()
    
    # 如果配置文件不存在，则创建并立即返回True
    if not config_file.exists():
        with open(config_file, "w") as f:
            json.dump({"last_update": current_time.isoformat()}, f)
        return True
    
    # 读取上次更新时间
    try:
        with open(config_file, "r") as f:
            data = json.load(f)
            last_update = datetime.datetime.fromisoformat(data.get("last_update", "2000-01-01T00:00:00"))
    except (json.JSONDecodeError, ValueError):
        # 文件损坏或格式错误，重新创建
        with open(config_file, "w") as f:
            json.dump({"last_update": current_time.isoformat()}, f)
        return True
    
    # 计算时间差
    time_diff = current_time - last_update
    if time_diff.total_seconds() / 3600 >= threshold_hours:
        # 更新时间戳
        with open(config_file, "w") as f:
            json.dump({"last_update": current_time.isoformat()}, f)
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

def fetch_music_data_with_cache(threshold_hours=24):
    """
    带缓存检查的音乐数据获取函数
    
    Args:
        threshold_hours: 缓存时间阈值（小时）
    """
    # 检查是否需要更新
    if not should_update_metadata(threshold_hours):
        print("⏩ 未达到更新阈值，跳过数据更新")
        return
    
    print("🔄 开始更新音乐数据...")
    
    # 更新国服数据
    _fetch_music_data(
        name="国服",
        url=url_cn,
        filepath=music_info_path,
        transformer=lambda d: d.get("songs", [])
    )

    # 难度映射配置
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
    
    # 更新日服数据
    _fetch_music_data(
        name="日服",
        url=base64.b64decode(url),
        filepath=jp_music_info_path,
        transformer=transformer
    )
    
    print("✅ 音乐数据更新完成")

# 保留原有的 fetch_music_data 函数用于直接调用（不检查缓存）
def fetch_music_data():
    """
    直接获取音乐数据（不检查缓存时间）
    """
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
        url=base64.b64decode(url),
        filepath=jp_music_info_path,
        transformer=transformer
    )