"""
QuadAccel.py - Quadrants GPU 合成计算核心

由 utils/Taichi/TaichiAccel.py 移植而来（Taichi → Quadrants）。
提供逐像素并行的图像合成 kernel 与 FrameCompositor，供 QuadRenderer 调用。

与 Taichi 版的关键差异：
1. 后端初始化用 qd.init（gpu 自动选首个 GPU，失败回退 cpu），不再有 Taichi 的
   CUDA 上下文亲和性问题，因此**丢弃 _TaichiWorkerThread / _submit_to_worker**。
2. Quadrants 强制 **kernel 编译必须在主线程**（参见 quad-docs/user_guide/quirks.md
   与参考实现 utils/Quadrants/score_material_generator-quad.py），故 init_quad()
   内做 _warmup_kernels() 预编译；后台线程只执行已编译 kernel。
3. kernel 图像参数统一用 qd.types.NDArray[dtype, ndim] + qd.ndarray 设备缓冲
   （对应 Taichi 的 ti.types.ndarray），而非 qd.field。原因：ndarray 仅按
   dtype+ndim 绑定 kernel，**更换/新建缓冲（如每片段不同尺寸的谱面帧）不会触发
   重编译**；field 则会按 shape 重编译，多片段渲染会造成重编译风暴。
   参见 quad-docs/user_guide/tensor_types.md。

帧数据约定（与 Taichi 版一致）：
- 视频/背景/谱面帧：RGB (H, W, 3) uint8
- 叠加层（成绩板/底板）：RGBA (H, W, 4) uint8，alpha 在 host 端拆为独立 2D mask
- bg_brightness：0~1 系数，在 FrameCompositor 内换算为 0~255 的**加性偏移**
"""

import os
from typing import Tuple

import cv2
import numpy as np

try:
    import quadrants as qd
    QUAD_AVAILABLE = True
except ImportError:
    QUAD_AVAILABLE = False

_quad_initialized = False
_quad_available = False


if QUAD_AVAILABLE:
    @qd.dataclass
    class _CompositeGeometry:
        """合成几何参数（host 端结构，不改变 kernel ABI）。

        记录输出尺寸与谱面摆放位置，替代散落在 __init__ 里的多个标量属性；
        将来若要把几何打包进 kernel 参数，可直接作为一个 qd.dataclass 传入。
        """
        out_w: qd.i32
        out_h: qd.i32
        chart_x: qd.i32
        chart_y: qd.i32

    @qd.kernel(fastcache=True)
    def _blend_probe_kernel(
        out: qd.types.NDArray[qd.u8, 3],
        geometry: _CompositeGeometry,
        brightness: qd.f32,
    ):
        """几何 dataclass 作为 kernel 参数的用法演示（用极小缓冲验证）。

        证明 _CompositeGeometry 可作为 kernel 参数直接传入——字段按值展开，
        零运行时开销；这是 dataclass 相对长参数列表的实际价值。
        """
        for i, j in qd.ndrange(geometry.out_h, geometry.out_w):
            out[i, j, 0] = qd.cast(qd.min(qd.max(brightness, 0.0), 255.0), qd.u8)
            out[i, j, 1] = qd.cast(geometry.chart_x, qd.u8)
            out[i, j, 2] = qd.cast(geometry.chart_y, qd.u8)


# ============================================================================
# 初始化与可用性
# ============================================================================

def init_quad(arch=None) -> bool:
    """惰性初始化 Quadrants（必须在主线程调用，会触发 kernel 预编译）。

    Args:
        arch: 显式指定后端（qd.gpu / qd.cuda / qd.vulkan / qd.cpu ...）。
              为 None 时按环境变量 QUAD_DEVICE 选择：默认 gpu，失败回退 cpu。

    Returns:
        bool: 初始化是否成功（成功后 is_available() 为 True）。
    """
    global _quad_initialized, _quad_available
    if _quad_initialized:
        return _quad_available
    if not QUAD_AVAILABLE:
        print("[QuadAccel] quadrants 未安装，GPU 加速不可用")
        _quad_available = False
        return False

    try:
        if arch is not None:
            qd.init(arch=arch)
        else:
            device = os.environ.get("QUAD_DEVICE", "gpu").lower()
            if device == "cpu":
                qd.init(qd.cpu)
                print("[QuadAccel] 初始化 CPU 模式")
            else:
                try:
                    qd.init(qd.gpu)
                    print("[QuadAccel] 初始化 GPU 模式")
                except Exception as gpu_err:
                    print(f"[QuadAccel] qd.gpu 初始化失败（{gpu_err}），回退 qd.cpu")
                    try:
                        qd.reset()
                    except Exception:
                        pass
                    qd.init(qd.cpu)
        _quad_initialized = True
        _quad_available = True
    except Exception as e:
        print(f"[QuadAccel] Quadrants 初始化失败: {e}")
        _quad_available = False
        return False

    # 主线程预编译所有 kernel（Quadrants 要求编译在主线程）
    try:
        _warmup_kernels()
    except Exception as e:
        print(f"[QuadAccel] kernel 预编译失败: {e}")
        _quad_available = False
        return False

    return True


def is_available() -> bool:
    return QUAD_AVAILABLE and _quad_initialized and _quad_available


def is_cuda_context_error(text: str) -> bool:
    """判断错误文本是否属于 CUDA 上下文级故障。

    这类故障（驱动重置 / TDR / 运行时内部错误）的特征是：上下文一旦死亡，
    后续所有 CUDA 调用都会原地失败到进程结束——原地重试毫无意义，必须重建运行时。
    """
    return ('CUDA_ERROR_INVALID_CONTEXT' in text
            or 'invalid device context' in text.lower()
            or 'CUDA_ERROR_NOT_INITIALIZED' in text
            or 'CUDA_ERROR_ILLEGAL_ADDRESS' in text)


def ensure_healthy_context() -> bool:
    """确保当前运行时可用：惰性初始化 → 轻量探针验证上下文健康 → 失效时重建。

    探针 = 真实的小块显存分配 + 同步。CUDA 上下文一旦死亡（sticky 的
    INVALID_CONTEXT），探针必然失败——此时尝试整体重建；重建成功则 GPU
    路径继续，失败则返回 False（调用方回退 CPU 路径）。
    """
    if not init_quad():
        return False
    if not is_available():
        return False
    try:
        probe = qd.ndarray(qd.u8, (8, 8, 3))
        del probe
        qd.sync()
        return True
    except Exception as e:
        print(f"[QuadAccel] CUDA 上下文探针失败（{e}），尝试重建运行时")
        return reinit_quad()


def reinit_quad() -> bool:
    """CUDA 上下文失效后的恢复入口：销毁旧运行时并完整重初始化。

    kernel 重新编译走离线缓存，通常秒级。与 init_quad 一样，只能在原初始化
    线程（Streamlit 脚本线程）调用。旧上下文分配的设备缓冲全部作废，
    缓存必须一并丢弃。
    """
    global _quad_initialized, _quad_available
    print("[QuadAccel] 正在重建 CUDA 运行时（reset + init + 预编译）...")
    try:
        qd.reset()
    except Exception as e:
        print(f"[QuadAccel] qd.reset() 异常（忽略，继续重建）: {e}")
    _quad_initialized = False
    _quad_available = False
    # 旧上下文分配的设备缓冲全部作废：池连同 resize 缓存一并丢弃
    _BUF_POOL.clear()
    _resize_buf_cache.clear()
    try:
        return init_quad()
    except Exception as e:
        print(f"[QuadAccel] CUDA 运行时重建失败: {e}")
        _quad_available = False
        return False


# ============================================================================
# Quadrants Kernels（移植自 TaichiAccel.py 的 fast 系列）
# ----------------------------------------------------------------------------
# 核心原则：每个 kernel 最外层 for 用 qd.ndrange 遍历输出像素 (i, j)，
# Quadrants 自动映射为 GPU 线程，逐像素并行。mask 作为独立 2D 数组传入，
# kernel 内不做动态 shape 分支。
# ============================================================================

if QUAD_AVAILABLE:

    @qd.kernel(fastcache=True)
    def _resize_bilinear_kernel(
        src: qd.types.NDArray[qd.f32, 3],
        out: qd.types.NDArray[qd.f32, 3],
        src_h: qd.i32, src_w: qd.i32,
        dst_h: qd.i32, dst_w: qd.i32,
    ):
        """逐像素并行双线性插值缩放（固定 3 通道）"""
        for i, j in qd.ndrange(dst_h, dst_w):
            src_y = qd.cast(i, qd.f32) * qd.cast(src_h, qd.f32) / qd.cast(dst_h, qd.f32)
            src_x = qd.cast(j, qd.f32) * qd.cast(src_w, qd.f32) / qd.cast(dst_w, qd.f32)

            y0 = qd.cast(qd.floor(src_y), qd.i32)
            x0 = qd.cast(qd.floor(src_x), qd.i32)
            y1 = qd.min(y0 + 1, src_h - 1)
            x1 = qd.min(x0 + 1, src_w - 1)

            fy = src_y - qd.cast(y0, qd.f32)
            fx = src_x - qd.cast(x0, qd.f32)

            w00 = (1.0 - fx) * (1.0 - fy)
            w01 = fx * (1.0 - fy)
            w10 = (1.0 - fx) * fy
            w11 = fx * fy

            for c in qd.static(range(3)):
                out[i, j, c] = (src[y0, x0, c] * w00 +
                                src[y0, x1, c] * w01 +
                                src[y1, x0, c] * w10 +
                                src[y1, x1, c] * w11)

    @qd.kernel(fastcache=True)
    def _resize_bilinear_4ch_kernel(
        src: qd.types.NDArray[qd.f32, 3],
        out: qd.types.NDArray[qd.f32, 3],
        src_h: qd.i32, src_w: qd.i32,
        dst_h: qd.i32, dst_w: qd.i32,
    ):
        """逐像素并行双线性插值缩放（固定 4 通道 RGBA）

        注意：Quadrants 的 NDArray 标注按 (dtype, ndim) 绑定，4 通道与 3 通道
        同为 (f32, 3)，故这里用独立的 4 通道循环体但相同的类型标注；运行时按
        传入缓冲的实际通道数访问第 4 通道。
        """
        for i, j in qd.ndrange(dst_h, dst_w):
            src_y = qd.cast(i, qd.f32) * qd.cast(src_h, qd.f32) / qd.cast(dst_h, qd.f32)
            src_x = qd.cast(j, qd.f32) * qd.cast(src_w, qd.f32) / qd.cast(dst_w, qd.f32)

            y0 = qd.cast(qd.floor(src_y), qd.i32)
            x0 = qd.cast(qd.floor(src_x), qd.i32)
            y1 = qd.min(y0 + 1, src_h - 1)
            x1 = qd.min(x0 + 1, src_w - 1)

            fy = src_y - qd.cast(y0, qd.f32)
            fx = src_x - qd.cast(x0, qd.f32)

            w00 = (1.0 - fx) * (1.0 - fy)
            w01 = fx * (1.0 - fy)
            w10 = (1.0 - fx) * fy
            w11 = fx * fy

            for c in qd.static(range(4)):
                out[i, j, c] = (src[y0, x0, c] * w00 +
                                src[y0, x1, c] * w01 +
                                src[y1, x0, c] * w10 +
                                src[y1, x1, c] * w11)

    @qd.kernel(fastcache=True)
    def _two_layer_composite_bgonly_fast_kernel(
        bg_video: qd.types.NDArray[qd.u8, 3],
        bg_brightness: qd.f32,
        out_h: qd.i32, out_w: qd.i32,
        out: qd.types.NDArray[qd.u8, 3],
    ):
        """Info 片段：纯背景（u8 加性亮度偏移）"""
        for i, j in qd.ndrange(out_h, out_w):
            # 输入为 BGR（cv2 原生），反序读取使输出仍为 RGB（免每帧 BGR→RGB 转换）
            r = qd.cast(bg_video[i, j, 2], qd.f32) + bg_brightness
            g = qd.cast(bg_video[i, j, 1], qd.f32) + bg_brightness
            b = qd.cast(bg_video[i, j, 0], qd.f32) + bg_brightness

            out[i, j, 0] = qd.cast(qd.min(r, 255.0), qd.u8)
            out[i, j, 1] = qd.cast(qd.min(g, 255.0), qd.u8)
            out[i, j, 2] = qd.cast(qd.min(b, 255.0), qd.u8)

    @qd.kernel(fastcache=True)
    def _two_layer_composite_withoverlay_fast_kernel(
        bg_video: qd.types.NDArray[qd.u8, 3],
        overlay_image: qd.types.NDArray[qd.u8, 3],
        overlay_mask: qd.types.NDArray[qd.f32, 2],
        bg_brightness: qd.f32,
        out_h: qd.i32, out_w: qd.i32,
        out: qd.types.NDArray[qd.u8, 3],
    ):
        """Info 片段：背景 + 全幅叠加层（alpha 混合）"""
        for i, j in qd.ndrange(out_h, out_w):
            # 输入为 BGR/BGRA（cv2 原生），反序读取使输出仍为 RGB
            r = qd.cast(bg_video[i, j, 2], qd.f32) + bg_brightness
            g = qd.cast(bg_video[i, j, 1], qd.f32) + bg_brightness
            b = qd.cast(bg_video[i, j, 0], qd.f32) + bg_brightness

            sa = overlay_mask[i, j]
            inv_sa = 1.0 - sa
            r = r * inv_sa + qd.cast(overlay_image[i, j, 2], qd.f32) * sa
            g = g * inv_sa + qd.cast(overlay_image[i, j, 1], qd.f32) * sa
            b = b * inv_sa + qd.cast(overlay_image[i, j, 0], qd.f32) * sa

            out[i, j, 0] = qd.cast(qd.min(r, 255.0), qd.u8)
            out[i, j, 1] = qd.cast(qd.min(g, 255.0), qd.u8)
            out[i, j, 2] = qd.cast(qd.min(b, 255.0), qd.u8)

    @qd.kernel(fastcache=True)
    def _three_layer_fast_kernel(
        bg_video: qd.types.NDArray[qd.u8, 3],
        overlay_image: qd.types.NDArray[qd.u8, 3],   # 成绩板 BGR（未预乘，cv2 原生序）
        overlay_mask: qd.types.NDArray[qd.f32, 2],   # 成绩板 alpha [0,1]
        chart_video: qd.types.NDArray[qd.u8, 3],     # 谱面视频帧（BGR）
        out: qd.types.NDArray[qd.u8, 3],
        bg_brightness: qd.f32,
        chart_x: qd.i32, chart_y: qd.i32,
        chart_w: qd.i32, chart_h: qd.i32,
        out_h: qd.i32, out_w: qd.i32,
    ):
        """Main 片段三层合成：背景(+亮度) → 成绩板(alpha 混合) → 谱面视频(硬覆盖)

        输入缓冲为 BGR / BGRA（cv2 原生顺序，省掉每帧 BGR→RGB 转换），
        kernel 内反序读取通道，输出仍为 RGB——与 FFmpegWriter 的 rgb24 输入一致。
        """
        for i, j in qd.ndrange(out_h, out_w):
            # Layer 1: 背景（加性亮度偏移）
            r = qd.cast(bg_video[i, j, 2], qd.f32) + bg_brightness
            g = qd.cast(bg_video[i, j, 1], qd.f32) + bg_brightness
            b = qd.cast(bg_video[i, j, 0], qd.f32) + bg_brightness

            # Layer 2: 成绩板（标准 alpha 混合，全幅）
            sa = overlay_mask[i, j]
            inv_sa = 1.0 - sa
            r = r * inv_sa + qd.cast(overlay_image[i, j, 2], qd.f32) * sa
            g = g * inv_sa + qd.cast(overlay_image[i, j, 1], qd.f32) * sa
            b = b * inv_sa + qd.cast(overlay_image[i, j, 0], qd.f32) * sa

            # Layer 3: 谱面视频（按位置硬覆盖，忽略其自身 alpha）
            ci = i - chart_y
            cj = j - chart_x
            if ci >= 0 and ci < chart_h and cj >= 0 and cj < chart_w:
                r = qd.cast(chart_video[ci, cj, 2], qd.f32)
                g = qd.cast(chart_video[ci, cj, 1], qd.f32)
                b = qd.cast(chart_video[ci, cj, 0], qd.f32)

            out[i, j, 0] = qd.cast(qd.min(qd.max(r, 0.0), 255.0), qd.u8)
            out[i, j, 1] = qd.cast(qd.min(qd.max(g, 0.0), 255.0), qd.u8)
            out[i, j, 2] = qd.cast(qd.min(qd.max(b, 0.0), 255.0), qd.u8)


# ============================================================================
# Host 辅助
# ============================================================================

def _split_rgba(image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """RGBA(H,W,4) → rgb(H,W,3) float32(0~255) + mask(H,W) float32[0,1]。
    RGB 输入则返回 rgb + 全 1 mask。"""
    if image.ndim == 3 and image.shape[2] == 4:
        rgb = image[:, :, :3].astype(np.float32)
        mask = image[:, :, 3].astype(np.float32) / 255.0
    elif image.ndim == 3 and image.shape[2] == 3:
        rgb = image.astype(np.float32)
        mask = np.ones((image.shape[0], image.shape[1]), dtype=np.float32)
    else:
        raise ValueError(f"Unsupported image shape: {image.shape}")
    return rgb, mask


# resize 的设备缓冲按 (src_h, src_w, dst_h, dst_w, ch) 缓存复用，
# 避免每帧重复分配 GPU 内存。
_resize_buf_cache = {}


def _get_resize_bufs(src_h, src_w, dst_h, dst_w, ch):
    key = (src_h, src_w, dst_h, dst_w, ch)
    bufs = _resize_buf_cache.get(key)
    if bufs is None:
        bufs = (qd.ndarray(qd.f32, (src_h, src_w, ch)),
                qd.ndarray(qd.f32, (dst_h, dst_w, ch)))
        _resize_buf_cache[key] = bufs
    return bufs


def resize_bilinear(image: np.ndarray, target_size: tuple) -> np.ndarray:
    """GPU 双线性插值缩放。

    ⚠ 性能警示（实测）：对 host 整帧缩放时，本函数远慢于 cv2 host 缩放——它需把
    整帧转 f32 上传 GPU 再下载结果（1080p 实测 qd~63ms vs cv2~4ms）。逐帧热路径
    应改用 resize_host()。本函数保留用于：源数据已驻留 GPU 的管线，或与 Taichi
    版保持 API parity。

    Args:
        image: (H, W, 3|4) uint8
        target_size: (target_width, target_height)
    Returns:
        缩放后 uint8，通道数与输入一致。
    """
    if not is_available():
        raise RuntimeError("Quadrants 未初始化")

    dst_w, dst_h = int(target_size[0]), int(target_size[1])
    src_h, src_w = image.shape[:2]
    channels = image.shape[2] if image.ndim == 3 else 3

    src = image.astype(np.float32)
    if src.ndim == 2:
        src = np.stack([src, src, src], axis=-1)
        channels = 3

    if channels == 4:
        src = np.ascontiguousarray(src)
        src_nd, out_nd = _get_resize_bufs(src_h, src_w, dst_h, dst_w, 4)
        src_nd.from_numpy(src)
        _resize_bilinear_4ch_kernel(src_nd, out_nd, src_h, src_w, dst_h, dst_w)
        out = out_nd.to_numpy()
    else:
        src = np.ascontiguousarray(src[:, :, :3])
        src_nd, out_nd = _get_resize_bufs(src_h, src_w, dst_h, dst_w, 3)
        src_nd.from_numpy(src)
        _resize_bilinear_kernel(src_nd, out_nd, src_h, src_w, dst_h, dst_w)
        out = out_nd.to_numpy()

    return np.clip(out, 0, 255).astype(np.uint8)


def resize_host(image: np.ndarray, target_size: tuple) -> np.ndarray:
    """Host 端 cv2 双线性缩放——逐帧热路径用这个，而非 GPU 的 resize_bilinear。

    profiling 结论：整帧缩放时 cv2 host 远快于 GPU 往返（1080p bg 实测 cv2~4.3ms
    vs qd~63ms；chart cv2~1.4ms vs qd~47ms）。GPU 只负责合成。
    若 image 已是目标尺寸则直接返回连续视图（跳过无谓缩放，如 1080p 输出下的
    1080p 背景）。支持 u8/f32、1/3/4 通道。target_size=(width, height)。
    """
    dst_w, dst_h = int(target_size[0]), int(target_size[1])
    h, w = image.shape[:2]
    if h == dst_h and w == dst_w:
        return np.ascontiguousarray(image)
    return cv2.resize(image, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)


# ============================================================================
# 设备缓冲池（跨片段复用）
# ============================================================================

# 实测问题：CUDA 上下文在渲染 ~4-5 个片段后失效（两次复现，均发生在新
# FrameCompositor 的第一次 qd.ndarray 分配处，即上一片段的设备缓冲刚被 GC
# 释放之后）。高嫌疑触发点是反复的「分配→释放」循环打崩了 stream-ordered
# 分配器的生命周期。池化后整个渲染周期只在首次用到某形状时分配一次，
# 之后零分配零释放——无论是否命中根因，都消除了这个触发模式，
# 顺带省掉每片段的分配开销。
_BUF_POOL: dict = {}


def _pooled_nd(dtype, shape, role: str = ""):
    """从设备缓冲池取（或创建）一个 (role, dtype, shape) 对应的 ndarray。

    池内缓冲被多个 FrameCompositor 实例先后复用——要求实例**串行**使用
    （当前渲染流程满足：每片段一个实例，用完才建下一个）。
    role 必须区分不同用途的缓冲（如 "bg" / "ov_rgb"）：相同 dtype+shape 但
    用途不同的缓冲绝不能共享，否则上传 overlay 会覆盖 bg。跨片段复用同一
    role 的缓冲则是安全的（每次使用前都会重新 from_numpy 上传内容）。
    reinit_quad 会清空整个池（旧上下文的缓冲随运行时一起作废）。

    防御：池内旧缓冲若来自已失效的运行时（如外部直接复位过 flags 而没走
    reinit），其内部 shape 读出来是 None——取出时校验，坏对象丢弃重建。
    """
    key = (role, dtype, tuple(shape))
    buf = _BUF_POOL.get(key)
    if buf is not None:
        try:
            if tuple(buf.shape) != tuple(shape):
                buf = None  # 形状不符（不可能，除非内部状态坏了）→ 重建
        except Exception:
            buf = None  # 连 shape 都读不出：旧运行时的死对象 → 重建
    if buf is None:
        buf = qd.ndarray(dtype, shape)
        _BUF_POOL[key] = buf
    return buf


def _pooled_tensor(dtype, shape, role: str = ""):
    """返回 qd.Tensor 包装的池化 ndarray，保持底层缓冲 ABI 不变。"""
    if not QUAD_AVAILABLE:
        raise RuntimeError("Quadrants 未安装")
    return qd.Tensor(_pooled_nd(dtype, shape, role))


# ============================================================================
# FrameCompositor（Quadrants 版）
# ============================================================================

class FrameCompositor:
    """统一帧合成器：2 层（Info 页）/ 3 层（Main 页）。

    图层结构：
    - info: 背景(+亮度) → 可选静态叠加层(alpha)
    - main: 背景(+亮度) → 成绩板(alpha) → 谱面视频(硬覆盖)

    性能要点（相对 Taichi 版的改进）：静态叠加层（成绩板/底板）作为设备缓冲
    **每片段只上传一次**；动态层（背景帧、谱面帧）每帧 from_numpy 进复用的设备
    缓冲；输出每帧 to_numpy() 下载（返回独立 host 数组，可安全跨帧持有）。

    生命周期（重要）：设备缓冲全部来自类级 _BUF_POOL，跨实例复用——因此实例
    必须**串行**使用（渲染流程天然满足）；叠加层/谱面内容变化时用 from_numpy
    重新上传到池内缓冲，不重新分配。
    """

    def __init__(
        self,
        mode: str = "main",                 # "main" 或 "info"
        bg_video: np.ndarray = None,        # 背景帧 (H, W, 3) uint8（占位/首帧）
        bg_brightness: float = 0.8,
        output_size: tuple = (1920, 1080),
        score_layer: np.ndarray = None,     # main: 成绩板 RGBA (H, W, 4)
        chart_video_pos: tuple = (0, 0),    # main: 谱面视频位置 (x, y)
        overlay_image: np.ndarray = None,   # info: 静态叠加层 RGBA (H, W, 4)，可选
    ):
        if not is_available():
            raise RuntimeError("Quadrants 未初始化")

        self.mode = mode
        self.out_w, self.out_h = int(output_size[0]), int(output_size[1])
        # 0~1 系数 → 0~255 加性偏移（与 Taichi fast kernel 语义一致）
        self.bg_brightness = float(bg_brightness * 255.0)

        if mode == "main":
            if score_layer is None:
                raise ValueError("main 模式需要 score_layer 参数")
            if bg_video is None:
                raise ValueError("main 模式需要 bg_video 参数")
        elif mode == "info":
            if bg_video is None:
                raise ValueError("info 模式需要 bg_video 参数")
        else:
            raise ValueError(f"未知模式: {mode}，支持 'main' 或 'info'")

        self._geometry = _CompositeGeometry(
            out_w=self.out_w,
            out_h=self.out_h,
            chart_x=int(chart_video_pos[0]) if mode == "main" else 0,
            chart_y=int(chart_video_pos[1]) if mode == "main" else 0,
        )

        # qd.Tensor 包装池化 ndarray，保留底层缓冲 ABI 与跨片段生命周期。
        self._out_tensor = _pooled_tensor(qd.u8, (self.out_h, self.out_w, 3), "out")
        self._bg_tensor = _pooled_tensor(qd.u8, (self.out_h, self.out_w, 3), "bg")
        self._out_nd = self._out_tensor._unwrap()
        self._bg_nd = self._bg_tensor._unwrap()

        bg_u8 = self._prepare_bg(bg_video)
        self._bg_nd.from_numpy(bg_u8)

        # ---- 谱面缓冲（main，懒创建：尺寸随源视频而变）----
        self._chart_nd = None
        self._chart_shape = None

        if mode == "main":
            self.chart_x, self.chart_y = int(chart_video_pos[0]), int(chart_video_pos[1])
            rgb_u8, mask_f32 = self._prepare_overlay(score_layer)
            self._overlay_rgb_nd = _pooled_nd(qd.u8, (self.out_h, self.out_w, 3), "ov_rgb")
            self._overlay_mask_nd = _pooled_nd(qd.f32, (self.out_h, self.out_w), "ov_mask")
            self._overlay_rgb_nd.from_numpy(rgb_u8)
            self._overlay_mask_nd.from_numpy(mask_f32)
        else:  # info
            self.has_overlay = overlay_image is not None
            if self.has_overlay:
                rgb_u8, mask_f32 = self._prepare_overlay(overlay_image)
                self._overlay_rgb_nd = _pooled_nd(qd.u8, (self.out_h, self.out_w, 3), "ov_rgb")
                self._overlay_mask_nd = _pooled_nd(qd.f32, (self.out_h, self.out_w), "ov_mask")
                self._overlay_rgb_nd.from_numpy(rgb_u8)
                self._overlay_mask_nd.from_numpy(mask_f32)
            else:
                self._overlay_rgb_nd = None
                self._overlay_mask_nd = None

    # ---- host 端预处理 ----

    def _prepare_bg(self, bg_frame: np.ndarray) -> np.ndarray:
        """背景帧 → 输出尺寸的连续 u8 数组（host 端 cv2 缩放）。"""
        bg_u8 = bg_frame[:, :, :3]
        bg_u8 = resize_host(bg_u8, (self.out_w, self.out_h))
        return np.ascontiguousarray(bg_u8, dtype=np.uint8)

    def _prepare_overlay(self, layer: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """叠加层 RGBA → (rgb u8 连续, mask f32 连续)，必要时缩放到输出尺寸。

        缩放走 host cv2；mask 直接以 f32 缩放，避免 u8 量化损失 alpha 精度。
        """
        rgb, mask = _split_rgba(layer)  # rgb: f32(0~255), mask: f32[0,1]
        if rgb.shape[0] != self.out_h or rgb.shape[1] != self.out_w:
            rgb = resize_host(rgb, (self.out_w, self.out_h))      # f32 直接缩放
            mask = resize_host(mask, (self.out_w, self.out_h))    # f32，无量化
        rgb_u8 = np.ascontiguousarray(np.clip(rgb, 0, 255).astype(np.uint8))
        mask_f32 = np.ascontiguousarray(mask.astype(np.float32))
        return rgb_u8, mask_f32

    # ---- 每帧更新 ----

    def update_bg(self, bg_frame: np.ndarray):
        """更新背景帧（所有模式通用）。bg_frame 应已是输出尺寸。"""
        bg_u8 = self._prepare_bg(bg_frame)
        self._bg_nd.from_numpy(bg_u8)

    def update_score_layer(self, score_layer: np.ndarray):
        """更新成绩板（仅 main）。一般整段静态，无需每帧调用。"""
        if self.mode != "main":
            raise RuntimeError("update_score_layer 仅支持 main 模式")
        rgb_u8, mask_f32 = self._prepare_overlay(score_layer)
        self._overlay_rgb_nd.from_numpy(rgb_u8)
        self._overlay_mask_nd.from_numpy(mask_f32)

    def update_overlay(self, overlay_image: np.ndarray):
        """更新叠加层（仅 info）。"""
        if self.mode != "info":
            raise RuntimeError("update_overlay 仅支持 info 模式")
        self.has_overlay = overlay_image is not None
        if self.has_overlay:
            rgb_u8, mask_f32 = self._prepare_overlay(overlay_image)
            if self._overlay_rgb_nd is None:
                self._overlay_rgb_nd = _pooled_nd(qd.u8, (self.out_h, self.out_w, 3), "ov_rgb")
                self._overlay_mask_nd = _pooled_nd(qd.f32, (self.out_h, self.out_w), "ov_mask")
            self._overlay_rgb_nd.from_numpy(rgb_u8)
            self._overlay_mask_nd.from_numpy(mask_f32)

    def _ensure_chart_buf(self, chart_u8: np.ndarray):
        shape = chart_u8.shape
        if self._chart_nd is None or self._chart_shape != shape:
            self._chart_nd = _pooled_nd(qd.u8, shape, "chart")
            self._chart_shape = shape

    def composite(self, chart_frame: np.ndarray = None) -> np.ndarray:
        """合成一帧，返回 (H, W, 3) uint8 host 数组（独立副本，可安全持有）。"""
        if self.mode == "main":
            return self._composite_main(chart_frame)
        return self._composite_info()

    def _composite_main(self, chart_frame: np.ndarray) -> np.ndarray:
        if chart_frame is None:
            raise ValueError("main 模式需要 chart_frame 参数")
        chart_u8 = np.ascontiguousarray(chart_frame[:, :, :3], dtype=np.uint8)
        chart_h, chart_w = chart_u8.shape[:2]
        self._ensure_chart_buf(chart_u8)
        self._chart_nd.from_numpy(chart_u8)

        _three_layer_fast_kernel(
            self._bg_nd,
            self._overlay_rgb_nd,
            self._overlay_mask_nd,
            self._chart_nd,
            self._out_nd,
            self.bg_brightness,
            self.chart_x, self.chart_y,
            chart_w, chart_h,
            self.out_h, self.out_w,
        )
        return self._out_nd.to_numpy()

    def _composite_info(self) -> np.ndarray:
        if self.has_overlay:
            _two_layer_composite_withoverlay_fast_kernel(
                self._bg_nd,
                self._overlay_rgb_nd,
                self._overlay_mask_nd,
                self.bg_brightness,
                self.out_h, self.out_w,
                self._out_nd,
            )
        else:
            _two_layer_composite_bgonly_fast_kernel(
                self._bg_nd,
                self.bg_brightness,
                self.out_h, self.out_w,
                self._out_nd,
            )
        return self._out_nd.to_numpy()


# ============================================================================
# Kernel 预编译（主线程）
# ============================================================================

def _warmup_kernels():
    """用极小 dummy 数据触发所有 kernel 编译（必须在主线程）。

    Quadrants 的 kernel 编译只能在主线程进行；预编译后后台线程只执行。
    参考 utils/Quadrants/score_material_generator-quad.py 的 _warmup_kernels。
    """
    print("[QuadAccel] 预编译 kernels...")
    sh, sw = 4, 4
    dh, dw = 2, 2

    # resize（3ch / 4ch）
    src3 = qd.ndarray(qd.f32, (sh, sw, 3)); src3.from_numpy(np.zeros((sh, sw, 3), np.float32))
    dst3 = qd.ndarray(qd.f32, (dh, dw, 3))
    _resize_bilinear_kernel(src3, dst3, sh, sw, dh, dw)
    src4 = qd.ndarray(qd.f32, (sh, sw, 4)); src4.from_numpy(np.zeros((sh, sw, 4), np.float32))
    dst4 = qd.ndarray(qd.f32, (dh, dw, 4))
    _resize_bilinear_4ch_kernel(src4, dst4, sh, sw, dh, dw)

    # 合成 kernel
    bg = qd.ndarray(qd.u8, (dh, dw, 3)); bg.from_numpy(np.zeros((dh, dw, 3), np.uint8))
    ov = qd.ndarray(qd.u8, (dh, dw, 3)); ov.from_numpy(np.zeros((dh, dw, 3), np.uint8))
    mk = qd.ndarray(qd.f32, (dh, dw)); mk.from_numpy(np.zeros((dh, dw), np.float32))
    chart = qd.ndarray(qd.u8, (2, 2, 3)); chart.from_numpy(np.zeros((2, 2, 3), np.uint8))
    out = qd.ndarray(qd.u8, (dh, dw, 3))

    _two_layer_composite_bgonly_fast_kernel(bg, 0.0, dh, dw, out)
    _two_layer_composite_withoverlay_fast_kernel(bg, ov, mk, 0.0, dh, dw, out)
    _three_layer_fast_kernel(bg, ov, mk, chart, out, 0.0, 0, 0, 2, 2, dh, dw)

    qd.sync()
    print("[QuadAccel] kernel 预编译完成 [OK]")
