"""
视频处理工具模块
提供视频片段生成、音频处理、视频拼接等功能
"""

import numpy as np
from datetime import datetime
from queue import Queue, Empty
import os, threading, subprocess, time, collections
from typing import Any, Dict, List, Tuple, Optional

from moviepy import ImageClip

from utils.DataUtils import sort_video_files
from utils.ImageUtils import create_blank_image
from utils.PageUtils import format_time_difference
from utils.Variables import HARD_RENDER_METHOD, REVERSE_LEVEL_LABELS, image_root_path


# ==================== 常量定义 ====================

DEFAULT_AUDIO_TARGET_DBFS = -20
DEFAULT_FPS = 60
DEFAULT_AUDIO_BITRATE = "320k"
DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_AUDIO_SAMPLE_RATE = 44100
DEFAULT_AUDIO_CHANNELS = 2
DEFAULT_PIXEL_FORMAT = "yuv420p"
DEFAULT_MAX_MUXING_QUEUE_SIZE = "4096"
DEFAULT_THREADS = 0
DEFAULT_THREAD_TYPE = "frame"
GAIN_CLIP_MIN = 0.1
GAIN_CLIP_MAX = 3.0

# 路径类型说明：
# - output_path: 片段最终输出路径，ffmpeg 单次编码直写（先 .part 再原子改名）
# - final_clips_dir: 最终片段存储目录，用于存储渲染完成的视频片段（后续拼接用）
# - output_dir: 通用输出目录


# ==================== 音频处理 ====================

def measure_audio_gain_db(audio_path: Optional[str], start: float = 0,
                          duration: float = None) -> Optional[float]:
    """算出把该音频段对齐到 DEFAULT_AUDIO_TARGET_DBFS 所需的增益 (dB)。

    与旧 MoviePy 实现同一套语义：测 RMS → 求差 → 线性增益限在 [0.1, 3.0]
    （换算成 dB 即 [-20, +9.54]）。测量交给 RenderIO 的 volumedetect 探测，
    它按 (path, start, duration) 缓存，多片段共用同一条 BGM 只跑一次子进程。
    返回 None 表示不施加增益（无音频 / 静音页 / 测量失败）。
    """
    if not audio_path or not os.path.exists(audio_path):
        return None
    from utils.Quadrants.RenderIO import _measure_audio_rms
    rms_db = _measure_audio_rms(audio_path, start, duration)
    if rms_db == -20.0:            # 探测失败的兜底值：宁可不均衡也别把整段推爆
        return None
    delta = DEFAULT_AUDIO_TARGET_DBFS - rms_db
    return max(20 * np.log10(GAIN_CLIP_MIN), min(20 * np.log10(GAIN_CLIP_MAX), delta))


# ==================== 视频生成 ====================

_bg_duration_cache: Dict[str, float] = {}


def get_bg_duration(bg_video_path: str) -> float:
    """背景视频时长（秒），进程级缓存；探测失败返回 0.0（调用方据此跳过取模）。"""
    cached = _bg_duration_cache.get(bg_video_path)
    if cached is not None:
        return cached
    duration = 0.0
    try:
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        result = subprocess.run(
            [get_ffmpeg_binary('ffprobe'), '-v', 'error', '-show_entries',
             'format=duration', '-of', 'csv=p=0', bg_video_path],
            capture_output=True, text=True, timeout=30, encoding='utf-8')
        duration = float(result.stdout.strip())
    except Exception as e:
        print(f"[SegmentUtils] Warning: 背景视频时长探测失败({bg_video_path}): {e}")
        duration = 0.0
    _bg_duration_cache[bg_video_path] = duration
    return duration


# 生成器原始 ffmpeg 命令的逐编码器调优参数（码率由 _build_base_ffmpeg_args 统一提供，
# 此处不再重复 -b:v）。默认自动探测硬件编码器（N/A/I 逐一实探），
# 用户在页面上勾了 GPU 加速并指定品牌时以其选择为准。
_HW_ENCODER_TUNING = {
    'h264_nvenc': ['-preset', 'p4', '-tune', 'hq'],
    'h264_amf': ['-quality', 'balanced'],
    'h264_qsv': ['-preset', 'medium'],
    'h264_videotoolbox': ['-allow_sw', '1'],
}


class VideoGenerator:
    """视频片段生成器基类"""
    
    def __init__(self, encoder_param: dict, style_config: dict, timestamp: str):
        """
        初始化视频片段生成器
        
        Args:
            encoder_param: 编码器参数
            style_config: 样式配置
        """
        self.encoder_param = encoder_param
        self.style_config = style_config
        self.resolution = encoder_param['resolution']
        self.bitrate = encoder_param['bitrate']
        self.timestamp = timestamp
        # 淡入淡出 / 响度在唯一一次编码里由 ffmpeg 完成，由 generate() 填充
        self._v_fx = ''
        self._a_fx = ''

    def _build_effects(self, duration: float, fade_duration: float,
                       gain_db: Optional[float]) -> Tuple[str, str]:
        """返回 (视频滤镜后缀, 音频滤镜后缀)，直接接在滤镜链末尾的标签之前。

        fade 与 MoviePy 的 FadeIn/FadeOut 同义（对黑场淡入淡出）；片段短到容不下
        两次淡变时按比例压缩淡变时长，避免出现负数起始点。

        音频末尾固定补/裁到 duration 整长并按样本数重建 PTS：AAC 一帧 1024 样本
        （44.1kHz 下 23.2ms）不整除片段长度，产物音频会比视频长一点点。单看一个
        片段无所谓，但 concat 复用流时它是按"声明时长"推进时间基线的，这多出来的一
        帧会在每个衔接处撞进下一段 → 50 段累计实测把音频拉到比视频长 24 秒、
        5426 个包时间戳非递增，播放器以音频为主时钟便会反复微调视频（表现为卡顿与
        音画不同步）。旧实现靠 MoviePy 收尾时顺手重整了时间戳，单遍编码必须自己做。
        """
        v_fx = ''
        fade = min(max(float(fade_duration or 0), 0.0), duration / 2) if duration > 0 else 0.0
        if fade > 0:
            v_fx = (f',fade=t=in:st=0:d={fade:.3f}'
                    f',fade=t=out:st={duration - fade:.3f}:d={fade:.3f}')
        a_fx = ''
        if fade > 0:
            a_fx = (f',afade=t=in:st=0:d={fade:.3f}'
                    f',afade=t=out:st={duration - fade:.3f}:d={fade:.3f}')
        if gain_db is not None and abs(gain_db) > 0.01:
            a_fx += f',volume={gain_db:.2f}dB'
        if duration > 0:
            a_fx += f',apad,atrim=0:{duration:.3f},asetpts=N/SR/TB'
        return v_fx, a_fx

    def _bg_offset(self, bg_video_path: str, clip_config: dict) -> float:
        """该片段的背景起播偏移，已折进背景视频一轮长度内。"""
        offset = float(clip_config.get('bg_offset', 0) or 0)
        duration = get_bg_duration(bg_video_path)
        if offset > 0 and duration > 0:
            offset %= duration
        return max(offset, 0.0)

    def _bg_seek_args(self, bg_video_path: str, clip_config: dict) -> List[str]:
        """背景起播偏移参数（-ss）。

        必须取模：完整 Best50 有 500+ 秒而 bg.mp4 只有 60 秒左右，不取模时第 7 个
        片段之后 -ss 会越过文件末尾，背景输入零帧 → 整条滤镜图无输出 →
        ffmpeg 报 "Could not open encoder before EOF"（rc=-22）整段丢失。
        """
        offset = self._bg_offset(bg_video_path, clip_config)
        return [] if offset <= 0 else ['-ss', f'{offset:.3f}']

    def _bg_chain(self, filter_parts: List[str], input_args: List[str],
                  bg_video_path: str, bg_idx: int, clip_config: dict,
                  duration: float, next_idx: int) -> str:
        """产出连续播放 duration 秒的背景流，返回其标签名（已归零 PTS）。

        替掉旧的 loop=loop=-1:size=1000：那个滤镜会把窗口内的帧**全部缓存在内存里**
        重放（1080p 一帧约 3MB，1000 帧就是 ~3GB），而且只会反复重播那 1000 帧——
        片段跨过 bg.mp4 末尾时画面卡在那一小段里来回，而不是回到开头接着播。
        这里改成"够长就 trim，不够就把同一个文件多挂几路输入 concat 上"：
        不解码多余帧、不缓存窗口，回绕语义与 quad 路径
        （seek_to(bg_offset % duration) 顺序读到 EOF 再回头）一致。

        next_idx: 回绕用的额外输入应拿到的索引（调用方须先排完自己的基础输入）。
        背景长度探测不到时退回旧的 loop 写法，保证不因此丢片段。
        """
        bg_dur = get_bg_duration(bg_video_path)
        if bg_dur <= 0:
            filter_parts.append(
                f'[{bg_idx}:v]loop=loop=-1:size=1000:start=0,'
                f'trim=duration={duration},setpts=PTS-STARTPTS[bgseq];')
            return 'bgseq'

        offset = self._bg_offset(bg_video_path, clip_config)
        labels = []
        first = min(duration, bg_dur - offset)
        # 与谱面那路一样先 fps=60：两路都落在同一张 60fps 时间网格上，overlay 才会
        # 每帧推进（否则背景这一路作为主输入决定输出节奏，谱面会被隔帧复制）
        filter_parts.append(
            f'[{bg_idx}:v]fps={DEFAULT_FPS},trim=duration={first:.3f},'
            f'setpts=PTS-STARTPTS[bg0];')
        labels.append('[bg0]')

        remaining = duration - first
        k = 1
        while remaining > 1e-3:
            take = min(remaining, bg_dur)
            input_args.extend(['-i', bg_video_path])
            filter_parts.append(
                f'[{next_idx}:v]fps={DEFAULT_FPS},trim=duration={take:.3f},'
                f'setpts=PTS-STARTPTS[bg{k}];')
            labels.append(f'[bg{k}]')
            next_idx += 1
            remaining -= take
            k += 1

        if len(labels) == 1:
            return 'bg0'
        src = 'bgjoined'
        filter_parts.append(
            f'{" ".join(labels)}concat=n={len(labels)}:v=1:a=0[{src}];')
        return src

    def _build_encoding_args(self) -> List[str]:
        """构建编码参数。

        用户勾选「使用 GPU 硬件加速」时以其选定的品牌编码器为准（显卡型号只有
        用户自己清楚，自动探测在同机多卡时可能挑错）；未勾选时自动探测
        （N/A/I 逐一实探），无可用硬件才回退 libx264——不勾选不该等于自废加速。
        探测针对本路径实际调用的 ffmpeg 二进制，结果进程级缓存只探一次。
        """
        from utils.Quadrants.RenderIO import detect_hw_encoder
        codec = None
        if self.encoder_param.get('hwaccel') and self.encoder_param.get('codec'):
            codec = self.encoder_param['codec']
        if not codec:
            codec, _ = detect_hw_encoder()
        self.encoder_name = codec
        args = ['-vcodec', codec]
        args.extend(_HW_ENCODER_TUNING.get(codec, []))
        return args
    
    def _build_base_ffmpeg_args(self) -> List[str]:
        """构建FFmpeg基础参数

        -ar/-ac 必须固定：各谱面源的音频采样率不一致（B 站有 44.1k 也有 48k），
        产物就会带着不同采样率的 AAC 进 concat。`-c copy` 只按第一段的采样率建轨，
        其余段的包被按错误的时间基摆放——实测混合 12 段产生 238 次 Non-monotonic
        DTS（同参数则是每衔接 1 次），表现为渐进的音画错位与卡顿，而总时长看不出异常。
        """
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
            '-ar', str(DEFAULT_AUDIO_SAMPLE_RATE),
            '-ac', str(DEFAULT_AUDIO_CHANNELS),
            '-b:a', DEFAULT_AUDIO_BITRATE,
            '-max_muxing_queue_size', DEFAULT_MAX_MUXING_QUEUE_SIZE,
        ]
    
    def _log_error(self, clip_config: dict, output_path: str, cmd: List[str], timestamp: str,
                   error: subprocess.CalledProcessError):
        """记录FFmpeg错误日志"""
        # timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_content = f"""========================== FFmpeg 生成失败！============================
生成时间：{timestamp}，
视频 ID: {clip_config['id']}，
输出路径: {output_path}，
持续时间: {clip_config['duration']} 秒，
分辨率: {self.resolution}

FFmpeg 命令:
{str(' '.join(cmd))}

错误输出:
{error.stderr}

配置信息:
{clip_config}
============================ 错误日志结束 ============================"""
        
        log_path = f'./videos/error_logs/generation_error_report_{timestamp}.log'
        if not os.path.exists(os.path.dirname(log_path)):
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_content)
        
        print("FFmpeg 生成失败！详细错误报告已保存为文件；")
        print("请将此文件发送给 chu-gen 开发者，而不是这个画面的截图。")
        print(f"路径：{os.path.abspath(log_path)}")
        print("============================ 这里是分隔符 ============================")


class InfoSegmentGenerator(VideoGenerator):
    """信息片段（背景板/说明页）生成器"""
    
    def generate(self, clip_config: dict, output_path: str,
                 fade_duration: float = 0.0,
                 gain_db: Optional[float] = None) -> bool:
        """生成信息片段，单次编码直接写到最终路径

        Args:
            clip_config: 片段配置
            output_path: 最终输出文件路径（片段目录里的 {前缀}_{id}.mp4）
            fade_duration: 淡入淡出时长，0 表示不烘焙转场
            gain_db: 响度对齐增益 (dB)，None 表示不施加

        Returns:
            成功 True / 失败 False
        """
        start_time_generation = time.time()
        
        # 验证配置
        if 'duration' not in clip_config:
            raise ValueError(f"缺少 duration 字段: {clip_config}")
        
        # 准备路径
        bg_video_path = self._get_bg_video_path()
        bg_image_path = self._get_bg_image_path(clip_config)
        bg_audio_path = self._get_bg_audio_path(clip_config)

        self._v_fx, self._a_fx = self._build_effects(
            float(clip_config['duration']), fade_duration,
            gain_db if bg_audio_path else None)

        # 构建FFmpeg命令
        input_args, filter_complex, audio_stream = self._build_ffmpeg_command(
            clip_config, bg_video_path, 
            bg_image_path, bg_audio_path
        )
        
        encoding_args = self._build_encoding_args()
        base_args = self._build_base_ffmpeg_args()
        
        # 与编码器探测使用同一个 ffmpeg 二进制（bundled 优先）——
        # 探测结论只对执行编码的那个二进制有效
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        ffmpeg_exe = get_ffmpeg_binary('ffmpeg')

        # 先写 .part 再原子改名：中途被杀留下的半截文件不会被当成"已渲染"跳过
        staged_path = output_path + '.part'
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        def _make_cmd(enc_args: List[str]) -> List[str]:
            return [
                ffmpeg_exe,
                *input_args,
                *base_args,
                '-filter_complex', filter_complex,
                '-map', '[v_out]',
                '-map', f'[{audio_stream}]',
                *enc_args,
                '-f', 'mp4',
                staged_path
            ]

        cmd = _make_cmd(encoding_args)

        print(f"正在为您生成【{clip_config['id']}】的片段")
        print("正在执行 FFmpeg 生成命令。")

        try:
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
            except subprocess.CalledProcessError as hw_err:
                # 硬件编码器探测通过但实际编码失败（段位/驱动行为差异等）：
                # 回退 libx264 重试一次，避免整段静默丢失
                if getattr(self, 'encoder_name', 'libx264') != 'libx264':
                    print(f"[SegmentUtils] {self.encoder_name} 编码失败，回退 libx264 重试: {hw_err}")
                    cmd = _make_cmd(['-vcodec', 'libx264', '-preset', 'medium'])
                    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                else:
                    raise
            os.replace(staged_path, output_path)
            print(f"已生成您的视频片段，名称为：{clip_config['id']}.mp4")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return True
        except subprocess.CalledProcessError as e:
            _discard_staged(staged_path)
            self._log_error(clip_config, output_path,
                            cmd, self.timestamp, e)
            return None
    
    def _get_bg_video_path(self) -> str:
        """获取背景视频路径"""
        from utils.Variables import bgclips_path
        path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
        if not os.path.exists(path):
            raise FileNotFoundError(f"背景视频不存在: {path}")
        return path

    def get_audio_source(self, clip_config: dict) -> Tuple[Optional[str], float]:
        """info 片段的响度测量对象：BGM 从 0 起算，静音页返回 None"""
        path = self._get_bg_audio_path(clip_config)
        return path, 0.0
    
    def _get_bg_image_path(self, clip_config: dict) -> Optional[str]:
        """获取背景图片路径

        任何"没有可用底图"的情形（无底图开关 / 路径为空 / 文件不存在）统一
        返回 None 走纯背景渲染——此前普通文本页会把幽灵路径传给 ffmpeg 直接炸，
        与 quad 路径的优雅跳过行为分歧。
        """
        clip_id = clip_config.get('id', '?')
        bg_page = clip_config.get('bg_page', False)
        no_overlay = clip_config.get('no_overlay', False)

        if no_overlay:
            print(f"信息: 片段 {clip_id} 已禁用底板图像")
            return None
        if not bg_page:
            # 普通文本页：底图只在真实生成过时才可用
            raw = (clip_config.get('full_image') or '').strip()
            if not raw or not os.path.exists(raw):
                print(f"信息: 片段 {clip_id} 无可用底图，按纯背景渲染")
                return None
        return os.path.abspath(clip_config['full_image']).replace('\\', '/')

    def _get_bg_audio_path(self, clip_config: dict) -> Optional[str]:
        """获取背景音频路径"""
        from utils.Variables import audios_path

        # no_sound 必须短路返回 None：此前条件写成 (exists or no_sound)，
        # 勾了静音反而会把 BGM 路径带回去
        if clip_config.get('no_sound'):
            return None
        path = os.path.abspath(f"{audios_path}/bgm.mp3").replace('\\', '/')
        return path if os.path.exists(path) else None
    
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

        # 先把基础输入全部排好，回绕用的额外 bg 输入一律追加在它们之后
        # （滤镜里引用的输入索引必须等于该输入在命令行里的位置；
        #   不能用 len(input_args) 推——前面还有 -ss 这类两参数选项会把计数带偏）
        input_args = self._bg_seek_args(bg_video_path, clip_config) + ['-i', bg_video_path]
        bg_idx, n_inputs = 0, 1
        img_idx = None
        if bg_image_path:
            input_args.extend(['-i', bg_image_path])
            img_idx, n_inputs = n_inputs, n_inputs + 1
        audio_idx = None
        if bg_audio_path:
            input_args.extend(['-i', bg_audio_path])
            audio_idx, n_inputs = n_inputs, n_inputs + 1

        filter_parts = []

        # 背景视频处理（跨过 bg.mp4 末尾时自动回到开头续播，见 _bg_chain）
        bg_src = self._bg_chain(filter_parts, input_args, bg_video_path,
                                bg_idx, clip_config, duration, n_inputs)
        filter_parts.append(f'[{bg_src}]eq=brightness={darkness}[bg_processed];')

        # 背景图片叠加
        if bg_image_path:
            filter_parts.append(
                f'[bg_processed][{img_idx}:v]overlay=0:0[bg_combined];'
            )
            base_stream = 'bg_combined'
        else:
            base_stream = 'bg_processed'

        # 最终缩放
        filter_parts.append(
            f'[{base_stream}]scale={self.resolution[0]}:{self.resolution[1]},'
            f'trim=duration={duration},'
            f'setpts=PTS-STARTPTS{self._v_fx}[v_out];'
        )

        # 音频处理
        audio_stream = 'a_out'
        if bg_audio_path:
            filter_parts.append(
                f'[{audio_idx}:a]atrim=duration={duration},asetpts=PTS-STARTPTS{self._a_fx}[a_out]'
            )
        else:
            filter_parts.append(f'aevalsrc=0:duration={duration}[a_out]')

        return input_args, ''.join(filter_parts), audio_stream
    

class VideoSegmentGenerator(VideoGenerator):
    """视频片段生成器（带评论和动画效果）"""
    
    def generate(self, clip_config: dict, output_path: str,
                 fade_duration: float = 0.0,
                 gain_db: Optional[float] = None) -> bool:
        """生成视频片段（谱面确认 + 成绩图），单次编码直接写到最终路径

        Args:
            clip_config: 片段配置
            output_path: 最终输出文件路径（片段目录里的 {前缀}_{id}.mp4）
            fade_duration: 淡入淡出时长，0 表示不烘焙转场
            gain_db: 响度对齐增益 (dB)，None 表示不施加

        Returns:
            成功 True / 失败 False
        """
        start_time_generation = time.time()

        self._v_fx, self._a_fx = self._build_effects(
            float(clip_config['duration']), fade_duration, gain_db)

        # 构建FFmpeg命令
        input_args, filter_complex, audio_stream = self._build_ffmpeg_command(clip_config)
        
        encoding_args = self._build_encoding_args()
        base_args = self._build_base_ffmpeg_args()
        
        # 与编码器探测使用同一个 ffmpeg 二进制（bundled 优先）
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        ffmpeg_exe = get_ffmpeg_binary('ffmpeg')

        # 先写 .part 再原子改名：中途被杀留下的半截文件不会被当成"已渲染"跳过
        staged_path = output_path + '.part'
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        def _make_cmd(enc_args: List[str]) -> List[str]:
            return [
                ffmpeg_exe,
                *input_args,
                *base_args,
                '-filter_complex', filter_complex,
                '-map', '[v_out]',
                '-map', f'[{audio_stream}]',
                *enc_args,
                '-t', str(clip_config['duration']),
                '-f', 'mp4',
                staged_path
            ]

        cmd = _make_cmd(encoding_args)

        song_name = clip_config['song_name']
        level = REVERSE_LEVEL_LABELS[clip_config['level_index']]
        print(f"正在为您生成【{song_name} - {level}】的片段")
        print("正在执行 FFmpeg 生成命令。")

        try:
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
            except subprocess.CalledProcessError as hw_err:
                # 硬件编码失败：回退 libx264 重试一次，避免整段静默丢失
                if getattr(self, 'encoder_name', 'libx264') != 'libx264':
                    print(f"[SegmentUtils] {self.encoder_name} 编码失败，回退 libx264 重试: {hw_err}")
                    cmd = _make_cmd(['-vcodec', 'libx264', '-preset', 'medium'])
                    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                else:
                    raise
            os.replace(staged_path, output_path)
            print(f"已生成您的视频片段，名称为：{clip_config['id']}-{level}.mp4")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return True
        except subprocess.CalledProcessError as e:
            _discard_staged(staged_path)
            self._log_error(clip_config, output_path,
                            cmd, self.timestamp, e)
            return None

    def get_audio_source(self, clip_config: dict) -> Tuple[Optional[str], float]:
        """main 片段的响度测量对象：谱面视频从 start 起算的那一段"""
        return self._get_video_path(clip_config), float(clip_config.get('start', 0) or 0)
    
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

        # bg 连续循环：按片段在整条视频中的时序偏移起播背景（超出一轮则取模回绕）
        # 谱面那路同样用输入侧 -ss 定位：放在滤镜图里 trim=start=N 会把 0→N 全部
        # 解码再丢掉，实测 10s 片段因此从 9.0s 涨到 31.7s（成本在解码，不在缩放——
        # 只把 scale/trim 换序仍然要 36.5s）
        seek_chart = ['-ss', f'{float(start_time):.3f}'] if float(start_time or 0) > 0 else []
        input_args = self._bg_seek_args(bg_video_path, clip_config) + [
            '-i', bg_video_path,
            '-i', main_image_path,
            *seek_chart,
            '-i', video_path,
        ]
        
        filter_parts = []
        
        # 索引硬编码，清晰明确
        bg_video_idx = 0
        img_idx = 1
        video_idx = 2

        # 处理背景（跨过 bg.mp4 末尾时自动回到开头续播；额外输入排在 3 之后）
        bg_src = self._bg_chain(filter_parts, input_args, bg_video_path,
                                bg_video_idx, clip_config, duration, 3)
        base_stream = self._process_background(filter_parts, bg_src,
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

    def _process_background(self, filter_parts, bg_src, img_idx, duration, darkness):
        filter_parts.append(f'[{img_idx}:v]scale={self.resolution[0]}:{self.resolution[1]}[img];')
        filter_parts.append(
            f'[{bg_src}]scale={self.resolution[0]}:{self.resolution[1]},'
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
        
        # fps=60 必须在 scale 之前：overlay 按主输入的时间网格取次输入的帧，两路时间基
        # 不严格对齐时它会隔几帧才推进一次，产物虽是 60fps 容器、内容却只有 ~40fps
        # （实测现状滤镜图 45 帧里 14 帧与前一帧完全相同，加 fps=60 后为 0）
        filter_parts.append(
            f'[{video_idx}:v]fps={DEFAULT_FPS},scale=-1:{coords["height"]},'
            f'trim=duration={duration},'
            f'setpts=PTS-STARTPTS[overlay_vid];'
        )
        filter_parts.append(
            f'[{base_stream}][overlay_vid]overlay={coords["left"]}:{coords["top"]}[final_video];'
        )
        filter_parts.append(f'[final_video]trim=duration={duration}{self._v_fx}[v_out];')
        # 起播位置已由输入侧 -ss 完成，音视频都只取 duration 长度（再 atrim=start=
        # 会变成双重偏移）
        filter_parts.append(
            f'[{video_idx}:a]atrim=duration={duration},'
            f'asetpts=PTS-STARTPTS{self._a_fx}[a_out]'
        )
        
        return 'a_out'
    

# ==================== 辅助函数 ====================

def _discard_staged(staged_path: str):
    """删除编码失败留下的 .part 半成品（文件可能正被占用，忽略删除失败）"""
    try:
        if os.path.exists(staged_path):
            os.remove(staged_path)
    except OSError:
        pass


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
    force_render: bool = False,
    bake_fades: bool = True
):
    """
    生成所有视频片段并保存到最终片段目录。

    每个片段只编码一次：淡入淡出与响度对齐作为 ffmpeg 滤镜在同一条命令里完成，
    产物直接落到 final_clips_dir（旧实现先由 FFmpeg 编一遍、再交给 MoviePy 以
    libx264 重编一遍，1080p 实测第二次编码占总耗时 71%，且会废掉硬件编码器）。

    Args:
        resources: 视频配置数据
        final_clips_dir: 最终片段存储目录（拼接用的片段存放位置）
        trans_param: 过渡参数
        encoder_param: 编码器参数
        style_config: 样式配置
        force_render: 是否强制渲染
        bake_fades: 是否在片段内烘焙淡入淡出。默认 True（CPU 直拼路径用）；
            传入 False 时片段不烘焙转场，由拼接阶段的 xfade 统一处理
            （与 quad 路径保持一致，回退与 GPU 片段混用时过渡风格统一）。
    """
    from utils.Variables import bgclips_path
    
    resolution = encoder_param['resolution']
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
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
    
    # 转场不启用、或交由拼接阶段做 xfade 时，片段内不烘焙淡变
    fade_duration = 0.0
    if bake_fades and trans_param.get('enabled'):
        fade_duration = float(trans_param.get('duration', 0) or 0)

    vfile_prefix = 0
    bg_elapsed = 0.0   # bg 连续循环：累计本片段之前所有片段的时长（秒）
    failed: List[str] = []   # 编码失败的片段；不回报的话调用方会以为整片渲染成功

    def render_selected_clips(clip_configs: List[dict], segment_type: str):
        nonlocal vfile_prefix, bg_elapsed
        for config in clip_configs:
            current_prefix = vfile_prefix
            # bg 连续循环：把时序偏移注入配置，生成器的 ffmpeg 命令据此 -ss 起播背景
            config['bg_offset'] = round(bg_elapsed, 3)
            bg_elapsed += float(config.get('duration', 0))

            # 最终输出路径（保存到 final_clips_dir）
            final_output_file = os.path.join(final_clips_dir, f"{current_prefix}_{config['id']}.mp4")
            
            if config in to_render:
                if segment_type == "info":
                    print(f"开始处理头尾: {current_prefix}_{config['id']}.mp4")
                    generator = InfoSegmentGenerator(encoder_param, style_config, timestamp)
                else:
                    print(f"开始处理主片段: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                    generator = VideoSegmentGenerator(encoder_param, style_config, timestamp)

                duration = float(config.get('duration', 0) or 0)
                audio_path, audio_start = generator.get_audio_source(config)
                gain_db = measure_audio_gain_db(audio_path, audio_start, duration)
                if not generator.generate(config, final_output_file, fade_duration, gain_db):
                    failed.append(f"{current_prefix}_{config['id']}")
            
            vfile_prefix += 1
    
    # 渲染各个部分
    if 'intro' in resources:
        render_selected_clips(resources['intro'], 'info')
    
    render_selected_clips(resources['main'], 'video')
    
    if 'ending' in resources:
        render_selected_clips(resources['ending'], 'info')

    if failed:
        print(f"[SegmentUtils] 警告：{len(failed)} 个片段编码失败，未产出文件，"
              f"拼接出的完整视频会缺这些段落：{', '.join(failed[:12])}"
              f"{' …' if len(failed) > 12 else ''}")
        print(f"[SegmentUtils] 每个片段的 ffmpeg 错误详情见 ./videos/error_logs/ 下本次生成的日志")
    return failed


def _audio_signature(path: str) -> Optional[Tuple[str, int, int]]:
    """取音频流的 (codec, 采样率, 声道数)；取不到返回 None。"""
    try:
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        r = subprocess.run(
            [get_ffmpeg_binary('ffprobe'), '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_name,sample_rate,channels',
             '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=60, encoding='utf-8')
        f = r.stdout.strip().split(',')
        if len(f) >= 3:
            return (f[0], int(f[1]), int(f[2]))
    except Exception as e:
        print(f"[SegmentUtils] Warning: 读取音频参数失败 {path}: {e}")
    return None


def _unify_audio(sorted_files: List[str], final_clips_dir: str,
                 target: Tuple[str, int, int]) -> Dict[str, str]:
    """把音频参数不一致的片段规范化成 target（视频流直接拷贝，只重编音频）。

    返回 {原文件名: 应替换成的路径}。这些副本放在 videos/temp_generated 下，
    渲染收尾时会被一并清掉。必须在 concat 之前做：`-c copy` 拼接对采样率/声道数
    不一致的输入只会按第一段建轨，后续段的时间基全错（见 _build_base_ffmpeg_args）。
    """
    from utils.Quadrants.RenderIO import get_ffmpeg_binary
    tmp_dir = './videos/temp_generated/audio_unify'
    os.makedirs(tmp_dir, exist_ok=True)
    replaced = {}
    for name in sorted_files:
        src = os.path.join(final_clips_dir, name)
        sig = _audio_signature(src)
        if sig is None or sig == target:
            continue
        dst = os.path.join(tmp_dir, name)
        r = subprocess.run(
            [get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error',
             '-i', src, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
             '-c:a', target[0], '-ar', str(target[1]), '-ac', str(target[2]), dst],
            capture_output=True, text=True, timeout=600, encoding='utf-8')
        if r.returncode == 0 and os.path.exists(dst):
            replaced[name] = dst
        else:
            print(f"[SegmentUtils] 警告：{name} 音频规范化失败，仍按原样拼接："
                  f"{(r.stderr or '')[-160:]}")
    return replaced


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
        # 先统一音频参数：concat -c copy 不接受混合采样率（历史存档普遍存在）
        sigs = [s for s in (_audio_signature(os.path.join(final_clips_dir, f))
                           for f in sorted_files) if s]
        target = None
        if sigs:
            counts = collections.Counter(sigs)
            target = counts.most_common(1)[0][0]
            if len(counts) > 1:
                print(f"[信息] 检测到 {len(counts)} 种音频参数 {dict(counts)}，"
                      f"统一为 {target} 后再拼接")
                replaced = _unify_audio(sorted_files, final_clips_dir, target)
                if replaced:
                    sorted_files = [replaced.get(f, os.path.join(final_clips_dir, f))
                                    for f in sorted_files]
                else:
                    sorted_files = [os.path.join(final_clips_dir, f) for f in sorted_files]
            else:
                sorted_files = [os.path.join(final_clips_dir, f) for f in sorted_files]
        else:
            sorted_files = [os.path.join(final_clips_dir, f) for f in sorted_files]

        # 创建MP4文件列表
        mp4_list_file = os.path.join(final_clips_dir, "mp4_files.txt")
        with open(mp4_list_file, 'w', encoding='utf-8') as f:
            for full_path in sorted_files:
                f.write("file '%s'\n" % os.path.abspath(full_path).replace('\\', '/'))
        
        # 拼接输出为 MP4（输出到 final_clips_dir 目录）
        output_path = os.path.join(final_clips_dir, f"{username}_Best50.mp4")
        real_path = os.path.abspath(final_clips_dir)
        
        # 其余 5 处都走运行目录里那份 ffmpeg，这处此前漏了：PATH 上没有就会静默失败
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        cmd = [
            get_ffmpeg_binary('ffmpeg'), '-y',
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
