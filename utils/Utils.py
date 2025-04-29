import json
import requests
import threading
from PIL import Image
from update_music_data import music_info_path
from concurrent.futures import ThreadPoolExecutor

class Utils:
    def __init__(self, InputUserID: int = 0):
        UserId = InputUserID
        if UserId != 0:
            try:
                with open(f"./b30_datas/{UserId}_b30.json") as file:
                    UserB30Data = json.load(file)
            except FileNotFoundError:
                print("错误：未找到 JSON 文件。")
                return {}
            except json.JSONDecodeError:
                print("错误：JSON 解码失败。")
                return {}

class TextAnchor:
    """动态锚点定位系统"""
    def __init__(self, x_center, y_center):
        self.base = (x_center, y_center)
    
    def get_pos(self, draw, text, font, x_offset=0, y_offset=0):
        bbox = draw.textbbox((0,0), text, font=font)
        x = self.base[0] - (bbox[2]-bbox[0])//2 + x_offset
        y = self.base[1] - (bbox[3]-bbox[1])//2 + y_offset
        return (x, y)

def _process_b30_data(raw_data: list, source_type: str, b30_raw_file, b30_data_file):
    """Best30 数据清洗（只要关键的）。

    Args:
        raw_data(list): API 请求的原始数据
        source_type(str): Best30 数据来源（水鱼 / 落雪）
        b30_raw_file(JSON): Best30 原始数据存储文件
        b30_data_file(JSON): Best30 处理数据存储文件
    
    Returns:
        processed_data(list): 经过处理后的数据（使用落雪格式）
    """
    # 1. 加载本地曲目数据库（主线程完成）
    with open(music_info_path, 'r', encoding='utf-8') as f:
        song_db = json.load(f)

    # 2. 根据数据源类型提取字段映射规则
    field_map = {
        "lxns": {
            "id": "id",
            "song_name": "song_name",
            "level_index": "level_index",
            "score": "score",
            "rating": "rating",
            "fc": "full_combo",
            "data_field": "data"
        },
        "fish": {
            "id": "mid",
            "song_name": "title",
            "level_index": "level_index",
            "score": "score",
            "rating": "ra",
            "fc": "fc",
            "data_field": "records.b30"
        }
    }
    fields = field_map[source_type]

    # 3. 提取原始 B30 数据（支持嵌套字段如 'records.b30'）
    def get_nested_field(data, field_path):
        keys = field_path.split('.')
        for key in keys:
            data = data[key]
        return data
    b30_data = get_nested_field(raw_data, fields["data_field"])[:30]

    # 4. 缓存原始数据（主线程完成）
    with open(b30_raw_file, 'w', encoding='utf-8') as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=4)

    # 5. 多线程处理每条曲目数据
    processed_data = []
    print_lock = threading.Lock()  # 用于保护打印输出
    
    def process_song(song, i):
        nonlocal song_db
        try:
            processed_song = {
                "id": song[fields["id"]],
                "song_name": song[fields["song_name"]],
                "level_index": song[fields["level_index"]],
                "score": song[fields["score"]],
                "rating": song[fields["rating"]],
                "full_combo": song[fields["fc"]],
                "clip_id": f"Best_{i + 1}"
            }

            # 从本地数据库匹配曲目信息
            song_info = next((item for item in song_db if item["id"] == processed_song["id"]), None)
            if song_info:
                for diff in song_info.get("difficulties", []):
                    if diff.get("difficulty") == processed_song["level_index"]:
                        level_value = diff["level_value"]
                        processed_song["level"] = float(level_value) if isinstance(level_value, int) else level_value
                        break
                else:
                    with print_lock:
                        print(f"警告：曲目【{processed_song['song_name']}】未找到 {processed_song['level_index']} 难度")
            else:
                with print_lock:
                    print(f"警告：未找到曲目【{processed_song['song_name']}】的信息")

            # 备用方案
            if "level" not in processed_song:
                try:
                    raw_level = str(song.get("level", "")).rstrip('+')
                    processed_song["level"] = float(raw_level) if raw_level.replace('.', '').isdigit() else song.get("level", "N/A")
                except (ValueError, AttributeError):
                    processed_song["level"] = song.get("level", "N/A")
                with print_lock:
                    print(f"使用原始 level 值: {processed_song['level']} (曲目ID: {processed_song['id']})")
            
            return processed_song
        except Exception as e:
            with print_lock:
                print(f"处理曲目 {i} 时出错: {str(e)}")
            return None

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_song, song, i) for i, song in enumerate(b30_data)]
        for future in futures:
            if result := future.result():
                processed_data.append(result)

    # 6. 保存处理后的数据（主线程完成）
    with open(b30_data_file, 'w', encoding='utf-8') as f:
        json.dump(processed_data, f, ensure_ascii=False, indent=4)
    return processed_data

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

# def diff_bg_change(num):
#     """ 根据谱面难度返回对应的背景图像编号 """
#     if num == 2:
#         return "EXPERT"
#     elif num == 3:
#         return "MASTER"
#     elif num == 4:
#         return "ULTIMA"
#     else:
#         return 2

def diff_bg_change(num):
    """根据谱面难度返回对应的背景图像编号"""
    return {2: "EXPERT", 3: "MASTER", 4: "ULTIMA"}.get(num, 2)


def special_mark(mark):
    """FC | AJ 判定"""
    if mark == "fullcombo":
        return "(FC)"
    elif mark == "alljustice":
        return "(AJ)"
    else:
        return ""

# def get_keyword(downloader_type, title_name, level_index):
#     match level_index:
#         case 0:
#             dif_name = "BASIC"
#         case 1:
#             dif_name = "ADVANCED"
#         case 2:
#             dif_name = "EXPERT"
#         case 3:
#             dif_name = "MASTER"
#         case 4:
#             dif_name = "ULTIMA"
#         # case 5:
#             # dif_name = "World's End" # 不包含在内
#         case _:
#             dif_name = ""
#             print(f"Warning: 谱面{title_name}具有未指定的难度！")
#     if downloader_type == "youtube":
#         suffix = "(譜面確認) [CHUNITHM チュウニズム]"
#         return f"{title_name} {dif_name} {suffix}"
#     elif downloader_type == "bilibili":
#         prefix = "【CHUNITHM/谱面预览】"
#         return f"{prefix} {title_name} {dif_name}"

def get_keyword(downloader_type, title_name, level_index):
    dif_name = {0: "BASIC", 1: "ADVANCED", 2: "EXPERT", 3: "MASTER", 4: "ULTIMA"}.get(level_index, "")
    if not dif_name:
        print(f"Warning: 谱面{title_name}具有未指定的难度！")
    return (
        f"{title_name} {dif_name} (譜面確認) [CHUNITHM チュウニズム]"
        if downloader_type == "youtube"
        else f"【CHUNITHM/谱面预览】 {title_name} {dif_name}"
    )


def get_b30_data_from_fish(username):
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

def get_b30_data_from_lxns(token):
    url = "https://maimai.lxns.net/api/v0/user/chunithm/player/scores"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "X-User-Token": token
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 自动处理 4xx/5xx 错误
        data = response.json()
        
        # 检查业务逻辑错误（如 success=false）
        if not data.get("success", True):
            raise Exception(f"落雪 API 返回错误: {data.get('message')}")
        
        return data
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise Exception("Token 无效或已过期，请检查您的 API 密钥") from e
        else:
            raise Exception(f"API 请求失败: {e.response.status_code}") from e
    except Exception as e:
        raise Exception(f"获取数据时发生意外错误: {str(e)}") from e