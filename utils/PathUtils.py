import streamlit as st
from datetime import datetime
from moviepy import VideoFileClip
import os, json, yaml, subprocess, platform, threading, time

def get_user_base_dir(username):
    """Get base directory for user data"""
    return os.path.join("b30_datas", username)

def get_user_version_dir(username, timestamp=None):
    """Get versioned directory for user data"""
    # 如果没有指定时间戳，则使用当前时间，返回新的时间戳组成的文件夹路径
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(get_user_base_dir(username), timestamp)

def get_data_paths(username, timestamp=None):
    """Get all data file paths for a specific version"""
    version_dir = get_user_version_dir(username, timestamp)
    return {
        'raw_file': os.path.join(version_dir, "b30_raw.json"),
        'data_file': os.path.join(version_dir, "b30_config.json"),
        'config_yt': os.path.join(version_dir, "b30_config_youtube.json"),
        'config_bi': os.path.join(version_dir, "b30_config_bilibili.json"),
        'custom_style': os.path.join(version_dir, "customization.json"),
        'video_config': os.path.join(version_dir, "video_configs.json"),
        'old_video_config': os.path.join(version_dir, "old_video_configs.json"),
        'exported_b30_search_config': os.path.join(version_dir, "exported_b30_search_config.json"),
        'image_dir': os.path.join(version_dir, "images"),
        'output_video_dir': os.path.join(version_dir, "videos"),
    }

def get_user_versions(username):
    """Get all available versions for a user"""
    base_dir = get_user_base_dir(username)
    if not os.path.exists(base_dir):
        return []
    versions = [d for d in os.listdir(base_dir) 
               if os.path.isdir(os.path.join(base_dir, d))]
    return sorted(versions, reverse=True)

def _read_config(file_path):
    def read():
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    try:
        return read()
    except PermissionError:
        # Windows 上 os.replace 的目标有一个极短的"删除待定"窗口，此时新开读句柄会被
        # 拒绝（WinError 13），文件本身完好。后台在刷曲库就会撞上，退让一次重试，
        # 别把它读成"曲库缺失"。
        time.sleep(0.05)
        return read()


# 缓存键必须带上文件版本：只按路径缓存时，save_config 写完再读仍然拿到旧内容
# （实测覆盖第二版后 60 秒内返回的还是第一版），读后写就永远看不到自己刚存的东西。
# mtime + size 每次写入必然变化，拿它当版本号就不需要显式失效，也不会因为一次保存
# 把整套曲库的缓存连带清掉。参数名不能带下划线 —— 下划线开头的参数不参与缓存键计算。
@st.cache_data(ttl=60)
def _cached_read_config(file_path, file_version):
    return _read_config(file_path)


def load_config(file_path, use_cache=False):
    """加载JSON配置文件，use_cache 时 60 秒内复用同版本文件的解析结果"""

    if use_cache and 'st' in globals():
        try:
            file_version = (os.path.getmtime(file_path), os.path.getsize(file_path))
        except OSError:
            # 连版本都取不到（文件不存在／被占用），别拿缓存猜，让 _read_config 抛原始错误
            return _read_config(file_path)
        return _cached_read_config(file_path, file_version)
    return _read_config(file_path)

def save_config(config_file, config_data):
    """
    原子替换：曲库在后台线程里自动刷新，前台不能读到只写了一半的 JSON。

    Windows 上 os.replace 会被"目标正被另一个句柄读着"挡下（WinError 5），而读者只持有
    文件毫秒级，所以退让着重试几次。始终失败时让异常抛出去 —— 此时目标里是完整的上一份，
    宁可不更新这次，也不能原地写坏。临时名带线程 id，同进程两个写者不互相覆盖。
    """
    tmp_file = f"{config_file}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        for attempt in range(20):
            try:
                os.replace(tmp_file, config_file)
                return
            except PermissionError:
                time.sleep(0.03)
        raise PermissionError(f"{config_file} 一直被占用，本次未更新（旧副本保持完整）")
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

def read_global_config():
    if os.path.exists("global_config.yaml"):
        with open("global_config.yaml", "r", encoding='utf-8') as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    else:
        raise FileNotFoundError("global_config.yaml not found")

def write_global_config(config):
    try:
        with open("global_config.yaml", "w", encoding='utf-8') as f:
            yaml.dump(config, f)
    except Exception as e:
        print(f"Error writing global config: {e}")

def get_video_duration(video_path):
    """Returns the duration of a video file in seconds"""
    try:
        with VideoFileClip(video_path, audio=False) as clip:
            return clip.duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return 0

def open_file_explorer(path):
    try:
        # Windows
        if platform.system() == "Windows":
            subprocess.run(['explorer', path], check=True)
        # macOS
        elif platform.system() == "Darwin":
            subprocess.run(['open', path], check=True)
        # Linux
        elif platform.system() == "Linux":
            subprocess.run(['xdg-open', path], check=True)
        return True
    except Exception as e:
        return False