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
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from utils.Variables import REVERSE_LEVEL_LABELS, bgclips_path, audios_path

from . import QuadAccel
from .QuadAccel import (
    FrameCompositor, resize_host, init_quad, is_available,
    reinit_quad, is_cuda_context_error,
)
from .RenderIO import render_checkpoint
from .RenderIO import (
    VideoFrameReader, FFmpegWriter,
    detect_hw_encoder, is_transient_lock_error,
    _measure_audio_rms, _load_image_rgba,
)


@dataclass
class RenderContext:
    """渲染上下文，缓存整批片段共享的静态配置。"""
    resolution: Tuple[int, int]
    fps: int = 60
    bitrate: str = "5000k"
    codec: str = None
    style_config: dict = None

    def __post_init__(self):
        if self.codec is None:
            self.codec, _ = detect_hw_encoder()
        # 分辨率统一为 (w, h) 整数元组
        self.resolution = (int(self.resolution[0]), int(self.resolution[1]))
        # 日志去重：同批次里位置/尺寸未变化时不重复打印（它们随分辨率/素材而定）
        self._last_geom_print = None


class SegmentRenderError(RuntimeError):
    """单个片段渲染失败（重试穷尽后抛出）。

    io=True 表示由文件占用类瞬时错误引起（杀软扫描 / 播放器预览 / 同步盘持锁）。
    SafeRender 据此跳过 CPU 全量回退——回退路径会撞同一把锁，只会白烧时间。
    """

    def __init__(self, message: str, io: bool = False):
        super().__init__(message)
        self.io = io


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
    - 主线程  ：composite_fn(idx, frames) -> out_frame。frames 为各路按序产出的
      帧列表（与 producers 顺序一致）；Quadrants GPU 合成，kernel 已在
      init_quad 主线程预编译，执行阶段安全。
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
            overlay_image = _load_image_rgba(full_image_path, ctx.resolution)
            print(f"[QuadRenderer] 信息片段 {clip_id}: 使用默认底板图")
        else:
            print(f"[QuadRenderer] 信息片段 {clip_id}: 默认底板图不存在，跳过")
    else:  # 普通文本页
        if full_image_path and os.path.exists(full_image_path):
            overlay_image = _load_image_rgba(full_image_path, ctx.resolution)
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
        bg_reader = VideoFrameReader(bg_video_path)

        # 2. 音频（{audios_path}/bgm.mp3，no_sound 可静音）
        audio_path = None
        if not clip_config.get('no_sound', False):
            audio_path = os.path.abspath(f"{audios_path}/bgm.mp3")
            if not os.path.exists(audio_path):
                print(f"[QuadRenderer] 警告: BGM 文件不存在: {audio_path}")
                audio_path = None

        # 3. 音频响度均衡
        volume_adjust_db = 0
        if audio_path:
            measured_rms = _measure_audio_rms(audio_path, 0, duration)
            volume_adjust_db = max(-20.0, min(9.5, -20.0 - measured_rms))
            if abs(volume_adjust_db) > 0.5:
                print(f"[QuadRenderer] 音频均衡: {clip_id} 调整={volume_adjust_db:+.1f}dB")

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

        # 6. 流水线渲染（解码线程 → 主线程合成 → 编码线程）
        fade_in_frames = int(fade_in * ctx.fps) if fade_in > 0 else 0
        fade_out_frames = int(fade_out * ctx.fps) if fade_out > 0 else 0
        # bg 连续循环：从全局累计偏移处起播（跨片段连续），片段内播完再从头循环
        bg_reader.seek_to(bg_start_offset % bg_reader.duration if bg_reader.duration > 0 else 0)
        res_w, res_h = ctx.resolution

        def _decode_bg(idx):
            bg_frame = bg_reader.read_next()
            if bg_frame is None:           # 背景循环播放
                bg_reader.seek_to(0)
                bg_frame = bg_reader.read_next()
            if bg_frame is None:
                return np.zeros((res_h, res_w, 3), dtype=np.uint8)
            return resize_host(bg_frame, ctx.resolution)

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

    except Exception as e:
        print(f"[QuadRenderer] Error: {traceback.format_exc()}")
        return {"status": "error", "info": f"渲染失败: {str(e)}",
                "io": is_transient_lock_error(e)}
    finally:
        try:
            if writer is not None:
                writer.close()
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

    # 图像选择：优先 full_image（已含文字），否则 main_image（纯成绩图）
    full_image_path = clip_config.get('full_image') or ''
    main_image_path = clip_config.get('main_image') or ''
    if full_image_path and os.path.exists(full_image_path):
        overlay_image = _load_image_rgba(full_image_path, ctx.resolution)
        print(f"[QuadRenderer] 视频片段 {song_name}: 使用 full_image（已含文字）")
    elif main_image_path and os.path.exists(main_image_path):
        overlay_image = _load_image_rgba(main_image_path, ctx.resolution)
        print(f"[QuadRenderer] 视频片段 {song_name}: 使用 main_image（纯成绩图）")
    else:
        print(f"[QuadRenderer] 视频片段 {song_name}: 无有效图像，使用透明底板")
        overlay_image = np.zeros((ctx.resolution[1], ctx.resolution[0], 4), dtype=np.uint8)

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
        bg_reader = VideoFrameReader(bg_video_path)

        # 2. 谱面视频
        video_path = clip_config.get('video') or ''
        if not video_path or not os.path.exists(video_path):
            raise ValueError(f"视频文件不存在: {video_path}")
        video_reader = VideoFrameReader(video_path)

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
        volume_adjust_db = 0

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

        # 7. 流水线渲染（解码线程 → 主线程合成 → 编码线程）
        total_frames = int(duration * ctx.fps)
        fade_in_frames = int(fade_in * ctx.fps) if fade_in > 0 else 0
        fade_out_frames = int(fade_out * ctx.fps) if fade_out > 0 else 0
        bg_reader.seek_to(bg_start_offset % bg_reader.duration if bg_reader.duration > 0 else 0)
        video_reader.seek_to(start_time)
        res_w, res_h = ctx.resolution
        chart_w, chart_h = target_video_size

        # bg / chart 两路解码各自独立线程（cv2 解码/缩放释放 GIL，真并行）——
        # 此前在同一线程串行，是实测的吞吐短板（20.7ms/帧 里两路合计占满）
        def _decode_bg(idx):
            bg_frame = bg_reader.read_next()
            if bg_frame is None:
                bg_reader.seek_to(0)
                bg_frame = bg_reader.read_next()
            if bg_frame is None:
                bg_frame = np.zeros((res_h, res_w, 3), dtype=np.uint8)
            else:
                bg_frame = resize_host(bg_frame, ctx.resolution)
            return bg_frame

        last_chart = None

        def _decode_chart(idx):
            nonlocal last_chart
            chart_frame = video_reader.read_next()
            if chart_frame is None:
                # 源帧耗尽（典型：30fps 源配 60fps 输出，帧数只有一半）：
                # 重复最后一帧保持画面连续，不再黑屏补零。
                # 输出 fps 可经 encoder_param['fps'] 调低以匹配源，见 render_all_clips。
                if last_chart is None:
                    chart_frame = np.zeros((chart_h, chart_w, 3), dtype=np.uint8)
                else:
                    chart_frame = last_chart
            else:
                chart_frame = resize_host(chart_frame, target_video_size)
                last_chart = chart_frame
            return chart_frame

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

    except Exception as e:
        print(f"[QuadRenderer] Error: {traceback.format_exc()}")
        return {"status": "error", "info": f"渲染失败: {str(e)}",
                "io": is_transient_lock_error(e)}
    finally:
        try:
            if writer is not None:
                writer.close()
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
    # 输出帧率自适应：优先显式指定（encoder_param['fps']），否则探测第一个可用的
    # 谱面源视频的帧率——源是 30fps 时按 60fps 渲染等于每帧翻倍重绘+编码，
    # 纯浪费（用户反馈：有人只用 30 帧的）。探测失败回退 60。
    video_fps = int(encoder_param.get('fps') or 0)
    if video_fps <= 0:
        video_fps = 60
        for cfg in (video_configs.get('main', []) or []):
            vpath = cfg.get('video') or ''
            if vpath and os.path.exists(vpath):
                try:
                    cap = cv2.VideoCapture(vpath)
                    probed = cap.get(cv2.CAP_PROP_FPS)
                    cap.release()
                    if probed and 1 < probed <= 120:
                        video_fps = max(1, min(60, round(probed)))
                        print(f"[QuadRenderer] 输出帧率跟随源视频: {video_fps}fps（{os.path.basename(vpath)}）")
                except Exception as e:
                    print(f"[QuadRenderer] 源帧率探测失败，回退 60fps: {e}")
            break

    # 写回探测结果：SafeRender 的 CPU 回退路径要用同一个 fps 拼接（片段与
    # 拼接时间基一致，混用 quad/回退片段时不会出现帧率不一致）
    encoder_param['fps'] = video_fps

    # 编码器设计上无视页面的【使用 GPU 硬件加速】复选框（那是 CPU 路径的选项）：
    # Quadrants 渲染始终自动探测最优硬件编码器（videotoolbox→nvenc→amf→qsv），
    # 无硬件可用才落回 libx264。不要把页面写入的 encoder_param['codec'] 接进来——
    # 未勾选加速时它是 libx264，其编码线程会与 cv2 解码线程抢 CPU 核
    # （本次实测解码被拖到 27-47ms/帧）。
    ctx = RenderContext(resolution, video_fps, bitrate, style_config=style_configs)

    intro_configs = video_configs.get('intro', []) or []
    main_configs = video_configs.get('main', []) or []
    ending_configs = video_configs.get('ending', []) or []
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

    def make_cb(clip_name):
        if progress_callback is None:
            return None
        def cb(frame, total_frames, name):
            progress_callback(clip_idx, total_clips, frame, total_frames, clip_name)
        return cb

    def _render_with_retry(render_fn, config, output_file, name, kind_label, bg_start_offset=0.0):
        """片段级重试：文件占用类瞬时失败退让重试；CUDA 上下文失效则重建 GPU
        运行时后重试——避免一处故障就让整条链路降级成 CPU 全量回退。"""
        last = None
        reinited = False
        attempt = 0
        while attempt < 3:
            result = render_fn(config, ctx, output_file, make_cb(name), 0, 0,
                               bg_start_offset=bg_start_offset)
            if result.get('status') == 'success':
                return
            last = result
            info = str(result.get('info', ''))
            # CUDA 上下文一旦死亡，重试只会原地失败：先重建运行时再谈重试。
            # 重建不消耗重试名额（正常只需一次，耗时秒级）。
            if not reinited and is_cuda_context_error(info):
                reinited = True
                print(f"[QuadRenderer] {kind_label}片段 {name}: 检测到 CUDA 上下文失效，重建 GPU 运行时")
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
        if os.path.exists(output_file) and not force_render:
            print(f"[QuadRenderer] 跳过已存在: {display_name}")
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            skipped += 1
            continue
        _render_with_retry(render_info_segment, config, output_file, display_name, "开场",
                           bg_start_offset=bg_elapsed)
        bg_elapsed += float(config.get('duration', 0))
        clip_idx += 1

    # ---- main ----
    for config in main_configs:
        clip_name = config['id']
        display_name = f"{config.get('song_name', clip_name)} [{REVERSE_LEVEL_LABELS[config['level_index']]}]"
        output_file = os.path.join(video_output_path, f"{clip_idx}_{clip_name}.mp4")
        if os.path.exists(output_file) and not force_render:
            print(f"[QuadRenderer] 跳过已存在: {display_name}")
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            skipped += 1
            continue
        _render_with_retry(render_video_segment, config, output_file, display_name, "主",
                           bg_start_offset=bg_elapsed)
        bg_elapsed += float(config.get('duration', 0))
        clip_idx += 1

    # ---- ending ----
    for page_no, config in enumerate(ending_configs, start=1):
        clip_name = config['id']
        display_name = f"结尾第 {page_no} 页"
        output_file = os.path.join(video_output_path, f"{clip_idx}_{clip_name}.mp4")
        if os.path.exists(output_file) and not force_render:
            print(f"[QuadRenderer] 跳过已存在: {display_name}")
            bg_elapsed += float(config.get('duration', 0))
            clip_idx += 1
            skipped += 1
            continue
        _render_with_retry(render_info_segment, config, output_file, display_name, "结尾",
                           bg_start_offset=bg_elapsed)
        bg_elapsed += float(config.get('duration', 0))
        clip_idx += 1

    # 区分「真渲染」与「全部跳过」：后者会让整个任务在 1 秒内返回（没有任何
    # 逐帧进度），页面侧看起来就像"渲染状态窗口坏了"。如实上报，便于排查。
    rendered = clip_idx - skipped
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
