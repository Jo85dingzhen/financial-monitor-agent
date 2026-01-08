📈 Financial Monitor Agent (基于 LangGraph 的全自动财经研报系统)
Automated, Reliable, Traceable. 一个基于 Multi-Agent 架构的智能财经监控系统，旨在解决信息过载与大模型幻觉问题。

📖 项目简介 (Introduction)
Financial Monitor Agent 是一个全自动化的财经情报生产流水线。它利用 LangGraph 编排多个职能明确的 AI 智能体，模拟了人类专业投研团队的工作流：从全网搜集、去重聚类、研报撰写，到合规审计与最终发布。

本项目旨在探索 Agentic AI 在垂直领域的应用，特别是如何通过**“白名单机制”和“自我审计回路（Self-Correction）”**来降低 LLM 的幻觉率，实现可追溯、高信度的内容生成。

🏗️ 系统架构 (System Architecture)
系统采用有向无环图（DAG）与循环（Cycle）结合的状态机设计，包含五个核心节点：

Module A (The Gatherer): 基于 DuckDuckGo 的多策略搜索器。内置 Tier 1/2 权威媒体白名单（如央行、财新），从源头过滤噪音。

Module B (The Analyst): 利用 DeepSeek (LLM) 对碎片化新闻进行语义聚类，识别核心事件（Event）。

Module C (The Journalist): 基于聚类后的事实生成结构化研报，遵循 Chain-of-Thought (CoT) 写作逻辑。

Module D (The Auditor): (核心创新) 系统的“安全阀”。对生成的研报进行实体一致性、语气和时间线检查。若发现错误，自动触发修正循环。

Module E (The Publisher): 将经过审计的内容渲染为标准 Markdown 日报并落盘。

🕹️ 操作指南 (Operation Guide)
1. 启动程序
在终端中运行主程序：

Bash

python main.py
2. 运行时观测 (Runtime Monitoring)
系统启动后，终端将通过 Rich 库展示实时可视化的执行流程。请关注以下五个阶段：

🔵 Phase 1: Gathering (采集)

观察日志中的 Searching: ...。

注意查看灰色的 🗑️ [过滤] 日志（表示成功拦截了非白名单噪音）和绿色的 ⚡ Hit 日志（表示命中了权威信源）。

阶段结束时会展示一张采集结果预览表。

🟣 Phase 2: Analyst (分析)

系统会打印 DeepSeek Analyst 正在深度分析...。

观察输出的 Tree 树状图，展示了 AI 如何将几十条新闻归纳为几个核心 Topic（如“央行降准”、“美联储会议”）。

🟢 Phase 3: Drafting (撰写)

你会看到 Draft #1 Generated 的面板。这是 Journalist 根据事实写出的初稿预览。

🟡 Phase 4: Auditing (审计 - 关键环节)

重点关注：这是系统体现“智能”的时刻。

如果显示 ✅ PASS，说明初稿事实无误。

如果显示 ⚠️ FIXED，说明 Auditor 发现了错误（如数字单位错误、语气过激）并已自动修正。

🚀 Phase 5: Publishing (发布)

显示 Report Generated Successfully，并给出最终文件的路径。

3. 查看输出结果 (Outputs)
程序运行结束后，请查看项目目录下的以下文件：

最终研报：位于 daily_reports/ 文件夹。

文件名示例：Financial_Briefing_2025-01-08.md。

建议：使用 VS Code 的 "Open Preview" 功能查看渲染后的 Markdown，体验最佳。请检查文末的 Source Refs 以验证溯源能力。

原始数据日志：位于 debug_logs/ 文件夹。

raw_articles_xxxx.json: 记录了爬虫抓到的所有原始数据，用于证明“没有遗漏”。

gathered_results.json: 采集模块的调试快照。

4. 自定义搜索词 (Customization)
如果您想监控特定的财经话题，请修改 main.py 底部的 initial_state：

Python

# main.py
initial_state = {
    "queries": [
        "site:pbc.gov.cn 降息",       # 定向监控央行
        "site:caixin.com 人工智能",   # 监控特定行业
        "美联储 货币政策"             # 广撒网搜索
    ],
    # ...
}
🚀 快速安装 (Installation)
1. 环境准备
确保您的系统已安装 Python 3.10+。

Bash

# 创建并激活虚拟环境 (推荐)
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
2. 安装依赖
Bash

pip install -r requirements.txt
3. 配置 API Key
在项目根目录下创建一个 .env 文件，填入 Key：

代码段

# .env 
DEEPSEEK_API_KEY=sk-your-api-key-here
# 或者
OPENAI_API_KEY=sk-your-api-key-here