import re
import streamlit as st
from datetime import datetime
from moviepy import VideoFileClip
import os, json, yaml, subprocess, platform, threading, time

# 应用根 = 本文件所在 utils/ 的上一级，按 __file__ 定位而不是按当前工作目录。
# 随包分发时用户未必从应用根启动（快捷方式"起始于"填错、从别处 streamlit run），那时按
# 相对路径读配置会抛 "global_config.yaml not found" —— 表现正好是"只有读配置的那几个页面
# 报错、其他页面正常"。（以前 B 站下载期间还会把整个进程的 cwd 切到 videos/downloads，
# 那条已在 video_crawler.bilibili_download 里取消。）
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLOBAL_CONFIG_PATH = os.path.join(APP_ROOT, "global_config.yaml")

# 渲染临时产物的统一归宿（ts_files.txt / 音频规范化副本 / island 主体段等）。以前六处各写
# 各的 './videos/temp_generated'，只在 st_app.py 启动时 chdir 过才成立；其中一处是
# shutil.rmtree —— cwd 被别的启动方式带偏就会删错目录，所以收成一条按 __file__ 锚定的常量。
TEMP_GENERATED_DIR = os.path.join(APP_ROOT, "videos", "temp_generated")

# 谱面确认素材的共享下载目录。这里刻意保持**相对**写法：README 承诺的命名约定是
# `{song_id}-{难度}.mp4`，而 video_configs.json 里存下的就是 `videos\downloads\...` 这种
# 相对路径（页 4 生成配置时按 cwd 解析）。收成一条常量是为了消灭"四个地方各写一遍"，
# 改成绝对路径会连带改动存档里的路径格式。可写性由 st_app.py 启动时的 chdir 保证。
DOWNLOADS_DIR = os.path.join("videos", "downloads")

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

SAVE_ID_PATTERN = re.compile(r"^\d{8}_\d{6}$")


def is_save_id(name):
    """存档目录名的形状（YYYYmmdd_HHMMSS）。用户手动放进 b30_datas 里的杂项目录不是存档。"""
    return bool(SAVE_ID_PATTERN.match(name))


def is_artifact_valid(path):
    """产物是否真的可用：是个文件，而且非零字节。

    判据必须只有一份：下载/渲染都把"文件存在"当成"已生成"，而 ffmpeg 或 httpx 中断很可能
    留下 0 字节壳子。两处口径不一致时会出现"下载页要重下、生成配置却当它已就绪"互相打架。
    """
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def get_user_versions(username):
    """列出一个用户的全部存档版本；名字不合形状的目录一律不当存档看待

    各页面都拿 `datetime.strptime(save_id.split("_")[0], "%Y%m%d")` 显示日期，混进来一个
    `backup` 之类的目录会让这些页面一起 ValueError。
    """
    base_dir = get_user_base_dir(username)
    if not os.path.exists(base_dir):
        return []
    versions = [d for d in os.listdir(base_dir)
               if is_save_id(d) and os.path.isdir(os.path.join(base_dir, d))]
    return sorted(versions, reverse=True)

def _read_config(file_path):
    def read():
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    try:
        return read()
    except PermissionError:
        # Windows 上 os.replace 的目标有一个极短的"删除待定"窗口，此时新开读句柄会被
        # 拒绝（WinError 13），文件本身完好。后台在刷曲库就会撞上，退让重试，
        # 别把它读成"曲库缺失"。只退让一次 50ms 不够（并发压测里会偶发穿透），
        # 改成与 save_config 同一口径的多次短退让；真读不到才抛原始错误。
        for _ in range(20):
            time.sleep(0.03)
            try:
                return read()
            except PermissionError:
                continue
        raise


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
    if os.path.exists(GLOBAL_CONFIG_PATH):
        with open(GLOBAL_CONFIG_PATH, "r", encoding='utf-8') as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    raise FileNotFoundError(
        f"未找到 global_config.yaml（查找位置：{GLOBAL_CONFIG_PATH}）。"
        f"请确认应用是否完整解压，且该文件位于应用根目录")

def write_global_config(config):
    """写回全局配置。失败必须让调用方知道：旧实现只 print 后返回 None，
    页 6 紧接着就 toast「配置已保存！」，磁盘没写进去也报成功。
    """
    tmp_file = f"{GLOBAL_CONFIG_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f)
        for attempt in range(20):
            try:
                os.replace(tmp_file, GLOBAL_CONFIG_PATH)
                return
            except PermissionError:
                time.sleep(0.03)
        raise PermissionError(f"{GLOBAL_CONFIG_PATH} 一直被占用，本次未更新（旧副本保持完整）")
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

def get_video_duration(video_path):
    """返回时长（秒），探测失败返回 None。

    不能返回 0：页 4 用它算时间轴上界（`max_minutes = duration // 60`），文件本身正常、
    只是 moviepy 那一刻被占用/读不动时，0 会把起止选择器塌成 0..0 —— 用户对着一个能播的
    视频填不进任何区间，而且界面看不出是探测失败。调用方必须显式判 None 再回退默认值。
    """
    try:
        with VideoFileClip(video_path, audio=False) as clip:
            return clip.duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return None

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