import json
import requests
from typing import Dict, Any

# 读取配置
with open('llm_api_config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

gemini_config = config['gemini']

print("=" * 60)
print("Gemini API 连通性测试")
print("=" * 60)

# 1. 检查配置
print("\n[1] 配置检查:")
print(f"  Provider: {gemini_config['provider']}")
print(f"  Model: {gemini_config['model']}")
print(f"  API Base URL: {gemini_config['base_url']}")
print(f"  API Key: {gemini_config['api_key'][:20]}..." if gemini_config['api_key'] else "  API Key: 未设置")
print(f"  Enabled: {gemini_config['enabled']}")

# 2. 检查API密钥
print("\n[2] API密钥检查:")
if not gemini_config['api_key']:
    print("  ❌ API密钥未设置")
elif gemini_config['api_key'] == "":
    print("  ❌ API密钥为空")
else:
    print(f"  ✓ API密钥已设置")

# 3. 测试网络连接
print("\n[3] 网络连接测试:")
try:
    response = requests.head(gemini_config['base_url'], timeout=5)
    print(f"  ✓ 可以连接到 {gemini_config['base_url']}")
    print(f"    状态码: {response.status_code}")
except requests.exceptions.Timeout:
    print(f"  ⚠ 连接超时: {gemini_config['base_url']}")
except requests.exceptions.ConnectionError as e:
    print(f"  ❌ 连接失败: {e}")
except Exception as e:
    print(f"  ❌ 其他错误: {e}")

# 4. 测试API调用
print("\n[4] API调用测试:")
try:
    # Gemini API 的调用格式
    api_url = f"{gemini_config['base_url']}/models/{gemini_config['model']}:generateContent?key={gemini_config['api_key']}"
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": "Hello, test message"
                    }
                ]
            }
        ]
    }
    
    response = requests.post(api_url, json=payload, headers=headers, timeout=10)
    
    print(f"  状态码: {response.status_code}")
    print(f"  响应头: {dict(response.headers)}")
    
    if response.status_code == 200:
        print("  ✓ API调用成功")
        result = response.json()
        print(f"  响应内容: {json.dumps(result, indent=2, ensure_ascii=False)[:200]}...")
    else:
        print(f"  ❌ API返回错误")
        print(f"  错误内容: {response.text}")
        
        # 尝试解析错误信息
        try:
            error_info = response.json()
            if 'error' in error_info:
                print(f"\n  错误详情:")
                print(f"    Code: {error_info['error'].get('code', 'N/A')}")
                print(f"    Message: {error_info['error'].get('message', 'N/A')}")
                print(f"    Status: {error_info['error'].get('status', 'N/A')}")
        except:
            pass

except requests.exceptions.Timeout:
    print("  ❌ 请求超时")
except requests.exceptions.ConnectionError as e:
    print(f"  ❌ 连接错误: {e}")
except Exception as e:
    print(f"  ❌ 错误: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
