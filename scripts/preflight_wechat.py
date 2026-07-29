from pathlib import Path
#!/usr/bin/env python3
"""公众号发布预检脚本 — ai-self-media-tools 固化版
在每次公众号内容生成+推送前执行，防止跳步和漏规则。

用法: python3 preflight_wechat.py
返回: 0=通过, 1=未通过(打印失败项)
"""
import sys, os, json, re, glob

FAILED = []

def check(desc, condition, fix=""):
    if condition:
        print(f"  ✅ {desc}")
    else:
        print(f"  ❌ {desc}")
        FAILED.append(f"{desc} — {fix}" if fix else desc)

print(f"{'='*50}")
print(f"📋 公众号发布预检清单")
print(f"{'='*50}")

# 1. 环境检查
check("CN代理配置存在", bool(os.environ.get("CN_PROXY")), "export CN_PROXY=socks5h://127.0.0.1:1080")

env_file = "/root/.ai-self-media-tools/secrets/wechat.env"
check("wechat.env 存在", os.path.exists(env_file), "创建 wechat.env")
if os.path.exists(env_file):
    env_data = open(env_file).read()
    check("WECHAT_APP_ID 已配置", "WECHAT_APP_ID=" in env_data)
    check("WECHAT_APP_SECRET 已配置", "WECHAT_APP_SECRET=" in env_data)

# 2. 主题检查
themes_dir = os.environ.get("HERMES_WECHAT_THEMES_DIR", str(Path.home() / ".hermes" / "tools" / "wechat-themes"))
theme_files = sorted(glob.glob(f"{themes_dir}/*.json"))
check(f"109套主题完整 ({len(theme_files)}/109)", len(theme_files) >= 109, f"需要109套，当前{len(theme_files)}")

if theme_files:
    # 验证主题结构正确
    sample = json.loads(open(theme_files[0]).read())
    has_styles = "styles" in sample and "h2" in sample.get("styles", {})
    check("主题CSS路径正确 (styles.h2)", has_styles, "主题JSON必须是 {styles:{h2:..., p:...}} 结构")

# 3. 图片引擎检查
scripts_dir = os.environ.get("HERMES_SCRIPTS_DIR", str(Path.home() / ".hermes" / "scripts"))
engine_file = f"{scripts_dir}/image_gen_engine.py"
check("image_gen_engine.py 存在", os.path.exists(engine_file), "文件缺失")

# 4. 内容规则记忆检查
print(f"\n📋 内容规则确认（必须遵守）:")
print(f"  • 字数: 每篇 ≥1200字，先写文件用 wc -m 确认")
print(f"  • 插图: 每篇 ≥3张内容相关图")
print(f"  • 封面: 内容相关，上传微信CDN，禁止纯色卡")
print(f"  • 版式: 每篇至少1引文(>)+1列表(-)")
print(f"  • 主题: 每篇不同，CSS内联，16px字号")
print(f"  • 数量: 策略基础量 + 1")
print(f"  • 图片: 优先复用已有微信CDN素材")

print(f"\n📋 生成流程确认:")
print(f"  • 先抓平台热门数据再定选题，不臆造")
print(f"  • 先测试图片引擎可用性（3张快速测试）")
print(f"  • 先写内容到文件计数≥1200字再推送")
print(f"  • 先删旧草稿再推新的")
print(f"  • 每步汇报但不需要用户同意")

print(f"\n{'='*50}")
if FAILED:
    print(f"❌ {len(FAILED)} 项未通过:")
    for f in FAILED:
        print(f"  • {f}")
    sys.exit(1)
else:
    print(f"✅ 全部通过，可以开始公众号发布流程")
    sys.exit(0)
