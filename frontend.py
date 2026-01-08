# frontend.py
# 最终修复版：显示真实 AI 研报

import streamlit as st
import requests
import pandas as pd
import numpy as np
import os

# === 1. 页面配置与样式 ===
st.set_page_config(
    page_title="AI Financial Monitor Hub",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入自定义 CSS
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background-color: #1E1E1E; color: #E0E0E0; }
    [data-testid="stSidebar"] { background-color: #252526; }
    h1, h2, h3 { color: #FFFFFF !important; }
    div[data-testid="stContainer"] {
        background-color: #2D2D2D; padding: 20px; border-radius: 12px;
        border: 1px solid #3E3E3E; margin-bottom: 20px;
    }
    .stButton>button {
        background-color: #0E639C; color: white; border: none;
        border-radius: 8px; padding: 10px 20px; font-weight: bold;
    }
    .stButton>button:hover { background-color: #1177BB; }
    .stTextInput>div>div>input, .stTextArea>div>div>textarea {
        background-color: #3C3C3C; color: #FFFFFF;
        border: 1px solid #555555; border-radius: 8px;
    }
    .streamlit-expanderHeader { background-color: #3C3C3C; color: #FFFFFF; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# === 2. 初始化 Session State ===
if 'run_data' not in st.session_state:
    st.session_state.run_data = None
if 'api_status' not in st.session_state:
    st.session_state.api_status = "Unknown"

# === 3. 侧边栏 ===
with st.sidebar:
    st.title("AI Monitor Hub")
    st.markdown("---")
    st.button("📱 Dashboard", use_container_width=True, type="primary")
    st.button("👤 Profile", use_container_width=True)
    st.button("⚙️ Parameters", use_container_width=True)
    st.markdown("---")
    st.caption("System Version: v6.3.0 Fixed")

# === 4. 主界面 ===

st.title("AI Financial Monitor Hub")
st.header("Dashboard")

# --- 第一排：核心控制 ---
col_input, col_status, col_downloads = st.columns([2, 1, 2])

# [卡片 1] 输入
with col_input:
    with st.container():
        st.subheader("Input Parameters")
        default_queries = """site:pbc.gov.cn OR site:mof.gov.cn OR site:stats.gov.cn OR site:ndrc.gov.cn 宏观政策
site:csrc.gov.cn OR site:nfra.gov.cn OR site:safe.gov.cn 金融监管
site:gov.cn 国务院重磅
site:cs.com.cn OR site:cnstock.com OR site:stcn.com 资本市场
site:financialnews.com.cn OR site:ce.cn OR site:jjckb.cn 金融要闻
site:cfen.com.cn OR site:zhonghongwang.com OR site:cet.com.cn 经济动态
site:chnfund.com OR site:cbimc.cn OR site:bbtnews.com.cn 行业分析
site:caixin.com OR site:yicai.com OR site:21jingji.com 深度报道
site:cls.cn OR site:jiemian.com OR site:thepaper.cn OR site:jwview.com 财经快讯
site:eeo.com.cn OR site:cb.com.cn OR site:nbd.com.cn OR site:lanjinger.com 商业观察
site:bjnews.com.cn OR site:thecover.cn OR site:shobserver.com OR site:chinatimes.net.cn 财经热点"""
        
        query_input = st.text_area("Monitoring Keywords", value=default_queries, height=200)
        queries = [q.strip() for q in query_input.split('\n') if q.strip()]
        
        st.text_input("Annual Filter Value (Optional)", value="$1,875,000")
        run_btn = st.button("🚀 Run Audit Analysis", use_container_width=True)

# 处理运行
if run_btn:
    if not queries:
        st.error("Please enter at least one keyword.")
    else:
        with st.spinner("🤖 AI Agent is running full analysis workflow..."):
            try:
                # ✅ 使用你的 DevTunnel 公网地址
                api_url = "https://spw6pww2-8000.use.devtunnels.ms/api/run"
                
                response = requests.post(api_url, json={"queries": queries}, timeout=300)
                
                if response.status_code == 200:
                    st.session_state.run_data = response.json()
                    st.session_state.api_status = "Active"
                    st.success("✅ Analysis completed successfully!")
                else:
                    st.error(f"API Error: {response.text}")
                    st.session_state.api_status = "Error"
            except Exception as e:
                st.error(f"Connection Error: {e}")
                st.session_state.api_status = "Offline"

# [卡片 2] 状态
with col_status:
    with st.container():
        st.subheader("System Status")
        status_map = {
            "Active": ("✅ Active", "Running"),
            "Offline": ("🔴 Offline", "Connection Failed"),
            "Error": ("⚠️ Error", "API Error"),
            "Unknown": ("⚪ Idle", "Ready")
        }
        status_label, status_desc = status_map.get(st.session_state.api_status, status_map["Unknown"])
        st.markdown(f"# {status_label}")
        st.caption(status_desc)
        st.progress(100 if st.session_state.api_status == "Active" else 0)

# [卡片 3] 下载
with col_downloads:
    with st.container():
        st.subheader("Latest Reports")
        if st.session_state.run_data and st.session_state.run_data.get("download_link"):
            file_path = st.session_state.run_data.get("download_link")
            if file_path:
                 # 注意：如果是远程访问，download_button 只能下载 Server 本地文件
                 # 在演示版中，我们只提供按钮，暂不处理远程文件流传输的复杂逻辑
                 st.info(f"Report generated: {file_path}")
        
        # 静态历史记录
        reports_list = [
            {"title": "Q3 Monetary Policy Review", "date": "2026-01-03"},
        ]
        for rep in reports_list:
            with st.expander(f"📄 {rep['title']}", expanded=False):
                st.caption(f"Date: {rep['date']}")
                st.button("Download", key=rep['title'], use_container_width=True)

# --- 第二排：图表 ---
with st.container():
    st.subheader("Audit Findings Trend")
    chart_data = pd.DataFrame(np.random.randn(20, 2).cumsum(axis=0), columns=['Compliance Score', 'Risk Index'])
    st.line_chart(chart_data, height=300)

# --- 第三排：精选文章 (✅ 核心修改：显示真实内容) ---
st.subheader("Featured Articles & Insights")
st.caption("AI Generated Intelligence Reports:")

# 获取数据
reports = st.session_state.run_data.get("reports", []) if st.session_state.run_data else []

if not reports:
    st.info("👋 暂无报告。请点击上方的 'Run Audit Analysis' 按钮开始生成。")
else:
    # 动态创建列
    cols = st.columns(3)
    
    for i in range(len(reports)):
        # 确保只显示前3个，或者换行显示
        col = cols[i % 3]
        with col:
            # === 显示真实数据 ===
            report = reports[i]
            
            # 安全获取字段
            title = report.get('title', '无标题')
            summary = report.get('summary', '暂无摘要')
            analysis = report.get('analysis', '暂无深度分析')
            outlook = report.get('outlook', '暂无展望')
            
            # 使用卡片容器
            with st.container():
                st.image(f"https://via.placeholder.com/400x200/0E639C/FFFFFF?text=Report+{i+1}", use_container_width=True)
                st.markdown(f"#### {title}")
                st.markdown(f"_{summary[:80]}..._")
                
                with st.expander("阅读完整研报", expanded=False):
                    st.markdown("### 深度分析")
                    st.write(analysis)
                    st.markdown("### 未来展望")
                    st.info(outlook)
