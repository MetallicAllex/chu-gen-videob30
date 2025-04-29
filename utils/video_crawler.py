from pytubefix import YouTube, Search
from bilibili_api import login, user, search, video, Credential, sync, HEADERS
from bilibili_api.video import Video
from typing import Tuple
from abc import ABC, abstractmethod
import os
import yaml
import json
import asyncio
import pickle
import httpx
import traceback
import subprocess
import platform
import re

# 根据操作系统选择FFMPEG的输出重定向方式
# TODO：添加日志输出
if platform.system() == "Windows":
    REDIRECT = "> NUL 2>&1"
else:
    REDIRECT = "> /dev/null 2>&1"

FFMPEG_PATH = 'ffmpeg'
MAX_LOGIN_RETRIES = 3

def custom_po_token_verifier() -> Tuple[str, str]:

    with open("global_config.yaml", "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    
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
        print(f"验证PO Token生成失败 (JSON解析错误): {str(e)}")
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

def remove_html_tags_and_invalid_chars(text: str) -> str:
    """去除字符串中的HTML标记和非法字符"""
    # 去除HTML标记
    clean = re.compile('<.*?>')
    text = re.sub(clean, ' ', text)
    
    # 去除非法字符
    invalid_chars = r'[<>:"/\\|?*【】]'  # 定义非法字符
    text = re.sub(invalid_chars, ' ', text)  # 替换为' '

    return text.strip()  # 去除首尾空白字符

def convert_duration_to_seconds(duration: str) -> int:
    try:
        minutes, seconds = map(int, duration.split(':'))
        return minutes * 60 + seconds
    except:
        return int(duration)

def load_credential(credential_path):
    if not os.path.isfile(credential_path):
        print("#####【bilibili】未找到登录凭证，请在终端扫码登录（按住 Ctrl + 滚轮缩小终端文字大小以便扫描二维码）")
        return None
    else:
        # 读取凭证文件
        with open(credential_path, 'rb') as f:
            loaded_data = pickle.load(f)
        
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
            print("#####【bilibili】登录凭证无效，请在终端重新扫码登录（按住 Ctrl + 滚轮缩小终端文字大小以便扫描二维码）")
            return False
        
        # 验证凭证的有效性
        is_valid = sync(credential.check_valid())
        if not is_valid:
            print("#####【bilibili】登录凭证无效，请在终端重新扫码登录（按住 Ctrl + 滚轮缩小终端文字大小以便扫描二维码）")
            return None
        try:
            need_refresh = sync(credential.check_refresh())
            if need_refresh:
                print("#####【bilibili】正在尝试刷新登录凭证。")
                sync(credential.refresh())
        except:
            traceback.print_exc()
            print("#####【【bilibili】刷新登录凭证失败，请在终端重新扫码登录（按住 Ctrl + 滚轮缩小终端文字大小以便扫描二维码）")
            return None
        
        print(f"#####【bilibili】缓存登录成功：{sync(user.get_self_info(credential))['name']}】")
        return credential

async def download_url_from_bili(url: str, out: str, info: str):
    async with httpx.AsyncClient(headers=HEADERS) as sess:
        resp = await sess.get(url)
        length = resp.headers.get('content-length')
        with open(out, 'wb') as f:
            process = 0
            for chunk in resp.iter_bytes(1024):
                if not chunk:
                    break

                process += len(chunk)
                percentage = (process / int(length)) * 100 if length else 0
                print(f'      -- [正在从bilibili下载流: {info} {percentage:.2f}%]', end='\r')
                f.write(chunk)
        print("Done.\n")

# async def bilibili_download(bvid, credential, output_name, output_path, high_res=False):
#     v = video.Video(bvid=bvid, credential=credential)
#     download_url_data = await v.get_download_url(0)
#     detecter = video.VideoDownloadURLDataDetecter(data=download_url_data)

#     # 获取最佳媒体流: 返回列表中0是视频流，1是音频流
#     if high_res:
#         streams = detecter.detect_best_streams()
#     else:
#         streams = detecter.detect_best_streams(video_max_quality=video.VideoQuality._480P,
#                                                no_dolby_video=True, no_dolby_audio=True, no_hdr=True)

#     output_file = os.path.join(output_path, f"{output_name}.mp4")
#     if detecter.check_flv_stream() == True:
#         # FLV 流下载
#         await download_url_from_bili(streams[0].url, "flv_temp.flv", "FLV 音视频")
#         os.system(f'{FFMPEG_PATH} -y -i flv_temp.flv {output_file} {REDIRECT}')
#         # 删除临时文件
#         os.remove("flv_temp.flv")
#         print(f"下载完成，存储为: {output_name}.mp4")
#     else:
#         # MP4 流下载
#         await download_url_from_bili(streams[0].url, "video_temp.m4s", "视频流")
#         await download_url_from_bili(streams[1].url, "audio_temp.m4s", "音频流")
#         print(f"下载完成，正在合并视频和音频")
#         os.system(f'{FFMPEG_PATH} -y -i video_temp.m4s -i audio_temp.m4s -vcodec copy -acodec copy {output_file} {REDIRECT}')
#         # 删除临时文件
#         os.remove("video_temp.m4s")
#         os.remove("audio_temp.m4s")
#         print(f"合并完成，存储为: {output_name}.mp4")

async def bilibili_download(self, bvid, page=1, output_name=None, output_path="."):
    """ 哔哩哔哩视频合并

    Args:
        bvid(str): 视频BV号
        page(int): 分P序号（从1开始）
        output_name(str): 输出文件名（不含后缀）
        output_path(path): 输出目录
    """
    try:
        v = video.Video(bvid=bvid, credential=self.credential)
        page_list = sync(v.get_page_list())
        
        # 检查分P序号是否有效
        if page < 1 or page > len(page_list):
            print(f"错误：分P序号 {page} 无效（该视频共有 {len(page_list)} 个分P）")
            return False

        # 获取目标分P的cid
        target_cid = page_list[page - 1]['cid']
        download_url_data = await v.get_download_url(target_cid)  # 关键修改：传入cid
        detecter = video.VideoDownloadURLDataDetecter(data=download_url_data)

        # 后续下载逻辑（与原代码一致）
        streams = detecter.detect_best_streams()
        output_file = os.path.join(output_path, f"{output_name or page_list[page - 1]['part']}.mp4")
        
        if detecter.check_flv_stream():
            await download_url_from_bili(streams[0].url, "flv_temp.flv", "FLV音视频")
            os.system(f'{FFMPEG_PATH} -y -i flv_temp.flv {output_file} {REDIRECT}')
            os.remove("flv_temp.flv")
            print(f"下载完成，存储为: {output_name}.mp4")
        else:
            await download_url_from_bili(streams[0].url, "video_temp.m4s", "视频流")
            await download_url_from_bili(streams[1].url, "audio_temp.m4s", "音频流")
            print(f"下载完成，正在合并音视频轨道。")
            os.system(f'{FFMPEG_PATH} -y -i video_temp.m4s -i audio_temp.m4s -vcodec copy -acodec copy {output_file} {REDIRECT}')
            os.remove("video_temp.m4s")
            os.remove("audio_temp.m4s")
            print(f"合并完成（已删除临时文件）：{output_file}")

    except Exception as e:
        print(f"下载失败: {e}")
        return False

class Downloader(ABC):
    @abstractmethod
    def search_video(self, keyword):
        pass

    @abstractmethod
    def download_video(self, video_id, output_name, output_path, high_res=False):
        pass

# def parse_video_id(input_str):
#     """解析用户输入的视频标识（支持BV号、YouTube ID、含分P的URL）

#     Args:
#         input_str(str): 输入地址
    
#     Returns: 
#       platform: "bilibili" 或 "youtube"
#       video_id: 纯净的ID（如BV号或YouTube videoId）
#       page: 分P序号（仅B站有效，默认1）
#     """
#     # 处理B站URL（含分P）
#     if "bilibili.com" in input_str:
#         match = re.search(r"video/(BV\w+)(?:\?p=(\d+))?", input_str)
#         if match:
#             return "bilibili", match.group(1), int(match.group(2)) if match.group(2) else 1
    
#     # 处理B站BV号（含分P简写）
#     if input_str.startswith("BV"):
#         parts = input_str.split("/?p=")
#         return "bilibili", parts[0], int(parts[1]) if len(parts) > 1 else 1
    
#     # 默认视为YouTube ID（或关键词）
#     return "youtube", input_str, 1

def parse_video_id(raw_input: str) -> tuple[str, int]:
    """
    只负责提取视频 ID 和分 P，不猜测平台。
    返回: video_id, page
    """
    page = 1
    video_id = raw_input.strip()

    # 提取分 P 信息（/?p=数字）
    match = re.search(r"/\?p=(\d+)", video_id)
    if match:
        page = int(match.group(1))
        video_id = video_id.split("/?p=")[0]  # 去掉 ?p= 部分

    return video_id, page


async def get_bilibili_video_info(bvid_or_aid: str, page: int = 1) -> dict:
    # 根据输入构造 Video 对象（自动识别 AV 或 BV）
    if bvid_or_aid.lower().startswith("bv"):
        video = Video(bvid=bvid_or_aid)
    elif bvid_or_aid.lower().startswith("av"):
        video = Video(aid=int(bvid_or_aid[2:]))
    else:
        # 纯 ID 时默认用 BV
        video = Video(bvid=bvid_or_aid)

    info = await video.get_info()
    pages = info["pages"]

    if page > len(pages):
        raise ValueError(f"该视频只有 {len(pages)} P，无法获取第 {page} P")

    p_info = pages[page - 1]

    return {
        "id": bvid_or_aid,
        "url": f"https://www.bilibili.com/video/{video.get_bvid()}/?p={page}",
        "title": p_info["part"],
        "duration": p_info["duration"],
        "page": page
    }

def get_youtube_video_info(video_id: str) -> dict:
    url = f"https://www.youtube.com/watch?v={video_id}"
    yt = YouTube(url)
    return {
        "id": video_id,
        "url": url,
        "title": yt.title,
        "duration": yt.length
    }

class PurePytubefixDownloader(Downloader):
    """使用pytubefix进行搜索和下载的youtube视频下载器"""
    def __init__(self, proxy=None, use_oauth=False, use_potoken=False, auto_get_potoken=False, 
                 search_max_results=3):
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
    
    def search_video(self, keyword):
        if self.proxy:
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        else:
            proxies = None

        results = Search(keyword, 
                         proxies=proxies, 
                         use_oauth=self.use_oauth, 
                         use_po_token=self.use_potoken,
                         po_token_verifier=self.po_token_verifier)
        videos = []
        for result in results.videos:
            videos.append({
                'id': result.watch_url,  # 使用Pytubefix时，video_id是url字符串
                'pure_id': result.video_id,
                'title': remove_html_tags_and_invalid_chars(result.title),
                'url': result.watch_url,
                'duration': result.length
            })
        if self.search_max_results < len(videos):
            videos = videos[:self.search_max_results]
        return videos
    
    def download_video(self, video_id, output_name, output_path, high_res=False):
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
                down_video = video.download(output_path, filename="video_temp")
                down_audio = audio.download(output_path, filename="audio_temp")
                print(f"下载完成，正在合并视频和音频")
                output_file = os.path.join(output_path, f"{output_name}.mp4")
                os.system(f'{FFMPEG_PATH} -y -i {down_video} -i {down_audio} -vcodec copy -acodec copy {output_file} {REDIRECT}')
                # 删除临时文件
                os.remove(f"{down_video}")
                os.remove(f"{down_audio}")
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

class BilibiliDownloader(Downloader):
    def __init__(self, proxy=None, no_credential=False, credential_path="../cred_datas/bilibili_cred.pkl", search_max_results=3):
        self.proxy = proxy
        self.search_max_results = search_max_results
        
        if no_credential:
            self.credential = None
            return
        
        self.credential = load_credential(credential_path)
        if self.credential:
            return
        
        for attempt in range(MAX_LOGIN_RETRIES):
            log_succ = self.log_in(credential_path)
            if log_succ:
                break  # 登录成功，退出循环
            print(f"正在尝试第 {attempt + 1} 次重新登录...")
    
    def get_credential_username(self):
        if not self.credential:
            return None
        return sync(user.get_self_info(self.credential))['name']

    def log_in(self, credential_path):
        # credential = login.login_with_qrcode_term() # 在终端打印二维码登录
        credential = login.login_with_qrcode_term() # 使用 Tkinter 终端显示二维码登录
        try:
            credential.raise_for_no_bili_jct() # 判断是否成功
            credential.raise_for_no_sessdata() # 判断是否成功
        except:
            print("#####【登录失败，请重试】")
            return False
        print(f"#####【bilibili】登录成功：{sync(user.get_self_info(credential))['name']}】")
        self.credential = credential
        # 缓存凭证
        with open(credential_path, 'wb') as f:
            pickle.dump(credential, f)
        return True
    
    def search_video(self, keyword): 
            # 并发搜索50个视频可能被风控，使用同步方法逐个搜索
            results = sync(
                search.search_by_type(keyword=keyword, 
                                    search_type=search.SearchObjectType.VIDEO,
                                    order_type=search.OrderVideo.TOTALRANK,
                                    order_sort=0,  # 由高到低
                                    page=1,
                                    page_size=self.search_max_results)
            )
            videos = []
            if 'result' not in results:
                print(f"搜索结果异常，请检查如下输出：")
                print(results)
                return []
            res_list = results['result']
            for each in res_list:
                videos.append({
                    'id': each['bvid'],  # 使用bilibili-api时，video_id是bvid字符串或aid
                    'aid': each['aid'],
                    'cid': each['cid'] if 'cid' in each else 0,
                    'title': remove_html_tags_and_invalid_chars(each['title']),  # 去除特殊字符
                    'url': each['arcurl'],
                    'duration': convert_duration_to_seconds(each['duration']),  # 转换为总秒数
                })
            return videos

    def download_video(self, video_id, output_name, output_path, high_res=False):
        if not self.credential:
            print(f"Warning: 未成功配置bilibili登录凭证，下载视频可能失败！")
        # 使用异步方法下载
        result = asyncio.run(
            bilibili_download(bvid=video_id, 
                              credential=self.credential, 
                              output_name=output_name, 
                              output_path=output_path,
                              high_res=high_res)
        )


# test
if __name__ == "__main__":
    downloader = BilibiliDownloader()
    downloader.search_video("【(maimai】【谱面确认】 DX谱面 Aegleseeker 紫谱 Master")