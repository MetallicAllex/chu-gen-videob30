"""
SafeRender.py - 安全渲染入口（Quadrants 优先，失败优雅回退 SegmentUtils）

体现「安全接入」而非「盲目接入」：
- 先尝试 Quadrants GPU 加速：init_quad → render_all_clips → island 低内存拼接 → loudnorm。
- 任一步抛异常 / Quadrants 不可用 → 打印 traceback 并回退到现有 proven 路径
  utils.SegmentUtils（render_all_video_clips + combine_full_video_direct）。

回退时强制 force_render，覆盖 Quadrants 可能产生的半成品片段，保证回退输出自洽
（SegmentUtils 片段含烘焙淡入淡出 + 普通 concat）。回退仅在失败时触发，重渲染可接受。

本模块**不修改任何页面**；将来接线只需把 6_Compostie_Videos.py 的
render_all_video_clips(...) + combine_full_video_direct(...) 两行换成
render_full_video_safe(...)。
"""

import os
import queue as _queue
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional, Set

from .RenderIO import (get_ffmpeg_binary, detect_hw_encoder, retry_on_lock,
                       is_transient_lock_error)


def _normalize_video_audio(input_path: str, output_path: str):
    """对成片做单次 ffmpeg loudnorm 音频均衡（视频流拷贝），失败则直接用原文件。

    节选自 utils/VideoUtils-mgv.py 的 _normalize_video_audio。
    成品名被其他程序占用（常见：旧成片还在播放器里开着）时退让重试；
    重试穷尽后抛出占用类异常，由调用方判定「不回退 CPU、直接报可操作错误」。
    """
    if os.path.exists(output_path):
        retry_on_lock(lambda: os.remove(output_path),
                      what=f"清理旧成片 {os.path.basename(output_path)}")
    try:
        cmd = [
            get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning',
            '-i', input_path,
            '-c:v', 'copy',
            '-af', 'loudnorm=I=-20:TP=-1.5:LRA=11,aresample=48000:first_pts=0,asetpts=N/SR/TB',
            '-c:a', 'aac', '-b:a', '192k',
            '-ar', '48000',
            output_path
        ]
        subprocess.run(cmd, check=True)
        print(f"[SafeRender] 音频均衡化完成: {output_path}")
    except Exception as e:
        print(f"[SafeRender] Warning: 音频均衡化失败 ({e})，尝试直接使用拼接结果")
        # 均衡失败也要把拼接结果落到成品名上；目标被占用时重试后仍失败则上抛，
        # 绝不能在这条路径上静默吞掉——否则用户拿到的成片缺了最后一步还不知情
        retry_on_lock(lambda: os.replace(input_path, output_path),
                      what=f"落盘成片 {os.path.basename(output_path)}")
        print(f"[SafeRender] 已跳过音频均衡，直接使用拼接结果: {output_path}")
        return
    # 均衡成功后清理中间产物；失败不影响成片
    try:
        if os.path.exists(input_path) and input_path != output_path:
            os.remove(input_path)
    except OSError as e:
        print(f"[SafeRender] Warning: 清理中间文件失败（不影响成片）: {e}")


# 进程级渲染互斥：同一应用同时只允许一个渲染任务。防止双页签/刷新重入时
# 两路渲染写同一批片段文件——实测会造成同一片段两路并发、tmp 互踩、成品被
# 另一路的 ffmpeg 长时间锁住。注意：刷新页面并不能终止后台渲染（渲染循环里
# 没有 Streamlit 中断点），被拒时提示等待是正确行为而非 bug。
_RENDER_LOCK = threading.Lock()


class RenderCancelled(RuntimeError):
    """当前 job_id 被用户取消。"""


@dataclass
class RenderJob:
    job_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    children: Set[object] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def register_child(self, process):
        with self.lock:
            self.children.add(process)
        if self.cancel_event.is_set():
            _terminate_owned_process(process)

    def unregister_child(self, process):
        with self.lock:
            self.children.discard(process)

    def cancel(self):
        self.cancel_event.set()
        with self.lock:
            children = list(self.children)
        for process in children:
            _terminate_owned_process(process)

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise RenderCancelled(f"渲染任务 {self.job_id} 已取消")


def _terminate_owned_process(process):
    """只终止当前 RenderJob 登记的 Popen 对象，不按进程名搜索/查杀。"""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        except Exception:
            pass


@dataclass
class RenderStatus:
    """渲染任务状态：后台渲染线程写、页面脚本线程轮询读。

    字段赋值在 GIL 下是原子的，展示用途无需加锁；页面用 snapshot() 取快照。
    running 的生命周期由启动渲染的线程持有。
    """
    running: bool = False
    phase: str = ""            # 初始化/渲染片段/回退渲染/转场拼接/音频处理/完成/失败
    backend: str = ""          # quadrants / segmentutils / none
    clip_idx: int = 0
    total_clips: int = 0
    frame: int = 0
    total_frames: int = 0
    clip_name: str = ""
    start_ts: float = 0.0
    end_ts: float = 0.0
    error: str = ""
    note: str = ""             # 结果补充说明（如「全部片段已存在，未重新渲染」）
    job_id: str = ""
    cancel_requested: bool = False
    job: Optional[RenderJob] = None

    def snapshot(self) -> dict:
        return {
            'running': self.running, 'phase': self.phase, 'backend': self.backend,
            'clip_idx': self.clip_idx, 'total_clips': self.total_clips,
            'frame': self.frame, 'total_frames': self.total_frames,
            'clip_name': self.clip_name, 'start_ts': self.start_ts,
            'end_ts': self.end_ts, 'error': self.error, 'note': self.note,
            'job_id': self.job_id, 'cancel_requested': self.cancel_requested,
        }


RENDER_STATUS = RenderStatus()


# ============================================================================
# 常驻渲染工作线程
# ============================================================================
# 关键约束：Quadrants 的 CUDA 上下文有**线程亲和性**——运行时在哪个线程初始化，
# 就应始终在哪个线程使用。Streamlit 每次脚本运行都是新线程，如果每次渲染直接
# 起临时线程，刷新页面后的渲染就跑在与初始化不同的线程上，第一次显存分配即报
# CUDA_ERROR_INVALID_CONTEXT（两次"渲染 4-5 个片段后死亡"的事故实为此因：
# 死亡点都在页面刷新后的新一轮）。
# 因此渲染走**常驻工作线程**：首次渲染在该线程完成 init+预编译，此后所有渲染
# 复用同一线程，亲和性永远一致；页面脚本线程只负责提交任务与轮询状态。

_render_queue: "_queue.Queue" = _queue.Queue()
_render_worker_started = False
_worker_lock = threading.Lock()


def _ensure_render_worker():
    """惰性启动常驻渲染线程（整个进程只启动一次）。"""
    global _render_worker_started
    with _worker_lock:
        if _render_worker_started:
            return

        def _worker_loop():
            while True:
                job = _render_queue.get()
                if job is None:
                    return
                try:
                    render_full_video_safe(**job)
                except RenderCancelled as e:
                    RENDER_STATUS.phase = "已取消"
                    RENDER_STATUS.error = str(e)
                except Exception:
                    # render_full_video_safe 内部已兜底，这里只防线程级意外
                    traceback.print_exc()
                finally:
                    RENDER_STATUS.running = False
                    RENDER_STATUS.end_ts = time.time()
                    RENDER_STATUS.job = None
                    # 回退到 SegmentUtils 时会用到 temp_generated，清理其中的临时产物；
                    # 但若产物目录本身就在 temp_generated 之内（测试/特殊配置），跳过——
                    # 不能把刚渲染完的片段连带删掉
                    try:
                        _tg = os.path.abspath('./videos/temp_generated')
                        _vo = os.path.abspath(job.get('video_output_path', '') or '')
                        if not (_vo and (_vo == _tg or _vo.startswith(_tg + os.sep))):
                            import shutil
                            shutil.rmtree(_tg, ignore_errors=True)
                            os.makedirs(_tg, exist_ok=True)
                    except Exception:
                        pass

        threading.Thread(target=_worker_loop, name="quad-render-worker", daemon=True).start()
        _render_worker_started = True


def submit_render(**kwargs) -> bool:
    """提交渲染任务到常驻工作线程（非阻塞）。"""
    if RENDER_STATUS.running:
        return False
    _ensure_render_worker()
    job = RenderJob(uuid.uuid4().hex)
    kwargs['_render_job'] = job
    RENDER_STATUS.running = True
    RENDER_STATUS.phase = "初始化"
    RENDER_STATUS.backend = ""
    RENDER_STATUS.error = ""
    RENDER_STATUS.note = ""
    RENDER_STATUS.cancel_requested = False
    RENDER_STATUS.job_id = job.job_id
    RENDER_STATUS.job = job
    RENDER_STATUS.clip_idx = 0
    RENDER_STATUS.total_clips = 0
    RENDER_STATUS.frame = 0
    RENDER_STATUS.total_frames = 0
    RENDER_STATUS.clip_name = ""  # 清掉上一任务的残留名，避免新任务初始化窗口显示旧片段
    RENDER_STATUS.start_ts = time.time()
    RENDER_STATUS.end_ts = 0.0
    _render_queue.put(dict(kwargs))
    return True


def cancel_render(job_id: str) -> bool:
    """取消指定 job_id；只操作该任务登记的子进程，不按名称查杀。"""
    job = RENDER_STATUS.job
    if not RENDER_STATUS.running or job is None or job.job_id != job_id:
        return False
    RENDER_STATUS.cancel_requested = True
    RENDER_STATUS.phase = "取消中"
    job.cancel()
    return True


def render_full_video_safe(
    video_configs: dict,
    video_output_path: str,
    trans_param: dict,
    encoder_param: dict,
    style_config: dict,
    username: str,
    force_render: bool = False,
    clips_only: bool = False,
    progress_callback=None,
    _render_job: Optional[RenderJob] = None,
) -> dict:
    """对外入口：非阻塞获取渲染互斥锁后转交实现；被占用时立即返回错误。"""
    job = _render_job or RenderJob(uuid.uuid4().hex)
    job.check_cancelled()
    if not _RENDER_LOCK.acquire(blocking=False):
        print("[SafeRender] 拒绝渲染：已有渲染任务在进行中")
        return {
            "status": "error", "backend": "none",
            "info": "已有渲染在进行中（同一应用同时只允许一个渲染任务）。"
                    "刷新页面不会终止后台渲染——等控制台出现「渲染完成/失败」"
                    "字样后再点击重试；若确认无渲染在跑，重启应用可复位。",
        }
    try:
        from .RenderIO import set_active_render_job, clear_active_render_job
        set_active_render_job(job)
        return _render_full_video_safe_impl(
            video_configs, video_output_path, trans_param, encoder_param,
            style_config, username, force_render, clips_only, progress_callback,
            _render_job=job,
        )
    finally:
        try:
            from .RenderIO import clear_active_render_job
            clear_active_render_job(job)
        finally:
            _RENDER_LOCK.release()


def _render_full_video_safe_impl(
    video_configs: dict,
    video_output_path: str,
    trans_param: dict,
    encoder_param: dict,
    style_config: dict,
    username: str,
    force_render: bool = False,
    clips_only: bool = False,
    progress_callback=None,
    _render_job: Optional[RenderJob] = None,
) -> dict:
    """安全渲染完整视频：Quadrants GPU 优先，失败回退 SegmentUtils。

    Args:
        video_configs:    {'intro': [...], 'main': [...], 'ending': [...]}
        video_output_path:片段与成片输出目录
        trans_param:      {'enabled': bool, 'duration': float}
        encoder_param:    {'resolution': (w,h), 'bitrate': int(kbps), ...}
        style_config:     customization.json 内容
        username:         用于成片命名 {username}_Best50.mp4
        force_render:     覆盖已存在片段
        clips_only:       只渲染逐片段，不拼接成片
        progress_callback:(clip_idx, total_clips, frame, total_frames, clip_name)

    Returns:
        {'status': 'success'|'error', 'info': str, 'backend': 'quadrants'|'segmentutils'}

    状态上报：全过程更新模块级 RENDER_STATUS（phase / 逐帧进度 / 最终结果），
    供页面后台渲染时轮询显示。传入的 progress_callback 若非 None 也会同时回调。
    """
    job = _render_job or RenderJob(uuid.uuid4().hex)
    _render_job = job
    job.check_cancelled()
    RENDER_STATUS.job = job
    RENDER_STATUS.phase = "初始化"
    RENDER_STATUS.backend = ""
    RENDER_STATUS.error = ""
    RENDER_STATUS.cancel_requested = False
    RENDER_STATUS.clip_idx = 0
    RENDER_STATUS.total_clips = 0
    RENDER_STATUS.frame = 0
    RENDER_STATUS.total_frames = 0
    RENDER_STATUS.clip_name = ""

    def _status_cb(clip_idx, total_clips, frame, total_frames, clip_name):
        job.check_cancelled()
        RENDER_STATUS.clip_idx = clip_idx
        RENDER_STATUS.total_clips = total_clips
        RENDER_STATUS.frame = frame
        RENDER_STATUS.total_frames = total_frames
        RENDER_STATUS.clip_name = clip_name

    # ========== 1) 优先尝试 Quadrants GPU 加速 ==========
    try:
        from .QuadAccel import ensure_healthy_context, reinit_quad
        from .QuadRenderer import render_all_clips, SegmentRenderError
        from .IslandConcat import combine_full_video_xfade_islands

        # 渲染开始前先做健康探针：上一轮渲染结束后上下文可能在空闲窗口死亡
        # （实测：第一次渲染正常，第二次渲染 init 即 INVALID_CONTEXT）。探针
        # 失败时在仍在回复期的上下文上尝试重建；重建也失败才回退 CPU。
        if ensure_healthy_context():
            print("=" * 60)
            print("[SafeRender] 使用 Quadrants GPU 加速渲染")
            print("=" * 60)
            RENDER_STATUS.phase = "渲染片段（GPU）"
            res = render_all_clips(
                video_configs, video_output_path, encoder_param,
                trans_param, style_config, force_render, _status_cb,
            )
            if res.get('status') == 'error':
                raise RuntimeError(res.get('info'))

            # 如实记录片段渲染结果：全部已存在时会 0 秒返回「未渲染任何片段」，
            # 界面据此解释"为什么没看到进度"（否则表现得像状态窗口坏了）。
            RENDER_STATUS.note = str(res.get('info') or "")

            if not clips_only:
                RENDER_STATUS.phase = "转场拼接"
                trans_enabled = trans_param.get('enabled', True) if trans_param else True
                trans_time = trans_param.get('duration', 1.0) if (trans_param and trans_enabled) else 0
                bitrate = f"{encoder_param['bitrate']}k"
                # 与片段渲染同为自动探测——Quadrants 路径设计上无视【使用 GPU 加速】
                # 复选框，始终选最优可用编码器；fps 一并传递，避免拼接与片段的
                # 时间基假设不一致
                codec, _ = detect_hw_encoder()
                video_fps = int(encoder_param.get('fps') or 60)
                island_out = combine_full_video_xfade_islands(
                    video_output_path, trans_time=trans_time, codec=codec,
                    bitrate=bitrate, video_fps=video_fps,
                )
                RENDER_STATUS.phase = "音频处理"
                final_path = os.path.join(video_output_path, f"{username}_Best50.mp4")
                _normalize_video_audio(island_out, final_path)
                print(f"[SafeRender] Quadrants 成片完成: {final_path}")

            RENDER_STATUS.phase = "完成"
            RENDER_STATUS.backend = "quadrants"
            if progress_callback:
                progress_callback(RENDER_STATUS.total_clips, RENDER_STATUS.total_clips,
                                  RENDER_STATUS.total_frames, RENDER_STATUS.total_frames,
                                  "全部片段")
            # 渲染一结束就主动重建运行时：此刻上下文必然存活（全部 GPU 工作
            # 刚成功完成），reset+init 必然成功——为下一次渲染提供全新上下文，
            # 规避实测的确定性故障「第一次渲染正常，第二次渲染 init 即
            # INVALID_CONTEXT」（上下文死于两次渲染之间的空闲窗口，且死后
            # 连 reset 都无法完成，进程内无解；趁健康时换新是唯一可靠解）。
            try:
                reinit_quad()
            except Exception as e:
                print(f"[SafeRender] Warning: 渲染后重建运行时失败（不影响本次成片）: {e}")
            return {"status": "success", "info": "Quadrants GPU 加速合成成功", "backend": "quadrants"}
        else:
            print("[SafeRender] Quadrants 不可用，回退 SegmentUtils")
    except RenderCancelled as e:
        RENDER_STATUS.phase = "已取消"
        RENDER_STATUS.error = str(e)
        RENDER_STATUS.cancel_requested = True
        raise
    except SegmentRenderError as e:
        if e.io:
            # 文件占用类错误回退 CPU 也会撞同一把锁，全量重渲只是白烧几分钟：
            # 直接报可操作错误。已成功渲染的片段保留（下次运行按存在性跳过）。
            RENDER_STATUS.phase = "失败"
            RENDER_STATUS.error = str(e)
            print(f"[SafeRender] 片段渲染因文件占用失败，跳过 CPU 回退: {e}")
            return {
                "status": "error", "backend": "none",
                "info": f"{e} —— 文件被其他程序占用，已跳过 CPU 回退。"
                        f"关闭占用该文件的程序（播放器/同步盘/杀毒扫描）后重新渲染即可，"
                        f"已完成片段会保留。",
            }
        print(f"[SafeRender] Quadrants 片段渲染失败，回退 SegmentUtils: {e}")
        traceback.print_exc()
    except Exception as e:
        if is_transient_lock_error(e):
            RENDER_STATUS.phase = "失败"
            RENDER_STATUS.error = str(e)
            print(f"[SafeRender] 文件占用类错误，跳过 CPU 回退（回退会撞同一把锁）: {e}")
            return {
                "status": "error", "backend": "none",
                "info": f"{e} —— 文件被其他程序占用，已跳过 CPU 回退。"
                        f"关闭占用该文件的程序（播放器/同步盘/杀毒扫描）后重新渲染即可。",
            }
        print(f"[SafeRender] Quadrants 渲染失败，回退 SegmentUtils: {e}")
        traceback.print_exc()

    # ========== 2) 回退：现有 proven 路径（SegmentUtils）==========
    print("=" * 60)
    print("[SafeRender] 回退 CPU/SegmentUtils 渲染路径")
    print("=" * 60)
    RENDER_STATUS.phase = "回退渲染（CPU，无逐帧进度）"
    try:
        from utils.SegmentUtils import render_all_video_clips
        from .IslandConcat import combine_full_video_xfade_islands

        # 防御性补全 SegmentUtils 强依赖的键（页面通常已提供；用浅拷贝避免污染调用方字典）
        fb_encoder_param = dict(encoder_param)
        fb_encoder_param.setdefault('hwaccel', False)
        fb_encoder_param.setdefault('brand', None)

        # 沿用页面的覆盖选择：quad 片段经临时名+原子替换落盘，磁盘上的必然是
        # 完整产物，跳过已存在是安全的（旧版硬编码 True 是为覆盖 GPU 半成品，
        # 该前提已不成立——曾经导致回退时已完成的片段被全量重渲）。
        if not force_render:
            print("[SafeRender] force_render=False：跳过已存在片段，只补渲染缺失部分")
        # 与 quad 路径一致：片段不烘焙转场（bake_fades=False），拼接阶段统一 xfade——
        # 回退补渲的片段与已存在的 GPU 片段过渡风格一致
        render_all_video_clips(
            video_configs, video_output_path, trans_param,
            fb_encoder_param, style_config, force_render,
            bake_fades=False,
        )
        if not clips_only:
            RENDER_STATUS.phase = "转场拼接"
            trans_enabled = trans_param.get('enabled', True) if trans_param else True
            trans_time = trans_param.get('duration', 1.0) if (trans_param and trans_enabled) else 0
            bitrate = f"{encoder_param['bitrate']}k"
            codec, _ = detect_hw_encoder()
            video_fps = int(encoder_param.get('fps') or 60)
            island_out = combine_full_video_xfade_islands(
                video_output_path, trans_time=trans_time, codec=codec,
                bitrate=bitrate, video_fps=video_fps,
            )
            RENDER_STATUS.phase = "音频处理"
            final_path = os.path.join(video_output_path, f"{username}_Best50.mp4")
            _normalize_video_audio(island_out, final_path)
            print(f"[SafeRender] 回退成片完成: {final_path}")
        RENDER_STATUS.phase = "完成"
        RENDER_STATUS.backend = "segmentutils"
        # CPU 回退路径也顺手重建 GPU 运行时：若上下文只是闲置后失效（而非死亡），
        # 重建让下一次渲染能继续走 GPU；若上下文已真死，重建失败仅打警告，
        # 下一次渲染的 ensure_healthy_context 会再次尝试并按结果分流。
        try:
            from .QuadAccel import reinit_quad
            reinit_quad()
        except Exception as e:
            print(f"[SafeRender] Warning: 回退渲染后重建 GPU 运行时失败（不影响本次成片）: {e}")
        return {"status": "success", "info": "已回退 CPU/SegmentUtils 合成", "backend": "segmentutils"}
    except Exception as e:
        RENDER_STATUS.phase = "失败"
        RENDER_STATUS.error = f"Quadrants 与 SegmentUtils 均失败: {e}"
        print(f"[SafeRender] 回退路径同样失败: {e}")
        traceback.print_exc()
        return {"status": "error", "info": f"Quadrants 与 SegmentUtils 均失败: {e}", "backend": "none"}
