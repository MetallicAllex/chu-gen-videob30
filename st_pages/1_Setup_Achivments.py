import time
import streamlit as st
import os, json, traceback
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import *
from utils.DataUtils import _process_b50_data, st_init_cache_pathes, update_b50_data
from utils.Variables import jp_music_info_path, music_info_path

st.set_page_config(
    page_title="获取 / 管理 Best50 成绩与存档",
    page_icon="💾",
)

st.header("获取 / 管理 Best50 成绩与存档")

def check_username(input_username):
    # 检查用户名是否包含非法字符
    if any(char in input_username for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
        return escape_markdown_text(input_username), input_username
    else:
        return input_username, input_username
    
def read_raw_username(username):
    userinfo_file = os.path.join(get_user_base_dir(username), "user_info.json")
    # 优先从新系统读取
    if os.path.exists(userinfo_file):
        data = load_config(userinfo_file)
        return data.get("legacy_raw_username", data.get("username", username))

# ========== 新增：自动加载用户配置 ==========
def load_user_info_from_file(username):
    """从 user_info.json 加载用户数据到 session_state"""
    if not username:
        return False
    
    user_info_path = os.path.join(get_user_base_dir(username), "user_info.json")
    if os.path.exists(user_info_path):
        try:
            user_info = load_config(user_info_path)
            # 更新 session_state
            st.session_state.update({
                "username": user_info.get("username", username),
                "friend_code": user_info.get("friend_code", ""),
                "use_lxns": user_info.get("use_lxns", False),  # 从文件读取实际状态
                "config_saved": True
            })
            return True
        except Exception as e:
            return False
    return False

# 初始化会话状态
if 'use_lxns' not in st.session_state:
    st.session_state.use_lxns = False
if 'config_saved' not in st.session_state:
    st.session_state.config_saved = False

# ========== 新增：自动加载已存在用户的配置 ==========
username = st.session_state.get("username", None)
# 如果有用户名但没有标记为已配置，尝试从文件加载
if username and not st.session_state.get('config_saved', False):
    load_user_info_from_file(username)

# 重新获取更新后的值
username = st.session_state.get("username", None)
save_id = st.session_state.get('save_id', None)
friend_code = st.session_state.get("friend_code", None)
use_lxns = st.session_state.get("use_lxns", False)

with st.container(border=True):
    input_username = st.text_input(
        "用户名 / 绑定 QQ 号（水鱼查分器所需）",
        value=username if username else "", 
        placeholder="建议用户名，便于辨认且方便水鱼查分（不要输入任何符号）"
    )
    
    # 添加复选框控制是否显示好友码输入框
    use_lxns = st.checkbox(
        "我使用落雪查分器（填写/更新后请勿再次勾选，避免反复更新导致好友码丢失）", 
        value=use_lxns,  # 使用更新后的值
        help="如果您使用落雪查分器作为数据源，请勾选此项"
    )
    
    # 根据复选框状态决定是否显示好友码输入框
    if use_lxns:
        col1, col2 = st.columns([0.75, 0.2], vertical_alignment='bottom')
        with col1:
            friend_code = st.text_input(
                "好友码（落雪查分器所需）",
                value=friend_code if friend_code else "",
                placeholder="使用落雪查分（首次）必须提供此项，否则查询将失败",
                help="""
                不知道好友码在哪？
                - 访问 [【账号详情】页](https://maimai.lxns.net/user/profile) 查看
                
                为什么我提供了好友码，仍然无法查询数据？
                - 请确保您在 [【账号设置】页](https://maimai.lxns.net/user/settings) 开启了所有读取权限
                """
            )
        with col2:
            if st.session_state.get('config_saved', False):
                # 已保存配置，显示更新按钮
                if st.button("更新好友码", width='stretch'):
                    if not friend_code.strip():
                        st.toast("请输入好友码", icon="❌")
                    elif int(friend_code[:2]) == 99 or int(friend_code[:2]) != 10:
                        st.toast("请输入对应游戏的好友码", icon="❌")
                    else:
                        username = st.session_state.get("username")
                        if username:
                            userinfo_file = os.path.join(get_user_base_dir(username), "user_info.json")
                            if os.path.exists(userinfo_file):
                                user_info = load_config(userinfo_file)
                                
                                # 更新好友码
                                user_info["friend_code"] = friend_code.strip()                                
                                save_config(userinfo_file, user_info)
                                
                                st.session_state.friend_code = friend_code.strip()
                                st.toast("好友码已更新！", icon="✅")
                            else:
                                st.toast("未找到用户信息文件", icon="❌")
                        else:
                            st.toast("未找到用户名", icon="❌")
    
    # 显示"确定"按钮
    if st.button("确定", width='stretch'):
        if not input_username:
            st.error("用户名不能为空！", icon="❌")
            st.session_state.config_saved = False
        else:  
            # 输入的 username 作为文件夹路径，需要去除非法字符
            username, raw_username = check_username(input_username)
            root_save_dir = get_user_base_dir(username)
            if not os.path.exists(root_save_dir):
                os.makedirs(root_save_dir, exist_ok=True)
            
            # 创建或更新 JSON 文件用于保存用户数据
            userinfo_file = os.path.join(root_save_dir, "user_info.json")
            user_info = {}
            
            # 如果用户信息文件已存在，先加载现有数据
            if os.path.exists(userinfo_file):
                user_info = load_config(userinfo_file)
            
            # 更新用户信息
            user_info["username"] = username
            user_info["use_lxns"] = use_lxns  # ========== 新增：保存复选框状态 ==========
            
            # 只有在使用落雪查分器时才保存或更新好友码
            if use_lxns and friend_code and friend_code[:2] == 10:
                user_info["friend_code"] = friend_code.strip()
            # 如果不使用落雪查分器，但之前有好友码，保留原有好友码
            elif "friend_code" in user_info:
                # 保留原有好友码，不做修改
                pass
            else:
                # 既不使用落雪查分器，也没有原有好友码，设置为空
                user_info["friend_code"] = ""
            
            # 保存用户信息
            save_config(userinfo_file, user_info)
            
            st.toast("用户信息已保存！", icon="✅")
            st.session_state.update({
                "username": username,
                "friend_code": user_info.get("friend_code", ""),
                "use_lxns": use_lxns,
                "config_saved": True
            })

# def update_b50(update_function, secret_identifier, save_paths, best_new, server, query_param: dict = None):
#     try:
#         # 1. 强制加载用户名（完全隔离好友码）
#         def get_safe_display_name():
#             """从session_state或文件获取真实用户名，绝不使用传入的secret_identifier"""
#             # 优先从session获取
#             safe_name = st.session_state.get("username", None)
#             if safe_name: 
#                 return safe_name
                
#             # 次之从user_info.json获取
#             user_info_path = os.path.join(get_user_base_dir(secret_identifier), "user_info.json")
#             if os.path.exists(user_info_path):
#                 user_info = load_config(user_info_path)
#                 return user_info.get("username", "用户")
#             return "用户"  # 最终回退

#         safe_name = get_safe_display_name()

#         # 2. 执行数据获取（原逻辑不变）
#         b50_data = update_function(save_paths['raw_file'], save_paths['data_file'], secret_identifier, best_new, server, query_param)
        
#         # 3. 绝对安全显示
#         if "error" not in b50_data:
#             st.toast(f"已获取 {safe_name} 的游戏数据", icon="✅")
#             st.toast("请检查 b50_config.json 是否有内容，如没有则为清洗失败", icon="⚠️")
#             st.session_state.data_updated_step1 = True
#             st.session_state.config_saved = True
#             return b50_data
#         else:
#             st.error(f"获取 {safe_name} 的游戏数据失败: {b50_data['error']}", icon="❌")
#             time.sleep(5)
#             st.rerun()

#     except Exception as e:
#         st.session_state.data_updated_step1 = False
        
#         # ========== 新增：删除存档文件夹 ==========
#         save_dir = os.path.dirname(save_paths['data_file'])
#         if os.path.exists(save_dir):
#             try:
#                 import shutil
#                 shutil.rmtree(save_dir)
#                 st.toast(f"已删除本次获取的存档文件夹", icon="🗑️")
#             except Exception as rm_error:
#                 print(f"删除存档文件夹失败: {rm_error}")
        
#         # 4. 错误信息核级过滤
#         error_msg = str(e)
#         filtered_msg = error_msg.replace(secret_identifier, "[已过滤]")  # 暴力替换所有可能泄露
        
#         st.toast(filtered_msg, icon="❌")
#         st.expander("详细错误信息（请将这部分内容拷贝或截图发给开发者）：", icon="⚠️").write(traceback.format_exc())  # 确保traceback也过滤
#         return None

def update_b50(update_function, secret_identifier, save_paths, query_param):
    print(query_param)
    try:
        # 1. 强制加载用户名（完全隔离好友码）
        def get_safe_display_name():
            """从session_state或文件获取真实用户名，绝不使用传入的secret_identifier"""
            # 优先从session获取
            safe_name = st.session_state.get("username", None)
            if safe_name: 
                return safe_name
                
            # 次之从user_info.json获取
            user_info_path = os.path.join(get_user_base_dir(secret_identifier), "user_info.json")
            if os.path.exists(user_info_path):
                user_info = load_config(user_info_path)
                return user_info.get("username", "用户")
            return "用户"  # 最终回退

        safe_name = get_safe_display_name()

        # 2. 执行数据获取（原逻辑不变）
        b50_data = update_function(save_paths['raw_file'], save_paths['data_file'], secret_identifier, query_param)
        
        # 3. 绝对安全显示
        if "error" not in b50_data:
            st.toast(f"已获取 {safe_name} 的游戏数据", icon="✅")
            st.toast("请检查 b50_config.json 是否有内容，如没有则为清洗失败", icon="⚠️")
            st.session_state.data_updated_step1 = True
            st.session_state.config_saved = True
            return b50_data
        else:
            st.error(f"获取 {safe_name} 的游戏数据失败: {b50_data['error']}", icon="❌")
            time.sleep(5)
            st.rerun()

    except Exception as e:
        st.session_state.data_updated_step1 = False
        
        # ========== 新增：删除存档文件夹 ==========
        save_dir = os.path.dirname(save_paths['data_file'])
        if os.path.exists(save_dir):
            try:
                import shutil
                shutil.rmtree(save_dir)
                st.toast(f"已删除本次获取的存档文件夹", icon="🗑️")
            except Exception as rm_error:
                print(f"删除存档文件夹失败: {rm_error}")
        
        # 4. 错误信息核级过滤
        error_msg = str(e)
        filtered_msg = error_msg.replace(secret_identifier, "[已过滤]")  # 暴力替换所有可能泄露
        
        st.toast(filtered_msg, icon="❌")
        st.expander("详细错误信息（请将这部分内容拷贝或截图发给开发者）：", icon="⚠️").write(traceback.format_exc())  # 确保traceback也过滤
        return None


@st.dialog("删除存档？", width="medium")
def delete_save_data(username, save_id):
    version_dir = get_user_version_dir(username, save_id)
    st.warning(f"""
               您是要删除【{username} - {save_id}】吗？
               - 将清除所有已生成 Best50 底图和视频，且不可撤销！
               """, icon="⚠️")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("是的！我要删除它！", icon="✔️", width='stretch'):
            # 迭代地删除文件夹version_dir下的所有文件和子文件夹
            for root, dirs, files in os.walk(version_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(version_dir)
            st.toast(f"已删除存档【{username} - {save_id}】", icon="✅")
            st.rerun()
    with col2:
        if st.button("不了，也许哪天会用？", icon="✖️", width='stretch'):
            st.rerun()

def load_user_info(username):
    """从 user_info.json 加载用户数据到 session_state"""
    user_info_path = os.path.join(get_user_base_dir(username), "user_info.json")
    if os.path.exists(user_info_path):
        try:
            user_info = load_config(user_info_path)
            # 更新 session_state
            st.session_state.update({
                "username": user_info.get("username", username),
                "friend_code": user_info.get("friend_code", ""),
                "use_lxns": user_info.get("use_lxns", False),  # 从配置读取实际状态
            })
            return True
        except Exception as e:
            st.error(f"加载用户信息失败: {e}", icon="❌")
            return False
    return False

st.divider()
if st.session_state.get('config_saved', False):
    raw_username = read_raw_username(username)

    st_init_cache_pathes()

    st.write("b50 存档读取 / 编辑")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            st.info(f"新存档可能无法立刻显示，单击其他存档即可刷新。", icon="ℹ️")
            selected_save_id = st.selectbox(
                "选择一份已保存的存档",
                versions,
                format_func=lambda x: f"{x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
            )
            col1, col2, col3 = st.columns(3, gap="small")
            with col1:
                if st.button("加载此存档", icon="▶️", width='stretch'):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        if load_user_info(username):
                            st.toast("已加载您的存档。", icon="✅")
                            if use_lxns:
                                st.session_state.friend_code = friend_code
                                st.toast("您的好友码已恢复至生成器内，您现在可以获取落雪查分器数据了。", icon="ℹ️")
                        else:
                            st.warning("存档加载成功，但未找到用户信息（可能需要重新输入好友码）。", icon="⚠️")
                        st.session_state.data_updated_step1 = True
                        st.session_state.config_saved = True
                        time.sleep(3)
                        st.rerun()
                    else:
                        st.error("未指定有效的存档路径！", icon="❌")
            with col2:
                version_dir = get_user_version_dir(username, selected_save_id)
                if st.button("打开文件夹", icon="📂", help=version_dir, width='stretch'):
                    if os.path.exists(version_dir):
                        absolute_path = os.path.abspath(version_dir)
                    else:
                        absolute_path = os.path.abspath(os.path.dirname(version_dir))
                    open_file_explorer(absolute_path)
            with col3:
                if st.button("删除存档", icon="🗑️", width='stretch'):
                    delete_save_data(username, selected_save_id)

    else:
        st.warning(f"{username} 还没有历史存档，请从下方获取新的 Best30 数据。", icon="⚠️")

    st.divider()
    st.write(f"新建 / 获取 b50 数据")
    st.info("""
            从下面选择您使用的查分器获取 Best50 数据，系统将为您创建存档。
            - 【水鱼】需关闭 [（禁止其他人查询我的成绩）](https://www.diving-fish.com/maimaidx/prober/#Profile)以允许用户名查询
            - 【落雪】加载存档后若下方未出现【已保存好友码】提示，请重新加载
            """, icon="ℹ️")
    with st.container(border=True):
        metadata_status = os.path.exists(music_info_path) and os.path.exists(jp_music_info_path)
        if not metadata_status:
            st.error("""
                    您的包体未拥有谱面数据，请回到首页下载！
                    - 刚下载的新包体**默认未携带谱面数据**，**已经用过但文件不存在**则可能是被误删
                    - 生成器任何操作**均基于此数据完成**，您*必须*要有这份数据后才能继续
                    """, icon="❗")
        with st.expander("我玩国服", icon="🔴"):
            stat_col1, stat_col2 = st.columns(2)
            with stat_col1:
                st.warning("【落雪】请确保存档中已保存有好友码，否则无法获取游戏数据。", icon="⚠️")
            with stat_col2:
                # 显示当前好友码状态（如果有）
                if st.session_state.get("friend_code"):
                    st.info(f"【落雪】已存好友码: ******{st.session_state.friend_code[11:]}", icon="ℹ️")
                else:
                    st.info(f"您的存档中没有保存好友码，是要用水鱼吗？", icon="ℹ️")
                    
            data_col1, data_col2, data_col3 = st.columns(3, vertical_alignment="center", gap="small")
            data_params = {"data_server": "fish", "lxns_data_api": None, "best_or_new": "全都要"}
            with data_col1:
                data_server = st.radio("查分器数据源", ["lxns", "fish"], index=1, captions=["落雪查分器（需 API 代理）", "水鱼查分器"],
                                            disabled=not metadata_status, key="select_data_server", width="stretch", horizontal=True,
                                            help="如果选择落雪，请确保已保存好友码，否则无法获取游戏数据。水鱼则确保用户名相同")
                data_params["data_server"] = data_server
            with data_col2:            
                lxns_data_api = st.radio("落雪数据源接口", ["主 API", "备用 API"], index=0, captions=["由 @赛因斯没有坦 提供", "由 @天藍_空韻 提供"],
                            disabled=not metadata_status or data_server=="fish", key="select_lxns_data_api", horizontal=True, 
                            help="仅影响落雪的数据获取，水鱼不受影响" if data_server != "fish" else "水鱼默认接口已提供完整 best 数据，无需选择")
                data_params["lxns_data_api"] = lxns_data_api
            
            with data_col3: 
                best_or_new = st.radio("获取数据类型",["全都要", "仅旧曲", "仅新曲"], index=0, disabled=not metadata_status, horizontal=True, key="select_data_type",
                                    help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "国服与外服的设置相互分离", captions=["Best30 + New20", "Only Best30", "Only New20"])
                data_params["best_or_new"] = best_or_new

            if st.button("获取数据", icon="🔻", width='stretch', disabled=not metadata_status or (data_server=="lxns" and not st.session_state.get("friend_code"))):
                if data_server == "lxns" and not st.session_state.get("friend_code"):
                    st.error("未设置好友码！请在上方勾选'我使用落雪查分器'并输入您的好友码。", icon="❌")
                else:
                    try:
                        current_paths = get_data_paths(username, timestamp=None)
                        save_dir = os.path.dirname(current_paths['data_file'])
                        save_id = os.path.basename(save_dir)
                        if save_id:
                            os.makedirs(save_dir, exist_ok=True)
                            st.session_state.save_id = save_id
                            with st.spinner("正在获取数据。"):
                                update_b50(
                                    update_b50_data,
                                    st.session_state.friend_code if data_server == "lxns" else raw_username,
                                    current_paths,
                                    data_params
                                )
                    except Exception as e:
                        st.error(f"获取数据时发生错误: {e}", icon="❌")
                        
            # data_act_col1, data_act_col2 = st.columns(2)
            # with data_act_col1:
            #     if st.button("从落雪查分器获取", help="您缺少所需的参数以从此查分器获取游戏数据" if not (metadata_status or not st.session_state.get("friend_code")) else "将使用您的好友码作为验证参数向代理请求游戏数据",
            #                  icon="❄️", width='stretch', disabled=not (metadata_status or not st.session_state.get("friend_code")) or not st.session_state.get("friend_code")):
            #         if not st.session_state.get("friend_code"):
            #             st.error("未设置好友码！请在上方勾选'我使用落雪查分器'并输入您的好友码。", icon="❌")
            #         else:
            #             try:
            #                 current_paths = get_data_paths(username, timestamp=None)
            #                 save_dir = os.path.dirname(current_paths['data_file'])
            #                 save_id = os.path.basename(save_dir)
            #                 if save_id:
            #                     os.makedirs(save_dir, exist_ok=True)
            #                     st.session_state.save_id = save_id
            #                     with st.spinner("正在获取数据。"):
            #                         update_b50(
            #                             update_b50_data,
            #                             st.session_state.friend_code,
            #                             current_paths,
            #                             best_or_new,
            #                             "lxns",
            #                             None
            #                         )
            #             except Exception as e:
            #                 st.error(f"获取数据时发生错误: {e}", icon="❌")
            # with data_act_col2:
            #     if st.button("从水鱼查分器获取", help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "将使用您的用户名作为查询参数",
            #                  icon="🐟", width='stretch', disabled=not metadata_status):
            #         current_paths = get_data_paths(username, timestamp=None)
            #         save_dir = os.path.dirname(current_paths['data_file'])
            #         save_id = os.path.basename(save_dir)
            #         if save_id:
            #             os.makedirs(save_dir, exist_ok=True)
            #             st.session_state.save_id = save_id
            #             with st.spinner("正在获取数据。"):
            #                 update_b50(
            #                     update_b50_data,
            #                     raw_username,
            #                     current_paths,
            #                     best_or_new,
            #                     "fish",
            #                     None
            #                 )
        with st.expander("我玩外服", icon="🔵"):
            st.info(f"""
                    请按照以下步骤，完成您的创建存档操作：
                    - 上传您的游戏数据文件（扩展名以 .json 结尾）
                    - 在数据预览内，检查您的前几条数据是否正常
                    - 选择解析类型，点击 “解析并创建存档” 以开始解析
                    """, icon="ℹ️")
            uploaded_file = st.file_uploader(
                "选择数据文件", 
                type=["json"], 
                disabled=not metadata_status,
                key="intr_uploader"
            )
            
            if uploaded_file is not None and metadata_status:
                try:
                    # 读取文件
                    content = uploaded_file.read()
                    raw_data = json.loads(content.decode('utf-8'))
                    
                    # ========== 检查必要键值是否存在 ==========
                    missing_keys = []
                    if "best" not in raw_data:
                        missing_keys.append("best")
                    if "new" not in raw_data:
                        missing_keys.append("new")
                    
                    if missing_keys:
                        st.error(f"文件中缺少必要的键值: {', '.join(missing_keys)}", icon="❌")
                        st.caption("请确保文件包含 best 和 new 数组")
                        
                        # 显示文件中的实际键值供参考
                        available_keys = list(raw_data.keys())
                        if available_keys:
                            st.info(f"文件中现有的键值: {', '.join(available_keys)}")
                        
                        # 显示数据预览
                        with st.expander("查看文件内容预览"):
                            preview_data = {}
                            for key in available_keys[:5]:  # 只预览前5个键，避免数据太大
                                if isinstance(raw_data[key], list):
                                    preview_data[key] = raw_data[key][:3] if raw_data[key] else []
                                else:
                                    preview_data[key] = raw_data[key]
                            st.json(preview_data)
                        
                        st.stop()  # 停止执行
                    
                    # ========== 显示数据统计（不限制长度） ==========
                    best_count = len(raw_data["best"])
                    new_count = len(raw_data["new"])
                    
                    # col1, col2 = st.columns(2)
                    # with col1:
                    #     st.metric("Best 曲目数", best_count)
                    # with col2:
                    #     st.metric("New 曲目数", new_count)
                    
                    # 不再警告长度异常，只显示信息
                    st.caption(f"注：文件包含 {best_count} 首 Best 曲目，{new_count} 首 New 曲目")
                    
                    # 显示数据预览（只显示前几条作为示例）
                    with st.expander("数据预览（各自显示前 5 条）"):
                        preview = {}
                        if best_count > 0:
                            preview["best_sample"] = raw_data["best"][:5]
                        if new_count > 0:
                            preview["new_sample"] = raw_data["new"][:5]
                        st.json(preview)
                    
                    intr_act_col1, intr_act_col2 = st.columns(2, vertical_alignment="center")
                    with intr_act_col1:
                        # 让用户选择数据类型
                        data_type = st.radio(
                            "选择要解析的数据类型", disabled=not metadata_status,
                            options=["全都要", "仅旧曲", "仅新曲"], horizontal=True, 
                            captions=["Best30 + New20", "Only Best30", "Only New20"], key="intr_data_type",
                            help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "国服与外服的设置相互分离"
                        )
                    
                    # 根据数据类型检查数据是否存在（不检查长度）
                    if data_type in ["仅旧曲", "全都要"] and best_count == 0:
                        st.error("您选择了解析 旧曲目 数据，但文件中没有 旧曲目 数据", icon="❌")
                        st.stop()
                    if data_type in ["仅新曲", "全都要"] and new_count == 0:
                        st.error("您选择了解析 新曲目 数据，但文件中没有 新曲目 数据", icon="❌")
                        st.stop()
                    
                    # 准备存档路径
                    current_paths = get_data_paths(username, timestamp=None)
                    save_dir = os.path.dirname(current_paths['data_file'])
                    save_id = os.path.basename(save_dir)
                    
                    with intr_act_col2:
                        if st.button("解析并创建存档", use_container_width=True, icon="🔄", disabled=not metadata_status):
                            try:
                                os.makedirs(save_dir, exist_ok=True)
                                st.session_state.save_id = save_id
                                
                                with st.spinner("正在解析数据..."):
                                    # 根据数据类型决定传哪些键值
                                    filtered_data = {}
                                    if data_type in ["仅旧曲", "全都要"]:
                                        filtered_data["best"] = raw_data["best"]
                                    if data_type in ["仅新曲", "全都要"]:
                                        filtered_data["new"] = raw_data["new"]
                                    
                                    # 直接调用 _process_b50_data
                                    processed_data = _process_b50_data(
                                        filtered_data,
                                        "intr",
                                        current_paths['raw_file'],
                                        current_paths['data_file'],
                                        data_type
                                    )
                                
                                # 成功
                                st.toast(f"成功解析 {len(processed_data)} 首曲目", icon="✅")
                                st.session_state.data_updated_step1 = True
                                st.session_state.config_saved = True
                                
                                # 显示解析结果统计
                                b30_count = len([s for s in processed_data if s['clip_id'].startswith('Best_')])
                                n20_count = len([s for s in processed_data if s['clip_id'].startswith('New_')])
                                # st.success(f"Best 曲目: {b30_count} 首, New 曲目: {n20_count} 首")
                                
                            except Exception as e:
                                # 失败时清理
                                if os.path.exists(save_dir):
                                    import shutil
                                    shutil.rmtree(save_dir)
                                
                                st.toast(f"❌ 解析失败: {str(e)}", icon="❌")
                                with st.expander("错误详情"):
                                    st.code(traceback.format_exc())
                                
                                if 'save_id' in st.session_state:
                                    del st.session_state.save_id
                                    
                except json.JSONDecodeError:
                    st.error("文件格式错误，请上传有效的 JSON 文件", icon="❌")
                except Exception as e:
                    st.error(f"读取文件失败: {str(e)}", icon="❌")
            # st.file_uploader("上传您的 Best30 数据", type="json", accept_multiple_files=False,
            #                  help="您的包体（目前）未拥有谱面数据，请回到首页下载！" if not metadata_status else "此数据需从 CHUNITHM-NET 中使用特定方法下载", disabled=not metadata_status)
            # st.warning("目前需要提供测试样本以用于测试，因此此功能仍在重新开发", icon="⚠️")


        col1, col2 = st.columns([.3, 1.7], gap="small", vertical_alignment="center")
        with col1:
            st.markdown("或者，您也可以")
        
        with col2:
            if st.button("新建空白存档", key="int_create_new_save", icon="📄", width='stretch', disabled=not metadata_status,
                         help="您的包体（目前）未拥有谱面数据，请回到首页下载！" if not metadata_status else "如果您目前没有可用于生成存档的数据，可生成空白存档（作为占位）"):
                current_paths = get_data_paths(username, timestamp=None)
                save_dir = os.path.dirname(current_paths['data_file'])
                save_id = os.path.basename(save_dir)
                os.makedirs(save_dir, exist_ok=True)
                new_data = {
                    "clip_id": "Best_1",
                    "id": 1,
                    "song_name": "koko",
                    "artist": "先辈",
                    "score": 114514,
                    "rating": 1.919,
                    "level": 8.1,
                    "level_next": 8.2,
                    "level_index": 1,
                    "full_combo": None,
                    "full_chain": None,
                    "play_count": 0
                }
                with open(f'{save_dir}/b30_config.json', 'w', encoding='utf-8') as f:
                    print(f'[{json.dumps(new_data, ensure_ascii=False)}]', file=f)
                st.session_state.save_id = save_id
                st.session_state.data_updated_step1 = True
                st.session_state.config_saved = True
                st.success(f"已新建空白存档！用户名：{username}，存档时间：{save_id}", icon="✅")
                st.rerun()
        
    if st.session_state.get('data_updated_step1', False):
        st.divider()
        col1, col2 = st.columns(2, gap="small", vertical_alignment="center")
        with col1:
            st.write("确认数据无误后，前往下一步准备生成底图。")
        
        with col2:
            if st.button("下一步", icon="➡️", help="您需要获取谱面数据后才能继续，因为您的存档依靠此数据生成" if not metadata_status else "", width='stretch', disabled=not metadata_status):
                st.switch_page("st_pages/Generate_Pic_Resources.py")
else:
    st.warning("请先确定用户名！", icon="⚠️")