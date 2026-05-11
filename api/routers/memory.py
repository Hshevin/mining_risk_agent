"""
记忆系统统计与导出接口。
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from harness.agentfs import AgentFS
from harness.memory import ShortTermMemory
from harness.memory_statistics import (
    MemoryStatsFilters,
    build_export_rows,
    build_statistics_payload,
    parse_time,
)

router = APIRouter()

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 20


def _get_agentfs() -> AgentFS:
    return AgentFS()


def _get_runtime_short_term() -> Optional[ShortTermMemory]:
    """
    读取当前进程中已经存在的短期记忆对象。

    不主动创建 HybridMemoryManager，避免一次只读统计请求产生额外 AgentFS 初始化
    或长期记忆文件初始化写入。
    """
    for module_name in ("api.routers.prediction", "agent.workflow"):
        module = sys.modules.get(module_name)
        manager = getattr(module, "_memory", None) if module else None
        short_term = getattr(manager, "short_term", None)
        if short_term is not None:
            return short_term
    return None


def _filters(
    module: str,
    priority: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    keyword: Optional[str],
    path: Optional[str],
    risk_level: Optional[str],
    risk_type: Optional[str],
    limit: int,
    offset: int,
) -> MemoryStatsFilters:
    normalized_module = module if module in {"short_term", "long_term", "warning_experience", "all"} else "all"
    normalized_priority = priority if priority in {"P0", "P1", "P2", "P3"} else None
    return MemoryStatsFilters(
        module=normalized_module,
        priority=normalized_priority,
        start_time=parse_time(start_time),
        end_time=parse_time(end_time),
        keyword=keyword.strip() if keyword else None,
        path=path.strip() if path else None,
        risk_level=risk_level.strip() if risk_level else None,
        risk_type=risk_type.strip() if risk_type else None,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


def _cache_key(filters: MemoryStatsFilters) -> str:
    return "|".join(
        [
            filters.module,
            filters.priority or "",
            str(filters.start_time or ""),
            str(filters.end_time or ""),
            filters.keyword or "",
            filters.path or "",
            filters.risk_level or "",
            filters.risk_type or "",
            str(filters.limit),
            str(filters.offset),
        ]
    )


@router.get("/statistics")
async def get_memory_statistics(
    module: str = Query("all", description="short_term / long_term / warning_experience / all"),
    priority: Optional[str] = Query(None, description="P0/P1/P2/P3"),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    path: Optional[str] = Query(None, description="AgentFS 记忆文件路径或知识库类型"),
    risk_level: Optional[str] = Query(None),
    risk_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    refresh: bool = Query(False, description="跳过短时缓存，重新统计"),
) -> Dict[str, Any]:
    filters = _filters(
        module,
        priority,
        start_time,
        end_time,
        keyword,
        path,
        risk_level,
        risk_type,
        limit,
        offset,
    )
    short_term = _get_runtime_short_term()
    key = _cache_key(filters)
    now = datetime.now().timestamp()
    cached = _CACHE.get(key)
    if not refresh and short_term is None and cached and now - cached["timestamp"] <= _CACHE_TTL_SECONDS:
        payload = cached["payload"]
        payload["cache"] = {"hit": True, "ttl_seconds": _CACHE_TTL_SECONDS}
        return payload

    payload = build_statistics_payload(
        filters=filters,
        agentfs=_get_agentfs(),
        short_term=short_term,
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _CACHE_TTL_SECONDS}
    if short_term is None:
        _CACHE[key] = {"timestamp": now, "payload": payload}
    return payload


def _export_filename(module: str, start_time: Optional[str], end_time: Optional[str], ext: str) -> str:
    start = (start_time or "all").replace(":", "").replace("/", "-")
    end = (end_time or "all").replace(":", "").replace("/", "-")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"memory_{module}_{start}_{end}_{stamp}.{ext}"


def _stream_bytes(data: bytes, filename: str, media_type: str) -> StreamingResponse:
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(io.BytesIO(data), media_type=media_type, headers=headers)


def _rows_to_pdf(rows: list[dict[str, Any]]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
    except Exception:
        return _rows_to_minimal_pdf(rows)

    buffer = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "STSong-Light"
    normal.fontSize = 8
    title_style = styles["Title"]
    title_style.fontName = "STSong-Light"

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    table_rows = [["模块", "优先级", "来源/路径", "更新时间", "风险类型", "关联度", "摘要"]]
    for row in rows[:500]:
        table_rows.append([
            row.get("module", ""),
            row.get("priority", ""),
            Paragraph(f"{row.get('source', '')}<br/>{row.get('path', '')}", normal),
            row.get("updated_at", ""),
            row.get("risk_type", ""),
            row.get("association_score", ""),
            Paragraph(str(row.get("summary") or row.get("content") or "")[:260], normal),
        ])

    table = Table(table_rows, colWidths=[22 * mm, 18 * mm, 48 * mm, 34 * mm, 28 * mm, 20 * mm, 105 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#94a3b8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    doc.build([Paragraph("记忆系统导出", title_style), table])
    return buffer.getvalue()


def _pdf_hex(text: str) -> str:
    safe = (text or "").replace("\r", " ").replace("\n", " ")
    return safe.encode("utf-16-be", errors="replace").hex().upper()


def _minimal_pdf_line(text: str, width: int = 86) -> list[str]:
    compact = " ".join(str(text or "").split())
    if len(compact) <= width:
        return [compact]
    return [compact[index: index + width] for index in range(0, len(compact), width)]


def _rows_to_minimal_pdf(rows: list[dict[str, Any]]) -> bytes:
    """无第三方依赖的中文 CID 字体 PDF fallback。"""
    page_width, page_height = 842, 595
    commands = ["BT", "/F1 14 Tf", f"40 {page_height - 42} Td", f"<{_pdf_hex('记忆系统导出')}> Tj"]
    commands.extend(["/F1 8 Tf", "0 -20 Td"])
    line_count = 0
    for row in rows[:120]:
        text = (
            f"{row.get('module', '')} | {row.get('priority', '')} | "
            f"{row.get('risk_type', '')} | {row.get('updated_at', '')} | "
            f"{row.get('path', '')} | {row.get('summary') or row.get('content') or ''}"
        )
        for line in _minimal_pdf_line(text):
            if line_count >= 38:
                break
            commands.append(f"<{_pdf_hex(line[:120])}> Tj")
            commands.append("0 -13 Td")
            line_count += 1
        if line_count >= 38:
            break
    if len(rows) > 120 or line_count >= 38:
        commands.append(f"<{_pdf_hex('（内容较多，仅展示前若干行；完整数据请导出 CSV 或 Excel。）')}> Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>"
        ).encode("ascii"),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [5 0 R] >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    chunks = [b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n"]
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


@router.get("/export")
async def export_memory_data(
    export_format: str = Query("csv", alias="format", description="csv/xlsx/pdf"),
    module: str = Query("all", description="short_term / long_term / warning_experience / all"),
    priority: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    path: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    risk_type: Optional[str] = Query(None),
) -> StreamingResponse:
    fmt = export_format.lower().strip()
    if fmt not in {"csv", "xlsx", "pdf"}:
        raise HTTPException(status_code=400, detail="format 仅支持 csv/xlsx/pdf")

    filters = _filters(
        module,
        priority,
        start_time,
        end_time,
        keyword,
        path,
        risk_level,
        risk_type,
        limit=100000,
        offset=0,
    )
    rows = build_export_rows(
        filters=filters,
        agentfs=_get_agentfs(),
        short_term=_get_runtime_short_term(),
    )
    df = pd.DataFrame(rows)

    if fmt == "csv":
        data = df.to_csv(index=False).encode("utf-8-sig")
        filename = _export_filename(filters.module, start_time, end_time, "csv")
        return _stream_bytes(data, filename, "text/csv; charset=utf-8")

    if fmt == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="memory_export", index=False)
        filename = _export_filename(filters.module, start_time, end_time, "xlsx")
        return _stream_bytes(
            buffer.getvalue(),
            filename,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    data = _rows_to_pdf(rows)
    filename = _export_filename(filters.module, start_time, end_time, "pdf")
    return _stream_bytes(data, filename, "application/pdf")
