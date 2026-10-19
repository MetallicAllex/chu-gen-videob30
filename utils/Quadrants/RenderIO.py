"""
RenderIO.py - 与计算框架无关的渲染 I/O 件（自包含，零 Taichi/Quadrants 依赖）

从 utils/Taichi/AccelRenderer2.py 移植：
- FFmpeg 工具/版本/硬件编码器探测
- 视频帧读取（OpenCV 软解 / FFmpeg -hwaccel 管道）
- FFmpegWriter（裸 rgb24 帧管道写入 + 音频滤镜 + 硬件编码）
- 图像加载辅助

唯一改动：FFmpegWriter.write_frame 的尺寸回退缩放改用 cv2.resize（而非 Taichi 的
resize_bilinear），使本模块完全不依赖任何 GPU 计算框架，可独立测试。
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import cv2
import numpy as np
from collections import deque
from typing import Optional, Tuple

# 编码器的唯一一张表在 utils.Variables（HW_ENCODERS）：这里只按它实探、按它取调参。
# 放 Variables 而不是放本模块，是因为 Variables 只 import os——反过来会让常量模块
# 拖上 cv2/numpy。encoder_tuning 也从这里过一道手，SegmentUtils 沿用同一个导入口。
from utils.Variables import (SOFTWARE_ENCODER, SOFTWARE_ENCODERS,
                             ENCODER_BY_CODEC,
                             encoder_probe_order, encoder_tuning)


class SegmentRenderError(RuntimeError):
    """单个片段渲染失败（重试穷尽后抛出）。

    放在 RenderIO 而不是 QuadRenderer：**SafeRender 在 `except` 子句里要用它**，
    而它原先是在那个 try 块内部才 `from .QuadRenderer import` 进来的——万一那次导入
    本身失败，Python 去评估 `except SegmentRenderError` 时会抛 NameError，把原始错误
    整个盖掉。异常类型属于"两条路之间的协议"，家该安在零依赖的 I/O 层。

    io=True 表示由文件占用类瞬时错误引起（杀软扫描 / 播放器预览 / 同步盘持锁）。
    missing=True 表示配置本身带缺口（谱面视频/成绩板缺文件或解不出来）。
    两者都让 SafeRender 跳过 CPU 全量回退——回退路径要么撞同一把锁，要么把同一段
    再缺一次，只会白烧时间。但**结论文案必须分开**：给缺素材的人报"关闭占用该文件的
    程序"是误导，那一段真正要做的是回【搜索、检查和下载视频】/【生成 Best50 图】页。
    """

    def __init__(self, message: str, io: bool = False, missing: bool = False):
        super().__init__(message)
        self.io = io
        self.missing = missing


# 当前渲染任务的轻量协议钩子（由 SafeRender 注入，避免 RenderIO 反向导入它）。
_ACTIVE_RENDER_JOB = None


def set_active_render_job(job):
    global _ACTIVE_RENDER_JOB
    _ACTIVE_RENDER_JOB = job


def clear_active_render_job(job=None):
    global _ACTIVE_RENDER_JOB
    if job is None or _ACTIVE_RENDER_JOB is job:
        _ACTIVE_RENDER_JOB = None


def get_active_render_job():
    return _ACTIVE_RENDER_JOB


def render_checkpoint():
    """在写帧等热路径检查任务取消；不按进程名操作任何外部进程。"""
    job = _ACTIVE_RENDER_JOB
    if job is not None:
        job.check_cancelled()


# ============================================================================
# 像素通道顺序约定（输入侧 BGR / 输出侧 RGB）
# ============================================================================
# 背景：cv2 解码原生输出 BGR。旧实现每帧做一次 cv2.cvtColor(BGR2RGB) 把全链路
# 统一到 RGB——实测该转换单独成本约 3.2ms/帧（占独立解码 8.2ms 的 39%）。
#
# 现约定（免每帧转换）：
#   输入侧：解码/加载后**保持 cv2 原生 BGR/BGRA**（不转换）。
#   合成侧：QuadAccel 的合成 kernel 内**反序读取**通道，写出的仍是 RGB
#           （kernel 通道对称，反序读取不改变任何逐通道运算的语义）。
#   输出侧：因此 FFmpegWriter 的 rawvideo 输入仍为 rgb24，与改动前完全一致。
#
# 收益：实测端到端省 8.5%（无编码）/ 8.8%（含编码），且编码产物与改动前
# **逐字节相同**（因为写入侧的像素格式与数据都未变）。
# 详见 PCIe_OPTIMIZATION_NOTES.md 第二部分。
INPUT_PIX_FMT = "bgr24"    # 解码→合成器：cv2 原生 BGR
OUTPUT_PIX_FMT = "rgb24"   # 合成器→编码：kernel 已把输出写回 RGB


# ============================================================================
# FFmpeg 工具 / 版本 / 硬件编码器探测
# ============================================================================

_FFMPEG_MIN_VERSION = (5, 0)  # 最低要求 FFmpeg 5.0（NVENC 新版 preset API、xfade）
_ffmpeg_version_checked = False


def get_ffmpeg_binary(tool_name: str = 'ffmpeg') -> str:
    """解析 FFmpeg 工具路径：运行目录 → 应用根目录 → PATH。

    只信 os.getcwd() 不够：随包的 ffmpeg.exe 放在应用根，而 cwd 取决于用户怎么启动
    （快捷方式"起始于"填错、从别处 streamlit run 都不一样）。PATH 上没有 ffmpeg 的机器
    于是会在这一步默默拿不到工具。以前 B 站下载合并还会把 cwd 切到 videos/downloads
    （现已取消，见 video_crawler.bilibili_download），那时连页面其它环节的解析都不一致。
    """
    executable = f"{tool_name}.exe" if os.name == 'nt' else tool_name
    app_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    for candidate in (os.path.join(os.getcwd(), executable), os.path.join(app_root, executable)):
        if os.path.exists(candidate):
            return candidate

    resolved = shutil.which(tool_name)
    if resolved:
        return resolved

    raise FileNotFoundError(f"未找到 {executable}")


def check_ffmpeg_version():
    """检测 FFmpeg 版本，低于最低要求时抛出 RuntimeError。仅首次实际执行。"""
    global _ffmpeg_version_checked
    if _ffmpeg_version_checked:
        return

    try:
        ffmpeg_path = get_ffmpeg_binary('ffmpeg')
        ffprobe_path = get_ffmpeg_binary('ffprobe')
        result = subprocess.run(
            [ffmpeg_path, '-version'],
            capture_output=True, text=True, timeout=10
        )
        match = re.search(r'ffmpeg version [nN]?(\d+)\.(\d+)', result.stdout)
        if not match:
            raise RuntimeError(
                f"无法解析 FFmpeg 版本号。请确认 FFmpeg 已正确安装。\n"
                f"FFmpeg 输出: {result.stdout.splitlines()[0] if result.stdout else '(空)'}"
            )
        major, minor = int(match.group(1)), int(match.group(2))
        if (major, minor) < _FFMPEG_MIN_VERSION:
            raise RuntimeError(
                f"FFmpeg 版本过低: 检测到 {major}.{minor}，"
                f"最低要求 {_FFMPEG_MIN_VERSION[0]}.{_FFMPEG_MIN_VERSION[1]}。"
            )
        # xfade 拼接与时长探测依赖 ffprobe，前置确认可避免长时间渲染后才报错
        subprocess.run(
            [ffprobe_path, '-version'],
            capture_output=True, text=True, timeout=10, check=True
        )
        _ffmpeg_version_checked = True
        print(f"[RenderIO] FFmpeg 版本: {major}.{minor} [OK]")
    except FileNotFoundError:
        raise RuntimeError(
            "未找到 FFmpeg 或 FFprobe，请确认已将它们添加到系统 PATH 或运行目录中。"
        )


_hw_encoder_cache = None
_hw_probe_cache = None
_sw_probe_cache = None

# 实探的优先序与显示名不在这里写第二份：Variables.HW_ENCODERS 的列表顺序就是
# detect_hw_encoder 的挑选序（第一个"列里有且实探通过"的算最优），取用走
# encoder_probe_order()。


def _encode_probe_ok(codec: str) -> bool:
    """真编一帧 nullsrc 看驱动买不买账：`-encoders` 里列出来不等于能编（驱动版本不满足
    时报错的是编码那一步），所以判据必须是实际跑一次。失败原因只打最后一行 stderr。"""
    probe = subprocess.run(
        [get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error',
         '-f', 'lavfi', '-i', 'nullsrc=s=256x256:d=0.04:r=25',
         '-c:v', codec, '-f', 'null', '-'],
        capture_output=True, text=True, timeout=10
    )
    if probe.returncode != 0:
        reason = probe.stderr.strip().split('\n')[-1] if probe.stderr.strip() else '未知原因'
        print(f"[RenderIO] {codec} 不可用: {reason}")
    return probe.returncode == 0


def probe_hw_encoders() -> list:
    """本机**实际可用**的硬件编码器，按 Variables.HW_ENCODERS 的优先序返回
    [(codec, 显示名), ...]。

    为什么单独要有这一个：页面下拉框要列出"能选的牌子"，而 detect_hw_encoder 只回第一名。
    两边必须共用同一份探测结果——否则下拉框按 `-encoders` 的列表说 AMD 可选，渲染时实探
    又说 AMD 不可用，用户点下去就是一场失败。结果进程级缓存（每个候选实探一次，几毫秒）。
    """
    global _hw_probe_cache
    if _hw_probe_cache is not None:
        return _hw_probe_cache
    available = []
    try:
        result = subprocess.run(
            [get_ffmpeg_binary('ffmpeg'), '-hide_banner', '-encoders'],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout + result.stderr
        for codec, name in encoder_probe_order():
            if codec in output and _encode_probe_ok(codec):
                available.append((codec, name))
    except Exception as e:
        print(f"[RenderIO] Warning: 检测硬件编码器失败: {e}")
    _hw_probe_cache = available
    return available


def probe_software_encoders() -> list:
    """本机 ffmpeg 实际可用的软件编码器，[(codec, 显示名), ...]。

    软件档不依赖显卡，但 libx265 不是每个 ffmpeg 构建都带：随包是 full build，用户
    自己换过 ffmpeg 时仍要实探，别把必然失败的选项摆进下拉。libx264 是兜底，不探
    （探不过是整个应用都不能编码，页面也救不了）。
    """
    global _sw_probe_cache
    if _sw_probe_cache is not None:
        return _sw_probe_cache
    available = []
    try:
        for codec in SOFTWARE_ENCODERS:
            if codec == SOFTWARE_ENCODER or _encode_probe_ok(codec):
                row = ENCODER_BY_CODEC.get(codec) or {}
                available.append((codec, row.get('name') or codec))
    except Exception as e:
        print(f"[RenderIO] Warning: 检测软件编码器失败: {e}")
    _sw_probe_cache = available
    return available


def detect_hw_encoder() -> Tuple[str, str]:
    """检测可用的 FFmpeg 硬件编码器（取优先序里第一个可用的）。

    Returns:
        (codec_name, display_name)，如 ('h264_nvenc', 'NVIDIA NVENC')；
        无可用硬件编码器时回退软编（表里 SOFTWARE_ENCODER 那一行）。
    """
    global _hw_encoder_cache
    if _hw_encoder_cache is not None:
        return _hw_encoder_cache

    available = probe_hw_encoders()
    if available:
        _hw_encoder_cache = available[0]
        print(f"[RenderIO] 检测到硬件编码器: {_hw_encoder_cache[1]} ({_hw_encoder_cache[0]})")
        return _hw_encoder_cache

    _hw_encoder_cache = (SOFTWARE_ENCODER, ENCODER_BY_CODEC[SOFTWARE_ENCODER]['name'])
    print("[RenderIO] 未检测到硬件编码器，使用 CPU 软件编码")
    return _hw_encoder_cache


def resolve_encoder(encoder_param: dict) -> str:
    """本批**实际要用**的编码器，并把结论写回 encoder_param['codec']。

    判据只此一份：用户点名了（hwaccel 且给了 codec；软件档也走这一支）就用他点的，
    否则实探、实探不通才 libx264。以前这条判据长在 SegmentUtils._build_encoding_args
    里，而指纹、GPU 路、拼接各自去读 encoder_param['codec'] —— 那个值是页面写的，
    页面写的时候不知道渲染器会不会改用它，于是"记的"和"用的"可以不是同一个（点名
    Intel 时 GPU 路照样自己探测，指纹里却记 qsv）。写回之后，下游读到的都是真正跑过
    ffmpeg 的那一个。
    """
    codec = None
    if encoder_param.get('hwaccel') and encoder_param.get('codec'):
        codec = encoder_param['codec']
    if not codec:
        codec, _ = detect_hw_encoder()
    encoder_param['codec'] = codec
    return codec


# 调参表也搬到 Variables.HW_ENCODERS 里了（encoder_tuning 从那里导进来，本模块只是
# 转手）：SegmentUtils 与这里共用同一份，不再各存一张。


def get_ffmpeg_encoder_args(codec: str, bitrate: str = "5000k") -> list:
    """`-c:v <编码器> -b:v <码率> + 调参`。未知名字一律按 libx264 编：宁可退回稳的，
    也不要把一个 ffmpeg 不认的编码器名送进命令行（旧版是静默换的，这里说一声）。"""
    if codec not in ENCODER_BY_CODEC:
        if codec and codec != SOFTWARE_ENCODER:
            print(f"[RenderIO] 未知编码器 {codec!r}，本次按 {SOFTWARE_ENCODER} 编码")
        codec = SOFTWARE_ENCODER
    return ['-c:v', codec, '-b:v', bitrate] + encoder_tuning(codec)


# ============================================================================
# 音频响度测量
# ============================================================================

# (path, start, duration) -> RMS dB；避免对同一音频（如各 info 片段共用的 bgm.mp3）
# 重复 spawn ffmpeg volumedetect 子进程。只缓存成功值，不缓存失败兜底 -20.0。
_audio_rms_cache = {}


def _measure_audio_rms(audio_path: str, start: float = 0,
                       duration: Optional[float] = None) -> float:
    """用 FFmpeg volumedetect 测量音频片段 RMS 电平 (dB)，失败返回 -20.0。

    结果按 (path, start, duration) 缓存：同一 bgm 被多个 info 片段测量时只跑一次子进程。
    """
    key = (audio_path, round(float(start), 2),
           round(float(duration), 2) if duration else None)
    cached = _audio_rms_cache.get(key)
    if cached is not None:
        return cached

    cmd = [get_ffmpeg_binary('ffmpeg'), '-hide_banner', '-loglevel', 'info']
    if start > 0:
        cmd += ['-ss', str(start)]
    if duration:
        cmd += ['-t', str(duration)]
    cmd += ['-i', audio_path, '-af', 'volumedetect', '-f', 'null', '-']

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30)
        match = re.search(r'mean_volume:\s*([-\d.]+)\s*dB', result.stderr)
        if match:
            val = float(match.group(1))
            _audio_rms_cache[key] = val
            return val
    except Exception as e:
        print(f"[RenderIO] Warning: 音频RMS测量失败: {e}")
    return -20.0


# ============================================================================
# 子进程启动（stderr 排空）
# ============================================================================

def run_owned_command(cmd: list, **kwargs):
    """运行当前任务的外部命令；Popen 登记到当前 job，取消可精准终止。"""
    job = _ACTIVE_RENDER_JOB
    process = subprocess.Popen(cmd, **kwargs)
    if job is not None:
        job.register_child(process)
    try:
        return process.communicate()
    finally:
        if job is not None:
            job.unregister_child(process)


def run_owned_complete(cmd: list, encoding: Optional[str] = 'utf-8'):
    """run_owned_command 的"要返回码 + 两条流"版本，供 SegmentUtils 编码用。

    encoding 必须允许 None：IslandConcat 三处调用**刻意**传 None 走本机 locale，
    否则 Windows 那条"另一个程序正在使用此文件"的中文提示会变乱码而漏掉
    `_is_lockish_text`（标注成 str 时 Pylance 直接报"None 不可分配给 str"）。

    那边原来写的是 `subprocess.run(check=True, capture_output=True)`：Popen 是 run() 内部
    私有的，`cancel_render` 手里没有进程对象，只能等这条 ffmpeg 自己编完——**取消点了没反应**
    就是这么来的。登记给当前 job 之后，取消会真的终止这次编码。
    """
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding=encoding, errors='replace')
    job = _ACTIVE_RENDER_JOB
    if job is not None:
        job.register_child(process)
    try:
        out, err = process.communicate()
        return process.returncode, out, err
    finally:
        if job is not None:
            job.unregister_child(process)


def _start_ffmpeg(cmd: list, capture_stdout: bool = False, bufsize: int = 0, render_job=None):
    """启动 ffmpeg，并登记到当前 RenderJob；取消只会终止该 Popen 实例。"""
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=bufsize,
    )
    if render_job is not None:
        render_job.register_child(process)
    tail = deque(maxlen=64)

    def _drain():
        stderr = process.stderr      # 建管道时就是 PIPE，运行时不会是 None；取局部是为了
        try:                         # 让"判过非空"这件事留在同一个作用域里
            for line in stderr or ():
                text = line.decode(errors='replace').rstrip()
                if text:
                    tail.append(text)
        except Exception:
            pass
        finally:
            if render_job is not None:
                render_job.unregister_child(process)

    threading.Thread(target=_drain, daemon=True,
                     name="ffmpeg-stderr-drain").start()
    return process, tail


# ============================================================================
# Windows 文件占用退让重试
# ============================================================================
# 杀毒扫描、资源管理器缩略图、播放器预览、OneDrive 同步都会短暂持锁打开
# 刚写出的 mp4；这类占用通常亚秒级释放，退让重试即可，不应升级成整段渲染失败，
# 更不应触发 SafeRender 的 CPU 全量回退（回退会撞同一把锁）。

_TRANSIENT_WINERRORS = frozenset({5, 13, 32, 33})  # 拒绝访问 / 删除待定 / 共享冲突 / 锁违规


def is_transient_lock_error(e: Optional[BaseException]) -> bool:
    """判断异常链中是否包含 Windows 文件占用类错误。

    除 OSError 识别外，还匹配 ffmpeg stderr 里透传的 'Permission denied'
    （输出文件被占用时 ffmpeg 自行退出，Python 侧只能从它的报错里看到原因）。
    """
    while e is not None:
        if isinstance(e, PermissionError):
            return True
        if getattr(e, 'winerror', None) in _TRANSIENT_WINERRORS:
            return True
        msg = str(e)
        if ('Permission denied' in msg or 'WinError 32' in msg
                or 'WinError 5' in msg or '被占用' in msg):
            return True
        e = e.__cause__
    return False


def retry_on_lock(action, what: str = "", attempts: int = 6, base_delay: float = 0.25):
    """退让重试一个受文件占用影响的操作；非占用类异常立即抛出。

    attempts=6、指数退避（0.25s 起）时总等待约 7.75s，足以覆盖绝大多数
    杀软扫描/缩略图/同步盘造成的短暂持锁。
    """
    for attempt in range(attempts):
        try:
            return action()
        except OSError as e:
            transient = (isinstance(e, PermissionError)
                         or getattr(e, 'winerror', None) in _TRANSIENT_WINERRORS)
            if not transient or attempt == attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(
                f"[RenderIO] {what} 被占用（{e}），{delay:.2f}s 后重试 ({attempt + 2}/{attempts})")
            time.sleep(delay)
    # 走到这里需要最后一轮既不 return 也不 raise——当前不可能（attempt == attempts-1
    # 那轮必然 raise）。但缺了这条兜底，本函数的返回类型就是 `T | None`，于是
    # `self.cap = retry_on_lock(_open, ...)` 被静态判成"可能是 None"，
    # 后面每一处 self.cap.get(...) 都要再摊一条错误（实测一处兜底能消 7 条）。
    raise RuntimeError(
        f"{what or 'retry_on_lock'} 的退让循环异常结束（{attempts} 次均未成功）")


# ============================================================================
# 视频帧读取
# ============================================================================

class HWAccelFrameReader:
    """FFmpeg -hwaccel auto 硬件解码，输出 BGR24 host numpy，API 兼容 VideoFrameReader。"""

    def __init__(self, video_path: str, loop: bool = False):
        self.video_path = video_path
        self.loop = loop
        self._probe()
        self.process = None
        self._stderr_tail = deque(maxlen=64)
        self._frame_size = self.width * self.height * 3  # RGB24 原始数据
        self._current_pos = 0

    def _probe(self):
        result = subprocess.run(
            [get_ffmpeg_binary('ffprobe'), '-v', 'error',
             '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,r_frame_rate,duration',
             '-of', 'json', self.video_path],
            capture_output=True, text=True
        )
        info = json.loads(result.stdout)['streams'][0]
        self.width = int(info['width'])
        self.height = int(info['height'])
        fps_str = info['r_frame_rate']
        num, den = map(int, fps_str.split('/'))
        self.fps = num / den if den else 0.0
        self.duration = float(info['duration']) if info.get(
            'duration') else 0.0
        self.frame_count = int(
            self.duration * self.fps) if self.duration else 0

    def seek_to(self, time_sec: float):
        """定位并重启解码器。"""
        self.close()
        self._current_pos = int(time_sec * self.fps)
        self._start_process(time_sec)

    def read_next(self) -> Optional[np.ndarray]:
        if self.process is None:
            self._start_process(0)
        proc = self.process
        out = proc.stdout if proc is not None else None
        if proc is None or out is None or proc.poll() is not None:
            # close() 会把 self.process 置 None，所以这一路在静态上必须是 Optional；
            # 运行时真撞上（例如另一线程刚 close）就按"读不到帧"处理，与 EOF 同语义。
            return None
        data = out.read(self._frame_size)
        if len(data) < self._frame_size:
            return None
        self._current_pos += 1
        return np.frombuffer(data, np.uint8).reshape((self.height, self.width, 3))

    def _start_process(self, seek: float = 0):
        cmd = [get_ffmpeg_binary('ffmpeg'), '-hide_banner',
               '-loglevel', 'error']
        if self.loop:
            cmd += ['-stream_loop', '-1']
        cmd += ['-hwaccel', 'auto']
        if seek > 0:
            cmd += ['-ss', str(seek)]
        cmd += ['-i', self.video_path]
        cmd += ['-f', 'rawvideo', '-pix_fmt',
                INPUT_PIX_FMT, '-vsync', '0', 'pipe:1']

        self.process, self._stderr_tail = _start_ffmpeg(
            cmd, capture_stdout=True, bufsize=self._frame_size * 4,
            render_job=_ACTIVE_RENDER_JOB)

    def close(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.process = None

    @property
    def is_open(self) -> bool:
        return True


_AV1_DECODER_MODES = ('auto', 'msmf', 'ffmpeg')
_av1_hw_decode_cache = {}


def _av1_hw_decode_available(video_path: str, width: int, height: int) -> bool:
    """本机能否硬解这条 AV1 流，按文件缓存。

    只认 ffmpeg debug 日志里的 `AV1 decode get format: d3d11`。返回码不能作判据：
    强制 libdav1d 软解、以及 4:4:4 这类硬解不支持的流，rc 同样是 0。
    """
    key = (os.path.abspath(video_path), int(width), int(height))
    if key in _av1_hw_decode_cache:
        return _av1_hw_decode_cache[key]
    ok = False
    try:
        probe = subprocess.run(
            [get_ffmpeg_binary('ffmpeg'), '-hide_banner', '-v', 'debug',
             '-hwaccel', 'd3d11va', '-hwaccel_output_format', 'd3d11',
             '-i', video_path, '-frames:v', '1', '-an', '-f', 'null', '-'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=15)
        ok = probe.returncode == 0 and 'AV1 decode get format: d3d11' in probe.stderr
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[RenderIO] AV1 硬解探测失败，按不可用处理: {e}")
    _av1_hw_decode_cache[key] = ok
    return ok


def clear_av1_hw_decode_cache():
    """清空按文件缓存的硬解探测结果（页 6「重新探测」入口）。"""
    _av1_hw_decode_cache.clear()


class VideoFrameReader:
    """使用 OpenCV 顺序读取视频帧（RGB uint8），避免随机 seek 开销。"""

    def __init__(self, video_path: str, av1_decoder: str = 'auto'):
        self.path = video_path
        if av1_decoder not in _AV1_DECODER_MODES:
            av1_decoder = 'auto'

        def _open():
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                cap.release()
                raise IOError(f"无法打开视频: {video_path}")

            # AV1 在 Windows 上可走 MSMF（Media Foundation，实测解码 28.1→11.9ms/帧）；
            # H.264 必须留在 FFMPEG——同一实测里 MSMF 反而 16.6 vs 11.7ms。MSMF 打开后
            # FOURCC 读出来是垃圾值，所以编码只能先由默认（FFMPEG）句柄判一次。
            # av1_decoder：auto=硬解探测通过才切 MSMF；msmf/ffmpeg=用户强制。
            if os.name == 'nt' and hasattr(cv2, 'CAP_MSMF'):
                fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                codec = ''.join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4))
                if codec.upper() == 'AV01':
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    if av1_decoder == 'msmf':
                        use_msmf, why = True, "强制 MSMF"
                    elif av1_decoder == 'ffmpeg':
                        use_msmf, why = False, "强制 FFMPEG"
                    elif _av1_hw_decode_available(video_path, width, height):
                        use_msmf, why = True, "硬解探测通过"
                    else:
                        use_msmf, why = False, "无可用硬解"
                    if not use_msmf:
                        print(f"[RenderIO] AV1 源{why}，保持 FFMPEG: {os.path.basename(video_path)}")
                    else:
                        msmf = cv2.VideoCapture(video_path, cv2.CAP_MSMF)
                        # 帧数/fps 缺一不可：seek_to 靠 frame_count 夹起点，读成 0 会静默
                        # 从片头开始渲，画面对不上片段配置。
                        if (msmf.isOpened()
                                and msmf.get(cv2.CAP_PROP_FRAME_WIDTH) > 0
                                and msmf.get(cv2.CAP_PROP_FRAME_HEIGHT) > 0
                                and msmf.get(cv2.CAP_PROP_FRAME_COUNT) > 0
                                and msmf.get(cv2.CAP_PROP_FPS) > 0):
                            print(f"[RenderIO] AV1 源{why}，改用 MSMF 解码: {os.path.basename(video_path)}")
                            cap.release()
                            return msmf
                        msmf.release()
                        print(f"[RenderIO] AV1 源{why}但 MSMF 打不开/元数据不全，回退 FFMPEG: "
                              f"{os.path.basename(video_path)}")
            return cap

        # 源视频被播放器/同步盘短暂持锁时退让重试，而不是直接判死整个片段
        self.cap = retry_on_lock(
            _open, what=f"打开视频 {os.path.basename(video_path)}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 60.0
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration = self.frame_count / self.fps if self.fps > 0 else 0
        self._current_pos = 0

    def seek_to(self, time_sec: float):
        frame_idx = int(time_sec * self.fps)
        # frame_count 读不出来时是 0，`min(frame_idx, -1)` 会得到 -1，cv2 对负位置
        # 的行为是"保持在当前位置"——循环背景的 seek_to(0) 于是没有回到开头。
        frame_idx = max(0, min(frame_idx, max(0, self.frame_count - 1)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        self._current_pos = frame_idx

    @property
    def current_pos(self) -> int:
        """下一帧的源索引（grab/read 都已推进到这一位）。"""
        return self._current_pos

    def grab(self) -> bool:
        """只推进不解码：输出帧率低于源帧率时用来跳过中间帧（不付解码/缩放成本）。"""
        ok = self.cap.grab()
        if ok:
            self._current_pos += 1
        return bool(ok)

    def read_next(self) -> Optional[np.ndarray]:
        ret, frame = self.cap.read()
        if ret:
            self._current_pos += 1
            # 保持 cv2 原生 BGR（不转 RGB）：合成 kernel 内反序读取，输出仍是 RGB。
            # 省掉每帧 BGR→RGB 全图转换（实测 ~3.2ms/帧）。
            return frame
        return None

    def close(self):
        if self.cap:
            self.cap.release()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class FramePump:
    """按**输出时间基**从一个 VideoFrameReader 取帧，源/输出帧率可以不同。

    旧写法每输出一帧就读源一帧：30fps 源按 60fps 输出时，画面被拉成两倍时长，而
    音频仍按 clip_config 的真实时长截取——音画从第一秒起就不同步；反过来 60fps 源
    配 30fps 输出时，一半源帧被直接丢掉（本可 grab 跳过，不必解码）。

    这里按"每输出一帧，源位置前进 src_fps/out_fps 帧"累积：
    - 源比输出慢（30→60）：同一源帧连续返回，保持真实时长；
    - 源比输出快（60→30）：用 grab() 跳过中间帧（只推进不解码），再解码目标帧；
    - loop=True：读到结尾回到开头（背景循环）；否则保持最后一帧（谱面源耗尽时
      画面停住，而不是黑屏）。

    调用约定与 VideoFrameReader 一致：先 seek_to(起点)，再反复 read()。
    """

    def __init__(self, reader: VideoFrameReader, out_fps: float,
                 loop: bool = False, hold_last: bool = True):
        self.reader = reader
        self.out_fps = max(float(out_fps), 1e-6)
        src_fps = float(getattr(reader, 'fps', 0) or 0)
        self.src_fps = src_fps if src_fps > 0 else self.out_fps
        self.loop = loop
        self.hold_last = hold_last
        self._src_pos = 0.0      # 自 seek 起点起已前进的源帧数（浮点）
        self._base_pos = 0       # seek 后的源绝对帧号
        self._last = None
        self._eof = False
        self._started = False

    @property
    def step(self) -> float:
        """每输出一帧前进的源帧数。"""
        return self.src_fps / self.out_fps

    def seek_to(self, time_sec: float):
        self.reader.seek_to(time_sec)
        self._base_pos = self.reader.current_pos
        self._src_pos = 0.0
        self._last = None
        self._eof = False
        self._started = True

    def read(self) -> Optional[np.ndarray]:
        if not self._started:
            self.seek_to(0.0)
        while True:
            if self._eof:
                if self.loop:
                    if self._last is None:
                        # 源连一帧都没读出来（空文件/容器损坏）：回绕只会原地打转，
                        # 把渲染线程挂死。交给调用方补黑帧，与"非循环源耗尽"同语义。
                        return None
                    self.seek_to(0.0)
                elif self.hold_last:
                    return self._last
                else:
                    return None

            target = self._base_pos + int(self._src_pos + 1e-6)
            if target < self.reader.current_pos:
                # 输出比源慢：当前显示帧仍在时间窗内，复用上次解码结果
                frame = self._last
            else:
                while self.reader.current_pos < target:
                    if not self.reader.grab():
                        self._eof = True
                        break
                if self._eof:
                    continue
                frame = self.reader.read_next()
                if frame is None:
                    self._eof = True
                    continue
                self._last = frame

            self._src_pos += self.step
            return frame


# ============================================================================
# FFmpeg 写入管线
# ============================================================================

# (abs_path, mtime, size) -> 是否含音频流。只缓存探测成功的结论。
_audio_stream_cache = {}


def has_audio_stream(path: str) -> bool:
    """ffprobe 确认文件里真有 a:0 流。

    只判 `os.path.exists` 不够：谱面视频可能是无声的（录屏工具/转码时丢了音轨），
    而 FFmpegWriter 会照旧 `-i path -map 1:a`——ffmpeg 报 "Stream map '1:a' matches
    no streams"，整段编码失败，上层却按"编码器故障"重试三次再回退。这里先问清楚；
    探测本身失败（工具缺失/文件被锁）时按"有音频"处理，保持旧行为，让 ffmpeg 自己
    给出可定位的报错，而不是静默换成静音轨。
    """
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), int(st.st_mtime), st.st_size)
    except OSError:
        return False
    if key in _audio_stream_cache:
        return _audio_stream_cache[key]
    try:
        result = subprocess.run(
            [get_ffmpeg_binary('ffprobe'), '-v', 'error',
             '-select_streams', 'a:0', '-show_entries', 'stream=index',
             '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        print(f"[RenderIO] 音频流探测失败，按有音频处理: {e}")
        return True
    if result.returncode != 0:
        tail = (result.stderr or '').strip().splitlines()
        print(f"[RenderIO] 音频流探测失败，按有音频处理: "
              f"{tail[-1] if tail else result.returncode}")
        return True
    has = bool(result.stdout.strip())
    _audio_stream_cache[key] = has
    return has


class FFmpegWriter:
    """通过 stdin pipe 向 FFmpeg 写入裸 rgb24 帧并编码（含音频滤镜）。"""

    def __init__(self, output_path: str, width: int, height: int,
                 fps: int = 60, codec: Optional[str] = None, bitrate: str = "5000k",
                 audio_path: Optional[str] = None, audio_start: float = 0,
                 audio_duration: Optional[float] = None,
                 audio_fade_in: float = 0, audio_fade_out: float = 0,
                 volume_adjust_db: float = 0):
        self.output_path = output_path
        self.width = width
        self.height = height

        # 版本检查以前定义了却没有任何调用点：`_FFMPEG_MIN_VERSION` 形同虚设，
        # 低版本 ffmpeg 直到 xfade/fps 参数报错时才暴露。第一次真正要编码时检查一次。
        check_ffmpeg_version()
        if codec is None:
            codec, _ = detect_hw_encoder()

        encoder_args = get_ffmpeg_encoder_args(codec, bitrate)

        cmd = [
            get_ffmpeg_binary(
                'ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning',
            '-f', 'rawvideo', '-pix_fmt', OUTPUT_PIX_FMT,
            '-s', f'{width}x{height}', '-r', str(fps),
            '-i', 'pipe:0',
        ]

        has_audio = False
        if audio_path is not None and os.path.exists(audio_path):
            # 文件在、但没有音频流：走下面的 anullsrc 分支，别让 `-map 1:a` 把整段编死
            has_audio = has_audio_stream(audio_path)
            if not has_audio:
                print("[FFmpegWriter] 音频源没有音频流，改用静音轨: "
                      f"{os.path.basename(audio_path)}")
        if has_audio:
            cmd += ['-i', audio_path]
            af_filters = []

            if audio_start > 0 or (audio_duration and audio_duration < float('inf')):
                dur_part = f":duration={audio_duration}" if audio_duration else ""
                af_filters.append(f"atrim=start={audio_start}{dur_part}")
                af_filters.append("asetpts=PTS-STARTPTS")

            # 施加门限与经典路 _build_effects 对齐（>0.01 dB）。旧的 >0.5 会让两路
            # 在 0.01~0.5 dB 这段区间里给出不同产物——量级虽小，但正是"两条路对同一段
            # 素材取舍分叉"那一类，混用时无声累积。
            if abs(volume_adjust_db) > 0.01:
                af_filters.append(f"volume={volume_adjust_db}dB")

            if audio_fade_in > 0:
                af_filters.append(f"afade=t=in:d={audio_fade_in}")
            if audio_fade_out > 0 and audio_duration:
                fade_out_start = max(0, audio_duration - audio_fade_out)
                af_filters.append(
                    f"afade=t=out:st={fade_out_start:.3f}:d={audio_fade_out}")

            # 音频源比这段要的时长短时（谱面视频被拉成更长片段、或下载到的段落不够长），
            # `-shortest` 会在音频到尾的那一刻就把容器收尾：stdin 随即关闭，还在喂帧的写侧
            # 撞 BrokenPipeError。实测 1 秒源配 8 秒请求 → 第 49 帧（≈1.63s）炸，上层报成
            # "编码器失败"，重试 3 次再回退 CPU。所以有明确 audio_duration 时把音频补到那个
            # 长度，收尾条件交给管道（视频喂完）而不是两个输入各自的长度。
            pad_to = float(audio_duration) if audio_duration else 0.0
            if pad_to > 0:
                af_filters.append(f"apad=whole_dur={pad_to:.3f}")
                # apad 只补不裁。源音频比请求时长长/采样帧量化/负 PTS 都会在尾部
                # 留一截，容器于是比视频长；补完后按精确终点收回，并把 PTS 从 0
                # 重新编号，避免 muxer 再按时间戳自行补静音。
                af_filters.append(f"atrim=start=0:end={pad_to:.3f}")
                af_filters.append("asetpts=N/SR/TB")

            if af_filters:
                cmd += ['-filter_complex', f'[1:a]{",".join(af_filters)}[a]']
                cmd += ['-map', '0:v', '-map', '[a]']
            else:
                cmd += ['-map', '0:v', '-map', '1:a']

            if pad_to <= 0:
                # 没有明确时长可补齐时保持旧行为（anullsrc 那条分支同理：无限音轨必须靠
                # -shortest 收尾，去掉它会写不停）
                cmd += ['-shortest']
        else:
            # 无音频源时生成静音音轨，确保输出始终含音频流（xfade 拼接需要）
            cmd += ['-f', 'lavfi', '-i',
                    'anullsrc=channel_layout=stereo:sample_rate=48000']
            cmd += ['-map', '0:v', '-map', '1:a', '-shortest']

        cmd += encoder_args
        cmd += ['-pix_fmt', 'yuv420p']
        cmd += ['-fflags', '+genpts', '-avoid_negative_ts',
                'make_zero', '-vsync', 'cfr']
        # 先写临时名、close 时原子替换成品名：成品路径不再经历"半写完"状态，
        # 临时后缀不带 .mp4，不会被 island 的片段扫描（^\d+_*.mp4）误收；
        # 成品名被其他程序占用（播放器/同步盘）时由 close 退让重试替换。
        self._final_output_path = output_path
        # tmp 名带 pid+线程 id：并发渲染（双页签/刷新后旧线程未死）写同一成品名时
        # 各写各的 tmp，互不踩踏；成品替换是原子操作，后完成者胜出（内容等价）。
        self._tmp_output_path = f"{output_path}.{os.getpid()}-{threading.get_ident()}.quadtmp"
        self._finalized = False
        # 临时名没有标准扩展名，ffmpeg 无法据此选 muxer，显式指定 mp4 封装
        cmd += ['-f', 'mp4', self._tmp_output_path]

        # stdout 无用途（结果直接写临时文件），显式丢弃防止意外阻塞；
        # stderr 由排空线程实时消费，避免管道写满导致的流水线死锁
        self.process, self._stderr_tail = _start_ffmpeg(
            cmd, capture_stdout=False, render_job=_ACTIVE_RENDER_JOB)

    def write_frame(self, frame: np.ndarray):
        """写入一帧 RGB uint8 数据。"""
        render_checkpoint()
        if self.process.stdin:
            if self.process.poll() is not None:
                # ffmpeg 已退出（常见：输出文件被占用/磁盘错误）。把 stderr 尾部带出来，
                # 让上层能按"文件占用"分类处理，而不是表现为莫名其妙的管道错误
                tail = "\n".join(self._stderr_tail)
                raise RuntimeError(
                    f"FFmpeg 提前退出: {tail[-400:] if tail else '(无 stderr 输出)'}")
            if frame.shape[0] != self.height or frame.shape[1] != self.width:
                # 尺寸回退缩放（罕见路径）：用 cv2，保持本模块零计算框架依赖
                frame = cv2.resize(frame, (self.width, self.height))
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = frame[:, :, :3]
            # 已是 u8 且连续则不复制（ascontiguousarray 返回原数组）；再用 memoryview
            # 直写管道，省去 tobytes() 的整帧复制（1080p 每帧约 6MB memcpy）
            frame = np.ascontiguousarray(frame, dtype=np.uint8)
            self.process.stdin.write(frame.reshape(-1).data)

    def discard(self):
        """异常/取消展开时用：终止编码器并删掉暂存文件，**不**把半成品挂上成品名。

        原先两条渲染路的收尾语义不一致：经典路是 `.part` + `os.replace`（取消就丢暂存），
        而这里的 `finally: writer.close()` 会关掉 stdin，让 ffmpeg **正常收尾并返回 0**，
        于是把一段被截断的产物挂上成品名留下（实测：请求 8 秒，产物 1.04 秒、非零字节）。
        """
        if self._finalized:
            return
        self._finalized = True
        try:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except Exception:
                    self.process.kill()
        except Exception as e:
            print(f"[FFmpegWriter] 终止编码器失败（不影响丢弃暂存）: {e}")
        try:
            if os.path.exists(self._tmp_output_path):
                # 刚 terminate 掉的 ffmpeg 句柄可能还要几十毫秒才释放（实测 WinError 32），
                # 退让几次；真删不掉也只是留一个 .quadtmp（不带 .mp4，拼接扫描收不到它，
                # 且 30 分钟以上的旧 tmp 会被 render_all_clips 的清理顺带收掉）。
                retry_on_lock(lambda: os.remove(self._tmp_output_path),
                              what=f"删除暂存 {os.path.basename(self._tmp_output_path)}",
                              attempts=4, base_delay=0.1)
        except OSError as e:
            print(f"[FFmpegWriter] 暂存文件没删掉（不阻断收尾）：{e}"
                  f"｜{self._tmp_output_path}")

    @property
    def finalized(self) -> bool:
        return self._finalized

    def close(self):
        """收尾并原子替换成品名。**任何一步没成都必须抛**，不能只 print。

        旧写法在 `returncode != 0` 时打印三行然后 return：调用方（render_info_segment /
        render_video_segment）的成功判据就是"close() 没抛异常"，于是一段编码失败的片段
        被记成 success，`_keep_and_flush` 还把指纹写进清单。两个实测后果：清单里出现
        磁盘上没有的文件，拼接阶段才报"渲染清单里有 N 个片段不在磁盘上"（错误定位到拼接
        而不是真凶那一段）；勾了「覆盖已存在的视频」时旧文件还躺在原位，陈旧内容被当成
        新渲静默进成片。经典路一直是两道判据（返回码非零即抛 + 产物非零字节），这里补齐。
        """
        if self._finalized:
            return
        self._finalized = True
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait()
        if self.process.returncode != 0:
            stderr = "\n".join(self._stderr_tail)
            print(f"[FFmpegWriter] FFmpeg 返回码 {self.process.returncode}")
            if stderr:
                print(f"[FFmpegWriter] stderr: {stderr[:800]}")
            print(f"[FFmpegWriter] 失败输出保留在: {self._tmp_output_path}")
            raise RuntimeError(
                "FFmpeg 编码失败（返回码 "
                f"{self.process.returncode}）：{(stderr[-400:] if stderr else '无 stderr 输出')}"
                f"｜暂存保留在 {os.path.basename(self._tmp_output_path)}")
        # 编码成功：临时产物原子替换为成品名；成品被占用时退让重试
        try:
            retry_on_lock(
                lambda: os.replace(self._tmp_output_path,
                                   self._final_output_path),
                what=f"写出 {os.path.basename(self._final_output_path)}")
        except OSError:
            print(f"[FFmpegWriter] 成品替换失败（目标可能正被其他程序占用），"
                  f"完整输出保留在: {self._tmp_output_path}")
            raise
        # 返回码 0 不等于产物可用：0 字节的壳子会被"文件在就算渲过"的判据收进清单
        try:
            produced = os.path.getsize(self._final_output_path)
        except OSError:
            produced = 0
        if produced <= 0:
            raise RuntimeError(f"FFmpeg 返回码 0 但产物是 0 字节/不存在："
                               f"{self._final_output_path}")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ============================================================================
# 图像加载辅助
# ============================================================================

class ImageDecodeError(RuntimeError):
    """图片在磁盘上（或压根不在），但 cv2 解不出来。

    单独一个类型是为了让调用方把它归到"这一段的输入不可用"那条通道里，
    而不是"编码器失败"——经典路遇到同样的文件是让 ffmpeg 打不开输入、
    这一段带着原因失败，其余照跑。
    """


def _load_image_rgba(path: str, target_size: Optional[tuple] = None) -> np.ndarray:
    """加载图片为 RGBA numpy 数组（target_size=(w,h)）。读不出来就抛 ImageDecodeError。

    旧写法失败时返回一张**全透明占位图**继续渲：产物是一段没有成绩板的画面，
    而上层判据是"没抛异常就是成功"，于是照常写指纹、照常拼进成片、界面显示
    「渲染完成」——降级只留在控制台里（而 start.bat 之外启动的用户常常没有控制台）。
    """
    img = None
    for attempt in range(4):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is not None:
            break
        if not os.path.exists(path):
            break
        # 文件存在却读不出：多半被扫描/同步短暂持锁，退让后重试
        time.sleep(0.2 * (attempt + 1))
    if img is None:
        why = "文件不存在" if not os.path.exists(path) else "存在但解码失败（被占用或不是有效图片）"
        raise ImageDecodeError(f"图片不可用（{why}：{path}）")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    # 保持 cv2 原生 BGRA（不转 RGBA）：合成 kernel 内反序读取。
    # 静态图只加载一次，本来就无每帧成本；统一到 BGR 是为与解码侧保持一致。
    if target_size:
        img = cv2.resize(img, target_size)
    return img


def _load_image_rgb(path: str, target_size: Optional[tuple] = None) -> np.ndarray:
    """加载图片为 3 通道 numpy 数组（target_size=(w,h)）。失败返回占位黑图。

    注意：返回的是 **cv2 原生 BGR**，与 decode 侧（VideoFrameReader）及合成
    kernel 的输入约定一致——kernel 内反序读取，故这里不要转 RGB。
    当前无调用方，保留作为公共辅助。
    """
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        if target_size:
            return np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
        return np.zeros((1080, 1920, 3), dtype=np.uint8)
    if target_size:
        img = cv2.resize(img, target_size)
    return img
