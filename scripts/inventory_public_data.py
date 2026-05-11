"""Inventory public enterprise data and produce a knowledge-base field map.

This script is intentionally read-only for source data and project code. It
scans ``公开数据`` recursively, reads every .csv/.xlsx table, profiles schemas,
infers field themes, maps raw columns to canonical fields, and writes report
artifacts under ``mining_risk_agent/reports``.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DATA_ROOT = REPO_ROOT / "公开数据"
REPORT_DIR = REPO_ROOT / "mining_risk_agent" / "reports"
REPORT_PATH = REPORT_DIR / "public_data_inventory_report.md"
MAPPING_CSV_PATH = REPORT_DIR / "public_data_field_mapping.csv"
INVENTORY_JSON_PATH = REPORT_DIR / "public_data_inventory.json"

KNOWLEDGE_BASES = {
    "compliance": "工矿风险预警智能体合规执行书.md",
    "dept_sop": "部门分级审核SOP.md",
    "physics_sensor": "工业物理常识及传感器时间序列逻辑.md",
    "execution_conditions": "企业已具备的执行条件.md",
    "accident_cases": "类似事故处理案例.md",
    "warning_memory": "预警历史经验与短期记忆摘要.md",
}

THEMES = [
    "企业基本信息",
    "行业分类",
    "风险历史",
    "隐患排查",
    "日常检查",
    "执法文书",
    "行政处罚",
    "部门/人员/监管主体",
    "安全管理人员与资质",
    "粉尘涉爆",
    "冶金设备",
    "危化品",
    "有限空间",
    "地理位置",
    "生产状态",
    "其他可用于知识库的字段",
]

THEME_KEYWORDS = {
    "企业基本信息": [
        "enterprise_information",
        "enterprise_directory",
        "st_ds_aczf_enterprise",
        "base_info",
        "enterprise_name",
        "企业名称",
        "公司名称",
        "单位名称",
        "统一社会信用",
        "社会信用代码",
        "法定代表人",
        "法人",
        "注册",
        "登记",
        "经营范围",
        "联系方式",
    ],
    "行业分类": [
        "industry",
        "volkswirtschaft",
        "indus",
        "行业",
        "国民经济",
        "监管大类",
        "监管分类",
        "supervision",
    ],
    "风险历史": [
        "risk_history",
        "enterprise_risk",
        "risk_target",
        "risk",
        "风险",
        "事故",
        "accident",
        "等级",
        "隐患数量",
    ],
    "隐患排查": [
        "trouble",
        "hidden",
        "隐患",
        "整改",
        "排查",
        "问题",
    ],
    "日常检查": [
        "routine_check",
        "check_log",
        "check_plan",
        "检查",
        "巡查",
        "自查",
        "计划",
    ],
    "执法文书": [
        "writ",
        "accessory",
        "文书",
        "附件",
        "签章",
        "pdf",
    ],
    "行政处罚": [
        "penalty",
        "discretion",
        "illage",
        "处罚",
        "罚款",
        "违法",
        "裁量",
        "立案",
    ],
    "部门/人员/监管主体": [
        "sys_dept",
        "sys_user",
        "dept",
        "user",
        "部门",
        "人员",
        "监管",
        "承办人",
        "填报人",
        "创建人",
        "审核",
    ],
    "安全管理人员与资质": [
        "safety",
        "安全管理",
        "安全生产",
        "持证",
        "证书",
        "特种作业",
        "投保",
        "三同时",
        "资质",
    ],
    "粉尘涉爆": [
        "dust",
        "粉尘",
        "涉爆",
        "除尘",
        "清扫",
        "清除",
    ],
    "冶金设备": [
        "metallurgy",
        "metal",
        "smelt",
        "冶金",
        "金属冶炼",
        "高炉",
        "转炉",
        "电炉",
        "中频炉",
        "铝加工",
        "深井铸造",
    ],
    "危化品": [
        "chemical",
        "危化",
        "危险化学品",
        "氨",
        "危险源",
        "hazardous",
    ],
    "有限空间": [
        "finite",
        "confined",
        "有限空间",
    ],
    "地理位置": [
        "gcj02",
        "address",
        "longitude",
        "latitude",
        "location",
        "geo",
        "地址",
        "坐标",
        "经度",
        "纬度",
        "省",
        "市",
        "区县",
        "乡镇",
        "街道",
        "行政区划",
    ],
    "生产状态": [
        "production_status",
        "生产状态",
        "停产",
        "经营状态",
        "注销",
        "歇业",
    ],
}


@dataclass(frozen=True)
class FieldRule:
    standard_field: str
    topic: str
    kbs: tuple[str, ...]
    keywords: tuple[str, ...]
    note: str = ""


def rule(
    standard_field: str,
    topic: str,
    kbs: list[str],
    keywords: list[str],
    note: str = "",
) -> FieldRule:
    return FieldRule(standard_field, topic, tuple(kbs), tuple(keywords), note)


STANDARD_FIELD_RULES = [
    rule("unified_social_credit_code", "企业基本信息", ["execution_conditions", "compliance", "warning_memory"], ["统一社会信用", "社会信用代码", "信用代码", "credit_code", "unified", "uscc"], "企业级主键优先候选"),
    rule("enterprise_internal_id", "企业基本信息", ["execution_conditions", "warning_memory"], ["企业id", "企业ID", "enterprise_id", "ent_id", "companyid", "company_id"], "内部企业ID，需用桥表转信用代码"),
    rule("enterprise_name", "企业基本信息", ["execution_conditions", "compliance", "accident_cases", "warning_memory"], ["企业名称", "公司名称", "单位名称", "enterprise_name", "corpname", "company_name", "party_name"]),
    rule("legal_person", "企业基本信息", ["execution_conditions"], ["法定代表人", "法人", "legal_person"]),
    rule("contact_phone", "企业基本信息", ["execution_conditions", "dept_sop"], ["电话", "手机", "联系方式", "phone", "cellphone", "mobile"]),
    rule("registered_address", "地理位置", ["execution_conditions"], ["注册地址", "registered_address", "reg_address"]),
    rule("business_address", "地理位置", ["execution_conditions", "compliance"], ["生产经营地址", "经营地址", "办公地址", "详细地址", "标准地址", "address", "business_address", "formatted_address"]),
    rule("province", "地理位置", ["execution_conditions", "dept_sop"], ["省名称", "所在省", "province", "省编码", "省"]),
    rule("city", "地理位置", ["execution_conditions", "dept_sop"], ["市名称", "所在市", "city", "市编码", "市"]),
    rule("county", "地理位置", ["execution_conditions", "dept_sop"], ["区县名称", "所在县", "县", "区县", "county", "district"]),
    rule("town", "地理位置", ["execution_conditions", "dept_sop"], ["乡镇", "街道", "town", "street"]),
    rule("village", "地理位置", ["execution_conditions"], ["村", "社区", "village", "community"]),
    rule("longitude", "地理位置", ["execution_conditions", "compliance"], ["经度", "longitude", "lng", "lon"]),
    rule("latitude", "地理位置", ["execution_conditions", "compliance"], ["纬度", "latitude", "lat"]),
    rule("geo_address_id", "地理位置", ["execution_conditions"], ["地址id", "address_id", "生产经营地址id", "标准地址id"]),
    rule("industry_supervision_large", "行业分类", ["execution_conditions", "compliance", "warning_memory"], ["行业监管大类", "监管大类", "supervision_large"]),
    rule("industry_supervision_small", "行业分类", ["execution_conditions", "compliance"], ["行业监管小类", "监管小类", "supervision_small"]),
    rule("national_economy_class", "行业分类", ["execution_conditions"], ["国民经济门类", "indus_type_class"]),
    rule("national_economy_large", "行业分类", ["execution_conditions"], ["国民经济大类", "indus_type_large", "indus_type_lagre"]),
    rule("national_economy_middle", "行业分类", ["execution_conditions"], ["国民经济中类", "indus_type_middle"]),
    rule("national_economy_small", "行业分类", ["execution_conditions"], ["国民经济小类", "indus_type_small"]),
    rule("enterprise_scale", "企业基本信息", ["execution_conditions"], ["企业规模", "规模", "enterprise_scale", "above_designated"]),
    rule("above_designated_flag", "企业基本信息", ["execution_conditions"], ["规上", "above_designated"]),
    rule("business_status", "生产状态", ["execution_conditions", "warning_memory"], ["经营状态", "business_status"]),
    rule("production_status", "生产状态", ["execution_conditions", "compliance", "warning_memory"], ["生产状态", "停产", "production_status", "rh_production_status"]),
    rule("report_status", "风险历史", ["warning_memory"], ["报告状态", "上报状态", "report_status"]),
    rule("report_time", "风险历史", ["warning_memory", "execution_conditions"], ["报告时间", "上报时间", "报告日期", "report_time"]),
    rule("report_history_id", "风险历史", ["execution_conditions", "warning_memory"], ["报告历史id", "报告历史ID", "risk_report_id", "latest_risk_report_id"]),
    rule("risk_id", "风险历史", ["accident_cases", "warning_memory"], ["风险表id", "风险id", "risk_id"]),
    rule("risk_code", "风险历史", ["accident_cases", "compliance", "warning_memory"], ["风险代码", "risk_code"]),
    rule("risk_name", "风险历史", ["accident_cases", "compliance"], ["风险名称", "risk_name"]),
    rule("risk_category", "风险历史", ["compliance", "physics_sensor"], ["管理类别", "风险类别", "risk_category"]),
    rule("risk_level", "风险历史", ["execution_conditions", "accident_cases", "compliance", "warning_memory"], ["风险等级", "安全风险等级", "latest_risk_level", "risk_level"]),
    rule("major_accident_type", "风险历史", ["accident_cases", "physics_sensor"], ["主要事故类别", "事故类型", "accident_type", "work_injury_accident_types"]),
    rule("risk_point", "风险历史", ["accident_cases", "physics_sensor"], ["风险点", "risk_point"]),
    rule("risk_description", "风险历史", ["accident_cases", "compliance", "physics_sensor"], ["风险描述", "事故概述", "risk_description", "accident_summary"]),
    rule("control_measure", "风险历史", ["compliance", "physics_sensor", "accident_cases"], ["管控措施", "control_measure", "防控措施"]),
    rule("risk_owner_dept", "部门/人员/监管主体", ["dept_sop", "compliance"], ["责任部门", "检查部门", "dept"]),
    rule("risk_owner_person", "部门/人员/监管主体", ["dept_sop", "compliance"], ["责任人", "checker", "检查人员", "承办人"]),
    rule("risk_accident_flag", "风险历史", ["accident_cases", "warning_memory"], ["是否发生事故", "曾发生事故", "risk_accident_flag", "accident_flag"]),
    rule("risk_event_flag", "风险历史", ["accident_cases", "warning_memory"], ["是否发生事件", "event"]),
    rule("risk_total_count", "风险历史", ["execution_conditions", "warning_memory"], ["风险数量", "风险总数", "risk_total_count"]),
    rule("major_risk_count", "风险历史", ["execution_conditions", "compliance"], ["重大风险数量", "risk_level_a_count", "较大以上"]),
    rule("larger_risk_count", "风险历史", ["execution_conditions"], ["较大风险数量", "risk_level_b_count"]),
    rule("risk_with_accident_count", "风险历史", ["execution_conditions", "accident_cases", "warning_memory"], ["曾发事故的风险数", "risk_with_accident_count"]),
    rule("risk_company_flag", "风险历史", ["execution_conditions", "compliance"], ["风险重点企业", "risk_company_flag", "关键风险企业"]),
    rule("check_id", "日常检查", ["execution_conditions", "accident_cases", "warning_memory"], ["检查主键id", "检查主键ID", "记录表id", "check_id"]),
    rule("check_plan_id", "日常检查", ["dept_sop", "warning_memory"], ["计划id", "plan_id"]),
    rule("check_type", "日常检查", ["dept_sop", "warning_memory"], ["检查类型", "检查类别", "check_type"]),
    rule("check_time", "日常检查", ["execution_conditions", "warning_memory"], ["检查时间", "check_time"]),
    rule("check_name", "日常检查", ["warning_memory"], ["检查名称", "check_name"]),
    rule("check_content", "日常检查", ["accident_cases", "warning_memory"], ["检查内容", "check_content"]),
    rule("check_department", "日常检查", ["dept_sop", "warning_memory"], ["检查部门", "check_department"]),
    rule("checker_id", "部门/人员/监管主体", ["dept_sop"], ["检查人员id", "checker_id"]),
    rule("checker_name", "部门/人员/监管主体", ["dept_sop"], ["检查人员姓名", "checker_name"]),
    rule("check_total_count", "日常检查", ["execution_conditions", "warning_memory"], ["检查总次数", "check_total_count"]),
    rule("check_trouble_count", "隐患排查", ["execution_conditions", "warning_memory"], ["检查发现问题次数", "check_trouble_count"]),
    rule("has_trouble_flag", "隐患排查", ["execution_conditions", "accident_cases", "warning_memory"], ["是否发现问题隐患", "has_risk_item"]),
    rule("trouble_id", "隐患排查", ["accident_cases", "warning_memory"], ["隐患id", "trouble_id", "主键ID"]),
    rule("hidden_danger_level", "隐患排查", ["execution_conditions", "accident_cases", "compliance"], ["隐患等级", "trouble_level"]),
    rule("hidden_danger_detail", "隐患排查", ["accident_cases", "compliance"], ["隐患详情", "问题隐患", "trouble_detail"]),
    rule("rectification_suggestion", "隐患排查", ["compliance", "accident_cases"], ["整改建议", "整改意见", "rectification_suggestion"]),
    rule("rectification_status", "隐患排查", ["execution_conditions", "accident_cases", "warning_memory"], ["整改状态", "隐患状态", "rectification_status"]),
    rule("rectification_deadline", "隐患排查", ["compliance", "warning_memory"], ["期限整改时间", "整改时间", "rectification_deadline"]),
    rule("law_enforcement_submit_status", "隐患排查", ["dept_sop", "compliance"], ["提交行政执法状态"]),
    rule("trouble_total_count", "隐患排查", ["execution_conditions", "warning_memory"], ["隐患总数", "trouble_total_count"]),
    rule("trouble_level_1_count", "隐患排查", ["execution_conditions"], ["一般隐患数", "trouble_level_1_count"]),
    rule("trouble_level_2_count", "隐患排查", ["execution_conditions", "accident_cases", "compliance"], ["重大隐患数", "trouble_level_2_count"]),
    rule("trouble_unrectified_count", "隐患排查", ["execution_conditions", "accident_cases", "compliance"], ["未整改隐患数", "trouble_unrectified_count"]),
    rule("writ_id", "执法文书", ["accident_cases", "compliance", "warning_memory"], ["文书记录id", "writ_id"]),
    rule("writ_type_code", "执法文书", ["accident_cases", "compliance"], ["文书类型编码", "writ_type"]),
    rule("writ_no", "执法文书", ["accident_cases", "compliance"], ["文书号", "writ_no"]),
    rule("writ_source", "执法文书", ["accident_cases", "warning_memory"], ["文书来源"]),
    rule("writ_status", "执法文书", ["dept_sop", "warning_memory"], ["签章状态", "上报省厅", "上传标志"]),
    rule("writ_total_count", "执法文书", ["execution_conditions", "warning_memory"], ["文书总数", "writ_total_count"]),
    rule("writ_from_case_count", "执法文书", ["execution_conditions", "accident_cases"], ["立案文书数", "writ_from_case_count"]),
    rule("writ_from_check_count", "执法文书", ["execution_conditions", "accident_cases"], ["检查文书数", "writ_from_check_count"]),
    rule("attachment_id", "执法文书", ["accident_cases", "compliance"], ["附件id", "附件ID", "accessory", "attachment"]),
    rule("pdf_attachment_id", "执法文书", ["accident_cases", "compliance"], ["pdf附件id", "pdf"]),
    rule("penalty_id", "行政处罚", ["accident_cases", "compliance", "warning_memory"], ["处罚id", "penalty_id"]),
    rule("case_id", "行政处罚", ["accident_cases", "compliance"], ["立案", "案件", "case_id", "业务id", "来源id"]),
    rule("illegal_fact", "行政处罚", ["accident_cases", "compliance"], ["违法事实", "违法行为", "illegal", "illage"]),
    rule("penalty_basis", "行政处罚", ["compliance", "accident_cases"], ["处罚依据", "裁量", "discretion", "依据"]),
    rule("penalty_decision", "行政处罚", ["accident_cases", "compliance"], ["处罚决定", "处理结果", "处罚内容"]),
    rule("penalty_amount", "行政处罚", ["execution_conditions", "accident_cases", "compliance"], ["处罚金额", "罚款", "total_penalty_money", "penalty_money"]),
    rule("dept_id", "部门/人员/监管主体", ["dept_sop"], ["部门id", "dept_id", "单位id"]),
    rule("dept_name", "部门/人员/监管主体", ["dept_sop"], ["部门名称", "dept_name", "单位名称"]),
    rule("parent_dept_id", "部门/人员/监管主体", ["dept_sop"], ["父部门", "上级部门", "parent"]),
    rule("user_id", "部门/人员/监管主体", ["dept_sop"], ["用户id", "人员id", "user_id", "承办人id", "填报人"]),
    rule("user_name", "部门/人员/监管主体", ["dept_sop"], ["用户名称", "姓名", "user_name"]),
    rule("role_name", "部门/人员/监管主体", ["dept_sop"], ["角色", "职务", "岗位", "role"]),
    rule("staff_num", "安全管理人员与资质", ["execution_conditions"], ["职工总人数", "从业人员", "staff_num"]),
    rule("outsourced_staff_num", "安全管理人员与资质", ["execution_conditions"], ["外用总人数", "外包", "outsourced"]),
    rule("safety_staff_total", "安全管理人员与资质", ["execution_conditions", "compliance"], ["安全管理人员数量", "安全生产管理人员数", "safety_num"]),
    rule("fulltime_safety_staff_num", "安全管理人员与资质", ["execution_conditions", "compliance"], ["专职安全", "fulltime_safety_num"]),
    rule("parttime_safety_staff_num", "安全管理人员与资质", ["execution_conditions"], ["兼职安全", "parttime_safety_num"]),
    rule("safety_department_name", "安全管理人员与资质", ["execution_conditions", "dept_sop"], ["安全管理部门"]),
    rule("safety_dept_staff_num", "安全管理人员与资质", ["execution_conditions"], ["部门安全管理人员数量", "safety_dept_num"]),
    rule("fulltime_cert_num", "安全管理人员与资质", ["execution_conditions", "compliance"], ["专职安全生产管理人员持证", "fulltime_cert_num"]),
    rule("parttime_cert_num", "安全管理人员与资质", ["execution_conditions"], ["兼职安全生产管理人员持证", "parttime_cert_num"]),
    rule("special_work_cert_num", "安全管理人员与资质", ["execution_conditions", "compliance"], ["特种作业", "special_work_cert_num"]),
    rule("safety_standardization", "安全管理人员与资质", ["execution_conditions", "compliance"], ["安全生产标准化", "safety_build"]),
    rule("safety_invest_ratio", "安全管理人员与资质", ["execution_conditions"], ["安全生产投入", "safety_invest"]),
    rule("comply_formality_flag", "安全管理人员与资质", ["execution_conditions", "compliance"], ["三同时", "comply_formality"]),
    rule("insurance_flag", "安全管理人员与资质", ["execution_conditions"], ["是否投保", "if_insure"]),
    rule("insurance_amount", "安全管理人员与资质", ["execution_conditions"], ["投保金额", "insure_money"]),
    rule("work_injury_insurance", "安全管理人员与资质", ["execution_conditions"], ["工伤保险", "injury_insurance"]),
    rule("insured_num", "安全管理人员与资质", ["execution_conditions"], ["投保人数", "insure_num"]),
    rule("turnover_rate", "安全管理人员与资质", ["execution_conditions"], ["人员流动率", "last_year_turnover"]),
    rule("last_year_income", "企业基本信息", ["execution_conditions"], ["上一年经营收入", "last_year_income"]),
    rule("fixed_assets", "企业基本信息", ["execution_conditions"], ["固定资产", "fixed_assets"]),
    rule("dust_enterprise_flag", "粉尘涉爆", ["execution_conditions", "compliance", "physics_sensor"], ["粉尘涉爆", "explosive_dust", "is_explosive_dust"]),
    rule("dust_dry_dedusting_system_num", "粉尘涉爆", ["execution_conditions", "physics_sensor"], ["干式除尘", "dust_ganshi_num"]),
    rule("dust_wet_dedusting_system_num", "粉尘涉爆", ["execution_conditions", "physics_sensor"], ["湿式除尘", "dust_shishi_num"]),
    rule("dust_clear_time", "粉尘涉爆", ["execution_conditions", "warning_memory"], ["除尘时间", "清扫时间"]),
    rule("dust_clear_count", "粉尘涉爆", ["execution_conditions"], ["除尘作业次数", "粉尘清扫次数", "dust_clear_count"]),
    rule("dust_clear_recorder", "粉尘涉爆", ["execution_conditions"], ["记录人", "recorder"]),
    rule("dust_clear_operator", "粉尘涉爆", ["execution_conditions"], ["实际操作人", "operator"]),
    rule("dust_clear_condition", "粉尘涉爆", ["execution_conditions", "compliance"], ["除尘情况"]),
    rule("metal_smelter_flag", "冶金设备", ["execution_conditions", "compliance", "physics_sensor"], ["金属冶炼", "冶金", "is_metal_smelter"]),
    rule("blast_furnace_num", "冶金设备", ["execution_conditions", "physics_sensor"], ["高炉", "gaolu_num"]),
    rule("converter_num", "冶金设备", ["execution_conditions", "physics_sensor"], ["转炉", "zhuanlu_num"]),
    rule("electric_furnace_num", "冶金设备", ["execution_conditions", "physics_sensor"], ["电炉", "dianlu_num"]),
    rule("medium_frequency_furnace_flag", "冶金设备", ["execution_conditions", "physics_sensor"], ["中频炉"]),
    rule("aluminum_deep_casting_flag", "冶金设备", ["execution_conditions", "physics_sensor"], ["铝加工", "深井铸造"]),
    rule("dangerous_chemical_enterprise_flag", "危化品", ["execution_conditions", "compliance", "physics_sensor"], ["危险化学品", "危化", "dangerous_chemical_enterprise"]),
    rule("dangerous_chemical_use_flag", "危化品", ["execution_conditions", "compliance"], ["危险化学品使用", "risk_whp_use_flag"]),
    rule("ammonia_refrigeration_flag", "危化品", ["execution_conditions", "physics_sensor"], ["氨制冷", "is_ammonia_refrigerating"]),
    rule("major_hazard_flag", "危化品", ["execution_conditions", "compliance"], ["重大危险源", "is_major_hazards"]),
    rule("confined_space_enterprise_flag", "有限空间", ["execution_conditions", "compliance"], ["有限空间企业", "is_finite_space"]),
    rule("confined_space_operation_flag", "有限空间", ["execution_conditions", "compliance"], ["有限空间作业", "confined_spaces_enterprise"]),
    rule("data_source", "其他可用于知识库的字段", ["warning_memory"], ["数据来源", "source", "cf_source"]),
    rule("created_time", "其他可用于知识库的字段", ["warning_memory"], ["创建时间", "创建日期", "created", "create_time"]),
    rule("updated_time", "其他可用于知识库的字段", ["warning_memory"], ["更新时间", "修改时间", "updated", "update_time"]),
    rule("delete_flag", "其他可用于知识库的字段", ["warning_memory"], ["删除标识", "deleted", "delete"]),
]

EXECUTION_CONDITION_FIELDS = {
    "unified_social_credit_code",
    "enterprise_internal_id",
    "enterprise_name",
    "industry_supervision_large",
    "national_economy_class",
    "national_economy_large",
    "national_economy_middle",
    "national_economy_small",
    "business_address",
    "longitude",
    "latitude",
    "business_status",
    "production_status",
    "enterprise_scale",
    "above_designated_flag",
    "staff_num",
    "outsourced_staff_num",
    "safety_staff_total",
    "fulltime_safety_staff_num",
    "parttime_safety_staff_num",
    "safety_dept_staff_num",
    "fulltime_cert_num",
    "parttime_cert_num",
    "special_work_cert_num",
    "safety_standardization",
    "safety_invest_ratio",
    "comply_formality_flag",
    "insurance_flag",
    "insurance_amount",
    "insured_num",
    "risk_level",
    "risk_total_count",
    "major_risk_count",
    "risk_with_accident_count",
    "trouble_total_count",
    "trouble_level_2_count",
    "trouble_unrectified_count",
    "rectification_status",
    "check_total_count",
    "check_time",
    "penalty_amount",
    "writ_total_count",
    "dust_enterprise_flag",
    "dust_dry_dedusting_system_num",
    "dust_wet_dedusting_system_num",
    "dust_clear_count",
    "metal_smelter_flag",
    "blast_furnace_num",
    "converter_num",
    "electric_furnace_num",
    "medium_frequency_furnace_flag",
    "dangerous_chemical_enterprise_flag",
    "dangerous_chemical_use_flag",
    "ammonia_refrigeration_flag",
    "major_hazard_flag",
    "confined_space_enterprise_flag",
    "confined_space_operation_flag",
}

ACCIDENT_CASE_FIELDS = {
    "unified_social_credit_code",
    "enterprise_internal_id",
    "enterprise_name",
    "risk_id",
    "risk_code",
    "risk_name",
    "risk_level",
    "major_accident_type",
    "risk_point",
    "risk_description",
    "control_measure",
    "risk_accident_flag",
    "risk_event_flag",
    "risk_with_accident_count",
    "hidden_danger_level",
    "hidden_danger_detail",
    "rectification_suggestion",
    "rectification_status",
    "trouble_level_2_count",
    "trouble_unrectified_count",
    "check_id",
    "check_time",
    "check_content",
    "writ_id",
    "writ_type_code",
    "writ_no",
    "writ_source",
    "writ_from_case_count",
    "writ_from_check_count",
    "penalty_id",
    "case_id",
    "illegal_fact",
    "penalty_basis",
    "penalty_decision",
    "penalty_amount",
    "attachment_id",
}


def clean_for_match(text: Any) -> str:
    value = "" if text is None else str(text)
    value = value.strip()
    value = re.sub(r"\.\d+$", "", value)
    value = value.replace(" ", "").replace("\u3000", "")
    return value.lower()


def safe_cell(text: Any, limit: int | None = None) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def make_unique_columns(columns: list[str]) -> tuple[list[str], list[str]]:
    seen: Counter[str] = Counter()
    unique_columns: list[str] = []
    duplicates: list[str] = []
    for column in columns:
        seen[column] += 1
        if seen[column] == 1:
            unique_columns.append(column)
            continue
        renamed = f"{column}__dup{seen[column]}"
        unique_columns.append(renamed)
        duplicates.append(f"{column} -> {renamed}")
    return unique_columns, duplicates


def pct(value: float | int | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{float(value) * 100:.1f}%"


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def read_csv_robust(path: Path) -> tuple[pd.DataFrame, str, str | None]:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk"]
    last_error: Exception | None = None
    for encoding in encodings:
        for engine in ["c", "python"]:
            try:
                df = pd.read_csv(
                    path,
                    dtype=str,
                    keep_default_na=True,
                    encoding=encoding,
                    engine=engine,
                    low_memory=False if engine == "c" else None,
                )
                return df, encoding, None
            except TypeError:
                try:
                    df = pd.read_csv(
                        path,
                        dtype=str,
                        keep_default_na=True,
                        encoding=encoding,
                        engine=engine,
                    )
                    return df, encoding, None
                except Exception as exc:  # noqa: BLE001 - record and continue.
                    last_error = exc
            except UnicodeDecodeError as exc:
                last_error = exc
                break
            except pd.errors.ParserError as exc:
                last_error = exc
                continue
            except Exception as exc:  # noqa: BLE001 - record and continue.
                last_error = exc
                continue
    message = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    raise RuntimeError(message)


def read_xlsx_sheets(path: Path) -> list[tuple[str, pd.DataFrame, str | None]]:
    sheets: list[tuple[str, pd.DataFrame, str | None]] = []
    excel = pd.ExcelFile(path)
    for sheet_name in excel.sheet_names:
        try:
            df = pd.read_excel(excel, sheet_name=sheet_name, dtype=str)
            sheets.append((sheet_name, df, None))
        except Exception as exc:  # noqa: BLE001
            sheets.append((sheet_name, pd.DataFrame(), f"{type(exc).__name__}: {exc}"))
    return sheets


def missing_profile(df: pd.DataFrame) -> dict[str, Any]:
    rows, cols = df.shape
    column_rates: dict[str, float] = {}
    missing_cells = 0

    for column in df.columns:
        series = df[column]
        nulls = int(series.isna().sum())
        if rows:
            non_null = series.dropna()
            if not non_null.empty:
                blanks = int(non_null.astype(str).str.strip().eq("").sum())
                nulls += blanks
        rate = nulls / rows if rows else 0.0
        column_rates[str(column)] = rate
        missing_cells += nulls

    total_cells = rows * cols
    overall = missing_cells / total_cells if total_cells else 0.0
    sorted_rates = sorted(column_rates.items(), key=lambda item: item[1], reverse=True)
    all_missing = [name for name, rate in sorted_rates if rate >= 0.999 and rows > 0]
    high_missing = [name for name, rate in sorted_rates if rate >= 0.8 and rows > 0]
    zero_missing_count = sum(1 for rate in column_rates.values() if rate == 0)
    return {
        "overall_missing_rate": overall,
        "column_missing_rates": column_rates,
        "top_missing": sorted_rates[:10],
        "all_missing_fields": all_missing,
        "high_missing_fields": high_missing,
        "zero_missing_field_count": zero_missing_count,
    }


def normalized_values(series: pd.Series, cap: int | None = None) -> list[str]:
    values: list[str] = []
    for item in series.dropna():
        value = str(item).strip()
        if not value:
            continue
        value = re.sub(r"\.0$", "", value)
        value = re.sub(r"\s+", "", value).upper()
        if value in {"NAN", "NONE", "NULL", "<NA>"}:
            continue
        values.append(value)
        if cap and len(values) >= cap:
            break
    return values


def credit_like_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    sample = values[:500]
    matches = sum(1 for value in sample if re.fullmatch(r"[0-9A-Z]{18}", value))
    return matches / len(sample)


def map_source_field(column: str, values: list[str]) -> tuple[str, str, list[str], str]:
    norm = clean_for_match(column)
    credit_ratio = credit_like_ratio(values)

    if credit_ratio >= 0.6 and any(token in norm for token in ["enterprise_id", "企业id", "企业ID".lower(), "id"]):
        return (
            "unified_social_credit_code",
            "企业基本信息",
            [KNOWLEDGE_BASES[key] for key in ["execution_conditions", "compliance", "warning_memory"]],
            "字段名为企业ID但值形态为18位统一社会信用代码",
        )

    for item in STANDARD_FIELD_RULES:
        if any(clean_for_match(keyword) in norm for keyword in item.keywords):
            return (
                item.standard_field,
                item.topic,
                [KNOWLEDGE_BASES[key] for key in item.kbs],
                item.note,
            )

    inferred_topic = classify_field_theme(column)
    return (
        "retain_as_raw_field",
        inferred_topic,
        [KNOWLEDGE_BASES["warning_memory"]],
        "未归入核心标准字段，建议保留原始字段用于追溯或后续人工建模",
    )


def classify_field_theme(column: str) -> str:
    norm = clean_for_match(column)
    scores: Counter[str] = Counter()
    for theme, keywords in THEME_KEYWORDS.items():
        for keyword in keywords:
            if clean_for_match(keyword) in norm:
                scores[theme] += 1
    if scores:
        return scores.most_common(1)[0][0]
    return "其他可用于知识库的字段"


def classify_table(path: Path, columns: list[str]) -> list[str]:
    haystack = " ".join([rel(path), path.stem] + columns)
    norm = clean_for_match(haystack)
    scores: Counter[str] = Counter()
    for theme, keywords in THEME_KEYWORDS.items():
        for keyword in keywords:
            if clean_for_match(keyword) in norm:
                scores[theme] += 1
    if not scores:
        return ["其他可用于知识库的字段"]
    selected = [theme for theme, score in scores.items() if score >= 1]
    selected.sort(key=lambda theme: (-scores[theme], THEMES.index(theme)))
    return selected[:6]


def is_key_candidate(column: str) -> bool:
    norm = clean_for_match(column)
    tokens = [
        "id",
        "uuid",
        "主键",
        "代码",
        "编码",
        "code",
        "统一社会信用",
        "社会信用",
        "credit",
        "报告历史",
        "计划id",
        "检查主键",
        "文书记录",
        "企业id",
        "附件",
    ]
    return any(clean_for_match(token) in norm for token in tokens)


def infer_key_type(column: str, values: list[str]) -> str:
    norm = clean_for_match(column)
    if credit_like_ratio(values) >= 0.6 or any(token in norm for token in ["统一社会信用", "社会信用代码", "信用代码", "credit"]):
        return "统一社会信用代码"
    if any(token in norm for token in ["报告历史", "risk_report", "latest_risk_report"]):
        return "风险报告/报告历史ID"
    if any(token in norm for token in ["检查主键", "记录表id", "check_id"]):
        return "检查记录ID"
    if any(token in norm for token in ["计划id", "plan_id"]):
        return "检查计划ID"
    if any(token in norm for token in ["风险代码", "risk_code"]):
        return "风险代码"
    if any(token in norm for token in ["风险表id", "risk_id"]):
        return "风险记录ID"
    if any(token in norm for token in ["文书记录id", "writ_id"]):
        return "执法文书ID"
    if "附件" in norm and "id" in norm:
        return "附件ID"
    if any(token in norm for token in ["部门id", "dept_id", "单位id"]):
        return "部门ID"
    if any(token in norm for token in ["用户id", "人员id", "承办人id", "user_id", "填报人"]):
        return "人员/用户ID"
    if any(token in norm for token in ["行政区划", "地区编码", "省编码", "市编码", "区县编码", "乡镇编码"]):
        return "行政区划代码"
    if any(token in norm for token in ["企业id", "enterprise_id", "companyid", "company_id"]):
        return "企业内部ID"
    if any(token in norm for token in ["主键", "uuid"]) or norm == "id":
        return "表内主键/UUID"
    return "其他ID/代码"


def profile_key_column(path: Path, sheet: str, column: str, series: pd.Series) -> tuple[dict[str, Any], set[str]]:
    values = normalized_values(series)
    value_set = set(values)
    non_null = len(values)
    unique = len(value_set)
    profile = {
        "source_file": rel(path),
        "sheet": sheet,
        "field": column,
        "key_type": infer_key_type(column, values),
        "non_null": non_null,
        "unique": unique,
        "unique_ratio": unique / non_null if non_null else 0.0,
        "credit_like_ratio": credit_like_ratio(values),
        "sample_values": sorted(list(value_set))[:5],
    }
    return profile, value_set


def compare_key_sets(key_sets: dict[str, set[str]], key_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {profile["key_id"]: profile for profile in key_profiles}
    grouped: dict[str, list[str]] = defaultdict(list)
    for profile in key_profiles:
        if profile["unique"] > 0:
            grouped[profile["key_type"]].append(profile["key_id"])

    results: list[dict[str, Any]] = []
    comparable_types = {
        "统一社会信用代码",
        "风险报告/报告历史ID",
        "检查记录ID",
        "检查计划ID",
        "执法文书ID",
        "附件ID",
        "企业内部ID",
        "风险代码",
        "风险记录ID",
        "部门ID",
        "人员/用户ID",
        "行政区划代码",
    }

    for key_type, ids in grouped.items():
        if key_type not in comparable_types or len(ids) < 2:
            continue
        for left, right in itertools.combinations(ids, 2):
            left_profile = by_id[left]
            right_profile = by_id[right]
            if left_profile["source_file"] == right_profile["source_file"] and left_profile["sheet"] == right_profile["sheet"]:
                continue
            left_values = key_sets[left]
            right_values = key_sets[right]
            overlap = left_values & right_values
            if not overlap:
                continue
            min_unique = min(len(left_values), len(right_values))
            max_unique = max(len(left_values), len(right_values))
            results.append(
                {
                    "key_type": key_type,
                    "left": f'{left_profile["source_file"]} [{left_profile["sheet"]}].{left_profile["field"]}',
                    "right": f'{right_profile["source_file"]} [{right_profile["sheet"]}].{right_profile["field"]}',
                    "overlap": len(overlap),
                    "overlap_min_ratio": len(overlap) / min_unique if min_unique else 0.0,
                    "overlap_max_ratio": len(overlap) / max_unique if max_unique else 0.0,
                    "sample_values": sorted(list(overlap))[:5],
                }
            )
    results.sort(key=lambda item: (item["key_type"], -item["overlap"], -item["overlap_min_ratio"]))
    return results[:250]


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_无_"
    lines = [
        "| " + " | ".join(safe_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(safe_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def summarize_sources(records: list[dict[str, Any]], standard_fields: set[str]) -> list[list[Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["standard_field"] in standard_fields:
            grouped[record["standard_field"]].append(record)

    rows: list[list[Any]] = []
    for standard_field in sorted(grouped):
        items = grouped[standard_field]
        topics = sorted({item["topic"] for item in items})
        raw_fields = []
        source_files = []
        for item in items:
            raw_fields.append(item["source_field"])
            source_files.append(item["source_file"])
        rows.append(
            [
                standard_field,
                "、".join(topics),
                len(items),
                "；".join(sorted(set(raw_fields))[:8]),
                "；".join(sorted(set(source_files))[:6]),
            ]
        )
    return rows


def aggregation_hint(standard_field: str) -> str:
    if standard_field.endswith("_count") or standard_field.endswith("_num") or standard_field in {
        "penalty_amount",
        "insurance_amount",
        "insured_num",
        "staff_num",
        "fixed_assets",
        "last_year_income",
    }:
        return "按企业聚合取最新值/求和；历史事实保留时间维度"
    if standard_field.endswith("_flag"):
        return "按企业取最新有效标志；多源冲突时保留来源置信度"
    if "status" in standard_field or "level" in standard_field:
        return "按时间取最新状态，同时保留最高风险/最严重等级"
    if "time" in standard_field or standard_field.endswith("_date"):
        return "作为事件时间线字段，不直接求和"
    return "维度字段，按主键桥表去重后回填"


def write_mapping_csv(records: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    headers = [
        "source_file",
        "format",
        "sheet",
        "source_field",
        "standard_field",
        "topic",
        "target_knowledge_bases",
        "missing_rate",
        "note",
    ]
    with MAPPING_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in headers})


def build_report(
    table_records: list[dict[str, Any]],
    mapping_records: list[dict[str, Any]],
    key_profiles: list[dict[str, Any]],
    join_candidates: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_files = len({record["source_file"] for record in table_records})
    total_sheets = len(table_records)
    total_rows = sum(record["rows"] for record in table_records)
    total_columns = sum(record["columns"] for record in table_records)
    ext_counts = Counter(record["format"] for record in table_records)
    theme_counts: Counter[str] = Counter()
    for record in table_records:
        for theme in record["themes"]:
            theme_counts[theme] += 1

    lines: list[str] = []
    lines.append("# 公开数据企业数据全量盘点与字段映射报告")
    lines.append("")
    lines.append(f"- 生成时间：{generated_at}")
    lines.append(f"- 扫描范围：`{PUBLIC_DATA_ROOT}` 及所有子目录")
    lines.append(f"- 只读分析脚本：`{rel(Path(__file__))}`")
    lines.append(f"- 逐字段映射明细：`{rel(MAPPING_CSV_PATH)}`")
    lines.append(f"- 机器可读盘点：`{rel(INVENTORY_JSON_PATH)}`")
    lines.append("")

    lines.append("## 1. 总览")
    lines.append("")
    rows = [
        ["文件数", total_files],
        ["sheet/表数", total_sheets],
        ["总行数", total_rows],
        ["总字段出现次数", total_columns],
        ["CSV 表数", ext_counts.get(".csv", 0)],
        ["XLSX sheet 数", ext_counts.get(".xlsx", 0)],
        ["读取异常/提示数", len(errors)],
    ]
    lines.append(markdown_table(["指标", "值"], rows))
    lines.append("")
    lines.append("业务主题覆盖：")
    lines.append("")
    lines.append(markdown_table(["主题", "命中文件/sheet 数"], [[theme, theme_counts.get(theme, 0)] for theme in THEMES]))
    lines.append("")

    if errors:
        lines.append("### 读取异常/数据提示")
        lines.append("")
        lines.append(markdown_table(["文件", "sheet", "错误"], [[item["source_file"], item.get("sheet", ""), item["error"]] for item in errors]))
        lines.append("")

    lines.append("## 2. 文件与字段清单")
    lines.append("")
    lines.append("每个 CSV 视为一个 `CSV` sheet；每个 XLSX 按实际 sheet 展开。字段列表保留原始表头，缺失率概览给出整体缺失率、全空字段、80% 以上高缺失字段和缺失率最高字段。")
    lines.append("")

    for index, record in enumerate(sorted(table_records, key=lambda item: (item["source_file"], item["sheet"])), 1):
        lines.append(f"### 2.{index} `{record['source_file']}` / `{record['sheet']}`")
        lines.append("")
        lines.append(f"- 格式：`{record['format']}`")
        lines.append(f"- 行数 / 列数：{record['rows']} / {record['columns']}")
        lines.append(f"- sheet 名：`{record['sheet']}`")
        lines.append(f"- 业务主题：{'、'.join(record['themes'])}")
        lines.append(f"- 缺失率概览：整体 {pct(record['overall_missing_rate'])}；零缺失字段 {record['zero_missing_field_count']} 个；全空字段 {len(record['all_missing_fields'])} 个；高缺失字段 {len(record['high_missing_fields'])} 个")
        if record["top_missing"]:
            top_missing = "；".join(f"{name} {pct(rate)}" for name, rate in record["top_missing"])
            lines.append(f"- 缺失率最高字段：{safe_cell(top_missing, 900)}")
        if record["all_missing_fields"]:
            lines.append(f"- 全空字段：{safe_cell('；'.join(record['all_missing_fields']), 900)}")
        lines.append("")
        lines.append("字段列表：")
        lines.append("")
        lines.append("`" + safe_cell("`、`".join(record["fields"])) + "`")
        lines.append("")

    lines.append("## 3. 按业务主题归类")
    lines.append("")
    for theme in THEMES:
        themed_tables = [record for record in table_records if theme in record["themes"]]
        themed_fields = sorted(
            {
                item["source_field"]
                for item in mapping_records
                if item["topic"] == theme
            }
        )
        lines.append(f"### {theme}")
        lines.append("")
        if themed_tables:
            lines.append("- 文件/sheet：")
            for record in themed_tables[:40]:
                lines.append(f"  - `{record['source_file']}` / `{record['sheet']}` ({record['rows']} 行, {record['columns']} 列)")
            if len(themed_tables) > 40:
                lines.append(f"  - ……另有 {len(themed_tables) - 40} 个 sheet")
        else:
            lines.append("- 文件/sheet：未命中")
        if themed_fields:
            lines.append(f"- 代表字段：{safe_cell('；'.join(themed_fields[:60]), 1200)}")
        lines.append("")

    lines.append("## 4. 源文件字段到标准字段映射")
    lines.append("")
    lines.append("下表是按标准字段聚合后的映射索引；完整逐字段、逐文件映射见同目录 CSV。`retain_as_raw_field` 表示暂未纳入核心标准字段，但仍建议保留原始字段供溯源和后续建模。")
    lines.append("")

    grouped_mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in mapping_records:
        grouped_mapping[record["standard_field"]].append(record)
    mapping_rows: list[list[Any]] = []
    for standard_field, items in sorted(grouped_mapping.items()):
        topics = sorted({item["topic"] for item in items})
        kbs = sorted({kb for item in items for kb in item["target_knowledge_bases"].split(";") if kb})
        raw_fields = sorted({item["source_field"] for item in items})
        source_files = sorted({item["source_file"] for item in items})
        mapping_rows.append(
            [
                standard_field,
                "、".join(topics),
                len(items),
                "；".join(raw_fields[:12]),
                "；".join(source_files[:8]),
                "；".join(kbs[:6]),
            ]
        )
    lines.append(markdown_table(["标准字段", "主题", "字段出现次数", "源字段示例", "源文件示例", "服务知识库"], mapping_rows))
    lines.append("")

    lines.append("## 5. 可补齐“企业已具备的执行条件.md”的字段")
    lines.append("")
    execution_rows = summarize_sources(mapping_records, EXECUTION_CONDITION_FIELDS)
    execution_rows = [row + [aggregation_hint(row[0])] for row in execution_rows]
    lines.append(markdown_table(["标准字段", "主题", "命中次数", "源字段示例", "源文件示例", "建议处理"], execution_rows))
    lines.append("")
    lines.append("重点可用信息包括：设备数量（高炉/转炉/电炉、干/湿式除尘系统）、人员数量、安全管理人员和持证人数、风险类型/等级/数量、隐患数量和整改状态、检查频次、处罚金额/文书数量、行业分类、经纬度/地址、经营/生产状态。")
    lines.append("")

    lines.append("## 6. 可构建“类似事故处理案例.md”的字段")
    lines.append("")
    accident_rows = summarize_sources(mapping_records, ACCIDENT_CASE_FIELDS)
    accident_rows = [row + [aggregation_hint(row[0])] for row in accident_rows]
    lines.append(markdown_table(["标准字段", "主题", "命中次数", "源字段示例", "源文件示例", "建议处理"], accident_rows))
    lines.append("")
    lines.append("当前公开表中未发现独立、规范的“事故ID”字段；可用 `风险记录ID/风险代码 + 是否发生事故/事件 + 事故概述 + 重大或未整改隐患 + 处罚/文书记录` 组合生成案例候选 ID。")
    lines.append("")

    lines.append("## 7. 主键/外键与 Join 可行性")
    lines.append("")
    key_rows = [
        [
            item["key_type"],
            item["source_file"],
            item["sheet"],
            item["field"],
            item["non_null"],
            item["unique"],
            f'{item["unique_ratio"]:.3f}',
            f'{item["credit_like_ratio"]:.3f}',
            "；".join(item["sample_values"]),
        ]
        for item in sorted(key_profiles, key=lambda item: (item["key_type"], item["source_file"], item["field"]))
    ]
    lines.append("### 7.1 候选键字段画像")
    lines.append("")
    lines.append(markdown_table(["键类型", "文件", "sheet", "字段", "非空", "唯一值", "唯一率", "信用代码形态", "样例"], key_rows[:300]))
    if len(key_rows) > 300:
        lines.append("")
        lines.append(f"_候选键字段共 {len(key_rows)} 个，报告仅展示前 300 个；完整内容在 JSON 中。_")
    lines.append("")

    lines.append("### 7.2 可 Join 候选")
    lines.append("")
    join_rows = [
        [
            item["key_type"],
            item["left"],
            item["right"],
            item["overlap"],
            f'{item["overlap_min_ratio"]:.3f}',
            f'{item["overlap_max_ratio"]:.3f}',
            "；".join(item["sample_values"]),
        ]
        for item in join_candidates
    ]
    lines.append(markdown_table(["键类型", "左表字段", "右表字段", "交集数", "较小表覆盖率", "较大表覆盖率", "交集样例"], join_rows[:160]))
    if len(join_rows) > 160:
        lines.append("")
        lines.append(f"_Join 候选共 {len(join_rows)} 条，报告仅展示前 160 条；完整内容在 JSON 中。_")
    lines.append("")

    lines.append("### 7.3 ID 体系兼容性判断")
    lines.append("")
    lines.append("- 统一社会信用代码是最稳的企业级 join 键：`new_已清洗.xlsx` 的 `enterprise_id` 值形态为 18 位信用代码，可与包含 `统一社会信用代码/社会信用代码` 的企业目录、日常检查、粉尘清扫等表对齐。")
    lines.append("- `报告历史ID/报告历史id` 可连接风险报告明细、安全管理信息、风险项等同一风险报告链路；但需要区分大小写/中英文导出字段，并以数值字符串规范化后再 join。")
    lines.append("- `企业ID` 存在两类含义：一类是信用代码形态，另一类是平台内部 UUID/流水 ID。只有前者能直接与企业目录 join；后者必须通过企业信息表或专门桥表回填信用代码。")
    lines.append("- `主键ID/主键id/id/uuid` 多数是表内主键，不能跨表直接 join；仅在同一业务链路中有明确外键字段时使用，例如 `检查主键ID` 到隐患表、`计划id` 到检查计划表。")
    lines.append("- `ds_aczf_*` 执法处罚/文书表有独立执法系统 ID；如无信用代码字段，应先通过 `st_ds_aczf_enterprise` 或 `企业id` 桥接，再回到企业主档。")
    lines.append("- `zjj_house_*` 房屋安全表以房屋/图斑 ID 为主，与工矿企业 ID 体系不天然兼容；除非地址或经营主体可匹配，否则只适合作为地理/建筑风险侧信息。")
    lines.append("")

    lines.append("## 8. 重建企业执行条件知识库的数据方案")
    lines.append("")
    lines.append("1. 建立 Bronze 原始层：逐文件逐 sheet 入库，保留 `source_file`、`sheet`、`source_row_number`、读取编码、字段原名和读取时间，不覆盖任何公开数据。")
    lines.append("2. 建立企业主键桥表：优先以统一社会信用代码为 `enterprise_key`；对内部 `企业ID`、执法系统 `企业id`、报告历史 ID 建 `id_crosswalk`，记录来源、有效期和冲突情况。")
    lines.append("3. 建立 Silver 标准事实表：`dim_enterprise`、`dim_geo`、`dim_industry`、`fact_risk_item`、`fact_risk_report`、`fact_check`、`fact_trouble`、`fact_writ`、`fact_penalty`、`fact_safety_capability`、`fact_dust_record`、`fact_production_status`、`dim_dept_user`。")
    lines.append("4. 生成 Gold 表 `enterprise_execution_conditions`：一企一行，聚合人员/持证、设备数量、危化/粉尘/冶金/有限空间标签、最新风险等级、近 N 次检查、未整改隐患、重大隐患、处罚金额、文书数量、生产/经营状态、经纬度和行业。")
    lines.append("5. 生成 Gold 表 `accident_case_candidates`：以事故标志、事故概述、重大隐患、未整改隐患、行政处罚、执法文书、检查问题为事件源，按企业和时间线合并，形成案例标题、触发因素、处置依据、整改闭环状态。")
    lines.append("6. 知识库写入策略：`企业已具备的执行条件.md` 只写 Gold 表摘要和关键证据链；`类似事故处理案例.md` 写案例卡片；`预警历史经验与短期记忆摘要.md` 写事件时间线；其余知识库通过标准字段引用事实来源，不直接塞原始宽表。")
    lines.append("7. 质量门槛：每次重建前输出行数校验、主键覆盖率、重复企业数、核心字段缺失率、跨表 join 覆盖率和异常 ID 清单；低覆盖字段先保留为空，不用伪造默认值。")
    lines.append("")

    lines.append("## 9. 附：目标知识库映射口径")
    lines.append("")
    kb_rows = [
        [KNOWLEDGE_BASES["compliance"], "风险等级、重大隐患、违法处罚、执法文书、管控措施、处置责任部门"],
        [KNOWLEDGE_BASES["dept_sop"], "部门/人员、检查计划、提交/审核/执法状态、地区监管主体"],
        [KNOWLEDGE_BASES["physics_sensor"], "粉尘涉爆、冶金设备、危化品、有限空间、风险点、事故类型、管控措施"],
        [KNOWLEDGE_BASES["execution_conditions"], "人员持证、设备数量、风险/隐患/整改、检查频次、处罚、行业、位置、生产状态"],
        [KNOWLEDGE_BASES["accident_cases"], "事故标志/概述、重大隐患、未整改隐患、检查问题、处罚、文书、风险项"],
        [KNOWLEDGE_BASES["warning_memory"], "报告时间、检查/隐患/处罚/文书时间线、数据来源、创建更新时间"],
    ]
    lines.append(markdown_table(["知识库", "主要字段口径"], kb_rows))
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [
            path
            for path in PUBLIC_DATA_ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"}
        ]
    )
    print(f"Scanning {len(files)} files under {PUBLIC_DATA_ROOT}")

    table_records: list[dict[str, Any]] = []
    mapping_records: list[dict[str, Any]] = []
    key_profiles: list[dict[str, Any]] = []
    key_sets: dict[str, set[str]] = {}
    errors: list[dict[str, str]] = []

    for file_index, path in enumerate(files, 1):
        print(f"[{file_index}/{len(files)}] {rel(path)}")
        suffix = path.suffix.lower()
        sheet_items: list[tuple[str, pd.DataFrame, str | None, str | None]] = []
        try:
            if suffix == ".csv":
                df, encoding, warning = read_csv_robust(path)
                sheet_items.append(("CSV", df, encoding, warning))
            else:
                for sheet_name, df, warning in read_xlsx_sheets(path):
                    sheet_items.append((sheet_name, df, None, warning))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source_file": rel(path), "sheet": "", "error": f"{type(exc).__name__}: {exc}"})
            table_records.append(
                {
                    "source_file": rel(path),
                    "format": suffix,
                    "sheet": "UNREADABLE",
                    "encoding": "",
                    "rows": 0,
                    "columns": 0,
                    "fields": [],
                    "themes": classify_table(path, []),
                    "overall_missing_rate": 0.0,
                    "top_missing": [],
                    "all_missing_fields": [],
                    "high_missing_fields": [],
                    "zero_missing_field_count": 0,
                }
            )
            continue

        for sheet_name, df, encoding, warning in sheet_items:
            if warning:
                errors.append({"source_file": rel(path), "sheet": sheet_name, "error": warning})
            original_columns = [str(column).strip() for column in df.columns]
            unique_columns, duplicate_columns = make_unique_columns(original_columns)
            df.columns = unique_columns
            if duplicate_columns:
                errors.append(
                    {
                        "source_file": rel(path),
                        "sheet": sheet_name,
                        "error": "重复字段已追加 __dupN 后缀: " + "；".join(duplicate_columns[:12]),
                    }
                )
            fields = list(df.columns)
            miss = missing_profile(df)
            themes = classify_table(path, fields)
            table_record = {
                "source_file": rel(path),
                "format": suffix,
                "sheet": sheet_name,
                "encoding": encoding or "",
                "rows": int(df.shape[0]),
                "columns": int(df.shape[1]),
                "fields": fields,
                "themes": themes,
                "overall_missing_rate": miss["overall_missing_rate"],
                "top_missing": miss["top_missing"],
                "all_missing_fields": miss["all_missing_fields"],
                "high_missing_fields": miss["high_missing_fields"],
                "zero_missing_field_count": miss["zero_missing_field_count"],
            }
            table_records.append(table_record)

            for column in fields:
                values = normalized_values(df[column], cap=500)
                standard_field, topic, target_kbs, note = map_source_field(column, values)
                mapping_records.append(
                    {
                        "source_file": rel(path),
                        "format": suffix,
                        "sheet": sheet_name,
                        "source_field": column,
                        "standard_field": standard_field,
                        "topic": topic,
                        "target_knowledge_bases": ";".join(target_kbs),
                        "missing_rate": f"{miss['column_missing_rates'].get(column, 0.0):.6f}",
                        "note": note,
                    }
                )

                if is_key_candidate(column):
                    profile, values_set = profile_key_column(path, sheet_name, column, df[column])
                    key_id = f"{rel(path)}::{sheet_name}::{column}"
                    profile["key_id"] = key_id
                    key_profiles.append(profile)
                    key_sets[key_id] = values_set

    join_candidates = compare_key_sets(key_sets, key_profiles)
    write_mapping_csv(mapping_records)

    json_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "public_data_root": str(PUBLIC_DATA_ROOT),
        "table_records": table_records,
        "mapping_csv": rel(MAPPING_CSV_PATH),
        "key_profiles": [
            {key: value for key, value in profile.items() if key != "key_id"}
            for profile in key_profiles
        ],
        "join_candidates": join_candidates,
        "errors": errors,
    }
    INVENTORY_JSON_PATH.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(table_records, mapping_records, key_profiles, join_candidates, errors)
    REPORT_PATH.write_text(report, encoding="utf-8-sig")
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {MAPPING_CSV_PATH}")
    print(f"Wrote {INVENTORY_JSON_PATH}")


if __name__ == "__main__":
    main()
