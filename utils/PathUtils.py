import streamlit as st
from datetime import datetime
from moviepy import VideoFileClip
import os, re, json, yaml, subprocess, platform

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

def load_config(file_path, use_cache=False, cache_time=3600):
    """加载JSON配置文件，可选择是否使用缓存"""
    
    def _load_config(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    if use_cache and 'st' in globals():
        # 创建缓存版本
        @st.cache_data(ttl=cache_time)
        def _cached_load(file_path):
            return _load_config(file_path)
        return _cached_load(file_path)
    else:
        return _load_config(file_path)

def save_config(config_file, config_data):
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

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