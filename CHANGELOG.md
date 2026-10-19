# 更新日志

> 仓库内只维护这一份全量更新日志（相对上一个发布版本的全部改动），含实测数字、成因、完整已知问题、发行包注意事项。
> 面向自己人与反馈排查；对外简略说明在出包时另行摘录，仓库内不留第二份。

## [1.2.6a] - 2026-10-02 出包，工作树截至 2026-10-18

相对 v1.2.6 的全量改动：20 个已跟踪文件 +800/−524（`git diff --numstat cd322c3 662c2dc` 排除本文件，实测恰为此数：
`st_pages/3_Confirm_Videos.py`
+129/−322、`utils/DataUtils.py` +196/−43、`utils/video_crawler.py` +192/−59、`utils/PathUtils.py` +84/−16、
`utils/fetch_settings.py` +51/−17）。按环节记录，**行号以工作树当前状态为准**。本节主体只覆盖 `662c2dc`；
其后的渲染链路提交 `8394015`、`98216a0` 细节在各自 commit message 里，2026-10-18 的 quadrant 收口
见「视频合成 · quadrant 线路收口（2026-10-18，未随包发出）」。

- **与用户手上那份包对齐过（比对时点 2026-10-13）**：`dist/chu-gen-videob30-v1.2.6a.zip`
  （2026-10-02 16:35、53,950,830 字节）里 14 个承重文件逐个 md5 比对，**当时 12 个与工作树字节相同**，
  只有 `utils/DataUtils.py`（包后再 +93/−11）与 `st_app.py`（+33/−28，导入顺序与续行缩进 +
  `callable(reconfigure)` 硬化）是出包之后再改的。也就是说本节描述的绝大部分**已经随 v1.2.6a 发出去了**。
  包后新增的是「曲库镜像对账」与「quadrant 线路收口」两节，后者**尚未进任何发行包**，且已使
  `utils/Quadrants/*`、`utils/SegmentUtils.py`、`requirements.txt` 不再与包内文件逐字节相同。
  版本号 `st_pages/0_homepage.py:98` 现在仍写 **v1.2.6**，出包前要改。

### 传输层：B 站请求从 aiohttp 换到 httpx

- 现场是进「搜索、检查和下载视频」页就 `AttributeError: 'URL' object has no attribute 'host_port_subcomponent'`。
  根因**不在业务代码，在随包 `runtime/` 的半装状态**：`site-packages` 里同时有 `yarl-1.11.1.dist-info` 与
  `yarl-1.23.0.dist-info`，真正被 import 到的模块 `__version__` 是 **1.11.1**，实测
  `hasattr(yarl.URL('https://x.bilibili.com'), 'host_port_subcomponent')` → **False**；而 `aiohttp 3.13.3` 的
  `client_reqrep.py:1061` 无条件读这个属性（它自己的 METADATA `:42` 就写着 `yarl<2.0,>=1.17.0`）。
  B 站凭证校验（nav）是页面进来后的第一个请求，于是一进来就整页 traceback。
- 同型的第二处：`Brotli-1.1.0.dist-info` 与 `brotli-1.2.0.dist-info` 并存，磁盘上的 `_brotli.pyd` 实测
  **821248** 字节、`_brotli.__version__` = 1.1.0，而 1.2.0 那份 RECORD 记的是 **856576**
  （`brotli-1.2.0.dist-info/RECORD`）。aiohttp 3.13 按 `speedups` 声明（METADATA `:45` `Brotli>=1.2`）以
  双参 `process(data, max_length)` 调用，1.1.0 的 `process` 只收一参 ⇒ TypeError 被 http_parser 的裸 except
  改写成 **`Can not decode content-encoding: br`**。报的是编码、坏的是依赖版本，看着像 B 站挂了或风控。
- **为什么不修 runtime**：`runtime/` 是便携包，终端用户没有 pip、也常常正开着应用（`.pyd` 被占用，
  卸载直接 WinError 5）。修法落在源码层：`utils/video_crawler.py:38` 在 import 期 `select_client('httpx')`，
  让 `bilibili_api` 的 HTTP 全走 httpx（0.26.0），一次绕开 yarl 属性与 Brotli 签名两处耦合。
  三道 fail-fast 而不是静默退回：httpx 装没装（`:13-20`，提示里直接给 `pip install "httpx>=0.24"` 与
  conda/Release 两种出路）、`bilibili_api.utils.network.select_client` 存不存在（`:29-35`，要求
  `bilibili-api-python~=17.4.2`）、切换本身有没有成功（`:37-45`，报错文案写明**不要改回 aiohttp 硬跑**、
  连同两个版本号发给作者）。静默退回等于把那串版本耦合再请回来。
- 换传输层带来的两处写法差异一起处理：`normalize_proxy`（`:58-73`）把裸 `127.0.0.1:7890` 补成
  `http://127.0.0.1:7890`，已带 scheme 的（含 `socks5://`）原样保留 —— `global_config.yaml` 与界面占位符
  历来是不带 scheme 的形态，而 httpx 在构造期就 `ValueError: Unknown scheme for proxy URL`，requests 反而
  原样透传到建连接时才抛 `InvalidProxyURL`，于是"勾了代理反而全失败"和"填对了也没用"长得一模一样。
  另两处是 `bilibili_api` 自己的全局设置 `request_settings.set_proxy(self.proxy or "")`（`:1247`，登出传空串
  而不是 None，会下发给已缓存的会话）和两处自建 `httpx.AsyncClient(..., proxy=...)`（`:325`、`:1063`）。
- `requirements.txt:13-22` 把三个下限钉死并留成因注释：`aiohttp>=3.13,<4.0`、`yarl>=1.17,<2.0`、
  `Brotli>=1.2,<2`。**这只管新装**；已装用户（含 v1.2.6a）的修复面仍是**只覆盖 `utils/video_crawler.py`
  一个文件**（测试 G4 就是按"旧 `RenderIO.py` 共存"造的场景）。
- 反向验证过开关真的生效：填一个不可达代理，改前能拿到 **50 条**搜索结果（说明请求压根没走代理那条路），
  改后直接 `httpx.ConnectError` 冒出来。

### 「未生成有效视频文件」剩下的几个来源

v1.2.6 那节已把"合并找不到 ffmpeg"的主因修掉（`FFMPEG_PATH` 裸名与 `os.system` 拼 shell 在 `cd322c3` 里
已无调用点）。本轮在这条
判据周围还剩几类会塌成同一句话，逐个堵住：

- **YouTube 那条是静默失败**：`download_video` 原来是 `except Exception: traceback.print_exc(); return None`，
  异常只进控制台，页面拿到 None 后由 `utils/DataUtils.py:856` / `:928` 的存在性校验报"未生成有效视频文件"。
  现在引入 `UserFacingDownloadError`（`utils/video_crawler.py:427`），在 6 个抛点带出原因：B 站无可选流 `:520`、
  FLV 封装 `:538`、双流合并 `:550`、YouTube 取流为空 `:992`、合并失败 `:1003`、`:1011`；外层 `:1029` 原样重抛、
  `:1032` 把其它异常包成 `YouTube 下载失败（{video_id}）: {类型}: {消息}`。
- **下载期间的进程级 chdir 取消**：`bilibili_download` 原来为让临时文件用裸文件名而 `os.chdir` 到
  `videos/downloads`，``:523` 注释记录了为什么不能这么干 —— cwd 是整进程共享的，下载期间后台曲库线程
  就在那里建出 `music_datasets/`。`flv_temp` / `video_temp` / `audio_temp`（`:528` 起）与
  `stash_failed_streams`（`:478`）改为按输入所在目录绝对化，失败现场仍留在输入旁边。
- **0 字节产物曾被当成"已生成"**：判据收敛见下一节。
- **页 3 的下载闸门**：`st_download_video`（`:176`）返回**可用素材数**而不是无条件 `download_completed = True`，
  `ready_count`（`:232`）按 `video_info_match` + `is_video_cached` 统计，调用点 `:766` 写
  `download_completed = ... > 0`。0 可用 ⇒ `st.error`（`:237-245`，附首条失败原因与 ffmpeg 提示）并**锁住
  「下一步」**；部分失败 ⇒ `st.warning`（`:246-252`）给 `可用 N/总数` 和曲名清单。改前是"全部失败也解锁"，
  用户带着空素材进页 4。
- **为什么作者机测不出来**（同 v1.2.6 那节的机制，这里补两条）：他机 `runtime/` 不是半装态、PATH 上有
  `E:\FFmpegTools\bin`，且始终从应用根启动。本轮新暴露的这条不对称是**游客 vs 登录 + 选流档位**：
  同一存档同一网络，游客开高分辨率实测仍只到 `852×480`（视频/音频 0.79 / 0.57 Mbps），登录后实测选到
  **1920×1080 h264 60fps 3103451 bps**（视频流 53.87MB + 音频流 1.92MB），合并产物 `ffprobe` 两条轨齐。

### 路径锚定与产物判据

- `st_app.py:10` 在**导入 utils 之前** `os.chdir(应用根)`（`from utils import DataUtils as DU` 现在在 `:12`）。
  曲库/缓存/存档历来是 `./music_datasets`、`./cache`、`b30_datas` 这类相对写法，逐条改绝对会把
  `video_configs.json` 里存的相对路径格式改掉，所以锚在入口；每轮 rerun 都重跑这行，
  被别的代码改走的 cwd 会自愈。
- `utils/PathUtils.py` 新增 `:12 APP_ROOT`、`:13 GLOBAL_CONFIG_PATH`、`:18 TEMP_GENERATED_DIR`（绝对）；
  `:24 DOWNLOADS_DIR` **故意保持相对**（同上，测试 I6 验的是"各页不再各写字面量"，并证明与绝对写法
  normpath 等价）。此前按 cwd 拼 `videos/temp_generated` 的三处改用常量：`utils/SegmentUtils.py:1349`
  （音频统一临时目录）、`utils/Quadrants/IslandConcat.py:38`（**导入期**的 `abspath('./videos/temp_generated')`，
  把启动时那个 cwd 冻结进模块）、`utils/Quadrants/SafeRender.py:210`（这一步是 **rmtree**，cwd 被带偏
  就删错目录）。`6_Compostie_Videos.py:198`（建目录）同理——页 6 里那处收尾清理（原 `:381-382`）在 `8394015`
  已随渲染搬进工作线程，现即上面 `SafeRender.py:210` 这一段。
- 同一族的另一半是**工具解析**：`utils/PageUtils.py:85-87` 的 `get_ffmpeg_version` 在拿不到 `RenderIO` 时
  先试 `APP_ROOT/ffmpeg.exe` 再退到 `shutil.which`，不再只信 PATH —— 随包那份 exe 在应用根，而裸 `'ffmpeg'`
  在 Windows 上按当前目录解析，启动方式一变就把明明装了的 ffmpeg 报成"未安装"。
- `global_config.yaml not found`：`read_global_config`（`:150`）报错带上查找位置；`write_global_config`
  （`:158`）改原子替换（旧写法 `except: print` 把写失败吞成"配置没生效"）；`_read_config`（`:86`）在
  Windows 的"文件占用 / delete pending"窗口里按 **20×30ms** 重试（原来单发 50ms，测试 C1 自己先不稳）。
- `get_video_duration`（`:177`）失败返回 **None** 而不是 0。0 会被当真实时长，`max_minutes = 0` ⇒
  页 4 起止选择器塌成 `0..0`，正常视频也填不进区间；`st_pages/4_Edit_Video_Content.py:333-334` 显式回退
  `DEFAULT_VIDEO_MAX_DURATION`（测试 E6/E7）。
- **唯一判据** `PathUtils.is_artifact_valid`（`:65`，isfile + size>0），`662c2dc` 时 19 处调用点
  （工作树现为 24 处——渲染链路那轮在 `SegmentUtils.py` 里又加了 5 处）：
  `DataUtils.py:234/:239/:856/:928/:1486/:1856/:1889/:2193`、`ImageUtils.py:858`、
  `QuadRenderer.py:692/:708/:724`、`SegmentUtils.py:1095`、`3_Confirm_Videos.py:467/:532`、
  `4_Edit_Video_Content.py:333/:542/:545`、`Generate_Pic_Resources.py:26`。裸 `os.path.exists` 把 0 字节
  失败产物当"已生成"，链路是：跳过重渲 → 直接拼进成片 → 界面显示成功。
- **失败要留在页面上**：`ImageUtils.py:912` 生成评论图失败写 `st.session_state.render_error`（页 5 生成完就
  `st.rerun()`，当场那句 `st.error` 会被冲掉）；页 5 `:411-417` 给持久展示位、`:527` 每次点「生成评论图」先清
  旧记录；页 6 `:485-488` 把"渲染完成"toast 移进 `else` 分支，`_failed` 非空时改口 ⚠️（耗时统计对两者都成立，
  所以留在分支外）。`1_Setup_Achivments.py:179` 存档"文件在但读不出来"以前静默当没存档（用户看到存档凭空
  消失），现在仍按未配置处理但打印位置与原因；`:1019` 空白存档从 `print(f'[{json.dumps(...)}]', file=f)`
  改走 `save_config(..., [new_data])`。

### B 站登录态与 OAuth 令牌

- `save_credential`（`video_crawler.py:194`）原子写 pkl；`load_credential`（`:218`，回写在 `:266-269`）把
  "刷新成功但写盘失败"与"凭证无效"分开 —— 嵌套 try，写失败只警告、本次会话照常可用（这条回归是我上一轮
  引入的）。实测一次真实刷新后 pkl 从 `3e24531d1521…` 变成 `f1b7bf70e5fc…`，没有截断。
- `fetch_settings.py:185/:188/:194` 登录态改三态 True / False / **None**：pkl 读不出来时以前只有"未登录"一种
  显示，用户会去重复扫码；现在 `bilibili_cred_error` 带 `类型: 消息`，面板写"原因：…"。
  `bilibili_login_dialog(proxy=None)`（`:27`）与 `bilibili_logout()`（`:119`）同步维护该状态；`:158`
  「使用代理」的 help 按实际生效范围重写。
- 落雪令牌：`OAuthUtils.py:149` `save_lxns_token` 改 `.tmp` + `os.replace`（半截写会在下次 load 时
  JSONDecodeError，而那条路径是"损坏 → 返回 None"，用户只看到"未登录"、不知道令牌其实还在只是被写坏了）；
  `:234` 把 `except Exception: pass` 拆成两档 —— 传输入口失败（`ConnectionError` / `Timeout`）**保留**
  refresh_token 直接返回 None，上游明确拒绝才 `clear_lxns_token()`。一次断网不再把用户推去重走整条浏览器授权。

### 页 3（搜索、检查和下载视频）

- **1022 → 829 行**。删两块注释掉的旧实现（原 `copy_search_args` 那 150 行调试版 + 一段 15 行死代码），
  压平状态重算（恒不成立的 `isinstance(..., list)` 分支、`check_matched_songs` 被连调两次）。
- `:68-74` 换存档时把控件会话键一起清：`record_selector` 存着上一份存档的曲目字符串，新存档的 options 里没有
  它，Streamlit 恢复旧值会直接抛；`refresh_cache` 是不带 `clip_id` 的全局键，同理串档。用
  `st.session_state.pop(k, None)` —— 随包 streamlit 1.55.0 的 `SessionState.pop(self, key, default=…)`
  实测存在（AppTest 那个包装对象没有 `pop`，测试里改用 `del`）。
- `:86 if current_paths is None: st.stop()`。以前只 warning 不中止，最后崩在 `current_paths['config_yt']` 的
  `TypeError: 'NoneType' object is not subscriptable`。**位置必须在「更换存档」折叠栏之后**：写进 `save_id`
  分支会把这里唯一能当场改选存档的出口一起 stop 掉。
- `polite_wait`（`:167`）：只要发过请求就按 `search_wait_time` 等，纯缓存命中不等。改前失败曲目是
  "失败 → continue"绕开了 sleep，等于零间隔连打平台；两条循环都走它（`:226`、`:282`）。
- `:176`/`:181` 等待参数只有一个来源：`st_download_video` 收 `settings`（下载器实际按哪份构造）而不是
  `G_config`，否则"界面改了、下载器没改"。
- `:532` + `:546` 播放列表缓存：读不出来（半截写/手工改坏）时**回源重取并原子写回**，缓存能自愈；
  `is_artifact_valid(cache_file)` 挡 0 字节。
- `:685` 缓存索引只在 `update_count > 0 or len(merged) != len(old_index)` 时写盘（`merge_b50_data` 在长度不符时
  返回 `update_count=0` 却做的是整体替换，所以两个条件都要）—— 以前每轮 rerun 都重写一次 json。
- `:741-742` `current_index` 钳位（页 4 早有 `safe_index`，页 3 没有）：存档删曲后越界取 `b30_config[i]`。
- `:795` 与 `:824-827` 迁移结果写 `st.session_state.migrate_report` 并给持久展示位 —— `st.caption` 撑不过
  `st.rerun()`，用户点完就看不见了。
- `migrate_search_args` 从页 3 移进 `utils/DataUtils.py:416`：索引键改成 `(id, level_index)`（原来 5 字段逐一
  比对是 O(n²)，且 artist/level 一变就导入失败），返回 `(updated, skipped, missing)`，`.get` 兜字段缺失。
  `apply_playlist_matches(b50_data, all_videos, keep_existing=True)`（`:800`）：批量匹配不再覆盖已手选的候选。

### 控制台可编码性（GBK 代码页）

- `DataUtils.py` 曾有 **19 处** `print` 含 GBK 编不进的字（⚠️✅🔄⏭📋 等）。这些 print 多数落在 except 分支里，
  也就是"善后"本身抛新异常、把真正的失败原因盖掉。改成 `[!] / [OK] / [SYNC] / [SKIP] / [LIST]` 前缀；
  扫描器在 `tests/test_paths_io.py:195 _bad_prints`，G1/G2 断言零命中且"扫描确实覆盖 `utils/` 与
  `utils/Quadrants/`"。
- **本轮我自己又踩了同一类**：`tests/test_paths_io.py:162` 的断言名带 `✅`，用 `python tests/test_paths_io.py`
  直跑时在 GBK 控制台抛 UnicodeEncodeError，**整轮测试跑到 F6 就断**（现场是 traceback，而不是某条 FAIL）。
  修法是 `tests/support.py` 里对 stdout/stderr `reconfigure(errors='replace')`（与 `st_app.py:18-24` 同一处置）
  并把那个 emoji 从断言名去掉。同型问题在比对脚本上又复现一次（打印含 ✅ 的 diff 行），已用 UTF-8 输出绕过。
- 页 6 原 `cleanup_after_render`（`662c2dc` 的 `:383-386`）的 `except: pass` 改成打印原因后继续收尾；
  `8394015` 把渲染搬进工作线程时该函数整体删除，清理逻辑落进 `SafeRender.py:210-224`，并一度以
  `shutil.rmtree(..., ignore_errors=True)` + `except Exception: pass` 退回"清没清掉没人知道"的老状态
  （页 6 的"不再有裸 except"断言只盯页 6，看不见搬走的那份），本轮改回失败即打印异常类型与目录；
  `video_crawler.py` 的裸 `except:` 由 `cd322c3` 的 `:93`/`:162`/`:177`/`:1345` 四处收成为
  `:148`（`ValueError/TypeError/AttributeError`）、`:243`、`:259-269`、`:1477` —— 裸 except 会连
  `KeyboardInterrupt` 一起吞掉，控制台的取消操作因此没反馈。

### 曲库镜像对账（v1.2.6a 之后才加，未随包发出）

`utils/DataUtils.py` 包后 +93/−11 那一块：

- `_row_reconcile`（`:1581`）把 meta 声称的行数与真正拿到的产物对上。meta 与产物是同一个桶里的两个对象、
  在镜像域名上是**两条独立缓存**，各自到期各自回源：实测同一 URL 的缓存在 263 秒 TTL 到点时从 **1561 行翻到
  1571 行**，另一条还停在旧版 —— "新 meta + 旧产物"是常态。不比对的话旧产物会被盖上新的 `written_at`，
  首页"本地/云端数据版本"两列同值、判成 ✅ 已是最新，而它其实少一首歌。
- 对不上时**数据照落、版本时刻不采信**（`version_time = None`，`:1667`），并记进 `_music_state["mismatch"]`
  （`:2161`）而**不是** `_note_fetch_failure`：后者写 `last_error`，而 `last_error` 驱动 6 小时退避 ——
  把"该早点重取"记成"接下来 6 小时别取"正好反了。展示侧 `:1961` 把它拼进 `本机：…`，否则状态列显示
  ⬇️ 有新版看着像正常待同步。按源名覆盖/清除，避免同轮后一个源把前一个源的实话抹掉。
- 失联判定改用 `checked_at`：`_r2_last_contact`（`:1830`）优先 `checked_at`（每轮都写，成功/aborted/304/
  内容没变都写），退回 `written_at` 并在文案里说破"只能按写入时刻算"。`R2_WRITE_STALE_DAYS`（40 天）改名
  `R2_CONTACT_STALE_DAYS`（`:1737`），cron 是每月 1/16 日两次、最大间隔 16 天，取 40 天等于连续跳过两轮多才
  开口；白名单 `:1725` 补 `checked_at`。**只盯 `written_at` 的话，"跑了但上游没变"与"cron 压根没生效"在首页
  长得一模一样** —— 2026-10 那次停摆就是这么全绿了 21 天。
- `st_app.py` 包后再 +33/−28，其中两处**本轮已收口**：`from utils import DataUtils as DU` 原本被 IDE 自动提到
  了文件第 1 行，也就是 `os.chdir` 之前 —— 与 `:5-9` 那条注释写的"必须在导入 utils 之前"正相反。
  查证过程：扫 `utils/*.py` 的模块级语句，没有一处在做文件系统访问或 `os.getcwd()` 求值
  （`PathUtils` 的 `APP_ROOT`/`TEMP_GENERATED_DIR` 按 `__file__` 算，`Variables.root_path` 是 `"./assets"`
  这种留给调用期解析的相对串），所以**当时并无实害**；但假规矩会误导后人，已把这条 import 挪回 chdir 之后
  （`:10` → `:12`，`DU` 的首个使用点远在 `:37`）。同批 `callable(reconfigure)` 硬化与 `st.Page` 续行缩进对齐保留。

### 视频合成 · quadrant 线路收口（2026-10-18，未随包发出）

`98216a0` 之后逐项复盘 GPU 路剩下的缺陷，修在 `utils/Quadrants/`、`utils/SegmentUtils.py`
与页 6 的接线。共同前提是旧写法只在"单源、单帧率、素材完好"时成立，而真实存档三者都不保证。
离线回归 `tests/test_render_freshness.py` 跑到 **合计 215 项，失败 0 项**（新增 DD 组逐条覆盖可测项；
`tests/` 按惯例仍不入库）。

- **混合帧率不再改变片段时长/速度**：帧读取原来是"每个输出帧读一个源帧"。30fps 谱面配 60fps 输出时
  1 秒的源只用 0.5 秒就被读空（随后停在尾帧），60fps 源配 30fps 输出则丢掉一半帧。现在由
  `RenderIO.py:588` 的 `FramePump` 按时间基换算源位置：需要重复时复用上一帧，需要跳帧时只
  `grab()` 不解码（`RenderIO.py:561`）；循环背景到 EOF 回绕，非循环谱面保持尾帧；`seek_to` 对
  `frame_count == 0` 也做了夹取（`RenderIO.py:552`）。离线实测：30fps → 60fps 连续 30 次输出正好
  覆盖 1 秒、每源帧用两次；25fps → 60fps 最长连续重复 3 帧；60fps → 30fps 消费 60 个源帧。
- **输出帧率取本批全部 main 源的最高值**（`QuadRenderer.py:655-676`，上限 60）：旧写法只看第一条源，
  30/60fps 混批时后半批会被按错误帧率重采样。一条都探测不到才回退 60fps。
- **island 拼接把裁剪点挪到输入侧**（`IslandConcat.py:222`、`:254`）：主体段与转场段原来都是 `-i` 之后
  `trim=start=...`，为了取每段尾部 1 秒要从第 0 帧解码整段；现改为 `-ss` 在 `-i` 之前、滤镜只做
  `trim=duration`。重编码下 `-ss` 仍是帧级精确，产物不变，只是不再白解前导。
- **libx264 回退带上目标码率**（`IslandConcat.py:126`）：旧兜底写死 `-crf 18`，硬编失败换软编后，
  产物码率与页面显示、指纹记录的不是一回事。现按 `-b:v/-maxrate/-bufsize`（2×）跟随目标码率。
- **编码器判据只留一份**：`RenderIO.resolve_encoder`（`:263`）把本批实际要用的 codec 写回
  `encoder_param['codec']`，指纹、每段 `-vcodec`、island 拼接与 CPU 回退读同一个值；硬编失败
  退回 libx264 时把结论写回（`SegmentUtils.py:547`、`:799`），清单改记软编，下一轮按真实编码器判废。
- **编码器下拉加入软件档（H.264/AVC 与 H.265/HEVC）**：`Variables.py:274` 的软编清单与
  `:288` 的 libx265 行；`RenderIO.probe_software_encoders`（`:219`）实探后与硬件档一起进页 6 的
  「编码器方案」，两类分别标【硬件】/【软件】——硬件实探通过不等于运行期一定编得动，软件档
  始终在列，随时能明确点名 CPU 渲染。AVC 就是 H.264，原来的兜底 `libx264` 一直就是它，只是以前
  不能主动点名；现在点名软编也会走 `resolve_encoder` 的显式分支（否则 `hwaccel=False` 会被自动
  探测覆盖）。libx265 产物打 `hvc1` 标签；island 直拼按编码器选 `hevc_mp4toannexb`
  （`IslandConcat.py:102`），流拷贝到 mp4 时补回 hvc1（`:112`）。实测两条出片链路与 island
  直拼/xfade 均为 `hevc/hvc1`，时长与帧数不变。
- **AV1 解码后端自动探测（2026-10-18）**：Windows 上 AV1 源默认走
  MSMF（实测 28.1→11.9ms/帧），H.264 留在 FFMPEG（16.6 vs 11.7ms）。但 MSMF 对解不了的流
  **不是返回失败，而是 open 成功、`read()` 挂住**（4:4:4 AV1 实测 >60s），低端 GPU 没有 AV1
  硬解时不能盲切。页 6（仅 Quadrants 路）在每进程首次遇到 AV1 源时用 ffmpeg debug 探针判
  本机/本流能否硬解——只认 `AV1 decode get format: d3d11`，返回码不可靠
  （强制 libdav1d、4:4:4 都是 rc=0），单次约 0.2s、按文件缓存；能硬解才用 MSMF，否则 FFMPEG。
  不给用户选项，页面上只留「重新探测」清除缓存（换驱动/显卡后重试）。经
  `RenderContext` → `VideoFrameReader` 落地。
  实测矩阵：1080p 4:2:0 AV1 自动→MSMF、强制 FFMPEG→FFMPEG、4:4:4 自动→FFMPEG 且正常出帧；
  H.264 不受影响，始终 FFMPEG。
- **编码失败只允许同族回退**：`Variables.fallback_encoder_on_failure` 只让 H.264 硬编失败退回
  `libx264`；H.265 失败不再静默换 H.264——同批片段会跨编码族，最终 `concat -c copy` 接不起来
  （逐段都能播，整支坏片）。`SegmentUtils.py` 两处逐段兜底与 `IslandConcat.py:148` 各阶段共用这一条
  判据；没有同族兜底时该段/该阶段明确失败并上报，不再产出混合编码的成片。
- **输出帧率进入全局指纹**（`SegmentUtils.py:127`）：GPU 路把探测值写回 `encoder_param['fps']`，
  经典路默认 `DEFAULT_FPS`；两条路共用片段目录，指纹不含 fps 时 30fps 片段会被 60fps 那批判"新鲜"
  直接复用，成片出现每帧复制的顿挫。代价是升级后第一次整轮重编一次（预期）。
- **缺 main 必须走失败通道**：GPU 路与经典路各有一道守卫（`QuadRenderer.py:702`、`SegmentUtils.py:1237`），
  GPU 守卫在 `makedirs` 之前，不会留下空目录/清单冒充渲过。
- **指纹补上 `bg_offset`**（`SegmentUtils.py:148-166`）：背景按前序片段累计时长取模起播，前序时长一变，
  本段背景起点就变；旧指纹不含它，会复用起点错误的旧片段。经典/GPU 两条路现在用同一个累计口径
  （`SegmentUtils.py:1260-1263`、`QuadRenderer.py:738-746`）。
- **转场时长只在启用时进全局指纹**（`SegmentUtils.py:108-146`）：禁用转场时改时长不再无谓判废；
  启用时（含 GPU 路 xfade 的 `trans_time`）必须进，否则改时长会沿用旧片段。
- **无音轨谱面不再把 GPU 路编死**：`RenderIO.py:701` 先用 `ffprobe -select_streams a:0` 探音频流，
  没有就切 `anullsrc` 静音轨（`:767-771`），不再出现 `[1:a]atrim` 绑不到流 → `BrokenPipeError` →
  三次重试 → CPU 全量重渲。实测 1 秒无音轨素材照常出片，产物含与视频同长的静音轨。
  同批把音频补白改成 `apad` 后 `atrim` + `asetpts` 精确收回：2 秒音频配 1 秒片段，产物音频是 1.0 秒。
- **worker 收尾不再抹掉新任务**（`SafeRender.py:257-291`）：先清理 `temp_generated`，**再**在
  `_submit_lock` 内按 job 身份复位；旧顺序里清理耗时可能跨过下一次提交，迟到的 finally 会把新任务
  的状态清成空闲。
- **GPU 按钮由探针决定**（`SafeRender.py:187`）：页面线程只做 `find_spec` 查依赖（缺 pydantic/cffi 时
  点名），CUDA 初始化只发生在常驻渲染线程；上一次渲染落在 CPU 后端的直接判不可用并说明原因。
  页 6 的实验按钮改为 `disabled=not _gpu_ok`，不可用时给出一行可见说明
  （`st_pages/6_Compostie_Videos.py:451-469`）。
- **版本与文档收口**：`check_ffmpeg_version()` 原来只有定义没有调用点，现在 `FFmpegWriter`
  （`RenderIO.py:752`）与两个拼接入口（`IslandConcat.py:324`、`:455`）都会先查；Quadrants 的
  "编译必须在主线程"旧说法改为"编译与执行在同一常驻线程"；`requirements.txt:34` 的
  `quadrants==1.3.0` 改为 `==1.3.3`，与随包 runtime 实测版本对齐（旧文写的"本机 1.0.2"已过期），
  `pydantic`/`cffi` 显式入列。

### 测试与验证口径

- `tests/test_paths_io.py` **52 项**（2026-10-18 复跑）、`tests/test_ffmpeg_merge.py` **26 项**，都在**还原后的半装 `runtime/`** 上跑
  到 `失败 0 项`（GBK 控制台直跑也不中断，即上一节那条）。分组：A 判据 / B 存档识别 /
  C 原子写并发（含"并发读写期间任何时刻都是完整文档"）/ D 页 1 空白存档 / E 判据唯一性 /
  F 渲染与临时目录不变量 / G 控制台编码 / H 迁移 / I 页 3 不变量。
- `tests/test_render_freshness.py` **215 项**（2026-10-18，`runtime/python.exe` 直跑）到
  `合计 215 项，失败 0 项`：渲染指纹、缺素材分段失败、frame-pump 时间基重采样、最大源帧率、
  island 输入侧裁剪、无音轨静音轨、音频精确收回、worker 收尾顺序、GPU 预检与编码器软编档都在内；
  音频两例走真实 ffmpeg 出片后用 ffprobe 复量，不是纯源码断言。另跑过一次真实主片段渲染
  （30fps 谱面源、60fps 输出、160×120、Quadrants CPU 后端）：成片 **1.000s / 60 帧 / 60fps**，
  音频 1.023s（AAC 帧长补齐），确认帧率换算没有改变片段时长。
- libx265 另做了一次真实出片验证（2026-10-18）：写帧器直出 30 帧 / 1.0s、经典路片段与成片、
  island 直拼 2 段与 xfade 2 段、最后的 loudnorm 拷贝，ffprobe 全部为 `hevc` + `hvc1`，
  帧数与时长与输入一致；island 直拼在补 `hevc_mp4toannexb` 前后各跑过一次。
- 源码级断言一律用 AST 或"必须出现的调用形状"，并在**改前基线 `cd322c3`（v1.2.6）**上做过反向验证
  （改前必红）：`git show cd322c3:<file>`。原先写作 "HEAD" 会随新提交过期，这里钉死 SHA。
  F6（`toast("渲染完成！")` 的行号必须落在 `_failed` 分支区间内）、I1–I6 都这样做过；否则就是恒真断言。
- 页 3 用 `streamlit.testing.v1.AppTest` 在沙盒里真跑起来并出过截图（`output/visual/page3_render.png`）；
  同一沙盒喂 `cd322c3`（v1.2.6）的页 3 能复现原崩溃：`cd322c3:st_pages/3_Confirm_Videos.py:956 → update_editor:503 → IndexError`。
- 选流与合并链路（E/D 组 + A/B/C 组）在无网络、无用户素材的条件下验；真实下载与真实凭证改写各跑过一次，
  数字见「未生成有效视频文件」与「B 站登录态」两节。

### 发布包体检（dist/ 里两份包 vs 工作树）

包已挪到 `dist/`（`.gitignore:27` 覆盖），里面现存两份：`chu-gen-videob30-v1.2.6.zip`（2026-09-20 13:54，
61,772,448 字节，144 个文件，未压缩 72.85MB）与 `chu-gen-videob30-v1.2.6a.zip`（2026-10-02 16:35，
53,950,830 字节，247 个文件，未压缩 66.61MB）。逐条比过清单：

- **v1.2.6a 不是 `script/build_release.ps1` 出的**：脚本在打包前会把 payload 里的 `__pycache__` /
  `.pytest_cache` / `.ipynb_checkpoints` 目录与 `.pyc` / `.pyo` / `.tmp` 整批剥掉（`:163-167`），
  而这份包里有 **117 个 `.pyc`**（未压缩多 2.67MB），包括**已删页面的孤儿字节码**
  `st_pages/__pycache__/2_Search_For_Videos-ori.cpython-313.pyc`、`2_Search_For_Videoes_old.cpython-313.pyc`，
  以及一批 **cpython-313** 的缓存 —— 而包内 `runtime/` 是 3.12。等于热修包**绕过了脚本的四道前置拦截**
  （`$RequiredRel` 承重缺失、悬空 import、疑似凭证、构建后回读校验）。
  影响要分级说清：**不会跑错代码** —— 源码都在包里，`.pyc` 只在源文件 mtime+size 对得上时才复用，
  对不上就重编；页面导航是显式 `st.Page`，孤儿 pyc 不会被当成页面。代价是包体卫生 + **这版没跑过承重清单**
  （1.2.6a 恰好不缺文件，是我逐 md5 验出来的，不是脚本挡出来的）。
- **v1.2.6 的「仓库清理」确实落进了包里**：v1.2.6a 相对 v1.2.6 少 14 个文件、省 6.92MB —— 11 份 `-bak`
  （`bg_bak.mp4` 4.55MB、`bgm_bak.mp3` 1.33MB、`content_base-bak.png`×2、`init/{2,3,4}-bak`、
  `Frames/{0,2,3,4}-bak`）+ `Base/content/versions/jp-mate.webp` + 死页面 `st_pages/2_Search_For_Videos.py`
  + `utils/VideoUtils.py`。与 v1.2.6 那节的清单逐项对上。
- **素材没有停在旧状态**（这条是好消息）：包里 `assets/Audios/bgm.mp3` = 1,390,091 字节、
  `assets/BgClips/bg.mp4` = 16,549,117 字节，**都与工作树当前值一致**；v1.2.6 包里还是旧的
  4,801,509 / 15,283,775。也就是 bgm 换小、bg 换过两版之后，热修包带的是新的一份。
- **随包 CHANGELOG 的口径从 v1.2.6a 起变了**：v1.2.6 包里那份只有 **764 字节**（占位/摘录件 —— 包出在
  9-20 13:54，而 `cd322c3 v1.2.6` 这个 commit 在 9-21 01:30，全量文档是事后写的），v1.2.6a 包里是
  **33,355 字节的全量工程台账**（含已知问题与实测数字），工作树现在是 55,707 字节。
  所以 v1.2.6 那节末条"随包分发的是这份全量口径"**对 v1.2.6 包并不成立，从 1.2.6a 才成立**。
- **`runtime-licenses/` 没接进任何发布环节**：里面有 `FFmpeg-LICENSE.txt`（35,147 字节）与 `SOURCES.txt`
  （265 字节，记的是 Python 3.12.10 与 "FFmpeg 7.1 Windows full build" + 源码包链接）。
  `build_release.ps1` 全文不引用它，`setup_runtime.ps1` 也不引用 —— 于是**带 runtime 那条链没有把许可证一起带上**。
  顺带核了一遍 ffmpeg 的三处口径，跑 `-version` 实测（只读 banner，不转码）：
  **当前仓库根这两份是同一套 release，不是两个日期的 nightly** —— `ffmpeg 7.1-full_build-www.gyan.dev`
  与 `ffprobe 7.1-full_build-www.gyan.dev`，`libavcodec 61.19.100`、`libavformat 61.7.100` 两边逐字相同，
  与 `SOURCES.txt` 记的 7.1 full build 相符；NVENC 编码器在位（`-encoders` 里 3 个 nvenc）。
  ⇒ v1.2.6 那节「随包 ffmpeg 与 ffprobe 来自不同 commit 的 nightly，建议换成套 release 构建」这条**对现在这两份
  已经不成立**（换过了，或当时量的是别的文件）。历史那节没改，修正记在这里。
  **连带影响**：v1.2.6 的「视频合成 · 测试环境与口径」那条写的也是"随包 ffmpeg `2026-04-16-git` 构建"，
  也就是说那整批性能表（1080p 单片段 52.69s → 13.9s、50 段全片约 44 分钟 → 约 15 分钟等）是在
  **另一个构建**上测的。要引用它们得按现在这对 7.1 release 重跑一遍，或至少在对外说明里注明测量环境。
  还剩一处对不上：`setup_runtime.ps1:60` 下载的是 **9.0.1 essentials**
  （`gh.zwy.one/github.com/GyanD/codexffmpeg/releases/download/9.0.1/…`）—— 与现在包外这对 7.1 full 不是同一条线。
- **两份 dist 包都是纯源码包**：`unzip -l` 里 `ffmpeg.exe` / `ffprobe.exe` / `start.bat` / `runtime/` 命中数都是 **0**
  （与 `$NeverShip` 一致）。所以"用户机器上的 ffmpeg 从哪来"发生在**这条链之外**的装配步骤里，
  `runtime-licenses/` 要接的正是那一步。

### 已知问题（1.2.6a 遗留）

- ~~**`st_app.py` 的 chdir 与 utils 导入顺序对不上注释**~~ —— **本轮已改**：那条 import 从 `:1` 挪回
  `os.chdir`（`:10`）之后的 `:12`，与注释一致了。改前先证过它当时并无实害（`utils/*.py` 没有模块级 cwd 求值），
  所以这一条是"假规矩"而不是 bug；详见「曲库镜像对账」末条。
- **`check_refresh → save_credential` 那条真实分支没被观测到**：需要一个临期 token 才能走到，实测的 pkl 改写
  来自另一条路径。上线后要盯"登入后隔天失效"的反馈。
- **`runtime/` 的半装状态本轮没修**（明确要求不动 runtime）。想修的人：先关掉正在运行的应用，否则 `.pyd`
  占用会 WinError 5；`pip check` 会直接把 yarl/Brotli 与 aiohttp 的冲突报出来。新装按 `requirements.txt` 不受影响。
- `fetch_settings.py:153` 的列宽 `[1, 0.35, 1.35]` 在窄窗口下会把「使用代理」那一行挤成一列竖排 —— 本轮之前的
  版式问题，没动（改它会连带影响面板里其它行的对齐，按一次只改一个变量单独处理）。
- 挂着的两处一致性：`check_matched_songs`（`3_Confirm_Videos.py:286`）第三个返回值仍无人使用；缓存索引跨存档
  来回切换会互相顶掉条目（`videos/downloads` 是同一目录、两存档共用）。
- ~~`quadrants` 缺 `cffi` / `pydantic`，且 `requirements.txt` 钉 `==1.3.0` 而本机实测 1.0.2~~
  —— **已收口（2026-10-18）**：随包 runtime 实测 `quadrants 1.3.3`（llvm 22.1.0 / commit 00423caa），
  `requirements.txt:34` 已对齐 `==1.3.3`，并把 `pydantic>=2,<3`、`cffi>=1.16` 显式写进依赖（`:38-39`）。
  GPU import 仍包在 try 里，缺它不挡下载与渲染主路。
- ~~**`httpx` 是裸名没钉版本**~~ —— **本轮已钉**：`requirements.txt:29` 改为 `httpx>=0.24,<1.0`，与
  `video_crawler.py:18` 提示语里承诺的下限对上。随包那份实测 0.26.0，在区间内；`anyio` 实测 4.11.0。

### 发行包注意（1.2.6a）

- 版本号 `st_pages/0_homepage.py:98` 仍写 **v1.2.6**。
- `tests/`（3 个文件）与 `runtime-licenses/` **未跟踪**（都不在 `.gitignore` 里，是 `??` 状态）。
  发布包已挪进 `dist/`，而 `dist/` 早在 `.gitignore:27` —— 所以**根目录那份 zip 的噪声问题不存在了**，
  不需要再加 ignore 条目。`tests/` 不进客户端包（`script/build_release.ps1` 的 `$Dirs` 不含它）。
- 只覆盖 `utils/video_crawler.py` 一个文件仍能修好已装用户的下载（测试 G4）；**但本轮之后这条不再充分**：
  页 3 的下载闸门、产物判据与路径锚定分布在 `st_pages/3_Confirm_Videos.py`、`utils/PathUtils.py`、
  `utils/DataUtils.py`，单发一个文件会让"闸门说没素材"与"判据说已生成"互相矛盾。给老包补热修时要按这一节
  的文件清单一起发。

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
  注：~~这条还没覆盖全~~ —— **2026-10-18 已补齐**：主视频配置缺失时经典路 `SegmentUtils.py:1237`
  与 GPU 路 `QuadRenderer.py:702` 都改走失败通道（不再裸 `return`/渲染出没有正片的成片）；
  `SafeRender` 也把回退补渲返回的失败列表转为 `RuntimeError`，不再带着缺段继续拼接。
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
- ~~**本机 `quadrants` 实测是 1.0.2，而 `requirements.txt` 钉 `==1.3.0`**~~ —— **已对齐（2026-10-18）**：
  随包 runtime 实测 1.3.3，`requirements.txt:34` 改为 `==1.3.3`。**注意**：下文「视频合成 · 性能」里
  那批 GPU/经典对比数字仍是在 1.0.2 上测的，未在 1.3.3 重跑，不能当作当前版本的结论。
- `generate()` 标了 `-> bool`（`utils/SegmentUtils.py:297`、`:539`），失败路径实际 `return None`（`:382`、`:612`）；
  另外 `_get_full_image_path` 在 `bg_page=True` 且不检查文件是否存在就返回绝对路径（`:417`），与"渲染失败不落盘"的约定相反。

### 已知问题（视频合成）

- ~~`assets/BgClips/bg.mp4` 在 40.283s 处有一个全黑帧~~ —— **已解决**：素材于 09-19 20:48 换过一次、09-20 14:23 又换过一次，
  当前这份实测 **3028 帧 / 50.47s**（ffprobe），`blackframe=amount=2:threshold=16` 全片扫描零命中。
  对外说明里的"背景黑帧已知问题"已随之删除。
  注意所有以"bg 长 60.4s"为前提的旧数字现在对应 50.47s（取模逻辑不变，回绕点变密）。
- **两后端成片时长与过渡形态不一致**：经典路淡入黑场 + `-c copy` 不缩时长；GPU 路 `xfade` 交叉淡化，每个边界吃掉 `trans_time`
  （同素材实测成片 12.049s vs 10.578s）。页 6 的注意事项现在把这条差异直接写给用户（两种按钮的过渡方式，
  以及它们会互相作废对方渲好的片段）。
- ~~GPU 路取消任务会落到没有取消检查点的 CPU 全量重渲~~ —— **已修（2026-10-18）**：`RenderCancelled`
  被管线 `except BaseException` 重包成普通 `RuntimeError` 后，`SafeRender` 认不出它是取消。现在片段重试前
  先过 `render_checkpoint()`（`QuadRenderer.py:787`），island 的重编码回退也先 `_reraise_if_cancelled`
  （`IslandConcat.py:70`、`:157/:284/:418`）；实测取消抛 `RenderCancelled`，不再回退软编或 CPU 全量重渲。
- ~~无音轨的谱面素材会让 GPU 路崩~~ —— **已修（2026-10-18）**：`RenderIO.has_audio_stream`（`:676`）先探测，
  缺失则切 `anullsrc` 静音轨（`:742-746`）；实测 1 秒无音轨素材照常出片。
- ~~经典路整条渲染仍阻塞 Streamlit 主线程~~ —— **已修（2026-10-18）**：页 6 的「开始渲染」改为提交
  `SafeRender` 常驻工作线程（`prefer="classic"`），脚本线程立即返回；经典/GPU 两路共用进度浮窗与取消。
- ~~随包 `ffmpeg.exe` 与 `ffprobe.exe` 是 nightly git 构建且日期不同~~ —— **已换**：当前随包是同一套
  `7.1-full_build-www.gyan.dev` release，`ffmpeg -version` / `ffprobe -version` 首行一致。
- `requirements.txt` 已声明 `quadrants==1.3.3`（GPU 后端唯一依赖，`:34`）、`pydantic>=2,<3` / `cffi>=1.16`
  （`:38-39`，Quadrants 的传递依赖）与 `qrcode>=8.2`（B 站扫码登录）。
  Taichi 后端已于 2026-09-20 移除（长期不更新、与 Quadrants 功能区重叠，且 Quadrants 已把它的能力复制完），
  所以 `taichi` 不再需要；此前它也从不在 `runtime/` 内，本机那次 `import taichi` 成功是用户级 site-packages 泄漏。
- GPU 路在两种源上都比修后经典路慢（**以下数字全部测于 quadrants 1.0.2；随包已升到 1.3.3，未重测，
  不能当作当前版本的结论**。1080p/10s 单片段：H.264 源 7.90s vs 14.50s；AV1 源 9.89s vs 28.67s）。
  阶段消融显示合成阶段一开，两路解码各 +11ms、编码 +7.3ms，连带损失远大于它自己的 18ms；已排除 GIL 抢占、CPU 掉频、NVENC 队列争用。
  ~~出路是别让帧离开 GPU（NVDEC→GPU 合成→NVENC），或试 pinned memory~~ —— 两条都被否掉：**NVDEC 直连**与"qd 要全设备可用"冲突
  （且 Ampere 的 NVDEC 不解 AV1，正是最慢那批素材）；**pinned/零拷贝**拿不到（`qd.ndarray` 不接受外部指针，
  `to_numpy(copy=False)` 在 GPU 后端抛 `Zero-copy numpy requires a CPU backend`，批量 K=1..16 只省 0.2~0.6ms/帧）。
  真因在库里：`_ndarray.py:224-229/268-271` 显示每次 host↔device 都是"桥 kernel（每字节一个 GPU 线程）+ 一次全设备 `sync()`"，
  所以还能做的是减少往返次数（chart 折进 bg 只传一次）、绕开 `to_numpy` 的 `np.zeros`、`graph=True` 打散启动开销。

### 与其他工作线的交界

- 页 6 的硬件加速选择已合并（工作树 2026-10-18）：原「使用 GPU 硬件加速」复选框（`disabled=True`、
  恒 `False`）与挂在它身上的「加速方案」下拉都已删除，改为一个「编码器方案」下拉；选项来自
  `probe_hw_encoders()` 真编一帧后的实探结果，「自动」档就是渲染侧 `detect_hw_encoder()` 会用的那一个，
  不再在页面上写死 `libx264`。下拉里另有软件 H.264/AVC（libx264）与 H.265/HEVC（libx265）两档，
  后者同样先实探再列出；两类分别标【硬件】/【软件】，软件档始终在列，硬编运行期失败时用户仍可
  明确改回 CPU。点名任一项都会走 `resolve_encoder` 的显式分支。此前 `if hwaccel:` 分支恒
  不成立、`encoder_param['codec']` 恒为 `libx264` 的问题随之消失。对外发布说明仍不写"修复 GPU 加速
  复选框"——这不是修好一个旧开关，而是把两个控件合并成一个按实探结果工作的选择，再把软件档补齐。
- 页 6 的「Quadrants GPU 渲染（实验）」按钮**不再写死禁用**（2026-10-18）：改由 `gpu_preflight()` 决定，
  缺 pydantic/cffi 或上次渲染落在 CPU 后端时灰化，并在页面上给一行可见原因；依赖齐且探针未否定时可用。
  页面线程不做 GPU 初始化（CUDA/Vulkan，上下文有线程亲和性），探针只在常驻渲染线程跑。
  后端选择保持自动（CUDA → Vulkan → CPU，见下一条），与【编码器方案】的软/硬编无关；
  页面 caption 与按钮帮助文案都写明这一点，不把两个维度塞进同一个下拉。
- Quadrants 后端回退链补上 Vulkan（2026-10-18）：`init_quad()` 现在按 CUDA → Vulkan → CPU
  依次尝试（`qd.gpu` 在无 CUDA 设备时不会自动改选 Vulkan，实测直接抛 CUDA_ERROR_NO_DEVICE，
  必须显式 `qd.init(qd.vulkan)`）；`quad_backend()` 从 `'gpu'/'cpu'` 改为 `'cuda'/'vulkan'/'cpu'`，
  状态条与 `gpu_preflight()` 按真实后端说话；上下文故障判定同时识别 CUDA 的
  INVALID_CONTEXT 与 Vulkan 的 VK_ERROR_DEVICE_LOST。Intel Iris Xe 实测 init、5 个 kernel
  预热、main/info 合成与 20 片段 soak 通过，输出与 CUDA 最大差 1/255。Vulkan 只替换
  合成后端，编码器选择不变。
  另修一处记账错误：Vulkan loader/ICD 不可用时 `qd.init(qd.vulkan)` **不抛异常**，只打印
  `falling back to CPU` 并把运行时建在 x64 上；旧实现按入参记账，会把 CPU 误报成 Vulkan。
  现在 init 后用 `qd.cfg.arch` 复核实际后端，链中间的 GPU 候选若静默降级 CPU 就 reset
  并继续试后续候选（无 CUDA + Vulkan ICD 无效时实测正确落到 `cpu`）。

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
