import json, requests, hashlib, requests, json, os, base64, datetime, subprocess, re
from pathlib import Path
from PIL import Image
from utils.PageUtils import *

# ========== 类型定义 ==========
class Utils:
    def __init__(self, InputUserID: int = 0):
        UserId = InputUserID
        if UserId != 0:
            try:
                with open(f"./b30_datas/{UserId}/b30_raw.json") as file:
                    UserB30Data = json.load(file)
            except FileNotFoundError:
                print("错误：未找到 JSON 文件。")
                return {}
            except json.JSONDecodeError:
                print("错误：JSON 解码失败。")
                return {}

def format_time_difference(seconds):
    """
    格式化时间差，隐藏为 0 的单位
    """
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    
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

def add_layer(base_image, layer_image, position=(0, 0), opacity=1.0):
    """将图层叠加到基础图像上，支持透明度控制。

    Args:
        base_image(Image): 基础图像（RGBA 模式）
        layer_image(Image): 要叠加的图层（RGBA 模式）
        position(tuple[int, int]): 叠加位置 (x, y)
        opacity(float): 图层透明度（0.0 完全透明，1.0 完全不透明）

    Returns:
        canvas: 合并后的新图像
    """
    if layer_image.mode != 'RGBA':
        layer_image = layer_image.convert('RGBA')
    
    # 调整图层透明度
    if opacity < 1.0:
        alpha = layer_image.split()[3]
        alpha = alpha.point(lambda p: p * opacity)
        layer_image.putalpha(alpha)
    
    # 创建临时画布，避免直接修改原图
    canvas = Image.new('RGBA', base_image.size)
    canvas.paste(base_image, (0, 0))  # 先放基础图像
    
    # 将图层粘贴到指定位置
    canvas.paste(layer_image, position, mask=layer_image)
    return canvas

def get_keyword(downloader_type, title_name, level_index):
    if not level_index:
        print(f"警告: 谱面【{title_name}】具有未指定的难度！")
    return (
        f"{title_name} {level_index} (譜面確認) [CHUNITHM チュウニズム]"
        if downloader_type == "youtube"
        else f"【CHUNITHM/中二节奏】谱面确认 {title_name} {level_index}"
    )

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

def get_b50_data_from_fish(username):
    url = "https://www.diving-fish.com/api/chunithmprober/query/player"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Content-Type": "application/json"
    }
    payload = {
        "username": username,
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        return response.json()
    elif response.status_code == 400:
        return {"error": "未搜索到此用户"}
    elif response.status_code == 403:
        return {"error": "查询被拒绝，请检查您是否已关闭【允许其他人查询您的成绩】"}
    else:
        return {"error": f"获取数据失败：{response.status_code}"}

def get_b50_data_from_lxns(friend_code):
    url = f"https://fish-usta-proxy-efexqrwlmf.cn-shanghai.fcapp.run?source=lxns&game=chunithm&query=best&friend_code={friend_code}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # 自动处理 4xx/5xx 错误
        data = response.json()
        
        # 检查业务逻辑错误（如 success=false）
        if not data.get("success", True):
            raise Exception(f"落雪 API 返回错误: {data.get('error')}")
        
        return data
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise Exception("好友码无效，请检查您的好友码是否输入正确") from e
        else:
            raise Exception(f"API 请求失败: {e.response.status_code}") from e
    except Exception as e:
        raise Exception(f"获取数据时发生意外错误: {str(e)}") from e

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
        # with open(config_file, "w") as f:
        #     json.dump({"last_update": current_time.isoformat()}, f)
        save_config(config_file, {"last_update": current_time.isoformat()})
        return True
    
    # 读取上次更新时间
    try:
        data = load_config(config_file)
        last_update = datetime.datetime.fromisoformat(data.get("last_update", "2000-01-01T00:00:00"))
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

def fetch_music_data_with_cache(threshold_hours=24):
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
    
    print("✅ 谱面数据更新完成")

# 保留原有的 fetch_music_data 函数用于直接调用（不检查缓存）
def fetch_music_data():
    """
    直接获取谱面数据（不检查缓存时间）
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