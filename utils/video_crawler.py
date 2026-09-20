# import tkinter as tk
from typing import Tuple
# from PIL import Image, ImageTk
from abc import ABC, abstractmethod
from pytubefix import YouTube, Search
from utils.PathUtils import read_global_config
from utils.PageUtils import remove_html_tags_and_invalid_chars
from bilibili_api import login_v2, user, search, video, Credential, sync, HEADERS
import os, json, asyncio, pickle, httpx, traceback, subprocess, shutil, requests, time

# ffmpeg 的路径解析与实际调用都收在 merge_streams() 里（统一走 RenderIO.get_ffmpeg_binary）；
# 不再用 os.system 拼 shell 字符串，也就不再需要按平台写重定向。
MAX_LOGIN_RETRIES = 3
# 单次搜索请求的候选扫描池；最终保留几条由 search_max_results 在排名之后决定
SEARCH_SCAN_SIZE = 50
BILI_URL_PREFIX = "https://www.bilibili.com/video/"
YTB_URL_PREFIX = "https://www.youtube.com/watch?v="
YTB_DATAV3_ENDPOINT = "https://www.googleapis.com/youtube/v3/"

def custom_po_token_verifier() -> Tuple[str, str]:

    config = read_global_config()
    # with open("global_config.yaml", "r", encoding="utf-8") as f:
    #     config = yaml.load(f, Loader=yaml.FullLoader)
    
    if config['CUSTOMER_PO_TOKEN']['visitor_data'] == "" or config['CUSTOMER_PO_TOKEN']['po_token'] == "":
        print("未配置CUSTOMER_PO_TOKEN，请检查global_config.yaml")

    # print(f"/Customer PO Token/\n"
    #       f"visitor_data: {config['CUSTOMER_PO_TOKEN']['visitor_data']}, \n"
    #       f"po_token: {config['CUSTOMER_PO_TOKEN']['po_token']}")

    return config["CUSTOMER_PO_TOKEN"]["visitor_data"], config["CUSTOMER_PO_TOKEN"]["po_token"]
        
def autogen_po_token_verifier() -> Tuple[str, str]:
    # 自动生成 PO Token
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "external_scripts", "po_token_generator.js")
    result = subprocess.run(["node", script_path], capture_output=True, text=True)
    
    try:
        cleaned_output = result.stdout.strip()  # 尝试清理输出中的空白字符
        output = json.loads(cleaned_output)
        # print(f"PO Token生成结果: {output}")
    except json.JSONDecodeError as e:
        print(f"验证 PO Token 生成失败 (JSON 解析错误): {str(e)}")
        print(f"原始输出内容: {repr(result.stdout)}")  # 使用repr()显示所有特殊字符
        
        if result.stderr:
            print(f"外部脚本错误输出: {result.stderr}")
        return None, None
    
    # 检查输出中是否含有特定键
    if "visitorData" not in output or "poToken" not in output:
        print("验证PO Token生成失败: 输出中不包含有效值")
        print(f"原始输出内容: {repr(result.stdout)}")
        return None, None
    
    # print(f"/Auto Generated PO Token/\n"
    #       f"visitor_data: {output['visitor_data']}, \n"
    #       f"po_token: {output['po_token']}")
    
    return output["visitorData"], output["poToken"]

# 获取关键字
def get_keyword(downloader_type, title_name, level_index):
    if not level_index:
        print(f"警告: 谱面【{title_name}】具有未指定的难度！")
    return (
        f"{title_name} {level_index} (譜面確認) [CHUNITHM チュウニズム]"
        if downloader_type == "youtube"
        else f"【CHUNITHM/中二节奏】谱面确认 {title_name} {level_index}"
    )

def get_keyword_fallback(downloader_type, title_name, level_index):
    """曲名前置的备选关键词

    B 站会把【CHUNITHM/中二节奏】这类带括号和斜杠的长关键词按词拆分再按热度排序，
    实测同一首曲子主关键词扫 50 条零命中，而曲名放最前能命中正确的谱面确认视频。
    备选只留曲名 + 谱面确认 + 难度这三个有区分度的词：中二节奏/CHUNITHM 几乎出现在
    所有相关视频里，对区分毫无贡献，只会稀释曲名的权重，把原曲、手元之类的高热
    结果顶到前排（表现为搜出一堆奇奇怪怪的视频）。
    """
    return (
        f"{title_name} {level_index} 譜面確認 CHUNITHM"
        if downloader_type == "youtube"
        else f"{title_name} 谱面确认 {level_index}"
    )

def convert_duration_to_seconds(duration: str) -> int:
    try:
        minutes, seconds = map(int, duration.split(':'))
        return minutes * 60 + seconds
    except:
        return int(duration)

# def load_credential(credential_path):
#     if not os.path.isfile(credential_path):
#         print("#####【bilibili】未找到登录凭证，请重新扫码登录（若首次扫描登录未成功，请关闭当前二维码窗口，程序会要求重新登录）")
#         return None
#     else:
#         # 读取凭证文件
#         with open(credential_path, 'rb') as f:
#             loaded_data = pickle.load(f)
        
#         try:
#             # 创建 Credential 实例
#             credential = Credential(
#                 sessdata=loaded_data.sessdata,
#                 bili_jct=loaded_data.bili_jct,
#                 buvid3=loaded_data.buvid3,
#                 dedeuserid=loaded_data.dedeuserid,
#                 ac_time_value=loaded_data.ac_time_value
#             )
#         except:
#             traceback.print_exc()
#             print("#####【bilibili】登录凭证无效，请重新扫码登录（若首次扫描登录未成功，请关闭当前二维码窗口，程序会要求重新登录）")
#             return False
        
#         # 验证凭证的有效性
#         is_valid = sync(credential.check_valid())
#         if not is_valid:
#             print("#####【bilibili】登录凭证无效，请重新扫码登录（若首次扫描登录未成功，请关闭当前二维码窗口，程序会要求重新登录）")
#             return None
#         try:
#             need_refresh = sync(credential.check_refresh())
#             if need_refresh:
#                 print("#####【bilibili】正在尝试刷新登录凭证。")
#                 sync(credential.refresh())
#         except:
#             traceback.print_exc()
#             print("#####【bilibili】刷新登录凭证失败，请重新扫码登录（若首次扫描登录未成功，请关闭当前二维码窗口，程序会要求重新登录）")
#             return None
        
#         print(f"#####【bilibili】缓存登录成功：{sync(user.get_self_info(credential))['name']}")
#         return credential

def load_credential(credential_path):
    if not os.path.isfile(credential_path):
        print("#####【未找到bilibili登录凭证，请先扫码登录】")
        return None, None
    else:
        # 读取凭证文件
        with open(credential_path, 'rb') as f:
            try:
                loaded_data = pickle.load(f)
            except Exception as e:
                # 凭证二进制文件损坏或格式错误，删除凭证并提示重新登录
                if os.path.isfile(credential_path):
                    os.remove(credential_path)
                print(f"#####【bilibili】读取登录凭证失败: {str(e)}，请重新扫码登录")
                return None, None
        
        try:
            # 创建 Credential 实例
            credential = Credential(
                sessdata=loaded_data.sessdata,
                bili_jct=loaded_data.bili_jct,
                buvid3=loaded_data.buvid3,
                dedeuserid=loaded_data.dedeuserid,
                ac_time_value=loaded_data.ac_time_value
            )
        except:
            traceback.print_exc()
            print("#####【bilibili】登录凭证无效，请重新扫码登录")
            return None, None
        
        # 验证凭证的有效性
        is_valid = sync(credential.check_valid())
        if not is_valid:
            print("#####【bilibili】登录凭证已失效，请重新扫码登录")
            return None, None
        try:
            need_refresh = sync(credential.check_refresh())
            if need_refresh:
                print("#####【bilibili】正在尝试刷新登录凭据。")
                sync(credential.refresh())
        except:
            traceback.print_exc()
            print("#####【bilibili】刷新登录凭证失败，请重新扫码登录")
            return None, None
        
        username = sync(user.get_self_info(credential))['name']
        print(f"#####【bilibili】缓存登录成功：{username}")
        return credential, username

# async def download_url_from_bili(url: str, out: str, info: str):
#     async with httpx.AsyncClient(headers=HEADERS) as sess:
#         resp = await sess.get(url)
#         length = resp.headers.get('content-length')
#         with open(out, 'wb') as f:
#             process = 0
#             for chunk in resp.iter_bytes(1024):
#                 if not chunk:
#                     break

#                 process += len(chunk)
#                 percentage = (process / int(length)) * 100 if length else 0
#                 print(f'      -- [正在从bilibili下载流: {info} {percentage:.2f}%]', end='\r')
#                 f.write(chunk)
#         print("完成。\n")

async def download_url_from_bili(url: str, out: str, info: str, max_retries=3):
    """
    从B站下载流文件，支持断点续传和自动重试
    
    Args:
        url: 下载URL
        out: 输出文件路径
        info: 文件类型信息（用于显示）
        max_retries: 最大重试次数
    """
    # 配置超时时间（单位：秒）
    timeout = httpx.Timeout(
        connect=30.0,    # 连接超时
        read=60.0,       # 读取超时（大文件需要较长读取时间）
        write=30.0,      
        pool=None
    )
    
    # 记录已下载的大小
    downloaded_size = 0
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # 检查是否已有部分下载的文件，实现断点续传
            headers = HEADERS.copy()
            if os.path.exists(out) and downloaded_size > 0:
                # 设置Range头，从已下载的位置继续
                headers['Range'] = f'bytes={downloaded_size}-'
                print(f"\n      -- [尝试续传，从 {downloaded_size} 字节处继续]")
            
            async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as sess:
                resp = await sess.get(url)
                
                # 检查响应状态
                if resp.status_code == 416:  # Range Not Satisfiable
                    # 文件可能已经下载完成
                    if os.path.exists(out) and os.path.getsize(out) >= int(resp.headers.get('content-length', 0)):
                        print(f"      -- [{info} 已经下载完成]")
                        return
                
                resp.raise_for_status()
                
                # 获取总大小
                total_length = resp.headers.get('content-length')
                if total_length:
                    total_length = int(total_length)
                    # 如果是续传，调整总大小
                    if 'Range' in headers:
                        total_length += downloaded_size
                
                # 以追加模式打开文件
                mode = 'ab' if downloaded_size > 0 else 'wb'
                with open(out, mode) as f:
                    process = downloaded_size
                    
                    async for chunk in resp.aiter_bytes(1024 * 1024):  # 1MB chunks
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        process += len(chunk)
                        
                        if total_length:
                            percentage = (process / total_length) * 100
                            print(f'      -- [正在从bilibili下载流: {info} {percentage:.2f}%]', end='\r')
                        else:
                            print(f'      -- [正在从bilibili下载流: {info} 已下载 {process/1024/1024:.2f}MB]', end='\r')
                    
                    downloaded_size = process
                    
                    # 检查是否下载完整
                    if total_length and downloaded_size < total_length:
                        raise Exception(f"下载不完整: {downloaded_size}/{total_length}")
                    
                    print(f"\n      -- [{info} 下载完成，共 {downloaded_size/1024/1024:.2f}MB]")
                    return
                    
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError, 
                httpx.RemoteProtocolError, httpx.NetworkError) as e:
            retry_count += 1
            if retry_count < max_retries:
                wait_time = 2 ** retry_count  # 指数退避：2,4,8秒
                print(f"\n      -- [下载中断: {str(e)[:50]}...]")
                print(f"      -- [等待 {wait_time} 秒后重试 ({retry_count}/{max_retries})...]")
                
                # 记录已下载的文件大小
                if os.path.exists(out):
                    downloaded_size = os.path.getsize(out)
                
                await asyncio.sleep(wait_time)
            else:
                print(f"\n      -- [下载失败，已重试 {max_retries} 次]")
                raise
        except Exception as e:
            print(f"\n      -- [下载出错: {str(e)}]")
            raise


def _pick_bili_streams_compat(detecter, high_res):
    """自行挑选媒体流：[最佳视频流, 最佳音频流]，挑不到时为 [None, None]"""
    max_video_quality = video.VideoQuality._1080P_60 if high_res else video.VideoQuality._480P
    max_audio_quality = video.AudioQuality._192K
    video_streams, audio_streams = [], []

    for stream in detecter.detect_all():
        if isinstance(stream, video.VideoStreamDownloadURL):
            if stream.video_quality == video.VideoQuality.DOLBY:
                continue
            if not high_res and stream.video_quality == video.VideoQuality.HDR:
                continue
            if stream.video_quality.value > max_video_quality.value:
                continue
            video_streams.append(stream)
        elif isinstance(stream, video.AudioStreamDownloadURL):
            if stream.audio_quality == video.AudioQuality.DOLBY:
                continue
            if not high_res and stream.audio_quality == video.AudioQuality.HI_RES:
                continue
            if stream.audio_quality.value > max_audio_quality.value:
                continue
            audio_streams.append(stream)

    # 与 bilibili-api 一致：高清晰度模式下杜比视界 / HDR 优先
    def video_priority(stream):
        is_dolby_or_hdr = stream.video_quality in (video.VideoQuality.DOLBY, video.VideoQuality.HDR)
        return (int(is_dolby_or_hdr), stream.video_quality.value)

    best_video = max(video_streams, key=video_priority, default=None)
    best_audio = max(audio_streams, key=lambda s: s.audio_quality.value, default=None)
    return [best_video, best_audio]

def _ffmpeg_bin(tool_name: str = 'ffmpeg') -> str:
    """复用渲染链路那个解析器（运行目录 → 应用根目录 → PATH）。

    自己再留一层兜底不是为了重写逻辑，而是让只被部分更新的安装也能跑：
    万一 `utils/Quadrants/RenderIO.py` 还是旧版（只认 cwd）或缺件，这里仍能找到
    随包放在应用根目录的那份 ffmpeg，不必要求用户拷文件或改 PATH。
    """
    try:
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        return get_ffmpeg_binary(tool_name)
    except Exception:
        executable = f"{tool_name}.exe" if os.name == 'nt' else tool_name
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled = os.path.join(app_root, executable)
        if os.path.exists(bundled):
            return bundled
        return shutil.which(tool_name) or tool_name


def merge_streams(input_files, output_file):
    """把已下载好的媒体流封装成 output_file。成功返回 None，失败返回可直接展示的原因。

    旧实现是 os.system 拼字符串 + `> NUL 2>&1`：ffmpeg 的报错被丢掉、返回码没人看，
    "合并完成"因此是无条件打印，真相只剩下游存在性校验，且不带任何成因。
    """
    staged = f"{output_file}.part"
    cmd = [_ffmpeg_bin(), '-y']
    for stream_file in input_files:
        cmd += ['-i', stream_file]
    cmd += ['-vcodec', 'copy', '-acodec', 'copy', '-f', 'mp4', staged]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    except OSError as e:
        return f"无法启动 ffmpeg（{cmd[0]}）：{e}"

    if result.returncode == 0 and os.path.isfile(staged) and os.path.getsize(staged) > 0:
        os.replace(staged, output_file)
        return None

    if os.path.exists(staged):
        os.remove(staged)
    lines = [line.strip() for line in (result.stderr or '').splitlines() if line.strip()]
    return " / ".join(lines[-4:]) or f"ffmpeg 退出码 {result.returncode}，且没有产出文件"


def stash_failed_streams(temp_files, clip_name):
    """合并失败时把输入流改名留下，否则现场被清掉就没法手工复现这条 ffmpeg 命令。"""
    kept = []
    for name in temp_files:
        target = f"failed_{clip_name}_{name}"
        if os.path.exists(name):
            try:
                os.replace(name, target)
                kept.append(target)
            except OSError:
                kept.append(name)
    return kept

def _detect_bili_streams(detecter, high_res):
    """获取最佳媒体流: 返回列表中0是视频流，1是音频流"""
    # 只做 stream copy 封进 mp4，杜比视界/杜比音频这类流 muxer 不收 —— 两种画质档都得排除。
    # 旧代码只在低画质档排除，勾了高分辨率就会选到必然合并失败的流。
    quality_args = dict(no_dolby_video=True, no_dolby_audio=True)
    if not high_res:
        quality_args.update(video_max_quality=video.VideoQuality._480P, no_hdr=True)
    try:
        return detecter.detect_best_streams(**quality_args)
    except AttributeError:
        # bilibili-api<=17.4.1 无法识别 hvc1/dvh1 等编码，会以 None 参与排序
        print("      -- [bilibili-api 选流失败，改用兼容模式挑选媒体流]")
        return _pick_bili_streams_compat(detecter, high_res)

async def bilibili_download(bvid, credential, output_name, output_path, high_res=False, p_index=0):
    v = video.Video(bvid=bvid, credential=credential)
    download_url_data = await v.get_download_url(p_index)
    detecter = video.VideoDownloadURLDataDetecter(data=download_url_data)

    streams = _detect_bili_streams(detecter, high_res)
    is_flv_mp4 = detecter.check_flv_mp4_stream()
    if streams[0] is None or (not is_flv_mp4 and streams[1] is None):
        raise Exception(f"{bvid} 第 {p_index + 1} 分P 没有可下载的媒体流（可能需要大会员权限，或该分P 尚未转码完成）")

    # 必须在下面的 os.chdir 之前转成绝对路径：output_path 可能是 "./videos/downloads" 这类相对路径，
    # 切换工作目录后再解析会指向不存在的嵌套目录，ffmpeg 会静默合并失败
    output_file = os.path.abspath(os.path.join(output_path, f"{output_name}.mp4"))
    
    # 确保输出目录存在
    os.makedirs(output_path, exist_ok=True)
    
    # 切换到临时文件所在目录
    original_dir = os.getcwd()
    os.chdir(output_path)
    
    try:
        if is_flv_mp4:
            # FLV 流下载（增加重试次数）
            await download_url_from_bili(streams[0].url, "flv_temp.flv", "FLV 音视频", max_retries=5)
            error = merge_streams(["flv_temp.flv"], output_file)
            if error:
                kept = stash_failed_streams(["flv_temp.flv"], output_name)
                raise Exception(f"封装 FLV 失败: {error}（输入已保留为 {', '.join(kept)}）")
            os.remove("flv_temp.flv")
            print(f"下载完成，存储为: {output_name}.mp4")
        else:
            # MP4 流下载（增加重试次数）
            await download_url_from_bili(streams[0].url, "video_temp.m4s", "视频流", max_retries=5)
            await download_url_from_bili(streams[1].url, "audio_temp.m4s", "音频流", max_retries=5)
            
            print(f"下载完成，正在合并视频和音频")
            error = merge_streams(["video_temp.m4s", "audio_temp.m4s"], output_file)
            if error:
                kept = stash_failed_streams(["video_temp.m4s", "audio_temp.m4s"], output_name)
                raise Exception(f"合并音视频失败: {error}（输入已保留为 {', '.join(kept)}）")
            for temp in ("video_temp.m4s", "audio_temp.m4s"):
                if os.path.exists(temp):
                    os.remove(temp)
            print(f"合并完成，存储为: {output_name}.mp4")
    finally:
        # 恢复原始目录
        os.chdir(original_dir)

class Downloader(ABC):
    @abstractmethod
    def search_video(self, keyword):
        pass

    @abstractmethod
    def download_video(self, video_id, output_name, output_path, high_res=False, p_index=0):
        pass
    
    @abstractmethod
    def get_video_info(self, video_id):
        """通过视频ID直接获取视频信息"""
        pass
    
    @abstractmethod
    def get_video_pages(self, video_id):
        """获取视频的分P信息（如果有）"""
        pass

class PurePytubefixDownloader(Downloader):
    """
    使用pytubefix或YouTube Data API v3进行搜索和下载的youtube视频下载器
    """
    def __init__(self, proxy=None, use_oauth=False, use_potoken=False, auto_get_potoken=False, 
                 search_max_results=5, search_scan_pages=2, use_api=False, api_key=None):
        self.proxy = proxy
        # use_oauth 和 use_potoken 互斥，优先使用use_potoken
        self.use_potoken = use_potoken
        if use_potoken:
            self.use_oauth = False
        else:
            self.use_oauth = use_oauth
        if auto_get_potoken:
            self.po_token_verifier = autogen_po_token_verifier
        else:
            self.po_token_verifier = custom_po_token_verifier

        self.search_max_results = search_max_results
        self.search_scan_pages = max(1, int(search_scan_pages or 1))
        self.use_api = use_api  # 是否使用 YouTube Data API v3 进行搜索
        self.api_key = api_key  # YouTube Data API v3 的 API Key
        
        # 如果没有提供 API Key，尝试从配置文件读取
        if self.use_api and not self.api_key:
            try:
                # with open("global_config.yaml", "r", encoding="utf-8") as f:
                #     config = yaml.load(f, Loader=yaml.FullLoader)
                config = read_global_config()
                self.api_key = config.get('YOUTUBE_API_KEY', '')
            except Exception as e:
                print(f"读取配置文件失败: {e}")
                self.api_key = ''
    
    def search_video(self, keyword):
        # 如果配置了使用 API，优先使用 YouTube Data API v3
        if self.use_api and self.api_key:
            return self._search_video_with_api(keyword)
        else:
            return self._search_video_with_pytubefix(keyword)
    
    def _search_video_with_api(self, keyword):
        """
        使用 YouTube Data API v3 进行搜索
        
        参考: https://developers.google.com/youtube/v3/docs/search/list
        """
        keyword = keyword.strip()
        
        # YouTube Data API v3 搜索端点
        # api_url = "https://www.googleapis.com/youtube/v3/search"
        api_url = YTB_DATAV3_ENDPOINT + "search"
        params = {
            'part': 'snippet',
            'q': keyword,
            'type': 'video',
            'maxResults': SEARCH_SCAN_SIZE,
            'key': self.api_key,
            'order': 'relevance'  # 按相关性排序
        }
        
        # 配置代理
        proxies = None
        if self.proxy:
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # search 单次最多返回 50 条，多出的扫描量靠 nextPageToken 翻页
                items = []
                page_token = None
                for _ in range(self.search_scan_pages):
                    request_params = dict(params, pageToken=page_token) if page_token else params
                    response = requests.get(api_url, params=request_params, proxies=proxies, timeout=10)
                    response.raise_for_status()

                    data = response.json()
                    items.extend(data.get('items') or [])
                    page_token = data.get('nextPageToken')
                    if not page_token:
                        break

                if not items:
                    print(f"API搜索未找到结果: {keyword}")
                    return []
                
                videos = []
                video_ids = [item['id']['videoId'] for item in items]
                
                # 获取视频详细信息（包括时长）
                videos_info = self._get_videos_duration(video_ids)
                
                for item in items:
                    video_id = item['id']['videoId']
                    snippet = item['snippet']
                    
                    # 获取视频时长
                    duration = videos_info.get(video_id, 0)
                    
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    videos.append({
                        'id': video_url,
                        'pure_id': video_id,
                        'title': remove_html_tags_and_invalid_chars(snippet['title']),
                        'url': video_url,
                        'duration': duration
                    })
                
                return videos
                
            except requests.exceptions.HTTPError as e:
                error_msg = str(e)
                if response.status_code == 403:
                    raise Exception(f"YouTube API 搜索失败 (403错误): API Key 可能无效或配额已用完。请检查 API Key 配置。")
                elif response.status_code == 400:
                    if attempt < max_retries - 1:
                        print(f"API搜索失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                        print(f"等待 {retry_delay} 秒后重试...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        raise Exception(f"YouTube API 搜索失败 (400错误): {error_msg}。系统将自动尝试其他搜索策略。")
                else:
                    raise Exception(f"YouTube API 搜索失败: {error_msg}")
            except Exception as e:
                error_msg = str(e)
                if attempt < max_retries - 1:
                    print(f"API搜索失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise Exception(f"YouTube API 搜索失败: {error_msg}")
        
        return []
    
    def _get_videos_duration(self, video_ids):
        """
        通过 YouTube Data API v3 获取视频时长
        
        参考: https://developers.google.com/youtube/v3/docs/videos/list
        """
        if not video_ids:
            return {}
        
        # api_url = "https://www.googleapis.com/youtube/v3/videos"
        api_url = YTB_DATAV3_ENDPOINT + "videos"
        
        proxies = None
        if self.proxy:
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        
        durations = {}
        # videos.list 单次最多接受 100 个 id
        for start in range(0, len(video_ids), 100):
            chunk = video_ids[start:start + 100]
            params = {
                'part': 'contentDetails',
                'id': ','.join(chunk),
                'key': self.api_key
            }
            try:
                response = requests.get(api_url, params=params, proxies=proxies, timeout=10)
                response.raise_for_status()

                for item in response.json().get('items', []):
                    durations[item['id']] = self._parse_duration(item['contentDetails']['duration'])
            except Exception as e:
                print(f"获取视频时长失败: {e}")
                for video_id in chunk:
                    durations.setdefault(video_id, 0)

        return durations
    
    def _parse_duration(self, duration_str):
        """
        将 ISO 8601 格式的时长（如 PT1H2M10S）转换为秒数
        """
        import re
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        if not match:
            return 0
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return hours * 3600 + minutes * 60 + seconds
    
    def _search_video_with_pytubefix(self, keyword):
        """
        使用 pytubefix 进行搜索（原有方法）
        """
        # 清理搜索关键词
        keyword = keyword.strip()
        # 注意：不要对关键词进行URL编码，pytubefix的Search类会自己处理
        
        if self.proxy:
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        else:
            proxies = None

        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                # 尝试使用不同的配置进行搜索
                if self.use_potoken:
                    # 使用 PO Token
                    results = Search(keyword, 
                                   proxies=proxies, 
                                   use_oauth=False, 
                                   use_po_token=True,
                                   po_token_verifier=self.po_token_verifier)
                elif self.use_oauth:
                    # 使用 OAuth
                    results = Search(keyword, 
                                   proxies=proxies, 
                                   use_oauth=True, 
                                   use_po_token=False)
                else:
                    # 不使用认证（可能更容易触发400错误，但先尝试）
                    results = Search(keyword, 
                                   proxies=proxies, 
                                   use_oauth=False, 
                                   use_po_token=False)
                
                videos = []
                for result in results.videos:
                    videos.append({
                        'id': result.watch_url,  # 使用Pytubefix时，video_id是url字符串
                        'pure_id': result.video_id,
                        'title': remove_html_tags_and_invalid_chars(result.title),
                        'url': result.watch_url,
                        'duration': result.length
                    })
                    if len(videos) >= SEARCH_SCAN_SIZE * self.search_scan_pages:
                        break
                return videos
                
            except Exception as e:
                error_msg = str(e)
                # 对于400错误和其他错误，都进行重试
                if attempt < max_retries - 1:
                    print(f"搜索失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                    print(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                    continue
                else:
                    # 所有重试均失败，抛出异常让上层多策略系统尝试下一个关键词
                    if "400" in error_msg or "Bad Request" in error_msg:
                        raise Exception(f"YouTube搜索失败 (400错误): {error_msg}。系统将自动尝试其他搜索策略。")
                    else:
                        raise
    
    def get_video_info(self, video_id):
        """
        通过视频ID直接获取YouTube视频信息
        video_id: YouTube视频ID (例如: dQw4w9WgXcQ) 或完整URL
        """
        import time
        
        if self.proxy:
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        else:
            proxies = None

        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                # 如果输入的是完整URL，直接使用；否则构建URL
                if video_id.startswith('http'):
                    url = video_id
                else:
                    # url = f"https://www.youtube.com/watch?v={video_id}"
                    url = YTB_URL_PREFIX + video_id
                
                # 尝试使用不同的配置获取视频信息
                if self.use_potoken:
                    yt = YouTube(url, 
                               proxies=proxies, 
                               use_oauth=False, 
                               use_po_token=True,
                               po_token_verifier=self.po_token_verifier)
                elif self.use_oauth:
                    yt = YouTube(url, 
                               proxies=proxies, 
                               use_oauth=True, 
                               use_po_token=False)
                else:
                    yt = YouTube(url, 
                               proxies=proxies, 
                               use_oauth=False, 
                               use_po_token=False)
                
                # 返回符合存档格式的video_info信息
                video_info = {
                    'id': yt.watch_url,
                    'pure_id': yt.video_id,
                    'title': remove_html_tags_and_invalid_chars(yt.title),
                    'url': yt.watch_url,
                    'duration': yt.length,
                    'page_count': 1,  # YouTube视频没有分P
                    'p_index': 0  # 默认为0
                }
                return video_info
                
            except Exception as e:
                error_msg = str(e)
                if "400" in error_msg or "Bad Request" in error_msg or "HTTP Error" in error_msg:
                    if attempt < max_retries - 1:
                        print(f"获取视频信息失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                        print(f"等待 {retry_delay} 秒后重试...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                        continue
                    else:
                        raise Exception(f"YouTube获取视频信息失败: {error_msg}。建议：1) 检查视频ID是否正确，2) 更新pytubefix库 (pip install --upgrade pytubefix)，3) 配置PO Token或OAuth认证，4) 检查网络连接。")
                else:
                    # 其他类型的错误直接抛出
                    raise
        
        # 如果所有重试都失败了
        raise Exception("获取YouTube视频信息失败，已超过最大重试次数。")

    def search_video_from_playlist(self, playlist_id, keyword=None):
        """从YouTube播放列表中获取所有视频"""
        from pytubefix.contrib.playlist import Playlist
        proxies = {'http': self.proxy, 'https': self.proxy} if self.proxy else None
        playlist_url = playlist_id if playlist_id.startswith('http') else f"https://www.youtube.com/playlist?list={playlist_id}"
        try:
            if self.use_potoken:
                pl = Playlist(playlist_url, proxies=proxies, use_po_token=True, po_token_verifier=self.po_token_verifier)
            elif self.use_oauth:
                pl = Playlist(playlist_url, proxies=proxies, use_oauth=True)
            else:
                pl = Playlist(playlist_url, proxies=proxies)
            all_videos = []
            for video in pl.videos:
                title = remove_html_tags_and_invalid_chars(video.title)
                all_videos.append({
                    'id': video.watch_url, 'pure_id': video.video_id,
                    'title': title, 'url': video.watch_url, 'duration': video.length
                })
            return all_videos
        except Exception as e:
            raise Exception(f"获取YouTube播放列表失败: {e}")

    def get_video_pages(self, video_id):
        """
        获取YouTube视频的分P信息
        YouTube视频没有分P的概念，返回一个只包含单个页面的列表
        """
        # YouTube 没有分P，返回简单的单页信息
        return [
            {
                "page": 1,
                "part": "完整视频",
                "duration": 0,  # 如果需要真实时长，需要重新调用API
            }
        ]
    
    def download_video(self, video_id, output_name, output_path, high_res=False, p_index=0):
        # p_index 是基类统一签名的一部分（download_one_video 会按分P传入）；
        # YouTube 没有分P概念，这里接受但忽略，否则调用会直接 TypeError
        try:
            if not os.path.exists(output_path):
                os.makedirs(output_path)

            if self.proxy:
                proxies = {
                    'http': self.proxy,
                    'https': self.proxy
                }
            else:
                proxies = None

            yt = YouTube(video_id, 
                         proxies=proxies, 
                         use_oauth=self.use_oauth, 
                         use_po_token=self.use_potoken,
                         po_token_verifier=self.po_token_verifier)
            
            print(f"正在下载: {yt.title}")
            if high_res:
                # 分别下载视频和音频
                video = yt.streams.filter(adaptive=True, file_extension='mp4').\
                    order_by('resolution').desc().first()
                audio = yt.streams.filter(only_audio=True).first()
                down_video = video.download(output_path, "video_temp")
                down_audio = audio.download(output_path, "audio_temp")
                print(f"下载完成，正在合并视频和音频")
                output_file = os.path.join(output_path, f"{output_name}.mp4")
                error = merge_streams([down_video, down_audio], output_file)
                if error:
                    # 失败时不动临时文件：留在原地才能手工复现这条命令
                    raise Exception(f"合并音视频失败: {error}")
                os.remove(down_video)
                os.remove(down_audio)
                print(f"合并完成，存储为: {output_name}.mp4")
            else:
                downloaded_file = yt.streams.filter(progressive=True, file_extension='mp4').\
                    order_by('resolution').desc().first().download(output_path)
                # 重命名下载到的视频文件
                new_filename = f"{output_name}.mp4"
                output_file = os.path.join(output_path, new_filename)
  
                # 检查文件是否存在，如果存在则删除
                if os.path.exists(output_file):
                    os.remove(output_file)  # 删除已存在的文件
                
                os.rename(downloaded_file, output_file)
                print(f"下载完成，存储为: {new_filename}")

            return output_file
            
        except Exception as e:
            print(f"下载视频时发生错误:")
            traceback.print_exc()
            return None

class BilibiliQrCodeLoginSession:
    """
    Bilibili 网页端扫码登录会话

    不使用 login_v2.QrCodeLogin 取凭证：它的 WEB 分支从轮询结果的 url 查询参数里解析
    SESSDATA/bili_jct，而 B 站现在改为通过响应头 Set-Cookie 下发，导致取到的凭证是空的
    （表现为"扫码成功 → Credential 类未提供 bili_jct 或者为空"）。

    使用方式：
    1. 调用 generate_qrcode() 获取二维码图片
    2. 循环调用 check_state() 检查登录状态
    3. 登录成功后调用 get_credential() 获取凭证
    """
    def __init__(self):
        self._qr_key = None
        self._credential = None
        self._generated = False

    async def _request(self, api, params=None):
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=False) as sess:
            return await sess.get(api["url"], params=params)

    def generate_qrcode(self):
        """生成二维码，返回 PIL Image 对象"""
        import io
        from PIL import Image
        import qrcode

        async def _generate():
            api = login_v2.API["qrcode"]["web"]["get_qrcode_and_token"]
            resp = await self._request(api)
            data = (resp.json() or {}).get("data") or {}
            if not data.get("qrcode_key"):
                raise Exception(f"获取二维码失败：{resp.text[:200]}")
            self._qr_key = data["qrcode_key"]

            qr = qrcode.QRCode()
            qr.add_data(data["url"])
            buffer = io.BytesIO()
            qr.make_image().save(buffer, format="PNG")
            buffer.seek(0)
            self._generated = True
            return Image.open(buffer)
        return sync(_generate())

    def check_state(self):
        """
        轮询扫码状态；登录成功时从响应头取出完整 Cookie

        返回: (state, message)
            state: 'waiting' | 'confirmed' | 'success' | 'timeout' | 'error'
        """
        if not self._generated or not self._qr_key:
            return ('error', '请先生成二维码')
        if self._credential is not None:
            return ('success', '登录成功！')

        async def _poll():
            api = login_v2.API["qrcode"]["web"]["get_events"]
            return await self._request(api, params={"qrcode_key": self._qr_key,
                                                     "source": "main-fe-header"})
        try:
            resp = sync(_poll())
            payload = resp.json() or {}
        except Exception as e:
            return ('error', f'查询扫码状态失败：{e}')

        data = payload.get("data") or {}
        code = data.get("code", payload.get("code"))
        if code == 86101:
            return ('waiting', '咱就在这里，等扫这个二维码。')
        elif code == 86090:
            return ('confirmed', '扫完了，不点下确认吗？')
        elif code == 86038:
            return ('timeout', '当前二维码已过期，请刷新重试。')

        cookies = resp.cookies
        if not cookies.get("SESSDATA"):
            return ('error', f'登录未完成（code={code}），请重新扫码')

        credential_args = {
            "sessdata": cookies["SESSDATA"],
            "dedeuserid": cookies.get("DedeUserID", ""),
            "ac_time_value": data.get("refresh_token", ""),
        }
        if cookies.get("bili_jct"):
            credential_args["bili_jct"] = cookies["bili_jct"]
        if cookies.get("buvid3"):
            credential_args["buvid3"] = cookies["buvid3"]
        self._credential = Credential(**credential_args)
        return ('success', '登录成功！')

    def get_credential(self):
        """获取登录凭证，仅在登录成功后有效"""
        return self._credential


def streamlit_login_bilibili(credential_path="cred_datas/bilibili_cred.pkl"):
    """
    在 Streamlit 中进行 Bilibili 登录
    
    返回: (success: bool, credential: Credential|None, message: str)
    
    注意：此函数应该在 Streamlit 页面中调用，它会：
    1. 显示二维码
    2. 轮询检查登录状态
    3. 登录成功后保存凭证
    """
    import streamlit as st
    
    # 创建登录会话
    if 'bilibili_login_session' not in st.session_state:
        st.session_state.bilibili_login_session = BilibiliQrCodeLoginSession()
    
    session = st.session_state.bilibili_login_session
    
    with st.expander("Bilibili 扫码登录", expanded=False, icon="📱"):
        # 显示二维码
        qr_placeholder = st.empty()
        status_placeholder = st.empty()
        
        # 生成二维码
        if 'bilibili_qr_image' not in st.session_state:
            try:
                qr_image = session.generate_qrcode()
                st.session_state.bilibili_qr_image = qr_image
            except Exception as e:
                return (False, None, f"生成二维码失败: {str(e)}", None)
        
        # 显示二维码图片
        qr_placeholder.image(st.session_state.bilibili_qr_image, caption="请使用哔哩哔哩客户端扫描此二维码")
        
        # 检查登录状态
        state, message = session.check_state()
        status_placeholder.info(message, icon="📱")
        
        if state == 'success':
            # 登录成功
            credential = session.get_credential()
            
            # 验证凭证
            try:
                credential.raise_for_no_bili_jct()
                credential.raise_for_no_sessdata()
            except Exception as e:
                # 清理会话
                del st.session_state.bilibili_login_session
                if 'bilibili_qr_image' in st.session_state:
                    del st.session_state.bilibili_qr_image
                return (False, None, f"凭证验证失败: {str(e)}", None)
            
            # 获取用户名
            username = sync(user.get_self_info(credential))['name']
            
            # 保存凭证
            os.makedirs(os.path.dirname(credential_path), exist_ok=True)
            with open(credential_path, 'wb') as f:
                pickle.dump(credential, f)
            
            # 清理会话
            del st.session_state.bilibili_login_session
            if 'bilibili_qr_image' in st.session_state:
                del st.session_state.bilibili_qr_image
            
            return (True, credential, f"登录成功！", username)
        
        elif state == 'timeout':
            # 清理过期的二维码
            if 'bilibili_qr_image' in st.session_state:
                del st.session_state.bilibili_qr_image
            del st.session_state.bilibili_login_session
            return (False, None, "二维码已过期，请刷新页面重试", None)
        
        else:
            # 等待中，返回 None 表示需要继续轮询
            return (False, None, message, None)

class BilibiliDownloader(Downloader):
    # def __init__(self, proxy=None, no_credential=False, credential_path="cred_datas/bilibili_cred.pkl", search_max_results=3):
    #     self.proxy = proxy
    #     self.search_max_results = search_max_results
        
    #     if no_credential:
    #         self.credential = None
    #         return
        
    #     self.credential = load_credential(credential_path)
    #     if self.credential:
    #         return
        
    #     for attempt in range(MAX_LOGIN_RETRIES):
    #         log_succ = self.log_in(credential_path)
    #         if log_succ:
    #             break  # 登录成功，退出循环
    #         print(f"正在尝试第 {attempt + 1} 次重新登录...")
    
    def __init__(self, proxy=None, no_credential=False, credential_path="cred_datas/bilibili_cred.pkl", search_max_results=5, search_scan_pages=2, skip_login=False):
        self.proxy = proxy
        self.search_max_results = search_max_results
        self.search_scan_pages = max(1, int(search_scan_pages or 1))
        self.credential_path = credential_path
        
        if no_credential:
            self.credential = None
            return
        
        self.credential, self.username = load_credential(credential_path)
        if self.credential:
            return
        
        # 如果跳过登录（用于 Streamlit 等异步环境），则不自动登录
        if skip_login:
            self.credential = None
            return
        
        # 原有的自动登录逻辑（使用终端打印二维码）
        for attempt in range(MAX_LOGIN_RETRIES):
            log_succ = self._login_terminal(credential_path)
            # log_succ = self.log_in(credential_path)
            if log_succ:
                break  # 登录成功，退出循环
            print(f"正在尝试第 {attempt + 1} 次重新登录...")
    
    def get_credential_username(self):
        if not self.credential:
            return None
        return sync(user.get_self_info(self.credential))['name']

    # def log_in(self, credential_path):
    #     credential = login.login_with_qrcode() # 使用 Tkinter 窗口显示二维码登录
    #     try:
    #         credential.raise_for_no_bili_jct() # 判断是否成功
    #         credential.raise_for_no_sessdata() # 判断是否成功
    #     except:
    #         print("#####【登录失败，请重试】")
    #         return False
    #     print(f"#####【bilibili】登录成功：{sync(user.get_self_info(credential))['name']}】")
    #     self.credential = credential
    #     # 缓存凭证
    #     with open(credential_path, 'wb') as f:
    #         pickle.dump(credential, f)
    #     return True
    
    # def log_in(self, credential_path):
    #     """
    #     稳定版：所有 Tkinter 操作都在主线程，使用 after 轮询
    #     """
    #     # 创建窗口
    #     root = tk.Tk()
    #     root.title("哔哩哔哩登录")
    #     root.geometry("450x450")

    #     # 状态标签
    #     status_label = tk.Label(root, text="正在生成二维码...", font=("msyh", 20))
    #     status_label.pack(pady=10)

    #     # 二维码标签
    #     qr_label = tk.Label(root)
    #     qr_label.pack(pady=10)

    #     # 标志：用户是否手动关闭了窗口
    #     window_closed = False

    #     def on_closing():
    #         nonlocal window_closed
    #         window_closed = True
    #         root.destroy()

    #     root.protocol("WM_DELETE_WINDOW", on_closing)

    #     # 立即更新窗口
    #     root.update()

    #     # 存储登录结果
    #     login_result = [False]      # 用列表以便在嵌套函数中修改
    #     credential_result = [None]

    #     try:
    #         # 1. 生成二维码（同步，短暂阻塞，但有 update 保持响应）
    #         qr_login = login_v2.QrCodeLogin()
    #         sync(qr_login.generate_qrcode())

    #         if not qr_login.has_qrcode():
    #             status_label.config(text="生成二维码失败", fg="red")
    #             root.update()
    #             time.sleep(2)
    #             root.destroy()
    #             return False

    #         qr_picture = qr_login.get_qrcode_picture()

    #         # 获取图片数据
    #         if qr_picture.content:
    #             img_data = qr_picture.content
    #             qr_img = Image.open(io.BytesIO(img_data))
    #         else:
    #             import tempfile
    #             temp_path = tempfile.mktemp(suffix=".png")
    #             qr_picture.to_file(temp_path)
    #             qr_img = Image.open(temp_path)

    #         # 显示二维码
    #         qr_img_resized = qr_img.resize((350, 350), Image.Resampling.LANCZOS)
    #         photo = ImageTk.PhotoImage(qr_img_resized, master=root)  # 指定 master
    #         qr_label.config(image=photo)
    #         root.update()

    #         # 2. 轮询登录状态（使用 after，在主线程中执行）
    #         def poll_login():
    #             if window_closed or login_result[0]:  # 窗口已关闭或已登录成功，停止轮询
    #                 return

    #             try:
    #                 event = sync(qr_login.check_state())

    #                 if event == login_v2.QrCodeLoginEvents.SCAN:
    #                     status_label.config(text="请使用 哔哩哔哩 手机客户端扫描", fg="orange")
    #                 elif event == login_v2.QrCodeLoginEvents.CONF:
    #                     status_label.config(text="已扫描，请在您的手机上确认", fg="blue")
    #                 elif event == login_v2.QrCodeLoginEvents.DONE:
    #                     credential = qr_login.get_credential()
    #                     credential_result[0] = credential
    #                     login_result[0] = True
    #                     status_label.config(text="登录成功！", fg="green")
    #                     root.update()
    #                     time.sleep(0.5)
    #                     root.destroy()
    #                     return
    #                 elif event == login_v2.QrCodeLoginEvents.TIMEOUT:
    #                     status_label.config(text="二维码已过期", fg="red")
    #                     root.update()
    #                     time.sleep(2)
    #                     root.destroy()
    #                     return

    #                 # 继续轮询
    #                 root.after(1000, poll_login)

    #             except Exception as e:
    #                 print(f"轮询出错: {e}")
    #                 traceback.print_exc()
    #                 status_label.config(text="登录出错", fg="red")
    #                 root.after(2000, root.destroy)

    #         # 启动轮询（延迟1秒开始）
    #         root.after(1000, poll_login)

    #         # 运行主循环，直到窗口关闭
    #         root.mainloop()

    #     except Exception as e:
    #         print(f"登录异常: {e}")
    #         traceback.print_exc()
    #         try:
    #             status_label.config(text="错误", fg="red")
    #             root.update()
    #             time.sleep(2)
    #         except:
    #             pass
    #         root.destroy()

    #     # 主循环结束后，根据登录结果保存凭证
    #     if login_result[0] and credential_result[0]:
    #         try:
    #             credential = credential_result[0]
    #             credential.raise_for_no_bili_jct()
    #             credential.raise_for_no_sessdata()
    #             username = sync(user.get_self_info(credential))['name']
    #             print(f"#####【bilibili】登录成功：{username}")
    #             self.credential = credential
    #             with open(credential_path, 'wb') as f:
    #                 pickle.dump(credential, f)
    #             return True
    #         except Exception as e:
    #             print(f"凭证验证失败: {e}")
    #             traceback.print_exc()
    #             return False
    #     else:
    #         if window_closed:
    #             print("用户取消登录")
    #         else:
    #             print("登录失败")
    #         return False
    
    def _login_terminal(self, credential_path):
        """
        使用终端打印二维码的方式登录（fallback 方案）
        """
        async def _login():
            qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
            # 生成二维码
            await qr.generate_qrcode()
            
            # ✅ 正确：使用 get_qrcode_terminal() 获取终端显示的二维码字符画
            qr_terminal_str = qr.get_qrcode_terminal()
            print("\n请使用哔哩哔哩客户端扫描以下二维码登录：")
            print(qr_terminal_str)
            
            # 轮询检查登录状态
            while True:
                if qr.has_done():
                    return qr.get_credential()
                
                state = await qr.check_state()
                
                if state == login_v2.QrCodeLoginEvents.DONE:
                    print("\n登录成功！")
                    return qr.get_credential()
                elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
                    print("\n二维码已过期")
                    return None
                elif state == login_v2.QrCodeLoginEvents.SCAN:
                    print("\r正在等待扫描...", end="", flush=True)
                elif state == login_v2.QrCodeLoginEvents.CONF:
                    print("\r点下确认啊！", end="", flush=True)
                
                await asyncio.sleep(1)
        
        credential = sync(_login())
        
        if credential is None:
            print("\n#####【登录失败，请重试】")
            return False
        
        try:
            credential.raise_for_no_bili_jct()
            credential.raise_for_no_sessdata()
        except:
            print("\n#####【登录失败，请重试】")
            return False
        
        print(f"\n#####【登录bilibili成功，登录账号为：{sync(user.get_self_info(credential))['name']}】")
        self.credential = credential
        with open(credential_path, 'wb') as f:
            pickle.dump(credential, f)
        return True
    
    # def _login_terminal(self, credential_path):
    #     """
    #     使用终端打印二维码的方式登录（fallback 方案）
    #     """
    #     import qrcode_terminal
        
    #     async def _login():
    #         qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
    #         await qr.generate_qrcode()
            
    #         # 获取二维码链接并在终端打印
    #         qr_url = qr.generate_qrcode()
    #         print("\n请使用哔哩哔哩客户端扫描以下二维码登录：")
    #         qrcode_terminal.qrcode(qr_url)
    #         print("\n或访问以下链接扫码：")
    #         print(qr_url)
            
    #         # 轮询检查登录状态
    #         while True:
    #             if qr.has_done():
    #                 return qr.get_credential()
                
    #             state = await qr.check_state()
                
    #             if state == login_v2.QrCodeLoginEvents.DONE:
    #                 return qr.get_credential()
    #             elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
    #                 print("\n二维码已过期")
    #                 return None
    #             elif state == login_v2.QrCodeLoginEvents.SCAN:
    #                 print("\r已扫描，请在手机上确认登录...", end="", flush=True)
    #             elif state == login_v2.QrCodeLoginEvents.CONF:
    #                 print("\r已确认，正在登录...", end="", flush=True)
                
    #             await asyncio.sleep(1)
        
    #     credential = sync(_login())
        
    #     if credential is None:
    #         print("\n#####【登录失败，请重试】")
    #         return False
        
    #     try:
    #         credential.raise_for_no_bili_jct()
    #         credential.raise_for_no_sessdata()
    #     except:
    #         print("\n#####【登录失败，请重试】")
    #         return False
        
    #     print(f"\n#####【登录bilibili成功，登录账号为：{sync(user.get_self_info(credential))['name']}】")
    #     self.credential = credential
    #     with open(credential_path, 'wb') as f:
    #         pickle.dump(credential, f)
    #     return True
    
    def set_credential(self, credential):
        """设置凭证（用于 Streamlit 登录后手动设置）"""
        self.credential = credential
    
    def search_video(self, keyword): 
        # 每页向 B 站取 50 条候选（实测 page_size 50 为单请求上限），排名和截断交给上层按曲名/难度做
        videos = []
        for page in range(1, self.search_scan_pages + 1):
            results = sync(
                search.search_by_type(keyword=keyword, 
                                      search_type=search.SearchObjectType.VIDEO,
                                      order_type=search.OrderVideo.TOTALRANK,
                                      order_sort=0,  # 由高到低
                                      page=page,
                                      page_size=SEARCH_SCAN_SIZE)
            )
            if 'result' not in results:
                if page == 1:
                    print(f"搜索结果异常，请检查如下输出：")
                    print(results)
                break
            batch = results['result']
            if not batch:
                break

            for each in batch:
                vid = each.get('bvid')
                if not vid:
                    continue
                # 搜索接口已带标题与时长，不再逐条请求视频详情：否则一次搜索就是几十次请求，很容易触发风控
                videos.append({
                    "id": vid,
                    "aid": each.get('aid', 0),
                    "title": remove_html_tags_and_invalid_chars(each.get('title', '')),
                    "duration": convert_duration_to_seconds(each.get('duration', 0)),
                    "url": BILI_URL_PREFIX + vid,
                })
            if len(batch) < SEARCH_SCAN_SIZE:
                break  # 不足一页说明没有更多结果
        return videos

    def download_video(self, video_id, output_name, output_path, high_res=False, p_index=0):
        if not self.credential:
            print(f"Warning: 未成功配置bilibili登录凭证，下载视频可能失败！")
        # 使用异步方法下载
        result = asyncio.run(
            bilibili_download(bvid=video_id, 
                              credential=self.credential, 
                              output_name=output_name, 
                              output_path=output_path,
                              high_res=high_res,
                              p_index=p_index)
        )

    def get_video_info(self, video_id):
        # 获取视频信息
        v = video.Video(bvid=video_id, credential=self.credential)
        info = sync(v.get_info())

        # 返回符合存档格式的match_info信息
        match_info = {
            "id": info.get("bvid", ""),
            "aid": info.get("aid", 0),
            "title": info.get("title", ""),
            "duration": info.get("duration", 0),
            "page_count": len(info.get("pages", [])),
            "p_index": info.get("p_index", 0),
            "url": BILI_URL_PREFIX + info.get("bvid", ""),
        }
        return match_info

    def get_video_pages(self, video_id):
        # 获取视频分p信息
        v = video.Video(bvid=video_id, credential=self.credential)
        pages = sync(v.get_pages())
        
        page_info = []

        for each in pages:
            page_info.append({
                "cid": each.get("cid", 0),
                "page": each.get("page", 0),
                "part": remove_html_tags_and_invalid_chars(each.get("part", "")),
                "duration": each.get("duration", 0)
            })

        return page_info

    def search_video_from_playlist(self, playlist_id, keyword=None):
        """从Bilibili合集/收藏夹中获取所有视频"""
        from bilibili_api.favorite_list import FavoriteList, FavoriteListType
        from bilibili_api.channel_series import ChannelSeries, ChannelSeriesType

        playlist_id = str(playlist_id).strip()

        # BV号：当作单视频分P处理
        if playlist_id.upper().startswith('BV'):
            try:
                pages = self.get_video_pages(playlist_id)
                info = self.get_video_info(playlist_id)
                bv_videos = []
                for i, page in enumerate(pages):
                    bv_videos.append({
                        'id': info['id'], 'pure_id': info['id'],
                        'title': page['part'], 'url': info['url'],
                        'duration': page['duration'],
                        'page_count': len(pages), 'p_index': i,
                    })
                return bv_videos
            except Exception as e:
                raise Exception(f"获取BV号分P失败: {e}")

        # 数字ID
        if not playlist_id.isdigit():
            import re
            nums = re.findall(r'\d+', playlist_id)
            if nums:
                playlist_id = nums[-1]
            else:
                raise Exception("无法识别列表ID")

        list_id = int(playlist_id)
        all_videos = []
        errors = []

        # 策略1：收藏夹
        try:
            fl = FavoriteList(type_=FavoriteListType.VIDEO, media_id=list_id, credential=self.credential)
            info = sync(fl.get_info())
            if not info:
                raise Exception("信息为空")
            page = 1
            while True:
                data = sync(fl.get_content(page=page))
                medias = data.get('medias') or []
                if not medias:
                    break
                for m in medias:
                    bvid = m.get('bvid', '')
                    title = m.get('title', '')
                    duration = m.get('duration', 0)
                    if not bvid or not title:
                        continue
                    all_videos.append({
                        'id': bvid, 'pure_id': bvid,
                        'title': remove_html_tags_and_invalid_chars(title),
                        'url': BILI_URL_PREFIX + bvid, 'duration': duration,
                        'page_count': 1, 'p_index': 0,
                    })
                if not data.get('has_more'):
                    break
                page += 1
            if all_videos:
                return all_videos
        except Exception as e:
            errors.append(f"收藏夹: {e}")

        # 策略2：合集 — 两种类型都试，取最优
        best_videos = []
        for type_ in [ChannelSeriesType.SERIES, ChannelSeriesType.SEASON]:
            try:
                cs = ChannelSeries(type_=type_, id_=list_id, credential=self.credential)
                page = 1
                type_videos = []
                while True:
                    data = sync(cs.get_videos(pn=page, ps=100))
                    archives = data.get('archives') or []
                    if not archives:
                        break
                    for a in archives:
                        bvid = a.get('bvid', '')
                        title = a.get('title', '')
                        duration = a.get('duration', 0)
                        if not bvid or not title:
                            continue
                        type_videos.append({
                            'id': bvid, 'pure_id': bvid,
                            'title': remove_html_tags_and_invalid_chars(title),
                            'url': BILI_URL_PREFIX + bvid, 'duration': duration,
                            'page_count': 1, 'p_index': 0,
                        })
                    page += 1
                if len(type_videos) > len(best_videos):
                    best_videos = type_videos
            except Exception as e:
                errors.append(f"合集(type_{type_.value})")
                continue

        if best_videos:
            return best_videos

        raise Exception(f"获取Bilibili列表失败: {'; '.join(errors)}")


def create_downloader(settings):
    """按设置字典构造下载器实例（纯工厂，不含 UI 与登录交互）"""
    downloader_type = settings.get('downloader')
    proxy = settings['proxy_address'] if settings.get('use_proxy') else None
    max_results = settings.get('search_max_results', 5)
    scan_pages = max(1, int(settings.get('search_scan_pages', 2) or 2))

    if downloader_type == "youtube":
        if settings.get('use_youtube_api'):
            return PurePytubefixDownloader(
                proxy=proxy, use_potoken=False, use_oauth=False, auto_get_potoken=False,
                search_max_results=max_results, search_scan_pages=scan_pages,
                use_api=True, api_key=settings.get('youtube_api_key')
            )
        use_potoken = settings.get('use_custom_po_token') or settings.get('use_auto_po_token')
        return PurePytubefixDownloader(
            proxy=proxy, use_potoken=use_potoken, use_oauth=settings.get('use_oauth'),
            auto_get_potoken=settings.get('use_auto_po_token'),
            search_max_results=max_results, search_scan_pages=scan_pages,
            use_api=False, api_key=None
        )

    if downloader_type == "bilibili":
        return BilibiliDownloader(
            proxy=proxy, no_credential=settings.get('no_credential'),
            credential_path="./cred_datas/bilibili_cred.pkl",
            search_max_results=max_results, search_scan_pages=scan_pages, skip_login=True
        )

    raise ValueError(f"未配置正确的下载器类型：{downloader_type!r}，请重新确认抓取设置")