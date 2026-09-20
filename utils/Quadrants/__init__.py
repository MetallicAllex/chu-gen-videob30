"""
utils.Quadrants - Quadrants GPU 视频渲染模块（Taichi → Quadrants 迁移）

自包含、可导入。公共入口：

    from utils.Quadrants import render_full_video_safe
    render_full_video_safe(video_configs, video_output_path, trans_param,
                           encoder_param, style_config, username, ...)

渲染策略：Quadrants GPU 优先，失败优雅回退到现有 utils.SegmentUtils（CPU/ffmpeg）。
本模块不修改任何页面；接线方式见 SafeRender.render_full_video_safe 文档。

子模块：
- QuadAccel    : Quadrants 合成 kernel + FrameCompositor（移植自 Taichi/TaichiAccel.py）
- RenderIO     : 帧读取 / FFmpegWriter / 编码器探测（框架无关，移植自 Taichi/AccelRenderer2.py）
- QuadRenderer : 逐片段渲染编排（info / main / 批量）
- IslandConcat : transition-island 低内存拼接（节选自 VideoUtils-mgv.py）
- SafeRender   : 安全入口（Quadrants 优先 + 回退 SegmentUtils）

注意：导入本包不会初始化 GPU（qd.init 惰性发生在 init_quad()）。kernel 定义在
导入期完成但不编译，编译发生在 init_quad() 的主线程 warmup（Quadrants 要求编译
必须在主线程，参见 quad-docs/user_guide/quirks.md）。
"""

from .QuadAccel import (
    init_quad,
    is_available,
    resize_bilinear,
    resize_host,
    FrameCompositor,
    QUAD_AVAILABLE,
)
from .QuadRenderer import (
    RenderContext,
    render_info_segment,
    render_video_segment,
    render_all_clips,
)
from .IslandConcat import (
    combine_full_video_xfade_islands,
    combine_full_video_direct,
)
from .SafeRender import render_full_video_safe

__all__ = [
    "render_full_video_safe",
    "render_all_clips",
    "render_info_segment",
    "render_video_segment",
    "RenderContext",
    "combine_full_video_xfade_islands",
    "combine_full_video_direct",
    "init_quad",
    "is_available",
    "resize_bilinear",
    "resize_host",
    "FrameCompositor",
    "QUAD_AVAILABLE",
]
