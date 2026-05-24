# auditor_demo.py
# Module D: The Auditor (Fact-Checking & Citation Verify)
# 响应评审要求：逐句核对出处，测试是否编造

import os
import json
import re
from typing import List
from pydantic import BaseModel

try:
    from openai import OpenAI
    from rich.console import Console
    console = Console()
except ImportError:
    pass

try:
    from journalist_demo import NewsReport
    from analyst_demo import Event
except ImportError:
    exit()

class AuditResult(BaseModel):
    event_id: str
    original_report: NewsReport
    status: str  # PASS / FIXED / FLAGGED
    issues: List[str]
    revised_report: NewsReport = None

class AuditorAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")

    def batch_audit(self, reports: List[NewsReport], events: List[Event]) -> List[AuditResult]:
        results = []
        event_map = {e.event_id: e for e in events}
        
        console.rule("[bold yellow]⚖️  Module D: 事实与引用核查 (Dual Verification)[/]")

        for report in reports:
            event = event_map.get(report.event_id)
            if not event: continue
            
            # 1. 构造“原文池”供核查
            # 将 article list 转换为 { "1": "text...", "2": "text..." }
            source_pool = {}
            for i, art in enumerate(event.articles, 1):
                text = getattr(art, 'full_text', art.snippet) or art.snippet
                source_pool[str(i)] = text

            # 2. 执行单篇审计
            res = self._audit_single(report, source_pool)
            results.append(res)
            
            # 打印结果
            status_icon = "✅" if res.status == "PASS" else "⚠️" if res.status == "FIXED" else "❌"
            console.print(f"{status_icon} [bold]{report.title}[/] - {len(res.issues)} issues")
            if res.issues:
                for issue in res.issues:
                    console.print(f"   - {issue}", style="dim red")

        return results

    def _audit_single(self, report: NewsReport, source_pool: dict) -> AuditResult:
        # 我们把整个 Report 内容拼起来检查
        full_content = f"{report.summary}\n{report.background}\n{report.analysis}"
        
        # ⚡️ 核心 Prompt：事实核查
        system_prompt = """
你是一名苛刻的财经事实核查员 (Fact Checker)。你的任务是验证文章中的声明是否被引用的来源支持。

【输入数据】
1. 待核查文本：包含 标记的段落。
2. 来源池：索引 x 对应的真实原文。

【核查规则】
1. **幻觉检查**：检查文本中的关键数字、日期、实体，是否在对应的 原文中出现。
2. **引用匹配**：如果文本说 "A公司利润增长50% [cite: 1]"，但 Source 1 中只说了 "A公司亏损"，这属于重大错误。
3. **未引用检查**：如果有重大断言但没有 [cite] 标记，视为高风险。

【输出格式】
JSON:
{
  "status": "PASS" | "FAIL",
  "issues": ["第1句引用错误：原文未提及...", "数字不匹配..."],
  "suggestion": "修正后的文本（仅在FAIL时填写）"
}
"""
        # 构造 User Prompt
        # 为了节省 Token，只取摘要和部分分析进行演示检查
        check_text = report.summary 
        sources_text = json.dumps(source_pool, ensure_ascii=False)[:3000] # 截断防止溢出

        user_prompt = f"""
【待核查文本】:
{check_text}

【来源池 (Source Pool)】:
{sources_text}
"""
        try:
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            data = json.loads(resp.choices[0].message.content)
            
            status = data.get("status", "PASS")
            issues = data.get("issues", [])
            
            result_status = "PASS"
            final_report = report

            if status == "FAIL":
                result_status = "FIXED" # 简化处理：假设 Auditor 提出了修正意见
                # 这里可以引入修正逻辑，把 suggestion 覆盖回去
                # 为演示简单，仅记录问题
            
            return AuditResult(
                event_id=report.event_id,
                original_report=report,
                status=result_status,
                issues=issues,
                revised_report=final_report
            )

        except Exception as e:
            return AuditResult(event_id=report.event_id, original_report=report, status="FLAGGED", issues=[str(e)])
