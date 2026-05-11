"""Rebuild the enterprise execution-condition knowledge base from public data.

The script is intentionally data-driven and idempotent: each run reloads public
tables through DataLoader and overwrites only knowledge_base/企业已具备的执行条件.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.loader import DataLoader  # noqa: E402
from utils.config import get_config, resolve_project_path  # noqa: E402


TARGET_KB = PROJECT_ROOT / "knowledge_base" / "企业已具备的执行条件.md"
INVENTORY_JSON = PROJECT_ROOT / "reports" / "public_data_inventory.json"
FIELD_MAPPING_CSV = PROJECT_ROOT / "reports" / "public_data_field_mapping.csv"
INVENTORY_REPORT = PROJECT_ROOT / "reports" / "public_data_inventory_report.md"

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
    "未填",
    "空",
    "无数据",
    "未知",
}

TRUTHY = {
    "1",
    "1.0",
    "true",
    "yes",
    "y",
    "是",
    "有",
    "正常",
    "已投保",
    "涉及",
    "存在",
}

FALSY = {
    "0",
    "0.0",
    "false",
    "no",
    "n",
    "否",
    "无",
    "不涉及",
    "不存在",
    "未投保",
}


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    category: str
    kind: str
    aliases: tuple[str, ...]
    description: str
    zero_means_no_record: bool = False


@dataclass
class FieldAccumulator:
    values: Counter[str] = field(default_factory=Counter)
    sources: set[str] = field(default_factory=set)
    numeric_max: float | None = None
    numeric_sum_seen: bool = False
    true_seen: bool = False
    false_seen: bool = False

    def add(self, raw_value: Any, source: str, kind: str) -> None:
        value = clean_value(raw_value)
        if value is None:
            return
        self.values[value] += 1
        self.sources.add(source)
        if kind == "number":
            num = parse_number(value)
            if num is not None:
                self.numeric_sum_seen = True
                self.numeric_max = num if self.numeric_max is None else max(self.numeric_max, num)
        if kind == "flag":
            flag = parse_flag(value)
            if flag is True:
                self.true_seen = True
            elif flag is False:
                self.false_seen = True


@dataclass
class EnterpriseRecord:
    key: str
    names: Counter[str] = field(default_factory=Counter)
    credit_codes: Counter[str] = field(default_factory=Counter)
    internal_ids: Counter[str] = field(default_factory=Counter)
    fields: dict[str, FieldAccumulator] = field(default_factory=lambda: defaultdict(FieldAccumulator))
    row_sources: Counter[str] = field(default_factory=Counter)

    def primary_name(self) -> str:
        return most_common(self.names) or "未知企业"

    def primary_credit_code(self) -> str:
        return most_common(self.credit_codes) or "未知"

    def primary_internal_id(self) -> str:
        return most_common(self.internal_ids) or "未知"


FIELD_DEFS: list[FieldDef] = [
    FieldDef(
        "industry_class",
        "行业分类门类",
        "基础信息",
        "text",
        (
            "indus_type_class",
            "INDUS_TYPE_CLASS",
            "INDUSTRY_CATEGORY",
            "SUPERVISION_INDUSTRY_TYPES",
            "国民经济门类",
            "所属行业",
            "行业类别",
        ),
        "企业国民经济行业门类或监管行业大类，优先采用企业主表与预合并表。",
    ),
    FieldDef(
        "industry_large",
        "行业大类",
        "基础信息",
        "text",
        (
            "indus_type_large",
            "INDUS_TYPE_LAGRE",
            "INDUS_TYPE_LAGRE_NAME",
            "INDUSTRY_TYPE_BIG",
            "JGHYDL",
            "SSJGHYDL",
            "国民经济大类",
        ),
        "企业国民经济行业大类。",
    ),
    FieldDef(
        "industry_middle",
        "行业中类",
        "基础信息",
        "text",
        (
            "indus_type_middle",
            "INDUS_TYPE_MIDDLE",
            "INDUS_TYPE_MIDDLE_NAME",
            "INDUSTRY_TYPE_MIDDLE",
            "国民经济中类",
        ),
        "企业国民经济行业中类。",
    ),
    FieldDef(
        "industry_small",
        "行业小类",
        "基础信息",
        "text",
        (
            "indus_type_small",
            "INDUS_TYPE_SMALL",
            "INDUS_TYPE_SMALL_NAME",
            "INDUSTRY_TYPE_SMALL",
            "JGHYXL",
            "SSJGHYXL",
            "国民经济小类",
        ),
        "企业国民经济行业小类。",
    ),
    FieldDef(
        "supervision_category",
        "监管类别",
        "基础信息",
        "text",
        (
            "supervision_large",
            "SUPERVISION_LARGE",
            "SUPERVISION_NAME",
            "SUPERVISION_CORP_LARGE",
            "SUPERVISION_INDUSTRY_TYPE_NAMES",
            "COMPANY_SUPERVISION_TYPES",
            "监管行业大类",
            "行业监管大类",
            "监管分类",
        ),
        "监管部门或系统划分的行业监管类别。",
    ),
    FieldDef(
        "address",
        "地址",
        "基础信息",
        "text",
        (
            "address",
            "formatted_address",
            "busi_addr",
            "cf_formatted_address",
            "BUSINESS_ADDRESS_FULL",
            "BUSINESS_ADDRESS",
            "REGISTER_ADDRESS",
            "RIGISTER_ADDRESS",
            "ADDRESS",
            "ADDR",
            "BUSI_ADDR_NAME",
            "注册地址",
            "经营地址",
            "详细地址",
        ),
        "企业注册地址、经营地址或标准化地址。",
    ),
    FieldDef(
        "longitude",
        "经度",
        "基础信息",
        "number",
        ("dir_longitude", "addr_longitude", "QYWZJD", "LONGITUDE", "longitude", "经度"),
        "企业地址经度。",
    ),
    FieldDef(
        "latitude",
        "纬度",
        "基础信息",
        "number",
        ("dir_latitude", "addr_latitude", "QYWZWD", "LATITUDE", "latitude", "纬度"),
        "企业地址纬度。",
    ),
    FieldDef(
        "production_status",
        "生产状态",
        "基础信息",
        "text",
        ("production_status", "rh_production_status", "PRODUCTION_STATUS", "生产状态"),
        "企业生产状态，含停产记录表与风险历史中的状态字段。",
    ),
    FieldDef(
        "business_status",
        "经营状态",
        "基础信息",
        "text",
        ("business_status", "company_operation_status", "COMPANY_OPERATION_STATUS", "QYZT", "经营状态"),
        "企业工商或系统经营状态。",
    ),
    FieldDef(
        "latest_risk_level",
        "最新风险等级",
        "风险计数",
        "text",
        ("new_level", "latest_risk_level", "last_level", "NEW_LEVEL", "LAST_LEVEL", "风险等级", "最新风险等级"),
        "模型或报送系统形成的企业最新风险等级。",
    ),
    FieldDef(
        "staff_num",
        "职工人数",
        "人员资质",
        "number",
        ("staff_num", "employee_count", "EMPLOYEE_COUNT", "企业职工总人数", "职工人数", "员工人数"),
        "企业职工或从业人员总数。",
    ),
    FieldDef(
        "safety_num",
        "安全管理人员数量",
        "人员资质",
        "number",
        (
            "safety_num",
            "safety_manager_count",
            "SAFETY_PRODUCT_MANAGER_COUNT",
            "SAFETY_MANAGE_PERSON",
            "企业安全管理人员数量",
            "安全管理人员数量",
        ),
        "安全生产管理人员总量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "fulltime_safety_num",
        "专职安全员数量",
        "人员资质",
        "number",
        ("fulltime_safety_num", "专职安全生产管理人员数", "专职安全员数量"),
        "专职安全生产管理人员数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "parttime_safety_num",
        "兼职安全员数量",
        "人员资质",
        "number",
        ("parttime_safety_num", "SAFETY_MANAGE_TEMP_PERSON_COUNT", "兼职安全生产管理人员数", "兼职安全员数量"),
        "兼职安全生产管理人员数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "fulltime_cert_num",
        "专职安全员持证人数",
        "人员资质",
        "number",
        ("fulltime_cert_num", "专职安全生产管理人员持证人数", "专职持证人数"),
        "专职安全管理人员持证人数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "parttime_cert_num",
        "兼职安全员持证人数",
        "人员资质",
        "number",
        ("parttime_cert_num", "兼职安全生产管理人员持证人数", "兼职持证人数"),
        "兼职安全管理人员持证人数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "special_work_cert_num",
        "特种作业持证人数",
        "人员资质",
        "number",
        ("special_work_cert_num", "TZZYRYSL", "特种作业人员数", "特种作业持证人员数", "特种作业持证人数"),
        "特种作业人员持证数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "is_explosive_dust",
        "粉尘涉爆标识",
        "粉尘涉爆",
        "flag",
        ("is_explosive_dust", "IS_EXPLOSIVE_DUST_COMPANY", "risk_dust_flag", "粉尘涉爆企业", "是否涉爆粉尘"),
        "企业是否被标识为粉尘涉爆或粉尘重点风险企业。",
    ),
    FieldDef(
        "dust_type",
        "粉尘类型",
        "粉尘涉爆",
        "text",
        ("dust_type", "DUST_TYPE", "DUST_TYPE_B", "粉尘类型"),
        "涉爆粉尘类型。",
    ),
    FieldDef(
        "dust_dry_system_num",
        "干式除尘系统数量",
        "粉尘涉爆",
        "number",
        ("dust_ganshi_num", "DUST_GANSHI_NUM", "集中除尘系统干式数量", "干式除尘系统数量"),
        "粉尘场景干式集中除尘系统数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "dust_wet_system_num",
        "湿式除尘系统数量",
        "粉尘涉爆",
        "number",
        ("dust_shishi_num", "DUST_SHISHI_NUM", "集中除尘系统湿式数量", "湿式除尘系统数量"),
        "粉尘场景湿式集中除尘系统数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "dust_work_num",
        "涉粉作业人数/点位",
        "粉尘涉爆",
        "number",
        ("dust_work_num", "DUST_WORK_NUM", "涉粉作业人数", "涉粉作业点位"),
        "粉尘作业人数或作业点位数量，按源字段原始口径保留。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "dust_clear_count",
        "除尘作业记录数",
        "粉尘涉爆",
        "number",
        ("dust_clear_count", "CLEAR_TIME", "除尘作业次数", "除尘记录数"),
        "除尘清扫记录数量；对清扫记录明细按企业聚合计数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "dust_last_clear_time",
        "最近除尘时间",
        "粉尘涉爆",
        "date",
        ("dust_last_clear_time", "CLEAR_TIME", "最近除尘时间", "除尘时间"),
        "最近一次除尘清扫记录时间。",
    ),
    FieldDef(
        "is_metal_smelter",
        "冶金/金属冶炼标识",
        "冶金",
        "flag",
        ("is_metal_smelter", "IS_METAL_SMELTER_COMPANY", "risk_metal_flag", "risk_fe_flag", "risk_al_flag", "金属冶炼企业"),
        "企业是否属于金属冶炼、钢铁、有色等冶金高风险场景。",
    ),
    FieldDef(
        "blast_furnace_num",
        "高炉数量",
        "冶金",
        "number",
        ("gaolu_num", "GAOLU_NUM", "高炉数量", "高炉数"),
        "高炉数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "converter_num",
        "转炉数量",
        "冶金",
        "number",
        ("zhuanlu_num", "ZHUANLU_NUM", "转炉数量", "转炉数"),
        "转炉数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "electric_furnace_num",
        "电炉数量",
        "冶金",
        "number",
        ("dianlu_num", "DIANLU_NUM", "电炉数量", "电炉数"),
        "电炉数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "gas_cabinet_num",
        "煤气柜数量",
        "冶金",
        "number",
        ("meiqi_num", "MEIQI_NUM", "煤气柜数量", "煤气柜数"),
        "冶金煤气柜数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "ammonia_tank_num",
        "氨罐数量",
        "危化品",
        "number",
        ("anguan_num", "ANGUAN_NUM", "氨罐数量", "氨罐数"),
        "氨罐数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "deep_well_casting_num",
        "深井铸造系统数量",
        "冶金",
        "number",
        ("SJJZXT_NUM", "深井铸造系统数量", "深井铸造"),
        "深井铸造系统数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "wire_rope_lift_num",
        "钢丝绳式提升装置数量",
        "冶金",
        "number",
        ("GSSSTSZZ_NUM", "钢丝绳式提升装置数量", "钢丝绳提升装置"),
        "钢丝绳式提升装置数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "hydraulic_lift_num",
        "液压式提升装置数量",
        "冶金",
        "number",
        ("YYSTSZZ_NUM", "液压式提升装置数量", "液压提升装置"),
        "液压式提升装置数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "interlock_device",
        "事故联锁装置记录",
        "冶金",
        "text",
        ("RLLSGLSZZ_INFO", "LCJZZSGLSZZ_INFO", "JSYLYJ", "JSYLLJG", "事故联锁装置", "联锁装置"),
        "熔炼炉、流槽或铸造系统事故联锁装置记录。",
    ),
    FieldDef(
        "dangerous_chemical_enterprise",
        "危化品企业标识",
        "危化品",
        "flag",
        (
            "dangerous_chemical_enterprise",
            "DANGEROUS_CHEMICAL_ENTERPRISE",
            "risk_whp_flag",
            "risk_whp_use_flag",
            "WHPQYKZLX",
            "危化品企业",
            "危险化学品企业",
        ),
        "企业是否属于危化品生产、经营或使用相关场景。",
    ),
    FieldDef(
        "is_ammonia_refrigerating",
        "涉氨制冷标识",
        "危化品",
        "flag",
        ("is_ammonia_refrigerating", "IS_AMMONIA_REFRIGERATING_COMPANY", "涉氨制冷", "氨制冷企业"),
        "企业是否属于涉氨制冷场景。",
    ),
    FieldDef(
        "is_major_hazards",
        "重大危险源标识",
        "危化品",
        "flag",
        (
            "is_major_hazards",
            "is_major_hazard",
            "isof_major_hazard",
            "IS_MAJOR_HAZARDS_COMPANY",
            "ISOF_MAJOR_HAZARD_SOURCES",
            "重大危险源",
        ),
        "企业是否涉及重大危险源。",
    ),
    FieldDef(
        "is_finite_space",
        "有限空间标识",
        "有限空间",
        "flag",
        (
            "is_finite_space",
            "IS_FINITE_SPACE_COMPANY",
            "confined_spaces_enterprise",
            "CONFINED_SPACES_ENTERPRISE",
            "risk_finite10_flag",
            "risk_finite_key_flag",
            "有限空间企业",
        ),
        "企业是否存在有限空间作业或被列为有限空间重点企业。",
    ),
    FieldDef(
        "risk_company_flag",
        "风险重点企业",
        "风险计数",
        "flag",
        ("risk_company_flag", "ZDYHYFLAG", "风险重点企业", "重点企业标识"),
        "企业是否被标识为风险重点企业。",
    ),
    FieldDef(
        "risk_company_key_flag",
        "关键风险企业",
        "风险计数",
        "flag",
        ("risk_company_key_flag", "关键风险企业", "重点风险企业"),
        "企业是否被标识为关键风险企业。",
    ),
    FieldDef(
        "risk_accident_flag",
        "事故关联企业",
        "风险计数",
        "flag",
        ("risk_accident_flag", "事故关联企业", "曾发生事故"),
        "企业是否存在事故关联标识。",
    ),
    FieldDef(
        "risk_total_count",
        "风险总数",
        "风险计数",
        "number",
        ("risk_total_count", "RISK_ITEM_NUM", "风险总数", "风险项数量"),
        "企业风险点或风险项总数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "risk_level_a_count",
        "A级风险数",
        "风险计数",
        "number",
        ("risk_level_a_count", "A级风险数", "A 级风险数"),
        "A级风险数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "risk_level_b_count",
        "B级风险数",
        "风险计数",
        "number",
        ("risk_level_b_count", "B级风险数", "B 级风险数"),
        "B级风险数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "risk_level_c_count",
        "C级风险数",
        "风险计数",
        "number",
        ("risk_level_c_count", "C级风险数", "C 级风险数"),
        "C级风险数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "risk_level_d_count",
        "D级风险数",
        "风险计数",
        "number",
        ("risk_level_d_count", "D级风险数", "D 级风险数"),
        "D级风险数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "risk_with_accident_count",
        "事故关联风险数",
        "风险计数",
        "number",
        ("risk_with_accident_count", "事故关联风险数", "事故风险数"),
        "与事故或事故类型有关联的风险数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "check_total_count",
        "检查次数",
        "检查执法",
        "number",
        ("check_total_count", "aczf_examine_cnt", "EXAMINE_CNT", "检查次数", "检查总次数"),
        "企业检查总次数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "check_trouble_count",
        "检查发现问题次数",
        "检查执法",
        "number",
        ("check_trouble_count", "检查发现问题次数"),
        "检查中发现问题或隐患的次数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "trouble_total_count",
        "隐患数量",
        "检查执法",
        "number",
        ("trouble_total_count", "隐患总数", "隐患数量"),
        "企业隐患总数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "trouble_level_2_count",
        "重大隐患数量",
        "检查执法",
        "number",
        ("trouble_level_2_count", "重大隐患数", "重大隐患数量"),
        "重大隐患数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "trouble_unrectified_count",
        "未整改隐患数量",
        "检查执法",
        "number",
        ("trouble_unrectified_count", "未整改隐患数", "未整改隐患数量"),
        "尚未整改隐患数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "writ_total_count",
        "执法文书数量",
        "检查执法",
        "number",
        ("writ_total_count", "执法文书数量", "文书总数"),
        "企业关联执法文书数量。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "total_penalty_money",
        "处罚金额合计",
        "检查执法",
        "number",
        ("total_penalty_money", "处罚金额", "罚款金额", "处罚金额合计"),
        "企业关联行政处罚金额合计。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "insurance_flag",
        "安全生产责任保险",
        "管理条件",
        "flag",
        ("if_insure", "保险", "是否投保", "安全生产责任保险"),
        "企业是否投保安全生产责任保险。",
    ),
    FieldDef(
        "insurance_amount",
        "保险金额",
        "管理条件",
        "number",
        ("insure_money", "insurance_amount", "保险金额", "投保金额"),
        "安全生产责任保险金额。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "insured_num",
        "投保人数",
        "管理条件",
        "number",
        ("insure_num", "insured_num", "投保人数"),
        "安全生产责任保险覆盖人数。",
        zero_means_no_record=True,
    ),
    FieldDef(
        "safety_standardization",
        "安全生产标准化",
        "管理条件",
        "text",
        ("safety_build", "aqscbzhdj", "AQSCBZHDJ", "STANDARD_LEVEL", "安全生产标准化", "标准化等级"),
        "企业安全生产标准化建设或等级情况。",
    ),
    FieldDef(
        "comply_formality_flag",
        "三同时手续",
        "管理条件",
        "flag",
        ("if_comply_formality", "ISOF_HEALTHY_THREE", "ISOF_SAFETY_EQUIPMENT_THREE", "三同时手续", "是否履行三同时手续"),
        "安全设施、职业健康等三同时手续履行情况。",
    ),
    FieldDef(
        "safety_dept",
        "安全管理机构",
        "管理条件",
        "text",
        ("safety_dept", "AQJGSZQK", "AQSCGLJG", "isof_safety_institution", "ISOF_SAFETY_INSTITUTION", "安全管理机构"),
        "企业安全管理机构或部门设置情况。",
    ),
]

FIELD_BY_KEY = {item.key: item for item in FIELD_DEFS}

NAME_ALIASES = (
    "enterprise_name",
    "ENTERPRISE_NAME",
    "COMPANY_NAME",
    "企业名称",
    "单位名称",
    "当事人名称",
    "被处罚单位",
    "检查对象名称",
)

CREDIT_ALIASES = (
    "enterprise_id",
    "UUIT_NO",
    "CREDIT_NO",
    "COMPANY_CODE",
    "REGISTERED_NO",
    "ENT_CODE",
    "ZZJGDM",
    "COMPANY_ORG_NO",
    "统一社会信用代码",
    "社会统一信用代码",
    "统一信用代码",
    "统一社会信用代码 主键",
    "社会统一信用代码 主键",
)

INTERNAL_ID_ALIASES = (
    "ENTERPRISE_ID",
    "企业ID",
    "企业主键",
    "REPORT_HISTORY_ID",
    "ENTERPRISE_HISTORY_ID",
)


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat") and not isinstance(value, str):
        text = value.isoformat()
    else:
        text = str(value)
    text = text.replace("\ufeff", "").strip()
    if text.endswith(".0") and re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if text.lower() in MISSING_VALUES:
        return None
    return text


def normalize_column_name(name: Any) -> str:
    return str(name).replace("\ufeff", "").strip().lower()


def normalize_entity_name(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", "", value)
    text = text.replace("（", "(").replace("）", ")")
    return text.lower() or None


def normalize_credit(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"[^0-9A-Za-z]", "", value).upper()
    if len(text) < 6:
        return None
    return text


def parse_number(value: Any) -> float | None:
    text = clean_value(value)
    if text is None:
        return None
    if text in TRUTHY:
        return 1.0
    if text in FALSY:
        return 0.0
    text = text.replace(",", "").replace("，", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
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
    normalized = text.strip().lower()
    if normalized in TRUTHY:
        return True
    if normalized in FALSY:
        return False
    num = parse_number(text)
    if num is not None:
        return num > 0
    return None


def format_number(value: float | None) -> str:
    if value is None:
        return "未知"
    if abs(value - int(value)) < 1e-9:
        return f"{int(value)}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def most_common(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def markdown_escape(value: Any) -> str:
    text = str(value)
    text = text.replace("\n", "；").replace("\r", "；").replace("|", "\\|")
    return text


def markdown_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    lines = [
        "| " + " | ".join(markdown_escape(item) for item in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = list(row)
        if len(values) != len(headers):
            raise ValueError(f"Markdown row length mismatch: {values}")
        lines.append("| " + " | ".join(markdown_escape(item) for item in values) + " |")
    return "\n".join(lines)


def compact_list(items: Iterable[str], limit: int = 4) -> str:
    unique = []
    for item in items:
        if item and item not in unique:
            unique.append(item)
    if not unique:
        return "未知"
    if len(unique) <= limit:
        return "；".join(unique)
    return "；".join(unique[:limit]) + f"；等 {len(unique)} 项"


def source_key_from_inventory_path(source_file: str) -> str:
    path = source_file.replace("\\", "/")
    prefix = "公开数据/公开数据/"
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return str(Path(path).with_suffix("")).replace("\\", "/")


def read_inventory() -> dict[str, dict[str, Any]]:
    if not INVENTORY_JSON.exists():
        return {}
    data = json.loads(INVENTORY_JSON.read_text(encoding="utf-8-sig"))
    records = {}
    for item in data.get("table_records", []):
        key = source_key_from_inventory_path(item.get("source_file", ""))
        records[key] = item
    return records


def read_field_mapping() -> pd.DataFrame:
    if not FIELD_MAPPING_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(FIELD_MAPPING_CSV, encoding="utf-8-sig")


def first_matching_column(columns: Iterable[str], aliases: Iterable[str]) -> str | None:
    by_norm = {normalize_column_name(col): col for col in columns}
    for alias in aliases:
        found = by_norm.get(normalize_column_name(alias))
        if found is not None:
            return found
    return None


def all_matching_columns(columns: Iterable[str], aliases: Iterable[str]) -> list[str]:
    by_norm = {normalize_column_name(col): col for col in columns}
    found = []
    for alias in aliases:
        col = by_norm.get(normalize_column_name(alias))
        if col is not None and col not in found:
            found.append(col)
    return found


def table_kind(key: str) -> str:
    lowered = key.lower()
    if "dust_clear_record" in lowered:
        return "dust_clear_record"
    if "routine_check_log" in lowered:
        return "check_log"
    if "routine_check_trouble" in lowered:
        return "check_trouble"
    if "risk_history" in lowered:
        return "risk_history"
    if "risk_target" in lowered:
        return "risk_target"
    if "writ" in lowered:
        return "writ"
    if "penalty" in lowered or "discretion" in lowered:
        return "penalty"
    return "generic"


def get_or_create_record(
    records: dict[str, EnterpriseRecord],
    name_to_key: dict[str, str],
    credit_to_key: dict[str, str],
    name: str | None,
    credit: str | None,
    internal_id: str | None,
) -> EnterpriseRecord | None:
    normalized_credit = normalize_credit(credit)
    normalized_name = normalize_entity_name(name)

    key = None
    if normalized_credit and normalized_credit in credit_to_key:
        key = credit_to_key[normalized_credit]
    elif normalized_name and normalized_name in name_to_key:
        key = name_to_key[normalized_name]
    elif normalized_credit:
        key = f"C:{normalized_credit}"
    elif normalized_name:
        key = f"N:{normalized_name}"
    elif internal_id:
        key = f"I:{internal_id}"

    if key is None:
        return None

    record = records.get(key)
    if record is None:
        record = EnterpriseRecord(key=key)
        records[key] = record

    if normalized_credit:
        credit_to_key[normalized_credit] = key
        record.credit_codes[normalized_credit] += 1
    if name:
        record.names[name] += 1
        if normalized_name:
            name_to_key[normalized_name] = key
    if internal_id:
        record.internal_ids[internal_id] += 1

    return record


def aggregate_tables(tables: dict[str, pd.DataFrame]) -> tuple[dict[str, EnterpriseRecord], dict[str, Any], list[dict[str, Any]]]:
    records: dict[str, EnterpriseRecord] = {}
    name_to_key: dict[str, str] = {}
    credit_to_key: dict[str, str] = {}
    field_stats: dict[str, dict[str, Any]] = {
        item.key: {"rows": 0, "non_missing": 0, "source_fields": set(), "tables": set()}
        for item in FIELD_DEFS
    }
    source_summaries: list[dict[str, Any]] = []

    for key, df in tables.items():
        if df is None or df.empty:
            source_summaries.append(
                {"key": key, "rows": 0, "columns": 0, "fields": [], "categories": set(), "matched": []}
            )
            continue

        columns = [str(col) for col in df.columns]
        name_col = first_matching_column(columns, NAME_ALIASES)
        credit_col = first_matching_column(columns, CREDIT_ALIASES)
        internal_col = first_matching_column(columns, INTERNAL_ID_ALIASES)
        matched_cols: dict[str, str] = {}
        categories: set[str] = set()

        for item in FIELD_DEFS:
            col = first_matching_column(columns, item.aliases)
            if col is None:
                continue
            matched_cols[item.key] = col
            categories.add(item.category)
            non_missing = int(df[col].map(lambda v: clean_value(v) is not None).sum())
            field_stats[item.key]["rows"] += int(len(df))
            field_stats[item.key]["non_missing"] += non_missing
            field_stats[item.key]["source_fields"].add(f"{key}:{col}")
            field_stats[item.key]["tables"].add(key)

        source_summaries.append(
            {
                "key": key,
                "rows": int(len(df)),
                "columns": int(len(df.columns)),
                "fields": columns,
                "categories": categories,
                "matched": [f"{FIELD_BY_KEY[field].label}={col}" for field, col in matched_cols.items()],
            }
        )

        useful_cols = sorted(
            {
                col
                for col in [name_col, credit_col, internal_col, *matched_cols.values()]
                if col is not None
            }
        )
        if not useful_cols:
            continue

        sub = df[useful_cols].copy()
        kind = table_kind(key)

        if kind == "dust_clear_record":
            aggregate_dust_clear_records(key, sub, name_col, credit_col, internal_col, records, name_to_key, credit_to_key)
            continue

        for row in sub.to_dict("records"):
            name = clean_value(row.get(name_col)) if name_col else None
            credit = clean_value(row.get(credit_col)) if credit_col else None
            internal_id = clean_value(row.get(internal_col)) if internal_col else None
            record = get_or_create_record(records, name_to_key, credit_to_key, name, credit, internal_id)
            if record is None:
                continue
            record.row_sources[key] += 1
            for field_key, col in matched_cols.items():
                item = FIELD_BY_KEY[field_key]
                record.fields[field_key].add(row.get(col), f"{key}:{col}", item.kind)

    return records, field_stats, source_summaries


def aggregate_dust_clear_records(
    key: str,
    df: pd.DataFrame,
    name_col: str | None,
    credit_col: str | None,
    internal_col: str | None,
    records: dict[str, EnterpriseRecord],
    name_to_key: dict[str, str],
    credit_to_key: dict[str, str],
) -> None:
    if df.empty:
        return
    clear_col = first_matching_column(df.columns, ("CLEAR_TIME", "dust_last_clear_time", "除尘时间"))
    groups: dict[str, dict[str, Any]] = {}
    for row in df.to_dict("records"):
        name = clean_value(row.get(name_col)) if name_col else None
        credit = clean_value(row.get(credit_col)) if credit_col else None
        internal_id = clean_value(row.get(internal_col)) if internal_col else None
        record = get_or_create_record(records, name_to_key, credit_to_key, name, credit, internal_id)
        if record is None:
            continue
        record.row_sources[key] += 1
        group = groups.setdefault(record.key, {"record": record, "count": 0, "latest": None})
        group["count"] += 1
        clear_time = clean_value(row.get(clear_col)) if clear_col else None
        if clear_time and (group["latest"] is None or clear_time > group["latest"]):
            group["latest"] = clear_time

    for group in groups.values():
        record = group["record"]
        record.fields["dust_clear_count"].add(group["count"], f"{key}:CLEAR_TIME", "number")
        if group["latest"]:
            record.fields["dust_last_clear_time"].add(group["latest"], f"{key}:CLEAR_TIME", "date")


def display_value(record: EnterpriseRecord, field_key: str) -> str:
    item = FIELD_BY_KEY[field_key]
    acc = record.fields.get(field_key)
    if not acc or not acc.values:
        return "未知"
    if item.kind == "flag":
        if acc.true_seen:
            return "是"
        if acc.false_seen:
            return "无记录"
        return most_common(acc.values) or "未知"
    if item.kind == "number":
        if acc.numeric_max is not None:
            if item.zero_means_no_record and abs(acc.numeric_max) < 1e-12:
                return "无记录"
            return format_number(acc.numeric_max)
        return most_common(acc.values) or "未知"
    return most_common(acc.values) or "未知"


def numeric_value(record: EnterpriseRecord, field_key: str) -> float:
    acc = record.fields.get(field_key)
    if not acc or acc.numeric_max is None:
        return 0.0
    return acc.numeric_max


def flag_value(record: EnterpriseRecord, field_key: str) -> bool:
    acc = record.fields.get(field_key)
    return bool(acc and acc.true_seen)


def field_sources(record: EnterpriseRecord, field_keys: Iterable[str], limit: int = 4) -> str:
    sources: list[str] = []
    for key in field_keys:
        acc = record.fields.get(key)
        if not acc:
            continue
        sources.extend(sorted(acc.sources))
    return compact_list(sources, limit=limit)


def scenario_score(record: EnterpriseRecord, scenario: str) -> float:
    if scenario == "dust":
        return (
            12 * flag_value(record, "is_explosive_dust")
            + 5 * min(numeric_value(record, "dust_dry_system_num"), 5)
            + 4 * min(numeric_value(record, "dust_wet_system_num"), 5)
            + 2 * min(numeric_value(record, "dust_work_num"), 50)
            + 2 * min(numeric_value(record, "dust_clear_count"), 20)
            + high_risk_score(record) / 10
        )
    if scenario == "metallurgy":
        return (
            12 * flag_value(record, "is_metal_smelter")
            + 8 * min(numeric_value(record, "blast_furnace_num"), 5)
            + 6 * min(numeric_value(record, "converter_num"), 5)
            + 5 * min(numeric_value(record, "electric_furnace_num"), 5)
            + 5 * min(numeric_value(record, "gas_cabinet_num"), 5)
            + 4 * min(numeric_value(record, "deep_well_casting_num"), 5)
            + high_risk_score(record) / 10
        )
    if scenario == "hazchem":
        return (
            12 * flag_value(record, "dangerous_chemical_enterprise")
            + 8 * flag_value(record, "is_ammonia_refrigerating")
            + 12 * flag_value(record, "is_major_hazards")
            + 5 * min(numeric_value(record, "ammonia_tank_num"), 5)
            + high_risk_score(record) / 10
        )
    if scenario == "finite":
        return 12 * flag_value(record, "is_finite_space") + high_risk_score(record) / 10
    return high_risk_score(record)


def scenario_applicable(record: EnterpriseRecord, scenario: str) -> bool:
    if scenario == "dust":
        return (
            flag_value(record, "is_explosive_dust")
            or numeric_value(record, "dust_dry_system_num") > 0
            or numeric_value(record, "dust_wet_system_num") > 0
            or numeric_value(record, "dust_clear_count") > 0
            or display_value(record, "dust_type") not in {"未知", "无记录"}
        )
    if scenario == "metallurgy":
        return (
            flag_value(record, "is_metal_smelter")
            or any(
                numeric_value(record, key) > 0
                for key in (
                    "blast_furnace_num",
                    "converter_num",
                    "electric_furnace_num",
                    "gas_cabinet_num",
                    "deep_well_casting_num",
                    "wire_rope_lift_num",
                    "hydraulic_lift_num",
                )
            )
        )
    if scenario == "hazchem":
        return (
            flag_value(record, "dangerous_chemical_enterprise")
            or flag_value(record, "is_ammonia_refrigerating")
            or flag_value(record, "is_major_hazards")
            or numeric_value(record, "ammonia_tank_num") > 0
        )
    if scenario == "finite":
        return flag_value(record, "is_finite_space")
    return True


def risk_level_points(value: str) -> float:
    text = (value or "").upper()
    if text.startswith("A") or "重大" in text or "红" in text:
        return 40
    if text.startswith("B") or "较大" in text or "橙" in text:
        return 25
    if text.startswith("C") or "一般" in text or "黄" in text:
        return 12
    if text.startswith("D") or "低" in text or "蓝" in text:
        return 4
    return 0


def high_risk_score(record: EnterpriseRecord) -> float:
    score = risk_level_points(display_value(record, "latest_risk_level"))
    score += min(numeric_value(record, "risk_level_a_count") * 10, 50)
    score += min(numeric_value(record, "risk_level_b_count") * 5, 40)
    score += min(numeric_value(record, "risk_total_count") * 0.8, 40)
    score += min(numeric_value(record, "risk_with_accident_count") * 8, 40)
    score += min(numeric_value(record, "trouble_level_2_count") * 12, 60)
    score += min(numeric_value(record, "trouble_unrectified_count") * 4, 50)
    score += min(numeric_value(record, "check_trouble_count") * 1.5, 40)
    score += min(numeric_value(record, "writ_total_count") * 2, 35)
    penalty = numeric_value(record, "total_penalty_money")
    if penalty > 0:
        score += min(math.log10(penalty + 1) * 6, 40)
    score += 20 * flag_value(record, "risk_company_key_flag")
    score += 12 * flag_value(record, "risk_company_flag")
    score += 20 * flag_value(record, "risk_accident_flag")
    score += 15 * flag_value(record, "is_major_hazards")
    score += 8 * flag_value(record, "dangerous_chemical_enterprise")
    score += 8 * flag_value(record, "is_explosive_dust")
    score += 8 * flag_value(record, "is_metal_smelter")
    score += 6 * flag_value(record, "is_finite_space")
    return round(score, 1)


def evidence_summary(record: EnterpriseRecord) -> str:
    items = []
    for key in (
        "latest_risk_level",
        "risk_level_a_count",
        "risk_with_accident_count",
        "trouble_level_2_count",
        "trouble_unrectified_count",
        "writ_total_count",
        "total_penalty_money",
    ):
        value = display_value(record, key)
        if value not in {"未知", "无记录"}:
            items.append(f"{FIELD_BY_KEY[key].label}={value}")
    for key in (
        "risk_company_key_flag",
        "risk_company_flag",
        "risk_accident_flag",
        "is_major_hazards",
        "dangerous_chemical_enterprise",
        "is_explosive_dust",
        "is_metal_smelter",
        "is_finite_space",
    ):
        if flag_value(record, key):
            items.append(FIELD_BY_KEY[key].label)
    return compact_list(items, limit=6)


def build_source_table(source_summaries: list[dict[str, Any]], inventory: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for item in sorted(source_summaries, key=lambda x: x["key"]):
        inv = inventory.get(item["key"], {})
        source_file = inv.get("source_file") or item["key"]
        fmt = inv.get("format") or "未知"
        rows.append(
            [
                source_file,
                fmt,
                item["rows"],
                item["columns"],
                compact_list(sorted(item["categories"]), limit=5),
                compact_list(item["matched"], limit=5),
            ]
        )
    return rows


def field_coverage_rows(field_stats: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in FIELD_DEFS:
        stat = field_stats[item.key]
        rows_seen = stat["rows"]
        non_missing = stat["non_missing"]
        if rows_seen:
            missing_rate = 1 - non_missing / rows_seen
            coverage = f"字段行数 {rows_seen}，非空 {non_missing}，缺失率 {missing_rate:.1%}"
        else:
            coverage = "未知：未在可读表中匹配到字段"
        rows.append(
            [
                item.label,
                item.category,
                item.description,
                compact_list(sorted(stat["source_fields"]), limit=4),
                coverage,
            ]
        )
    return rows


def missing_rows(field_stats: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in FIELD_DEFS:
        stat = field_stats[item.key]
        rows_seen = stat["rows"]
        non_missing = stat["non_missing"]
        if not rows_seen:
            rows.append(
                [
                    item.label,
                    item.category,
                    "未知",
                    "数据源未发现可直接映射字段",
                    "补采企业统一口径字段，并纳入 public_data_field_mapping.csv。",
                ]
            )
            continue
        missing_rate = 1 - non_missing / rows_seen
        if missing_rate >= 0.8:
            rows.append(
                [
                    item.label,
                    item.category,
                    f"{missing_rate:.1%}",
                    "字段存在但多数记录为空",
                    "优先补齐重点企业、A级/B级风险企业及场景适用企业记录。",
                ]
            )
    return rows[:40]


def top_records(records: Iterable[EnterpriseRecord], scenario: str | None = None, limit: int = 20) -> list[EnterpriseRecord]:
    selected = [
        rec
        for rec in records
        if rec.primary_name() != "未知企业" and (scenario is None or scenario_applicable(rec, scenario))
    ]
    return sorted(
        selected,
        key=lambda rec: scenario_score(rec, scenario or "general"),
        reverse=True,
    )[:limit]


def top_industry_rows(records: Iterable[EnterpriseRecord]) -> list[list[Any]]:
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "dust": 0, "metal": 0, "hazchem": 0, "finite": 0, "score": 0.0})
    for rec in records:
        category = display_value(rec, "supervision_category")
        if category == "未知":
            category = display_value(rec, "industry_large")
        bucket = buckets[category]
        bucket["count"] += 1
        bucket["dust"] += int(scenario_applicable(rec, "dust"))
        bucket["metal"] += int(scenario_applicable(rec, "metallurgy"))
        bucket["hazchem"] += int(scenario_applicable(rec, "hazchem"))
        bucket["finite"] += int(scenario_applicable(rec, "finite"))
        bucket["score"] += high_risk_score(rec)
    rows = []
    for category, data in sorted(buckets.items(), key=lambda x: x[1]["count"], reverse=True)[:15]:
        avg_score = data["score"] / data["count"] if data["count"] else 0
        rows.append(
            [
                category,
                data["count"],
                data["dust"],
                data["metal"],
                data["hazchem"],
                data["finite"],
                f"{avg_score:.1f}",
            ]
        )
    return rows


def source_metric_rows(records: dict[str, EnterpriseRecord], source_summaries: list[dict[str, Any]], inventory: dict[str, dict[str, Any]], mapping: pd.DataFrame) -> list[list[Any]]:
    readable_tables = len(source_summaries)
    readable_rows = sum(item["rows"] for item in source_summaries)
    readable_columns = sum(item["columns"] for item in source_summaries)
    inventory_total = len(inventory)
    mapping_rows = len(mapping) if not mapping.empty else 0
    return [
        ["可读表数量", readable_tables, "DataLoader.load_public_data(skip_errors=True)", "坏 XLSX 跳过；CSV 重复字段追加 __dupN。"],
        ["公开数据盘点表数量", inventory_total or "未知", "reports/public_data_inventory.json", "用于追溯源文件、sheet、行列数。"],
        ["可读数据行数", readable_rows, "全部可读 .xlsx/.csv/.json", "含参考/补充/新数据导出，未简单去重。"],
        ["字段出现次数", readable_columns, "DataLoader 实际读取列", "用于字段覆盖率和来源字段追溯。"],
        ["字段映射记录数", mapping_rows or "未知", "reports/public_data_field_mapping.csv", "只作为映射参考，最终抽取以脚本别名表为准。"],
        ["企业聚合记录数", len(records), "企业名称/统一社会信用代码/企业ID 聚合", "跨源 ID 体系不完全一致，名称与信用代码优先。"],
    ]


def build_top_high_risk_rows(records: Iterable[EnterpriseRecord], limit: int) -> list[list[Any]]:
    rows = []
    for idx, rec in enumerate(top_records(records, limit=limit), start=1):
        rows.append(
            [
                idx,
                rec.primary_name(),
                rec.primary_credit_code(),
                compact_list([display_value(rec, "industry_large"), display_value(rec, "supervision_category")], limit=2),
                compact_list([display_value(rec, "production_status"), display_value(rec, "business_status")], limit=2),
                evidence_summary(rec),
                high_risk_score(rec),
                field_sources(
                    rec,
                    (
                        "latest_risk_level",
                        "risk_level_a_count",
                        "risk_with_accident_count",
                        "trouble_level_2_count",
                        "trouble_unrectified_count",
                        "writ_total_count",
                        "total_penalty_money",
                    ),
                ),
            ]
        )
    return rows


def build_dust_rows(records: Iterable[EnterpriseRecord], limit: int) -> list[list[Any]]:
    rows = []
    for rec in top_records(records, scenario="dust", limit=limit):
        rows.append(
            [
                rec.primary_name(),
                display_value(rec, "supervision_category"),
                display_value(rec, "dust_type"),
                display_value(rec, "dust_dry_system_num"),
                display_value(rec, "dust_wet_system_num"),
                display_value(rec, "dust_work_num"),
                display_value(rec, "dust_clear_count"),
                display_value(rec, "dust_last_clear_time"),
                evidence_summary(rec),
                field_sources(
                    rec,
                    (
                        "is_explosive_dust",
                        "dust_type",
                        "dust_dry_system_num",
                        "dust_wet_system_num",
                        "dust_clear_count",
                    ),
                ),
            ]
        )
    return rows


def build_metallurgy_rows(records: Iterable[EnterpriseRecord], limit: int) -> list[list[Any]]:
    rows = []
    for rec in top_records(records, scenario="metallurgy", limit=limit):
        rows.append(
            [
                rec.primary_name(),
                display_value(rec, "supervision_category"),
                display_value(rec, "blast_furnace_num"),
                display_value(rec, "converter_num"),
                display_value(rec, "electric_furnace_num"),
                display_value(rec, "gas_cabinet_num"),
                display_value(rec, "ammonia_tank_num"),
                compact_list(
                    [
                        f"深井铸造={display_value(rec, 'deep_well_casting_num')}",
                        f"钢丝绳提升={display_value(rec, 'wire_rope_lift_num')}",
                        f"液压提升={display_value(rec, 'hydraulic_lift_num')}",
                        f"联锁={display_value(rec, 'interlock_device')}",
                    ],
                    limit=4,
                ),
                evidence_summary(rec),
                field_sources(
                    rec,
                    (
                        "is_metal_smelter",
                        "blast_furnace_num",
                        "converter_num",
                        "electric_furnace_num",
                        "gas_cabinet_num",
                        "deep_well_casting_num",
                    ),
                ),
            ]
        )
    return rows


def build_hazchem_rows(records: Iterable[EnterpriseRecord], limit: int) -> list[list[Any]]:
    rows = []
    for rec in top_records(records, scenario="hazchem", limit=limit):
        rows.append(
            [
                rec.primary_name(),
                display_value(rec, "supervision_category"),
                display_value(rec, "dangerous_chemical_enterprise"),
                display_value(rec, "is_ammonia_refrigerating"),
                display_value(rec, "ammonia_tank_num"),
                display_value(rec, "is_major_hazards"),
                compact_list(
                    [
                        f"文书={display_value(rec, 'writ_total_count')}",
                        f"处罚={display_value(rec, 'total_penalty_money')}",
                    ],
                    limit=2,
                ),
                evidence_summary(rec),
                field_sources(
                    rec,
                    (
                        "dangerous_chemical_enterprise",
                        "is_ammonia_refrigerating",
                        "ammonia_tank_num",
                        "is_major_hazards",
                        "writ_total_count",
                        "total_penalty_money",
                    ),
                ),
            ]
        )
    return rows


def build_finite_rows(records: Iterable[EnterpriseRecord], limit: int) -> list[list[Any]]:
    rows = []
    for rec in top_records(records, scenario="finite", limit=limit):
        rows.append(
            [
                rec.primary_name(),
                display_value(rec, "supervision_category"),
                display_value(rec, "is_finite_space"),
                display_value(rec, "risk_company_key_flag"),
                compact_list(
                    [
                        f"检查={display_value(rec, 'check_total_count')}",
                        f"隐患={display_value(rec, 'trouble_total_count')}",
                        f"未整改={display_value(rec, 'trouble_unrectified_count')}",
                    ],
                    limit=3,
                ),
                evidence_summary(rec),
                field_sources(
                    rec,
                    (
                        "is_finite_space",
                        "risk_company_key_flag",
                        "check_total_count",
                        "trouble_total_count",
                        "trouble_unrectified_count",
                    ),
                ),
            ]
        )
    return rows


def build_management_rows(records: Iterable[EnterpriseRecord], limit: int) -> list[list[Any]]:
    ranked = sorted(
        [rec for rec in records if rec.primary_name() != "未知企业"],
        key=lambda rec: (
            high_risk_score(rec),
            -int(display_value(rec, "insurance_flag") == "是"),
            -int(display_value(rec, "comply_formality_flag") == "是"),
        ),
        reverse=True,
    )[:limit]
    rows = []
    for rec in ranked:
        rows.append(
            [
                rec.primary_name(),
                display_value(rec, "staff_num"),
                display_value(rec, "safety_num"),
                compact_list(
                    [
                        f"专职={display_value(rec, 'fulltime_safety_num')}",
                        f"兼职={display_value(rec, 'parttime_safety_num')}",
                        f"持证={display_value(rec, 'fulltime_cert_num')}/{display_value(rec, 'parttime_cert_num')}",
                        f"特种作业={display_value(rec, 'special_work_cert_num')}",
                    ],
                    limit=4,
                ),
                display_value(rec, "insurance_flag"),
                display_value(rec, "safety_standardization"),
                display_value(rec, "comply_formality_flag"),
                display_value(rec, "safety_dept"),
                field_sources(
                    rec,
                    (
                        "staff_num",
                        "safety_num",
                        "fulltime_safety_num",
                        "parttime_safety_num",
                        "fulltime_cert_num",
                        "parttime_cert_num",
                        "special_work_cert_num",
                        "insurance_flag",
                        "safety_standardization",
                        "comply_formality_flag",
                    ),
                ),
            ]
        )
    return rows


def build_location_rows(records: Iterable[EnterpriseRecord], limit: int = 20) -> list[list[Any]]:
    rows = []
    candidates = [
        rec
        for rec in records
        if display_value(rec, "address") != "未知"
        or display_value(rec, "longitude") != "未知"
        or display_value(rec, "latitude") != "未知"
    ]
    for rec in sorted(candidates, key=high_risk_score, reverse=True)[:limit]:
        rows.append(
            [
                rec.primary_name(),
                rec.primary_credit_code(),
                display_value(rec, "address"),
                display_value(rec, "longitude"),
                display_value(rec, "latitude"),
                field_sources(rec, ("address", "longitude", "latitude")),
            ]
        )
    return rows


def summary_counts(records: Iterable[EnterpriseRecord]) -> dict[str, Any]:
    recs = list(records)
    named = [rec for rec in recs if rec.primary_name() != "未知企业"]
    with_credit = [rec for rec in recs if rec.primary_credit_code() != "未知"]
    return {
        "enterprise_records": len(recs),
        "named_enterprises": len(named),
        "credit_known": len(with_credit),
        "dust": sum(scenario_applicable(rec, "dust") for rec in recs),
        "metallurgy": sum(scenario_applicable(rec, "metallurgy") for rec in recs),
        "hazchem": sum(scenario_applicable(rec, "hazchem") for rec in recs),
        "finite": sum(scenario_applicable(rec, "finite") for rec in recs),
        "major_hazard": sum(flag_value(rec, "is_major_hazards") for rec in recs),
        "risk_key": sum(flag_value(rec, "risk_company_key_flag") for rec in recs),
        "risk_focus": sum(flag_value(rec, "risk_company_flag") for rec in recs),
    }


def build_markdown(
    records: dict[str, EnterpriseRecord],
    field_stats: dict[str, Any],
    source_summaries: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
    mapping: pd.DataFrame,
    top_n: int,
    scene_n: int,
) -> str:
    config = get_config()
    counts = summary_counts(records.values())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_paths = []
    if config.data.public_data_root:
        data_paths.append(config.data.public_data_root)
    data_paths.extend(config.data.all_public_data_paths or [])
    data_paths = list(dict.fromkeys(data_paths))

    parts: list[str] = []
    parts.append("# 企业已具备的执行条件")
    parts.append(
        "\n".join(
            [
                f"> 重建时间：{now}",
                "> 生成脚本：`scripts/rebuild_enterprise_conditions_kb.py`",
                "> 读取方式：`DataLoader.load_public_data(skip_errors=True)` 递归加载公开数据目录内全部可读 `.xlsx`、`.csv`、`.json`。",
                "> 本轮只更新文件系统 Markdown；AgentFS 同步建议见文末。",
            ]
        )
    )

    parts.append("## 1. 元数据与数据来源说明")
    parts.append(
        "本知识库用于 RAG 检索企业是否具备安全生产执行条件、哪些场景需要重点核查、哪些字段仍需补采。"
        "公开数据中存在预合并训练集、企业主数据、检查/隐患/执法/处罚明细、场景标签和补充导出表；脚本使用全部可读表，"
        "但在企业级聚合时采用“统一社会信用代码优先、企业名称次之、企业内部 ID 兜底”的策略，避免把参考表和补充表的重复导出简单相加。"
    )
    parts.append(
        markdown_table(
            ["指标", "值", "来源", "说明"],
            source_metric_rows(records, source_summaries, inventory, mapping),
        )
    )
    parts.append(
        markdown_table(
            ["公开数据配置项", "路径"],
            [[f"data_path_{idx + 1}", path] for idx, path in enumerate(data_paths)]
            + [
                ["merged_data_path", config.data.merged_data_path or "未知"],
                ["盘点报告", str(INVENTORY_REPORT.relative_to(PROJECT_ROOT)) if INVENTORY_REPORT.exists() else "未知"],
                ["字段映射", str(FIELD_MAPPING_CSV.relative_to(PROJECT_ROOT)) if FIELD_MAPPING_CSV.exists() else "未知"],
                ["机器盘点", str(INVENTORY_JSON.relative_to(PROJECT_ROOT)) if INVENTORY_JSON.exists() else "未知"],
            ],
        )
    )

    parts.append("### 1.1 可读数据源清单")
    parts.append("下表列出本次实际加载的全部可读表。`匹配字段` 展示进入本知识库抽取逻辑的字段，完整字段以 `reports/public_data_inventory.json` 为准。")
    parts.append(
        markdown_table(
            ["来源文件", "格式", "行数", "列数", "覆盖主题", "匹配字段示例"],
            build_source_table(source_summaries, inventory),
        )
    )

    parts.append("## 2. 字段口径说明")
    parts.append(
        "取值解释：`未知` 表示可读数据源未提供该企业该字段或该值缺失；`无记录` 表示字段存在且值为否/0/无；"
        "`不适用` 用于场景表中未纳入该场景的企业；具体数值或状态按数据源原值保留。"
    )
    parts.append(
        markdown_table(
            ["字段", "主题", "口径", "来源字段", "缺失率"],
            field_coverage_rows(field_stats),
        )
    )

    parts.append("## 3. 企业执行条件摘要")
    parts.append(
        markdown_table(
            ["摘要项", "数量", "说明"],
            [
                ["企业聚合记录", counts["enterprise_records"], "按信用代码/企业名称/内部 ID 聚合后的知识库记录数"],
                ["可识别企业名称", counts["named_enterprises"], "至少存在企业名称的记录"],
                ["可识别统一社会信用代码或信用编码", counts["credit_known"], "包含 `enterprise_id`、`UUIT_NO`、`CREDIT_NO` 等字段"],
                ["粉尘涉爆相关企业", counts["dust"], "含粉尘标识、粉尘类型、除尘系统或清扫记录"],
                ["冶金/金属冶炼相关企业", counts["metallurgy"], "含冶金标识或高炉、转炉、电炉、煤气柜等设备"],
                ["危化品/涉氨/重大危险源相关企业", counts["hazchem"], "含危化品、涉氨制冷、氨罐、重大危险源标识"],
                ["有限空间相关企业", counts["finite"], "含有限空间作业或重点企业标识"],
                ["重大危险源标识企业", counts["major_hazard"], "字段明确为是的企业数"],
                ["风险重点企业", counts["risk_focus"], "风险重点企业标识为是"],
                ["关键风险企业", counts["risk_key"], "关键风险企业标识为是"],
            ],
        )
    )
    parts.append("### 3.1 行业与场景分布")
    parts.append(
        markdown_table(
            ["行业/监管类别", "企业数", "粉尘涉爆", "冶金", "危化品", "有限空间", "平均风险计分"],
            top_industry_rows(records.values()),
        )
    )
    parts.append("### 3.2 地址与经纬度可追溯样例")
    parts.append(
        markdown_table(
            ["企业名称", "统一社会信用代码/企业ID", "地址", "经度", "纬度", "来源字段"],
            build_location_rows(records.values(), limit=20),
        )
    )

    parts.append("## 4. 粉尘涉爆执行条件")
    parts.append(
        "判定口径：企业存在粉尘涉爆标识、粉尘类型、干/湿式除尘系统数量、涉粉作业人数/点位或除尘清扫记录任一证据，即纳入粉尘涉爆场景。"
    )
    parts.append(
        markdown_table(
            ["企业名称", "监管类别", "粉尘类型", "干式除尘", "湿式除尘", "涉粉作业", "除尘记录", "最近除尘", "风险证据", "来源字段"],
            build_dust_rows(records.values(), scene_n),
        )
    )

    parts.append("## 5. 冶金设备执行条件")
    parts.append(
        "判定口径：企业存在金属冶炼标识，或高炉、转炉、电炉、煤气柜、深井铸造、提升装置、事故联锁装置等任一设备记录，即纳入冶金场景。"
    )
    parts.append(
        markdown_table(
            ["企业名称", "监管类别", "高炉", "转炉", "电炉", "煤气柜", "氨罐", "深井/提升/联锁", "风险证据", "来源字段"],
            build_metallurgy_rows(records.values(), scene_n),
        )
    )

    parts.append("## 6. 危化品与重大危险源执行条件")
    parts.append(
        "判定口径：企业存在危化品标识、涉氨制冷、氨罐数量、重大危险源标识或危化品使用/经营风险标识，即纳入危化品场景。"
    )
    parts.append(
        markdown_table(
            ["企业名称", "监管类别", "危化品企业", "涉氨制冷", "氨罐", "重大危险源", "执法处罚", "风险证据", "来源字段"],
            build_hazchem_rows(records.values(), scene_n),
        )
    )

    parts.append("## 7. 有限空间执行条件")
    parts.append("判定口径：企业有限空间标识、有限空间重点企业标识或有限空间相关场景标签为是，即纳入有限空间场景。")
    parts.append(
        markdown_table(
            ["企业名称", "监管类别", "有限空间标识", "关键风险企业", "检查隐患", "风险证据", "来源字段"],
            build_finite_rows(records.values(), scene_n),
        )
    )

    parts.append("## 8. 通用安全管理执行条件")
    parts.append(
        "本节覆盖人员、资质、保险、安全生产标准化、三同时手续和安全管理机构等通用管理条件。"
        "当字段为 `无记录` 时，代表源字段存在且值为否/0/无；当为 `未知` 时，代表该企业记录缺失。"
    )
    parts.append(
        markdown_table(
            ["企业名称", "职工人数", "安全管理人员", "专兼职/持证/特种作业", "保险", "标准化", "三同时", "安全管理机构", "来源字段"],
            build_management_rows(records.values(), scene_n),
        )
    )

    parts.append("## 9. 高风险企业 Top 清单")
    parts.append(
        "风险计分由最新风险等级、A/B 级风险数、事故关联风险、重大/未整改隐患、执法文书、处罚金额、重大危险源和重点企业标识综合形成，"
        "仅作为 RAG 检索和人工复核排序依据，不替代正式监管分级。"
    )
    parts.append(
        markdown_table(
            ["排名", "企业名称", "统一社会信用代码/企业ID", "行业/监管类别", "生产/经营状态", "核心风险证据", "风险计分", "来源字段"],
            build_top_high_risk_rows(records.values(), top_n),
        )
    )

    parts.append("## 10. 数据缺失与需补采字段清单")
    parts.append(
        "以下字段要么未在可读公开数据中发现，要么字段存在但缺失率超过 80%。补采时应优先以统一社会信用代码贯通企业主数据、检查执法、场景设备和风险台账。"
    )
    parts.append(
        markdown_table(
            ["字段", "主题", "缺失率", "缺失类型", "补采建议"],
            missing_rows(field_stats),
        )
    )

    parts.append("## 11. AgentFS 同步建议")
    parts.append(
        "\n".join(
            [
                "本轮已先更新文件系统知识库 Markdown，未直接写入 `data/agentfs.db`，避免覆盖 AgentFS 中可能存在的版本链和权限元数据。",
                "建议同步流程：",
                "1. 运行 `venv\\Scripts\\python.exe scripts\\check_knowledge_env.py` 对比文件系统与 AgentFS 中的知识库条目。",
                "2. 人工确认本文件内容后，通过项目现有 AgentFS 写入接口将 `knowledge_base/企业已具备的执行条件.md` 同步为同名路径。",
                "3. 同步后重建或刷新 VectorStore，确保 RAG 召回使用新分块。",
                "4. 保留 AgentFS 旧版本快照，便于回滚演示表版本与本次重建版本的差异。",
            ]
        )
    )

    parts.append("## 12. 更新日志")
    parts.append(
        markdown_table(
            ["时间", "动作", "影响范围", "质量控制"],
            [
                [
                    now,
                    "基于公开数据全量重建企业执行条件知识库",
                    "仅覆盖 `knowledge_base/企业已具备的执行条件.md`",
                    "清理旧演示长表和重复追加段落；新增字段口径、场景小表、Top 清单和缺失清单。",
                ]
            ],
        )
    )

    return "\n\n".join(parts).strip() + "\n"


def validate_markdown(text: str) -> list[str]:
    issues = []
    if len(text.strip()) < 5000:
        issues.append("文件内容过短")
    if text.count("| - |") > 5:
        issues.append("仍存在大量 `| - |` 占位")
    required = [
        "元数据与数据来源说明",
        "字段口径说明",
        "缺失率",
        "粉尘涉爆执行条件",
        "冶金设备执行条件",
        "危化品与重大危险源执行条件",
        "有限空间执行条件",
        "高风险企业 Top 清单",
        "AgentFS 同步建议",
    ]
    for item in required:
        if item not in text:
            issues.append(f"缺少章节：{item}")
    return issues


def rebuild(output: Path = TARGET_KB, top_n: int = 25, scene_n: int = 15) -> dict[str, Any]:
    logging.getLogger("data.loader").setLevel(logging.WARNING)
    loader = DataLoader()
    tables = loader.load_public_data(skip_errors=True)
    inventory = read_inventory()
    mapping = read_field_mapping()
    records, field_stats, source_summaries = aggregate_tables(tables)
    text = build_markdown(records, field_stats, source_summaries, inventory, mapping, top_n=top_n, scene_n=scene_n)
    issues = validate_markdown(text)
    if issues:
        raise RuntimeError("知识库质量检查失败：" + "；".join(issues))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    counts = summary_counts(records.values())
    return {
        "output": str(output.relative_to(PROJECT_ROOT)),
        "readable_tables": len(source_summaries),
        "readable_rows": sum(item["rows"] for item in source_summaries),
        **counts,
        "size_chars": len(text),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=TARGET_KB, help="Markdown output path")
    parser.add_argument("--top-n", type=int, default=25, help="High-risk enterprise top N")
    parser.add_argument("--scene-n", type=int, default=15, help="Scenario table row limit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output
    if not output.is_absolute():
        output = resolve_project_path(output)
    summary = rebuild(output=output, top_n=args.top_n, scene_n=args.scene_n)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
