🛠 系统架构 (Pipeline)
本系统由四个核心节点组成，数据流向为线性图结构：
1. 🔵 Module A: 采集者 (The Gatherer)
• 功能：基于严格白名单（央行、财政部、财新等）进行全网搜索与清洗。
• 核心技术：Tavily Search API + 自动去噪 + 正文提取。
2. 🟣 Module B: 分析师 (The Analyst)
• 功能：利用 DeepSeek-V3 对碎片化新闻进行语义聚类，识别核心事件。
• 核心技术：LLM 语义分析 + 影响力打分算法。
3. 🟢 Module C: 撰稿人 (The Journalist)
• 功能：基于核心事件撰写“零信任”财经简报，风格客观中立。
• 核心技术：学术化写作 Prompt + 严格基于素材限制。
4. 🟡 Module D: 审计官 (The Auditor)
• 功能：对简报进行“数学级”核对与实体审查，防止幻觉。
• 核心技术：中文数字归一化算法（解决“3万亿”vs“30000亿”匹配） + 实体对齐。

1.环境准备
安装依赖库
pip install langgraph langchain-core openai rich pydantic tavily-python

2. 如何运行
在命令行输入python main.py


