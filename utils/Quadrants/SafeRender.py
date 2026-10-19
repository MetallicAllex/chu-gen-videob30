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
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional, Set

from utils.PathUtils import TEMP_GENERATED_DIR

from .RenderIO import (get_ffmpeg_binary, detect_hw_encoder, retry_on_lock,
                       is_transient_lock_error, run_owned_complete,
                       get_active_render_job, SegmentRenderError)


def _normalize_video_audio(input_path: str, output_path: str):
    """对成片做单次 ffmpeg loudnorm 音频均衡（视频流拷贝），失败则直接用原文件。

    节选自 utils/VideoUtils-mgv.py 的 _normalize_video_audio。
    成品名被其他程序占用（常见：旧成片还在播放器里开着）时退让重试；
    重试穷尽后抛出占用类异常，由调用方判定「不回退 CPU、直接报可操作错误」。

    子进程必须登记给当前 job：这一步是整场渲染的最后一段，而它以前用的是裸
    `subprocess.run`——Popen 归 run() 私有，cancel_render 手里没有句柄，
    用户在「音频处理」阶段点取消只能等整片 loudnorm 自己跑完。这条线路其他地方
    早就为取消改用了登记通道（见 IslandConcat._run_subprocess_checked）。
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
        rc, _out, err = run_owned_complete(cmd)
        job = get_active_render_job()
        if job is not None:
            # 被取消终止的 loudnorm 返回码非零，形状和"均衡失败"一模一样：
            # 不先过这道检查点，取消会把下面那个 os.replace 执行掉——把半成品
            # 直接挂上成品名，还报"已跳过音频均衡"。
            job.check_cancelled()
        if rc != 0:
            raise RuntimeError(f"ffmpeg 返回码 {rc}：{(err or '').strip()[-300:]}")
        print(f"[SafeRender] 音频均衡化完成: {output_path}")
    except RenderCancelled:
        raise
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


# GPU 可用性对页面暴露的只读视图。**这里绝不做 GPU 初始化（CUDA/Metal/Vulkan/AMDGPU）**：Quadrants 的上下文有线程
# 亲和性（在哪个线程 init 就在哪个线程用），页面脚本线程每次刷新都是新线程，在这里探针
# 会把上下文建在错误的线程上——实测就是「渲染 4-5 个片段后死亡」那条事故的成因。
# 所以页面只看两件便宜的事：发行包里装没装齐（find_spec 不执行 import，微秒级），
# 以及工作线程上一次渲染的探针结果。
_gpu_probe_state = {'ok': None, 'reason': '', 'on_gpu': None}


def gpu_preflight() -> tuple:
    """返回 (能不能走 GPU 路, 不能走的原因)。用于决定实验按钮灰化与提示文案。

    「装了依赖」不等于「跑在 GPU 上」：init_quad 在 qd.gpu 不可用时会先尝试 Vulkan，
    两者都起不来才静静回退 qd.cpu（独显休眠/驱动不匹配都实测过）。这里把上一次渲染
    探针的真实后端也纳入判断——否则页面把按钮亮着、写着「GPU 加速」，用户点下去得到
    的是一支在 CPU 上编出来的片子。on_gpu=None 表示还没有渲染过、无从判断，此时不拦
    （首次照常尝试）。
    """
    import importlib.util
    missing = [name for name in ('quadrants', 'pydantic', 'cffi')
               if importlib.util.find_spec(name) is None]
    if missing:
        return False, (f"发行包缺少 {'、'.join(missing)}（quadrants 的传递依赖），"
                       "GPU 路起不来；现在点渲染会直接走 CPU 路径")
    if _gpu_probe_state['ok'] is False:
        return False, _gpu_probe_state['reason'] or "上次渲染的 GPU 探针失败，已回退 CPU"
    if _gpu_probe_state.get('on_gpu') is False:
        return False, ("上次渲染发现 Quadrants 只能跑在 CPU 后端（CUDA/Metal/Vulkan/AMDGPU 都没有可用的 GPU 设备，"
                       "或被 QUAD_DEVICE 强制为 CPU），"
                       "这条路不比经典路快；接上独显/更新驱动后重启应用再试。"
                       "现在点「开始渲染」会走经典 CPU 路径")
    return True, ""


# ============================================================================
# 常驻渲染工作线程
# ============================================================================
# 关键约束：Quadrants 的 GPU 上下文（CUDA/Metal/Vulkan/AMDGPU）有**线程亲和性**——运行时在哪个线程初始化，
# 就应始终在哪个线程使用。Streamlit 每次脚本运行都是新线程，如果每次渲染直接
# 起临时线程，刷新页面后的渲染就跑在与初始化不同的线程上，第一次显存分配即报
# CUDA_ERROR_INVALID_CONTEXT（两次"渲染 4-5 个片段后死亡"的事故实为此因：
# 死亡点都在页面刷新后的新一轮）。
# 因此渲染走**常驻工作线程**：首次渲染在该线程完成 init+预编译，此后所有渲染
# 复用同一线程，亲和性永远一致；页面脚本线程只负责提交任务与轮询状态。

_render_queue: "_queue.Queue" = _queue.Queue()
_render_worker_started = False
_worker_lock = threading.Lock()
# 提交侧互斥：保证「查 running → 置 running → 入队」是原子的（见 submit_render 文档）
_submit_lock = threading.Lock()


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
                    _res = render_full_video_safe(**job)
                except RenderCancelled as e:
                    RENDER_STATUS.phase = "已取消"
                    RENDER_STATUS.error = str(e)
                except Exception as e:
                    # render_full_video_safe 内部已兜底，这里只防线程级意外
                    traceback.print_exc()
                    RENDER_STATUS.phase = "失败"
                    RENDER_STATUS.error = RENDER_STATUS.error or f"{type(e).__name__}: {e}"
                else:
                    # 返回值以前整个丢掉：像「已有渲染在进行中」这类"函数正常返回、
                    # 但没成交片"的结论只有控制台看得到，浮窗那边停在初始化状态就被掐掉。
                    if isinstance(_res, dict) and _res.get('status') == 'error':
                        RENDER_STATUS.phase = "失败"
                        if _res.get('info'):
                            RENDER_STATUS.error = str(_res['info'])
                finally:
                    # 收尾顺序：先清理临时目录，**再**在提交锁内复位状态。
                    # 旧写法先无条件把 running 置 False、再慢慢 rmtree：页面恰好在这段
                    # 窗口里提交新任务时，新任务刚写进 temp_generated 的文件会被上一轮
                    # 的清理删掉。清理完再开闸，并且只在"当前任务仍是本任务"时复位，
                    # 避免迟到的收尾把新任务的 running/job 抹掉。
                    # 回退到 SegmentUtils 时会用到 temp_generated，清理其中的临时产物；
                    # 但若产物目录本身就在 temp_generated 之内（测试/特殊配置），跳过——
                    # 不能把刚渲染完的片段连带删掉
                    try:
                        # 按 __file__ 锚定，不在工作线程里按 cwd 算：这一步是 rmtree，
                        # cwd 被带偏就会删错目录。
                        _tg = TEMP_GENERATED_DIR
                        _vo = os.path.abspath(job.get('video_output_path', '') or '')
                        if not (_vo and (_vo == _tg or _vo.startswith(_tg + os.sep))):
                            import shutil
                            # 刻意不用 ignore_errors=True：ffmpeg 还握着句柄时它会把失败
                            # 抹平成"清掉了"，audio_unify 的旧副本留下次渲染去撞，而控制台
                            # 一声不响——正是页 6 那版 cleanup_after_render 已修过的静默事实。
                            try:
                                # 目录本来就不存在是正常情况（这批渲染没产生临时产物），
                                # 不该报"清理失败"——只报真的清不掉。
                                if os.path.isdir(_tg):
                                    shutil.rmtree(_tg)
                            except Exception as e:
                                print(f"[SafeRender] 清理临时渲染目录失败（不阻断收尾）："
                                      f"{type(e).__name__}: {e}｜目录：{_tg}")
                            os.makedirs(_tg, exist_ok=True)
                    except Exception as e:
                        print(f"[SafeRender] 收尾清理没执行（不阻断）：{type(e).__name__}: {e}")
                    with _submit_lock:
                        if RENDER_STATUS.job is job.get('_render_job'):
                            RENDER_STATUS.running = False
                            RENDER_STATUS.end_ts = time.time()
                            RENDER_STATUS.job = None

        threading.Thread(target=_worker_loop, name="quad-render-worker", daemon=True).start()
        _render_worker_started = True


def submit_render(**kwargs) -> bool:
    """提交渲染任务到常驻工作线程（非阻塞）。

    check-then-set 必须整个放进锁里。以前 `if RENDER_STATUS.running: return False`
    和后面的置 True 之间没有互斥，两个页签几乎同时点会双双通过检查：第二个任务
    排进队列，而第一个任务收尾的 finally 把 running 复位成 False——于是第二个任务
    在"界面认为没在跑"的状态下继续渲染，进度浮窗和「取消当前任务」都看不见它。
    """
    with _submit_lock:
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
    prefer: str = "quadrants",
    _render_job: Optional[RenderJob] = None,
) -> dict:
    """对外入口：非阻塞获取渲染互斥锁后转交实现；被占用时立即返回错误。

    prefer="classic" 走页 6「开始渲染」那条经典路（片段内烘焙淡变 + concat 流拷贝拼接），
    但同样跑在常驻工作线程里 —— 这样浏览器才有进度可轮询、取消才停得下来。
    """
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
        try:
            if prefer == "classic":
                return _render_classic(
                    video_configs, video_output_path, trans_param, encoder_param,
                    style_config, username, force_render, clips_only, job,
                )
            return _render_full_video_safe_impl(
                video_configs, video_output_path, trans_param, encoder_param,
                style_config, username, force_render, clips_only, progress_callback,
                _render_job=job,
            )
        finally:
            clear_active_render_job(job)
    finally:
        _RENDER_LOCK.release()


def _render_classic(video_configs, video_output_path, trans_param, encoder_param,
                    style_config, username, force_render, clips_only,
                    job: RenderJob) -> dict:
    """经典渲染路径，跑在常驻工作线程里（页 6 的「开始渲染」）。

    为什么要搬进线程：以前它直接在 Streamlit 脚本线程里跑，脚本不返回 → 页面整场冻结，
    浏览器里既没有进度也点不动任何东西，「取消」更无从下手（进度只存在于控制台）。
    语义与原来一致：片段内烘焙淡变（bake_fades 默认 True）+ concat 流拷贝拼接，
    不走 xfade islands，也不做loudnorm 二次编码。
    """
    from utils.SegmentUtils import render_all_video_clips, combine_full_video_direct

    RENDER_STATUS.job = job
    RENDER_STATUS.phase = "初始化"
    RENDER_STATUS.backend = "segmentutils"
    RENDER_STATUS.error = ""
    RENDER_STATUS.note = ""
    RENDER_STATUS.clip_idx = 0
    RENDER_STATUS.total_clips = 0
    RENDER_STATUS.frame = 0
    RENDER_STATUS.total_frames = 0
    RENDER_STATUS.clip_name = ""

    def _cb(done, total, name):
        job.check_cancelled()
        RENDER_STATUS.clip_idx = done
        RENDER_STATUS.total_clips = total
        RENDER_STATUS.clip_name = str(name)

    try:
        RENDER_STATUS.phase = "渲染片段（CPU）"
        failed = render_all_video_clips(
            video_configs, video_output_path, trans_param, encoder_param,
            style_config, force_render, progress=_cb,
        ) or []
        if failed:
            detail = "、".join(str(x) for x in failed[:12])
            more = f" 等 {len(failed)} 段" if len(failed) > 12 else ""
            raise RuntimeError(f"有 {len(failed)} 段没有产出文件，不拼接成片：{detail}{more}")
        if not clips_only:
            RENDER_STATUS.phase = "拼接成片"
            out = combine_full_video_direct(video_output_path, username)
            RENDER_STATUS.note = (
                # 一段都没渲（参数与素材都没变，全被指纹判为"已完成"）时必须说清原因：
                # 浮窗的「无事可渲」提示认的就是这个前缀。实测把成片路径塞进 note 会让它
                # 显示成「⚠️ 成片：…一秒结束」，看着像坏了，其实是没活可干。
                f"成片：{out}" if RENDER_STATUS.total_clips else
                "未渲染任何片段：参数与素材都没变，全部片段按渲染指纹跳过；"
                "需要重渲请勾选「覆盖已存在的视频」。"
                + ("" if clips_only else f"（成片沿用上一次的结果：{out}）")
            )
        RENDER_STATUS.phase = "完成"
        print(f"[SafeRender] 经典路径渲染完成（backend=segmentutils, 线程内）")
        return {"status": "success", "info": "经典路径渲染完成", "backend": "segmentutils"}
    except RenderCancelled:
        raise
    except Exception as e:
        RENDER_STATUS.phase = "失败"
        RENDER_STATUS.error = f"{type(e).__name__}: {e}"
        print(f"[SafeRender] 经典路径失败: {e}")
        traceback.print_exc()
        return {"status": "error", "info": str(e), "backend": "segmentutils"}


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
        from .QuadAccel import ensure_healthy_context, reinit_quad, quad_backend
        # SegmentRenderError 走模块级导入（在 RenderIO 里）：它被下面的 except 子句引用，
        # 若在这个 try 内部才导入，导入本身失败时评估 except 子句会抛 NameError 盖掉原错误
        from .QuadRenderer import render_all_clips
        from .IslandConcat import combine_full_video_xfade_islands

        # 渲染开始前先做健康探针：上一轮渲染结束后上下文可能在空闲窗口死亡
        # （实测：第一次渲染正常，第二次渲染 init 即 INVALID_CONTEXT）。探针
        # 失败时在仍在回复期的上下文上尝试重建；重建也失败才回退 CPU。
        if ensure_healthy_context():
            _gpu_probe_state['ok'] = True
            _gpu_probe_state['reason'] = ''
            # 探针通过 ≠ 在 GPU 上跑：CUDA 不可用时 init_quad 会先试 Vulkan、再回退 qd.cpu
            # （实测独显休眠后 CUDA 报 CUDA_ERROR_NO_DEVICE；无 CUDA 的机器只能靠 Vulkan）。
            # 状态与返回值都说真后端，别让进度条写着「渲染片段（GPU）」而全场在 CPU 上编。
            _backend = quad_backend()
            _on_gpu = _backend in ('cuda', 'metal', 'vulkan', 'amdgpu')
            _gpu_name = {'cuda': 'CUDA', 'metal': 'Metal',
                         'vulkan': 'Vulkan', 'amdgpu': 'AMDGPU'}.get(_backend, 'GPU')
            # 记下真实后端：页面下一次 gpu_preflight 据此决定是否还亮着「GPU 加速」。
            _gpu_probe_state['on_gpu'] = _on_gpu
            _q_label = f'Quadrants GPU（{_gpu_name}）' if _on_gpu else 'Quadrants（CPU 后端）'
            print("=" * 60)
            print(f"[SafeRender] 使用 {_q_label} 加速渲染")
            print("=" * 60)
            RENDER_STATUS.phase = (f"渲染片段（GPU·{_gpu_name}）" if _on_gpu
                                   else "渲染片段（Quadrants·CPU 后端）")
            res = render_all_clips(
                video_configs, video_output_path, encoder_param,
                trans_param, style_config, force_render, _status_cb,
            )
            if res.get('status') == 'error':
                if res.get('failed'):
                    # 缺输入素材：回退 CPU 也只是把同一段再缺一次（两条路判据与文案同源）。
                    # 已渲好的其余片段都带着指纹留在盘上，补齐素材后重跑会自动续上。
                    # 走 missing 通道而不是 io——两者都"不回退 CPU"，但给用户的结论不同。
                    raise SegmentRenderError(str(res.get('info') or '片段缺输入素材'),
                                             missing=True)
                raise RuntimeError(res.get('info'))

            # 如实记录片段渲染结果：全部已存在时会 0 秒返回「未渲染任何片段」，
            # 界面据此解释"为什么没看到进度"（否则表现得像状态窗口坏了）。
            RENDER_STATUS.note = str(res.get('info') or "")

            if not clips_only:
                RENDER_STATUS.phase = "转场拼接"
                trans_enabled = trans_param.get('enabled', True) if trans_param else True
                trans_time = trans_param.get('duration', 1.0) if (trans_param and trans_enabled) else 0
                bitrate = f"{encoder_param['bitrate']}k"
                # 拼接沿用片段渲染**实际用的那一个**编码器（QuadRenderer 选定后已写回
                # encoder_param['codec']），不再自己探一次：指纹记的、各段用的、成片
                # 重编用的必须是同一个值。fps 同理，两边共用一个读数。
                codec = encoder_param.get('codec') or detect_hw_encoder()[0]
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
            RENDER_STATUS.backend = "quadrants" if _on_gpu else "quadrants_cpu"
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
            return {"status": "success",
                    "info": f"{_q_label} 加速合成成功",
                    "backend": "quadrants" if _on_gpu else "quadrants_cpu"}
        else:
            print("[SafeRender] Quadrants 不可用，回退 SegmentUtils")
            _gpu_probe_state['ok'] = False
            _gpu_probe_state['reason'] = (
                "本次渲染的 GPU 健康探针失败（CUDA/Metal/Vulkan/AMDGPU 上下文起不来或已失效），已回退 CPU 路径；"
                "再试一次通常会在渲染前重建上下文")
    except RenderCancelled as e:
        RENDER_STATUS.phase = "已取消"
        RENDER_STATUS.error = str(e)
        RENDER_STATUS.cancel_requested = True
        raise
    except SegmentRenderError as e:
        if e.missing:
            # 缺素材与"文件被占用"要的是两种动作：一个回页面补素材，一个关掉占用程序。
            # 以前两者共用 io 通道，给用户的那句是「关闭占用该文件的程序（播放器/同步盘/
            # 杀毒扫描）」——对缺谱面视频的人完全指错方向。
            RENDER_STATUS.phase = "失败"
            RENDER_STATUS.error = str(e)
            print(f"[SafeRender] 片段缺输入素材，跳过 CPU 回退（回退也只是把同一段再缺一次）: {e}")
            return {
                "status": "error", "backend": "none",
                "info": f"{e} —— 已跳过 CPU 回退（同一段在经典路里也照样缺）。"
                        f"按上面点名的页面补齐素材后重新渲染即可，已完成片段会保留。",
            }
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
        fb_failed = render_all_video_clips(
            video_configs, video_output_path, trans_param,
            fb_encoder_param, style_config, force_render,
            bake_fades=False,
        ) or []
        if fb_failed:
            # 旧写法把返回值丢了：补渲缺了几段也照样往下拼，最后交出一支"完成"的缺半成片。
            # 这里必须把失败当终态，让浮窗与状态条报出缺哪些段，而不是继续拼接。
            detail = "、".join(str(x) for x in fb_failed[:12])
            more = f" 等 {len(fb_failed)} 段" if len(fb_failed) > 12 else ""
            raise RuntimeError(f"回退补渲有片段没产出文件：{detail}{more}")
        if not clips_only:
            RENDER_STATUS.phase = "转场拼接"
            trans_enabled = trans_param.get('enabled', True) if trans_param else True
            trans_time = trans_param.get('duration', 1.0) if (trans_param and trans_enabled) else 0
            bitrate = f"{encoder_param['bitrate']}k"
            # 回退补渲那几段的编码器由 render_all_video_clips 解析后写回
            # fb_encoder_param（中途退回软编重试时也会改成 libx264），拼接跟着它走；
            # 否则补渲段是软编、拼接却按探测结果重编，清单与实际产物又分家了。
            codec = fb_encoder_param.get('codec') or detect_hw_encoder()[0]
            video_fps = int(fb_encoder_param.get('fps') or encoder_param.get('fps') or 60)
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
