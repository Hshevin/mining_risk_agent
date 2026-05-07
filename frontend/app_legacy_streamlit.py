"""
Streamlit 前端应用 — 工业控制室风格 SCADA Dashboard
强制暗色模式 | 仪表盘网格布局 | SSE 时间轴 | 路演演示模式
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# 尝试导入 demo_data，若失败则内置兜底
try:
    from frontend.demo_data import generate_mock_decision, get_demo_data_json, DEMO_ENTERPRISES, SCENARIO_NAMES
except Exception:
    DEMO_ENTERPRISES = {}
    SCENARIO_NAMES = {"chemical": "危险化学品", "metallurgy": "冶金", "dust": "粉尘涉爆"}
    def get_demo_data_json(sid: str) -> str:
        return "{}"
    def generate_mock_decision(sid: str, eid: str) -> Dict[str, Any]:
        return {"enterprise_id": eid, "scenario_id": sid, "mock": True, "predicted_level": "红", "final_status": "APPROVE"}

# =============================================================================
# 配置
# =============================================================================
API_BASE = "http://localhost:8000/api/v1"
HEALTH_URL = "http://localhost:8000/health"

st.set_page_config(
    page_title="工矿企业风险预警智能体 | SCADA",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# SCADA 工业控制室风格 CSS
# =============================================================================
_CUSTOM_CSS = """
<style>
    /* ─── 全局强制暗色 ─── */
    html, body, [class*="css"], .stApp {
        background-color: #0a0e1a !important;
        color: #e5e7eb !important;
        font-family: "Inter", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif !important;
    }
    .stApp {
        background: #0a0e1a;
    }
    /* Streamlit 主容器 */
    .main .block-container {
        background-color: #0a0e1a !important;
        padding-top: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    /* 侧边栏 */
    [data-testid="stSidebar"] {
        background-color: #0f172a !important;
        border-right: 1px solid #1f2937 !important;
        min-width: 220px !important;
        max-width: 260px !important;
    }
    [data-testid="stSidebar"] .block-container {
        background-color: #0f172a !important;
    }
    /* 隐藏 Streamlit 默认顶部装饰 */
    #MainMenu, header, footer {visibility: hidden;}

    /* ─── 字体系统 ─── */
    .font-mono {
        font-family: "JetBrains Mono", "Roboto Mono", "SF Mono", "Courier New", monospace !important;
    }
    .font-display {
        font-family: "Inter", "Noto Sans SC", sans-serif !important;
    }

    /* ─── 系统状态栏 ─── */
    .system-status-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #0f172a;
        border-bottom: 1px solid #374151;
        padding: 6px 20px;
        font-size: 12px;
        color: #9ca3af;
        margin: -1rem -1rem 1rem -1rem;
        width: calc(100% + 2rem);
        box-sizing: border-box;
    }
    .status-bar-item {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;
    }
    .status-dot.online { background: #10b981; box-shadow: 0 0 6px #10b981; }
    .status-dot.offline { background: #ef4444; box-shadow: 0 0 6px #ef4444; }
    .status-dot.warn { background: #eab308; box-shadow: 0 0 6px #eab308; }

    /* ─── 卡片系统 ─── */
    .scada-card {
        background: #1f2937;
        border: 1px solid #374151;
        border-radius: 10px;
        padding: 16px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        height: 100%;
        box-sizing: border-box;
    }
    .scada-card:hover {
        transform: scale(1.02);
        box-shadow: 0 0 20px rgba(59, 130, 246, 0.12);
    }
    .scada-card-title {
        font-size: 12px;
        color: #9ca3af;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 8px;
        font-weight: 600;
    }
    .scada-card-value {
        font-family: "JetBrains Mono", "Roboto Mono", monospace;
        font-size: 36px;
        font-weight: 700;
        line-height: 1.1;
    }
    .scada-card-sub {
        font-size: 12px;
        color: #6b7280;
        margin-top: 4px;
    }

    /* ─── 风险色彩 + 光晕 ─── */
    .glow-red {
        color: #ef4444;
        text-shadow: 0 0 12px rgba(239, 68, 68, 0.45);
    }
    .glow-orange {
        color: #f97316;
        text-shadow: 0 0 12px rgba(249, 115, 22, 0.35);
    }
    .glow-yellow {
        color: #eab308;
        text-shadow: 0 0 12px rgba(234, 179, 8, 0.35);
    }
    .glow-blue {
        color: #3b82f6;
        text-shadow: 0 0 12px rgba(59, 130, 246, 0.35);
    }
    .glow-green {
        color: #10b981;
        text-shadow: 0 0 12px rgba(16, 185, 129, 0.35);
    }
    .glow-white {
        color: #f3f4f6;
        text-shadow: 0 0 8px rgba(255, 255, 255, 0.15);
    }

    /* ─── 红级脉冲动画 ─── */
    @keyframes pulse-red {
        0%   { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.55); }
        50%  { box-shadow: 0 0 0 16px rgba(239, 68, 68, 0); }
        100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
    .risk-red-pulse {
        animation: pulse-red 2s infinite ease-in-out;
    }
    @keyframes pulse-border-red {
        0%   { border-color: rgba(239, 68, 68, 0.8); box-shadow: 0 0 8px rgba(239, 68, 68, 0.3); }
        50%  { border-color: rgba(239, 68, 68, 0.3); box-shadow: 0 0 20px rgba(239, 68, 68, 0.1); }
        100% { border-color: rgba(239, 68, 68, 0.8); box-shadow: 0 0 8px rgba(239, 68, 68, 0.3); }
    }

    /* ─── 科技感按钮 ─── */
    .scada-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        background: linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%);
        color: #fff;
        border: none;
        border-radius: 8px;
        padding: 12px 28px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.25s ease;
        box-shadow: 0 0 12px rgba(59, 130, 246, 0.25);
        letter-spacing: 0.02em;
        width: 100%;
    }
    .scada-btn:hover {
        box-shadow: 0 0 24px rgba(59, 130, 246, 0.5);
        filter: brightness(1.1);
    }
    .scada-btn-secondary {
        background: transparent;
        border: 1px solid #374151;
        color: #9ca3af;
        box-shadow: none;
    }
    .scada-btn-secondary:hover {
        border-color: #6b7280;
        color: #e5e7eb;
        box-shadow: 0 0 8px rgba(107, 114, 128, 0.2);
    }

    /* ─── 时间轴日志节点 ─── */
    .timeline-container {
        position: relative;
        padding-left: 24px;
    }
    .timeline-container::before {
        content: "";
        position: absolute;
        left: 7px;
        top: 4px;
        bottom: 4px;
        width: 2px;
        background: linear-gradient(to bottom, #10b981, #374151);
        border-radius: 1px;
    }
    .timeline-node {
        position: relative;
        margin-bottom: 14px;
        padding-left: 18px;
    }
    .timeline-node::before {
        content: "";
        position: absolute;
        left: -20px;
        top: 4px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: #111827;
        border: 2px solid #374151;
        z-index: 2;
        transition: all 0.4s ease;
    }
    .timeline-node.completed::before {
        background: #10b981;
        border-color: #10b981;
        box-shadow: 0 0 8px rgba(16, 185, 129, 0.5);
    }
    .timeline-node.failed::before {
        background: #ef4444;
        border-color: #ef4444;
        box-shadow: 0 0 8px rgba(239, 68, 68, 0.5);
    }
    .timeline-node.running::before {
        background: #eab308;
        border-color: #eab308;
        box-shadow: 0 0 8px rgba(234, 179, 8, 0.5);
        animation: pulse-node 1.5s infinite;
    }
    @keyframes pulse-node {
        0%   { box-shadow: 0 0 0 0 rgba(234, 179, 8, 0.5); }
        70%  { box-shadow: 0 0 0 8px rgba(234, 179, 8, 0); }
        100% { box-shadow: 0 0 0 0 rgba(234, 179, 8, 0); }
    }
    .timeline-content {
        background: rgba(31, 41, 55, 0.6);
        border: 1px solid #374151;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 13px;
    }
    .timeline-content .node-name {
        font-weight: 600;
        color: #e5e7eb;
        font-size: 13px;
    }
    .timeline-content .node-detail {
        color: #9ca3af;
        font-size: 12px;
        margin-top: 4px;
        font-family: "JetBrains Mono", monospace;
    }

    /* ─── 风控校验卡片 ─── */
    .validation-card {
        background: #111827;
        border: 1px solid #374151;
        border-radius: 10px;
        padding: 16px;
        height: 100%;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .validation-card:hover {
        transform: scale(1.02);
    }
    .validation-card.pass { border-color: rgba(16, 185, 129, 0.4); box-shadow: 0 0 12px rgba(16, 185, 129, 0.08); }
    .validation-card.fail { border-color: rgba(239, 68, 68, 0.4); box-shadow: 0 0 12px rgba(239, 68, 68, 0.08); }
    .validation-card.warn { border-color: rgba(234, 179, 8, 0.4); box-shadow: 0 0 12px rgba(234, 179, 8, 0.08); }

    /* ─── 进度条 ─── */
    .scada-progress-track {
        width: 100%;
        height: 8px;
        background: #1f2937;
        border-radius: 4px;
        overflow: hidden;
        border: 1px solid #374151;
    }
    .scada-progress-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.6s ease;
    }

    /* ─── JSON 代码编辑器风格 ─── */
    .json-code-block {
        background: #0d1117 !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
        color: #c9d1d9 !important;
        font-family: "JetBrains Mono", "SF Mono", monospace !important;
        font-size: 12px !important;
        line-height: 1.6 !important;
        padding: 16px !important;
        overflow-x: auto;
    }
    .json-key { color: #7ee787; }
    .json-string { color: #a5d6ff; }
    .json-number { color: #79c0ff; }
    .json-bool { color: #ff7b72; }

    /* ─── 科技感旋转器 ─── */
    @keyframes spin-tech {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    .tech-spinner {
        width: 40px;
        height: 40px;
        border: 2px solid transparent;
        border-top-color: #3b82f6;
        border-right-color: #06b6d4;
        border-radius: 50%;
        animation: spin-tech 0.8s linear infinite;
        box-shadow: 0 0 12px rgba(59, 130, 246, 0.3);
    }
    .tech-spinner-inner {
        width: 28px;
        height: 28px;
        border: 2px solid transparent;
        border-bottom-color: #10b981;
        border-left-color: #3b82f6;
        border-radius: 50%;
        animation: spin-tech 0.6s linear infinite reverse;
        margin: 4px;
    }

    /* ─── 演示模式高亮 ─── */
    @keyframes demo-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.3); }
        50%  { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
        100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
    }
    .demo-highlight {
        animation: demo-pulse 2s infinite ease-in-out;
        border-color: #3b82f6 !important;
    }

    /* ─── 决策建议卡片 ─── */
    .advice-card {
        background: #111827;
        border: 1px solid #374151;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
        transition: transform 0.2s ease;
    }
    .advice-card:hover {
        transform: scale(1.01);
        border-color: #4b5563;
    }
    .advice-label {
        font-size: 11px;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 4px;
    }
    .advice-value {
        font-size: 14px;
        color: #e5e7eb;
        font-weight: 500;
    }
    .advice-highlight {
        color: #3b82f6;
        font-weight: 600;
    }

    /* ─── 输入框暗色风格 ─── */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div > div {
        background-color: #111827 !important;
        color: #e5e7eb !important;
        border: 1px solid #374151 !important;
        border-radius: 6px !important;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
    }
    /* File uploader */
    .stFileUploader > div > button {
        background: #111827 !important;
        border: 1px dashed #374151 !important;
        color: #9ca3af !important;
    }
    /* DataFrame / Table */
    .stDataFrame, [data-testid="stDataFrameResizable"] {
        background: #111827 !important;
    }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        background: #0f172a !important;
        border-bottom: 1px solid #374151 !important;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: #9ca3af !important;
        border-radius: 6px 6px 0 0 !important;
        border: none !important;
        padding: 10px 20px !important;
        font-size: 13px !important;
        font-weight: 500 !important;
    }
    .stTabs [aria-selected="true"] {
        background: #1f2937 !important;
        color: #e5e7eb !important;
        border-bottom: 2px solid #3b82f6 !important;
    }
    /* Expander */
    .streamlit-expanderHeader {
        background: #111827 !important;
        border: 1px solid #374151 !important;
        border-radius: 8px !important;
        color: #e5e7eb !important;
        font-size: 13px !important;
    }
    .streamlit-expanderContent {
        background: #0a0e1a !important;
        border: 1px solid #374151 !important;
        border-top: none !important;
        border-radius: 0 0 8px 8px !important;
    }
    /* Metric */
    [data-testid="stMetricValue"] {
        font-family: "JetBrains Mono", monospace !important;
        color: #e5e7eb !important;
    }
    [data-testid="stMetricLabel"] {
        color: #9ca3af !important;
        font-size: 11px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
    }
    /* Alert boxes */
    .stAlert {
        background: #111827 !important;
        border: 1px solid #374151 !important;
        color: #e5e7eb !important;
    }
    .stAlert [data-testid="stAlertContent"] {
        color: #e5e7eb !important;
    }
    /* st.info / success / warning / error backgrounds */
    .stAlert[data-baseweb="notification"] {
        background: #111827 !important;
    }

    /* ─── 拦截横幅 ─── */
    .intercept-banner {
        text-align: center;
        padding: 20px;
        border-radius: 12px;
        margin-top: 16px;
        border: 1px solid;
        font-size: 18px;
        font-weight: 700;
        letter-spacing: 0.04em;
    }

    /* ─── 记忆卡片 ─── */
    .memory-card {
        padding: 10px 14px;
        border-radius: 8px;
        background: #111827;
        border-left: 3px solid;
        margin-bottom: 8px;
        font-size: 13px;
        transition: transform 0.15s ease;
    }
    .memory-card:hover {
        transform: translateX(4px);
    }

    /* ─── 滚动条 ─── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0a0e1a; }
    ::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #4b5563; }

    /* ─── 知识库代码块 ─── */
    pre {
        background: #0d1117 !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
    }
    code {
        font-family: "JetBrains Mono", monospace !important;
        font-size: 12px !important;
    }
</style>
"""
st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

# =============================================================================
# 状态管理（Session State）
# =============================================================================
def _init_session_state() -> None:
    defaults = {
        "current_scenario": "chemical",
        "scenario_name": "危险化学品",
        "last_decision": None,
        "uploaded_df": None,
        "stream_log": [],
        "iteration_anim": False,
        "iteration_progress": 0,
        "short_term_memories": [],
        "long_term_query": "",
        "long_term_results": [],
        "glm5_status": None,
        "demo_mode": False,
        "demo_highlight_idx": 0,
        "backend_health": None,
        "last_update": time.strftime("%H:%M:%S"),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_session_state()


# =============================================================================
# API 封装
# =============================================================================

def api_health() -> Dict[str, Any]:
    try:
        resp = requests.get(HEALTH_URL, timeout=3)
        return resp.json() if resp.status_code == 200 else {"status": "error"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def api_switch_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.post(f"{API_BASE}/agent/scenario/{scenario_id}", timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def api_decision(enterprise_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.post(
            f"{API_BASE}/agent/decision",
            json={"enterprise_id": enterprise_id, "data": data},
            timeout=60,
        )
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def api_decision_stream(enterprise_id: str, data: Dict[str, Any]):
    """SSE 流式生成器"""
    try:
        resp = requests.post(
            f"{API_BASE}/agent/decision/stream",
            json={"enterprise_id": enterprise_id, "data": data},
            stream=True,
            timeout=120,
        )
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield json.loads(line[6:])
    except Exception as e:
        yield {"node": "workflow", "status": "failed", "detail": str(e)}


def api_iteration_status() -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(f"{API_BASE}/iteration/status", timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def api_iteration_trigger() -> Optional[Dict[str, Any]]:
    try:
        resp = requests.post(f"{API_BASE}/iteration/trigger", json={}, timeout=60)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def api_upload_file(file_bytes: bytes, filename: str) -> Optional[Dict[str, Any]]:
    try:
        files = {"file": (filename, file_bytes)}
        resp = requests.post(f"{API_BASE}/data/upload", files=files, timeout=30)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def api_knowledge_list() -> List[str]:
    try:
        resp = requests.get(f"{API_BASE}/knowledge/list", timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except Exception:
        return []


def api_knowledge_read(filename: str) -> Optional[str]:
    try:
        resp = requests.get(f"{API_BASE}/knowledge/read/{filename}", timeout=10)
        return resp.json().get("content", "") if resp.status_code == 200 else None
    except Exception:
        return None


def api_audit_query(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        resp = requests.get(f"{API_BASE}/audit/query", params=params, timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except Exception:
        return []


# =============================================================================
# 可视化组件 — SCADA 暗色风格
# =============================================================================

def plot_probability_distribution(probs: Dict[str, float], center_level: str = "") -> go.Figure:
    """环形概率分布图，中心显示最终判定等级"""
    colors = {"红": "#ef4444", "橙": "#f97316", "黄": "#eab308", "蓝": "#3b82f6"}
    labels = list(probs.keys())
    values = [probs.get(k, 0) for k in labels]
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.60,
        marker_colors=[colors.get(l, "#6b7280") for l in labels],
        textinfo="label+percent",
        textfont_size=14,
        textfont_color="#e5e7eb",
        hovertemplate="<b>%{label}</b><br>概率: %{percent}<extra></extra>",
    )])
    # 中心文字
    fig.add_annotation(
        text=f"<b>{center_level}</b>" if center_level else "",
        x=0.5, y=0.5,
        font_size=28,
        font_color=colors.get(center_level, "#e5e7eb"),
        font_family="JetBrains Mono, monospace",
        showarrow=False,
    )
    fig.update_layout(
        title="风险等级概率分布",
        title_font_size=14,
        title_font_color="#9ca3af",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=340,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.12,
            font=dict(color="#9ca3af", size=12),
        ),
    )
    return fig


def plot_shap_bar(shap_data: List[Dict[str, Any]], top_n: int = 5) -> go.Figure:
    """SHAP 水平条形图，带渐变色彩"""
    if not shap_data:
        fig = go.Figure()
        fig.update_layout(
            title="暂无 SHAP 数据",
            title_font_color="#6b7280",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=250,
        )
        return fig

    sorted_items = sorted(shap_data, key=lambda x: abs(x.get("contribution", 0)), reverse=True)[:top_n]
    names = [i["feature"] for i in sorted_items]
    values = [i.get("contribution", 0) for i in sorted_items]

    # 渐变色彩：正向红色系，负向绿色系
    bar_colors = []
    for v in values:
        if v >= 0:
            intensity = min(abs(v) / max(max(values), 0.01), 1.0)
            bar_colors.append(f"rgba(239, 68, 68, {0.4 + intensity * 0.6})")
        else:
            intensity = min(abs(v) / max(max([abs(x) for x in values]), 0.01), 1.0)
            bar_colors.append(f"rgba(16, 185, 129, {0.4 + intensity * 0.6})")

    fig = go.Figure(go.Bar(
        x=values,
        y=names,
        orientation="h",
        marker=dict(
            color=bar_colors,
            line=dict(color="rgba(255,255,255,0.1)", width=1),
        ),
        text=[f"{v:+.3f}" for v in values],
        textposition="outside",
        textfont=dict(color="#e5e7eb", size=12, family="JetBrains Mono, monospace"),
    ))
    fig.update_layout(
        title=f"Top {top_n} SHAP 特征贡献度",
        title_font_size=14,
        title_font_color="#9ca3af",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin=dict(l=10, r=50, t=40, b=10),
        showlegend=False,
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(color="#9ca3af", size=12),
            gridcolor="#374151",
        ),
        xaxis=dict(
            tickfont=dict(color="#9ca3af", size=11, family="JetBrains Mono, monospace"),
            gridcolor="#374151",
            zerolinecolor="#4b5563",
        ),
    )
    fig.add_vline(x=0, line_width=1, line_color="#6b7280")
    return fig


def plot_confidence_gauge(confidence: float, threshold: float) -> go.Figure:
    """置信度仪表盘图"""
    pct = min(max(confidence * 100, 0), 100)
    color = "#10b981" if confidence >= threshold else "#eab308" if confidence >= threshold * 0.8 else "#ef4444"

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=pct,
        number=dict(
            suffix="%",
            font=dict(size=32, color="#e5e7eb", family="JetBrains Mono, monospace"),
        ),
        delta=dict(reference=threshold * 100, suffix="%", font=dict(size=14, color="#9ca3af")),
        gauge=dict(
            axis=dict(range=[0, 100], tickcolor="#374151", tickfont=dict(color="#6b7280", size=10)),
            bar=dict(color=color, thickness=0.7),
            bgcolor="#111827",
            bordercolor="#374151",
            borderwidth=2,
            steps=[
                dict(range=[0, threshold * 80], color="#1f2937"),
                dict(range=[threshold * 80, threshold * 100], color="#292516"),
                dict(range=[threshold * 100, 100], color="#0f2e1f"),
            ],
            threshold=dict(
                line=dict(color="#f97316", width=3),
                thickness=0.85,
                value=threshold * 100,
            ),
        ),
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=20, r=20, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#9ca3af"),
    )
    return fig


# =============================================================================
# 辅助渲染函数
# =============================================================================

def _glow_class_for_level(level: str) -> str:
    return {"红": "glow-red", "橙": "glow-orange", "黄": "glow-yellow", "蓝": "glow-blue"}.get(level, "glow-white")


def _hex_for_level(level: str) -> str:
    return {"红": "#ef4444", "橙": "#f97316", "黄": "#eab308", "蓝": "#3b82f6"}.get(level, "#6b7280")


def _render_system_status_bar() -> None:
    """页面最顶部系统状态栏"""
    health = st.session_state.get("backend_health") or api_health()
    st.session_state.backend_health = health
    st.session_state.last_update = time.strftime("%H:%M:%S")

    is_online = health.get("status") == "healthy"
    dot_class = "online" if is_online else "offline"
    conn_text = "后端在线" if is_online else "后端离线"
    scenario = SCENARIO_NAMES.get(st.session_state.current_scenario, st.session_state.current_scenario)
    version = health.get("version", "v1.0.0")
    demo_tag = '<span style="background:#3b82f6;color:#fff;padding:1px 6px;border-radius:4px;font-size:10px;margin-left:8px;">DEMO</span>' if st.session_state.get("demo_mode") else ""

    st.markdown(
        f'<div class="system-status-bar">'
        f'  <div style="display:flex;gap:24px;">'
        f'    <div class="status-bar-item"><span class="status-dot {dot_class}"></span>{conn_text}</div>'
        f'    <div class="status-bar-item">场景: <b style="color:#e5e7eb;">{scenario}</b></div>'
        f'    <div class="status-bar-item">模型: <b style="color:#e5e7eb;">{version}</b></div>'
        f'  </div>'
        f'  <div style="display:flex;align-items:center;gap:16px;">'
        f'    <div class="status-bar-item">最后更新: {st.session_state.last_update}</div>'
        f'    {demo_tag}'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_kpi_cards(result: Dict[str, Any]) -> None:
    """顶部 KPI 卡片行：风险等级 | 置信度 | 校验状态 | 迭代状态"""
    level = result.get("predicted_level", "未知")
    final_status = result.get("final_status", "UNKNOWN")
    mc = result.get("monte_carlo_result", {})
    confidence = mc.get("confidence", 0.0)
    threshold = mc.get("threshold", 0.85)
    march = result.get("march_result", {})
    three_d = result.get("three_d_risk", {})

    level_hex = _hex_for_level(level)
    glow_cls = _glow_class_for_level(level)
    is_red = level == "红"

    status_info = {
        "APPROVE": ("通过", "#10b981", "glow-green"),
        "HUMAN_REVIEW": ("人工审核", "#eab308", "glow-yellow"),
        "REJECT": ("拦截", "#ef4444", "glow-red"),
    }.get(final_status, ("未知", "#6b7280", "glow-white"))

    march_ok = march.get("passed", False)
    march_text, march_color, march_glow = ("通过", "#10b981", "glow-green") if march_ok else ("失败", "#ef4444", "glow-red")

    three_d_blocked = three_d.get("blocked", False)
    td_text, td_color, td_glow = ("通过", "#10b981", "glow-green") if not three_d_blocked else ("拦截", "#ef4444", "glow-red")

    col1, col2, col3, col4 = st.columns(4)
    cards = [
        (col1, "风险等级", level, glow_cls, f"企业: {result.get('enterprise_id', '')}", is_red),
        (col2, "蒙特卡洛置信度", f"{confidence:.1%}", "glow-blue" if confidence >= threshold else "glow-yellow", f"阈值: {threshold:.0%}", False),
        (col3, "MARCH 校验", march_text, march_glow, march.get("reason", "")[:30] + "..." if len(march.get("reason", "")) > 30 else march.get("reason", ""), False),
        (col4, "三维风险评估", td_text, td_glow, f"总分: {three_d.get('total_score', 0):.2f}", False),
    ]

    for col, title, value, glow, sub, pulse in cards:
        with col:
            pulse_cls = " risk-red-pulse" if pulse else ""
            st.markdown(
                f'<div class="scada-card{pulse_cls}" style="border-top: 2px solid {level_hex if pulse else '#374151'};">'
                f'  <div class="scada-card-title">{title}</div>'
                f'  <div class="scada-card-value {glow}">{value}</div>'
                f'  <div class="scada-card-sub">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_validation_cards(result: Dict[str, Any]) -> None:
    """风控拦截校验卡片"""
    march = result.get("march_result", {})
    mc = result.get("monte_carlo_result", {})
    three_d = result.get("three_d_risk", {})
    final_status = result.get("final_status", "UNKNOWN")

    col1, col2, col3 = st.columns(3)

    with col1:
        passed = march.get("passed", False)
        cls = "pass" if passed else "fail"
        color = "#10b981" if passed else "#ef4444"
        icon = "✓" if passed else "✗"
        st.markdown(
            f'<div class="validation-card {cls}">'
            f'  <div class="scada-card-title" style="color:{color};">{icon} MARCH 规则校验</div>'
            f'  <div style="font-size:13px;color:#e5e7eb;margin-top:8px;">{march.get("reason", "N/A")}</div>'
            f'  <div class="scada-card-sub" style="margin-top:8px;">重试次数: {march.get("retry_count", 0)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col2:
        mc_passed = mc.get("passed", False)
        cls = "pass" if mc_passed else "warn"
        color = "#10b981" if mc_passed else "#eab308"
        confidence = mc.get("confidence", 0.0)
        threshold = mc.get("threshold", 0.85)
        pct = min(max(confidence * 100, 0), 100)
        bar_color = "#10b981" if mc_passed else "#eab308" if confidence >= threshold * 0.8 else "#ef4444"
        st.markdown(
            f'<div class="validation-card {cls}">'
            f'  <div class="scada-card-title" style="color:{color};">🎲 蒙特卡洛置信度检验</div>'
            f'  <div style="font-size:13px;color:#e5e7eb;margin-top:8px;">'
            f'    置信度: <span class="font-mono" style="color:{bar_color};font-weight:700;">{confidence:.1%}</span>'
            f'    <span style="color:#6b7280;"> / 阈值 {threshold:.0%}</span>'
            f'  </div>'
            f'  <div class="scada-progress-track" style="margin-top:10px;">'
            f'    <div class="scada-progress-fill" style="width:{pct}%;background:{bar_color};"></div>'
            f'  </div>'
            f'  <div class="scada-card-sub" style="margin-top:6px;">采样通过: {mc.get("valid_count", "N/A")}/{mc.get("total_samples", "N/A")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col3:
        blocked = three_d.get("blocked", False)
        cls = "pass" if not blocked else "fail"
        color = "#10b981" if not blocked else "#ef4444"
        total_score = three_d.get("total_score", 0.0)
        risk_threshold = 2.2 if result.get("scenario_id") == "chemical" else 2.5
        dims = []
        for d in ["severity", "relevance", "irreversibility"]:
            val = three_d.get(d, "")
            if val:
                dims.append(f"{d}: {val}")
        st.markdown(
            f'<div class="validation-card {cls}">'
            f'  <div class="scada-card-title" style="color:{color};">🛡️ 三维风险评估</div>'
            f'  <div style="font-size:13px;color:#e5e7eb;margin-top:8px;">'
            f'    总分: <span class="font-mono" style="color:{color};font-weight:700;">{total_score:.2f}</span>'
            f'    <span style="color:#6b7280;"> / 阈值 {risk_threshold}</span>'
            f'  </div>'
            f'  <div style="font-size:12px;color:#9ca3af;margin-top:6px;">{" | ".join(dims) if dims else ""}</div>'
            f'  <div class="scada-card-sub" style="margin-top:6px;">{three_d.get("reason", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if final_status in ("REJECT", "HUMAN_REVIEW"):
        banner_color = "#ef4444" if final_status == "REJECT" else "#eab308"
        banner_hex = "rgba(239,68,68,0.12)" if final_status == "REJECT" else "rgba(234,179,8,0.12)"
        banner_icon = "🚫" if final_status == "REJECT" else "👁️"
        banner_text = "已拦截 — 禁止自动推送" if final_status == "REJECT" else "已拦截 — 转人工审核"
        st.markdown(
            f'<div class="intercept-banner" style="background:{banner_hex};border-color:{banner_color};color:{banner_color};">'
            f'  {banner_icon} {banner_text}'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_decision_advice(result: Dict[str, Any]) -> None:
    """决策建议左右分栏"""
    gov = result.get("government_intervention", {})
    ent = result.get("enterprise_control", {})

    col_gov, col_ent = st.columns(2)

    with col_gov:
        st.markdown("<div style='font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:12px;'>🏛️ 政府干预建议</div>", unsafe_allow_html=True)
        dept_pri = gov.get("department_primary", {})
        if dept_pri:
            st.markdown(
                f'<div class="advice-card">'
                f'  <div class="advice-label">主责部门</div>'
                f'  <div class="advice-value advice-highlight">{dept_pri.get("name", "")}</div>'
                f'  <div class="advice-label" style="margin-top:8px;">联系人角色</div>'
                f'  <div class="advice-value">{dept_pri.get("contact_role", "")}</div>'
                f'  <div class="advice-label" style="margin-top:8px;">行动指令</div>'
                f'  <div class="advice-value" style="color:#ef4444;font-weight:600;">🎯 {dept_pri.get("action", "")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        actions = gov.get("actions", [])
        if actions:
            for a in actions:
                st.markdown(
                    f'<div class="advice-card" style="border-left:3px solid #3b82f6;">'
                    f'  <div style="font-size:13px;color:#e5e7eb;">▸ {a}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        deadline = gov.get("deadline_hours", "N/A")
        st.markdown(
            f'<div class="advice-card">'
            f'  <div class="advice-label">截止时间</div>'
            f'  <div class="advice-value font-mono" style="color:#f97316;">{deadline} 小时</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if gov.get("follow_up"):
            st.markdown(
                f'<div class="advice-card">'
                f'  <div class="advice-label">跟进要求</div>'
                f'  <div class="advice-value">{gov["follow_up"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with col_ent:
        st.markdown("<div style='font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:12px;'>🏭 企业管控建议</div>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="advice-card">'
            f'  <div class="advice-label">目标设备</div>'
            f'  <div class="advice-value advice-highlight">{ent.get("equipment_id", "")}</div>'
            f'  <div class="advice-label" style="margin-top:8px;">操作指令</div>'
            f'  <div class="advice-value" style="color:#f97316;font-weight:600;">🎯 {ent.get("operation", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        params = ent.get("parameters", {})
        if params:
            param_label_map = {
                "dcs_tag": "DCS 控制标签",
                "target_values": "目标设定值",
                "monitoring_interval_minutes": "监测间隔",
                "可燃气体报警设定值": "可燃气体报警设定值",
                "煤气压力报警设定值": "煤气压力报警设定值",
                "粉尘浓度报警设定值": "粉尘浓度报警设定值",
            }
            params_html = "\n".join(
                f'  <div style="font-size:13px;color:#e5e7eb;margin-bottom:6px;">'
                f'    <span style="color:#9ca3af;">{param_label_map.get(k, k)}：</span>'
                f'    <span style="font-weight:500;">{v}</span>'
                f'  </div>'
                for k, v in params.items()
            )
            st.markdown(
                f'<div class="advice-card">'
                f'  <div class="advice-label">调控参数</div>'
                f'  <div style="line-height:1.6;">'
                f'    {params_html}'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        emergency = ent.get("emergency_resources", [])
        if emergency:
            st.markdown(
                f'<div class="advice-card" style="border-left:3px solid #ef4444;">'
                f'  <div class="advice-label">应急资源</div>'
                f'  <div style="font-size:13px;color:#ef4444;">{" · ".join(emergency)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        personnel = ent.get("personnel_actions", [])
        if personnel:
            st.markdown(
                f'<div class="advice-card" style="border-left:3px solid #eab308;">'
                f'  <div class="advice-label">人员动作</div>'
                f'  <div style="font-size:13px;color:#eab308;">{" · ".join(personnel)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_timeline_logs(result: Dict[str, Any]) -> None:
    """时间轴样式 SSE 节点日志"""
    node_status = result.get("node_status", [])
    if not node_status:
        st.caption("暂无节点日志")
        return

    nodes_html = '<div class="timeline-container">'
    for ns in node_status:
        status = ns.get("status", "")
        css = status if status in ("completed", "failed", "running") else ""
        icon = "✓" if status == "completed" else "✗" if status == "failed" else "⟳"
        detail = ns.get("detail", "")
        nodes_html += (
            f'<div class="timeline-node {css}">'
            f'  <div class="timeline-content">'
            f'    <div class="node-name">{icon} {ns.get("node", "")}</div>'
            f'    {f"<div class=\'node-detail\'>{detail}</div>" if detail else ""}'
            f'  </div>'
            f'</div>'
        )
    nodes_html += '</div>'
    st.markdown(nodes_html, unsafe_allow_html=True)


def _render_json_editor_style(data: Dict[str, Any]) -> None:
    """代码编辑器风格的 JSON 展示"""
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    # 简单的语法高亮
    lines = json_str.split("\n")
    colored_lines = []
    for line in lines:
        colored = (
            line
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        # 键
        if '"' in colored and ':' in colored:
            parts = colored.split('":', 1)
            if len(parts) == 2 and parts[0].strip().startswith('"'):
                key = parts[0] + '"'
                rest = ':' + parts[1]
                colored = f'<span class="json-key">{key}</span>{rest}'
        # 字符串值
        colored = colored.replace('"true"', '<span class="json-bool">true</span>')
        colored = colored.replace('"false"', '<span class="json-bool">false</span>')
        colored = colored.replace('true', '<span class="json-bool">true</span>')
        colored = colored.replace('false', '<span class="json-bool">false</span>')
        colored = colored.replace('null', '<span class="json-bool">null</span>')
        colored_lines.append(colored)

    highlighted = "\n".join(colored_lines)
    st.markdown(
        f'<pre class="json-code-block">{highlighted}</pre>',
        unsafe_allow_html=True,
    )


# =============================================================================
# 侧边栏 — 收窄，仅保留场景切换和系统状态概览
# =============================================================================

def sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div style="font-size:16px;font-weight:700;color:#e5e7eb;margin-bottom:4px;">🛡️ 风险预警智能体</div>'
            '<div style="font-size:10px;color:#6b7280;letter-spacing:0.1em;margin-bottom:16px;">SCADA DASHBOARD v1.0</div>',
            unsafe_allow_html=True,
        )

        health = api_health()
        if health.get("status") == "healthy":
            st.markdown(
                '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#10b981;margin-bottom:12px;">'
                '<span class="status-dot online"></span>后端服务正常</div>',
                unsafe_allow_html=True,
            )
            st.session_state.glm5_status = "connected"
        else:
            st.markdown(
                '<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:#ef4444;margin-bottom:12px;">'
                '<span class="status-dot offline"></span>后端离线 (Mock)</div>',
                unsafe_allow_html=True,
            )
            st.session_state.glm5_status = "disconnected"

        st.markdown('<div style="border-top:1px solid #1f2937;margin:12px 0;"></div>', unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:8px;">场景配置</div>',
            unsafe_allow_html=True,
        )
        scenario = st.selectbox(
            "当前场景",
            ["chemical", "metallurgy", "dust"],
            format_func=lambda x: {"chemical": "🧪 危险化学品", "metallurgy": "🔩 冶金", "dust": "💨 粉尘涉爆"}.get(x, x),
            index=["chemical", "metallurgy", "dust"].index(st.session_state.current_scenario),
            key="sidebar_scenario",
            label_visibility="collapsed",
        )
        if scenario != st.session_state.current_scenario:
            result = api_switch_scenario(scenario)
            if result:
                st.session_state.current_scenario = result["scenario_id"]
                st.session_state.scenario_name = result["scenario_name"]
                st.success(f"已切换: {result['scenario_name']}")
            else:
                st.session_state.current_scenario = scenario
                st.session_state.scenario_name = SCENARIO_NAMES.get(scenario, scenario)
                st.warning("后端场景切换失败，已本地切换")

        st.markdown('<div style="border-top:1px solid #1f2937;margin:12px 0;"></div>', unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:8px;">系统状态</div>',
            unsafe_allow_html=True,
        )
        status = api_iteration_status()
        if status:
            state = status.get("current_state_cn", status.get("current_state", "未知"))
            st.markdown(
                f'<div style="font-size:13px;color:#e5e7eb;font-weight:600;margin-bottom:4px;">{state}</div>',
                unsafe_allow_html=True,
            )
            pending = status.get("pending_approvals", [])
            if pending:
                st.markdown(
                    f'<div style="font-size:11px;color:#eab308;">⏳ 待审批: {len(pending)} 项</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<div style="font-size:11px;color:#6b7280;">无待审批事项</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:11px;color:#6b7280;">无法获取迭代状态</div>', unsafe_allow_html=True)

        st.markdown('<div style="border-top:1px solid #1f2937;margin:12px 0;"></div>', unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:8px;">路演控制</div>',
            unsafe_allow_html=True,
        )
        demo_mode = st.toggle("演示模式", value=st.session_state.get("demo_mode", False), key="demo_toggle")
        st.session_state.demo_mode = demo_mode
        if demo_mode:
            st.markdown(
                '<div style="font-size:11px;color:#3b82f6;margin-top:4px;">✨ 自动轮播已启用</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div style="position:fixed;bottom:12px;font-size:10px;color:#374151;">'
            'Harness 工程化管控<br>推荐 1920×1080 投影</div>',
            unsafe_allow_html=True,
        )


# =============================================================================
# 标签页1：企业风险预测（核心演示页）
# =============================================================================

def tab_risk_prediction() -> None:
    st.markdown(
        '<div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:16px;">'
        '🎯 企业风险预测 — 上传数据 → 模型预测 → 决策建议 → 三重风控拦截</div>',
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([1, 3.2])

    with col_left:
        st.markdown(
            '<div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:8px;">输入面板</div>',
            unsafe_allow_html=True,
        )
        enterprise_id = st.text_input("企业 ID", value="ENT-DEMO-001", key="rp_enterprise_id")

        scenario_display = SCENARIO_NAMES.get(st.session_state.current_scenario, st.session_state.current_scenario)
        st.markdown(
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:10px;">当前场景: <b style="color:#e5e7eb;">{scenario_display}</b></div>',
            unsafe_allow_html=True,
        )

        if st.button("🎲 模拟数据填充", key="rp_mock_fill"):
            st.session_state.demo_data_json = get_demo_data_json(st.session_state.current_scenario)
            st.success("已填充高危模拟数据")

        demo_json = st.session_state.get("demo_data_json", get_demo_data_json(st.session_state.current_scenario))
        data_text = st.text_area("企业数据（JSON）", value=demo_json, height=240, key="rp_data_text")

        uploaded_file = st.file_uploader("或上传 CSV/Excel", type=["csv", "xlsx"])
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                st.session_state.uploaded_df = df
                st.success(f"已加载 {len(df)} 行 × {len(df.columns)} 列")
                st.dataframe(df.head(3), use_container_width=True)
            except Exception as e:
                st.error(f"读取失败: {e}")

        st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)
        btn_predict = st.button("🚀 执行预测", type="primary", use_container_width=True, key="rp_predict_btn")

    with col_right:
        if btn_predict:
            try:
                input_data = json.loads(data_text)
            except json.JSONDecodeError:
                st.error("JSON 格式错误，请检查输入")
                return

            if st.session_state.uploaded_df is not None:
                row = st.session_state.uploaded_df.iloc[0].to_dict()
                input_data.update({k: v for k, v in row.items() if pd.notna(v)})

            spinner_placeholder = st.empty()
            with spinner_placeholder:
                st.markdown(
                    '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px;">'
                    '  <div class="tech-spinner"><div class="tech-spinner-inner"></div></div>'
                    '  <div style="margin-top:16px;font-size:13px;color:#9ca3af;font-family:JetBrains Mono,monospace;">SYSTEM INITIALIZING WORKFLOW...</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            result = api_decision(enterprise_id, input_data)
            spinner_placeholder.empty()

            if result is None:
                st.warning("后端无响应，启用本地 Mock 数据")
                result = generate_mock_decision(st.session_state.current_scenario, enterprise_id)

            st.session_state.last_decision = result
            _render_prediction_result(result)
        else:
            last = st.session_state.get("last_decision")
            if last:
                _render_prediction_result(last)
            else:
                st.markdown(
                    '<div style="display:flex;align-items:center;justify-content:center;height:400px;color:#374151;font-size:14px;">'
                    '👈 在左侧输入企业数据并点击「执行预测」查看结果</div>',
                    unsafe_allow_html=True,
                )


def _render_prediction_result(result: Dict[str, Any]) -> None:
    is_mock = result.get("mock", False)
    level = result.get("predicted_level", "未知")
    final_status = result.get("final_status", "UNKNOWN")
    scenario_id = result.get("scenario_id", "chemical")

    level_hex = _hex_for_level(level)
    glow_cls = _glow_class_for_level(level)

    mock_html = '<span style="display:inline-block;background:#f97316;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;margin-left:8px;">MOCK</span>' if is_mock else ""

    is_red = level == "红"
    pulse_style = "risk-red-pulse" if is_red else ""
    st.markdown(
        f'<div style="text-align:center;padding:20px;border-radius:12px;background:#111827;border:1px solid {level_hex};margin-bottom:20px;" class="{pulse_style}">'
        f'  <div style="font-size:12px;color:#9ca3af;margin-bottom:8px;font-family:JetBrains Mono,monospace;">'
        f'    {result.get("enterprise_id", "")} | {SCENARIO_NAMES.get(scenario_id, scenario_id)}{mock_html}'
        f'  </div>'
        f'  <div style="font-size:42px;font-weight:800;{glow_cls};font-family:JetBrains Mono,monospace;line-height:1;">{level}级风险</div>'
        f'  <div style="margin-top:12px;">'
        f'    <span style="display:inline-block;padding:6px 18px;border-radius:20px;font-size:13px;font-weight:600;color:#fff;background:{level_hex};">'
        f'      {final_status}'
        f'    </span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if is_mock:
        st.info("当前返回为 Mock 降级数据（后端 Workflow 初始化失败或 GLM-5 API 不可用），用于路演演示。")

    st.markdown('<div style="margin-bottom:16px;"></div>', unsafe_allow_html=True)
    _render_kpi_cards(result)

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        probs = result.get("probability_distribution", {})
        if probs:
            st.plotly_chart(plot_probability_distribution(probs, center_level=level), use_container_width=True, key="prob_pie")
    with col2:
        shap = result.get("shap_contributions", [])
        if shap:
            st.plotly_chart(plot_shap_bar(shap, top_n=5), use_container_width=True, key="shap_bar")

    st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)
    _render_decision_advice(result)

    st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:12px;">🔒 风控拦截状态</div>',
        unsafe_allow_html=True,
    )
    _render_validation_cards(result)

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    with st.expander("📡 SSE 实时日志（工作流节点执行状态）", expanded=True):
        _render_timeline_logs(result)

    with st.expander("🔍 原始决策 JSON", expanded=False):
        _render_json_editor_style(result)


# =============================================================================
# 标签页2：知识库与记忆系统
# =============================================================================

def tab_knowledge_memory() -> None:
    st.markdown(
        '<div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:16px;">'
        "📚 知识库与记忆系统 — AgentFS + Git 版本控制 + 长短期混合记忆</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:10px;">'
        "📁 六大核心知识库</div>",
        unsafe_allow_html=True,
    )
    files = api_knowledge_list()
    if not files:
        kb_dir = os.path.join(os.path.dirname(__file__), "..", "knowledge_base")
        if os.path.isdir(kb_dir):
            files = [f for f in os.listdir(kb_dir) if f.endswith(".md")]

    if not files:
        st.warning("未找到知识库文件，请检查 knowledge_base/ 目录")
        return

    st.markdown(
        f'<div style="font-size:12px;color:#10b981;margin-bottom:10px;">共发现 {len(files)} 个知识库文件</div>',
        unsafe_allow_html=True,
    )
    selected_file = st.selectbox("选择文件预览", files, key="kb_select")
    if selected_file:
        content = api_knowledge_read(selected_file)
        if content is None:
            kb_path = os.path.join(os.path.dirname(__file__), "..", "knowledge_base", selected_file)
            try:
                with open(kb_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""
        if content:
            preview = content[:1200] + ("\n\n..." if len(content) > 1200 else "")
            st.markdown(f'<pre class="json-code-block">{preview}</pre>', unsafe_allow_html=True)
        else:
            st.error("无法读取文件内容")

    st.markdown('<div style="border-top:1px solid #1f2937;margin:20px 0;"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:10px;">'
        "🧠 短期记忆系统（P0-P3 优先级 + LRU 清理）</div>",
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns([2, 3])
    with col1:
        mem_text = st.text_input("记忆内容", value="发现3号储罐可燃气体浓度异常", key="mem_text")
        mem_priority = st.selectbox("优先级", ["P0", "P1", "P2", "P3"], index=2, key="mem_prio")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("➕ 添加记忆", type="primary", use_container_width=True):
                st.session_state.short_term_memories.append({
                    "text": mem_text,
                    "priority": mem_priority,
                    "time": time.strftime("%H:%M:%S"),
                })
                st.success(f"已添加 {mem_priority} 记忆")
        with c2:
            if st.button("🧹 触发清理", use_container_width=True):
                before = len(st.session_state.short_term_memories)
                kept = []
                p2_count = len([x for x in st.session_state.short_term_memories if x["priority"] == "P2"])
                for m in st.session_state.short_term_memories:
                    if m["priority"] == "P3":
                        continue
                    if m["priority"] == "P2" and p2_count > 1:
                        p2_count -= 1
                        continue
                    kept.append(m)
                removed = before - len(kept)
                st.session_state.short_term_memories = kept
                st.info(f"清理完成：移除 {removed} 条，剩余 {len(kept)} 条")

    with col2:
        memories = st.session_state.get("short_term_memories", [])
        if memories:
            prio_colors = {"P0": "#ef4444", "P1": "#f97316", "P2": "#3b82f6", "P3": "#10b981"}
            for m in memories:
                color = prio_colors.get(m["priority"], "#6b7280")
                st.markdown(
                    f'<div class="memory-card" style="border-color:{color};">'
                    f'<span style="color:{color};font-weight:700;font-size:11px;">{m["priority"]}</span> '
                    f'<span style="color:#e5e7eb;font-size:13px;">{m["text"]}</span> '
                    f'<span style="color:#374151;font-size:11px;font-family:JetBrains Mono,monospace;">{m["time"]}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div style="color:#374151;font-size:13px;padding:20px;text-align:center;">暂无记忆，请在左侧添加</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="border-top:1px solid #1f2937;margin:20px 0;"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:10px;">'
        "🔍 长期记忆召回（RAG: SelfQuery + BGE-Reranker 精排）</div>",
        unsafe_allow_html=True,
    )
    query = st.text_input("查询词", value="瓦斯泄漏", key="ltm_query")
    if st.button("🔎 召回记忆", type="primary"):
        demo_results = [
            {"text": "《工矿风险预警智能体合规执行书》第3.2条：瓦斯浓度超过1.0%时必须立即撤人断电", "source": "合规执行书.md", "rerank_score": 0.94},
            {"text": "类似事故案例：2023年某煤矿瓦斯超限未撤人导致3人死亡，涉事企业被吊销安全生产许可证", "source": "类似事故处理案例.md", "rerank_score": 0.91},
            {"text": "处置经验归档：瓦斯泄漏应急响应SOP——切断电源→撤人→通风→检测→复电", "source": "处置经验归档.md", "rerank_score": 0.88},
            {"text": "工业物理常识：甲烷爆炸极限5%-15%，一氧化碳浓度超过0.0024%即对人体有害", "source": "工业物理常识.md", "rerank_score": 0.85},
        ]
        filtered = [r for r in demo_results if query in r["text"] or any(kw in r["text"] for kw in query.split())] if query else demo_results
        if not filtered:
            filtered = demo_results[:2]
        st.session_state.long_term_results = filtered

    results = st.session_state.get("long_term_results", [])
    if results:
        for r in results:
            score_color = "#10b981" if r["rerank_score"] >= 0.9 else "#3b82f6" if r["rerank_score"] >= 0.85 else "#9ca3af"
            st.markdown(
                '<div class="advice-card" style="border-left:3px solid #3b82f6;">'
                f'<div style="font-size:13px;color:#e5e7eb;">{r["text"]}</div>'
                '<div style="font-size:11px;color:#6b7280;margin-top:6px;font-family:JetBrains Mono,monospace;">'
                f'📄 {r["source"]} | RERANK: <span style="color:{score_color};font-weight:700;">{r["rerank_score"]:.2f}</span>'
                "</div></div>",
                unsafe_allow_html=True,
            )


# =============================================================================
# 标签页3：模型迭代与 CI/CD
# =============================================================================

def tab_iteration() -> None:
    st.markdown(
        '<div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:16px;">'
        "🔄 模型迭代与 CI/CD — 监控触发 → 训练 → 回归测试 → 两级终审 → 灰度发布</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:10px;">'
        "📜 模型版本时间线</div>",
        unsafe_allow_html=True,
    )
    timeline_data = [
        {"版本": "v1.0.0", "日期": "2024-01-15", "状态": "✅ 生产", "F1": "0.842", "样本": "12,000"},
        {"版本": "v1.1.0", "日期": "2024-03-20", "状态": "✅ 生产", "F1": "0.861", "样本": "18,500"},
        {"版本": "v2.0.0", "日期": "2024-06-10", "状态": "🔄 灰度发布中", "F1": "0.878", "样本": "25,000"},
    ]
    st.dataframe(pd.DataFrame(timeline_data), use_container_width=True, hide_index=True)

    st.markdown('<div style="border-top:1px solid #1f2937;margin:20px 0;"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:10px;">'
        "📊 迭代状态仪表盘</div>",
        unsafe_allow_html=True,
    )
    status = api_iteration_status()
    if not status:
        status = {
            "current_state": "CANARY",
            "current_state_cn": "灰度发布中",
            "monitor_summary": {"total_samples": 25000, "recent_f1": 0.878},
            "pending_approvals": [
                {"record_id": "approval_v2_001", "model_version": "v2.0.0", "status": "SECURITY_APPROVED"}
            ],
        }

    col1, col2, col3, col4 = st.columns(4)
    total_samples = status.get("monitor_summary", {}).get("total_samples")
    total_samples_str = f"{total_samples:,}" if isinstance(total_samples, (int, float)) else "N/A"
    recent_f1 = status.get("monitor_summary", {}).get("recent_f1")
    recent_f1_str = f"{recent_f1:.3f}" if isinstance(recent_f1, (int, float)) else "N/A"
    metrics = [
        (col1, "当前状态", status.get("current_state_cn", "未知")),
        (col2, "累计样本", total_samples_str),
        (col3, "F1 分数", recent_f1_str),
        (col4, "待审批", len(status.get("pending_approvals", []))),
    ]
    for col, title, value in metrics:
        with col:
            st.markdown(
                f'<div class="scada-card">'
                f'<div class="scada-card-title">{title}</div>'
                f'<div class="scada-card-value glow-white">{value}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">📝 审批流程</div>', unsafe_allow_html=True)
    pending = status.get("pending_approvals", [])
    c1, c2 = st.columns(2)
    with c1:
        sec_ok = any(p.get("status") in ("SECURITY_APPROVED", "TECH_APPROVED", "STAGING", "CANARY", "PRODUCTION") for p in pending)
        color = "#10b981" if sec_ok else "#ef4444"
        bg = "rgba(16,185,129,0.08)" if sec_ok else "rgba(239,68,68,0.08)"
        border = f"1px solid {color}44"
        text = "✅ 安全负责人已审批" if sec_ok else "⏳ 安全负责人待审批"
        st.markdown(
            f'<div style="padding:14px;border-radius:8px;background:{bg};border:{border};font-size:13px;font-weight:600;color:{color};">{text}</div>',
            unsafe_allow_html=True,
        )
    with c2:
        tech_ok = any(p.get("status") in ("TECH_APPROVED", "STAGING", "CANARY", "PRODUCTION") for p in pending)
        color = "#10b981" if tech_ok else "#ef4444"
        bg = "rgba(16,185,129,0.08)" if tech_ok else "rgba(239,68,68,0.08)"
        border = f"1px solid {color}44"
        text = "✅ 技术负责人已审批" if tech_ok else "⏳ 技术负责人待审批"
        st.markdown(
            f'<div style="padding:14px;border-radius:8px;background:{bg};border:{border};font-size:13px;font-weight:600;color:{color};">{text}</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">🚀 灰度流量比例</div>', unsafe_allow_html=True)
    canary_ratio = 0.5 if status.get("current_state") == "CANARY" else 1.0 if status.get("current_state") == "PRODUCTION" else 0.0
    st.markdown(
        '<div class="scada-progress-track">'
        f'<div class="scada-progress-fill" style="width:{canary_ratio*100}%;background:linear-gradient(90deg,#3b82f6,#06b6d4);"></div>'
        "</div>"
        f'<div style="font-size:12px;color:#9ca3af;margin-top:6px;font-family:JetBrains Mono,monospace;">当前灰度比例: {canary_ratio:.0%}</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div style="border-top:1px solid #1f2937;margin:20px 0;"></div>', unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:10px;">'
        "▶️ 触发模拟迭代</div>",
        unsafe_allow_html=True,
    )
    if st.button("🚀 触发模拟迭代流水线", type="primary", use_container_width=True):
        st.session_state.iteration_anim = True
        st.session_state.iteration_progress = 0

    if st.session_state.get("iteration_anim"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        stages = [
            ("监控触发检查...", 0.1),
            ("数据清洗与特征工程...", 0.25),
            ("Stacking 模型训练（7基学习器+元学习器）...", 0.45),
            ("5折时序交叉验证...", 0.60),
            ("回归测试与 Drift 分析...", 0.75),
            ("两级终审流程...", 0.85),
            ("灰度发布 0.1 → 0.5 → 1.0...", 0.95),
            ("✅ 迭代完成，模型已上线", 1.0),
        ]
        for stage_name, pct in stages:
            status_text.markdown(
                f'<div style="font-family:JetBrains Mono,monospace;font-size:13px;color:#3b82f6;">{stage_name}</div>',
                unsafe_allow_html=True,
            )
            progress_bar.progress(pct)
            time.sleep(0.4)
        st.success("模拟迭代流水线执行完成！")
        st.session_state.iteration_anim = False

        real_result = api_iteration_trigger()
        if real_result:
            st.info(f"后端返回: {real_result.get('message', '')}")


# =============================================================================
# 标签页4：系统配置与 API 文档
# =============================================================================

def tab_system_config() -> None:
    st.markdown(
        '<div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;margin-bottom:16px;">'
        "⚙️ 系统配置与 API 文档</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">🤖 GLM-5 大模型配置</div>', unsafe_allow_html=True)
    glm5_status = st.session_state.get("glm5_status")
    if glm5_status == "connected":
        st.markdown(
            '<div style="padding:12px;border-radius:8px;background:rgba(16,185,129,0.08);border:1px solid #10b98144;color:#10b981;font-weight:600;font-size:13px;">'
            "✅ GLM-5 API 已连通</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="padding:12px;border-radius:8px;background:rgba(239,68,68,0.08);border:1px solid #ef444444;color:#ef4444;font-weight:600;font-size:13px;">'
            "❌ GLM-5 API 未连通（当前使用 Mock 降级演示）</div>",
            unsafe_allow_html=True,
        )
        st.info("Mock 降级确保路演不中断，所有决策建议按场景化规则生成")

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">🎛️ 当前场景配置参数</div>', unsafe_allow_html=True)
    scenario_cfg = {
        "chemical": {
            "场景名称": "危险化学品",
            "置信度阈值": 0.90,
            "风险阈值": 2.2,
            "校验严格度": "strict",
            "记忆召回 top_k": 5,
        },
        "metallurgy": {
            "场景名称": "冶金",
            "置信度阈值": 0.85,
            "风险阈值": 2.5,
            "校验严格度": "standard",
            "记忆召回 top_k": 5,
        },
        "dust": {
            "场景名称": "粉尘涉爆",
            "置信度阈值": 0.85,
            "风险阈值": 2.5,
            "校验严格度": "standard",
            "记忆召回 top_k": 5,
        },
    }
    cfg = scenario_cfg.get(st.session_state.current_scenario, scenario_cfg["chemical"])
    _render_json_editor_style(cfg)

    st.markdown('<div style="border-top:1px solid #1f2937;margin:20px 0;"></div>', unsafe_allow_html=True)

    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">📖 API 文档</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:#9ca3af;">'
        '<div>• <a href="http://localhost:8000/docs" target="_blank" style="color:#3b82f6;text-decoration:none;">Swagger UI (本地)</a></div>'
        '<div>• <a href="http://localhost:8000/redoc" target="_blank" style="color:#3b82f6;text-decoration:none;">Redoc (本地)</a></div>'
        '<div>• 健康检查: <span style="font-family:JetBrains Mono,monospace;color:#e5e7eb;">GET http://localhost:8000/health</span></div>'
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">🔌 核心接口速查</div>', unsafe_allow_html=True)
    api_table = [
        {"接口": "POST /api/v1/agent/decision", "说明": "触发完整决策工作流", "状态": "✅"},
        {"接口": "POST /api/v1/agent/decision/stream", "说明": "SSE 流式节点状态", "状态": "✅"},
        {"接口": "POST /api/v1/agent/scenario/{id}", "说明": "切换场景配置", "状态": "✅"},
        {"接口": "GET /api/v1/knowledge/list", "说明": "知识库文件列表", "状态": "✅"},
        {"接口": "GET /api/v1/iteration/status", "说明": "迭代状态查询", "状态": "✅"},
        {"接口": "POST /api/v1/iteration/trigger", "说明": "触发迭代流水线", "状态": "✅"},
    ]
    st.dataframe(pd.DataFrame(api_table), use_container_width=True, hide_index=True)

    st.markdown('<div style="border-top:1px solid #1f2937;margin:20px 0;"></div>', unsafe_allow_html=True)

    st.markdown('<div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:8px;">ℹ️ 系统信息</div>', unsafe_allow_html=True)
    health = api_health()
    sys_info = {
        "backend_status": health.get("status", "unknown"),
        "version": health.get("version", "unknown"),
        "api_base": API_BASE,
        "frontend": "Streamlit 1.30+ (SCADA Theme)",
        "recommended_resolution": "1920×1080",
        "theme": "Industrial Control Room Dark",
    }
    _render_json_editor_style(sys_info)


# =============================================================================
# 主入口
# =============================================================================

def main() -> None:
    # 系统状态栏
    _render_system_status_bar()

    # 演示模式轮播高亮（通过 JS 注入）
    if st.session_state.get("demo_mode"):
        st.markdown(
            """
            <script>
            (function() {
                const cards = document.querySelectorAll('.scada-card, .advice-card, .validation-card, .timeline-node');
                let idx = 0;
                function highlight() {
                    cards.forEach(c => c.classList.remove('demo-highlight'));
                    if (cards.length > 0) {
                        cards[idx % cards.length].classList.add('demo-highlight');
                        idx++;
                    }
                }
                highlight();
                setInterval(highlight, 3000);
            })();
            </script>
            """,
            unsafe_allow_html=True,
        )

    # 侧边栏
    sidebar()

    tabs = st.tabs([
        "🎯 企业风险预测",
        "📚 知识库与记忆系统",
        "🔄 模型迭代与CI/CD",
        "⚙️ 系统配置与API文档",
    ])

    with tabs[0]:
        tab_risk_prediction()
    with tabs[1]:
        tab_knowledge_memory()
    with tabs[2]:
        tab_iteration()
    with tabs[3]:
        tab_system_config()


if __name__ == "__main__":
    main()
