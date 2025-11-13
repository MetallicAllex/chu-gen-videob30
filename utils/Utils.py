import json, requests
from PIL import Image

# ========== 类型定义 ==========
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

def format_time_difference(seconds):
    """
    格式化时间差，隐藏为0的单位
    """
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_remaining = seconds % 60
    
    parts = []
    
    if hours > 0:
        parts.append(f"{hours} 小时")
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
        print(f"警告: 谱面{title_name}具有未指定的难度！")
    return (
        f"{title_name} {level_index} (譜面確認) [CHUNITHM チュウニズム]"
        if downloader_type == "youtube"
        else f"【CHUNITHM/中二节奏】谱面确认 {title_name} {level_index}"
    )

import subprocess
import re

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

# # 使用示例
# version = get_ffmpeg_version()
# print(f"FFmpeg 版本: {version}")

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
    url = f"https://1315228137-5e9bxr0gaf.ap-guangzhou.tencentscf.com?game=chunithm&player_id={friend_code}"
    # headers = {
    #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    #     "X-User-Token": friend_code
    # }
    
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