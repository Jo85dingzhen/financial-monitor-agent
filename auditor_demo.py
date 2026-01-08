# auditor_demo.py
# Module D: The Auditor (Robust Edition)
# V5.2: Auto-Fallback Matching + Rich Debugging

import os
import json
import re
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

try:
    from openai import OpenAI
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.text import Text
    console = Console()
except ImportError:
    pass

try:
    from analyst_demo import Event
    from journalist_demo import NewsReport
except ImportError:
    exit()

class AuditResult(BaseModel):
    event_id: str
    original_report: NewsReport
    status: str              # "PASS", "FIXED", "FLAGGED"
    correction_notes: str    
    revised_summary: Optional[str] = None 
    audit_breakdown: dict = {} 

class AuditorAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Missing API Key for Auditor")
        
        self.client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")
        self.critical_entities = ["中国人民银行", "财政部", "证监会", "国务院", "美联储", "统计局"]

    # === 基础检查功能 ===
    def _check_tone(self, original_text: str, report_text: str) -> str:
        prompt = f"""
        请判断简报语气是否过激（如使用"暴跌"、"血洗"等词）而原文很平和。
        原文片段：{original_text[:500]}
        简报：{report_text}
        输出JSON: {{ "is_exaggerated": true/false, "reason": "理由" }}
        """
        try:
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            data = json.loads(resp.choices[0].message.content)
            if data.get("is_exaggerated"):
                return f"[Tone] 语气警告: {data.get('reason')}"
            return "PASS"
        except:
            return "PASS"

    def _check_time(self, full_source_text: str, report_text: str) -> str:
        report_years = set(re.findall(r"202\d", report_text))
        source_years = set(re.findall(r"202\d", full_source_text))
        diff = report_years - source_years
        if diff:
            return f"[Time] ⚠️ 年份存疑: {diff}"
        return "PASS"

    def audit_single_report(self, report: NewsReport, source_event: Event) -> AuditResult:
        # 1. 获取原文
        full_source_text = ""
        for art in source_event.articles:
            text = getattr(art, 'full_text', art.snippet) or art.snippet
            full_source_text += text

        if not full_source_text:
            return AuditResult(
                event_id=report.event_id,
                original_report=report,
                status="FLAGGED",
                correction_notes="❌ 严重错误: 无法找到原始新闻素材，无法核实。",
                audit_breakdown={"source": "MISSING"}
            )

        # 2. 执行检查
        warnings = []
        breakdown = {}

        # 实体检查
        entity_errs = [ent for ent in self.critical_entities if ent in report.summary and ent not in full_source_text]
        if entity_errs:
            warnings.append(f"[Entity] 幻觉实体: {entity_errs}")
            breakdown["entity"] = "FAIL"
        else:
            breakdown["entity"] = "PASS"

        # 语气检查
        tone_res = self._check_tone(full_source_text, report.summary)
        if tone_res != "PASS":
            warnings.append(tone_res)
            breakdown["tone"] = "FAIL"
        else:
            breakdown["tone"] = "PASS"

        # 时间检查
        time_res = self._check_time(full_source_text, report.summary)
        if time_res != "PASS":
            warnings.append(time_res)
            breakdown["time"] = "FAIL"
        else:
            breakdown["time"] = "PASS"

        # 3. DeepSeek 综合修正
        system_prompt = """
        你是一名财经合规官。请根据Check Logs修正简报。
        如果状态是FIXED，必须提供revised_text。
        输出JSON: {
            "status": "PASS" 或 "FIXED",
            "correction_summary": "修正了...",
            "revised_text": "修正后的完整摘要"
        }
        """
        user_prompt = f"""
        【Check Logs】: {"; ".join(warnings) if warnings else "无明显错误"}
        【原文】: {full_source_text[:2000]}
        【待修简报】: {report.summary}
        """

        try:
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            res_json = json.loads(resp.choices[0].message.content)
            
            final_status = res_json.get("status", "PASS")
            if warnings and final_status == "PASS":
                final_status = "FIXED" # 强制修正
                
            return AuditResult(
                event_id=report.event_id,
                original_report=report,
                status=final_status,
                correction_notes=res_json.get("correction_summary", "无修正") + f" {warnings}",
                revised_summary=res_json.get("revised_text", report.summary),
                audit_breakdown=breakdown
            )
            
        except Exception as e:
            return AuditResult(
                event_id=report.event_id,
                original_report=report,
                status="FLAGGED",
                correction_notes=f"Audit Error: {e}",
                audit_breakdown={"system": "error"}
            )

    def batch_audit(self, reports: List[NewsReport], events: List[Event]) -> List[AuditResult]:
        results = []
        # 建立映射表
        event_map = {e.event_id: e for e in events}
        
        console.print(f"\n[bold yellow]🛡️  审计官启动 (待审: {len(reports)} 篇 | 来源: {len(events)} 个)...[/]")
        
        for i, report in enumerate(reports):
            src = None
            
            # === 🕵️‍♂️ 关键修复：智能匹配逻辑 ===
            # 1. 优先尝试 ID 匹配
            if report.event_id:
                src = event_map.get(report.event_id)
            
            # 2. 如果 ID 匹配失败（可能是 ID 为空），尝试按顺序匹配 (Fallback)
            if not src and i < len(events):
                console.print(f"[dim]⚠️ 警告: 报告 '{report.title[:10]}...' ID 丢失，正在使用第 {i+1} 个事件作为原文源。[/dim]")
                src = events[i]
            
            # 3. 开始审计
            if src:
                results.append(self.audit_single_report(report, src))
            else:
                console.print(f"[red]❌ 放弃: 无法找到报告 '{report.title}' 的原文来源。[/red]")

        return results

# === 可视化面板 ===
def print_audit_dashboard(audit_results: List[AuditResult]):
    if not audit_results:
        console.print("[red]❌ 审计结果为空！(未生成任何 AuditResult)[/red]")
        return

    console.print("\n")
    console.rule("[bold yellow]⚖️ Module D: 最终合规审计报告[/]")
    
    # 调整列宽，确保文字不被挤掉
    table = Table(box=box.ROUNDED, show_lines=True, width=120)
    table.add_column("状态", width=10, justify="center")
    table.add_column("维度检查", width=15)
    table.add_column("详情与修正", ratio=1) # 自动伸缩

    for res in audit_results:
        # 1. 维度列
        breakdown_str = ""
        for k, v in res.audit_breakdown.items():
            icon = "✅" if v == "PASS" else "❌"
            breakdown_str += f"{icon} {k}\n"

        # 2. 内容列
        if res.status == "PASS":
            status_style = "[bold green]PASS[/]"
            content = Text(f"原文无误。\n摘要: {res.original_report.summary[:100]}...", style="dim")
        else:
            status_style = "[bold yellow]FIXED[/]"
            # 使用 Text 对象处理换行和颜色
            content = Text()
            content.append(f"⚠️ 修正点: {res.correction_notes}\n\n", style="bold red")
            content.append(f"📝 修正后摘要:\n{res.revised_summary}", style="green")

        table.add_row(status_style, breakdown_str.strip(), content)

    console.print(table)
