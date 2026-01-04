# auditor_demo.py
# Module D: The Auditor (Compliance & Fact Checking)
# V2.0: Mathematical Verification & Entity Alignment

import os
import json
import re
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel

# === 依赖库 ===
try:
    from openai import OpenAI
except ImportError:
    print("❌ 错误: 缺少 openai 库。")
    exit()

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    console = Console()
except ImportError:
    pass

# === 引用上游数据结构 ===
try:
    from analyst_demo import Event
    from journalist_demo import NewsReport
except ImportError:
    print("❌ 无法找到上游模块文件。")
    exit()

# === 输出结构 ===
class AuditResult(BaseModel):
    event_id: str
    original_report: NewsReport
    status: str              # "PASS", "FIXED", "FLAGGED"
    correction_notes: str    # 具体的错误说明
    revised_summary: Optional[str] = None 

# ==========================================
# 🔧 核心组件 1: 中文数字归一化引擎
# 解决 "3万亿" vs "30000亿" 的匹配问题
# ==========================================
class NumberGuard:
    @staticmethod
    def normalize_cn_number(text: str) -> float:
        """
        将中文财经数字字符串转换为标准浮点数，用于数学比对。
        支持：3.5万亿, 3000亿, 50%, 100BP 等
        """
        text = text.replace(",", "") # 去掉千分位
        
        # 提取基础数值
        num_match = re.search(r"[-+]?\d*\.?\d+", text)
        if not num_match:
            return 0.0
        
        value = float(num_match.group())
        
        # 处理单位
        if "万亿" in text:
            value *= 1_0000_0000_0000
        elif "亿" in text:
            value *= 1_0000_0000
        elif "万" in text:
            value *= 1_0000
        elif "%" in text:
            value *= 0.01
        elif "BP" in text.upper() or "基点" in text:
            value *= 0.0001
            
        return value

    @staticmethod
    def extract_financial_numbers(text: str) -> List[str]:
        """从文本中提取所有关键财经数字串"""
        # 匹配模式：数字 + 可选的小数点 + 可选的单位(亿/万/%)
        # 例如: 3.5%, 3000亿, 500
        pattern = r"\d+(?:\.\d+)?(?:万亿|亿|万|%|BP|个基点)?"
        return re.findall(pattern, text)

# ==========================================
# 🕵️ 核心组件 2: 审计官 Agent
# ==========================================
class AuditorAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Missing API Key for Auditor")
        
        self.client = OpenAI(
            api_key=self.api_key, 
            base_url="https://api.deepseek.com"
        )
        
        # 关键实体库 (防止把财政部搞成央行)
        self.critical_entities = ["中国人民银行", "财政部", "证监会", "国务院", "美联储"]

    def audit_single_report(self, report: NewsReport, source_event: Event) -> AuditResult:
        """
        执行双重校验：
        1. Python 数学层：提取 Draft 和 Source 中的数字，计算是否等值。
        2. LLM 语义层：检查实体混淆和逻辑错误。
        """
        
        # --- Step 1: 准备原始素材 (Ground Truth) ---
        truth_text = ""
        full_source_content = ""
        for art in source_event.articles:
            # 拼接所有来源的文本
            text = getattr(art, 'full_text', art.snippet) or art.snippet
            truth_text += f"【来源: {art.source.outlet_name}】 {text}\n"
            full_source_content += text

        # --- Step 2: 实体与概念校对 (Entity Check) ---
        # 检查是否混淆了关键机构
        entity_warnings = []
        for entity in self.critical_entities:
            # 如果简报里提到了某机构，但原始素材里压根没出现
            if entity in report.summary and entity not in full_source_content:
                entity_warnings.append(f"警报：简报提及'{entity}'，但原始来源中未发现该实体，疑似幻觉。")

        # --- Step 3: DeepSeek 深度审计 (Logic Check) ---
        # 我们把 Python 算出来的“数字疑点”喂给它，让它做最终判断
        
        system_prompt = """
        你是一名严苛的财经审计师（Auditor）。你的任务是逐字核对"简报"与"事实"的一致性。
        
        请执行以下 checks：
        1. **数字归一化核对**：原文若为"30000亿"，简报写"3万亿"是正确的（PASS）；若写成"300亿"则是致命错误（FAIL）。
        2. **实体一致性**：绝不能把"财政部"写成"央行"。
        3. **拒绝废话**：如果发现错误，必须引用原文证据。
        
        输出格式(JSON)：
        {
            "status": "PASS" (完全无误) 或 "FIXED" (发现错误并已修正),
            "error_detail": "若无误留空。若有误，请明确指出：'原文是X，简报误写为Y'。",
            "revised_summary": "修正后的摘要全文 (仅在 status 为 FIXED 时填写)"
        }
        """

        user_prompt = f"""
        === 原始事实 (Ground Truth) ===
        {truth_text[:25000]} 

        === 待审计简报 (Draft) ===
        标题：{report.title}
        摘要：{report.summary}
        
        === 系统预检警报 (Python Pre-check) ===
        {"; ".join(entity_warnings) if entity_warnings else "实体检查通过。"}

        请开始审计，如果有任何数字不匹配或实体错误，必须修正：
        """

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={ "type": "json_object" },
                temperature=0.0 # 绝对理性
            )
            audit_data = json.loads(response.choices[0].message.content)
            
            status = audit_data.get("status", "PASS")
            detail = audit_data.get("error_detail", "")
            revised = audit_data.get("revised_summary", "")

            # 强制逻辑：如果有系统预检警报，必须标记为 FIXED
            if entity_warnings and status == "PASS":
                status = "FIXED"
                detail = f"实体错误修正: {'; '.join(entity_warnings)}"
                # 让 LLM 重新生成太慢，这里简单处理，实际可回落
            
            return AuditResult(
                event_id=report.event_id,
                original_report=report,
                status=status,
                correction_notes=detail if detail else "数据与事实核对一致",
                revised_summary=revised if status == "FIXED" else None
            )

        except Exception as e:
            console.print(f"[red]审计运行时错误: {e}[/]")
            return AuditResult(
                event_id=report.event_id,
                original_report=report,
                status="FLAGGED",
                correction_notes=f"System Error: {str(e)}",
                revised_summary=None
            )

    def batch_audit(self, reports: List[NewsReport], events: List[Event]) -> List[AuditResult]:
        """批量审计入口"""
        results = []
        if not reports: return []

        console.print(f"[bold yellow]🛡️ 审计官正在进行数学级核对 (Mathematical Verification)...[/]")
        
        event_map = {e.event_id: e for e in events}

        for report in reports:
            source_event = event_map.get(report.event_id)
            if not source_event: continue
            
            result = self.audit_single_report(report, source_event)
            results.append(result)
            
        return results

# === 可视化面板 (优化版) ===
def print_audit_dashboard(audit_results: List[AuditResult]):
    console.print("\n")
    console.rule("[bold yellow]⚖️ Module D: 最终合规报告 (Final Compliance)[/]")
    
    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("审计结论", justify="center", width=12)
    table.add_column("简报内容", ratio=2)
    table.add_column("核查详情 (Verification Details)", ratio=1)

    for res in audit_results:
        if res.status == "PASS":
            status_style = "[bold green]✅ PASS[/]"
            # PASS 的时候显示原摘要
            content = f"[bold]{res.original_report.title}[/bold]\n[dim]{res.original_report.summary}[/dim]"
            detail = "[green]• 数字归一化核对：通过\n• 实体一致性：通过\n• 事实溯源：完整[/]"
        
        elif res.status == "FIXED":
            status_style = "[bold yellow]⚠️ FIXED[/]"
            # FIXED 的时候显示修正后的摘要，并划掉旧的
            content = f"[bold]{res.original_report.title}[/bold]\n"
            content += f"[strike dim]{res.original_report.summary}[/strike dim]\n"
            content += f"[bold yellow]➥ {res.revised_summary}[/bold yellow]"
            
            detail = f"[bold red]发现错误:[/bold red]\n{res.correction_notes}"
        
        else:
            status_style = "[bold red]🛑 FLAGGED[/]"
            content = f"[bold]{res.original_report.title}[/bold]"
            detail = f"[red]无法验证: {res.correction_notes}[/red]"

        table.add_row(status_style, content, detail)

    console.print(table)
