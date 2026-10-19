"""
视频处理工具模块
提供视频片段生成、音频处理、视频拼接等功能
"""

import numpy as np
from datetime import datetime
from queue import Queue, Empty
import hashlib, json, os, threading, subprocess, time, collections
from typing import Any, Dict, List, Tuple, Optional

from moviepy import ImageClip

from utils.DataUtils import sort_video_files
from utils.ImageUtils import create_blank_image
from utils.PageUtils import format_time_difference
from utils.PathUtils import is_artifact_valid, load_config, save_config, ERROR_LOG_DIR, TEMP_GENERATED_DIR
from utils.Variables import (REVERSE_LEVEL_LABELS, image_root_path,
                             SOFTWARE_ENCODER, fallback_encoder_on_failure)


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

# ── 渲染指纹：让"这个片段还要不要渲"有依据可查 ────────────────────────
# 旧判据只有一条"文件在不在"，于是三类改动都不生效（实测见 tests/test_render_freshness.py）：
#   改分辨率/码率/背景亮度 → 旧片段原样进 concat -c copy，成片一段 720p 一段 1080p；
#   名单变短 → 目录里遗留的下一号被 sort_video_files 收进清单尾巴（多播两段旧内容）；
#   同编号新旧文件同时存在 → 收哪份取决于 os.listdir 的顺序（实测旧文件赢了，
#   0 号位置播的是上一轮那首歌）。
RENDER_MANIFEST_NAME = 'render_manifest.json'
LEGACY_SIGNATURE = 'legacy'   # 升级前渲的片段：没有指纹可对照，参数不变时按原样沿用


class MissingClipInputError(ValueError):
    """片段的必需输入素材缺失/不可用。

    与"ffmpeg 跑失败"区别对待：那种是环境或编码器问题，而这是配置本身带缺口
    （页 4「仍要生成（缺失项留空）」的产物）。旧写法把它拼进命令行里的 None，
    subprocess 抛 TypeError —— 那不是 CalledProcessError，generate() 的 except 拦不住，
    于是一段素材缺失能让 50 段全停、已渲的白做（实测 TypeError: expected str, bytes
    or os.PathLike object, not NoneType）。现在改成：这一段带着原因失败，其余照跑。
    """


def resolve_clip_video_path(clip_config: dict) -> str:
    """谱面视频路径的唯一判据，**两条渲染路共用**。

    以前 Quadrants 自己判了一遍，缺素材时抛 `ValueError("视频文件不存在: ")`——文案没有指引、
    还会重试 3 次，最后 `SegmentRenderError` 让整场中止；而标准路只让那一段带着原因失败，其余照跑。
    现在两边都走这里：同一个异常类型、同一段可操作文案。
    """
    video = (clip_config.get('video') or '').strip()
    if video and os.path.exists(video):
        return os.path.abspath(video).replace('\\', '/')
    raise MissingClipInputError(
        f"谱面视频不可用（video 字段是空路径或文件不存在：{video or '（空）'}）"
        "—— 到【搜索、检查和下载视频】页补齐，或把视频按 曲ID-难度.mp4 放进 "
        "videos/downloads 后重新生成配置")


def resolve_clip_board_image(clip_config: dict) -> str:
    """成绩板图（full_image 优先，否则 main_image）的唯一判据，两条路共用。
    缺失就报缺失，别拼一条打不开的命令、也别静默用透明底板出一段没有成绩板的画面。"""
    full_image = (clip_config.get('full_image') or '').strip()
    main_image = (clip_config.get('main_image') or '').strip()
    for cand in (full_image, main_image):
        if cand and os.path.exists(cand):
            return os.path.abspath(cand).replace('\\', '/')
    raise MissingClipInputError(
        "成绩板图片不可用（main_image 与 full_image 都指向不存在的文件："
        f"{main_image or '（空）'} ｜ {full_image or '（空）'}）"
        "—— 到【生成 Best50 图 / 查看数据】页重新生成图片，再重新生成配置")


def _digest(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str)
                        .encode('utf-8')).hexdigest()[:16]


def _file_stamp(path: Optional[str]) -> str:
    """素材的 (mtime, size) 摘要；空路径/读不到都归一成固定串。"""
    if not path:
        return 'none'
    try:
        st = os.stat(path)
        return f"{int(st.st_mtime)}:{st.st_size}"
    except OSError:
        return 'missing'


def global_render_signature(encoder_param: dict, style_config: dict,
                            trans_param: Optional[dict] = None,
                            bake_fades: bool = True) -> str:
    """影响"整批片段怎么渲"的参数指纹：换它就必须整批重渲。

    只收真正进成片的量：分辨率、码率、编码器、背景亮度、谱面叠加位置与高度、
    转场方式、响度口径。不含输出目录与用户名——那两个改了不该触发重渲。
    """
    position = ((style_config or {}).get('position') or {}).get('video') or {}
    trans = trans_param or {}
    payload = {
        'res': list(encoder_param.get('resolution') or []),
        'bitrate': encoder_param.get('bitrate'),
        'codec': encoder_param.get('codec'),
        # 输出帧率必须进指纹：GPU 路会把帧率**探测回写**进 encoder_param['fps']
        # （QuadRenderer 跟随源视频帧率，源 30fps 就渲 30），经典路没有 fps 控件、
        # 一直是 DEFAULT_FPS。两个按钮共用同一个片段目录，少了这一项时 30fps 渲好的
        # 片段会被 60fps 那一批判"新鲜"直接复用，成片里就是每帧复制的顿挫，而界面上
        # 一声不响。与 'loudness' 同一条口径：宁可换键后第一次整批重渲。
        'fps': int(encoder_param.get('fps') or DEFAULT_FPS),
        'darkness': (style_config or {}).get('darkness'),
        'overlay': position.get('overlay'),
        'height': position.get('height'),
        'transition': 'bake' if bake_fades else 'xfade',
        'trans_enabled': bool(trans.get('enabled')),
        # 响度口径的版本号。修复前 Quadrants 路的 main 片段不施加逐段增益
        # （QuadRenderer 里 volume_adjust_db 写死 0），修复后两路共用
        # measure_audio_gain_db。这个键必须进指纹：否则升级前渲好的 GPU 片段会被
        # 判"新鲜"继续用，跟修复后补渲的那几段差 5~10 dB 拼在同一片子里，
        # 而界面上看不出来。代价是升级后第一次渲染会整批重编（两条路各一次）。
        'loudness': 'per-clip-v2',
    }
    # duration 只在启用转场时影响产物（xfade/acrossfade 的窗口长度，或片段内烘焙的
    # 淡变时长）。禁用转场时它被两边都忽略——旧写法无条件收进指纹，改一个不生效的
    # 数值就触发整批重渲。
    if trans.get('enabled'):
        payload['trans_duration'] = trans.get('duration')
    return _digest(payload)


def clip_render_signature(config: dict, bg_offset: float = 0.0) -> str:
    """单个片段的指纹：它自己的参数 + 输入素材的 mtime/size + 背景起播偏移。

    bg_offset 是渲染时按前序片段累计注入的派生值，但**不是**可以忽略的量：前序片段
    时长变了（顺序、本段参数都没变）时，本段背景会从循环的另一秒起播。旧写法把它
    排除在外，于是只改上一首的时长，下一段的背景画面已经换了、指纹却仍判"新鲜"。
    顺序变化本身会改文件名前缀，不计入这里也不会漏判。两条渲染路必须传同一个累计口径
    （intro→main→ending），否则混用时会互相判废/误复用。
    """
    return _digest({
        'id': config.get('id'),
        'duration': config.get('duration'),
        'start': config.get('start'),
        'end': config.get('end'),
        'text': config.get('text'),
        'bg_page': config.get('bg_page'),
        'no_overlay': config.get('no_overlay'),
        'no_sound': config.get('no_sound'),
        'bg_offset': round(float(bg_offset or 0.0), 3),
        'src': {name: _file_stamp(config.get(name))
                for name in ('main_image', 'full_image', 'video')},
    })


def read_render_manifest(final_clips_dir: str) -> Optional[dict]:
    """读片段目录里的渲染指纹清单；不存在或读不出来都返回 None（= 没有指纹可依）。"""
    path = os.path.join(final_clips_dir, RENDER_MANIFEST_NAME)
    if not is_artifact_valid(path):
        return None
    try:
        data = load_config(path)
    except Exception as e:
        print(f"[!] 渲染指纹清单读不出来，本次按旧判据处理（{path}）："
              f"{type(e).__name__}: {e}")
        return None
    if not isinstance(data, dict) or 'clips' not in data:
        return None
    return data


def write_render_manifest(final_clips_dir: str, global_sig: str,
                          clips: Dict[str, str]) -> None:
    """落盘渲染指纹清单（save_config 是原子写）。失败只警告，不打断已经渲好的产物。"""
    path = os.path.join(final_clips_dir, RENDER_MANIFEST_NAME)
    try:
        save_config(path, {'global': global_sig, 'clips': clips,
                           'written_at': datetime.now().isoformat(timespec='seconds')})
    except (OSError, ValueError) as e:
        print(f"[!] 渲染指纹清单没写进去，下次渲染可能沿用陈旧片段（{path}）："
              f"{type(e).__name__}: {e}")


# ==================== 音频处理 ====================

def measure_audio_gain_db(audio_path: Optional[str], start: float = 0,
                          duration: Optional[float] = None) -> Optional[float]:
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


# 各编码器的调参表搬到 utils/Quadrants/RenderIO.HW_ENCODER_TUNING 了，取用走
# encoder_tuning()：这张表以前在这里和 get_ffmpeg_encoder_args 的 if/elif 里各有一份，
# 加编码器要改两处。码率仍由 _build_base_ffmpeg_args 统一给，这里不重复 -b:v。


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
        # 失败原因（缺素材等）。generate() 只回 True/False，原因靠这里带出去，
        # 由 render_all_video_clips 拼进失败清单，页面才能说清"这段为什么没出片"
        self.last_error = ''

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
        if duration > 0:
            offset %= duration
        else:
            # 探测不到长度就不能照原样发 -ss：Best50 累计 500+ 秒，而 bg.mp4 只有几十秒，
            # -ss 越过文件末尾 → 背景输入零帧 → 整条滤镜图无输出（"Could not open encoder
            # before EOF"），v1.2.6 记录的 52 段里 45 段静默失败就是这条路。
            # 归零与 _bg_chain 的 loop 兜底（start=0）同一起点：画面不推进，但不丢片段。
            offset = 0.0
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
        # 与谱面那路落在同一张时间网格上（两路都取 self.out_fps），overlay 才会
        # 每帧推进（否则背景这一路作为主输入决定输出节奏，谱面会被隔帧复制）
        filter_parts.append(
            f'[{bg_idx}:v]fps={self.out_fps},trim=duration={first:.3f},'
            f'setpts=PTS-STARTPTS[bg0];')
        labels.append('[bg0]')

        remaining = duration - first
        k = 1
        while remaining > 1e-3:
            take = min(remaining, bg_dur)
            input_args.extend(['-i', bg_video_path])
            filter_parts.append(
                f'[{next_idx}:v]fps={self.out_fps},trim=duration={take:.3f},'
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

    @property
    def out_fps(self) -> int:
        """本批片段的输出帧率，与 global_render_signature 用的是同一个数。

        页面没有 fps 控件：经典渲染路从来不带这个键，取 DEFAULT_FPS；GPU 路会探测
        源视频帧率并写回 encoder_param['fps']（QuadRenderer 里那句"输出帧率跟随源"），
        于是 GPU 失败回退到本路径时，回退那几段必须按**同一个** fps 渲，否则混在
        一批里的片段一半 30 一半 60（SafeRender 拼接处也是按这份 fps 走的）。
        """
        return int(self.encoder_param.get('fps') or DEFAULT_FPS)

    def _build_encoding_args(self) -> List[str]:
        """构建编码参数。

        判据只有 RenderIO.resolve_encoder 一份：用户点名了就以他选的品牌为准
        （显卡型号只有用户自己清楚，自动探测在同机多卡时可能挑错），没点名才逐一实探
        （N/A/I），全不通才 libx264——不勾选不该等于自废加速。
        探测针对本路径实际调用的 ffmpeg 二进制，结果进程级缓存只探一次；解析结果同时
        写回 encoder_param['codec']，指纹与拼接读的就是这一个值。
        """
        from utils.Quadrants.RenderIO import resolve_encoder, encoder_tuning
        codec = resolve_encoder(self.encoder_param)
        self.encoder_name = codec
        args = ['-vcodec', codec]
        args.extend(encoder_tuning(codec))
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
            '-r', str(self.out_fps),
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
        
        log_path = os.path.join(ERROR_LOG_DIR, f'generation_error_report_{timestamp}.log')
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
                _run_encode(cmd)
            except subprocess.CalledProcessError as hw_err:
                # 硬件编码器探测通过但实际编码失败（段位/驱动行为差异等）：同族才回退
                # libx264 重试一次，避免整段静默丢失。H.265 失败不能退回 H.264——同一批
                # 片段会跨编码族，最终 concat -c copy 接不起来，宁可让这一段明确失败。
                # 但"被取消终止"也长这样——不先过一遍检查点，点取消反而会再烧一遍软编。
                _render_checkpoint()
                fallback = fallback_encoder_on_failure(
                    getattr(self, 'encoder_name', SOFTWARE_ENCODER))
                if fallback:
                    print(f"[SegmentUtils] {self.encoder_name} 编码失败，回退 {fallback} 重试: {hw_err}")
                    cmd = _make_cmd(['-vcodec', fallback, '-preset', 'medium'])
                    _run_encode(cmd)
                    # 兜底成功 = 这段真是 libx264 编的。把结论写回这批共用的字典，
                    # 让 finally 里重算的指纹记的是实际产物用的那一个——宁可下一轮
                    # 多判一次过期整批重渲，也不许硬编段与软编段在同一份清单里都自称新鲜。
                    self.encoder_param['codec'] = fallback
                else:
                    if getattr(self, 'encoder_name', SOFTWARE_ENCODER) != SOFTWARE_ENCODER:
                        print(f"[SegmentUtils] {self.encoder_name} 编码失败；H.265 不跨族"
                              f"退回 H.264（拼接无法流拷贝），本段按失败处理: {hw_err}")
                    raise
            os.replace(staged_path, output_path)
            print(f"已生成您的视频片段，名称为：{clip_config['id']}.mp4")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return True
        except subprocess.CalledProcessError as e:
            self._log_error(clip_config, output_path,
                            cmd, self.timestamp, e)
            return False
        finally:
            # 取消/异常都会留下 .part（旧写法只在 CalledProcessError 分支里清，
            # RenderCancelled 直接从 finally 外头逃出去，半成品就一直躺在片段目录里）。
            # os.replace 成功之后这里是空操作。
            _discard_staged(staged_path)
    
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

        任何"没有可用底图"的情形（无底图开关 / 路径为空 / 文件不存在 / 配置里根本没这个键）
        统一返回 None 走纯背景渲染——此前普通文本页会把幽灵路径传给 ffmpeg 直接炸，
        而 bg_page=True 那支更是直接下标 `clip_config['full_image']`：intro/ending 的配置
        是 gen_video_config 造的，里面没有这个键，只有跑过生成图片才会补上 → KeyError 崩全场；
        值为空串时 abspath("") 得到的是**应用根目录**，ffmpeg 拿到一个目录当图片输入。
        """
        clip_id = clip_config.get('id', '?')
        bg_page = clip_config.get('bg_page', False)
        no_overlay = clip_config.get('no_overlay', False)

        if no_overlay:
            print(f"信息: 片段 {clip_id} 已禁用底板图像")
            return None
        raw = (clip_config.get('full_image') or '').strip()
        if not raw:
            print(f"信息: 片段 {clip_id} 声明了底图页但没有底图路径，按纯背景渲染")
            return None
        if not os.path.exists(raw):
            # 降级必须说破：勾了背景板却渲出纯背景，不能让人以为底图生效了
            print(f"信息: 片段 {clip_id} 的底图不存在（{raw}），本次按纯背景渲染"
                  f"{'（背景板页）' if bg_page else ''}")
            return None
        return os.path.abspath(raw).replace('\\', '/')

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
        try:
            input_args, filter_complex, audio_stream = self._build_ffmpeg_command(clip_config)
        except MissingClipInputError as e:
            # 缺素材只让这一段失败并带上原因：整场停摆会把已渲好的几十段一起废掉，
            # 而"静默把 None 拼进命令行"抛的是 TypeError，下面的 except 根本接不到。
            self.last_error = str(e)
            print(f"[!] 片段 {clip_config.get('id')} 缺输入素材，跳过这一段：{e}")
            return False
        
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
                _run_encode(cmd)
            except subprocess.CalledProcessError as hw_err:
                # 同族才回退 libx264；H.265 不跨族退回 H.264（理由见 InfoSegmentGenerator）。
                # 取消终止也走这个分支，所以先过检查点——否则点「取消」会再烧一遍软件编码。
                _render_checkpoint()
                fallback = fallback_encoder_on_failure(
                    getattr(self, 'encoder_name', SOFTWARE_ENCODER))
                if fallback:
                    print(f"[SegmentUtils] {self.encoder_name} 编码失败，回退 {fallback} 重试: {hw_err}")
                    cmd = _make_cmd(['-vcodec', fallback, '-preset', 'medium'])
                    _run_encode(cmd)
                    # 兜底成功 = 这段真是 libx264 编的。把结论写回这批共用的字典，
                    # 让 finally 里重算的指纹记的是实际产物用的那一个——宁可下一轮
                    # 多判一次过期整批重渲，也不许硬编段与软编段在同一份清单里都自称新鲜。
                    self.encoder_param['codec'] = fallback
                else:
                    if getattr(self, 'encoder_name', SOFTWARE_ENCODER) != SOFTWARE_ENCODER:
                        print(f"[SegmentUtils] {self.encoder_name} 编码失败；H.265 不跨族"
                              f"退回 H.264（拼接无法流拷贝），本段按失败处理: {hw_err}")
                    raise
            os.replace(staged_path, output_path)
            print(f"已生成您的视频片段，名称为：{clip_config['id']}-{level}.mp4")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return True
        except subprocess.CalledProcessError as e:
            self._log_error(clip_config, output_path,
                            cmd, self.timestamp, e)
            return False
        finally:
            # 同 InfoSegmentGenerator：取消逃过 except 也要清掉 .part
            _discard_staged(staged_path)

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
    
    def _get_main_image_path(self, clip_config: dict) -> str:
        """成绩板图：判据已抽到模块级 `resolve_clip_board_image`（两条渲染路共用一份）。"""
        return resolve_clip_board_image(clip_config)

    def _get_video_path(self, clip_config: dict) -> str:
        """谱面视频：判据已抽到模块级 `resolve_clip_video_path`（两条渲染路共用一份）。
        历史教训（`return None` 拼进命令行 → TypeError 接不住 → 一段缺素材让 50 段全停）
        记在那个字段的函数文档里。"""
        return resolve_clip_video_path(clip_config)
    
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
        
        # fps 必须在 scale 之前：overlay 按主输入的时间网格取次输入的帧，两路时间基
        # 不严格对齐时它会隔几帧才推进一次，产物虽是 60fps 容器、内容却只有 ~40fps
        # （实测现状滤镜图 45 帧里 14 帧与前一帧完全相同，加 fps=60 后为 0）
        filter_parts.append(
            f'[{video_idx}:v]fps={self.out_fps},scale=-1:{coords["height"]},'
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


def _run_encode(cmd: List[str]):
    """跑一次片段编码，非零返回码抛 CalledProcessError。

    原来这里是 `subprocess.run(check=True, capture_output=True)`——Popen 由 run() 内部私有，
    cancel_render 拿不到进程对象，**点「取消」只能等这条 ffmpeg 自己编完**（1080p 一段几十秒）。
    改走 RenderIO 的登记通道后，取消会真的终止本次编码；被终止的片段按失败记账，
    下一段开头的检查点随即结束整场。
    """
    from utils.Quadrants.RenderIO import run_owned_complete
    rc, out, err = run_owned_complete(cmd)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, output=out, stderr=err)


def _render_checkpoint():
    """渲染循环里的取消检查点；没有活动任务时什么都不做（页 6 之外调用也安全）。"""
    try:
        from utils.Quadrants.RenderIO import render_checkpoint
        render_checkpoint()
    except ImportError:
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
    if clip is None:      # moviepy 的 with_duration 标注允许返回 None
        raise RuntimeError("生成纯黑底板失败：ImageClip 没有返回可用对象")
    clip.write_videofile(f"{bgclips_path}/black_bg.mp4", fps=DEFAULT_FPS)


def clip_is_fresh(output_file: str, *, force_render: bool, global_sig: Optional[str],
                  manifest: Optional[dict], clip_sigs: Optional[Dict[str, str]]) -> bool:
    """这段产物能不能直接复用。**SegmentUtils 与 Quadrants 两条渲染路共用这一份判据**，
    否则两条路对"同一个片段算不算已渲染"会分叉：换过参数后一边重渲、另一边照旧沿用。

    底线是非零字节（0 字节的失败产物算"已渲染"会被拼进成片，画面缺一段而界面显示成功）；
    在此之上还要求全局参数没变、且该片段的参数指纹与清单里的记录一致。
    目录里还没有清单（升级前的旧产物）时按原样沿用，本次收尾再把它们记成 legacy。
    """
    if force_render or not is_artifact_valid(output_file):
        return False
    if not global_sig or not manifest:
        return True         # 不参与指纹判定 / 无指纹时代：旧行为
    if manifest.get('global') != global_sig:
        return False        # 全局参数换过：这批产物不是本次参数的结果
    if not clip_sigs:
        return True
    name = os.path.basename(output_file)
    recorded = (manifest.get('clips') or {}).get(name)
    if recorded == LEGACY_SIGNATURE:
        return True         # 没有可比对的指纹，参数没变就照旧沿用
    return recorded == clip_sigs.get(name)


def check_rendered_clips_multithreaded(
    video_configs: Dict[str, List[Dict[str, Any]]],
    final_clips_dir: str,
    force_render: bool = False,
    max_workers: int = 4,
    global_sig: Optional[str] = None,
    clip_sigs: Optional[Dict[str, str]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    多线程检测已渲染的视频片段（检查最终片段存储目录）
    
    Args:
        video_configs: 视频配置字典
        final_clips_dir: 最终片段存储目录（拼接用的片段存放位置）
        force_render: 是否强制重新渲染
        max_workers: 最大线程数
        global_sig: 本次渲染的全局参数指纹；None = 不参与判定（旧行为，只"有文件就算已渲染"）
        clip_sigs: {输出文件名: 片段指纹}，用于同参数下的逐片段判定
    
    Returns:
        (需要渲染的配置列表, 已存在的配置列表)
    """
    # manifest 为 None 表示这批片段是"没有指纹时代"的产物：沿用旧判据，
    # 由 render_all_video_clips 在本次收尾时把它们记成 LEGACY 补齐，
    # 而不是全部推翻（那会让升级用户白白重渲整片）。
    manifest = read_render_manifest(final_clips_dir) if global_sig else None
    manifest_clips = (manifest or {}).get('clips') or {}
    params_changed = bool(manifest) and manifest.get('global') != global_sig

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
            name = os.path.basename(output_file)
            # 判据只有 clip_is_fresh 这一份（Quadrants 路也走它）：非零字节是底线，
            # 再往下要求全局参数与逐片段指纹都对得上。
            fresh = clip_is_fresh(output_file, force_render=force_render,
                                  global_sig=global_sig, manifest=manifest,
                                  clip_sigs=clip_sigs)
            result_queue.put((prefix, config, fresh))
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

    if global_sig and params_changed:
        # params_changed 已经蕴含 manifest 非 None，但那是另一个变量，窄化带不过来；
        # 用 or {} 兜一下，静态与运行时同时成立（真为 None 时这行本来就打不出内容）。
        print(f"[SegmentUtils] 渲染参数与上次不同（{(manifest or {}).get('global')} → {global_sig}），"
              f"上一轮的 {len(manifest_clips)} 个片段将重新编码")
    
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
    bake_fades: bool = True,
    progress=None
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

    # 旧写法是裸 `return`（= None），而页 6 写的是 `_failed = _render_result or []` ——
    # None 被当成"零失败"，于是这一程一个片段都没渲，页面照样去拼接并弹「渲染完成」。
    # 目录里只要有上一轮的片段，拼出来的就是拿旧素材冒充本次成果的成片。缺 main 必须
    # 走失败通道；main 是空列表同样不是能出片的状态。
    if not resources.get('main'):
        why = ("配置缺少 main 段（video_configs.json 里没有 main 或它是空列表），"
               "本次没有渲染任何片段")
        print(f"[!] {why}：请回到【编辑 Best50 视频片段】页重新生成配置")
        return [why]

    # 片段顺序与编号必须和 check_rendered_clips_multithreaded 完全一致
    # （intro → main → ending，前缀递增），否则指纹会记到别人的文件上。
    clip_name = lambda p, cfg: f"{p}_{cfg['id']}.mp4"
    ordered: List[Tuple[int, dict]] = []
    _p = 0
    for segment_type in ['intro', 'main', 'ending']:
        for config in resources.get(segment_type, []):
            ordered.append((_p, config))
            _p += 1
    # 编码器与帧率都在算指纹之前定下来并写回：指纹、每段的 -vcodec、拼接阶段读的是
    # 同一个 encoder_param，谁都不许再各自挑一次（以前页面写 libx264、渲染器却自己探测，
    # 账面值从来没进过 ffmpeg 命令行）。
    from utils.Quadrants.RenderIO import resolve_encoder
    resolve_encoder(encoder_param)
    global_sig = global_render_signature(encoder_param, style_config, trans_param, bake_fades)
    # 指纹与下面的 render_selected_clips 用同一个 bg 累计口径（intro→main→ending）：
    # 前序片段时长变化会改变本段背景的起播秒数，那一段必须跟着判废。若只在渲染时
    # 注入、不写进指纹，就会复用一段背景起点不同的旧产物，而画面上没人看得出来。
    clip_sigs: Dict[str, str] = {}
    _sig_bg = 0.0
    for _p, _cfg in ordered:
        clip_sigs[clip_name(_p, _cfg)] = clip_render_signature(_cfg, bg_offset=_sig_bg)
        _sig_bg += float(_cfg.get('duration', 0) or 0)
    manifest = read_render_manifest(final_clips_dir)
    manifest_clips = (manifest or {}).get('clips') or {}

    # 检查已有片段（在最终目录中检查）
    to_render, existing = check_rendered_clips_multithreaded(
        resources, final_clips_dir, force_render, global_sig=global_sig,
        clip_sigs=clip_sigs
    )
    if manifest is None and existing:
        print("[SegmentUtils] 片段目录里还没有渲染指纹：这批旧片段本次按原样沿用，"
              "若成片出现尺寸/画质不一致或混入旧内容，勾选「覆盖已存在的视频」重渲一次即可建立指纹。")
    
    print(f"需要渲染 {len(to_render)} 个新片段，跳过 {len(existing)} 个已存在片段")
    
    # 如果底板视频不存在则生成一份新的
    if not os.path.exists(f"{bgclips_path}/black_bg.mp4"):
        gen_black_video(5, resolution)
    
    # 转场不启用、或交由拼接阶段做 xfade 时，片段内不烘焙淡变
    fade_duration = 0.0
    if bake_fades and trans_param.get('enabled'):
        fade_duration = float(trans_param.get('duration', 0) or 0)

    vfile_prefix = 0
    bg_elapsed = 0.0   # bg 连续循环：累计本片段之前所有片段的时长（秒）
    failed: List[str] = []   # 编码失败的片段；不回报的话调用方会以为整片渲染成功
    kept_signatures: Dict[str, str] = {}   # 本次结束时磁盘上确实可用的片段 → 指纹
    done_count = 0     # 已尝试渲染的段数，只给 progress 用
    total_to_render = len(to_render)

    def report_progress(name: str):
        """把"渲到第几段"报给页面。经典路整场跑在常驻工作线程里，
        页面靠 RENDER_STATUS 轮询——没有这个回调就只能等整片渲完才动一次。"""
        if progress is None:
            return
        try:
            progress(done_count, total_to_render, name)
        except Exception as e:
            print(f"[SegmentUtils] Warning: 进度回调异常（不影响渲染）: {e}")

    def render_selected_clips(clip_configs: List[dict], segment_type: str):
        nonlocal vfile_prefix, bg_elapsed, done_count
        for config in clip_configs:
            # 取消检查点：被终止的那一段已经按失败记账，下一段开头就该结束整场，
            # 而不是把剩下几十段继续编完（旧写法连这个点都没有，取消等于没点）
            _render_checkpoint()
            current_prefix = vfile_prefix
            name = clip_name(current_prefix, config)
            # bg 连续循环：把时序偏移注入配置，生成器的 ffmpeg 命令据此 -ss 起播背景
            config['bg_offset'] = round(bg_elapsed, 3)
            bg_elapsed += float(config.get('duration', 0))

            # 最终输出路径（保存到 final_clips_dir）
            final_output_file = os.path.join(final_clips_dir, name)
            
            if config in to_render:
                if segment_type == "info":
                    print(f"开始处理头尾: {name}")
                    generator = InfoSegmentGenerator(encoder_param, style_config, timestamp)
                else:
                    print(f"开始处理主片段: {name}({config['song_name']})")
                    generator = VideoSegmentGenerator(encoder_param, style_config, timestamp)

                ok = False
                report_progress(name)
                try:
                    duration = float(config.get('duration', 0) or 0)
                    audio_path, audio_start = generator.get_audio_source(config)
                    gain_db = measure_audio_gain_db(audio_path, audio_start, duration)
                    ok = generator.generate(config, final_output_file, fade_duration, gain_db)
                except MissingClipInputError as e:
                    # get_audio_source 也会走 _get_video_path：缺素材要在这一程就定性，
                    # 不能等 subprocess 拿到 None 再抛那种接不住的 TypeError
                    generator.last_error = str(e)
                    print(f"[!] 片段 {name} 缺输入素材，跳过这一段：{e}")
                done_count += 1
                if not ok:
                    label = name[:-4] if name.endswith('.mp4') else name
                    why = getattr(generator, 'last_error', '')
                    failed.append(f"{label}（{why}）" if why else label)
                elif is_artifact_valid(final_output_file):
                    kept_signatures[name] = clip_sigs.get(name, LEGACY_SIGNATURE)
            elif is_artifact_valid(final_output_file):
                # 跳过复用的片段：原来带什么指纹就继续记什么；没记录的属于无指纹旧产物
                kept_signatures[name] = manifest_clips.get(name, LEGACY_SIGNATURE)
            
            vfile_prefix += 1
    
    # 渲染各个部分
    # 清单必须无论如何都落盘：中途取消/异常时，已经渲好的那些片段如果没有指纹，
    # 下一轮会连它们一起重渲（几十段白编）。
    try:
        if 'intro' in resources:
            render_selected_clips(resources['intro'], 'info')

        render_selected_clips(resources['main'], 'video')

        if 'ending' in resources:
            render_selected_clips(resources['ending'], 'info')
    finally:
        # 指纹清单落盘：只记"本次结束时磁盘上可用"的片段。失败与缺失的一个都不写，
        # 下次它们会被判废重渲，而不是被当成陈旧产物混进拼接清单（见 combine_full_video_direct）。
        # 按当前 encoder_param 重算，不复用渲染前那份 global_sig：中途退回软编时
        # （见 _run_encode 的两处兜底）清单必须说真话，否则换了显卡/驱动之后
        # 旧片段仍被判"新鲜"，硬编段和软编段就混在同一条 -c copy 的拼接里。
        write_render_manifest(final_clips_dir,
                              global_render_signature(encoder_param, style_config,
                                                      trans_param, bake_fades),
                              kept_signatures)

    if failed:
        print(f"[SegmentUtils] 警告：{len(failed)} 个片段没有产出文件，"
              f"拼接出的完整视频会缺这些段落：")
        for _one in failed[:12]:
            print(f"    - {_one}")
        if len(failed) > 12:
            print(f"    … 其余 {len(failed) - 12} 段从略")
        print("[SegmentUtils] ffmpeg 失败详情见 ./videos/error_logs/ 下本次生成的日志；"
              "带原因括号的属于缺素材，补素材后重新生成配置即可")
    return failed


def _probe_duration(path: str) -> Optional[float]:
    """产物/素材的容器时长（秒）；读不出返回 None。

    读不出既包括文件损坏，也包括"根本不是一个容器"——正是 -f concat 会静默跳过的那类输入。
    """
    try:
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        r = subprocess.run(
            [get_ffmpeg_binary('ffprobe'), '-v', 'error', '-show_entries',
             'format=duration', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=60, encoding='utf-8')
        text = r.stdout.strip()
        return float(text) if text else None
    except Exception:
        return None


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
    tmp_dir = os.path.join(TEMP_GENERATED_DIR, 'audio_unify')
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


def _clip_order_key(name: str) -> int:
    """从 `编号_xxx.mp4` 取排序键；不合规的文件名给可读错误，而不是裸 ValueError。"""
    head = name.split('_')[0]
    if not head.isdigit():
        raise ValueError(f"渲染清单里的文件名不符合「编号_片段ID.mp4」规则：{name}")
    return int(head)


def concat_clip_list(final_clips_dir: str) -> Optional[List[str]]:
    """本次该拼进成片的片段文件名；返回 None 表示"没有清单可依"，调用方按目录内容处理。

    这是渲染侧与拼接侧唯一的一份"拼哪些段"判据：GPU 路的 IslandConcat 也走这里，
    否则两条路对同一片段的取舍会分叉（换名单后拼进旧段、缺段照拼、编号撞车收谁都行）。
    """
    manifest = read_render_manifest(final_clips_dir)
    if not manifest:
        return None
    clips = manifest.get('clips') or {}
    if not clips:
        return None
    ordered = sorted(clips.keys(), key=_clip_order_key)
    absent = [n for n in ordered if not is_artifact_valid(os.path.join(final_clips_dir, n))]
    if absent:
        raise ValueError(f"渲染清单里有 {len(absent)} 个片段不在磁盘上，"
                         f"拼接中止以免悄悄少段落：{absent[:8]}")
    # 编号必须正好是 0..N-1：渲染侧就是按这个顺序发号的（intro → main → ending）
    nums = [_clip_order_key(n) for n in ordered]
    if nums != list(range(len(nums))):
        missing = sorted(set(range(max(nums) + 1)) - set(nums))
        raise ValueError(f"渲染清单编号不连续！缺 {missing}（当前 {nums}）——"
                         "多半是清单被改坏或中途中断过，请勾选「覆盖已存在的视频」重渲")
    return ordered


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
    
    # 拼接清单以"本次渲染产出的片段"为准（concat_clip_list 里含"文件在不在"与
    # "编号是否正好 0..N-1"两道校验）。按目录内容 listdir 有三个实测后果
    # （见 tests/test_render_freshness.py 的 L 组）：名单变短后遗留的下一号被接到尾巴上；
    # 同编号的新旧文件同时存在时收哪份取决于 os.listdir 的顺序；上一轮成片也躺在同一目录。
    listed = concat_clip_list(final_clips_dir)
    if listed:
        sorted_files = listed
        print(f"[信息] 按渲染清单拼接 {len(sorted_files)} 个片段（目录里的其他 mp4 不参与）")
    else:
        video_files = [f for f in os.listdir(final_clips_dir) if f.endswith(".mp4")]
        sorted_files = sort_video_files(video_files)
        print("[信息] 没有渲染清单可用，按目录内容拼接（旧行为）")
    
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

        # 先量一边输入：-f concat 对打不开的输入是**跳过它继续拼并返回 0**，
        # 实测 4 段里有 1 段被换成非 mp4 内容时，产物只有 0.42s（应 1.6s）却一声不响，
        # 旧写法 check=True 看不出来，还会就地覆盖上一次成功的成片。
        durations = [(_probe_duration(p), p) for p in sorted_files]
        unreadable = [os.path.basename(p) for d, p in durations if not d]
        if unreadable:
            raise ValueError(f"有 {len(unreadable)} 个片段读不出时长（多半已损坏或不是有效 mp4），"
                             f"拼接中止以免悄悄缺段落：{unreadable[:8]}")
        # 上面 unreadable 已经保证每一项都是真数值，这里再过滤一次只为让类型收敛成
        # float：生成器表达式里 pyright 不会把那道守卫连过来。
        expect_total = sum(d for d, _ in durations if d)

        # 先写 .part 再原子改名：失败时上一次的成功成片保持原样，
        # 也不会留下一份"看起来是成品"的半成品（.part 必须显式 -f mp4，
        # 否则 ffmpeg 从扩展名推不出容器）
        staged_out = output_path + '.part'
        if os.path.exists(output_path):
            print(f"[信息] 输出目录里已有 {os.path.basename(output_path)}，"
                  f"本次拼接成功后才会替换它")
        from utils.Quadrants.RenderIO import get_ffmpeg_binary
        cmd = [
            get_ffmpeg_binary('ffmpeg'), '-y',
            '-hide_banner',
            '-loglevel', 'error',
            '-f', 'concat',
            '-safe', '0',
            '-i', os.path.join(real_path, "mp4_files.txt").replace('\\', '/'),
            '-fflags', '+genpts',
            '-avoid_negative_ts', 'make_zero',
            '-max_interleave_delta', '0',
            '-c', 'copy',
            '-threads', '0',
            '-f', 'mp4',
            staged_out,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
        if result.returncode != 0 or not is_artifact_valid(staged_out):
            _discard_staged(staged_out)
            tail = ' / '.join((result.stderr or '').strip().splitlines()[-3:])
            raise RuntimeError(
                f"拼接失败（ffmpeg 返回码 {result.returncode}）："
                f"{tail or '没有错误输出，且没有产出文件'}；上一次的成功成片未被改动")

        got = _probe_duration(staged_out)
        # 容差按实测定标：这条 mp4 concat 每段只漂 ~8ms（实测 3 段 24.0ms、4 段 23.2ms），
        # 52 段量级在 0.4s 上下，30ms/段已是一倍多的余量；真少一段是 10s 量级，不会被放过。
        tolerance = max(0.5, 0.03 * len(durations))
        if got is None or abs(got - expect_total) > tolerance:
            _discard_staged(staged_out)
            raise RuntimeError(
                f"拼接产物时长对不上：期望 {expect_total:.2f}s（{len(durations)} 段之和），"
                f"实际 {('%.2f' % got) if got is not None else '读不出'}s，"
                f"容差 {tolerance:.2f}s —— 有段落没进成片，已丢弃半成品，"
                f"上一次的成功成片未被改动")
        os.replace(staged_out, output_path)
        
        print(f"[信息] ==================== 视频拼接完成（{len(durations)} 段 / "
              f"{got:.2f}s）==================")
        return output_path
    
    except Exception as e:
        print(f"拼接失败：{str(e)}")
        raise
