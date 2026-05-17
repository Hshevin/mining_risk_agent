"""Rebuild ``knowledge_base/类似事故处理案例.md`` from public data.

The filesystem Markdown file is the authoritative source for the RAG case
library. This script is intentionally idempotent: each run reloads public data
through ``DataLoader``, rebuilds the full Markdown document, and overwrites only
the accident-case knowledge base plus an optional JSON run report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mining_risk_common.dataplane.loader import DataLoader  # noqa: E402
from mining_risk_common.utils.config import resolve_project_path  # noqa: E402


TARGET_KB = PROJECT_ROOT / "knowledge_base" / "类似事故处理案例.md"
INVENTORY_JSON = PROJECT_ROOT / "reports" / "public_data_inventory.json"
FIELD_MAPPING_CSV = PROJECT_ROOT / "reports" / "public_data_field_mapping.csv"
DEFAULT_REPORT_JSON = PROJECT_ROOT / "reports" / "accident_cases_kb_rebuild_run.json"

MISSING_VALUES = {
    "",
    "-",
    "--",
    "/",
    "\\",
    "nan",
    "none",
    "null",
    "nat",
    "无",
    "无记录",
    "未填",
    "空",
    "未知",
    "暂无",
}

TRUTHY = {"1", "1.0", "true", "yes", "y", "是", "有", "存在", "已发生"}
FALSY = {"0", "0.0", "false", "no", "n", "否", "无", "不存在", "未发生"}

CASE_LIMIT_PER_CLASS = 12
TEMPLATE_COUNT = 3


@dataclass
class SourceInfo:
    key: str
    source_file: str
    sheet: str
    rows: int
    columns: int
    fields: list[str] = field(default_factory=list)


@dataclass
class EnterpriseProfile:
    name: str | None = None
    credit_code: str | None = None
    internal_id: str | None = None
    industry: str | None = None
    supervision: str | None = None
    address: str | None = None
    production_status: str | None = None
    business_status: str | None = None
    latest_risk_level: str | None = None
    risk_total_count: str | None = None
    risk_with_accident_count: str | None = None
    risk_accident_flag: str | None = None
    trouble_total_count: str | None = None
    trouble_level_2_count: str | None = None
    trouble_unrectified_count: str | None = None
    check_total_count: str | None = None
    writ_total_count: str | None = None
    total_penalty_money: str | None = None
    staff_num: str | None = None
    safety_num: str | None = None
    dust_type: str | None = None
    dust_ganshi_num: str | None = None
    dust_work_num: str | None = None
    gaolu_num: str | None = None
    zhuanlu_num: str | None = None
    dianlu_num: str | None = None
    anguan_num: str | None = None
    dangerous_chemical: str | None = None
    finite_space: str | None = None
    metal_smelter: str | None = None


@dataclass
class RiskHistoryInfo:
    report_id: str
    enterprise_name: str | None = None
    enterprise_id: str | None = None
    industry: str | None = None
    supervision: str | None = None
    report_time: str | None = None
    risk_count: str | None = None
    major_risk_count: str | None = None
    large_risk_count: str | None = None
    production_status: str | None = None
    source: str | None = None


@dataclass
class WritInfo:
    writ_ids: list[str] = field(default_factory=list)
    writ_nos: list[str] = field(default_factory=list)
    writ_types: list[str] = field(default_factory=list)
    writ_sources: list[str] = field(default_factory=list)
    created_times: list[str] = field(default_factory=list)
    attachment_ids: list[str] = field(default_factory=list)
    source_file: str | None = None


@dataclass
class CaseCard:
    case_id: str
    class_code: str
    class_name: str
    title: str
    enterprise: str
    masked_id: str
    industry: str
    supervision: str
    risk_scene: str
    trigger_signals: list[str]
    evidence: list[str]
    risk_chain: list[str]
    disposal_flow: list[str]
    rectification_review: list[str]
    keywords: list[str]
    note: str = ""
    score: float = 0


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).replace("\ufeff", "").replace("\r", " ").replace("\n", " ")
    text = text.replace("??", "")
    text = text.replace("#@#@", "；").strip()
    text = re.sub(r"\s+", " ", text)
    if text.lower() in MISSING_VALUES:
        return None
    return text


def shorten(text: Any, limit: int = 120) -> str:
    value = clean_value(text) or "未知"
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def md_cell(value: Any) -> str:
    return shorten(value, 180).replace("|", "\\|")


def parse_number(value: Any) -> float | None:
    text = clean_value(value)
    if text is None:
        return None
    normalized = text.replace(",", "").replace("，", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_flag(value: Any) -> bool | None:
    text = clean_value(value)
    if text is None:
        return None
    low = text.lower()
    if low in TRUTHY:
        return True
    if low in FALSY:
        return False
    number = parse_number(text)
    if number is not None:
        if number == 1:
            return True
        if number == 0:
            return False
    return None


def mask_id(value: Any) -> str:
    text = clean_value(value)
    if text is None:
        return "未知"
    if len(text) <= 8:
        return text
    return f"{text[:6]}****{text[-4:]}"


def looks_like_credit_code(value: str | None) -> bool:
    if not value:
        return False
    text = re.sub(r"[^0-9A-Z]", "", value.upper())
    return 15 <= len(text) <= 18 and not text.startswith(("EP", "WS", "LA", "PI", "USER"))


def stable_hash(*parts: Any, length: int = 10) -> str:
    raw = "|".join(clean_value(part) or "" for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def find_col(df: pd.DataFrame, aliases: Iterable[str], contains: bool = False) -> str | None:
    columns = [str(col) for col in df.columns]
    for alias in aliases:
        if alias in df.columns:
            return alias
        for col in columns:
            if col == alias:
                return col
    if contains:
        for alias in aliases:
            for col in columns:
                if alias in col:
                    return col
    return None


def first_row_value(row: pd.Series, columns: Iterable[str | None]) -> str | None:
    for col in columns:
        if col and col in row.index:
            value = clean_value(row[col])
            if value is not None:
                return value
    return None


def source_key_from_inventory_path(source_file: str) -> str:
    stem = Path(source_file).with_suffix("").as_posix()
    prefix = "公开数据/公开数据/"
    if stem.startswith(prefix):
        return stem[len(prefix) :]
    return stem


def load_inventory() -> dict[str, SourceInfo]:
    if not INVENTORY_JSON.exists():
        return {}
    raw = json.loads(INVENTORY_JSON.read_text(encoding="utf-8"))
    records: dict[str, SourceInfo] = {}
    for item in raw.get("table_records", []):
        key = source_key_from_inventory_path(item.get("source_file", ""))
        records[key] = SourceInfo(
            key=key,
            source_file=item.get("source_file", key),
            sheet=item.get("sheet", ""),
            rows=int(item.get("rows") or 0),
            columns=int(item.get("columns") or 0),
            fields=[str(field) for field in item.get("fields", [])],
        )
    return records


def source_label(table_key: str, inventory: dict[str, SourceInfo]) -> str:
    info = inventory.get(table_key)
    if info is None:
        return table_key
    sheet = f" / {info.sheet}" if info.sheet and info.sheet != "CSV" else ""
    return f"{info.source_file}{sheet}"


def evidence_line(
    table_key: str,
    fields: Iterable[str],
    inventory: dict[str, SourceInfo],
    values: Iterable[str] | None = None,
) -> str:
    field_text = "、".join(fields)
    if values:
        value_text = "；".join(shorten(value, 80) for value in values if clean_value(value))
        if value_text:
            return f"{source_label(table_key, inventory)}：字段 {field_text}；关键值 {value_text}"
    return f"{source_label(table_key, inventory)}：字段 {field_text}"


def update_if_empty(profile: EnterpriseProfile, attr: str, value: Any) -> None:
    text = clean_value(value)
    if text is None:
        return
    if getattr(profile, attr) in (None, ""):
        setattr(profile, attr, text)


def build_profiles(
    tables: dict[str, pd.DataFrame],
) -> tuple[dict[str, EnterpriseProfile], dict[str, EnterpriseProfile]]:
    by_credit: dict[str, EnterpriseProfile] = {}
    by_name: dict[str, EnterpriseProfile] = {}

    for _, df in tables.items():
        name_col = find_col(df, ("enterprise_name", "ENTERPRISE_NAME", "COMPANY_NAME", "企业名称", "当事人"))
        credit_col = find_col(
            df,
            (
                "enterprise_id",
                "ENTERPRISE_ID",
                "UUIT_NO",
                "COMPANY_CODE",
                "CREDIT_NO",
                "社会信用代码",
                "统一社会信用代码",
                "社会统一信用代码 主键",
                "组织机构代码",
                "生产经营单位注册号",
                "统一社会信息用代码 duplicated?",
            ),
        )
        if not name_col and not credit_col:
            continue

        columns = {
            "industry": find_col(
                df,
                (
                    "indus_type_large",
                    "INDUS_TYPE_LAGRE_NAME",
                    "INDUS_TYPE_LAGRE",
                    "INDUSTRY_TYPE_BIG",
                    "行业类别大类",
                    "行业监管分类",
                    "行业领域",
                    "监管行业大类",
                    "企业所属监管行业大类",
                    "监管分类",
                ),
            ),
            "supervision": find_col(
                df,
                (
                    "supervision_large",
                    "SUPERVISION_LARGE",
                    "SUPERVISION_NAME",
                    "SUPERVISION_INDUSTRY_TYPE_NAMES",
                    "监管行业大类",
                    "行业监管大类",
                    "行业监管分类",
                    "监管分类",
                    "专项监管大类名称",
                ),
            ),
            "address": find_col(
                df,
                ("address", "formatted_address", "BUSINESS_ADDRESS_FULL", "BUSINESS_ADDRESS", "注册地址", "生产经营地址全称", "生产经营地址"),
            ),
            "production_status": find_col(df, ("production_status", "rh_production_status", "PRODUCTION_STATUS", "生产状态：1正常生产，2临时停产， 3长期停产")),
            "business_status": find_col(df, ("business_status", "COMPANY_OPERATION_STATUS", "企业经营状态")),
            "latest_risk_level": find_col(df, ("new_level", "latest_risk_level", "风险等级")),
            "risk_total_count": find_col(df, ("risk_total_count", "风险数量")),
            "risk_with_accident_count": find_col(df, ("risk_with_accident_count",)),
            "risk_accident_flag": find_col(df, ("risk_accident_flag", "事故")),
            "trouble_total_count": find_col(df, ("trouble_total_count",)),
            "trouble_level_2_count": find_col(df, ("trouble_level_2_count",)),
            "trouble_unrectified_count": find_col(df, ("trouble_unrectified_count",)),
            "check_total_count": find_col(df, ("check_total_count", "检查次数")),
            "writ_total_count": find_col(df, ("writ_total_count",)),
            "total_penalty_money": find_col(df, ("total_penalty_money",)),
            "staff_num": find_col(df, ("staff_num", "EMPLOYEE_COUNT", "从业人员数量")),
            "safety_num": find_col(df, ("safety_num", "SAFETY_NUM", "专职安全生产管理人员数量")),
            "dust_type": find_col(df, ("dust_type", "DUST_TYPE", "粉尘类型")),
            "dust_ganshi_num": find_col(df, ("dust_ganshi_num", "DUST_GANSHI_NUM", "集中除尘系统干式数量")),
            "dust_work_num": find_col(df, ("dust_work_num", "DUST_WORK_NUM")),
            "gaolu_num": find_col(df, ("gaolu_num", "GAOLU_NUM", "高炉数量")),
            "zhuanlu_num": find_col(df, ("zhuanlu_num", "ZHUANLU_NUM", "转炉数量")),
            "dianlu_num": find_col(df, ("dianlu_num", "DIANLU_NUM", "电炉数量")),
            "anguan_num": find_col(df, ("anguan_num", "ANGUAN_NUM", "氨罐数量")),
            "dangerous_chemical": find_col(df, ("dangerous_chemical_enterprise", "DANGEROUS_CHEMICAL_ENTERPRISE", "危化品")),
            "finite_space": find_col(df, ("is_finite_space", "CONFINED_SPACES_ENTERPRISE", "是否属于有限空间企业")),
            "metal_smelter": find_col(df, ("is_metal_smelter", "是否属于金属冶炼企业", "金属冶炼")),
        }

        for _, row in df.iterrows():
            name = clean_value(row[name_col]) if name_col else None
            raw_credit = clean_value(row[credit_col]) if credit_col else None
            credit = raw_credit if looks_like_credit_code(raw_credit) else None
            internal_id = raw_credit if raw_credit and not credit else None

            if not name and not credit and not internal_id:
                continue
            profile = by_credit.get(credit or "") if credit else None
            if profile is None and name:
                profile = by_name.get(name)
            if profile is None:
                profile = EnterpriseProfile()
            update_if_empty(profile, "name", name)
            update_if_empty(profile, "credit_code", credit)
            update_if_empty(profile, "internal_id", internal_id)
            for attr, col in columns.items():
                if col:
                    update_if_empty(profile, attr, row[col])

            if profile.credit_code:
                by_credit[profile.credit_code] = profile
            if profile.name:
                by_name[profile.name] = profile

    return by_credit, by_name


def profile_for(
    *,
    credit: str | None = None,
    name: str | None = None,
    by_credit: dict[str, EnterpriseProfile],
    by_name: dict[str, EnterpriseProfile],
) -> EnterpriseProfile:
    if credit and credit in by_credit:
        return by_credit[credit]
    if name and name in by_name:
        return by_name[name]
    profile = EnterpriseProfile(name=name, credit_code=credit)
    return profile


def profile_enterprise_name(profile: EnterpriseProfile, fallback: str | None = None) -> str:
    return profile.name or clean_value(fallback) or "脱敏企业"


def profile_masked_id(profile: EnterpriseProfile, fallback: str | None = None) -> str:
    return mask_id(profile.credit_code or profile.internal_id or fallback)


def profile_industry(profile: EnterpriseProfile, fallback: str | None = None) -> str:
    return profile.industry or profile.supervision or clean_value(fallback) or "未知"


def profile_supervision(profile: EnterpriseProfile, fallback: str | None = None) -> str:
    return profile.supervision or clean_value(fallback) or "未知"


def infer_scene(*texts: Any) -> str:
    text = " ".join(clean_value(item) or "" for item in texts)
    if re.search(r"有限空间|受限空间|雨水收集池|污水池|罐内|地下|地沟|下水道|井|池", text):
        return "有限空间"
    if re.search(r"粉尘|涉粉|涉爆|除尘|积尘|喷粉", text):
        return "粉尘涉爆"
    if re.search(r"危化|危险化学品|可燃|易燃|气体|储罐|甲类|氨|氧气瓶|燃气|六氟|制氢|动火|泄漏", text):
        return "危化品"
    if re.search(r"冶金|金属冶炼|高炉|转炉|电炉|煤气|熔炼|浇铸|铝|钢|行车|热风炉|脱硫脱硝", text):
        return "冶金"
    if re.search(r"中毒|窒息", text):
        return "有限空间"
    return "通用"


def disposal_flow(scene: str) -> list[str]:
    flows = {
        "粉尘涉爆": [
            "立即停止涉粉作业和动火作业，隔离积尘、火源和非防爆电气。",
            "核查除尘系统、泄爆/隔爆、清扫记录和粉尘浓度控制措施。",
            "由企业安全负责人和属地监管人员共同确认清扫、检测、复产条件。",
        ],
        "冶金": [
            "先停用相关炉窑、煤气、行车或压力部件，设置现场警戒。",
            "核查联锁、吹扫、检测、吊装和高温熔融金属防喷溅措施。",
            "复产前完成设备专项检测、作业票复核和班组再培训。",
        ],
        "危化品": [
            "立即停止动火、装卸、储存转移等高风险作业，切断泄漏/点火源。",
            "组织可燃、有毒、有害气体检测，按预案启用通风、喷淋、围堵或转移。",
            "复核危化品专库、报警仪、安全阀、压力表和特殊作业许可。",
        ],
        "有限空间": [
            "停止进入有限空间，撤出现场作业人员并设警戒和监护。",
            "执行“先通风、再检测、后作业”，复核氧含量、可燃气体和有毒气体。",
            "补齐审批、监护、救援三脚架/安全绳/呼吸防护等条件后方可恢复。",
        ],
        "通用": [
            "立即停止相关不安全作业，隔离风险点并保存检查证据。",
            "按隐患等级派单给企业主要负责人、安全管理部门和属地监管人员。",
            "整改完成后复查验证，形成照片、检测记录、培训记录和闭环台账。",
        ],
    }
    return flows.get(scene, flows["通用"])


def review_steps(scene: str, suggestion: str | None = None) -> list[str]:
    first = suggestion or "按风险点重新评估隐患原因、责任岗位和整改期限。"
    return [
        first,
        "复查时核验现场实物、制度台账、人员培训和整改照片，避免只做文字闭环。",
        f"将该案例写入 {scene} 场景关键词库，后续同类预警优先召回。",
    ]


def risk_chain_for(scene: str, trigger: str, control_gap: str | None = None) -> list[str]:
    scene_result = {
        "粉尘涉爆": "积尘、点火源或除尘失效可能演化为粉尘爆炸。",
        "冶金": "高温、煤气、吊装或联锁失效可能演化为灼烫、爆炸、中毒或机械伤害。",
        "危化品": "危化品储存、动火、泄漏或仪表失效可能演化为火灾、爆炸、中毒窒息。",
        "有限空间": "通风检测、审批监护或救援装备缺失可能演化为中毒窒息和盲目施救。",
        "通用": "现场缺陷叠加管理失效可能扩大为人员伤害或行政执法风险。",
    }
    return [
        f"触发点：{trigger}",
        f"薄弱环节：{control_gap or '现场管控、制度执行或复查闭环不足'}",
        f"可能后果：{scene_result.get(scene, scene_result['通用'])}",
    ]


def keyword_list(*parts: Any, scene: str) -> list[str]:
    words = [scene, "公开数据案例", "RAG案例", "隐患闭环", "执法处罚", "风险组合"]
    text = " ".join(clean_value(part) or "" for part in parts)
    for token in re.split(r"[、，,；;。\s]+", text):
        token = token.strip("“”\"'()（）")
        if 2 <= len(token) <= 16 and token not in words:
            if re.search(r"事故|隐患|处罚|风险|整改|文书|动火|有限空间|粉尘|危化|煤气|特种|安全", token):
                words.append(token)
        if len(words) >= 12:
            break
    return words


def build_risk_history_map(
    tables: dict[str, pd.DataFrame],
    inventory: dict[str, SourceInfo],
) -> dict[str, RiskHistoryInfo]:
    result: dict[str, RiskHistoryInfo] = {}
    for key, df in tables.items():
        if "szs_enterprise_risk_history" not in key:
            continue
        id_col = find_col(df, ("ID", "主键ID"))
        if not id_col:
            continue
        cols = {
            "enterprise_id": find_col(df, ("ENTERPRISE_ID", "企业ID")),
            "enterprise_name": find_col(df, ("ENTERPRISE_NAME", "企业名称")),
            "industry": find_col(df, ("SUPERVISION_NAME", "行业领域", "行业监管分类")),
            "supervision": find_col(df, ("SUPERVISION_LARGE", "行业监管分类")),
            "report_time": find_col(df, ("REPORT_TIME", "报告时间")),
            "risk_count": find_col(df, ("RISK_ITEM_NUM", "风险数量")),
            "major_risk_count": find_col(df, ("LEVEL_1_NUM", "重大风险数量")),
            "large_risk_count": find_col(df, ("LEVEL_2_NUM", "较大风险数量")),
            "production_status": find_col(df, ("PRODUCTION_STATUS", "生产状态：1正常生产，2临时停产， 3长期停产")),
        }
        for _, row in df.iterrows():
            report_id = clean_value(row[id_col])
            if not report_id:
                continue
            current = result.get(report_id) or RiskHistoryInfo(report_id=report_id)
            for attr, col in cols.items():
                if col:
                    value = clean_value(row[col])
                    if value and getattr(current, attr) is None:
                        setattr(current, attr, value)
            if current.source is None:
                current.source = source_label(key, inventory)
            result[report_id] = current
    return result


def build_writ_maps(
    tables: dict[str, pd.DataFrame],
    inventory: dict[str, SourceInfo],
) -> tuple[dict[str, WritInfo], dict[str, WritInfo]]:
    by_case: dict[str, WritInfo] = defaultdict(WritInfo)
    by_writ_id: dict[str, WritInfo] = defaultdict(WritInfo)

    for key, df in tables.items():
        if not key.endswith("ds_aczf_writ_3_202603181747"):
            continue
        cols = {
            "writ_id": find_col(df, ("文书记录id",)),
            "source_id": find_col(df, ("来源id",)),
            "business_id": find_col(df, ("业务id",)),
            "writ_no": find_col(df, ("文书号",)),
            "writ_type": find_col(df, ("文书类型编码(code关联字典表)",)),
            "writ_source": find_col(df, ("文书来源 L 立案  E 检查",)),
            "created_time": find_col(df, ("创建时间",)),
            "pdf_attachment": find_col(df, ("pdf附件id(关联附件表)",)),
            "signed_attachment": find_col(df, ("签字文书附件id(关联附件表)",)),
            "file_attachment": find_col(df, ("文书附件id(关联附件表)",)),
        }
        for _, row in df.iterrows():
            writ_id = first_row_value(row, (cols["writ_id"],))
            keys = [
                first_row_value(row, (cols["source_id"],)),
                first_row_value(row, (cols["business_id"],)),
            ]
            info = WritInfo(source_file=source_label(key, inventory))
            if writ_id:
                info.writ_ids.append(writ_id)
            for attr, col in (
                ("writ_nos", cols["writ_no"]),
                ("writ_types", cols["writ_type"]),
                ("writ_sources", cols["writ_source"]),
                ("created_times", cols["created_time"]),
                ("attachment_ids", cols["pdf_attachment"]),
                ("attachment_ids", cols["signed_attachment"]),
                ("attachment_ids", cols["file_attachment"]),
            ):
                value = first_row_value(row, (col,))
                if value:
                    getattr(info, attr).append(value)
            if writ_id:
                by_writ_id[writ_id] = merge_writ_info(by_writ_id[writ_id], info)
            for case_key in keys:
                if case_key:
                    by_case[case_key] = merge_writ_info(by_case[case_key], info)

    return dict(by_case), dict(by_writ_id)


def merge_writ_info(base: WritInfo, other: WritInfo) -> WritInfo:
    for attr in ("writ_ids", "writ_nos", "writ_types", "writ_sources", "created_times", "attachment_ids"):
        items = getattr(base, attr)
        for value in getattr(other, attr):
            if value and value not in items:
                items.append(value)
    if base.source_file is None:
        base.source_file = other.source_file
    return base


def parse_penalty_amount(text: Any) -> float | None:
    value = clean_value(text)
    if not value:
        return None
    candidates: list[float] = []
    for pattern in (r"(\d{3,}(?:\.\d+)?)\s*元", r"(\d{3,}(?:\.\d+)?),\s*3205"):
        for raw in re.findall(pattern, value):
            try:
                num = float(raw)
            except ValueError:
                continue
            if 1900 <= num <= 2100:
                continue
            if 500 <= num <= 5_000_000:
                candidates.append(num)
    return max(candidates) if candidates else None


def extract_enterprise_from_case(case_name: str | None, party: str | None = None) -> str | None:
    clean_party = clean_value(party)
    if clean_party and not clean_party.startswith(("USER", "LA", "PI", "WS")):
        clean_party = clean_party.replace("??", "").strip("“”\"'")
        if re.search(r"公司|厂|企业|合作社|中心|部|局", clean_party):
            return clean_party

    name = clean_value(case_name)
    if not name:
        return None
    for suffix in ("有限公司", "股份有限公司", "有限责任公司", "公司", "厂", "合作社", "经营部", "管理中心"):
        idx = name.find(suffix)
        if idx > 1:
            return name[: idx + len(suffix)].replace("??", "")
    return None


def load_discretion_map(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for key, df in tables.items():
        if not key.endswith("ds_aczf_la_discretion_3_202603181745"):
            continue
        case_col = find_col(df, ("立案对象id",))
        if not case_col:
            continue
        type_col = find_col(df, ("行政处罚类型",), contains=True)
        for _, row in df.iterrows():
            case_id = clean_value(row[case_col])
            if not case_id:
                continue
            row_text = " ".join(clean_value(row[col]) or "" for col in df.columns)
            text_candidates = [
                clean_value(row[col])
                for col in df.columns
                if clean_value(row[col]) and ("依据" in (clean_value(row[col]) or "") or "罚款" in (clean_value(row[col]) or ""))
            ]
            basis = max(text_candidates, key=len) if text_candidates else shorten(row_text, 300)
            mapping[case_id] = {
                "case_type": clean_value(row[type_col]) if type_col else None,
                "basis": basis,
                "amount": parse_penalty_amount(row_text),
                "source_key": key,
            }
    return mapping


def build_hidden_cases(
    tables: dict[str, pd.DataFrame],
    inventory: dict[str, SourceInfo],
    by_credit: dict[str, EnterpriseProfile],
    by_name: dict[str, EnterpriseProfile],
    limit: int,
) -> tuple[list[CaseCard], dict[str, int]]:
    raw_cases: list[dict[str, Any]] = []
    for key, df in tables.items():
        if "st_fxsb_enterprise_routine_check_trouble" not in key:
            continue
        cols = {
            "id": find_col(df, ("主键ID",)),
            "check_id": find_col(df, ("检查主键ID",)),
            "credit": find_col(df, ("社会信用代码",)),
            "level": find_col(df, ("隐患等级",), contains=True),
            "detail": find_col(df, ("隐患详情",)),
            "suggest": find_col(df, ("整改建议",)),
            "rect": find_col(df, ("整改状态",), contains=True),
            "deadline": find_col(df, ("预估/期限整改时间",)),
            "risk_code": find_col(df, ("风险代码",)),
            "check_time": find_col(df, ("检查时间",)),
            "check_dept": find_col(df, ("检查部门",)),
            "hidden_state": find_col(df, ("隐患状态",)),
            "source_type": find_col(df, ("信息来源",), contains=True),
        }
        if not all(cols[name] for name in ("id", "credit", "level", "detail", "rect")):
            continue
        for _, row in df.iterrows():
            level = clean_value(row[cols["level"]])
            rect = clean_value(row[cols["rect"]])
            hidden_state = clean_value(row[cols["hidden_state"]]) if cols["hidden_state"] else None
            is_major = level == "2"
            is_unrectified = rect == "0" or hidden_state == "0"
            if not (is_major or is_unrectified):
                continue
            detail = clean_value(row[cols["detail"]])
            if detail in (None, "无", "一般", "已整改", "正常"):
                if not is_major:
                    continue
            raw_cases.append(
                {
                    "source_key": key,
                    "source_priority": 0 if "数据补充" in key else 1,
                    "id": clean_value(row[cols["id"]]),
                    "check_id": clean_value(row[cols["check_id"]]) if cols["check_id"] else None,
                    "credit": clean_value(row[cols["credit"]]),
                    "level": level,
                    "detail": detail,
                    "suggest": clean_value(row[cols["suggest"]]) if cols["suggest"] else None,
                    "rect": rect,
                    "deadline": clean_value(row[cols["deadline"]]) if cols["deadline"] else None,
                    "risk_code": clean_value(row[cols["risk_code"]]) if cols["risk_code"] else None,
                    "check_time": clean_value(row[cols["check_time"]]) if cols["check_time"] else None,
                    "check_dept": clean_value(row[cols["check_dept"]]) if cols["check_dept"] else None,
                    "hidden_state": hidden_state,
                    "source_type": clean_value(row[cols["source_type"]]) if cols["source_type"] else None,
                    "is_major": is_major,
                    "is_unrectified": is_unrectified,
                }
            )

    dedup: dict[str, dict[str, Any]] = {}
    for item in sorted(raw_cases, key=lambda x: (x["source_priority"], x["id"] or "")):
        key = item["id"] or stable_hash(item["credit"], item["detail"])
        dedup.setdefault(key, item)

    selected_items = sorted(
        dedup.values(),
        key=lambda item: (
            100 if item["is_major"] else 0,
            80 if item["is_unrectified"] else 0,
            len(item.get("detail") or ""),
            item.get("check_time") or "",
        ),
        reverse=True,
    )

    cases: list[CaseCard] = []
    seen_signature: set[tuple[str, str]] = set()
    for item in selected_items:
        profile = profile_for(credit=item["credit"], by_credit=by_credit, by_name=by_name)
        scene = infer_scene(item["detail"], item["suggest"], profile.industry, profile.dust_type, profile.metal_smelter)
        signature = (profile_enterprise_name(profile, item["check_dept"]), scene)
        if signature in seen_signature and len(cases) >= 6:
            continue
        seen_signature.add(signature)
        trigger = []
        if item["is_major"]:
            trigger.append("隐患等级=2（重大隐患）")
        if item["is_unrectified"]:
            trigger.append("整改状态=0 或隐患状态=0（未整改/未闭环）")
        trigger.append(f"检查发现：{shorten(item['detail'], 100)}")
        if item["deadline"]:
            trigger.append(f"整改期限：{item['deadline']}")
        if item["risk_code"]:
            trigger.append(f"关联风险代码：{item['risk_code']}")

        evidence = [
            evidence_line(
                item["source_key"],
                ("主键ID", "社会信用代码", "隐患等级", "隐患详情", "整改建议", "整改状态", "预估/期限整改时间", "检查时间"),
                inventory,
                (f"主键ID={item['id']}", f"检查时间={item['check_time']}", f"隐患={item['detail']}"),
            )
        ]
        if profile.name or profile.industry:
            evidence.append("企业画像字段：企业名称、行业/监管类别、风险/隐患/处罚计数来自公开企业主表或预合并表。")

        cases.append(
            CaseCard(
                case_id=f"B-{len(cases) + 1:03d}",
                class_code="B",
                class_name="重大隐患与未整改闭环案例",
                title=f"{scene}隐患闭环：{shorten(item['detail'], 36)}",
                enterprise=profile_enterprise_name(profile, item["check_dept"]),
                masked_id=profile_masked_id(profile, item["credit"]),
                industry=profile_industry(profile),
                supervision=profile_supervision(profile),
                risk_scene=scene,
                trigger_signals=trigger,
                evidence=evidence,
                risk_chain=risk_chain_for(scene, shorten(item["detail"], 80), item["suggest"]),
                disposal_flow=disposal_flow(scene),
                rectification_review=review_steps(scene, item["suggest"]),
                keywords=keyword_list(item["detail"], item["suggest"], item["risk_code"], scene=scene),
                note="本案例为公开数据隐患闭环案例，不表述为已发生事故。",
                score=(100 if item["is_major"] else 0) + (80 if item["is_unrectified"] else 0),
            )
        )
        if len(cases) >= limit:
            break

    stats = {
        "raw_candidates": len(raw_cases),
        "deduplicated_candidates": len(dedup),
        "selected": len(cases),
        "major_hidden_danger_candidates": sum(1 for item in dedup.values() if item["is_major"]),
        "unrectified_candidates": sum(1 for item in dedup.values() if item["is_unrectified"]),
    }
    return cases, stats


def build_penalty_cases(
    tables: dict[str, pd.DataFrame],
    inventory: dict[str, SourceInfo],
    by_credit: dict[str, EnterpriseProfile],
    by_name: dict[str, EnterpriseProfile],
    limit: int,
) -> tuple[list[CaseCard], dict[str, int]]:
    discretion = load_discretion_map(tables)
    writ_by_case, writ_by_id = build_writ_maps(tables, inventory)
    raw_cases: list[dict[str, Any]] = []

    for key, df in tables.items():
        if key.endswith("ds_aczf_penalty_illage_3_202603181746"):
            for _, row in df.iloc[1:].iterrows():
                case_id = clean_value(row.iloc[1]) if len(row) > 1 else None
                case_name = clean_value(row.iloc[2]) if len(row) > 2 else None
                if not case_id or not case_name:
                    continue
                party = clean_value(row.iloc[3]) if len(row) > 3 else None
                writ_id = clean_value(row.iloc[6]) if len(row) > 6 else None
                raw_cases.append(
                    {
                        "source_key": key,
                        "case_id": case_id,
                        "case_name": case_name,
                        "party": extract_enterprise_from_case(case_name, party),
                        "writ_id": writ_id if writ_id and writ_id.startswith("WS") else None,
                        "dept": clean_value(row.iloc[4]) if len(row) > 4 else None,
                    }
                )

        if key.endswith("ds_aczf_penalty_disc_3_202603181745"):
            id_col = find_col(df, ("案件id",))
            name_col = find_col(df, ("案件名称",))
            party_col = find_col(df, ("当事人",))
            time_col = find_col(df, ("案发时间",))
            if not id_col or not name_col:
                continue
            for _, row in df.iterrows():
                case_id = clean_value(row[id_col])
                case_name = clean_value(row[name_col])
                if not case_id or not case_name:
                    continue
                raw_cases.append(
                    {
                        "source_key": key,
                        "case_id": case_id,
                        "case_name": case_name,
                        "party": clean_value(row[party_col]) if party_col else extract_enterprise_from_case(case_name),
                        "occurred_time": clean_value(row[time_col]) if time_col else None,
                        "writ_id": None,
                        "dept": None,
                    }
                )

    dedup: dict[str, dict[str, Any]] = {}
    for item in raw_cases:
        dedup.setdefault(item["case_id"], item)

    def case_score(item: dict[str, Any]) -> float:
        disc = discretion.get(item["case_id"], {})
        amount = disc.get("amount") or parse_penalty_amount(item.get("case_name")) or 0
        text = f"{item.get('case_name', '')} {disc.get('basis', '')}"
        score = amount / 1000
        if re.search(r"重大事故隐患|危险化学品|有限空间|高处作业|安全出口|事故隐患|特种作业|操作规程|危险物品", text):
            score += 120
        if item["case_id"] in writ_by_case or item.get("writ_id") in writ_by_id:
            score += 40
        return score

    selected_items = sorted(dedup.values(), key=case_score, reverse=True)
    cases: list[CaseCard] = []
    seen_enterprises: set[str] = set()
    for item in selected_items:
        disc = discretion.get(item["case_id"], {})
        enterprise_name = item.get("party") or extract_enterprise_from_case(item.get("case_name"))
        profile = profile_for(name=enterprise_name, by_credit=by_credit, by_name=by_name)
        scene = infer_scene(item.get("case_name"), disc.get("basis"), profile.industry, profile.supervision)
        enterprise = profile_enterprise_name(profile, enterprise_name)
        if enterprise in seen_enterprises and len(cases) >= 6:
            continue
        seen_enterprises.add(enterprise)
        amount = disc.get("amount") or parse_penalty_amount(item.get("case_name"))
        amount_text = f"{amount:.0f} 元" if isinstance(amount, (int, float)) else "公开字段未稳定解析"
        writ = writ_by_case.get(item["case_id"]) or writ_by_id.get(item.get("writ_id") or "") or WritInfo()
        writ_values = []
        if writ.writ_nos:
            writ_values.append(f"文书号={';'.join(writ.writ_nos[:3])}")
        if writ.writ_ids:
            writ_values.append(f"文书ID={';'.join(writ.writ_ids[:3])}")

        evidence = [
            evidence_line(
                item["source_key"],
                ("案件id", "案件名称", "当事人", "案发时间/流程时间"),
                inventory,
                (f"案件id={item['case_id']}", f"案件名称={item['case_name']}"),
            )
        ]
        if disc:
            evidence.append(
                evidence_line(
                    disc["source_key"],
                    ("立案对象id", "行政处罚类型", "处罚裁量/依据", "罚款金额"),
                    inventory,
                    (f"处罚金额={amount_text}", shorten(disc.get("basis"), 120)),
                )
            )
        if writ_values:
            evidence.append(
                f"{writ.source_file or source_label('新数据/ds_aczf_writ_3_202603181747', inventory)}：字段 文书记录id、文书号、文书来源、附件id；关键值 {'；'.join(writ_values)}"
            )

        trigger = [f"违法/处罚事由：{shorten(item['case_name'], 120)}", f"处罚金额：{amount_text}"]
        if disc.get("case_type") == "1":
            trigger.append("行政处罚类型=1（重大行政处罚案）")
        if writ.writ_nos:
            trigger.append(f"关联执法文书：{';'.join(writ.writ_nos[:2])}")

        control_gap = shorten(disc.get("basis") or item["case_name"], 100)
        cases.append(
            CaseCard(
                case_id=f"C-{len(cases) + 1:03d}",
                class_code="C",
                class_name="执法处罚与违法行为案例",
                title=f"{scene}执法处罚：{shorten(item['case_name'], 36)}",
                enterprise=enterprise,
                masked_id=profile_masked_id(profile, item["case_id"]),
                industry=profile_industry(profile),
                supervision=profile_supervision(profile, item.get("dept")),
                risk_scene=scene,
                trigger_signals=trigger,
                evidence=evidence,
                risk_chain=risk_chain_for(scene, shorten(item["case_name"], 90), control_gap),
                disposal_flow=[
                    "先按执法文书和处罚裁量确认违法事实、责任主体、整改期限和复查节点。",
                    *disposal_flow(scene)[:2],
                ],
                rectification_review=[
                    "复查处罚事由对应的制度、台账、现场设施、人员资质或作业许可是否真正补齐。",
                    "对同一企业近两年检查、隐患、文书、处罚记录做串联检索，识别重复违法。",
                    f"将案由关键词写入 {scene} 场景召回词，作为后续预警的合规处置样例。",
                ],
                keywords=keyword_list(item["case_name"], disc.get("basis"), scene=scene),
                note="本案例为公开数据执法处罚案例，不等同于事故调查报告。",
                score=case_score(item),
            )
        )
        if len(cases) >= limit:
            break

    stats = {
        "raw_candidates": len(raw_cases),
        "deduplicated_candidates": len(dedup),
        "selected": len(cases),
        "with_discretion": sum(1 for item in dedup.values() if item["case_id"] in discretion),
        "with_writ": sum(1 for item in dedup.values() if item["case_id"] in writ_by_case),
    }
    return cases, stats


def build_risk_cases(
    tables: dict[str, pd.DataFrame],
    inventory: dict[str, SourceInfo],
    by_credit: dict[str, EnterpriseProfile],
    by_name: dict[str, EnterpriseProfile],
    risk_history: dict[str, RiskHistoryInfo],
    limit: int,
) -> tuple[list[CaseCard], dict[str, int], dict[str, int]]:
    raw_cases: list[dict[str, Any]] = []
    accident_stats = {"risk_rows_accident_true": 0, "risk_rows_event_true": 0, "risk_rows_with_accident_summary": 0}
    for key, df in tables.items():
        if not (key.endswith("szs_enterprise_risk") or key.endswith("szs_enterprise_risk_202603191750")):
            continue
        cols = {
            "id": find_col(df, ("主键ID",)),
            "report_id": find_col(df, ("报告历史ID",)),
            "risk_code": find_col(df, ("风险代码",)),
            "risk_name": find_col(df, ("风险名称",)),
            "accident_type": find_col(df, ("主要事故类别",)),
            "risk_point": find_col(df, ("风险点",)),
            "risk_level": find_col(df, ("风险等级",)),
            "risk_desc": find_col(df, ("具体风险描述",)),
            "control": find_col(df, ("管控措施",)),
            "control_detail": find_col(df, ("管控措施详细信息",)),
            "duty_dept": find_col(df, ("责任部门",)),
            "duty_person": find_col(df, ("责任人",)),
            "accident_flag": find_col(df, ("是否发生事故",)),
            "accident_summary": find_col(df, ("事故概述",)),
            "event_flag": find_col(df, ("是否发生事件",)),
            "event_summary": find_col(df, ("事故概述__dup2",)),
            "created_time": find_col(df, ("创建时间",)),
            "attachment": find_col(df, ("附件ids",)),
        }
        if not cols["id"] or not cols["risk_name"]:
            continue
        for _, row in df.iterrows():
            accident_true = parse_flag(row[cols["accident_flag"]]) if cols["accident_flag"] else None
            event_true = parse_flag(row[cols["event_flag"]]) if cols["event_flag"] else None
            accident_summary = clean_value(row[cols["accident_summary"]]) if cols["accident_summary"] else None
            event_summary = clean_value(row[cols["event_summary"]]) if cols["event_summary"] else None
            if accident_true:
                accident_stats["risk_rows_accident_true"] += 1
            if event_true:
                accident_stats["risk_rows_event_true"] += 1
            if accident_summary and accident_summary != "没有":
                accident_stats["risk_rows_with_accident_summary"] += 1

            risk_name = clean_value(row[cols["risk_name"]])
            if not risk_name:
                continue
            raw_cases.append(
                {
                    "source_key": key,
                    "source_priority": 0 if "数据补充" in key else 1,
                    "id": clean_value(row[cols["id"]]),
                    "report_id": clean_value(row[cols["report_id"]]) if cols["report_id"] else None,
                    "risk_code": clean_value(row[cols["risk_code"]]) if cols["risk_code"] else None,
                    "risk_name": risk_name,
                    "accident_type": clean_value(row[cols["accident_type"]]) if cols["accident_type"] else None,
                    "risk_point": clean_value(row[cols["risk_point"]]) if cols["risk_point"] else None,
                    "risk_level": clean_value(row[cols["risk_level"]]) if cols["risk_level"] else None,
                    "risk_desc": clean_value(row[cols["risk_desc"]]) if cols["risk_desc"] else None,
                    "control": clean_value(row[cols["control"]]) if cols["control"] else None,
                    "control_detail": clean_value(row[cols["control_detail"]]) if cols["control_detail"] else None,
                    "duty_dept": clean_value(row[cols["duty_dept"]]) if cols["duty_dept"] else None,
                    "duty_person": clean_value(row[cols["duty_person"]]) if cols["duty_person"] else None,
                    "created_time": clean_value(row[cols["created_time"]]) if cols["created_time"] else None,
                    "attachment": clean_value(row[cols["attachment"]]) if cols["attachment"] else None,
                    "accident_true": accident_true,
                    "event_true": event_true,
                    "accident_summary": accident_summary,
                    "event_summary": event_summary,
                }
            )

    dedup: dict[str, dict[str, Any]] = {}
    for item in sorted(raw_cases, key=lambda x: (x["source_priority"], x["id"] or "")):
        dedup.setdefault(item["id"] or stable_hash(item["risk_name"], item["report_id"]), item)

    def risk_score(item: dict[str, Any]) -> float:
        text = " ".join(clean_value(item.get(k)) or "" for k in ("risk_name", "accident_type", "risk_point", "risk_desc", "control_detail"))
        score = len(text) / 80
        if re.search(r"火灾|爆炸|中毒|窒息|容器爆炸|灼烫", text):
            score += 120
        if re.search(r"有限空间|危险化学品|动火|燃气|粉尘|煤气|高处|坍塌|起重", text):
            score += 80
        level = parse_number(item.get("risk_level"))
        if level is not None:
            score += max(0, 5 - level) * 5
        return score

    selected_items = sorted(dedup.values(), key=risk_score, reverse=True)
    cases: list[CaseCard] = []
    scene_counter: Counter[str] = Counter()
    for item in selected_items:
        hist = risk_history.get(item.get("report_id") or "")
        profile = profile_for(
            credit=hist.enterprise_id if hist else None,
            name=hist.enterprise_name if hist else None,
            by_credit=by_credit,
            by_name=by_name,
        )
        scene = infer_scene(item["risk_name"], item["accident_type"], item["risk_point"], item["risk_desc"], item["control_detail"], hist.industry if hist else None)
        if scene_counter[scene] >= 4 and len(cases) < limit - 2:
            continue
        scene_counter[scene] += 1
        enterprise = profile_enterprise_name(profile, hist.enterprise_name if hist else None)
        trigger = [
            f"风险项：{shorten(item['risk_name'], 80)}",
            f"主要事故类别：{shorten(item.get('accident_type'), 80)}",
            f"风险点：{shorten(item.get('risk_point'), 80)}",
        ]
        if item.get("risk_level"):
            trigger.append(f"风险等级：{item['risk_level']}")
        if hist and hist.risk_count:
            trigger.append(f"企业风险数量：{hist.risk_count}，重大/较大风险：{hist.major_risk_count or '未知'}/{hist.large_risk_count or '未知'}")
        if profile.trouble_unrectified_count or profile.total_penalty_money:
            trigger.append(
                "企业画像叠加："
                f"未整改隐患={profile.trouble_unrectified_count or '未知'}，"
                f"处罚金额={profile.total_penalty_money or '未知'}"
            )
        if item.get("accident_true") or item.get("event_true"):
            trigger.append("风险明细字段显示事故/事件已发生，需要人工核验后进入 A 类。")

        evidence = [
            evidence_line(
                item["source_key"],
                ("主键ID", "报告历史ID", "风险代码", "风险名称", "主要事故类别", "风险点", "风险等级", "管控措施详细信息"),
                inventory,
                (f"风险ID={item['id']}", f"风险名称={item['risk_name']}", f"主要事故类别={item.get('accident_type')}"),
            )
        ]
        if hist:
            evidence.append(
                f"{hist.source or 'szs_enterprise_risk_history'}：字段 企业名称、企业ID、行业领域、风险数量、重大风险数量、较大风险数量、报告时间；关键值 企业={hist.enterprise_name}，报告时间={hist.report_time}"
            )

        cases.append(
            CaseCard(
                case_id=f"D-{len(cases) + 1:03d}",
                class_code="D",
                class_name="高风险企业风险组合案例",
                title=f"{scene}风险组合：{shorten(item['risk_name'], 36)}",
                enterprise=enterprise,
                masked_id=profile_masked_id(profile, hist.enterprise_id if hist else item.get("report_id")),
                industry=profile_industry(profile, hist.industry if hist else None),
                supervision=profile_supervision(profile, hist.supervision if hist else None),
                risk_scene=scene,
                trigger_signals=trigger,
                evidence=evidence,
                risk_chain=risk_chain_for(scene, shorten(item["risk_name"], 80), shorten(item.get("control_detail") or item.get("control"), 100)),
                disposal_flow=disposal_flow(scene),
                rectification_review=[
                    shorten(item.get("control_detail") or item.get("control") or "按风险分级管控措施逐项复核。", 180),
                    "将风险点、事故类别、责任部门和复查状态串成企业级处置时间线。",
                    "若同企业同时存在隐患、文书或处罚信号，升级为联合复核对象。",
                ],
                keywords=keyword_list(item["risk_name"], item["accident_type"], item["risk_point"], item["risk_code"], scene=scene),
                note="本案例为风险组合案例；风险表事故/事件字段未确认发生，不写成事故。",
                score=risk_score(item),
            )
        )
        if len(cases) >= limit:
            break

    stats = {
        "raw_candidates": len(raw_cases),
        "deduplicated_candidates": len(dedup),
        "selected": len(cases),
    }
    return cases, stats, accident_stats


def count_merged_accident_signals(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    stats = {
        "merged_risk_accident_flag_true": 0,
        "st_ds_accident_flag_true": 0,
        "work_injury_type_nonempty": 0,
        "risk_with_accident_count_positive": 0,
    }
    for key, df in tables.items():
        if key == "new_已清洗":
            if "risk_accident_flag" in df.columns:
                stats["merged_risk_accident_flag_true"] = int(df["risk_accident_flag"].apply(parse_flag).eq(True).sum())
            if "work_injury_accident_types" in df.columns:
                stats["work_injury_type_nonempty"] = int(df["work_injury_accident_types"].apply(clean_value).notna().sum())
            if "risk_with_accident_count" in df.columns:
                stats["risk_with_accident_count_positive"] = int((df["risk_with_accident_count"].apply(parse_number).fillna(0) > 0).sum())
        if key.endswith("st_ds_aczf_enterprise") and "risk_accident_flag" in df.columns:
            stats["st_ds_accident_flag_true"] += int(df["risk_accident_flag"].apply(parse_flag).eq(True).sum())
        if key.endswith("st_ds_aczf_enterprise_202603181755") and "事故" in df.columns:
            stats["st_ds_accident_flag_true"] += int(df["事故"].apply(parse_flag).eq(True).sum())
    return stats


def bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f"  - {item}" for item in items)


def render_case(case: CaseCard) -> str:
    lines = [
        f"### {case.case_id}｜{case.class_name}｜{case.title}",
        "",
        f"- case_id：`{case.case_id}`",
        f"- 企业名称/脱敏 ID：{case.enterprise}（{case.masked_id}）",
        f"- 行业/监管类别：{case.industry}；{case.supervision}",
        f"- 风险场景：{case.risk_scene}",
        "- 触发信号：",
        bullet_list(case.trigger_signals),
        "- 证据来源文件和字段：",
        bullet_list(case.evidence),
        "- 风险链条：",
        bullet_list(case.risk_chain),
        "- 推荐处置流程：",
        bullet_list(case.disposal_flow),
        "- 整改/复查建议：",
        bullet_list(case.rectification_review),
        f"- 可检索关键词：{', '.join(case.keywords)}",
    ]
    if case.note:
        lines.append(f"- 口径说明：{case.note}")
    return "\n".join(lines)


def render_templates() -> list[str]:
    templates = [
        (
            "E-001",
            "模板案例｜粉尘涉爆事故调查报告待补",
            "适用于后续接入政府事故调查报告后，将粉尘爆炸事故的事故经过、直接原因、间接原因、人员伤亡、行政追责和整改措施结构化入库。",
            "粉尘涉爆",
            "粉尘爆炸, 除尘系统, 积尘清扫, 防爆电气, 事故调查报告",
        ),
        (
            "E-002",
            "模板案例｜冶金煤气中毒事故调查报告待补",
            "适用于后续接入冶金煤气、有限空间交叉场景事故报告，重点抽取煤气隔断、置换、检测、监护和盲目施救链条。",
            "冶金",
            "煤气中毒, 冶金, 有限空间, 置换检测, 盲目施救",
        ),
        (
            "E-003",
            "模板案例｜危化品动火爆燃事故调查报告待补",
            "适用于后续接入危化品动火、储罐、可燃气体报警事故报告，重点抽取特殊作业票、可燃气体检测和承包商管理。",
            "危化品",
            "危化品, 动火作业, 可燃气体, 储罐, 特殊作业许可",
        ),
    ]
    rendered = []
    for case_id, title, usage, scene, keywords in templates:
        rendered.append(
            "\n".join(
                [
                    f"### {case_id}｜模板/外部待补案例｜{title}",
                    "",
                    f"- case_id：`{case_id}`",
                    "- 真实性口径：模板案例，未从本地公开数据确认具体事故，不参与真实案例统计。",
                    f"- 风险场景：{scene}",
                    f"- 使用方式：{usage}",
                    "- 待补证据字段：事故报告标题、事故时间、企业名称、事故经过、直接原因、间接原因、处罚追责、整改复查。",
                    "- 推荐处置流程：待外部报告接入后，以事故调查报告原文为主证据重建。",
                    f"- 可检索关键词：{keywords}, TEMPLATE, 外部待补",
                ]
            )
        )
    return rendered


def render_markdown(
    *,
    tables: dict[str, pd.DataFrame],
    inventory: dict[str, SourceInfo],
    b_cases: list[CaseCard],
    c_cases: list[CaseCard],
    d_cases: list[CaseCard],
    b_stats: dict[str, int],
    c_stats: dict[str, int],
    d_stats: dict[str, int],
    accident_stats: dict[str, int],
    merged_accident_stats: dict[str, int],
    generated_at: str,
) -> str:
    readable_tables = len(tables)
    readable_rows = sum(len(df) for df in tables.values())
    mapping_rows = 0
    if FIELD_MAPPING_CSV.exists():
        try:
            mapping_rows = len(pd.read_csv(FIELD_MAPPING_CSV, encoding="utf-8"))
        except Exception:
            mapping_rows = 0

    real_selected = len(b_cases) + len(c_cases) + len(d_cases)
    stats_rows = [
        ("A 类真实事故/事件案例", 0, "0", "风险明细表事故/事件发生字段均未确认发生；事故概述为空或“没有”。"),
        ("B 类重大隐患与未整改闭环案例", b_stats["deduplicated_candidates"], str(len(b_cases)), "来自隐患排查明细，含重大隐患和未整改/未闭环信号。"),
        ("C 类执法处罚与违法行为案例", c_stats["deduplicated_candidates"], str(len(c_cases)), "来自处罚、立案、裁量和执法文书表。"),
        ("D 类高风险企业风险组合案例", d_stats["deduplicated_candidates"], str(len(d_cases)), "来自风险项、事故类别、管控措施和企业风险历史。"),
        ("E 类模板/外部待补案例", TEMPLATE_COUNT, str(TEMPLATE_COUNT), "全部明确标注为模板，不混入真实案例统计。"),
    ]

    used_source_fields = [
        ("公开数据/公开数据/new_已清洗.xlsx", "enterprise_name, risk_accident_flag, risk_with_accident_count, trouble_unrectified_count, total_penalty_money, work_injury_accident_types"),
        ("公开数据/公开数据/数据补充/st_fxsb_enterprise_routine_check_trouble_202603191745.csv", "主键ID, 社会信用代码, 隐患等级, 隐患详情, 整改建议, 整改状态, 检查时间"),
        ("公开数据/公开数据/数据参考/st_fxsb_enterprise_routine_check_trouble.csv", "主键ID, 社会信用代码, 隐患等级, 隐患详情, 整改建议, 整改状态"),
        ("公开数据/公开数据/数据补充/szs_enterprise_risk_202603191750.csv", "风险名称, 主要事故类别, 风险点, 风险等级, 管控措施详细信息, 是否发生事故/事件"),
        ("公开数据/公开数据/数据补充/szs_enterprise_risk_history_202603191750.csv", "企业名称, 企业ID, 行业领域, 风险数量, 重大风险数量, 较大风险数量"),
        ("公开数据/公开数据/新数据/ds_aczf_penalty_disc_3_202603181745.csv", "案件id, 案件名称, 当事人, 案发时间"),
        ("公开数据/公开数据/新数据/ds_aczf_penalty_illage_3_202603181746.csv", "立案id, 案件id, 案件名称, 当事人, 文书ID"),
        ("公开数据/公开数据/新数据/ds_aczf_la_discretion_3_202603181745.csv", "立案对象id, 行政处罚类型, 处罚裁量, 罚款金额"),
        ("公开数据/公开数据/新数据/ds_aczf_writ_3_202603181747.csv", "文书记录id, 来源id, 文书号, 文书来源, 附件id"),
    ]

    lines = [
        "# 类似事故处理案例",
        "",
        f"> 重建时间：{generated_at}",
        "> 生成脚本：`scripts/rebuild_accident_cases_kb.py`",
        "> 读取方式：`DataLoader.load_public_data(skip_errors=True)` 递归加载公开数据目录内全部可读 `.xlsx`、`.csv`、`.json`。",
        "> 真实性口径：本库不伪造事故。未能用本地字段确认事故/事件发生的记录，只写为隐患闭环、执法处罚或风险组合案例。",
        "",
        "## 1. 元数据与真实性口径",
        "",
        "| 指标 | 值 | 说明 |",
        "| --- | --- | --- |",
        f"| 可读公开数据表 | {readable_tables} | 坏 XLSX 跳过；CSV 重复字段按 DataLoader 追加 `__dupN`。 |",
        f"| 可读数据行数 | {readable_rows} | 含预合并宽表、企业主表、隐患/风险/处罚/文书明细。 |",
        f"| 字段映射记录 | {mapping_rows} | 来自 `reports/public_data_field_mapping.csv`。 |",
        f"| 真实公开数据案例 | {real_selected} | B/C/D 类合计，不含模板。 |",
        f"| 模板/外部待补案例 | {TEMPLATE_COUNT} | E 类，单独统计。 |",
        "",
        "本地风险明细表存在“是否发生事故/是否发生事件/事故概述”字段，但本轮读取到的风险明细中事故/事件发生字段均为否，事故概述为空或“没有”。预合并表存在 `risk_accident_flag`、`risk_with_accident_count`、`work_injury_accident_types` 等事故关联信号，这些字段只能说明企业或风险项存在历史关联/工伤类型信号，缺少事故时间、经过和调查结论，因此不写作真实事故案例。",
        "",
        "## 2. 案例分层统计",
        "",
        "| 层级 | 候选数 | 选入知识库 | 口径 |",
        "| --- | ---: | ---: | --- |",
    ]
    for level, candidates, selected, note in stats_rows:
        lines.append(f"| {md_cell(level)} | {candidates} | {selected} | {md_cell(note)} |")

    lines.extend(
        [
            "",
            "### 2.1 事故/事件字段核验结果",
            "",
            "| 字段组 | 统计 | 处置口径 |",
            "| --- | ---: | --- |",
            f"| 风险明细 `是否发生事故=1` | {accident_stats['risk_rows_accident_true']} | 未生成 A 类事故详案。 |",
            f"| 风险明细 `是否发生事件=1` | {accident_stats['risk_rows_event_true']} | 未生成 A 类事件详案。 |",
            f"| 风险明细有事故概述且非“没有” | {accident_stats['risk_rows_with_accident_summary']} | 未生成 A 类事故详案。 |",
            f"| 预合并表 `risk_accident_flag=1` | {merged_accident_stats['merged_risk_accident_flag_true']} | 仅作为 D 类风险组合触发信号。 |",
            f"| 预合并表 `risk_with_accident_count>0` | {merged_accident_stats['risk_with_accident_count_positive']} | 仅作为事故关联风险数量，不等同事故发生。 |",
            f"| 预合并表 `work_injury_accident_types` 非空 | {merged_accident_stats['work_injury_type_nonempty']} | 可用于事故类型关键词，不等同本次事故案例。 |",
            "",
            "## 3. 数据来源与字段追溯",
            "",
            "| 来源文件 | 用于本库的字段 | 用途 |",
            "| --- | --- | --- |",
        ]
    )
    for source_file, fields in used_source_fields:
        purpose = "事故/风险/隐患/处罚/文书案例证据"
        lines.append(f"| {md_cell(source_file)} | {md_cell(fields)} | {purpose} |")

    lines.extend(
        [
            "",
            "## 4. A 类：真实事故/事件案例",
            "",
            "本轮不生成 A 类真实事故/事件详案。原因是：公开数据中虽有事故/事件字段，但风险明细 `是否发生事故`、`是否发生事件` 均未确认发生，`事故概述` 无有效事故经过；预合并宽表的历史事故关联信号缺少事故时间、调查报告、直接原因和处置记录。后续如果接入事故调查报告或补齐事故经过字段，才可升级为 A 类。",
            "",
            "## 5. B 类：重大隐患与未整改闭环案例",
            "",
        ]
    )
    lines.extend(render_case(case) for case in b_cases)

    lines.extend(["", "## 6. C 类：执法处罚与违法行为案例", ""])
    lines.extend(render_case(case) for case in c_cases)

    lines.extend(["", "## 7. D 类：高风险企业风险组合案例", ""])
    lines.extend(render_case(case) for case in d_cases)

    lines.extend(["", "## 8. E 类：模板/外部待补案例", ""])
    lines.extend(render_templates())

    lines.extend(
        [
            "",
            "## 9. 外部事故报告接口设计（不依赖网络成功）",
            "",
            "后续爬虫或人工导入事故调查报告时，建议按以下字段进入 `accident_case_candidates` 暂存表：`source_url`、`report_title`、`publish_org`、`publish_time`、`accident_time`、`enterprise_name`、`industry`、`accident_type`、`casualties`、`direct_cause`、`indirect_cause`、`emergency_response`、`penalty_or_accountability`、`rectification_measures`、`original_text_sha256`。只有当 `accident_time + enterprise_name + accident_type + cause` 四类字段均可追溯时，才写入 A 类真实事故/事件案例。",
            "",
            "建议种子：应急管理部事故调查报告栏目、江苏省/苏州市应急管理部门事故调查报告栏目、区县政府事故调查信息公开栏目。网络不可用时只保留种子配置，不阻塞本地公开数据重建。",
            "",
            "## 10. 复跑与同步说明",
            "",
            "1. 重建本文件：`venv\\Scripts\\python.exe scripts\\rebuild_accident_cases_kb.py`",
            "2. 同步 AgentFS：`venv\\Scripts\\python.exe scripts\\sync_kb_to_agentfs.py --backup --sync --verify --snapshot`",
            "3. 刷新 VectorStore：同步后重建或刷新向量库，确保 RAG 使用本文件的新标题分块。",
            "",
            "## 11. 质量检查清单",
            "",
            "- 文件存在且非空，并由本脚本整段重建，不保留旧版重复追加段落。",
            "- B/C/D 类案例均写明证据来源文件和字段；E 类模板单独统计并显式标注为模板。",
            "- A 类没有可确认事故/事件详案时保持空置说明，不把隐患、处罚或风险项写成事故。",
            "- Markdown 使用多级标题组织，`VectorStore.split_by_headers` 可按案例分块检索。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_summary(
    tables: dict[str, pd.DataFrame],
    b_cases: list[CaseCard],
    c_cases: list[CaseCard],
    d_cases: list[CaseCard],
    b_stats: dict[str, int],
    c_stats: dict[str, int],
    d_stats: dict[str, int],
    accident_stats: dict[str, int],
    merged_accident_stats: dict[str, int],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "target": str(TARGET_KB),
        "readable_tables": len(tables),
        "readable_rows": sum(len(df) for df in tables.values()),
        "case_counts": {
            "A_real_accident_event": 0,
            "B_hidden_danger_real": len(b_cases),
            "C_penalty_real": len(c_cases),
            "D_risk_combination_real": len(d_cases),
            "E_templates": TEMPLATE_COUNT,
            "real_public_data_cases": len(b_cases) + len(c_cases) + len(d_cases),
        },
        "candidate_stats": {
            "B": b_stats,
            "C": c_stats,
            "D": d_stats,
            "accident_field_audit": accident_stats,
            "merged_accident_signals": merged_accident_stats,
        },
        "cases": {
            "B": [asdict(case) for case in b_cases],
            "C": [asdict(case) for case in c_cases],
            "D": [asdict(case) for case in d_cases],
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(TARGET_KB), help="Markdown output path.")
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="JSON run report path.")
    parser.add_argument("--case-limit", type=int, default=CASE_LIMIT_PER_CLASS, help="Selected cases per B/C/D class.")
    parser.add_argument("--quiet-loader", action="store_true", help="Suppress DataLoader INFO/WARNING logs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.quiet_loader:
        logging.disable(logging.CRITICAL)

    generated_at = datetime.now().isoformat(timespec="seconds")
    inventory = load_inventory()
    loader = DataLoader()
    tables = loader.load_public_data(skip_errors=True, low_memory=False)
    by_credit, by_name = build_profiles(tables)
    risk_history = build_risk_history_map(tables, inventory)

    b_cases, b_stats = build_hidden_cases(tables, inventory, by_credit, by_name, args.case_limit)
    c_cases, c_stats = build_penalty_cases(tables, inventory, by_credit, by_name, args.case_limit)
    d_cases, d_stats, accident_stats = build_risk_cases(
        tables, inventory, by_credit, by_name, risk_history, args.case_limit
    )
    merged_accident_stats = count_merged_accident_signals(tables)

    markdown = render_markdown(
        tables=tables,
        inventory=inventory,
        b_cases=b_cases,
        c_cases=c_cases,
        d_cases=d_cases,
        b_stats=b_stats,
        c_stats=c_stats,
        d_stats=d_stats,
        accident_stats=accident_stats,
        merged_accident_stats=merged_accident_stats,
        generated_at=generated_at,
    )

    output_path = resolve_project_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    summary = build_summary(
        tables,
        b_cases,
        c_cases,
        d_cases,
        b_stats,
        c_stats,
        d_stats,
        accident_stats,
        merged_accident_stats,
        generated_at,
    )
    report_path = resolve_project_path(args.report_json) if args.report_json else None
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary["case_counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
