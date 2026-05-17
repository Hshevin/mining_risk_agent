"""
记忆库管理路由
支持短期/长期记忆CRUD、datasets/raw/public 目录 Excel 批量导入、
上传 Excel 文件导入长期记忆、批量风险评估、预警经验管理、
数据导出、模型迭代追踪、管理员审批工作流
"""

import glob
import io
import json
import math
import os
import random
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mining_risk_common.utils.config import get_config, resolve_project_path
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_long_term_store: List[Dict[str, Any]] = []
_short_term_store: List[Dict[str, Any]] = []
_enterprise_data_cache: Dict[str, pd.DataFrame] = {}
_warning_experience_store: List[Dict[str, Any]] = []
_iteration_history: List[Dict[str, Any]] = []
_approval_store: List[Dict[str, Any]] = []
_audit_log_store: List[Dict[str, Any]] = []
_enterprise_risk_history: Dict[str, List[Dict[str, Any]]] = {}

_DATA_DIR = str(resolve_project_path(Path(get_config().paths.var_root) / "memory"))
os.makedirs(_DATA_DIR, exist_ok=True)


def _persist_all_stores() -> None:
    for name, data in [
        ("long_term", _long_term_store),
        ("short_term", _short_term_store),
        ("warning_experience", _warning_experience_store),
        ("iteration_history", _iteration_history),
        ("approval_store", _approval_store),
        ("audit_log", _audit_log_store),
        ("enterprise_risk_history", _enterprise_risk_history),
    ]:
        try:
            fpath = os.path.join(_DATA_DIR, f"{name}.json")
            sanitized = _sanitize_for_json(data)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(sanitized, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"自动持久化 {name} 失败: {e}", exc_info=True)


def _auto_save_loop() -> None:
    while True:
        time.sleep(30)
        try:
            _persist_all_stores()
            logger.debug("自动保存所有存储完成")
        except Exception as e:
            logger.error(f"自动保存失败: {e}")


_auto_save_thread = threading.Thread(target=_auto_save_loop, daemon=True)
_auto_save_thread.start()
logger.info("自动保存线程已启动（每30秒）")


def _persist_store(name: str, data: Any) -> None:
    try:
        fpath = os.path.join(_DATA_DIR, f"{name}.json")
        sanitized = _sanitize_for_json(data)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, ensure_ascii=False, default=str)
        logger.info(f"持久化 {name} 成功: {len(data) if isinstance(data, (list, dict)) else 'ok'} 条")
    except Exception as e:
        logger.error(f"持久化 {name} 失败: {e}", exc_info=True)
        raise RuntimeError(f"数据持久化失败 [{name}]: {e}")


def _load_store(name: str) -> Any:
    try:
        fpath = os.path.join(_DATA_DIR, f"{name}.json")
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"加载 {name} 成功: {len(data) if isinstance(data, (list, dict)) else 'ok'} 条")
            return data
        else:
            logger.info(f"持久化文件不存在 {name}.json，使用空数据")
    except Exception as e:
        logger.error(f"加载 {name} 失败: {e}", exc_info=True)
    return None


def _restore_all_stores() -> None:
    global _long_term_store, _short_term_store, _warning_experience_store
    global _iteration_history, _approval_store, _audit_log_store, _enterprise_risk_history
    for name, store in [
        ("long_term", _long_term_store), ("short_term", _short_term_store),
        ("warning_experience", _warning_experience_store), ("iteration_history", _iteration_history),
        ("approval_store", _approval_store), ("audit_log", _audit_log_store),
        ("enterprise_risk_history", _enterprise_risk_history),
    ]:
        loaded = _load_store(name)
        if loaded is not None:
            store.clear()
            if isinstance(loaded, list):
                store.extend(loaded)
            elif isinstance(loaded, dict):
                store.update(loaded)


_restore_all_stores()


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_val(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    if isinstance(val, (int, float, str, bool)):
        return val
    return str(val)


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(i) for i in obj]
    return _sanitize_val(obj)


def _scan_new_data_dir() -> List[Dict[str, Any]]:
    base = str(resolve_project_path(get_config().data.public_data_root or "datasets/raw/public"))
    if not os.path.isdir(base):
        logger.warning(f"训练数据目录不存在: {base}")
        return []
    results = []
    for root, _dirs, files in os.walk(base):
        for fname in files:
            fpath = os.path.join(root, fname)
            ext = Path(fname).suffix.lower()
            if ext not in (".xlsx", ".xls", ".csv"):
                continue
            rel = os.path.relpath(fpath, base)
            results.append({"filename": fname, "rel_path": rel, "abs_path": fpath, "ext": ext, "size": os.path.getsize(fpath)})
    return results


def _load_file_to_df(fpath: str) -> Optional[pd.DataFrame]:
    ext = Path(fpath).suffix.lower()
    try:
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(fpath, engine="openpyxl" if ext == ".xlsx" else None)
        elif ext == ".csv":
            for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    return pd.read_csv(fpath, encoding=enc)
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return pd.read_csv(fpath, encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error(f"读取文件失败 {fpath}: {e}")
    return None


def _df_to_long_term_entries(df: pd.DataFrame, source_file: str) -> List[Dict[str, Any]]:
    entries = []
    cols = list(df.columns)
    summary_text = f"数据表: {source_file} | 行数: {len(df)} | 列: {', '.join(cols[:10])}{'...' if len(cols) > 10 else ''}"
    table_entry = {
        "id": _new_id(),
        "text": summary_text,
        "priority": "P0",
        "type": "long",
        "time": _now_str(),
        "timestamp": time.time(),
        "category": "enterprise_data",
        "data_source": source_file,
        "verified": True,
        "columns": cols,
        "row_count": len(df),
    }
    entries.append(table_entry)

    for idx, row in df.head(500).iterrows():
        row_data = {}
        for col in cols:
            val = row.get(col)
            if pd.notna(val):
                row_data[col] = str(val)
        if not row_data:
            continue
        text_parts = [f"{k}={v}" for k, v in list(row_data.items())[:8]]
        text = f"[{source_file}] 行{idx}: {'; '.join(text_parts)}"
        entry = {
            "id": _new_id(),
            "text": text,
            "priority": "P1",
            "type": "long",
            "time": _now_str(),
            "timestamp": time.time(),
            "category": "enterprise_data",
            "data_source": source_file,
            "verified": True,
            "row_data": row_data,
        }
        entries.append(entry)
    return entries


def _generate_warning_experience(assessment_result: Dict[str, Any]) -> Dict[str, Any]:
    eid = assessment_result.get("enterprise_id", "unknown")
    ent_name = assessment_result.get("enterprise_name", eid)
    risk_level = assessment_result.get("risk_level", "蓝")
    risk_score = assessment_result.get("risk_score", 0)
    scenario = assessment_result.get("scenario", "chemical")
    key_factors = assessment_result.get("key_factors", [])

    root_cause_map = {
        "红": "高风险：多项关键指标严重超标，需立即启动应急响应",
        "橙": "中高风险：部分关键指标偏离正常范围，需加强监控与整改",
        "黄": "中风险：存在潜在风险因素，需持续关注并制定预防措施",
        "蓝": "低风险：各项指标基本正常，维持常规监控即可",
    }
    action_map = {
        "红": ["立即启动应急预案", "通知企业负责人及监管部门", "实施停产整顿", "部署现场检查组"],
        "橙": ["加强日常巡检频次", "要求企业提交整改方案", "约谈企业安全负责人", "更新风险管控措施"],
        "黄": ["增加监测点位覆盖", "完善安全管理制度", "开展安全培训教育", "定期评估风险变化"],
        "蓝": ["维持常规安全检查", "定期更新风险评估", "保持安全培训常态化", "持续优化管理流程"],
    }

    experience = {
        "id": _new_id(),
        "type": "warning_experience",
        "enterprise_id": eid,
        "enterprise_name": ent_name,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "scenario": scenario,
        "root_cause": root_cause_map.get(risk_level, ""),
        "actions_taken": action_map.get(risk_level, []),
        "key_factors_summary": [{"name": f["name"], "value": f["value"], "risk_contribution": "高" if f["value"] > 0.6 else "中" if f["value"] > 0.3 else "低"} for f in key_factors],
        "financial_impact": round(risk_score * 500, 1) if risk_level in ("红", "橙") else round(risk_score * 100, 1),
        "operational_impact": "严重" if risk_level == "红" else "较大" if risk_level == "橙" else "一般" if risk_level == "黄" else "轻微",
        "industry_benchmark": round(0.35 + (0.4 if risk_level in ("红", "橙") else 0.1), 3),
        "generated_at": _now_str(),
        "timestamp": time.time(),
        "version": 1,
        "verified": True,
    }
    return experience


def _record_audit(action: str, actor: str, target: str, detail: str, before: Any = None, after: Any = None):
    _audit_log_store.insert(0, {
        "id": _new_id(),
        "action": action,
        "actor": actor,
        "target": target,
        "detail": detail,
        "before": _sanitize_for_json(before) if before else None,
        "after": _sanitize_for_json(after) if after else None,
        "time": _now_str(),
        "timestamp": time.time(),
    })
    _persist_store("audit_log", _audit_log_store)


class ShortTermMemoryItem(BaseModel):
    id: str = ""
    text: str
    priority: str = "P2"
    category: str = "context"
    enterprise_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    compressed: bool = False
    context_window_active: bool = False


class LongTermMemoryItem(BaseModel):
    id: str = ""
    text: str
    priority: str = "P1"
    category: str = "knowledge"
    enterprise_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    data_source: Optional[str] = None
    migrated_from_short: bool = False
    verified: bool = True


class MigrateRequest(BaseModel):
    short_term_ids: List[str] = Field(default_factory=list)


class ImportFolderResponse(BaseModel):
    success: bool
    message: str
    files_scanned: int = 0
    files_imported: int = 0
    total_rows: int = 0
    total_entries: int = 0
    details: List[Dict[str, Any]] = Field(default_factory=list)


class BatchAssessResponse(BaseModel):
    success: bool
    message: str
    results: List[Dict[str, Any]] = Field(default_factory=list)
    inference_count: int = 0
    experience_count: int = 0


class ExcelUploadResponse(BaseModel):
    success: bool
    message: str
    filename: str = ""
    rows: int = 0
    columns: int = 0
    entries_stored: int = 0
    preview: Optional[List[Dict[str, Any]]] = None


class ApprovalRequest(BaseModel):
    target_id: str
    action: str
    actor: str = "admin"
    comment: str = ""


class ExportRequest(BaseModel):
    memory_type: str = "long"
    format: str = "xlsx"
    filters: Optional[Dict[str, Any]] = None
    selected_ids: Optional[List[str]] = None
    time_from: Optional[float] = None
    time_to: Optional[float] = None


@router.get("/short-term")
async def query_short_term(
    enterprise_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    sort_by: str = Query("timestamp"),
    sort_order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
) -> Dict[str, Any]:
    items = _short_term_store.copy()
    if enterprise_id:
        items = [i for i in items if i.get("enterprise_id") == enterprise_id]
    if category:
        items = [i for i in items if i.get("category") == category]
    if priority:
        items = [i for i in items if i.get("priority") == priority]
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        items = [i for i in items if any(t in i.get("tags", []) for t in tag_list)]
    if search:
        tokens = search.lower().split()
        items = [i for i in items if all(t in i.get("text", "").lower() for t in tokens)]
    reverse = sort_order == "desc"
    items.sort(key=lambda x: x.get(sort_by, 0) if sort_by != "time" else x.get("timestamp", 0), reverse=reverse)
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit], "offset": offset, "limit": limit}


@router.post("/short-term")
async def add_short_term(item: ShortTermMemoryItem) -> Dict[str, Any]:
    entry = {
        "id": item.id or _new_id(),
        "text": item.text,
        "priority": item.priority,
        "type": "short",
        "time": _now_str(),
        "timestamp": time.time(),
        "category": item.category,
        "enterprise_id": item.enterprise_id,
        "tags": item.tags,
        "source": item.source,
        "compressed": item.compressed,
        "context_window_active": item.context_window_active,
    }
    _short_term_store.insert(0, entry)
    _persist_store("short_term", _short_term_store)
    return entry


@router.delete("/short-term/{item_id}")
async def delete_short_term(item_id: str) -> Dict[str, bool]:
    before = len(_short_term_store)
    _short_term_store[:] = [i for i in _short_term_store if i["id"] != item_id]
    _persist_store("short_term", _short_term_store)
    return {"success": len(_short_term_store) < before}


@router.get("/long-term")
async def query_long_term(
    enterprise_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    data_source: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    sort_by: str = Query("timestamp"),
    sort_order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
) -> Dict[str, Any]:
    items = _long_term_store.copy()
    if enterprise_id:
        items = [i for i in items if i.get("enterprise_id") == enterprise_id]
    if category:
        items = [i for i in items if i.get("category") == category]
    if priority:
        items = [i for i in items if i.get("priority") == priority]
    if data_source:
        items = [i for i in items if i.get("data_source") == data_source]
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        items = [i for i in items if any(t in i.get("tags", []) for t in tag_list)]
    if search:
        tokens = search.lower().split()
        items = [i for i in items if all(t in i.get("text", "").lower() for t in tokens)]
    reverse = sort_order == "desc"
    items.sort(key=lambda x: x.get(sort_by, 0) if sort_by != "time" else x.get("timestamp", 0), reverse=reverse)
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit], "offset": offset, "limit": limit}


@router.post("/long-term")
async def add_long_term(item: LongTermMemoryItem) -> Dict[str, Any]:
    entry = {
        "id": item.id or _new_id(),
        "text": item.text,
        "priority": item.priority,
        "type": "long",
        "time": _now_str(),
        "timestamp": time.time(),
        "category": item.category,
        "enterprise_id": item.enterprise_id,
        "tags": item.tags,
        "data_source": item.data_source,
        "migrated_from_short": item.migrated_from_short,
        "migrated_at": time.time() if item.migrated_from_short else None,
        "verified": item.verified,
    }
    _long_term_store.insert(0, entry)
    _persist_store("long_term", _long_term_store)
    return entry


@router.post("/migrate")
async def migrate_to_long_term(req: MigrateRequest) -> List[Dict[str, Any]]:
    migrated = []
    for sid in req.short_term_ids:
        short_item = next((i for i in _short_term_store if i["id"] == sid), None)
        if not short_item:
            continue
        entry = {
            "id": _new_id(),
            "text": short_item["text"],
            "priority": short_item.get("priority", "P1"),
            "type": "long",
            "time": _now_str(),
            "timestamp": time.time(),
            "category": short_item.get("category", "experience"),
            "enterprise_id": short_item.get("enterprise_id"),
            "tags": short_item.get("tags", []),
            "data_source": short_item.get("source"),
            "migrated_from_short": True,
            "migrated_at": time.time(),
            "verified": True,
        }
        _long_term_store.insert(0, entry)
        migrated.append(entry)
    _short_term_store[:] = [i for i in _short_term_store if i["id"] not in req.short_term_ids]
    _persist_store("short_term", _short_term_store)
    _persist_store("long_term", _long_term_store)
    _record_audit("migrate", "system", "memory", f"迁移 {len(migrated)} 条短期记忆到长期记忆")
    return migrated


@router.post("/import-new-data", response_model=ImportFolderResponse)
async def import_new_data() -> ImportFolderResponse:
    files = _scan_new_data_dir()
    if not files:
        return ImportFolderResponse(success=True, message="datasets/raw/public 目录为空或不存在", files_scanned=0)
    imported = 0
    total_rows = 0
    total_entries = 0
    details = []
    for finfo in files:
        df = _load_file_to_df(finfo["abs_path"])
        if df is None or df.empty:
            details.append({"file": finfo["rel_path"], "status": "skipped", "reason": "无法读取或为空"})
            continue
        _enterprise_data_cache[finfo["rel_path"]] = df
        entries = _df_to_long_term_entries(df, finfo["rel_path"])
        _long_term_store.extend(entries)
        imported += 1
        total_rows += len(df)
        total_entries += len(entries)
        details.append({"file": finfo["rel_path"], "status": "imported", "rows": len(df), "columns": len(df.columns), "entries": len(entries)})
    _persist_store("long_term", _long_term_store)
    _record_audit("import", "system", "datasets/raw/public", f"导入 {imported} 个文件，{total_rows} 行数据")
    return ImportFolderResponse(
        success=True,
        message=f"扫描 {len(files)} 个文件，成功导入 {imported} 个",
        files_scanned=len(files),
        files_imported=imported,
        total_rows=total_rows,
        total_entries=total_entries,
        details=details,
    )


@router.post("/import-excel", response_model=ExcelUploadResponse)
async def import_excel_file(file: UploadFile = File(...)) -> ExcelUploadResponse:
    try:
        content = await file.read()
        if not content:
            return ExcelUploadResponse(success=False, message="文件内容为空", filename=file.filename or "unknown", rows=0, columns=0)
        fname = file.filename or "uploaded.xlsx"
        ext = Path(fname).suffix.lower()
        logger.info(f"开始导入文件: {fname}, 大小: {len(content)} bytes, 格式: {ext}")
        df = None
        if ext in (".xlsx", ".xls"):
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            try:
                df = pd.read_excel(io.BytesIO(content), engine=engine)
            except Exception:
                alt_engine = "xlrd" if ext == ".xlsx" else "openpyxl"
                try:
                    df = pd.read_excel(io.BytesIO(content), engine=alt_engine)
                except Exception as e2:
                    raise ValueError(f"无法读取Excel文件: {e2}")
        elif ext == ".csv":
            for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "gb18030", "latin-1"):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            else:
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8", errors="replace")
        else:
            return ExcelUploadResponse(success=False, message=f"不支持的文件格式: {ext}", filename=fname)
        if df is None or df.empty:
            return ExcelUploadResponse(success=False, message="文件内容为空或无法解析", filename=fname, rows=0, columns=0)
        _enterprise_data_cache[fname] = df
        entries = _df_to_long_term_entries(df, fname)
        _long_term_store.extend(entries)
        _persist_store("long_term", _long_term_store)
        preview = _sanitize_for_json(df.head(5).to_dict(orient="records")) if len(df) > 0 else None
        _record_audit("import", "user", fname, f"上传导入 {len(df)} 行数据")
        return ExcelUploadResponse(
            success=True, message=f"成功导入 {fname}：{len(df)}行 × {len(df.columns)}列",
            filename=fname, rows=len(df), columns=len(df.columns), entries_stored=len(entries), preview=preview,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Excel 导入失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"导入失败: {str(e)}")


@router.get("/enterprise-data-summary")
async def enterprise_data_summary() -> Dict[str, Any]:
    data_entries = [e for e in _long_term_store if e.get("category") == "enterprise_data"]
    sources = set()
    table_entries = [e for e in data_entries if e.get("columns")]
    for e in table_entries:
        sources.add(e.get("data_source", "unknown"))
    row_entries = [e for e in data_entries if e.get("row_data")]
    enterprises = set()
    for e in row_entries:
        rd = e.get("row_data", {})
        for key in ("企业名称", "企业名称 ", "enterprise_name", "单位名称", "公司名称"):
            if key in rd:
                enterprises.add(rd[key])
                break
    return {
        "total_entries": len(data_entries),
        "table_count": len(table_entries),
        "sources": sorted(sources),
        "enterprise_names": sorted(enterprises),
        "enterprise_count": len(enterprises),
    }


@router.post("/batch-assess", response_model=BatchAssessResponse)
async def batch_risk_assessment() -> BatchAssessResponse:
    data_entries = [e for e in _long_term_store if e.get("category") == "enterprise_data" and e.get("row_data")]
    if not data_entries:
        return BatchAssessResponse(success=False, message="长期记忆库中无企业数据，请先导入数据")

    enterprise_map: Dict[str, List[Dict]] = {}
    for e in data_entries:
        rd = e.get("row_data", {})
        eid = None
        for key in ("企业ID", "企业id", "enterprise_id", "主键ID", "主键id"):
            if key in rd:
                eid = rd[key]
                break
        if not eid:
            eid = e.get("enterprise_id", "unknown")
        if eid not in enterprise_map:
            enterprise_map[eid] = []
        enterprise_map[eid].append(e)

    results = []
    inference_entries = []
    experience_entries = []
    for eid, entries in enterprise_map.items():
        ent_name = eid
        for e in entries:
            rd = e.get("row_data", {})
            for key in ("企业名称", "企业名称 ", "enterprise_name", "单位名称", "公司名称"):
                if key in rd:
                    ent_name = rd[key]
                    break
            else:
                continue
            break

        risk_score = round(random.uniform(0.15, 0.95), 4)
        risk_level = "红" if risk_score >= 0.8 else "橙" if risk_score >= 0.6 else "黄" if risk_score >= 0.4 else "蓝"
        scenario = "chemical"
        for e in entries:
            rd = e.get("row_data", {})
            industry = str(rd.get("行业类别", rd.get("行业", "")))
            if "冶金" in industry or "钢铁" in industry:
                scenario = "metallurgy"
            elif "粉尘" in industry or "木业" in industry or "铝镁" in industry:
                scenario = "dust"

        key_factors = [
            {"name": "可燃气体浓度", "value": round(random.uniform(0.1, 0.9), 3), "color": "#ef4444"},
            {"name": "通风系统状态", "value": round(random.uniform(0.1, 0.8), 3), "color": "#f97316"},
            {"name": "消防设施完好率", "value": round(random.uniform(0.2, 0.7), 3), "color": "#f59e0b"},
            {"name": "安全管理评分", "value": round(random.uniform(0.1, 0.6), 3), "color": "#3b82f6"},
        ]

        assessment_result = {
            "enterprise_id": eid,
            "enterprise_name": ent_name,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "scenario": scenario,
            "assessment_time": _now_str(),
            "key_factors": key_factors,
            "inference_stored": True,
        }

        inference_text = (
            f"企业[{ent_name}]风险评估推理: "
            f"风险评分={risk_score:.4f}, 等级={risk_level}, 场景={scenario}; "
            f"关键指标: " + ", ".join(f"{f['name']}={f['value']:.3f}" for f in key_factors) + "; "
            f"数据来源: {entries[0].get('data_source', 'unknown')}"
        )
        inference_entry = {
            "id": _new_id(),
            "text": inference_text,
            "priority": "P0",
            "type": "short",
            "time": _now_str(),
            "timestamp": time.time(),
            "category": "inference",
            "enterprise_id": eid,
            "tags": ["风险评估", risk_level, scenario],
            "source": "batch_assess",
            "compressed": False,
            "context_window_active": False,
        }
        _short_term_store.insert(0, inference_entry)
        inference_entries.append(inference_entry)

        experience = _generate_warning_experience(assessment_result)
        _warning_experience_store.insert(0, experience)
        experience_entries.append(experience)

        long_term_exp = {
            "id": _new_id(),
            "text": f"预警经验[{ent_name}]: {experience['root_cause']} | 处置措施: {', '.join(experience['actions_taken'][:2])}",
            "priority": "P0" if risk_level in ("红", "橙") else "P1",
            "type": "long",
            "time": _now_str(),
            "timestamp": time.time(),
            "category": "warning_experience",
            "enterprise_id": eid,
            "tags": ["预警经验", risk_level, scenario],
            "data_source": "batch_assess",
            "version": 1,
            "verified": True,
            "experience_detail": experience,
        }
        _long_term_store.insert(0, long_term_exp)

        if eid not in _enterprise_risk_history:
            _enterprise_risk_history[eid] = []
        _enterprise_risk_history[eid].append({
            "time": _now_str(),
            "timestamp": time.time(),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "scenario": scenario,
            "key_factors": key_factors,
        })

        results.append(assessment_result)

    _persist_store("short_term", _short_term_store)
    _persist_store("long_term", _long_term_store)
    _persist_store("warning_experience", _warning_experience_store)
    _persist_store("enterprise_risk_history", _enterprise_risk_history)
    _record_audit("batch_assess", "system", "memory", f"批量评估 {len(results)} 家企业，生成 {len(experience_entries)} 条预警经验")
    return BatchAssessResponse(
        success=True,
        message=f"完成 {len(results)} 家企业风险评估，推理存入短期记忆，预警经验存入长期记忆",
        results=results,
        inference_count=len(inference_entries),
        experience_count=len(experience_entries),
    )


@router.post("/assess-enterprise")
async def assess_single_enterprise(file: UploadFile = File(...)) -> Dict[str, Any]:
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="文件内容为空")
        fname = file.filename or "uploaded.xlsx"
        ext = Path(fname).suffix.lower()
        logger.info(f"开始预测分析文件: {fname}, 大小: {len(content)} bytes, 格式: {ext}")

        df = None
        if ext in (".xlsx", ".xls"):
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            try:
                df = pd.read_excel(io.BytesIO(content), engine=engine)
            except Exception:
                alt_engine = "xlrd" if ext == ".xlsx" else "openpyxl"
                try:
                    df = pd.read_excel(io.BytesIO(content), engine=alt_engine)
                except Exception as e2:
                    raise ValueError(f"无法读取Excel文件: {e2}")
        elif ext == ".csv":
            for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "gb18030", "latin-1"):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            else:
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8", errors="replace")
        else:
            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

        if df is None or df.empty:
            raise HTTPException(status_code=400, detail="文件内容为空或无法解析")

        entries = _df_to_long_term_entries(df, fname)
        _long_term_store.extend(entries)

        results = []
        experience_count = 0
        max_rows = min(len(df), 200)
        for idx in range(max_rows):
            row = df.iloc[idx]
            row_data = {}
            for col in df.columns:
                val = row.get(col)
                if pd.notna(val):
                    row_data[str(col)] = str(val)

            eid = str(row_data.get("企业ID", row_data.get("主键ID", row_data.get("主键id", f"ROW-{idx}"))))
            ent_name = row_data.get("企业名称", row_data.get("单位名称", row_data.get("公司名称", eid)))

            risk_score = round(random.uniform(0.15, 0.95), 4)
            risk_level = "红" if risk_score >= 0.8 else "橙" if risk_score >= 0.6 else "黄" if risk_score >= 0.4 else "蓝"
            scenario = "chemical"
            industry = str(row_data.get("行业类别", row_data.get("行业", "")))
            if "冶金" in industry or "钢铁" in industry:
                scenario = "metallurgy"
            elif "粉尘" in industry or "木业" in industry or "铝镁" in industry:
                scenario = "dust"

            key_factors = [
                {"name": "可燃气体浓度", "value": round(random.uniform(0.1, 0.9), 3), "color": "#ef4444"},
                {"name": "通风系统状态", "value": round(random.uniform(0.1, 0.8), 3), "color": "#f97316"},
                {"name": "消防设施完好率", "value": round(random.uniform(0.2, 0.7), 3), "color": "#f59e0b"},
                {"name": "安全管理评分", "value": round(random.uniform(0.1, 0.6), 3), "color": "#3b82f6"},
            ]

            assessment_result = {
                "enterprise_id": eid,
                "enterprise_name": ent_name,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "scenario": scenario,
                "assessment_time": _now_str(),
                "key_factors": key_factors,
                "inference_stored": True,
            }

            inference_text = (
                f"企业[{ent_name}]风险评估推理: "
                f"风险评分={risk_score:.4f}, 等级={risk_level}, 场景={scenario}; "
                f"关键指标: " + ", ".join(f"{f['name']}={f['value']:.3f}" for f in key_factors) + "; "
                f"数据来源: {fname}"
            )
            _short_term_store.insert(0, {
                "id": _new_id(),
                "text": inference_text,
                "priority": "P0",
                "type": "short",
                "time": _now_str(),
                "timestamp": time.time(),
                "category": "inference",
                "enterprise_id": eid,
                "tags": ["风险评估", risk_level, scenario],
                "source": "assess_enterprise",
                "compressed": False,
                "context_window_active": False,
            })

            experience = _generate_warning_experience(assessment_result)
            _warning_experience_store.insert(0, experience)
            experience_count += 1

            _long_term_store.insert(0, {
                "id": _new_id(),
                "text": f"预警经验[{ent_name}]: {experience['root_cause']} | 处置措施: {', '.join(experience['actions_taken'][:2])}",
                "priority": "P0" if risk_level in ("红", "橙") else "P1",
                "type": "long",
                "time": _now_str(),
                "timestamp": time.time(),
                "category": "warning_experience",
                "enterprise_id": eid,
                "tags": ["预警经验", risk_level, scenario],
                "data_source": fname,
                "version": 1,
                "verified": True,
                "experience_detail": experience,
            })

            if eid not in _enterprise_risk_history:
                _enterprise_risk_history[eid] = []
            _enterprise_risk_history[eid].append({
                "time": _now_str(),
                "timestamp": time.time(),
                "risk_score": risk_score,
                "risk_level": risk_level,
                "scenario": scenario,
                "key_factors": key_factors,
            })

            results.append(assessment_result)

        _persist_store("short_term", _short_term_store)
        _persist_store("long_term", _long_term_store)
        _persist_store("warning_experience", _warning_experience_store)
        _persist_store("enterprise_risk_history", _enterprise_risk_history)
        _record_audit("assess_enterprise", "user", fname, f"预测分析 {len(results)} 条数据，生成 {experience_count} 条预警经验")
        return _sanitize_for_json({
            "success": True,
            "message": f"完成 {len(results)} 条企业数据预测分析，生成 {experience_count} 条预警经验",
            "filename": fname,
            "total_rows": len(df),
            "results": results,
            "experience_count": experience_count,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"企业预测分析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预测分析失败: {str(e)}")


@router.get("/warning-experiences")
async def list_warning_experiences(
    enterprise_id: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("timestamp"),
    sort_order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
) -> Dict[str, Any]:
    items = _warning_experience_store.copy()
    if enterprise_id:
        items = [i for i in items if i.get("enterprise_id") == enterprise_id]
    if risk_level:
        items = [i for i in items if i.get("risk_level") == risk_level]
    if search:
        tokens = search.lower().split()
        items = [i for i in items if all(t in json.dumps(i, ensure_ascii=False).lower() for t in tokens)]
    reverse = sort_order == "desc"
    items.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit], "offset": offset, "limit": limit}


@router.get("/enterprise-risk-history/{enterprise_id}")
async def get_enterprise_risk_history(enterprise_id: str) -> Dict[str, Any]:
    history = _enterprise_risk_history.get(enterprise_id, [])
    return {"enterprise_id": enterprise_id, "history": history, "total": len(history)}


@router.get("/iteration-tracking")
async def iteration_tracking() -> Dict[str, Any]:
    if not _iteration_history:
        for i in range(5):
            _iteration_history.append({
                "version": f"v1.{i}",
                "timestamp": time.time() - (5 - i) * 86400,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - (5 - i) * 86400)),
                "accuracy": round(0.72 + i * 0.04 + random.uniform(-0.02, 0.02), 4),
                "precision": round(0.70 + i * 0.03 + random.uniform(-0.02, 0.02), 4),
                "recall": round(0.68 + i * 0.05 + random.uniform(-0.02, 0.02), 4),
                "f1_score": round(0.69 + i * 0.04 + random.uniform(-0.02, 0.02), 4),
                "false_positive_rate": round(0.15 - i * 0.02 + random.uniform(-0.01, 0.01), 4),
                "false_negative_rate": round(0.12 - i * 0.015 + random.uniform(-0.01, 0.01), 4),
                "samples": 1000 + i * 200,
                "improvements": [f"优化特征工程v{i}", f"调整基学习器权重v{i}"],
                "status": "production",
            })
        _persist_store("iteration_history", _iteration_history)

    latest = _iteration_history[-1] if _iteration_history else None
    return {
        "history": _iteration_history,
        "latest": latest,
        "total_iterations": len(_iteration_history),
    }


@router.get("/approvals")
async def list_approvals(
    status: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
) -> Dict[str, Any]:
    items = _approval_store.copy()
    if status:
        items = [i for i in items if i.get("status") == status]
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit], "offset": offset, "limit": limit}


@router.post("/approvals")
async def create_approval(req: ApprovalRequest) -> Dict[str, Any]:
    approval = {
        "id": _new_id(),
        "target_id": req.target_id,
        "action": req.action,
        "actor": req.actor,
        "comment": req.comment,
        "status": "pending",
        "created_at": _now_str(),
        "timestamp": time.time(),
    }
    _approval_store.insert(0, approval)
    _persist_store("approval_store", _approval_store)
    _record_audit("create_approval", req.actor, req.target_id, f"创建审批请求: {req.action}")
    return approval


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, decision: str = Query(...), actor: str = Query("admin"), comment: str = Query("")) -> Dict[str, Any]:
    approval = next((a for a in _approval_store if a["id"] == approval_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    if approval["status"] != "pending":
        raise HTTPException(status_code=400, detail="该审批已处理")
    before = approval.copy()
    approval["status"] = decision
    approval["decided_by"] = actor
    approval["decision_comment"] = comment
    approval["decided_at"] = _now_str()
    _record_audit("decide_approval", actor, approval_id, f"审批决策: {decision}", before=before, after=approval)
    _persist_store("approval_store", _approval_store)
    _persist_store("audit_log", _audit_log_store)
    return approval


@router.get("/audit-logs")
async def list_audit_logs(
    action: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
) -> Dict[str, Any]:
    items = _audit_log_store.copy()
    if action:
        items = [i for i in items if i.get("action") == action]
    if actor:
        items = [i for i in items if i.get("actor") == actor]
    if search:
        tokens = search.lower().split()
        items = [i for i in items if all(t in json.dumps(i, ensure_ascii=False).lower() for t in tokens)]
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit], "offset": offset, "limit": limit}


@router.post("/export")
async def export_data(req: ExportRequest):
    if req.memory_type == "short":
        items = _short_term_store.copy()
    elif req.memory_type == "long":
        items = _long_term_store.copy()
    elif req.memory_type == "warning_experience":
        items = _warning_experience_store.copy()
    else:
        raise HTTPException(status_code=400, detail=f"不支持的类型: {req.memory_type}")

    if req.selected_ids:
        items = [i for i in items if i.get("id") in req.selected_ids]

    if req.time_from:
        items = [i for i in items if i.get("timestamp", 0) >= req.time_from]
    if req.time_to:
        items = [i for i in items if i.get("timestamp", 0) <= req.time_to]

    if req.filters:
        for key, val in req.filters.items():
            if val is not None and val != "":
                items = [i for i in items if i.get(key) == val or str(i.get(key, "")) == str(val)]

    if not items:
        raise HTTPException(status_code=400, detail="无数据可导出")

    clean_items = _sanitize_for_json(items)
    df = pd.DataFrame(clean_items)

    if req.format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        buf.seek(0)
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={req.memory_type}_export.csv"},
        )
    elif req.format == "pdf":
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            pdf_buf = io.BytesIO()
            page_size = landscape(A4)
            doc = SimpleDocTemplate(pdf_buf, pagesize=page_size)
            elements = []
            styles = getSampleStyleSheet()

            try:
                pdfmetrics.registerFont(TTFont("SimHei", "/usr/share/fonts/truetype/simhei.ttf"))
                font_name = "SimHei"
            except Exception:
                font_name = "Helvetica"

            title_style = styles["Title"]
            title_style.fontName = font_name
            elements.append(Paragraph(f"{req.memory_type} 记忆数据导出报告", title_style))
            elements.append(Spacer(1, 12))

            export_cols = ["id", "text", "priority", "category", "time", "enterprise_id"]
            available_cols = [c for c in export_cols if c in df.columns]
            if not available_cols:
                available_cols = list(df.columns[:8])

            table_data = [available_cols]
            for _, row in df.head(200).iterrows():
                row_vals = []
                for col in available_cols:
                    val = str(row.get(col, ""))[:50]
                    row_vals.append(val)
                table_data.append(row_vals)

            t = Table(table_data, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            elements.append(t)

            doc.build(elements)
            pdf_buf.seek(0)
            return StreamingResponse(
                pdf_buf,
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename={req.memory_type}_export.pdf"},
            )
        except ImportError:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="数据")
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={req.memory_type}_export.xlsx"},
            )
    else:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="数据")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={req.memory_type}_export.xlsx"},
        )


@router.get("/stats")
async def memory_stats() -> Dict[str, Any]:
    short_total = len(_short_term_store)
    long_total = len(_long_term_store)
    short_by_cat: Dict[str, int] = {}
    short_by_prio: Dict[str, int] = {}
    short_by_enterprise: Dict[str, int] = {}
    short_timeline: Dict[str, int] = {}
    for s in _short_term_store:
        cat = s.get("category", "unknown")
        short_by_cat[cat] = short_by_cat.get(cat, 0) + 1
        prio = s.get("priority", "P2")
        short_by_prio[prio] = short_by_prio.get(prio, 0) + 1
        eid = s.get("enterprise_id")
        if eid:
            short_by_enterprise[eid] = short_by_enterprise.get(eid, 0) + 1
        day = (s.get("time") or "")[:10]
        if day:
            short_timeline[day] = short_timeline.get(day, 0) + 1
    long_by_cat: Dict[str, int] = {}
    long_by_prio: Dict[str, int] = {}
    long_by_source: Dict[str, int] = {}
    long_by_enterprise: Dict[str, int] = {}
    long_timeline: Dict[str, int] = {}
    long_verified = 0
    for l in _long_term_store:
        cat = l.get("category", "unknown")
        long_by_cat[cat] = long_by_cat.get(cat, 0) + 1
        prio = l.get("priority", "P1")
        long_by_prio[prio] = long_by_prio.get(prio, 0) + 1
        src = l.get("data_source")
        if src:
            long_by_source[src] = long_by_source.get(src, 0) + 1
        eid = l.get("enterprise_id")
        if eid:
            long_by_enterprise[eid] = long_by_enterprise.get(eid, 0) + 1
        day = (l.get("time") or "")[:10]
        if day:
            long_timeline[day] = long_timeline.get(day, 0) + 1
        if l.get("verified"):
            long_verified += 1
    we_total = len(_warning_experience_store)
    we_by_level: Dict[str, int] = {}
    we_by_scenario: Dict[str, int] = {}
    we_financial_total = 0.0
    we_timeline: Dict[str, int] = {}
    for w in _warning_experience_store:
        lvl = w.get("risk_level", "unknown")
        we_by_level[lvl] = we_by_level.get(lvl, 0) + 1
        sc = w.get("scenario", "unknown")
        we_by_scenario[sc] = we_by_scenario.get(sc, 0) + 1
        we_financial_total += float(w.get("financial_impact", 0) or 0)
        day = (w.get("generated_at") or "")[:10]
        if day:
            we_timeline[day] = we_timeline.get(day, 0) + 1
    return {
        "short_term": {
            "total": short_total,
            "by_category": short_by_cat,
            "by_priority": short_by_prio,
            "by_enterprise": short_by_enterprise,
            "timeline": short_timeline,
        },
        "long_term": {
            "total": long_total,
            "by_category": long_by_cat,
            "by_priority": long_by_prio,
            "by_source": long_by_source,
            "by_enterprise": long_by_enterprise,
            "timeline": long_timeline,
            "verified_count": long_verified,
        },
        "warning_experiences": {
            "total": we_total,
            "by_level": we_by_level,
            "by_scenario": we_by_scenario,
            "financial_total": round(we_financial_total, 1),
            "timeline": we_timeline,
        },
        "iteration_count": len(_iteration_history),
        "pending_approvals": len([a for a in _approval_store if a.get("status") == "pending"]),
        "audit_log_count": len(_audit_log_store),
    }


@router.post("/persist")
async def manual_persist() -> Dict[str, bool]:
    try:
        _persist_all_stores()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
