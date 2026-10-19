"""
QuadRenderer.py - Quadrants GPU 片段渲染编排

从 utils/Taichi/AccelRenderer2.py 移植：RenderContext + 逐片段渲染（info / main）
+ 批量渲染。计算改用 QuadAccel（Quadrants kernel + FrameCompositor），I/O 改用
RenderIO（cv2/ffmpeg + FFmpegWriter + 编码器探测）。

合成规格（与 SegmentUtils 的 InfoSegmentGenerator / VideoSegmentGenerator 对齐，
源自 AccelRenderer2.py 的开发者注释）：
- VideoSegment(main)：优先 full_image（已含文字），否则 main_image（纯成绩图）；
  音频取自谱面视频，start/duration 来自 clip_config。
- InfoSegment(info)：底板由 bg_page / no_overlay 控制：
    bg_page=T & no_overlay=T → 不放底板；
    bg_page=T & no_overlay=F → 放默认底板（full_image 为默认底板路径）；
    bg_page=F               → 放含文字底板（full_image 已渲染文字，no_overlay 无效）。
  音频取自 {audios_path}/bgm.mp3，时长取 clip_config['duration']，no_sound 可静音。

转场策略：本渲染器逐片段**不烘焙转场/淡入淡出**（fade=0），片段间的交叉淡化由
IslandConcat.combine_full_video_xfade_islands 在拼接阶段用 ffmpeg xfade 完成
（低内存、避免 README 记录的 _ArrayMemoryError）。
"""

import os
import time
import traceback
import threading
import queue as _queue
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cv2
import numpy as np

from utils.Variables import REVERSE_LEVEL_LABELS, bgclips_path, audios_path
# 素材判据与"缺素材"异常类型都取自标准路，两条路共用同一份（SegmentUtils 顶层不 import
# Quadrants，所以这里在模块级导入不会成环）。响度对齐增益同理共用一份：以前 GPU 路自己
# 算了一遍（info，夹在 ±9.5）并且对 main 干脆写死 0，两条路对同一段素材的音量不一致。
from utils.SegmentUtils import (MissingClipInputError, resolve_clip_board_image,
                                resolve_clip_video_path, measure_audio_gain_db)

from . import QuadAccel
from .QuadAccel import (
    FrameCompositor, resize_host, init_quad, is_available,
    reinit_quad, is_context_error,
)
from .RenderIO import render_checkpoint
from .RenderIO import (
    VideoFrameReader, FramePump, FFmpegWriter,
    detect_hw_encoder, resolve_encoder, is_transient_lock_error,
    ImageDecodeError, _load_image_rgba,
)


def _load_layer_or_missing(path: str, resolution):
    """底板/成绩板加载：读不出来就按「这一段缺输入」处置，与经典路同一个结局。

    旧写法由 RenderIO 塞一张**全透明占位图**继续渲：产物是一段没有成绩板的画面，
    而上层的成功判据是"没抛异常"，于是照常写指纹、照常拼进成片、界面显示「渲染完成」，
    降级只留在控制台里。经典路对同一个文件是让 ffmpeg 打不开输入、这一段带着原因失败，
    其余照跑——这里把两条路对齐（MissingClipInputError 不进重试、不触发 CPU 全量回退）。
    """
    try:
        return _load_image_rgba(path, resolution)
    except ImageDecodeError as e:
        raise MissingClipInputError(
            f"{e} —— 到【生成 Best50 图 / 查看数据】页重新生成这张图片，"
            "或关闭正在占用它的程序后重新渲染") from e


def _failed_entry(output_file: str, err: BaseException) -> str:
    """失败清单项，格式与标准路一致：`编号_片段ID（原因）`，方便页 6 直接点名是哪一段。"""
    name = os.path.basename(output_file)
    label = name[:-4] if name.endswith('.mp4') else name
    why = str(err)
    return f"{label}（{why}）" if why else label


@dataclass
class RenderContext:
    """渲染上下文，缓存整批片段共享的静态配置。"""
    resolution: Tuple[int, int]
    fps: int = 60
    bitrate: str = "5000k"
    # codec / style_config 允许不传（None 时 __post_init__ 里补默认值），标注必须是
    # Optional——写成 `codec: str = None` 时静态上"None 不是 str"，而调用方恰恰全都在
    # 传 None（render_all_clips 只给分辨率/码率/帧率）。
    # 这两个字段在 __post_init__ 里一定会被填成可用值，所以声明成非 Optional：
    # 否则 ctx.codec 静态上是 str|None、ctx.style_config[...] 是"不可下标"，
    # 而调用方（render_all_clips）本来就按必有一个可用配置来写。
    codec: str = field(default='')
    style_config: dict = field(default_factory=dict)
    # AV1 解码后端：auto / msmf / ffmpeg（见 RenderIO.VideoFrameReader）。
    av1_decoder: str = 'auto'
    # 日志去重的游标不是构造参数，用 field(init=False) 声明成真正的字段：
    # 只在 __post_init__ 里首次赋值的话，静态上它不算这个类的成员。
    _last_geom_print: Optional[tuple] = field(default=None, init=False)

    def __post_init__(self):
        if not self.codec:      # 空串=未指定，与 None 同义
            self.codec, _ = detect_hw_encoder()
        # 分辨率统一为 (w, h) 整数元组
        self.resolution = (int(self.resolution[0]), int(self.resolution[1]))


# SegmentRenderError 的家在 RenderIO（零依赖的 I/O 层）：SafeRender 要在 except 子句里
# 引用它，若那个类是"在同一个 try 内部才导入进来的"，导入本身一失败，评估 except 子句
# 就会抛 NameError 把原始错误盖掉。这里保留这个名字，历史调用方照旧能 import。
from .RenderIO import SegmentRenderError  # noqa: E402,F401


# ============================================================================
# 帧流水线辅助
# ============================================================================

def _apply_fade(out_frame: np.ndarray, idx: int, total_frames: int,
                fade_in_frames: int, fade_out_frames: int) -> np.ndarray:
    """按帧索引做淡入/淡出亮度斜坡（fade=0 时原样返回）。"""
    if fade_in_frames > 0 and idx < fade_in_frames:
        bright = idx / fade_in_frames
        return (out_frame.astype(np.float32) * bright).clip(0, 255).astype(np.uint8)
    if fade_out_frames > 0 and idx >= total_frames - fade_out_frames:
        bright = (total_frames - 1 - idx) / fade_out_frames
        return (out_frame.astype(np.float32) * bright).clip(0, 255).astype(np.uint8)
    return out_frame


def _run_frame_pipeline(total_frames, producers, composite_fn, write_fn,
                        progress_callback=None, clip_name="", queue_size=8):
    """多阶段线程流水线，重叠 解码（可多路并行）/ GPU 合成 / 编码 以逼近 max(各阶段) 的吞吐。

    - 解码线程（每路一个）：decode_fn(idx) -> data。cv2 解码/缩放释放 GIL，
      bg 与 chart 两路真并行——此前两路在同一线程串行，是实测吞吐短板。
    - 流水线线程：composite_fn(idx, frames) -> out_frame。frames 为各路按序产出的
      帧列表（与 producers 顺序一致）；Quadrants GPU 合成，kernel 已在
      init_quad 所在的常驻渲染线程预编译，这一步与该线程同线程执行，安全。
    - 编码线程：write_fn(out_frame)（memoryview 零拷贝 + ffmpeg 管道写，释放 GIL）

    Args:
        producers: [(decode_fn, stage_name), ...]，每路一个线程一条有界队列。
                   stage_name 同时是 stage_ms 的统计键（如 "decode_bg"/"decode_chart"，
                   单路时用 "decode"）。

    每路队列按路数均分 queue_size，内存恒定。主循环按 total_frames 计数逐帧从
    各路取帧配对（各路产出严格等量，天然 lockstep）；生产者死亡/出错时经
    errors 上抛，不会静默卡死。
    返回 {'elapsed': 总墙钟秒, 'frames': 已合成帧数, 'stage_ms': 各阶段累计毫秒}。
    """
    stage_names = [stage for _, stage in producers]
    if total_frames <= 0:
        return {"elapsed": 0.0, "frames": 0,
                "stage_ms": {name: 0.0 for name in (*stage_names, "composite", "encode")}}

    per_q = max(2, queue_size // len(producers))
    queues = [_queue.Queue(maxsize=per_q) for _ in producers]
    q_out = _queue.Queue(maxsize=queue_size)
    stop = threading.Event()
    errors = []
    SENTINEL = object()

    # 分阶段耗时统计（ms 累计）：只计各阶段函数体本身，不含队列等待，
    # 用于确认流水线短板——优化前先有数据。
    stage_ms = {name: 0.0 for name in (*stage_names, "composite", "encode")}
    stage_lock = threading.Lock()

    def _acc(stage, t0):
        dt = (time.perf_counter() - t0) * 1000.0
        with stage_lock:
            stage_ms[stage] += dt

    def _decoder(q, fn, stage):
        try:
            for idx in range(total_frames):
                if stop.is_set():
                    return
                _t0 = time.perf_counter()
                data = fn(idx)
                render_checkpoint()
                _acc(stage, _t0)
                while not stop.is_set():
                    try:
                        q.put((idx, data), timeout=0.1)
                        break
                    except _queue.Full:
                        continue
        except BaseException as e:  # noqa: BLE001 - 跨线程转发
            errors.append((stage, e))

    def _next_frame(q, thread, stage):
        """按序取一帧；生产者已退出且队列空 → 上抛其记录的异常（不静默卡死）。"""
        while True:
            try:
                return q.get(timeout=0.1)
            except _queue.Empty:
                if stop.is_set():
                    return None
                if not thread.is_alive():
                    if errors:
                        err_stage, e = errors[0]
                        raise RuntimeError(f"渲染流水线 {err_stage} 阶段失败: {e}") from e
                    raise RuntimeError(f"{stage} 解码线程意外退出")

    def _encoder():
        try:
            while True:
                try:
                    item = q_out.get(timeout=0.1)
                except _queue.Empty:
                    if stop.is_set():
                        break
                    continue
                if item is SENTINEL:
                    break
                _t0 = time.perf_counter()
                write_fn(item[1])
                _acc("encode", _t0)
        except BaseException as e:  # noqa: BLE001
            errors.append(("encode", e))

    t_start = time.perf_counter()
    frames_done = 0
    dts = [threading.Thread(target=_decoder, args=(q, fn, stage), daemon=True,
                            name=f"quad-decode-{stage}")
           for (fn, stage), q in zip(producers, queues)]
    et = threading.Thread(target=_encoder, daemon=True, name="quad-encode")
    for t in dts:
        t.start()
    et.start()
    try:
        for idx in range(total_frames):
            frames = []
            for q, t, stage in zip(queues, dts, stage_names):
                item = _next_frame(q, t, stage)
                if item is None:
                    break
                frames.append(item[1])
            if len(frames) < len(producers):
                break  # stop 被置位（异常终止路径），交给 errors 统一上抛
            _t0 = time.perf_counter()
            out_frame = composite_fn(idx, frames)
            render_checkpoint()
            _acc("composite", _t0)
            frames_done += 1
            # 编码线程若已死，避免在满队列上永久阻塞
            while True:
                try:
                    q_out.put((idx, out_frame), timeout=0.1)
                    break
                except _queue.Full:
                    if not et.is_alive():
                        raise RuntimeError("编码线程已退出，无法继续写入")
            if progress_callback:
                progress_callback(idx + 1, total_frames, clip_name)
    except BaseException as e:  # noqa: BLE001
        errors.append(("composite", e))
    finally:
        stop.set()
        try:
            q_out.put(SENTINEL, timeout=1.0)
        except _queue.Full:
            pass
        for t in dts:
            t.join(timeout=10.0)
        et.join(timeout=10.0)

    elapsed = time.perf_counter() - t_start
    if errors:
        stage, e = errors[0]
        raise RuntimeError(f"渲染流水线 {stage} 阶段失败: {e}") from e
    return {"elapsed": elapsed, "frames": frames_done, "stage_ms": stage_ms}


# ============================================================================
# Info 片段渲染（对应 InfoSegmentGenerator）
# ============================================================================

def render_info_segment(
    clip_config: dict,
    ctx: RenderContext,
    output_path: str,
    progress_callback=None,
    fade_in: float = 0,
    fade_out: float = 0,
    bg_start_offset: float = 0.0,
) -> dict:
    """渲染开场/结尾信息片段。bg_start_offset: 背景视频起始偏移（秒），用于跨片段连续循环。"""
    clip_id = clip_config['id']
    duration = clip_config['duration']
    total_frames = int(duration * ctx.fps)
    darkness = ctx.style_config['darkness']

    # 底板分支判断（用 .get 兼容缺失键的旧存档）：
    # no_overlay 优先——无论是否背景板页，声明了就不放任何底图。
    # bg_page 仅剩旧存档兼容语义（静态背景板），新配置不再产生它。
    no_overlay = clip_config.get('no_overlay', False)
    bg_page = clip_config.get('bg_page', False)
    full_image_path = clip_config.get('full_image') or ''

    overlay_image = None
    if no_overlay:
        print(f"[QuadRenderer] 信息片段 {clip_id}: 无底图，纯背景渲染")
    elif bg_page:
        if full_image_path and os.path.exists(full_image_path):
            overlay_image = _load_layer_or_missing(full_image_path, ctx.resolution)
            print(f"[QuadRenderer] 信息片段 {clip_id}: 使用默认底板图")
        else:
            print(f"[QuadRenderer] 信息片段 {clip_id}: 默认底板图不存在，跳过")
    else:  # 普通文本页
        if full_image_path and os.path.exists(full_image_path):
            overlay_image = _load_layer_or_missing(full_image_path, ctx.resolution)
            print(f"[QuadRenderer] 信息片段 {clip_id}: 使用含文字底板")
        else:
            print(f"[QuadRenderer] 信息片段 {clip_id}: 含文字底板不存在，跳过")

    print(f"[QuadRenderer] 正在渲染信息片段: {clip_id} (时长: {duration}s)")

    if not is_available():
        init_quad()
        if not is_available():
            return {"status": "error", "info": "Quadrants GPU 加速不可用"}

    bg_reader = None
    writer = None
    try:
        # 1. 背景视频
        bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4")
        if not os.path.exists(bg_video_path):
            raise FileNotFoundError(f"背景视频不存在: {bg_video_path}")
        # profiling 实测：对本项目 bg.mp4，cv2 软解(~9.3ms/帧) 快于 ffmpeg -hwaccel
        # 管道(~17ms/帧，管道读延迟高、流水线收益差)，且与 video 片段背景读取一致。
        # 若某些硬件上 hwaccel 更快，可换回 RenderIO.HWAccelFrameReader。
        bg_reader = VideoFrameReader(bg_video_path, av1_decoder=ctx.av1_decoder)
        bg_pump = FramePump(bg_reader, ctx.fps, loop=True)

        # 2. 音频（{audios_path}/bgm.mp3，no_sound 可静音）
        audio_path = None
        if not clip_config.get('no_sound', False):
            audio_path = os.path.abspath(f"{audios_path}/bgm.mp3")
            if not os.path.exists(audio_path):
                print(f"[QuadRenderer] 警告: BGM 文件不存在: {audio_path}")
                audio_path = None

        # 3. 音频响度均衡：与经典路共用 measure_audio_gain_db（同一个目标电平 -20 dBFS、
        # 同一对夹取边界 ±20/+9.542 dB），不再自己抄一份 9.5
        volume_adjust_db = measure_audio_gain_db(audio_path, 0, duration) or 0.0
        if abs(volume_adjust_db) > 0.01:
            print(f"[QuadRenderer] 音频均衡: {clip_id} 调整={volume_adjust_db:+.2f}dB")

        placeholder_bg = np.zeros((ctx.resolution[1], ctx.resolution[0], 3), dtype=np.uint8)

        # 4. 合成器（2 层模式）
        compositor = FrameCompositor(
            "info", placeholder_bg, darkness, ctx.resolution,
            overlay_image=overlay_image,
        )

        # 5. FFmpeg 写入器
        writer = FFmpegWriter(
            output_path, ctx.resolution[0], ctx.resolution[1],
            ctx.fps, ctx.codec, ctx.bitrate,
            audio_path, 0, duration, fade_in, fade_out, volume_adjust_db,
        )

        # 6. 流水线渲染（解码线程 → 当前渲染线程合成 → 编码线程）
        fade_in_frames = int(fade_in * ctx.fps) if fade_in > 0 else 0
        fade_out_frames = int(fade_out * ctx.fps) if fade_out > 0 else 0
        # bg 连续循环：从全局累计偏移处起播（跨片段连续），片段内播完再从头循环。
        # FramePump 负责"源帧率 → 输出帧率"的时间基换算（旧写法 30fps 背景配 60fps
        # 输出时整段被放慢一倍，音画不同步）。
        bg_pump.seek_to(bg_start_offset % bg_reader.duration if bg_reader.duration > 0 else 0)
        res_w, res_h = ctx.resolution
        last_bg_raw = None
        last_bg_frame = None

        def _decode_bg(idx):
            nonlocal last_bg_raw, last_bg_frame
            bg_frame = bg_pump.read()
            if bg_frame is None:
                return np.zeros((res_h, res_w, 3), dtype=np.uint8)
            # 源比输出慢时同一帧会连续返回：缩放只做一次（1080p 缩放约 2~4ms/帧）
            if bg_frame is not last_bg_raw:
                last_bg_raw = bg_frame
                last_bg_frame = resize_host(bg_frame, ctx.resolution)
            return last_bg_frame

        def _composite(idx, frames):
            compositor.update_bg(frames[0])
            out_frame = compositor.composite()
            return _apply_fade(out_frame, idx, total_frames, fade_in_frames, fade_out_frames)

        stats = _run_frame_pipeline(
            total_frames, [(_decode_bg, "decode")], _composite, writer.write_frame,
            progress_callback, clip_id,
        )
        if total_frames > 0:
            n = max(stats['frames'], 1)
            sm = stats['stage_ms']
            print(f"[QuadRenderer] {clip_id}: 吞吐 {stats['elapsed'] / total_frames * 1000:.2f}ms/帧 | "
                  f"解码 {sm['decode'] / n:.2f} / 合成 {sm['composite'] / n:.2f} / "
                  f"编码 {sm['encode'] / n:.2f} ms/帧")

        writer.close()
        bg_reader.close()
        print(f"[QuadRenderer] 信息片段渲染完成: {clip_id}")
        return {"status": "success", "info": f"渲染 {clip_id} 完成", "path": output_path}

    except MissingClipInputError as e:
        # 缺素材不是编码器故障：带着原因返回，由上层按"这一段失败"记账（与标准路一致），
        # 不进重试、也不让整场中止
        return {"status": "error", "info": str(e), "missing": True}
    except Exception as e:
        print(f"[QuadRenderer] Error: {traceback.format_exc()}")
        return {"status": "error", "info": f"渲染失败: {str(e)}",
                "io": is_transient_lock_error(e)}
    finally:
        try:
            if writer is not None and not writer.finalized:
                # 成功路径已经在 try 里 close() 过了；走到这里说明是异常/取消在展开，
                # 那就丢弃暂存——半截产物不该顶用成品名（对齐经典路的 .part 语义）
                writer.discard()
        except Exception:
            pass
        try:
            if bg_reader is not None:
                bg_reader.close()
        except Exception:
            pass


# ============================================================================
# Video 片段渲染（对应 VideoSegmentGenerator）
# ============================================================================

def render_video_segment(
    clip_config: dict,
    ctx: RenderContext,
    output_path: str,
    progress_callback=None,
    fade_in: float = 0,
    fade_out: float = 0,
    bg_start_offset: float = 0.0,
) -> dict:
    """渲染主片段（成绩板 + 谱面确认视频）。bg_start_offset: 背景视频起始偏移（秒）。"""
    song_name = clip_config.get('song_name', str(clip_config.get('id', 'clip')))
    level_index = clip_config['level_index']
    level_label = REVERSE_LEVEL_LABELS[level_index]
    duration = clip_config['duration']
    start_time = clip_config['start']
    darkness = ctx.style_config['darkness']

    # 图像选择：优先 full_image（已含文字），否则 main_image（纯成绩图）。
    # 判据与标准路共用 resolve_clip_board_image：两边都缺时那一段带着原因失败，
    # 而不是静默用透明底板出一段"没有成绩板"的画面（旧写法两条路行为不同）。
    overlay_image_path = resolve_clip_board_image(clip_config)
    _full = (clip_config.get('full_image') or '').strip()
    _is_full = bool(_full) and overlay_image_path == os.path.abspath(_full).replace('\\', '/')
    print(f"[QuadRenderer] 视频片段 {song_name}: "
          f"使用 {'full_image（已含文字）' if _is_full else 'main_image（纯成绩图）'}")
    overlay_image = _load_layer_or_missing(overlay_image_path, ctx.resolution)

    print(f"[QuadRenderer] 正在渲染视频片段: {song_name} - {level_label} (时长: {duration}s)")

    if not is_available():
        init_quad()
        if not is_available():
            return {"status": "error", "info": "Quadrants GPU 加速不可用"}

    bg_reader = None
    video_reader = None
    writer = None
    try:
        # 1. 背景视频
        bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4")
        if not os.path.exists(bg_video_path):
            raise FileNotFoundError(f"背景视频不存在: {bg_video_path}")
        bg_reader = VideoFrameReader(bg_video_path, av1_decoder=ctx.av1_decoder)
        bg_pump = FramePump(bg_reader, ctx.fps, loop=True)

        # 2. 谱面视频
        # 谱面视频判据与标准路共用一份（缺素材时带着可操作原因失败，而不是 ValueError 触发重试）
        video_path = resolve_clip_video_path(clip_config)
        video_reader = VideoFrameReader(video_path, av1_decoder=ctx.av1_decoder)
        chart_pump = FramePump(video_reader, ctx.fps, loop=False)

        # 3. 谱面视频位置与缩放（与 SegmentUtils 一致）
        video_position = ctx.style_config['position']['video']
        mul_x, mul_y = video_position['overlay']
        video_pos = (int(mul_x * ctx.resolution[0]), int(mul_y * ctx.resolution[1]))
        h_resize_px = video_position['height']
        target_h = int(h_resize_px * ctx.resolution[1] / 1080)  # 以 1080p 为基准
        scale = target_h / video_reader.height
        target_w = int(video_reader.width * scale)
        target_video_size = (target_w, target_h)
        # 同批次内位置/尺寸未变化时不重复打印（它们随分辨率/素材而定，逐片段打印是噪音）
        geom_key = (video_pos, target_video_size)
        if geom_key != ctx._last_geom_print:
            ctx._last_geom_print = geom_key
            print(f"[QuadRenderer] 视频位置: {video_pos}, 缩放尺寸: {target_video_size}")

        # 4. 音频（取自谱面视频，按 start 截取）
        audio_path = video_path
        audio_start = start_time
        # 响度对齐：main 片段以前在这里写死 0 dB，而经典路对同一段算的是
        # measure_audio_gain_db（实测真实存档 15 段里差 -10.1 ~ +1.1 dB，中位 -8.7）。
        # 后果不止"GPU 片子偏响"：GPU 渲大部分 + 回退补渲几段时，同一支片子里
        # 两种口径并存，电平在补渲边界上跳。两条路现在共用同一份判据。
        volume_adjust_db = measure_audio_gain_db(audio_path, audio_start, duration) or 0.0
        if abs(volume_adjust_db) > 0.01:
            print(f"[QuadRenderer] 音频均衡: {song_name} 调整={volume_adjust_db:+.2f}dB")

        placeholder_bg = np.zeros((ctx.resolution[1], ctx.resolution[0], 3), dtype=np.uint8)

        # 5. 合成器（main 3 层模式）
        compositor = FrameCompositor(
            "main", placeholder_bg, darkness, ctx.resolution,
            overlay_image, video_pos,
        )

        # 6. FFmpeg 写入器
        writer = FFmpegWriter(
            output_path, ctx.resolution[0], ctx.resolution[1],
            ctx.fps, ctx.codec, ctx.bitrate,
            audio_path, audio_start, duration, fade_in, fade_out, volume_adjust_db,
        )

        # 7. 流水线渲染（解码线程 → 当前渲染线程合成 → 编码线程）
        total_frames = int(duration * ctx.fps)
        fade_in_frames = int(fade_in * ctx.fps) if fade_in > 0 else 0
        fade_out_frames = int(fade_out * ctx.fps) if fade_out > 0 else 0
        # bg / chart 都按输出时间基取帧：30fps 源在 60fps 输出下每帧用两次，
        # 60fps 源在 30fps 输出下跳帧（grab 不解码）。旧写法一比一读源帧，
        # 混合帧率批次里 30fps 的谱面视频会被拉成两倍时长。
        bg_pump.seek_to(bg_start_offset % bg_reader.duration if bg_reader.duration > 0 else 0)
        chart_pump.seek_to(start_time)
        res_w, res_h = ctx.resolution
        chart_w, chart_h = target_video_size

        # bg / chart 两路解码各自独立线程（cv2 解码/缩放释放 GIL，真并行）——
        # 此前在同一线程串行，是实测的吞吐短板（20.7ms/帧 里两路合计占满）
        last_bg_raw = None
        last_bg_frame = None

        def _decode_bg(idx):
            nonlocal last_bg_raw, last_bg_frame
            bg_frame = bg_pump.read()
            if bg_frame is None:
                return np.zeros((res_h, res_w, 3), dtype=np.uint8)
            # 同一源帧被连续使用时只缩放一次
            if bg_frame is not last_bg_raw:
                last_bg_raw = bg_frame
                last_bg_frame = resize_host(bg_frame, ctx.resolution)
            return last_bg_frame

        last_chart_raw = None
        last_chart_frame = None

        def _decode_chart(idx):
            nonlocal last_chart_raw, last_chart_frame
            chart_frame = chart_pump.read()
            if chart_frame is None:
                # 一帧都没读到（空文件/容器损坏）：黑底，保持 compositor 的输入契约。
                # 源帧正常耗尽时 FramePump 会保持最后一帧，不会走到这里；起点越界
                # 由 VideoFrameReader.seek_to 夹到最后一帧，也不走这条。
                return np.zeros((chart_h, chart_w, 3), dtype=np.uint8)
            if chart_frame is not last_chart_raw:
                last_chart_raw = chart_frame
                last_chart_frame = resize_host(chart_frame, target_video_size)
            return last_chart_frame

        def _composite(idx, frames):
            bg_frame, chart_frame = frames
            compositor.update_bg(bg_frame)
            out_frame = compositor.composite(chart_frame)
            return _apply_fade(out_frame, idx, total_frames, fade_in_frames, fade_out_frames)

        stats = _run_frame_pipeline(
            total_frames,
            [(_decode_bg, "decode_bg"), (_decode_chart, "decode_chart")],
            _composite, writer.write_frame,
            progress_callback, f"{song_name}-{level_label}",
        )
        if total_frames > 0:
            n = max(stats['frames'], 1)
            sm = stats['stage_ms']
            print(f"[QuadRenderer] {song_name}: 吞吐 {stats['elapsed'] / total_frames * 1000:.2f}ms/帧 | "
                  f"解码 bg {sm['decode_bg'] / n:.2f} / chart {sm['decode_chart'] / n:.2f} / "
                  f"合成 {sm['composite'] / n:.2f} / 编码 {sm['encode'] / n:.2f} ms/帧")

        writer.close()
        bg_reader.close()
        video_reader.close()
        print(f"[QuadRenderer] 视频片段渲染完成: {song_name} - {level_label}")
        return {"status": "success", "info": f"渲染 {song_name} 完成", "path": output_path}

    except MissingClipInputError as e:
        # 缺素材不是编码器故障：带着原因返回，由上层按"这一段失败"记账（与标准路一致），
        # 不进重试、也不让整场中止
        return {"status": "error", "info": str(e), "missing": True}
    except Exception as e:
        print(f"[QuadRenderer] Error: {traceback.format_exc()}")
        return {"status": "error", "info": f"渲染失败: {str(e)}",
                "io": is_transient_lock_error(e)}
    finally:
        try:
            if writer is not None and not writer.finalized:
                # 成功路径已经在 try 里 close() 过了；走到这里说明是异常/取消在展开，
                # 那就丢弃暂存——半截产物不该顶用成品名（对齐经典路的 .part 语义）
                writer.discard()
        except Exception:
            pass
        for rd in (bg_reader, video_reader):
            try:
                if rd is not None:
                    rd.close()
            except Exception:
                pass


# ============================================================================
# 批量渲染
# ============================================================================

def render_all_clips(
    video_configs: dict,
    video_output_path: str,
    encoder_param: dict,
    trans_param: dict,
    style_configs: dict,
    force_render: bool = False,
    progress_callback=None,
) -> dict:
    """GPU 加速渲染所有片段（intro → main → ending），输出 {prefix}_{id}.mp4。

    逐片段不烘焙转场（fade=0）；片段间交叉淡化由 IslandConcat 在拼接阶段完成。
    单片段失败会退让重试（最多 3 次）；仍失败且属文件占用类错误时抛出
    SegmentRenderError(io=True)，SafeRender 据此跳过 CPU 回退。

    Args:
        video_configs: {'intro': [...], 'main': [...], 'ending': [...]}
        encoder_param: {'resolution': (w,h), 'bitrate': int(kbps),
                        'fps': int 可选，默认 60, ...}
                        编码器在此路径上始终自动探测，与页面复选框无关
        trans_param:   {'enabled': bool, 'duration': float}（此处不烘焙，仅保留签名兼容）
        style_configs: customization.json 内容（darkness / position.video）
        force_render:  覆盖已存在片段
        progress_callback: (clip_idx, total_clips, frame, total_frames, clip_name)

    Returns:
        {'status': 'success'|'error', 'info': str}
    """
    resolution = encoder_param['resolution']
    bitrate = f"{encoder_param['bitrate']}k"
    # 输出帧率：优先显式指定，否则取**本批全部 main 源**里的最高帧率（≤60）。
    # 早期版本的 break 让整批只看 main[0]；只修成"第一条存在的源"仍然不对——一批里
    # 混着 30fps 与 60fps 素材时，按 30fps 输出会把 60fps 谱面砍掉一半帧（画面顿挫）。
    # 取最高值后，低帧率源由 FramePump 按时间基重复帧，既不失真也不改变时长。
    video_fps = int(encoder_param.get('fps') or 0)
    if video_fps <= 0:
        probed_sources = []   # [(fps, basename)]：探测成功的每一条都参与决策
        for cfg in (video_configs.get('main', []) or []):
            vpath = cfg.get('video') or ''
            if not (vpath and os.path.exists(vpath)):
                continue
            try:
                cap = cv2.VideoCapture(vpath)
                try:
                    probed = cap.get(cv2.CAP_PROP_FPS)
                finally:
                    cap.release()
                if probed and 1 < probed <= 120:
                    probed_sources.append((float(probed), os.path.basename(vpath)))
            except Exception as e:
                print(f"[QuadRenderer] 源帧率探测失败（{os.path.basename(vpath)}）: {e}")
                continue
        if probed_sources:
            best_fps, best_name = max(probed_sources, key=lambda item: item[0])
            video_fps = max(1, min(60, round(best_fps)))
            distinct = sorted({round(fps, 2) for fps, _ in probed_sources})
            print(f"[QuadRenderer] 输出帧率取本批源视频最高值: {video_fps}fps"
                  f"（{len(probed_sources)} 段源，{best_fps:.3f}fps 来自 {best_name}"
                  + (f"，混合 {distinct}fps" if len(distinct) > 1 else "") + "）")
        else:
            video_fps = 60
            print("[QuadRenderer] 没有可探测的 main 源视频，输出帧率回退 60fps")

    # 写回探测结果：SafeRender 的 CPU 回退路径要用同一个 fps 拼接（片段与
    # 拼接时间基一致，混用 quad/回退片段时不会出现帧率不一致）
    encoder_param['fps'] = video_fps

    # 两条路用**同一个判据**选编码器（RenderIO.resolve_encoder：页面点名了就用点名的，
    # 没点名就实探 videotoolbox→nvenc→amf→qsv，全不通才 libx264），所以【编码器方案】
    # 对两个按钮都算数，指纹里记的也只有一个值（resolve 会把结论写回 encoder_param）。
    # 这里以前刻意不接页面的选择，理由是"未勾选加速时它是 libx264，软编线程与 cv2 解码
    # 抢核（实测解码被拖到 27-47ms/帧）"——那个前提已经不成立了：自动档现在写的就是
    # 实探结果，只有整台机器一个硬编都没有时才会落到 libx264，那时两条路都只能软编。
    ctx = RenderContext(resolution, video_fps, bitrate,
                        codec=resolve_encoder(encoder_param), style_config=style_configs,
                        av1_decoder=encoder_param.get('av1_decoder', 'auto'))

    intro_configs = video_configs.get('intro', []) or []
    main_configs = video_configs.get('main', []) or []
    ending_configs = video_configs.get('ending', []) or []

    # 缺 main 不是能出片的状态：经典路早就有这道守卫，GPU 路此前会把 intro/ending
    # 照渲一遍、拼出一支没有正片的"成片"，页面还按成功上报。判据与文案两路对齐。
    if not main_configs:
        why = ("配置缺少 main 段（video_configs.json 里没有 main 或它是空列表），"
               "本次没有渲染任何片段。请回到【编辑 Best50 视频片段】页重新生成配置")
        print(f"[QuadRenderer] [!] {why}")
        return {"status": "error", "info": why, "failed": [why]}

    total_clips = len(intro_configs) + len(main_configs) + len(ending_configs)

    os.makedirs(video_output_path, exist_ok=True)
    # 清理陈旧的临时产物（FFmpegWriter 异常退出时保留的 .quadtmp）。
    # 只删 30 分钟以前的：并发渲染（另一脚本线程）可能正持有新 tmp，不能误删。
    now_ts = time.time()
    for stale in os.listdir(video_output_path):
        if stale.endswith('.quadtmp'):
            p = os.path.join(video_output_path, stale)
            try:
                if now_ts - os.path.getmtime(p) > 1800:
                    os.remove(p)
            except OSError:
                pass
    clip_idx = 0
    skipped = 0   # 因「文件已存在且未勾选强制重渲」而跳过的片段数
    # 缺素材的段：带着原因失败、其余照跑（判据与文案都来自标准路的 resolve_*）
    failed: list = []

    # 指纹与清单：判据走 utils.SegmentUtils.clip_is_fresh，与经典路**同一份**。
    # 以前这里只有 `is_artifact_valid and not force_render`（文件在就算渲过），
    # 于是换过分辨率/码率/素材之后 GPU 路照旧沿用上一轮的片段，而经典路会重渲——
    # 两条路对同一片段的取舍分叉，成片里混进旧内容。GPU 路不烘焙转场，故 bake_fades=False。
    from utils.SegmentUtils import (global_render_signature, clip_render_signature,
                                    read_render_manifest, write_render_manifest,
                                    clip_is_fresh, LEGACY_SIGNATURE)
    global_sig = global_render_signature(encoder_param, style_configs, trans_param,
                                         bake_fades=False)
    _manifest = read_render_manifest(video_output_path)
    clip_sigs: dict = {}
    _ci = 0
    _sig_offset = 0.0   # 与渲染循环同一个 bg 累计口径（intro→main→ending）
    for _cfgs in (intro_configs, main_configs, ending_configs):
        for _c in _cfgs:
            # bg_offset 决定这段背景从循环的哪一秒起播。前序片段时长一变（不换序、
            # 不改本段参数），本段指纹也必须跟着变，否则会复用一段背景起点错误的旧产物。
            clip_sigs[f"{_ci}_{_c['id']}.mp4"] = clip_render_signature(
                _c, bg_offset=_sig_offset)
            _sig_offset += float(_c.get('duration', 0) or 0)
            _ci += 1
    kept_signatures: dict = {}

    def _keep_and_flush(output_file: str, reused: bool):
        """记下这段的指纹并落盘。逐段写而不等整场结束：取消或中途失败时，
        已经渲好的那些片段如果没有指纹，下一轮会连它们一起重渲（几十段白编）。"""
        name = os.path.basename(output_file)
        if reused:
            kept_signatures[name] = ((_manifest or {}).get('clips') or {}).get(
                name, LEGACY_SIGNATURE)
        else:
            kept_signatures[name] = clip_sigs.get(name, LEGACY_SIGNATURE)
        write_render_manifest(video_output_path, global_sig, dict(kept_signatures))

    def make_cb(clip_name):
        if progress_callback is None:
            return None
        cb_target = progress_callback   # 闭包里读的是形参的声明类型（Optional），
        def cb(frame, total_frames, name):   # 用局部变量把上面判过的结果带进闭包
            cb_target(clip_idx, total_clips, frame, total_frames, clip_name)
        return cb

    def _render_with_retry(render_fn, config, output_file, name, kind_label, bg_start_offset=0.0):
        """片段级重试：文件占用类瞬时失败退让重试；CUDA 上下文失效则重建 GPU
        运行时后重试——避免一处故障就让整条链路降级成 CPU 全量回退。"""
        last: dict = {}   # 循环里必然被赋值；给个空 dict 让静态也能读 .get
        reinited = False
        attempt = 0
        while attempt < 3:
            result = render_fn(config, ctx, output_file, make_cb(name), 0, 0,
                               bg_start_offset=bg_start_offset)
            if result.get('status') == 'success':
                return
            # 缺素材不重试：重试一百次它也还是缺。带着标准路那段可操作文案抛出去，
            # 由 render_all_clips 按"这一段失败"记账、其余照跑（与经典路同构）。
            if result.get('missing'):
                raise MissingClipInputError(str(result.get('info')))
            # 取消先过检查点：终止登记的 ffmpeg 子进程会让写帧那边先撞上
            # BrokenPipeError，它的形状和"编码器失败"一模一样。不在这里判一下，
            # 就会烧掉 3 次重试、再抛 SegmentRenderError 让 SafeRender 回退 CPU
            # 全量重渲——实测就是这个现象：用户点了取消，任务却在 CPU 上继续跑完。
            render_checkpoint()
            last = result
            info = str(result.get('info', ''))
            # GPU 上下文一旦死亡，重试只会原地失败：先重建运行时再谈重试。
            # 重建不消耗重试名额（正常只需一次，耗时秒级）。
            if not reinited and is_context_error(info):
                reinited = True
                print(f"[QuadRenderer] {kind_label}片段 {name}: 检测到 GPU 上下文失效，重建运行时")
                if reinit_quad():
                    continue
            attempt += 1
            if attempt < 3:
                delay = attempt
                print(f"[QuadRenderer] {kind_label}片段 {name} 渲染失败（{info}），"
                      f"{delay}s 后重试 ({attempt + 1}/3)")
                time.sleep(delay)
        raise SegmentRenderError(
            f"{kind_label}片段渲染失败: {last.get('info')}",
            io=bool(last.get('io')),
        )

    # ---- intro ----
    bg_elapsed = 0.0   # bg 连续循环：累计本片段之前所有片段的时长（秒）
    for page_no, config in enumerate(intro_configs, start=1):
        clip_name = config['id']
        # 进度展示用可读名（标签页标题/任务浮窗），ID 只用于落盘命名
        display_name = f"开头第 {page_no} 页"
        output_file = os.path.join(video_output_path, f"{clip_idx}_{clip_name}.mp4")
        if clip_is_fresh(output_file, force_render=force_render, global_sig=global_sig,
                         manifest=_manifest, clip_sigs=clip_sigs):
            print(f"[QuadRenderer] 跳过已存在: {display_name}")
            _keep_and_flush(output_file, reused=True)
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            skipped += 1
            continue
        try:
            _render_with_retry(render_info_segment, config, output_file, display_name, "开场",
                               bg_start_offset=bg_elapsed)
        except MissingClipInputError as e:
            failed.append(_failed_entry(output_file, e))
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            continue
        _keep_and_flush(output_file, reused=False)
        bg_elapsed += float(config.get('duration', 0))
        clip_idx += 1

    # ---- main ----
    for config in main_configs:
        clip_name = config['id']
        display_name = f"{config.get('song_name', clip_name)} [{REVERSE_LEVEL_LABELS[config['level_index']]}]"
        output_file = os.path.join(video_output_path, f"{clip_idx}_{clip_name}.mp4")
        if clip_is_fresh(output_file, force_render=force_render, global_sig=global_sig,
                         manifest=_manifest, clip_sigs=clip_sigs):
            print(f"[QuadRenderer] 跳过已存在: {display_name}")
            _keep_and_flush(output_file, reused=True)
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            skipped += 1
            continue
        try:
            _render_with_retry(render_video_segment, config, output_file, display_name, "主",
                               bg_start_offset=bg_elapsed)
        except MissingClipInputError as e:
            failed.append(_failed_entry(output_file, e))
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            continue
        _keep_and_flush(output_file, reused=False)
        bg_elapsed += float(config.get('duration', 0))
        clip_idx += 1

    # ---- ending ----
    for page_no, config in enumerate(ending_configs, start=1):
        clip_name = config['id']
        display_name = f"结尾第 {page_no} 页"
        output_file = os.path.join(video_output_path, f"{clip_idx}_{clip_name}.mp4")
        if clip_is_fresh(output_file, force_render=force_render, global_sig=global_sig,
                         manifest=_manifest, clip_sigs=clip_sigs):
            print(f"[QuadRenderer] 跳过已存在: {display_name}")
            _keep_and_flush(output_file, reused=True)
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            skipped += 1
            continue
        try:
            _render_with_retry(render_info_segment, config, output_file, display_name, "结尾",
                               bg_start_offset=bg_elapsed)
        except MissingClipInputError as e:
            failed.append(_failed_entry(output_file, e))
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            continue
        _keep_and_flush(output_file, reused=False)
        bg_elapsed += float(config.get('duration', 0))
        clip_idx += 1

    # 区分「真渲染」与「全部跳过」：后者会让整个任务在 1 秒内返回（没有任何
    # 逐帧进度），页面侧看起来就像"渲染状态窗口坏了"。如实上报，便于排查。
    rendered = clip_idx - skipped - len(failed)

    # 缺素材的段：其余照跑（与标准路同构），但整场结果必须带着失败清单返回。
    # 以前一段空 video 会抛 ValueError → 白烧 3 次重试 → 整场中止，已渲好的全浪费。
    if failed:
        print(f"[QuadRenderer] 警告：{len(failed)} 个片段因输入素材不可用没有产出，"
              f"拼接出的完整视频会缺这些段落：")
        for _one in failed[:12]:
            print(f"    - {_one}")
        if len(failed) > 12:
            print(f"    … 其余 {len(failed) - 12} 段从略")
        return {
            "status": "error",
            "info": (f"{len(failed)} 个片段缺输入素材（已渲好 {rendered} 段、"
                     f"沿用 {skipped} 段）：" + "；".join(failed[:3])
                     + ("…（完整清单见上方输出）" if len(failed) > 3 else "")),
            "failed": failed, "rendered": rendered, "skipped": skipped,
        }

    if rendered == 0:
        print(f"[QuadRenderer] 全部 {clip_idx} 个片段均已存在，未重新渲染"
              f"（如需重渲请勾选「强制重新渲染」）")
        return {
            "status": "success",
            "info": f"未渲染任何片段：{clip_idx} 个片段文件均已存在（如需重渲请勾选「强制重新渲染」）",
            "rendered": 0, "skipped": skipped,
        }
    print(f"[QuadRenderer] 所有片段渲染完成：新渲染 {rendered} 个，跳过已存在 {skipped} 个")
    return {
        "status": "success",
        "info": f"渲染完成：新渲染 {rendered} 个，跳过已存在 {skipped} 个（共 {clip_idx} 个）",
        "rendered": rendered, "skipped": skipped,
    }
