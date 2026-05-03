"""
视频处理工具模块
提供视频片段生成、音频处理、视频拼接等功能
"""

import numpy as np
from datetime import datetime
from queue import Queue, Empty
import os, threading, subprocess, time
from typing import Any, Dict, List, Tuple, Optional

from moviepy import VideoFileClip, ImageClip, vfx, afx

from utils.DataUtils import sort_video_files
from utils.ImageUtils import create_blank_image
from utils.PageUtils import format_time_difference
from utils.Variables import HARD_RENDER_METHOD, REVERSE_LEVEL_LABELS, image_root_path


# ==================== 常量定义 ====================

DEFAULT_AUDIO_TARGET_DBFS = -20
DEFAULT_FPS = 60
DEFAULT_AUDIO_BITRATE = "320k"
DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_PIXEL_FORMAT = "yuv420p"
DEFAULT_MAX_MUXING_QUEUE_SIZE = "4096"
DEFAULT_THREADS = 0
DEFAULT_THREAD_TYPE = "frame"
GAIN_CLIP_MIN = 0.1
GAIN_CLIP_MAX = 3.0
EPSILON = 1e-8

# 路径类型说明：
# - temp_output_path: 临时输出路径，用于存储单个片段渲染过程中的临时文件
# - final_clips_dir: 最终片段存储目录，用于存储渲染完成的视频片段（后续拼接用）
# - output_dir: 通用输出目录


# ==================== 音频处理 ====================

def normalize_audio_volume(clip, target_dbfs: int = DEFAULT_AUDIO_TARGET_DBFS):
    """
    均衡化音频响度到指定的分贝值
    
    Args:
        clip: 视频片段对象
        target_dbfs: 目标分贝值，默认-20dB
    
    Returns:
        处理后的视频片段
    """
    if clip.audio is None:
        return clip
    
    try:
        audio = clip.audio
        
        # 采样音频的多个点来计算平均音量
        sample_times = np.linspace(0, clip.duration, num=100)
        samples = []
        
        for t in sample_times:
            frame = audio.get_frame(t)
            if isinstance(frame, (list, tuple, np.ndarray)):
                samples.append(np.array(frame))
        
        if not samples:
            return clip
            
        # 计算当前音频的均方根值并应用增益
        audio_array = np.stack(samples)
        current_rms = np.sqrt(np.mean(audio_array**2))
        target_rms = 10 ** (target_dbfs / 20)
        gain = target_rms / (current_rms + EPSILON)
        gain = np.clip(gain, GAIN_CLIP_MIN, GAIN_CLIP_MAX)
        
        return clip.with_volume_scaled(gain)
    
    except Exception as e:
        print(f"警告: 音频均衡化失败 - {str(e)}")
        return clip


# ==================== 视频生成 ====================

class VideoGenerator:
    """视频片段生成器基类"""
    
    def __init__(self, encoder_param: dict, style_config: dict):
        """
        初始化视频生成器
        
        Args:
            encoder_param: 编码器参数
            style_config: 样式配置
        """
        self.encoder_param = encoder_param
        self.style_config = style_config
        self.resolution = encoder_param['resolution']
        self.bitrate = encoder_param['bitrate']

    def _build_encoding_arg(self) -> str:
        hwaccel = self.encoder_param['hwaccel']
        codec = self.encoder_param['codec']
        return codec if hwaccel else "libx264"
    
    def _build_encoding_args(self) -> List[str]:
        """构建编码参数"""
        hwaccel = self.encoder_param["hwaccel"]
        accel_type = self.encoder_param["brand"]
        encoding_args = []
        
        if hwaccel and accel_type in HARD_RENDER_METHOD:
            encoder_prefix = self.encoder_param.get("encoder", "h264")
            hardware_suffix = HARD_RENDER_METHOD[accel_type]["codec"]
            final_encoder = f"{encoder_prefix}_{hardware_suffix}"
            encoding_args.extend(['-vcodec', final_encoder])
        else:
            final_encoder = self.encoder_param.get("encoder", "libx264")
            encoding_args.extend(['-vcodec', final_encoder])
        
        return encoding_args
    
    def _build_base_ffmpeg_args(self) -> List[str]:
        """构建FFmpeg基础参数"""
        return [
            '-y',
            '-hide_banner',
            '-r', str(DEFAULT_FPS),
            '-threads', str(DEFAULT_THREADS),
            '-thread_type', DEFAULT_THREAD_TYPE,
            '-b:v', f'{self.bitrate}k',
            '-maxrate', f'{int(self.bitrate) * 2}k',
            '-bufsize', f'{int(self.bitrate) * 4}k',
            '-pix_fmt', DEFAULT_PIXEL_FORMAT,
            '-acodec', DEFAULT_AUDIO_CODEC,
            '-b:a', DEFAULT_AUDIO_BITRATE,
            '-max_muxing_queue_size', DEFAULT_MAX_MUXING_QUEUE_SIZE,
        ]
    
    def _log_error(self, clip_config: dict, output_path: str, cmd: List[str], 
                   error: subprocess.CalledProcessError):
        """记录FFmpeg错误日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_content = f"""========================== FFmpeg 生成失败！============================
生成时间：{timestamp}，
视频 ID: {clip_config.get('id', 'N/A')}，
输出路径: {output_path}，
持续时间: {clip_config.get('duration', 'N/A')} 秒，
分辨率: {self.resolution}

FFmpeg 命令:
{str(' '.join(cmd))}

错误输出:
{error.stderr}

配置信息:
{clip_config}
============================ 错误日志结束 ============================"""
        
        log_path = f'./videos/error_logs/generation_error_report_{timestamp}.log'
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_content)
        
        print("FFmpeg 生成失败！详细错误报告已保存为文件；")
        print("请将此文件发送给 chu-gen 开发者，而不是这个画面的截图。")
        print(f"路径：{os.path.abspath(log_path)}")
        print("============================ 这里是分隔符 ============================")


class InfoSegmentGenerator(VideoGenerator):
    """信息片段（背景板/说明页）生成器"""
    
    def generate(self, clip_config: dict, temp_output_path: str = './videos/temp_generated') -> Optional[VideoFileClip]:
        """
        生成信息片段
        
        Args:
            clip_config: 片段配置
            temp_output_path: 临时输出路径（文件或目录），用于存储渲染过程中的临时文件
        
        Returns:
            VideoFileClip 对象，失败时返回 None
        """
        start_time_generation = time.time()
        
        # 验证配置
        if 'duration' not in clip_config:
            raise ValueError(f"缺少 duration 字段: {clip_config}")
        
        # 准备路径
        bg_video_path = self._get_bg_video_path()
        bg_image_path = self._get_bg_image_path(clip_config)
        bg_audio_path = self._get_bg_audio_path(clip_config)
        
        # 构建FFmpeg命令
        input_args, filter_complex, audio_stream = self._build_ffmpeg_command(
            clip_config, bg_video_path, 
            bg_image_path, bg_audio_path
        )
        
        output_path = self._prepare_output_path(clip_config, temp_output_path)
        encoding_args = self._build_encoding_args()
        base_args = self._build_base_ffmpeg_args()
        
        cmd = [
            'ffmpeg',
            *input_args,
            *base_args,
            '-filter_complex', filter_complex,
            '-map', '[v_out]',
            '-map', f'[{audio_stream}]',
            *encoding_args,
            output_path
        ]
        
        print(f"正在为您生成【{clip_config['id']}】的片段")
        print("正在执行 FFmpeg 生成命令。")
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
            # print(f"已生成您的视频片段，名称为：{output_path}")
            print(f"已生成您的视频片段，名称为：{clip_config['id']}.mp4")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return VideoFileClip(output_path)
        except subprocess.CalledProcessError as e:
            self._log_error(clip_config, output_path, cmd, e)
            return None
    
    def _get_bg_video_path(self) -> str:
        """获取背景视频路径"""
        from utils.Variables import bgclips_path
        path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
        if not os.path.exists(path):
            raise FileNotFoundError(f"背景视频不存在: {path}")
        return path
    
    def _get_bg_image_path(self, clip_config: dict) -> Optional[str]:
        """获取背景图片路径"""
        bg_page = clip_config['bg_page']
        no_overlay = clip_config['no_overlay']
        
        if bg_page and no_overlay:
            print(f"信息: 片段 {clip_config['id']} 已禁用底板图像")
            return None
        elif bg_page and no_overlay == False:
            print(f"信息: 片段 {clip_config['id']} 已启用底板图像，但未填写内容，使用默认底板")
        return os.path.abspath(clip_config['full_image']).replace('\\', '/')
        # return None
    
    def _get_bg_audio_path(self, clip_config: dict) -> Optional[str]:
        """获取背景音频路径"""
        from utils.Variables import audios_path
        
        # if clip_config.get('no_sound'):
        #     return None
        
        path = os.path.abspath(f"{audios_path}/bgm.mp3").replace('\\', '/')
        return path if (os.path.exists(path) or clip_config['no_sound']) else None
    
    # def _build_ffmpeg_command(self, clip_config: dict, bg_video_path: str,
    #                         bg_image_path: Optional[str], bg_audio_path: Optional[str]) -> Tuple[List[str], str, str]:
    #     """构建FFmpeg命令组件（仅用于 info 片段）"""
    #     duration = clip_config['duration']
    #     darkness = self.style_config['darkness']
        
    #     input_args = ['-i', bg_video_path]
    #     filter_parts = []
        
    #     # 动态索引计数器
    #     next_input_idx = 1
        
    #     # 背景视频处理
    #     filter_parts.append(
    #         f'[0:v]loop=loop=-1:size=1000:start=0,'
    #         f'trim=duration={duration},'
    #         f'eq=brightness={darkness}[bg_processed];'
    #     )
        
    #     # 背景图片叠加（动态索引）
    #     if bg_image_path:
    #         input_args.extend(['-i', bg_image_path])
    #         filter_parts.append(
    #             f'[bg_processed][{next_input_idx}:v]overlay=0:0[bg_combined];'
    #         )
    #         base_stream = 'bg_combined'
    #         next_input_idx += 1
    #     else:
    #         base_stream = 'bg_processed'
        
    #     # 最终缩放
    #     filter_parts.append(
    #         f'[{base_stream}]scale={self.resolution[0]}:{self.resolution[1]},'
    #         f'trim=duration={duration},'
    #         f'setpts=PTS-STARTPTS[v_out];'
    #     )
        
    #     # 音频处理（info 片段可选静音）
    #     audio_stream = 'a_out'
    #     if bg_audio_path:
    #         # 有背景音乐
    #         input_args.extend(['-i', bg_audio_path])
    #         filter_parts.append(
    #             f'[{next_input_idx}:a]atrim=duration={duration},asetpts=PTS-STARTPTS[a_out]'
    #         )
    #     else:
    #         # 静音（no_sound = True）
    #         filter_parts.append(f'aevalsrc=0:duration={duration}[a_out]')
        
    #     return input_args, ''.join(filter_parts), audio_stream
    
    def _build_ffmpeg_command(self, clip_config: dict, bg_video_path: str,
                        bg_image_path: Optional[str], bg_audio_path: Optional[str]) -> Tuple[List[str], str, str]:
        """构建FFmpeg命令组件（仅用于 info 片段）"""
        duration = clip_config['duration']
        darkness = self.style_config['darkness']
        
        input_args = ['-i', bg_video_path]
        filter_parts = []
        
        # 文件索引计数器，从0开始
        file_idx = 0
        
        # 背景视频处理
        filter_parts.append(
            f'[{file_idx}:v]loop=loop=-1:size=1000:start=0,'  # 使用计数器
            f'trim=duration={duration},'
            f'eq=brightness={darkness}[bg_processed];'
        )
        
        # 背景图片叠加
        if bg_image_path:
            file_idx += 1  # 递增到1
            input_args.extend(['-i', bg_image_path])
            filter_parts.append(
                f'[bg_processed][{file_idx}:v]overlay=0:0[bg_combined];'  # 使用递增后的值
            )
            base_stream = 'bg_combined'
        else:
            base_stream = 'bg_processed'
        
        # 最终缩放
        filter_parts.append(
            f'[{base_stream}]scale={self.resolution[0]}:{self.resolution[1]},'
            f'trim=duration={duration},'
            f'setpts=PTS-STARTPTS[v_out];'
        )
        
        # 音频处理
        audio_stream = 'a_out'
        if bg_audio_path:
            file_idx += 1  # 递增到下一个可用索引
            input_args.extend(['-i', bg_audio_path])
            filter_parts.append(
                f'[{file_idx}:a]atrim=duration={duration},asetpts=PTS-STARTPTS[a_out]'
            )
        else:
            filter_parts.append(f'aevalsrc=0:duration={duration}[a_out]')
        
        return input_args, ''.join(filter_parts), audio_stream
    
    def _prepare_output_path(self, clip_config: dict, temp_output_path: str) -> str:
        """准备临时输出路径"""
        if os.path.isdir(temp_output_path):
            return os.path.join(temp_output_path, f"{clip_config['id']}.mp4")
        return temp_output_path


class VideoSegmentGenerator(VideoGenerator):
    """视频片段生成器（带评论和动画效果）"""
    
    def generate(self, clip_config: dict, temp_output_path: str = './videos/temp_generated') -> Optional[VideoFileClip]:
        """
        生成视频片段
        
        Args:
            clip_config: 片段配置
            temp_output_path: 临时输出路径（文件或目录），用于存储渲染过程中的临时文件
        
        Returns:
            VideoFileClip 对象，失败时返回 None
        """
        start_time_generation = time.time()
        
        # 构建FFmpeg命令
        input_args, filter_complex, audio_stream = self._build_ffmpeg_command(clip_config)
        
        output_path = self._prepare_output_path(clip_config, temp_output_path)
        encoding_args = self._build_encoding_args()
        base_args = self._build_base_ffmpeg_args()
        
        cmd = [
            'ffmpeg',
            *input_args,
            *base_args,
            '-filter_complex', filter_complex,
            '-map', '[v_out]',
            '-map', f'[{audio_stream}]',
            *encoding_args,
            '-t', str(clip_config['duration']),
            output_path
        ]
        
        song_name = clip_config['song_name']
        level = REVERSE_LEVEL_LABELS[clip_config['level_index']]
        print(f"正在为您生成【{song_name} - {level}】的片段")
        print("正在执行 FFmpeg 生成命令。")
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
            print(f"已生成您的视频片段，名称为：{clip_config['id']}-{level}.mp4")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return VideoFileClip(output_path)
        except subprocess.CalledProcessError as e:
            self._log_error(clip_config, output_path, cmd, e)
            return None
    
    def _get_coordinates(self) -> Dict[str, int]:
        """计算视频叠加坐标"""
        postion = self.style_config['position']['video']
        overlay = postion['overlay']
        height = postion['height']
        
        return {
            'left': int(overlay[0] * self.resolution[0]),
            'top': int(overlay[1] * self.resolution[1]),
            'height': int(height * self.resolution[1] / 1080)
        }
    
    # def _build_ffmpeg_command(self, clip_config: dict) -> Tuple[List[str], str, str]:
    #     from utils.Variables import bgclips_path
        
    #     duration = clip_config['duration']
    #     start_time = clip_config['start']
    #     darkness = self.style_config['darkness']
        
    #     # 文件路径
    #     bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
    #     main_image_path = self._get_main_image_path(clip_config)
    #     video_path = self._get_video_path(clip_config)
        
    #     # 检查视频路径
    #     if not video_path or not os.path.exists(video_path):
    #         raise ValueError(f"视频文件不存在: {video_path}")
        
    #     input_args = ['-i', bg_video_path]
    #     filter_parts = []
        
    #     # 动态追踪当前输入索引
    #     bg_idx = 0  # 背景视频索引
    #     img_idx = 1
    #     video_idx = 2
        
    #     # 处理背景和图片叠加
    #     if main_image_path:
    #         input_args.extend(['-i', main_image_path])
            
    #         filter_parts.append(f'[{img_idx}:v]scale={self.resolution[0]}:{self.resolution[1]}[img];')
    #         filter_parts.append(
    #             f'[{bg_idx}:v]loop=loop=-1:size=1000:start=0,'
    #             f'trim=duration={duration},'
    #             f'scale={self.resolution[0]}:{self.resolution[1]},'
    #             f'eq=brightness={darkness}[bg_processed];'
    #         )
    #         filter_parts.append('[bg_processed][img]overlay=0:0[bg_img];')
    #         base_stream = 'bg_img'
    #     else:
    #         filter_parts.append(
    #             f'[{bg_idx}:v]loop=loop=-1:size=1000:start=0,'
    #             f'trim=duration={duration},'
    #             f'scale={self.resolution[0]}:{self.resolution[1]},'
    #             f'eq=brightness={darkness}[bg_img];'
    #         )
    #         base_stream = 'bg_img'
        
    #     # 处理视频叠加
    #     input_args.extend(['-i', video_path])
    #     # video_idx = len(input_args) - 1
        
    #     coords = self._get_coordinates()
    #     filter_parts.append(
    #         f'[{video_idx}:v]scale=-1:{coords["height"]},'
    #         f'trim=start={start_time}:duration={duration},'
    #         f'setpts=PTS-STARTPTS[overlay_vid];'
    #     )
    #     filter_parts.append(
    #         f'[{base_stream}][overlay_vid]overlay={coords["left"]}:{coords["top"]}[final_video];'
    #     )
    #     filter_parts.append(f'[final_video]trim=duration={duration}[v_out];')
    #     filter_parts.append(
    #         f'[{video_idx}:a]atrim=start={start_time}:duration={duration},'
    #         f'asetpts=PTS-STARTPTS[a_out]'
    #     )
        
    #     return input_args, ''.join(filter_parts), 'a_out'
    
    def _build_ffmpeg_command(self, clip_config: dict) -> Tuple[List[str], str, str]:
        from utils.Variables import bgclips_path
        
        duration = clip_config['duration']
        start_time = clip_config['start']
        darkness = self.style_config['darkness']
        
        bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
        main_image_path = self._get_main_image_path(clip_config)
        video_path = self._get_video_path(clip_config)
        
        input_args = [
            '-i', bg_video_path,
            '-i', main_image_path,
            '-i', video_path,
        ]
        
        filter_parts = []
        
        # 索引硬编码，清晰明确
        bg_video_idx = 0
        img_idx = 1
        video_idx = 2
        
        # 处理背景
        base_stream = self._process_background(filter_parts, bg_video_idx,
                                    img_idx, duration, darkness)
        
        # 处理视频叠加
        audio_stream = self._process_video_overlay(filter_parts, video_idx, 
                                base_stream, start_time, duration)
        
        return input_args, ''.join(filter_parts), audio_stream
    
    def _get_main_image_path(self, clip_config: dict) -> Optional[str]:
        """获取主图片路径"""
        full_image = clip_config.get('full_image')
        main_image = clip_config['main_image']
        if full_image is not None and os.path.exists(full_image):
            return os.path.abspath(full_image).replace('\\', '/')
        return os.path.abspath(main_image).replace('\\', '/')
    
    def _get_video_path(self, clip_config: dict) -> Optional[str]:
        """获取视频路径"""
        video = clip_config.get('video')
        if video and os.path.exists(video):
            return os.path.abspath(video).replace('\\', '/')
        return None
    
    # def _process_background(self, filter_parts: List[str], input_args: List[str],
    #                     main_image_path: Optional[str], duration: float, darkness: float) -> str:
    #     """处理背景（使用动态索引）"""
    #     current_idx = 0  # 背景视频索引
        
    #     if main_image_path:
    #         input_args.extend(['-i', main_image_path])
    #         next_idx = len(input_args) - 1  # 动态获取刚添加的图片索引
            
    #         filter_parts.append(f'[{next_idx}:v]scale={self.resolution[0]}:{self.resolution[1]}[img];')
    #         filter_parts.append(
    #             f'[{current_idx}:v]loop=loop=-1:size=1000:start=0,'
    #             f'trim=duration={duration},'
    #             f'scale={self.resolution[0]}:{self.resolution[1]},'
    #             f'eq=brightness={darkness}[bg_processed];'
    #         )
    #         filter_parts.append('[bg_processed][img]overlay=0:0[bg_img];')
    #         return 'bg_img'
    #     else:
    #         filter_parts.append(
    #             f'[{current_idx}:v]loop=loop=-1:size=1000:start=0,'
    #             f'trim=duration={duration},'
    #             f'scale={self.resolution[0]}:{self.resolution[1]},'
    #             f'eq=brightness={darkness}[bg_img];'
    #         )
    #         return 'bg_img'

    def _process_background(self, filter_parts, bg_video_idx, img_idx, duration, darkness):
        filter_parts.append(f'[{img_idx}:v]scale={self.resolution[0]}:{self.resolution[1]}[img];')
        filter_parts.append(
            f'[{bg_video_idx}:v]loop=loop=-1:size=1000:start=0,'
            f'trim=duration={duration},'
            f'scale={self.resolution[0]}:{self.resolution[1]},'
            f'eq=brightness={darkness}[bg_processed];'
        )
        filter_parts.append('[bg_processed][img]overlay=0:0[bg_img];')
        return 'bg_img'

    # def _process_video_overlay(self, filter_parts: List[str], input_args: List[str],
    #                         video_path: str, base_stream: str, start_time: float, duration: float) -> str:
    #     """处理视频叠加（使用动态索引）"""
    #     coords = self._get_coordinates()
        
    #     input_args.extend(['-i', video_path])
    #     video_idx = len(input_args) - 1  # 动态获取视频索引
        
    #     filter_parts.append(
    #         f'[{video_idx}:v]scale=-1:{coords["height"]},'
    #         f'trim=start={start_time}:duration={duration},'
    #         f'setpts=PTS-STARTPTS[overlay_vid];'
    #     )
    #     filter_parts.append(
    #         f'[{base_stream}][overlay_vid]overlay={coords["left"]}:{coords["top"]}[final_video];'
    #     )
    #     filter_parts.append(f'[final_video]trim=duration={duration}[v_out];')
    #     filter_parts.append(
    #         f'[{video_idx}:a]atrim=start={start_time}:duration={duration},'
    #         f'asetpts=PTS-STARTPTS[a_out]'
    #     )
        
    #     return 'a_out'
    
    def _process_video_overlay(self, filter_parts, video_idx, base_stream, start_time, duration):
        coords = self._get_coordinates()
        
        filter_parts.append(
            f'[{video_idx}:v]scale=-1:{coords["height"]},'
            f'trim=start={start_time}:duration={duration},'
            f'setpts=PTS-STARTPTS[overlay_vid];'
        )
        filter_parts.append(
            f'[{base_stream}][overlay_vid]overlay={coords["left"]}:{coords["top"]}[final_video];'
        )
        filter_parts.append(f'[final_video]trim=duration={duration}[v_out];')
        filter_parts.append(
            f'[{video_idx}:a]atrim=start={start_time}:duration={duration},'
            f'asetpts=PTS-STARTPTS[a_out]'
        )
        
        return 'a_out'
    
    def _prepare_output_path(self, clip_config: dict, temp_output_path: str) -> str:
        """准备临时输出路径"""
        if os.path.isdir(temp_output_path):
            level_label = REVERSE_LEVEL_LABELS[clip_config['level_index']]
            return os.path.join(temp_output_path, f"{clip_config['id']}-{level_label}.mp4")
        return temp_output_path


# ==================== 辅助函数 ====================

def gen_black_video(duration: float, resolution: tuple[int, int]):
    """
    生成纯黑色底板视频
    
    Args:
        duration: 视频时长（秒）
        resolution: 分辨率 (width, height)
    """
    from utils.Variables import bgclips_path
    
    black_frame = create_blank_image(resolution[0], resolution[1], color=(0, 0, 0, 1))
    clip = ImageClip(black_frame).with_duration(duration)
    clip.write_videofile(f"{bgclips_path}/black_bg.mp4", fps=DEFAULT_FPS)


def check_rendered_clips_multithreaded(
    video_configs: Dict[str, List[Dict[str, Any]]],
    final_clips_dir: str,
    force_render: bool = False,
    max_workers: int = 4
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    多线程检测已渲染的视频片段（检查最终片段存储目录）
    
    Args:
        video_configs: 视频配置字典
        final_clips_dir: 最终片段存储目录（拼接用的片段存放位置）
        force_render: 是否强制重新渲染
        max_workers: 最大线程数
    
    Returns:
        (需要渲染的配置列表, 已存在的配置列表)
    """
    task_queue = Queue()
    result_queue = Queue()
    
    vfile_prefix = 0
    all_configs = []
    
    # 按顺序将所有片段加入任务队列
    for segment_type in ['intro', 'main', 'ending']:
        if segment_type in video_configs:
            for config in video_configs[segment_type]:
                task_queue.put((vfile_prefix, config))
                all_configs.append((vfile_prefix, config))
                vfile_prefix += 1
    
    def check_worker():
        while True:
            try:
                prefix, config = task_queue.get_nowait()
            except Empty:
                break
            
            output_file = os.path.join(final_clips_dir, f"{prefix}_{config['id']}.mp4")
            exists = os.path.exists(output_file) and not force_render
            result_queue.put((prefix, config, exists))
            task_queue.task_done()
    
    # 启动线程
    threads = []
    worker_count = min(max_workers, max(1, task_queue.qsize()))
    for _ in range(worker_count):
        t = threading.Thread(target=check_worker)
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    # 收集结果
    to_render = []
    existing = []
    while not result_queue.empty():
        _, config, exists = result_queue.get()
        if exists:
            existing.append(config)
        else:
            to_render.append(config)
    
    return to_render, existing


def render_all_video_clips(
    resources: dict,
    final_clips_dir: str,
    trans_param: dict,
    encoder_param: dict,
    style_config: dict,
    force_render: bool = False
):
    """
    生成所有视频片段并保存到最终片段目录
    
    Args:
        resources: 视频配置数据
        final_clips_dir: 最终片段存储目录（拼接用的片段存放位置）
        trans_param: 过渡参数
        encoder_param: 编码器参数
        style_config: 样式配置
        force_render: 是否强制渲染
    """
    from utils.Variables import bgclips_path
    
    resolution = encoder_param['resolution']
    bitrate = encoder_param['bitrate']
    temp_output_path = './videos/temp_generated'  # 临时渲染路径
    
    # 检查已有片段（在最终目录中检查）
    to_render, existing = check_rendered_clips_multithreaded(
        resources, final_clips_dir, force_render
    )
    
    print(f"需要渲染 {len(to_render)} 个新片段，跳过 {len(existing)} 个已存在片段")
    
    # 如果底板视频不存在则生成一份新的
    if not os.path.exists(f"{bgclips_path}/black_bg.mp4"):
        gen_black_video(5, resolution)
    
    if "main" not in resources:
        print("错误: 没有找到主视频片段的配置！请检查配置文件！")
        return
    
    vfile_prefix = 0
    
    def render_selected_clips(clip_configs: List[dict], segment_type: str):
        nonlocal vfile_prefix
        for config in clip_configs:
            current_prefix = vfile_prefix
            # 最终输出路径（保存到 final_clips_dir）
            final_output_file = os.path.join(final_clips_dir, f"{current_prefix}_{config['id']}.mp4")
            
            if config in to_render:
                if segment_type == "info":
                    print(f"开始处理头尾: {current_prefix}_{config['id']}.mp4")
                    generator = InfoSegmentGenerator(encoder_param, style_config)
                    # 使用临时路径进行渲染
                    clip = generator.generate(config, temp_output_path)
                else:
                    print(f"开始处理主片段: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                    generator = VideoSegmentGenerator(encoder_param, style_config)
                    # 使用临时路径进行渲染
                    clip = generator.generate(config, temp_output_path)
                
                if clip:
                    clip = normalize_audio_volume(clip)
                    
                    if trans_param['enabled']:
                        fade_duration = trans_param['duration']
                        clip = clip.with_effects([
                            vfx.FadeIn(fade_duration),
                            vfx.FadeOut(fade_duration),
                            afx.AudioFadeIn(fade_duration),
                            afx.AudioFadeOut(fade_duration)
                        ])
                    
                    # 直接写入最终目录
                    clip.write_videofile(
                        final_output_file,
                        fps=DEFAULT_FPS,
                        threads=4,
                        codec="libx264",
                        bitrate=f'{bitrate}k'
                    )
                    clip.close()
                    del clip
            
            vfile_prefix += 1
    
    # 渲染各个部分
    if 'intro' in resources:
        render_selected_clips(resources['intro'], 'info')
    
    render_selected_clips(resources['main'], 'video')
    
    if 'ending' in resources:
        render_selected_clips(resources['ending'], 'info')


def combine_full_video_direct(final_clips_dir: str, username: str) -> str:
    """
    拼接所有视频片段为完整视频
    
    Args:
        final_clips_dir: 最终片段存储目录（存放已渲染完成的视频片段）
        username: 用户名
    
    Returns:
        输出视频路径
    """
    print("[信息] ==================== 开始拼接视频 ==================")
    
    video_files = [f for f in os.listdir(final_clips_dir) if f.endswith(".mp4")]
    sorted_files = sort_video_files(video_files)
    
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")
    
    try:
        # 创建MP4文件列表
        mp4_list_file = os.path.join(final_clips_dir, "mp4_files.txt")
        with open(mp4_list_file, 'w', encoding='utf-8') as f:
            for file in sorted_files:
                full_path = os.path.abspath(os.path.join(final_clips_dir, file)).replace('\\', '/')
                f.write(f"file '{full_path}'\n")
        
        # 拼接输出为 MP4（输出到 final_clips_dir 目录）
        output_path = os.path.join(final_clips_dir, f"{username}_Best50.mp4")
        real_path = os.path.abspath(final_clips_dir)
        
        cmd = [
            'ffmpeg', '-y',
            '-hide_banner',
            '-loglevel', 'info',
            '-f', 'concat',
            '-safe', '0',
            '-i', f'{real_path}\\mp4_files.txt',
            '-fflags', '+genpts',
            '-avoid_negative_ts', 'make_zero',
            '-max_interleave_delta', '0',
            '-c', 'copy',
            '-threads', '0',
            output_path,
        ]
        subprocess.run(cmd, check=True)
        
        print("[信息] ==================== 视频拼接完成 ==================")
        return output_path
    
    except Exception as e:
        print(f"拼接失败：{str(e)}")
        raise


# ==================== 便捷函数（向后兼容） ====================

def create_info_segment(clip_config: dict, encoder_param: dict, 
                        style_config: dict, temp_output_path: str = './videos/temp_generated'):
    """便捷函数：创建信息片段（向后兼容）"""
    generator = InfoSegmentGenerator(encoder_param, style_config)
    return generator.generate(clip_config, temp_output_path)


def create_video_segment(clip_config: dict, encoder_param: dict, 
                         style_config: dict, temp_output_path: str = './videos/temp_generated'):
    """便捷函数：创建视频片段（向后兼容）"""
    generator = VideoSegmentGenerator(encoder_param, style_config)
    return generator.generate(clip_config, temp_output_path)