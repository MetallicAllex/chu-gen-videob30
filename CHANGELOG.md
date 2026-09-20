# 更新日志

> 仓库内只维护这一份全量更新日志（相对上一个发布版本的全部改动），含实测数字、成因、完整已知问题、发行包注意事项。
> 面向自己人与反馈排查；对外简略说明在出包时另行摘录，仓库内不留第二份。

## [1.2.6] - 2026-09-20

相对 v1.1.2.1 的全量改动：26 个已跟踪文件 +5394/−2689，新增 10 个文件约 4.5k 行；版本号在
`st_pages/0_homepage.py:98`。按环节记录，每条尽量给成因与代码位置，**行号以本次提交为准**（这份文档里的
`file:NNN` 引用会随改动过期，改完请重新 grep）。

### 国服建档：候选池与筛选

- 建档从"一次请求拿 Best50 再清洗"改成**候选池**：`fetch_cn_pool_raw`（`utils/DataUtils.py:1223`）先不带过滤地
  拉一次全量，`build_cn_pool`（`:1239`）负责归一化 → 过滤 → 分组限额 → 重建 raw；页 1 的改条件走
  `cn_pool_preview`（`st_pages/1_Setup_Achivments.py:467`）+ `st.session_state["cn_pool_cache"]`，本地零请求重筛。
- 三条正交选择：数据源（水鱼 / 落雪）× `POOL_BRIEF 简略成绩 / POOL_FULL 完整历史` ×
  `MODE_SERVER 服务端预筛 / MODE_LOCAL 纯本地`。`to_fish_params`（`utils/FilterUtils.py:393`）把 spec 翻译成水鱼
  查询参数；落雪的个人成绩接口没有查询参数，那一档固定本机筛。
- 筛选面板 `cn_filter_panel`（`:283`）：难度 / 定数区间 / 曲风 / 版本 / 全连 / 链条 / 曲名关键字 / 分数区间 /
  单曲 Rating 区间 / 达成 / 评级 / Over Power / 曲师 / 谱师 / BPM。**该数据源根本不返回的字段置灰并写明原因**
  （`FISH_ABSENT_FIELDS`，`:237`），而不是静默藏掉；水鱼的 rating 与落雪的 ra 不同算法，面板里也注明不可横向比较。
- 分组与配额：`分成 Best / New 两组` 关掉后是 `Best_1..N` 平铺 + "取前几条（按单曲 Rating 降序）"；
  `把 Selections（落雪额外 10 首）纳入候选`；`哪些版本算新曲` 默认照抄"最近两个版本"（水鱼服务端写死的版本表
  与落雪自己标的 New 20 都是这两档），交叉核对不上时退回"本地曲库最高两档"并警告；旧曲组 / 新曲组上限分别设
  （`cap_parts`，`utils/FilterUtils.py:465`）。
- 统计口径 `_cn_render_stats`（`:510`）：候选 / 符合条件 / 入库 / **因缺信息被排除**。
- ⚠️ `b30_raw.json` 语义变了：现在是**过滤后重建**的响应，不再是上游原始回复。排查上游问题时别拿它当上游证据。
- 修：`load_config_with_types`（`utils/DataUtils.py:286`）的 `return data` 原来写在 for 循环里，只返回第一条记录；
  `gen_video_config`（`:169`）里 `clip_start_interval` 自我赋值让默认区间失效，现回到 `(3, 8)`；
  `_process_b50_data`（`:21`）在 `clip_prefixes` 长度与记录数不符时直接中止而不是错位往下走；
  建存档会等到一个不撞秒的 save_id（旧代码有把刚建好的存档 rmtree 掉的路径），过滤后空结果时清理半成品目录。

### 取数鉴权：查分器官方 OAuth

- 新增 `utils/OAuthUtils.py`（602 行）：authorization-code + PKCE 公共客户端，水鱼 scope
  `chunithm.records.read`、落雪 scope `read_player`；本地回环监听接回调（`OAUTH_CALLBACK_PORT = 8599`，`:46`，
  IPv4 `127.0.0.1` 与 IPv6 `::1` 各一个 listener），等待上限 `OAUTH_WAIT_SECONDS = 300`（`:50`）。
  `begin_auth`（`:551`）/ `pop_auth_result`（`:585`）。
- `get_b50_data(server)`（`utils/DataUtils.py:1026`）只剩一个参数：身份取自令牌，因此**只能取到令牌主人自己的成绩**，
  用户名 / QQ / 好友码都不再传。注意水鱼那条 POST 的请求体必须是合法 JSON（服务端解析 body 的语句在 OAuth 分支之前）。
- 令牌落 `./cred_datas/fish_oauth.json` 与 `lxns_oauth.json`（`.gitignore` 已含 `cred_datas/`）：写入走 `.tmp`+
  `os.replace` 原子替换，刷新有 `_fish_refresh_lock`（`utils/OAuthUtils.py:104`，并发刷新会互相撤销令牌），
  401 带 `stale_token=` 标记走重授权。运行时对象挂在 `sys._chugen_oauth_runtime` 上，避免 Streamlit 模块重载时
  回调端口 WinError 10048。
- 页 1 授权区：`进入授权页` 按钮用 `window.open`（`st.link_button` 带 `rel="noreferrer"`，新标签拿不到 opener），
  配「完成授权」浮窗（`st_pages/1_Setup_Achivments.py:144`）；超时后授权链接失效，按钮只剩「重新发起」。

### 曲库与音乐数据

- 新增后台补齐：`start_music_data_update`（`utils/DataUtils.py:2047`）起线程按 ETag/304 拉各源
  （`_fetch_json_etag :1510`），`music_data_state`（`:2106`）报核心库是否就绪，`music_library_status`（`:1801`）
  在首页渲染 `归属 | 用途 | 曲目数 | 本地数据版本 | 云端数据版本 | 同步状态` 表；新鲜度阈值
  `MUSIC_DATA_STALENESS_HOURS = 16 * 24`（`:2002`），失败退避 `RETRY_BACKOFF_HOURS = 6`（`:2016`），
  请求重试 `_get_with_retry` 3 次，风控/挑战页由 `_blocked_reason`（`:1463`）识别（含 HTML 挑战页与
  "enable javascript and cookies" 特征）。
- `st_app.py` 因此不再要求"先点首页那个按钮"：`has_data` 每轮重算，曲库回来后【获取 / 管理存档】自己冒出来。
  新包体默认不带谱面数据，全量最慢实测 56 秒（`st_app.py` 初始化处注释），所以不挡首次渲染。
- 国际服曲库改为自维护 R2 产物（`fetch_intl_music_data :1587`，上游是 `cloudflare/music-db` 的 Worker 清洗结果，
  需 `INTL_MUSIC_URL`；wiki 风格导出必须清洗过才能用，所以这条没有"直连兜底"）；日服走 `JP_MUSIC_URL` 镜像；
  都没配就继续用包内快照。新增水鱼曲库 `fish_music_data.json` / `fish_latest_version.json`，以及国服 `song/list`
  里被 transformer 丢掉的 `versions` / `genres` 两张表单独落盘。
- 缺字段的补法：`backfill_pool_fields`（`:442`）按当前曲库重算 `artist` / `levels` / 空 `level` / `level_next`，
  不动记录列表；入口是【生成 Best50 图 / 查看数据】页的「回填曲库字段」。存档记录新增 `levels:{CN,JP,INT}`，
  `level` / `level_next` 由它派生，`gen_video_config` 会把 `levels` 带进 `video_config_data`。

### 视频检索与下载

- 抓取设置与下载器构造抽到 `utils/fetch_settings.py`（290 行）：`SETTING_KEYS`（`:19`）一份清单同时管住控件与
  下载器参数，`settings_fingerprint`（`:236`）判断设置是否变了，`credential_state`（`:109`）用 (存在, mtime)
  在登入/登出后重建下载器，`bilibili_login_dialog`（`:26`，`LOGIN_POLL_SECONDS = 170`）。
- B 站扫码登录自己发请求（`utils/video_crawler.py:912` `BilibiliQrCodeLoginSession`，直连 `login_v2` 的
  qrcode/web 接口 + `qrcode` 出图）：旧接口在 B 站把 SESSDATA 移进 `Set-Cookie` 后拿不到 `bili_jct`。
  86101 / 86090 / 86038 分别提示"咱就在这里，等扫这个二维码。""扫完了，不点下确认吗？""当前二维码已过期，请刷新重试。"
- 候选排序：`rank_video_candidates`（`utils/DataUtils.py:655`）按标题 / UP 主 / 时长打分，
  `video_match_warning`（`:686`）在最佳命中仍可疑（手元、其他音游、多P合集）时留「待确认[分数]」，
  不再默认取第一条；`get_keyword_fallback`（`utils/video_crawler.py:74`）给曲名前置的兜底关键词，两个关键词的结果
  合并去重后统一排序（`search_one_video`，`utils/DataUtils.py:702`）；`SEARCH_MAX_RESULTS` 3→20，新增
  `SEARCH_SCAN_PAGES`（默认 3，扫描页宽 `SEARCH_SCAN_SIZE = 50`）。
- 列表来源：`search_video_from_playlist`（YouTube `utils/video_crawler.py:816`、B 站 `:1492`）支持 YouTube
  Playlist、B 站 FavoriteList / ChannelSeries(SEASON)、BV 号展开全 P；预置搬运来源表在
  `utils/Variables.py:279` 的 `VIDEO_LISTS`。
- 下载缓存索引 `cache/video_cache_index.json`：`is_video_cached`（`utils/DataUtils.py:777`）/
  `mark_video_cached`（`:796`）记录来源（视频 ID 与分P），换候选或改分P 后重新下载会自动清旧文件重下；
  手动替换文件只要名字不变就照常使用。
- 修：`_pick_bili_streams_compat`（`utils/video_crawler.py:301`）兜住 bilibili-api ≤17.4.1 在 hvc1/dvh1 上对 `None`
  排序抛的 AttributeError，并把"没有可下载的媒体流（可能需要大会员权限…）"说清；`output_file` 在 `os.chdir`
  之前转绝对路径（相对 `./videos/downloads` 会让 ffmpeg 合并静默失败）；`BilibiliDownloader.search_video` 不再对每条
  命中都调 `get_video_info`（原来一次搜索约 50 个请求，容易撞风控）；YouTube `_get_videos_duration` 按 100 个 id
  分片并走 `nextPageToken` 翻页；`download_video` 补上 `p_index`（原来直接 TypeError）；0 字节算失败；批量结束报
  「下载完成，但有 N 首失败」而不是无声；`download_completed` 不再每轮重跑被重置。
- **修复"下载完成 → 合并完成 → 未生成有效视频文件"（用户包实测反馈）**。根因不是素材也不是编解码，而是
  **合并这一步找不到 ffmpeg 可执行文件**：`bilibili_download` 在合并前 `os.chdir` 到 `videos/downloads`
  （`utils/video_crawler.py:420`，全项目唯一一处 chdir，`:448` 才恢复），而旧命令是裸 `ffmpeg` 交给 cmd 解析 ——
  cmd 的搜索起点是**当前目录**，随包那份 `ffmpeg.exe` 在应用根目录，`start.bat` 又不改 PATH，
  于是命令根本没被执行；`> NUL 2>&1` 把"不是内部或外部命令"吞掉、`os.system` 返回码没人看，
  紧接着 `print("合并完成…")` 无条件打印，真相只剩 `DataUtils.py:857` 的存在性校验且不带成因。
  **开发机永远测不出来**：只要本机 PATH 里装了 ffmpeg（作者机是 `E:\FFmpegTools\bin`）这条路就正常，
  而页面其它环节照常，因为它们不 chdir、`get_ffmpeg_binary` 拿 `<cwd>/ffmpeg.exe` 恰好命中应用根目录。
  修法是两处一起：`get_ffmpeg_binary`（`utils/Quadrants/RenderIO.py:81`）增加"按 `__file__` 反推应用根目录"这一档候选，
  不再依赖 CWD；合并收进 `merge_streams()` 并看返回码、把 ffmpeg 的真实报错透传出来。
- 三处 `os.system` 合并（原 `:376` FLV、`:388` 双流、`:834` YouTube）统一收进 `merge_streams()`
  （`utils/video_crawler.py:347`）——`subprocess.run(capture_output=True)` + 看返回码 + 校验 `.part` 产物再
  `os.replace` 原子改名，失败时把 ffmpeg stderr 尾部拼进异常，由 `download_one_video` 的错误分支原样带出；
  "合并完成"移到判据之后，不再是无条件打印。配套的 `stash_failed_streams()`（`:374`）在失败时把输入流改名成
  `failed_{clip}_*.m4s` 留在原目录，否则现场被清掉就没法手工复现那条 ffmpeg 命令。
- **修复合并必然失败的一类选流**：`_detect_bili_streams` 原来只在**非**高分辨率档传 `no_dolby_*`，而
  `DOWNLOAD_HIGH_RES` 默认 true ⇒ `detect_best_streams()` 会把杜比视界/杜比音频挑成"最佳"，可合并用的却是
  `-vcodec copy -acodec copy` 直封 mp4，这类流 muxer 不收 ⇒ 下载看着正常、产物为零。现在两条挑路
  （主路 `:387`、兼容路 `:309`/`:317`）都与画质档无关地排除杜比；HDR 与 HI_RES 仍只在低画质档排除（保留原语义）。
- ffmpeg 路径解析统一到 `RenderIO.get_ffmpeg_binary`（原先 `FFMPEG_PATH = 'ffmpeg'` 是裸名，隐式依赖 PATH）。
  `_ffmpeg_bin`（`utils/video_crawler.py:334`）在复用之外自带一层"按 `__file__` 反推应用根目录"的兜底 ——
  不是重写逻辑，而是让**只被部分更新的安装**也能跑：老包体里只覆盖 `utils/video_crawler.py` 一个文件就修好下载
  （测试 H5 就是按这个场景造的）。GPU import 本身包在 try 里（`QuadAccel.py:32-35` 置 `QUAD_AVAILABLE`），
  缺 `quadrants` 不会连累下载合并。
- 页 2「未登录将以 480P 下载」的 toast 删了，但**不是丢功能**：接管的是抓取面板里置灰的「下载高分辨率视频」
  复选框 help 文案（`utils/fetch_settings.py:156-159`）。

### 样式与内容编辑

- `st_pages/Custom_Video_Style.py` 支持模板 / 只读 / 自定义三态（`_apply_preset_theme`，`:162`，自定义主题带
  `custom_` 前缀），用户主题从 `assets/themes/*.json` 扫描。
- **素材正本路径改为样式子目录**（内层才是正本，外层 flat 那几张退化为 bak）：渲染侧
  `utils/ImageUtils.py:322` → `Base/content/default/content_base.png`、`:533` → `Base/content/init/{level}.png`；
  样式编辑器侧 `st_pages/Custom_Video_Style.py:282` / `:286` 跟着指向 `default/`（init 分支 `:408` / `:415`
  本来就写内层，改的是读的一侧）。改前面有两条断路：本次换的新底图不进画面；init 模板下渲染读外层、
  编辑器写内层，用户在样式页改的图完全不生效。改后 `Frames/{level}.png`（`FrameLoader`，`utils/ImageUtils.py:63`）
  那条路不变。
- 片头片尾改用行内标记 `[静音]` / `[无底图]`（`utils/PageUtils.py:39` `parse_oped_text_markers`），标记在生成图片前
  剥掉，替代原来三个复选框；`render_song_form` 等页面层重复逻辑下沉，`utils/PageUtils.py` 净减约 530 行。
- 编辑 Best50 数据（`st_pages/Make_Custom_Save.py`）：排序结果落盘（`sort_b50_rows`，`:21`，用 `sort_signature`
  判断是否真变了）、按国服 / 国际服 / 日服三服定数对比表加曲、重复 `clip_id` 拒绝保存、「🧮 自动计算 Rating」。
- 底图 / 成绩图渲染失败改为**抛异常且不落盘**：下游把"文件存在"当成"已生成"，写一张错误占位图会被永久当成成品
  （`utils/ImageUtils.py` 相关 docstring）。生成配置时逐条检查 `images/background/{clip_id}.png` 与
  `videos/downloads/{曲ID}-{难度}.mp4`，有缺口就暂停并给汇总清单；`video_configs.json` 是生成那一刻的快照，
  补齐素材后必须重新生成配置才会填上。README 的「生成视频内容配置时提示『图片不存在』」一节按这个写。

### 页面与导航

- 页 2 并入页 3：导航标题改成「搜索、检查和下载视频」；`生成 Best50 图 / 查看数据`、`编辑 Best50 数据`、
  `视频样式编辑器` 三个标题去掉"（可选）"与过时措辞。
- 死页面 `st_pages/2_Search_For_Videos.py`（HEAD 里 403 行）删除；`st_app.py` 里那整块注释掉的旧导航一并清掉
  （142 → 107 行），删后 `nav_dict` 无任何悬空变量、`py_compile` 通过。

### 仓库清理

- Taichi 后端整体删除：`utils/Taichi/` 与三个 `VideoUtils*` 旁支副本（`-mgv` / `-ori` / `VideoUtilsAlt.py`）先删，
  本次再删 `utils/VideoUtils.py`（31KB、7 个函数，其中 `render_all_video_clips` / `combine_full_video_direct` /
  `gen_black_video` / `check_rendered_clips_multithreaded` 与 `utils/SegmentUtils.py` 重名）——全仓库对它的引用只剩
  页 6 一条注释掉的 import（原 `st_pages/6_Compostie_Videos.py:8`），连同注释掉的 `render_all_clips_accel2` 调用块
  一并清掉；`Quadrants/*.py` 里"节选自 `VideoUtils-mgv.py`""移植自 Taichi/…"的来源注释作为出处记录保留。
- **11 份 `-bak` 素材出仓**：`assets/BgClips/bg_bak.mp4`、`assets/Audios/bgm_bak.mp3`、
  `assets/images/Base/content/content_base-bak.png`、`Base/content/default/content_base-bak.png`、
  `Base/content/init/{2,3,4}-bak.png`、`Frames/{0,2,3,4}-bak.png`。依据是：样式编辑器在「确认替换」覆写前一律先
  `copy2(当前→bak)`（`st_pages/Custom_Video_Style.py:356` / `:487` / `:613` / `:733`），缺 bak 时还原按钮本来就被
  `has_video_backup` 隐藏，而渲染链路（`utils/ImageUtils.py` / `utils/SegmentUtils.py` / `utils/DataUtils.py`）
  **没有一处读 `-bak`**。仓库里那份 `bg_bak.mp4` 与 `bg.mp4` md5 完全相同（`f2cfee59…`），纯 16.5MB 重复。
  运行时生成的那些由 `.gitignore` 兜住。代价：手工在资源管理器里换素材的人不再有"还原"可点。
  其中 `Base/content/default/content_base-bak.png`、`Base/content/content_base-bak.png` 与外层
  `Base/content/content_base.png` 三张字节完全相同（都是改版前的 `34faf007…`）：外层那张按"外层即 bak"留着，
  两份 `-bak` 出仓，改由样式编辑器在覆写内层正本时生成（`Custom_Video_Style.py:356`）。
- `assets/images/Base/content/versions/`（定数版本对比的预留底图，页面控件已有、渲染无实际效果）只 ignore 不入库，
  等实现接上再提交。
- `.gitignore`：新增 `cache/`、`cloudflare/`、`oauth_docs/`、`utils/quad-docs`、`experiments/`、`output/`、
  `script/`、`_chat_text*.txt`、`.dsh-edit-review*.json` 与全套 `-bak`；删掉已名存实亡的
  `chu-gen-videob30-v1.1.2.1.zip`、`utils/VideoUtils-ori.py`、`utils/VideoUtilsAlt.py`、`utils/Taichi`
  和三行被注释掉的 ignore。

### 视频合成 · 测试环境与口径

以下环节实测数据来自：RTX 3060 Laptop，随包 ffmpeg `2026-04-16-git` 构建，探测到 `h264_nvenc`；
素材为最新存档 `b30_datas/metallicallex/20260821_042126` 与 `outside_test/20260909_205411`。
**所有对照均在同一次运行、同一份素材内完成**——这条管线的成本对源编码器极度敏感（AV1 vs H.264 差 2.5 倍），跨存档比较会得出相反结论。

### 视频合成 · 性能

| 场景 | 改前 | 改后 |
|---|---|---|
| 1080p · 10s · 单片段（两遍 → 单遍） | 52.69s | **13.9s** |
| 720p · 10s · 单片段（再叠加输入侧 `-ss` 起播定位） | 31.7s | **5.1 ~ 11.3s** |
| 1080p · 端到端 5 段（含各片段起点与响度探测） | 未在 1080p 单测改前值 | **17.6s/段** |
| 50 段 1080p 全片估算 | 约 44 分钟 | **约 15 分钟** |

- 原实现每个片段编码两遍：stage1 ffmpeg 走 nvenc，stage2 `clip.write_videofile(codec="libx264")`。
  1080p/10s 实测第二遍 37.27s / 总 52.69s（**占 70.7%**），且淡入淡出与响度对齐只能落在这遍，等于开过渡就必然软件重编。
  现在 fade/afade/volume 成为 stage1 滤镜，单遍直写。
- 只把 `scale`/`trim` 换序**不省时间**（36.5s）：成本在解码不在缩放。

### 视频合成 · 正确性

- **成片缺段**：`-ss bg_offset` 未对背景长度取模，bg.mp4 只有 60.4s 而 Best50 累计 500+s，第 7 段起背景输入零帧，
  ffmpeg 报 `Could not open encoder before EOF`（rc=-22），实测 52 段中 **45 段静默失败**，仍拼出"渲染完成"的缺半成片。
- **背景循环不无缝**：旧 `loop=loop=-1:size=1000` 会把窗口内帧全缓存在内存（1080p 约 3GB），
  且片段跨过背景末尾时只反复重播那 1000 帧、不回到开头。现改为够长就 `trim`、不够就把同一文件多挂几路输入 `concat`。
  坑：**输入侧 `-ss` 与 `-stream_loop -1` 同时用是坏的**（两种参数顺序都不对）。
- **音画错位的真凶是片段音频参数不一致 + `concat -c copy`**：谱面源混有 44.1k 与 48k（该存档 52 段 = 43×44100 + 9×48000，
  每个存档都混，旧 MoviePy 收尾同样没归一化）。`-c copy` 只按第一段参数建轨，其余段按错时间基摆放：
  混合 12 段实测 **238 次 Non-monotonic DTS**（同参数只 11 次），52 段 **5426 次**，音频轨比视频轨多 **24.26 秒**，
  而**总跨度指标看不出异常**。修复：编码期固定 `-ar 44100 -ac 2`，并在拼接前探测统一（视频流拷贝、只重编不一致段的音频）
  ⇒ 历史存档无需重渲，实测挤包 5426 → 51、+24.259s → +0.023s。
  注：固定到 44.1k 只覆盖经典路（`SegmentUtils.py:26` 的 `DEFAULT_AUDIO_SAMPLE_RATE`）；GPU 路统一重采样到 48k
  （`IslandConcat.py:104`、`SafeRender.py:48`），所以两路产物采样率不同，各自内部一致。
- **删掉二遍后遗留的音频时间戳不齐**：单遍产物每段音频比视频长一个 AAC 帧（1024/44100 = 23.2ms），concat 按声明时长推进基线 →
  每段溢出帧撞进下一段。现在音频链尾固定 `apad,atrim=0:{duration},asetpts=N/SR/TB`。
  注：`aresample=first_pts=0` 与 `-movflags -use_editlist` 实测都不能修此问题。
- **谱面看着像 30 帧**：素材是真 60fps（24 首 `mpdecimate` 默认阈值一张不丢），根因是 `overlay` 按主输入时间网格取次输入帧，
  两路时间基不严格对齐时隔几帧才推进一次，再由 `-r 60` 复制凑数。两路进 `overlay` 前各加 `fps=60` ⇒
  按帧号对齐源与产物的判据：**45 帧里 14 个重复帧 → 0**，三首歌均验证。
- **输入侧 `-ss` 的连带约束**：加了输入侧 `-ss` 后，音频那路必须由 `atrim=start=N:duration=D` 改成 `atrim=duration=D`，否则双重偏移。
  验证：新旧两版音频取 PCM 做 1 样本步进互相关 → **0 样本偏移、残差/信号 1.2%**（纯重编码噪声），视频两版均 600 帧、重复帧 0。
- **半成品文件**：产物先写 `.part` 再 `os.replace` 原子改名（`.part` 必须显式 `-f mp4`，否则 ffmpeg 从扩展名推不出容器）。

### 视频合成 · 界面与设置

- 「片段过渡」开关滞后一次渲染：勾选框写 `trans_params["enable"]`，渲染侧读 `['enabled']`。已统一为 `enabled`。
- 渲染失败此前只显示 10 秒随即 `st.rerun()` 抹掉，片段级失败既不报错也不阻止拼接。现在 `render_all_video_clips` 返回失败列表，
  页面写 `session_state.render_error` 持久展示并跳过拼接。
  注：这条还没覆盖全 —— 主视频配置缺失时 `SegmentUtils.py:975-978` 裸 `return`（None），页 6 的
  `_render_result or []` 会把它当成零失败照常拼接；`SafeRender.py:464` 也丢弃了回退补渲返回的失败列表。
- 曲名含 `・`(U+30FB) 时在非 UTF-8 控制台抛 `UnicodeEncodeError` 中断整条渲染。`start.bat` 有 `chcp 65001` 故发行包无恙，
  按 README 手敲 `streamlit run st_app.py` 的源码用户会挂（该存档 50 首中 16 首含此类字符）。现 `st_app.py` 给 stdout/stderr 设 `errors='replace'`。
- 「使用 GPU 硬件加速」复选框此前完全无效（唯一读 `hwaccel`/`codec` 的函数无调用点）。`_build_encoding_args` 已改为在 `hwaccel` 为真时采纳
  `encoder_param['codec']`，未勾选仍走自动探测（**没有翻转默认行为**）。

### 已知问题（跨环节）

- **影响已发布包（至 v1.2.6）：用户机器 PATH 上没有 ffmpeg 时，B 站下载全部停在「未生成有效视频文件」**
  （不分高低分辨率，两条分支都要过 ffmpeg 封装；YouTube 只有「高分辨率」档受影响，普通档走 `os.rename`）。
  根因与修法见「视频检索与下载」。给已装用户的办法是**只覆盖一个源文件** `utils/video_crawler.py`
  （它自带应用根目录探测，不要求同时更新 `RenderIO.py`）——不用拷 ffmpeg、不用改 PATH。
  拿不到新文件时的最后兜底才是把 `ffmpeg.exe` 复制进 `<应用目录>/videos/downloads/`。
- **老存档没有 `levels` 字段，且没有自动迁移**：渲染回退到 `song["level"]`，要拿三服定数得上
  【生成 Best50 图 / 查看数据】页手动「回填曲库字段」（`backfill_pool_fields`，`utils/DataUtils.py:442`）。
  首次升级就直奔渲染的用户不会看到任何报错，只是定数表少两列。
- `create_downloader`（`utils/video_crawler.py:1598`）硬编码 `./cred_datas/bilibili_cred.pkl`，忽略传进来的
  `credential_path`；`streamlit_login_bilibili()`（`:1009`）已经零调用点（旧的命令提示符登录），下次动这个文件时清掉。
- 底图与成绩图的正本在**样式子目录**里（`Base/content/default/`、`Base/content/init/`），外层 flat 那几张
  （`Base/content/content_base.png`、`Base/content/{2,3,4}.png`）按"外层即 bak"的定位保留，现在没有任何代码读它们。
  此前渲染与样式编辑器都指着外层：本次换的 `default/content_base.png` 新底图**根本不会进画面**，
  init 分支更是渲染读外层、编辑器写内层，改了等于没改。现已把四处路径统一到内层（详见「样式与内容编辑」）。
  实测佐证：HEAD 里内外层逐张 md5 相同，所以 init 分支这次改路径是零视觉变化，只是让后续编辑能落地；
  `default/content_base.png` 与外层不同（`d4dd50c9` vs `34faf007`），切换后新底图才真正生效。
  待定：若确认没人手工依赖外层，可以整批出仓。
- ~~`combine_full_video_direct`（`utils/SegmentUtils.py:1133`）仍直接起 PATH 上的 `'ffmpeg'`~~ **已修**：
  拼接（现 `utils/SegmentUtils.py:1135`）、版本探测（`utils/PageUtils.py:79`）、下载合并
  （`utils/video_crawler.py` 的 `merge_streams`）三处都先试 `RenderIO.get_ffmpeg_binary`。
  注意 `from utils.Quadrants.RenderIO import …` 会执行整个 `utils/Quadrants/__init__.py`，把 QuadRenderer /
  SafeRender / IslandConcat 连带 cv2、numpy 一起拉起来，只为拿一个路径解析器偏贵；GPU import 本身包在 try 里
  （`QuadAccel.py:32-35` 置 `QUAD_AVAILABLE`），缺 `quadrants` 不会炸，但下载与版本探测两处仍留了
  `shutil.which` 兜底。
- **本机 `quadrants` 实测是 1.0.2，而 `requirements.txt:24` 钉 `==1.3.0`**：GPU 路那批性能数字全是在 1.0.2 上跑的。
  要么把钉法放宽（并对齐 `runtime/` 里那份），要么升到 1.3.0 重跑 GPU 侧数据。
- `generate()` 标了 `-> bool`（`utils/SegmentUtils.py:297`、`:539`），失败路径实际 `return None`（`:382`、`:612`）；
  另外 `_get_full_image_path` 在 `bg_page=True` 且不检查文件是否存在就返回绝对路径（`:417`），与"渲染失败不落盘"的约定相反。

### 已知问题（视频合成）

- ~~`assets/BgClips/bg.mp4` 在 40.283s 处有一个全黑帧~~ —— **已解决**：素材于 09-19 20:48 换过一次、09-20 14:23 又换过一次，
  当前这份实测 **3028 帧 / 50.47s**（ffprobe），`blackframe=amount=2:threshold=16` 全片扫描零命中。
  对外说明里的"背景黑帧已知问题"已随之删除。
  注意所有以"bg 长 60.4s"为前提的旧数字现在对应 50.47s（取模逻辑不变，回绕点变密）。
- **两后端成片时长与过渡形态不一致**：经典路淡入黑场 + `-c copy` 不缩时长；GPU 路 `xfade` 交叉淡化，每个边界吃掉 `trans_time`
  （同素材实测成片 12.049s vs 10.578s）。
- GPU 路取消任务会落到没有取消检查点的 CPU 全量重渲（`RenderCancelled` 被 `QuadRenderer.py` 的 `except BaseException` 重包成普通 `RuntimeError`）。
- 无音轨的谱面素材会让 GPU 路崩：`[1:a]atrim` 绑不到流 → `BrokenPipeError` → 重试 3 次 → 触发 CPU 全量重渲。
- 经典路整条渲染仍阻塞 Streamlit 主线程（GPU 路已改常驻工作线程）。
- 随包 `ffmpeg.exe` 与 `ffprobe.exe` 是 nightly git 构建且来自**不同日期/不同 commit**（2026-04-16 与 2026-04-25），建议换成套 release 构建。
- `requirements.txt` 已声明 `quadrants==1.3.0`（GPU 后端唯一依赖，`requirements.txt:24`）与 `qrcode>=8.2`（B 站扫码登录）。
  Taichi 后端已于 2026-09-20 移除（长期不更新、与 Quadrants 功能区重叠，且 Quadrants 已把它的能力复制完），
  所以 `taichi` 不再需要；此前它也从不在 `runtime/` 内，本机那次 `import taichi` 成功是用户级 site-packages 泄漏。
- GPU 路在两种源上都比修后经典路慢（1080p/10s 单片段：H.264 源 7.90s vs 14.50s；AV1 源 9.89s vs 28.67s）。
  阶段消融显示合成阶段一开，两路解码各 +11ms、编码 +7.3ms，连带损失远大于它自己的 18ms；已排除 GIL 抢占、CPU 掉频、NVENC 队列争用。
  ~~出路是别让帧离开 GPU（NVDEC→GPU 合成→NVENC），或试 pinned memory~~ —— 两条都被否掉：**NVDEC 直连**与"qd 要全设备可用"冲突
  （且 Ampere 的 NVDEC 不解 AV1，正是最慢那批素材）；**pinned/零拷贝**拿不到（`qd.ndarray` 不接受外部指针，
  `to_numpy(copy=False)` 在 GPU 后端抛 `Zero-copy numpy requires a CPU backend`，批量 K=1..16 只省 0.2~0.6ms/帧）。
  真因在库里：`_ndarray.py:224-229/268-271` 显示每次 host↔device 都是"桥 kernel（每字节一个 GPU 线程）+ 一次全设备 `sync()`"，
  所以还能做的是减少往返次数（chart 折进 bg 只传一次）、绕开 `to_numpy` 的 `np.zeros`、`graph=True` 打散启动开销。

### 与其他工作线的交界

- 页 6 的「使用 GPU 硬件加速」复选框 `disabled=True` 且 `value=False`（`st_pages/6_Compostie_Videos.py:223`）、
  「加速方案」下拉 `disabled=... or not hwaccel`（:235）⇒ 两个控件当前都点不动。**这是作者主动灰置的，不是 bug**：
  Quadrants 路性能还没超过经典路，先不让用户选到慢的那条；等性能问题解决了再把「加速方案」提为唯一入口。
  对外发布说明里因此不写"修复 GPU 加速复选框"。
  顺带：`if hwaccel:` 分支（:338）恒不成立，`encoder_param['codec']` 恒为 `libx264`，但渲染侧只在 `hwaccel` 为真时才采纳它，
  已跑真码验证：`{'hwaccel': False, 'codec': 'libx264'}` → 实际下发 `-vcodec h264_nvenc`（走自动探测），**硬编没有被这个灰置打掉**。
- 页 6 的「Quadrants GPU 渲染（实验）」按钮 `disabled=True`、help 明写"当前未开放"⇒ 上面 GPU 路那串已知问题对普通用户不可达。

### 发行包注意

- 出包脚本 `script/build_release.ps1`（未跟踪）**只出源码包**：顶层结构对齐参考包 `script/reference.zip`
  （即当年那份 `chu-gen-videob30-v1.1.2.1.zip`），默认产物落 `dist/`（已在 .gitignore）。
  `runtime/`、`ffmpeg.exe`、`ffprobe.exe`、`start.bat` 由另外的专用脚本处理，本脚本把它们列进禁项并主动拦截。
  构建前拦三类：承重文件缺失、**悬空 import**（`from/import utils.X` 必须落到真实文件/包）、疑似凭证文件
  （`*.pkl`/`bilibili_cred*`/`.env` 等，`cred_datas/` 里就是 B 站扫码凭证）；构建后回读校验包内必备项（与前置同一份清单）
  并打印与参考包的目录差异。
- 客户端包里必须有的新文件（缺了就功能性崩）：`utils/OAuthUtils.py`、`utils/FilterUtils.py`、`utils/fetch_settings.py`、
  `utils/Quadrants/` 5 个模块（GPU 渲染后端；`SegmentUtils` 也惰性 import 其中 `RenderIO` 做 ffmpeg 路径/硬编探测/音频 RMS）。
  `cloudflare/` **不进客户端包**——它是服务端（Worker + R2 镜像），应用只通过 `utils/Variables.py` 里的 URL 依赖它。
- 目录已整理（2026-09-20）：包目录 `utils/Quadrants/` 只留 5 个运行时模块 + `__init__.py`；
  16 个实验/诊断脚本与 `PCIe_OPTIMIZATION_NOTES.md` 台账、2 份 html 导出移到仓库根 `experiments/Quadrants/`（作者自用，不进包）。
  实验脚本用 `sys.path.insert(0, os.getcwd())`，**必须从仓库根运行**。
- 包体瘦身（依据见上节「仓库清理」）：`utils/Taichi/` 及其旁支副本、`utils/VideoUtils.py`、11 份 `-bak` 素材、
  `assets/images/Base/content/versions/` 都不再随包分发。`script/build_release.ps1` 是按目录整体收集的
  （`$Dirs` 含 `st_pages` / `utils` / `assets`），文件不在仓库里就不在包里，脚本不用改；`$RequiredRel`
  那份承重清单也不含它们。
- 出包脚本的 `$RootFiles` 含 `CHANGELOG.md`，也就是**随包分发的是这份全量工程口径**（含已知问题与实测台账）。
  若不想把这些发给用户，应在脚本里换成摘录件，而不是在仓库内再维护第二份。

### 待确认（调研中标记，未核实即未写进对外说明）

- ~~页 2 删掉了「未登录将以 480P 下载」提示，是有意改行为还是被页 3 的设置面板接管，看不出来。~~
  **已核实为接管**：抓取设置面板的「下载高分辨率视频」在未登录时置灰，help 文案即"游客无法下载超过 480P+ 的视频"
  （`utils/fetch_settings.py:156-159`），提示没有丢。页 2 本身已作为死页面删除（并入页 3）。
- ~~README 宣称 CHUNITHM-NET 可建档，但页 1 的外服上传逻辑本次未见改动。~~
  **已核实**：走的就是页 1「我玩外服」的 .json 上传（`st_pages/1_Setup_Achivments.py:856`），国际服没有查分器，
  数据得在 CHUNITHM-NET 网页端用 JavaScript 导出；README 该条已按这个流程改写，不再写成"符合清洗要求即可建档"。
- ~~旧存档缺 `levels` 字段时只找到手动"回填"入口，没看到自动迁移。~~
  **已核实**（确实没有自动迁移），已上移到「已知问题（跨环节）」第一条。
