from flask import Flask, request, render_template_string
import requests
import urllib.parse
import secrets
import hashlib
import base64
import json

app = Flask(__name__)

# 应用信息
CLIENT_ID = "2e8b528a-684c-454e-9a10-a01a2339b1ff"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

# OAuth 接口地址
AUTHORIZE_URL = "https://maimai.lxns.net/oauth/authorize"
TOKEN_URL = "https://maimai.lxns.net/api/v0/oauth/token"
PLAYER_API_URL = "https://maimai.lxns.net/api/v0/user/chunithm/player/scores"

# HTML模板 - 单页显示所有步骤
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>落雪咖啡屋 maimai DX 查分器 OAuth 授权</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            max-width: 800px; 
            margin: 0 auto; 
            padding: 20px;
            background: #f8f9fa;
        }
        .container { 
            background: white; 
            padding: 30px; 
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .step { 
            margin-bottom: 25px; 
            padding: 20px;
            border-left: 4px solid #007bff;
            background: #f8f9fa;
            border-radius: 0 8px 8px 0;
        }
        .step-number {
            background: #007bff;
            color: white;
            border-radius: 50%;
            width: 30px;
            height: 30px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-right: 10px;
            font-weight: bold;
        }
        .code-box { 
            background: #2d3748; 
            color: #e2e8f0; 
            padding: 15px; 
            border-radius: 6px; 
            font-family: 'Courier New', monospace; 
            font-size: 14px;
            word-break: break-all;
            margin: 10px 0;
        }
        .btn { 
            background: #007bff; 
            color: white; 
            padding: 12px 24px; 
            border: none; 
            border-radius: 6px; 
            cursor: pointer; 
            text-decoration: none; 
            display: inline-block;
            font-size: 16px;
            transition: background 0.3s;
        }
        .btn:hover {
            background: #0056b3;
        }
        .btn-secondary {
            background: #6c757d;
        }
        .btn-secondary:hover {
            background: #545b62;
        }
        .success { 
            background: #d4edda; 
            border: 1px solid #c3e6cb; 
            color: #155724;
            padding: 15px;
            border-radius: 6px;
        }
        .error { 
            background: #f8d7da; 
            border: 1px solid #f5c6cb; 
            color: #721c24;
            padding: 15px;
            border-radius: 6px;
        }
        .info-box {
            background: #d1ecf1;
            border: 1px solid #bee5eb;
            color: #0c5460;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
        }
        .form-group {
            margin: 15px 0;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input[type="text"] {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
            box-sizing: border-box;
        }
        .hidden {
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 maimai DX 查分器 OAuth 授权</h1>
        <p>通过 OAuth 2.0 安全获取您的游戏数据</p>
        
        <!-- 步骤1: 开始授权 -->
        <div class="step">
            <h3><span class="step-number">1</span>开始授权流程</h3>
            <p>点击下方按钮前往落雪查分器进行授权：</p>
            <a href="{{ auth_url }}" class="btn" target="_blank">前往授权页面</a>
            <div class="info-box">
                <strong>提示：</strong>
                <ul>
                    <li>将在新页面打开落雪查分器授权页面</li>
                    <li>登录后同意授权，页面将显示授权码</li>
                    <li>复制授权码并返回此页面继续</li>
                </ul>
            </div>
        </div>

        <!-- 步骤2: 输入授权码 -->
        <div class="step">
            <h3><span class="step-number">2</span>输入授权码</h3>
            <p>请在下方粘贴您从授权页面获得的授权码：</p>
            <form method="POST" action="/exchange">
                <div class="form-group">
                    <label for="auth_code">授权码：</label>
                    <input type="text" id="auth_code" name="auth_code" 
                           placeholder="例如: JVJ6-VPTM-MGHZ" required>
                </div>
                <input type="hidden" name="code_verifier" value="{{ code_verifier }}">
                <button type="submit" class="btn">获取访问令牌</button>
            </form>
        </div>

        <!-- 步骤3: 显示结果 -->
        {% if step >= 3 %}
        <div class="step {% if success %}success{% else %}error{% endif %}">
            <h3><span class="step-number">3</span>授权结果</h3>
            
            {% if success %}
                <h4>✅ 授权成功！</h4>
                
                <div class="form-group">
                    <label>访问令牌：</label>
                    <div class="code-box">{{ access_token }}</div>
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
                    <div>
                        <strong>令牌类型：</strong><br>
                        {{ token_type }}
                    </div>
                    <div>
                        <strong>有效期：</strong><br>
                        {{ expires_in }} 秒
                    </div>
                    <div>
                        <strong>权限范围：</strong><br>
                        {{ scope }}
                    </div>
                </div>
                
                <div class="form-group">
                    <label>刷新令牌：</label>
                    <div class="code-box">{{ refresh_token }}</div>
                </div>
                
                {% if user_data %}
                <div class="form-group">
                    <label>用户数据：</label>
                    <div class="code-box">{{ user_data }}</div>
                </div>
                {% endif %}
                
                <a href="/" class="btn btn-secondary">重新开始</a>
                
            {% else %}
                <h4>❌ 授权失败</h4>
                <p>{{ error_message }}</p>
                <a href="/" class="btn">重新尝试</a>
            {% endif %}
        </div>
        {% endif %}
    </div>
</body>
</html>
'''

def generate_pkce_params():
    """生成 PKCE 相关参数"""
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return code_verifier, code_challenge

@app.route("/")
def home():
    """主页面 - 显示所有步骤"""
    code_verifier, code_challenge = generate_pkce_params()
    
    # 构建授权 URL
    scope = ["read_user_profile", "read_player", "read_user_token"]
    query_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(scope),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    
    auth_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query_params)}"
    
    return render_template_string(HTML_TEMPLATE, 
                                step=1,
                                auth_url=auth_url,
                                code_verifier=code_verifier)

@app.route("/exchange", methods=["POST"])
def exchange_token():
    """处理授权码交换"""
    auth_code = request.form.get("auth_code", "").strip()
    code_verifier = request.form.get("code_verifier", "")
    
    if not auth_code:
        return render_template_string(HTML_TEMPLATE, 
                                    step=3,
                                    success=False,
                                    error_message="授权码不能为空")
    
    try:
        # 使用授权码和 code_verifier 获取访问令牌
        token_response = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier
        })
        
        if token_response.status_code != 200:
            error_detail = token_response.text
            return render_template_string(HTML_TEMPLATE, 
                                        step=3,
                                        success=False,
                                        error_message=f"令牌获取失败: {error_detail}")
        
        token_data = token_response.json()
        
        # 检查响应结构
        if 'data' in token_data:
            token_info = token_data['data']
        else:
            token_info = token_data
        
        access_token = token_info.get("access_token")
        
        if not access_token:
            return render_template_string(HTML_TEMPLATE, 
                                        step=3,
                                        success=False,
                                        error_message="未获取到访问令牌")
        
        # 使用访问令牌获取用户数据
        user_data = "无法获取用户数据"
        try:
            user_response = requests.get(PLAYER_API_URL, headers={
                "Authorization": f"Bearer {access_token}"
            })
            if user_response.status_code == 200:
                user_data = json.dumps(user_response.json(), ensure_ascii=False, indent=2)
        except Exception as e:
            user_data = f"获取用户数据时出错: {str(e)}"
        
        return render_template_string(HTML_TEMPLATE,
                                    step=3,
                                    success=True,
                                    access_token=access_token,
                                    token_type=token_info.get("token_type", "Bearer"),
                                    expires_in=token_info.get("expires_in", 900),
                                    refresh_token=token_info.get("refresh_token", ""),
                                    scope=token_info.get("scope", ""),
                                    user_data=user_data)
    
    except Exception as e:
        return render_template_string(HTML_TEMPLATE, 
                                    step=3,
                                    success=False,
                                    error_message=f"处理过程中发生错误: {str(e)}")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)