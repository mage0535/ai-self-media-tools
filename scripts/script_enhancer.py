#!/usr/bin/env python3
"""
Screencast 内容增强 — 生成更长的 AI 效率 Shorts 脚本。
根据话题自动生成多步演示内容，让 Screencast 引擎输出 15-30s 视频。
"""
import random

# 预设内容模板（话题 → 分步演示步骤）
CONTENT_TEMPLATES = {
    "5": [
        ["打开终端", "安装工具", "配置环境", "运行演示", "查看结果"],
        ["下载 VS Code", "安装插件", "打开项目", "开始编码", "运行调试"],
        ["打开浏览器", "搜索工具官网", "阅读文档", "下载安装", "试用功能"],
    ],
    "n8n": [
        ["打开 n8n 控制台", "创建工作流", "配置触发器", "添加动作节点", "激活并测试"],
        ["登录 n8n", "选择模板", "修改参数", "连接 API", "部署上线"],
    ],
    "GitHub": [
        ["打开项目页面", "阅读 README", "查看代码结构", "运行示例", "查看结果"],
        ["搜索 GitHub", "找到热门项目", "查看 Issue", "克隆仓库", "本地运行"],
    ],
    "Python": [
        ["打开 Python 环境", "导入库", "编写函数", "运行测试", "输出结果"],
        ["创建虚拟环境", "安装依赖", "编写脚本", "定时任务", "查看日志"],
    ],
    "AI": [
        ["打开 AI 工具", "输入提示词", "调整参数", "生成结果", "优化输出"],
        ["选择模型", "配置 API Key", "编写调用代码", "测试接口", "集成到工作流"],
    ],
    "default": [
        ["准备工作环境", "打开工具", "配置参数", "执行操作", "完成演示"],
        ["启动应用", "登录账号", "进入设置", "调整配置", "保存更改"],
    ],
}


def generate_script(topic, duration_target=20):
    """根据话题生成多步脚本，使 Screencast 达到目标时长。"""
    steps = []

    # 匹配话题关键词找到对应模板
    matched = False
    for keyword, templates in CONTENT_TEMPLATES.items():
        if keyword.lower() in topic.lower():
            steps = random.choice(templates)
            matched = True
            break

    if not matched:
        steps = random.choice(CONTENT_TEMPLATES["default"])

    # 组装为逗号分隔的内容行（Screencast 引擎格式）
    return ",".join(steps)


def enhance_screencast_call(topic, platform="youtube_shorts"):
    """生成增强后的 screencast 命令参数。"""
    script = generate_script(topic)

    # 根据平台选择模板
    if any(w in topic for w in ["对比", "评测", "横评"]):
        template = "demo"
    elif any(w in topic for w in ["教程", "指南", "入门"]):
        template = "tutorial"
    elif any(w in topic for w in ["部署", "搭建", "配置"]):
        template = "cicd"
    else:
        template = "tutorial"

    return {
        "type": template,
        "title": topic,
        "content": script,
    }


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "5个免费AI工具提升编码效率"
    cmd = enhance_screencast_call(topic)
    print(f"话题: {topic}")
    print(f"模板: {cmd['type']}")
    print(f"内容: {cmd['content']}")
    print(f"预计时长: ~{len(cmd['content'].split(',')) * 4}s")
