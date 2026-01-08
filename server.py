# server.py
# 修复版：增加了数据格式转换 (Serialization)

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Any
import os

# 引入你的核心逻辑
from main import build_agent

# 定义前端传过来的数据格式
class MonitorRequest(BaseModel):
    queries: List[str]

app = FastAPI(title="Financial Agent API")

print("⚙️  正在初始化 AI Agent 引擎...")
agent_app = build_agent()
print("✅ 引擎加载完成！")

@app.get("/")
def home():
    return {"message": "Financial Agent API is running."}

@app.post("/api/run")
async def run_monitor(req: MonitorRequest):
    print(f"\n📩 收到前端请求，正在处理 {len(req.queries)} 个查询...")
    
    initial_state = {
        "queries": req.queries,
        "raw_articles": [], "events": [], "reports": [], 
        "audit_results": [], "final_file_path": None
    }
    
    try:
        # 1. 运行 Agent
        final_state = agent_app.invoke(initial_state)
        print("✅ Agent 工作流执行完毕，正在打包数据...")

        # 2. 【关键修复】提取并转换数据
        # 必须把 NewsReport 对象转换成字典，否则 JSON 传输会报错
        
        # 处理 Reports (文章)
        raw_reports = final_state.get("reports", [])
        formatted_reports = []
        for r in raw_reports:
            # 兼容处理：如果是 Pydantic 对象，转成 dict
            if hasattr(r, "model_dump"): 
                formatted_reports.append(r.model_dump())
            elif hasattr(r, "dict"): 
                formatted_reports.append(r.dict())
            else:
                formatted_reports.append(r) 

        # 处理 Audit Results (审计结果)
        raw_audits = final_state.get("audit_results", [])
        formatted_audits = []
        for r in raw_audits:
            formatted_audits.append({
                "status": getattr(r, "status", "UNKNOWN"),
                "correction_notes": getattr(r, "correction_notes", ""),
                "original_report_title": getattr(getattr(r, "original_report", {}), "title", "未知标题")
            })

        print(f"📦 打包完成: {len(formatted_reports)} 篇报告, {len(formatted_audits)} 条审计")

        # 3. 返回 JSON
        return {
            "status": "success",
            "reports": formatted_reports,         # 真实的研报数据
            "audit_results": formatted_audits,    # 真实的审计数据
            "download_link": final_state.get("final_file_path")
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ 严重错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
