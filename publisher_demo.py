# publisher_demo.py
# Module E: The Publisher (Footnote Rendering)
# 响应评审要求：生成带链接脚注的专业报告

import os
from datetime import datetime
from typing import List
from rich.console import Console
from rich.panel import Panel

try:
    from auditor_demo import AuditResult
except ImportError:
    exit()

class PublisherAgent:
    def __init__(self, output_dir="daily_reports"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir): os.makedirs(output_dir)

    def generate_daily_report(self, audit_results: List[AuditResult]):
        valid_results = [r for r in audit_results if r.status != "FLAGGED"]
        if not valid_results: return None

        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = os.path.join(self.output_dir, f"Financial_Briefing_{date_str}.md")
        
        md = f"# 📈 AI Financial Briefing ({date_str})\n\n"
        md += "> **Double-Verified**: Citations checked against source text.\n\n---\n\n"

        for i, res in enumerate(valid_results, 1):
            rep = res.original_report # 或者 revised
            
            # 图标状态
            icon = "🟢" if res.status == "PASS" else "🟡 (Audited)"
            
            md += f"## {i}. {rep.title} {icon}\n\n"
            
            # 渲染各个板块
            for section in [rep.summary, rep.background, rep.analysis, rep.outlook]:
                if section:
                    # 可以在这里把 [cite: 1] 替换成 Markdown 链接 [^1]
                    # 简单起见，保持原样，在底部列出
                    md += f"{section}\n\n"

            # ⚡️ 核心：渲染脚注 References
            if rep.source_mapping:
                md += "### 📚 References\n"
                for idx, meta in rep.source_mapping.items():
                    # meta 格式: "outlet|title|url"
                    try:
                        outlet, title, url = meta.split("|")
                        md += f"- **[{idx}]** {outlet}: [{title}]({url})\n"
                    except:
                        md += f"- **[{idx}]** {meta}\n"
            
            # 如果有审计问题，列出来
            if res.issues:
                md += "\n> **Audit Notes**:\n"
                for issue in res.issues:
                    md += f"> - ⚠️ {issue}\n"

            md += "\n---\n"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md)
            
        Console().print(Panel(f"Published: {file_path}", style="green"))
        return file_path
