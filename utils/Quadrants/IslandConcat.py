"""
IslandConcat.py - transition-island 低内存视频拼接

节选自 utils/VideoUtils-mgv.py（上游 mai-gen-video 合成层），改为自包含：
- get_ffmpeg_binary / get_ffmpeg_encoder_args 从本包 RenderIO 导入（不再依赖 utils.AccelRenderer）
- sort_video_files 从 utils.DataUtils 导入（稳定通用工具）

核心思想（治 README 记录的 _ArrayMemoryError）：
传统做法是把所有片段塞进一条巨型 ffmpeg xfade 滤镜链，片段一多内存爆炸。
transition-island 改为**每次只处理相邻两片的转场窗口**：
  对每个片段裁出"主体"(body，去掉两端转场窗口) + 对每对相邻片段裁出"转场"(xfade)，
  最后用 concat 流拷贝拼起来。任意时刻只有一小段在 ffmpeg 内，内存恒定。

纯 ffmpeg/ffprobe 实现，不依赖任何 GPU 计算框架。
"""

import os
import re
import shutil
import subprocess
import time

from utils.DataUtils import sort_video_files

from .RenderIO import get_ffmpeg_binary, get_ffmpeg_encoder_args, get_active_render_job


# ============================================================================
# 基础辅助
# ============================================================================

# 渲染临时产物的统一归宿（ts_files.txt / final_output.mp4 / island 主体段等）。
# 集中到 videos/temp_generated 下，避免散落在存档 videos 目录与仓库根目录；
# 渲染 worker 的 finally 会清理整个 temp_generated。
TEMP_ROOT = os.path.abspath('./videos/temp_generated')

def _get_video_duration(filepath: str) -> float:
    """用 ffprobe 获取视频时长（秒）。文件被短暂占用（扫描/同步/预览）时退让重试，
    仍失败返回 0.0（由调用方抛出明确的错误）。"""
    cmd = [
        get_ffmpeg_binary('ffprobe'), '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        filepath
    ]
    for attempt in range(5):
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            if attempt == 4:
                print(f"[Warning] 读取视频时长失败（文件可能被其他程序占用）: {filepath}")
                return 0.0
            time.sleep(0.25 * (attempt + 1))


def _format_seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.6f}"


def _run_subprocess_checked(cmd: list, stage: str):
    result = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    job = get_active_render_job()
    if job is not None:
        job.check_cancelled()
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        if len(stderr) > 2000:
            stderr = stderr[-2000:]
        raise RuntimeError(f"{stage} 失败，返回码 {result.returncode}: {stderr}")
    return result


def _get_libx264_encoder_args():
    return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']


def _get_encoder_args_with_fallback(codec: str, bitrate: str, force_software: bool = False) -> list:
    if force_software or not codec or codec == 'libx264':
        return _get_libx264_encoder_args()
    try:
        return get_ffmpeg_encoder_args(codec, bitrate)
    except Exception:
        return _get_libx264_encoder_args()


def _run_ffmpeg_encode_with_fallback(cmd_prefix: list, output_path: str,
                                     codec: str, bitrate: str, stage: str):
    """先尝试硬件编码器，失败回退 libx264。"""
    attempts = []
    if codec and codec != 'libx264':
        attempts.append((codec, _get_encoder_args_with_fallback(codec, bitrate)))
    attempts.append(('libx264', _get_libx264_encoder_args()))

    last_error = None
    used_codecs = set()
    for codec_name, encoder_args in attempts:
        if codec_name in used_codecs:
            continue
        used_codecs.add(codec_name)
        if os.path.exists(output_path):
            os.remove(output_path)
        cmd = cmd_prefix + encoder_args + [
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
            output_path
        ]
        try:
            _run_subprocess_checked(cmd, f"{stage} ({codec_name})")
            if codec_name != codec and codec and codec != 'libx264':
                print(f"[Info] {stage}: 硬件编码失败后已回退 libx264")
            return
        except RuntimeError as e:
            last_error = e
            if codec_name != 'libx264':
                print(f"[Warning] {stage}: {codec_name} 编码失败，尝试回退 libx264")
                continue
            raise
    if last_error:
        raise last_error


# ============================================================================
# transition-island 各阶段
# ============================================================================

def _render_xfade_body_segment(input_path: str, start: float, duration: float,
                               output_path: str, codec: str, bitrate: str,
                               video_fps: int, stage: str):
    """裁出一个片段的"主体"（去掉两端转场窗口），统一格式。"""
    filter_complex = (
        f"[0:v]trim=start={_format_seconds(start)}:duration={_format_seconds(duration)},"
        f"setpts=PTS-STARTPTS,fps={video_fps},format=yuv420p,settb=AVTB[v];"
        f"[0:a]atrim=start={_format_seconds(start)}:duration={_format_seconds(duration)},"
        f"asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
        f"asetpts=N/SR/TB,aformat=sample_fmts=fltp:channel_layouts=stereo[a]"
    )
    cmd_prefix = [
        get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', input_path,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '[a]'
    ]
    _run_ffmpeg_encode_with_fallback(cmd_prefix, output_path, codec, bitrate, stage)


def _render_xfade_transition_segment(left_path: str, right_path: str,
                                     left_start: float, duration: float,
                                     output_path: str, codec: str, bitrate: str,
                                     video_fps: int, stage: str):
    """对相邻两片的重叠窗口做 xfade（视频）+ acrossfade（音频）。"""
    duration_s = _format_seconds(duration)
    filter_complex = (
        f"[0:v]trim=start={_format_seconds(left_start)}:duration={duration_s},"
        f"setpts=PTS-STARTPTS,fps={video_fps},format=yuv420p,settb=AVTB[v0];"
        f"[1:v]trim=start=0:duration={duration_s},"
        f"setpts=PTS-STARTPTS,fps={video_fps},format=yuv420p,settb=AVTB[v1];"
        f"[v0][v1]xfade=transition=fade:duration={duration_s}:offset=0,"
        f"format=yuv420p,settb=AVTB[vout];"
        f"[0:a]atrim=start={_format_seconds(left_start)}:duration={duration_s},"
        f"asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
        f"asetpts=N/SR/TB,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
        f"[1:a]atrim=start=0:duration={duration_s},"
        f"asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
        f"asetpts=N/SR/TB,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];"
        f"[a0][a1]acrossfade=d={duration_s}:c1=tri:c2=tri,"
        f"aresample=48000:async=1:first_pts=0,asetpts=N/SR/TB[aout]"
    )
    cmd_prefix = [
        get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', left_path, '-i', right_path,
        '-filter_complex', filter_complex,
        '-map', '[vout]', '-map', '[aout]'
    ]
    _run_ffmpeg_encode_with_fallback(cmd_prefix, output_path, codec, bitrate, stage)


def _is_lockish_text(e: Exception) -> bool:
    """判断子进程报错文本是否指向文件占用（ffmpeg 打不开被锁定的输出时在此显形）。"""
    text = str(e)
    return ('Permission' in text or 'denied' in text
            or 'WinError' in text or '被占用' in text)


def _concat_island_segments(segment_paths: list, list_file: str, output_path: str,
                            video_fps: int):
    """concat 流拷贝拼接所有 body/transition 段。

    成品被其他程序占用（旧成片还在播放器里开着等）时先退让重试；流拷贝失败
    再回退重编码。"""
    with open(list_file, 'w', encoding='utf-8') as f:
        for path in segment_paths:
            safe_path = os.path.abspath(path).replace('\\', '/').replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    copy_cmd = [
        get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning',
        '-f', 'concat', '-safe', '0',
        '-i', list_file,
        '-c', 'copy',
        output_path
    ]
    reencode_cmd = [
        get_ffmpeg_binary('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'warning',
        '-f', 'concat', '-safe', '0',
        '-i', list_file,
        '-vf', f'fps={video_fps},format=yuv420p',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        output_path
    ]
    for attempt in range(3):
        try:
            _run_subprocess_checked(copy_cmd, "transition island 最终 concat")
            return
        except RuntimeError as e:
            if _is_lockish_text(e) and attempt < 2:
                delay = 0.5 * (attempt + 1)
                print(f"[Warning] 成品疑似被其他程序占用，{delay:.1f}s 后重试 concat "
                      f"({attempt + 2}/3): {e}")
                time.sleep(delay)
                continue
            print(f"[Warning] 最终 concat 流拷贝失败，将回退重编码: {e}")
            break
    _run_subprocess_checked(reencode_cmd, "transition island 最终 concat 重编码")


def combine_full_video_xfade_islands(video_clip_path: str, trans_time: float = 1,
                                     codec: str = None, bitrate: str = "5000k",
                                     video_fps: int = 60,
                                     temp_dir_name: str = "xfade_islands_tmp"):
    """低内存 xfade 拼接：每次只处理相邻两片的转场窗口，再 concat。

    仅调用 FFmpeg/FFprobe，不依赖 MoviePy 或 GPU 计算框架。
    片段需命名为 {数字前缀}_{...}.mp4 以便 sort_video_files 正确排序。
    """
    print("[Info] --------------------开始 transition island 低内存拼接-------------------")
    t_concat_start = time.perf_counter()

    video_files = [f for f in os.listdir(video_clip_path)
                   if f.endswith(".mp4") and re.match(r'^\d+_', f)]
    sorted_files = sort_video_files(video_files)
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")
    if len(sorted_files) == 1 or trans_time <= 0:
        return combine_full_video_direct(video_clip_path, auto_add_transition=False,
                                         trans_time=trans_time, video_fps=video_fps)

    file_paths = [os.path.join(video_clip_path, f) for f in sorted_files]
    durations = []
    for fp in file_paths:
        duration = _get_video_duration(fp)
        if duration <= 0:
            raise ValueError(f"无法获取视频时长: {fp}")
        durations.append(duration)

    frame_epsilon = 1 / max(video_fps, 1)
    transition_times = []
    for i in range(len(file_paths) - 1):
        max_duration = min(
            float(trans_time),
            durations[i] / 2 - frame_epsilon,
            durations[i + 1] / 2 - frame_epsilon
        )
        transition_times.append(max_duration if max_duration > frame_epsilon else 0.0)

    output_path = os.path.join(TEMP_ROOT, "final_output.mp4")
    temp_dir = os.path.join(TEMP_ROOT, temp_dir_name)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

    generated_segments = []
    success = False
    try:
        segment_index = 0
        for i, file_path in enumerate(file_paths):
            left_transition = transition_times[i - 1] if i > 0 else 0.0
            right_transition = transition_times[i] if i < len(transition_times) else 0.0
            body_start = left_transition
            body_end = durations[i] - right_transition
            body_duration = body_end - body_start

            if body_duration > frame_epsilon:
                body_path = os.path.join(temp_dir, f"{segment_index:04d}_body_{i:04d}.mp4")
                print(f"[Island] 生成主体片段 {i + 1}/{len(file_paths)}: "
                      f"start={body_start:.3f}, duration={body_duration:.3f}")
                _render_xfade_body_segment(
                    file_path, body_start, body_duration, body_path,
                    codec, bitrate, video_fps, f"主体片段 {i + 1}"
                )
                generated_segments.append(body_path)
                segment_index += 1
            else:
                print(f"[Island] 跳过过短主体片段 {i + 1}: duration={body_duration:.3f}")

            if i < len(file_paths) - 1:
                transition_duration = transition_times[i]
                if transition_duration > frame_epsilon:
                    transition_path = os.path.join(
                        temp_dir, f"{segment_index:04d}_transition_{i:04d}_{i + 1:04d}.mp4")
                    left_start = durations[i] - transition_duration
                    print(f"[Island] 生成转场 {i + 1}->{i + 2}: duration={transition_duration:.3f}")
                    _render_xfade_transition_segment(
                        file_path, file_paths[i + 1], left_start, transition_duration,
                        transition_path, codec, bitrate, video_fps, f"转场 {i + 1}->{i + 2}"
                    )
                    generated_segments.append(transition_path)
                    segment_index += 1
                else:
                    print(f"[Island] 片段 {i + 1}->{i + 2} 太短，退化为无转场拼接")

        if not generated_segments:
            raise RuntimeError("transition island 未生成任何有效临时片段")

        list_file = os.path.join(temp_dir, "concat_list.txt")
        _concat_island_segments(generated_segments, list_file, output_path, video_fps)
        success = True
        print(f"[Timer] transition island 拼接总耗时: {time.perf_counter() - t_concat_start:.2f}s")
        return output_path
    except Exception as e:
        print(f"[Error] transition island 拼接失败，临时文件保留在: {temp_dir}")
        raise RuntimeError(f"transition island 拼接失败: {e}。临时文件保留在: {temp_dir}") from e
    finally:
        if success and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


# ============================================================================
# 无转场直接拼接（island 在单片段/零转场时的回退）
# ============================================================================

def combine_full_video_direct(video_clip_path, auto_add_transition=False, trans_time=1,
                              codec=None, bitrate="5000k", video_fps=60):
    """拼接文件夹下所有 {数字前缀}_*.mp4 片段。

    - auto_add_transition=False：TS remux + concat 流拷贝（无转场，最快、最低内存）。
    - auto_add_transition=True ：转交 combine_full_video_xfade_islands（低内存 xfade）。
    """
    if auto_add_transition and trans_time > 0:
        return combine_full_video_xfade_islands(
            video_clip_path, trans_time=trans_time, codec=codec,
            bitrate=bitrate, video_fps=video_fps)

    print("[Info] --------------------开始拼接视频-------------------")
    t_concat_start = time.perf_counter()

    video_files = [f for f in os.listdir(video_clip_path)
                   if f.endswith(".mp4") and re.match(r'^\d+_', f)]
    sorted_files = sort_video_files(video_files)
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")
    print(f"[Timer] 拼接: 找到 {len(sorted_files)} 个片段")

    output_path = os.path.join(TEMP_ROOT, "final_output.mp4")
    temp_dir = os.path.join(TEMP_ROOT, "temp_ts")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        t_remux = time.perf_counter()
        ts_list_file = os.path.join(TEMP_ROOT, "ts_files.txt")
        with open(ts_list_file, 'w', encoding='utf-8') as f:
            for i, file in enumerate(sorted_files):
                ts_name = f"{i:04d}.ts"
                ts_path = os.path.join(temp_dir, ts_name)
                cmd = [
                    get_ffmpeg_binary('ffmpeg'), '-y',
                    '-i', os.path.join(video_clip_path, file),
                    '-c', 'copy',
                    '-bsf:v', 'h264_mp4toannexb',
                    '-f', 'mpegts',
                    ts_path
                ]
                subprocess.run(cmd, check=True)
                # concat 列表用绝对路径，不再依赖子进程 cwd 的相对解析
                f.write(f"file '{ts_path.replace(os.sep, '/')}'\n")
        print(f"[Timer] 拼接: TS remux 耗时: {time.perf_counter() - t_remux:.2f}s")

        t_merge = time.perf_counter()
        cmd = [
            get_ffmpeg_binary('ffmpeg'), '-y',
            '-f', 'concat', '-safe', '0',
            '-i', ts_list_file,
            '-c', 'copy',
            output_path
        ]
        subprocess.run(cmd, check=True)
        print(f"[Timer] 拼接: concat merge 耗时: {time.perf_counter() - t_merge:.2f}s")
        print("视频拼接完成")
    finally:
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)
        for txt_file in ['ts_files.txt']:
            txt_path = os.path.join(TEMP_ROOT, txt_file)
            if os.path.exists(txt_path):
                os.remove(txt_path)

    print(f"[Timer] 拼接(concat)总耗时: {time.perf_counter() - t_concat_start:.2f}s")
    return output_path
