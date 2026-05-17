"""
企业CSV数据融合脚本：一键生成/增量填充6个核心Markdown知识库文件

用法：
    python scripts/init_knowledge_base.py --data-dir datasets/raw/public
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from _bootstrap import setup_project_paths

setup_project_paths()

from mining_risk_common.dataplane.loader import DataLoader
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)

# 6个核心知识库文件名
KNOWLEDGE_FILES = [
    "工矿风险预警智能体合规执行书.md",
    "部门分级审核SOP.md",
    "工业物理常识及传感器时间序列逻辑.md",
    "企业已具备的执行条件.md",
    "类似事故处理案例.md",
    "预警历史经验与短期记忆摘要.md",
]

# 传感器/设备字段映射（基于CSV中的字段）
EQUIPMENT_FIELDS = [
    "集中除尘系统干式数量",
    "集中除尘系统湿式数量",
    "高炉数量",
    "转炉数量",
    "电炉数量",
    "煤气柜数量",
    "氨罐数量",
    "深井浇筑系统数量",
    "钢丝绳式提升装置数量",
    "液压式提升装置数量",
    "熔炼炉事故联锁装置",
    "流槽及铸造系统事故联锁装置",
]

# 企业类型标识字段
ENTERPRISE_TYPE_FIELDS = [
    "存在附属污水处理设施设备企业",
    "存在造纸企业",
    "存在酱腌菜企业",
    "涉炉企业内容",
    "粉尘涉爆企业内容",
    "有限空间企业内容",
    "钢铁企业内容",
    "铝加工企业内容",
    "危化品企业内容",
]


def find_csv_files(data_dir: str) -> Dict[str, str]:
    """在数据目录中递归查找目标CSV文件"""
    targets = {
        "szs_enterprise_information": None,
        "szs_enterprise_industry_category": None,
        "szs_enterprise_safety": None,
        "szs_enterprise_risk": None,
        "st_ds_aczf_enterprise": None,
    }
    data_path = Path(data_dir)
    for root, _, files in os.walk(data_path):
        for f in files:
            if not f.endswith(".csv"):
                continue
            for key in targets:
                if key in f:
                    targets[key] = os.path.join(root, f)
                    break
    return targets


def find_feature_summary(data_dir: str) -> Optional[str]:
    """查找特征汇总Excel文件"""
    data_path = Path(data_dir)
    for root, _, files in os.walk(data_path):
        for f in files:
            if "特征汇总" in f and f.endswith(".xlsx"):
                return os.path.join(root, f)
    return None


def load_dataframes(files: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """加载所有目标CSV为DataFrame"""
    loader = DataLoader()
    dfs = {}
    for name, path in files.items():
        if path and os.path.exists(path):
            try:
                dfs[name] = loader.load_file(path)
                logger.info(f"加载 {name}: {dfs[name].shape}")
            except Exception as e:
                logger.warning(f"加载 {name} 失败: {e}")
        else:
            logger.warning(f"未找到 {name} 的CSV文件")
    return dfs


def _ensure_kb_dir(kb_dir: str) -> None:
    os.makedirs(kb_dir, exist_ok=True)
    os.makedirs(os.path.join(kb_dir, "raw_texts"), exist_ok=True)


def _write_md(kb_dir: str, filename: str, content: str) -> None:
    path = os.path.join(kb_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"已生成知识库文件: {path} ({len(content)} 字符)")


def _read_existing_md(kb_dir: str, filename: str) -> str:
    path = os.path.join(kb_dir, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _df_to_markdown_table(df: pd.DataFrame, max_rows: int = 100) -> str:
    """将DataFrame转为Markdown表格"""
    df = df.head(max_rows)
    lines = []
    lines.append("| " + " | ".join(str(c) for c in df.columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(df.columns)) + " |")
    for _, row in df.iterrows():
        vals = [str(v) if pd.notna(v) else "" for v in row.values]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def generate_compliance(kb_dir: str, dfs: Dict[str, pd.DataFrame], feature_meta: str = "") -> None:
    """生成《工矿风险预警智能体合规执行书.md》"""
    filename = "工矿风险预警智能体合规执行书.md"
    existing = _read_existing_md(kb_dir, filename)
    
    # 提取风险类型用于合规红线
    risk_types = set()
    if "szs_enterprise_risk" in dfs:
        df = dfs["szs_enterprise_risk"]
        if "主要事故类别" in df.columns:
            risk_types = set(df["主要事故类别"].dropna().unique())
    
    lines = [
        "# 工矿风险预警智能体合规执行书",
        "",
        "> 生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "> 数据来源: 公开数据 + 爬取法规".format(),
        "",
        "## 一、合规红线",
        "",
        "| 序号 | 红线内容 | 违规后果 | 触发等级 |",
        "|------|---------|---------|---------|",
        "| 1 | 瓦斯浓度超限时未立即撤人、断电 | 重大事故 | 红 |",
        "| 2 | 通风系统擅自停运或改造 | 群死群伤 | 红 |",
        "| 3 | 特种作业人员无证上岗 | 行政处罚+停产 | 橙 |",
        "| 4 | 重大危险源未登记建档 | 罚款+限期整改 | 橙 |",
        "| 5 | 安全培训记录缺失 | 警告+补训 | 黄 |",
    ]
    
    if risk_types:
        lines.extend(["", "### 基于企业数据识别的风险红线", ""])
        for i, rt in enumerate(list(risk_types)[:20], 6):
            lines.append(f"| {i} | 涉及{rt}的重大隐患 | 按对应预案处置 | 橙 |")
        lines.append("")
    
    lines.extend([
        "## 二、工况逻辑",
        "",
        "### 2.1 高风险设备联锁逻辑",
        "- 高炉/转炉/电炉区域：温度异常+煤气泄漏→立即切断气源并启动氮气吹扫",
        "- 涉粉爆炸区域：除尘系统停运+粉尘浓度超标→立即停机并启动惰化保护",
        "- 危化品储罐：压力超限+温度异常→启动紧急泄压与喷淋降温",
        "- 深井铸造：提升装置故障+液位异常→立即停止浇筑并疏散人员",
        "",
        "### 2.2 传感器判异规则",
        "- 单点偏离滑动窗口均值 3σ 以上 → 异常突变",
        "- 连续5个点同向单调变化且斜率超过历史基线 20% → 趋势异常",
        "- 偏离日/周周期性规律幅度超过 30% → 周期异常",
        "",
        "## 三、处置可行性",
        "",
        "### 3.1 政府侧处置能力",
        "| 处置等级 | 责任部门 | 响应时限 | 所需装备 |",
        "|---------|---------|---------|---------|",
        "| 红 | 省级应急厅+属地局 | 2小时 | 气体检测仪、防爆设备 |",
        "| 橙 | 属地应急管理局 | 24小时 | 执法记录仪、检测工具 |",
        "| 黄 | 区县级安监站 | 7天 | 检查清单、整改通知书 |",
        "| 蓝 | 企业安全部 | 15天 | 自查表、培训材料 |",
        "",
        "### 3.2 企业侧处置条件",
        "- 微型消防站 3分钟内到达现场",
        "- 应急物资 10分钟内调取到位",
        "- 每年至少组织 2 次综合应急演练",
        "- 安全管理人员持证率 100%",
        "",
    ])
    
    if feature_meta:
        lines.extend(["## 附录：字段元数据", "", feature_meta, ""])
    
    content = "\n".join(lines)
    # 如果已有内容，追加更新标记
    if existing and len(existing) > 50:
        content = existing + "\n\n---\n\n## 增量更新 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + content.split("## 一、合规红线")[0] + "\n" + "## 一、合规红线" + content.split("## 一、合规红线")[1]
    
    _write_md(kb_dir, filename, content)


def generate_sop(kb_dir: str, dfs: Dict[str, pd.DataFrame]) -> None:
    """生成《部门分级审核SOP.md》"""
    filename = "部门分级审核SOP.md"
    existing = _read_existing_md(kb_dir, filename)
    
    lines = [
        "# 部门分级审核 SOP",
        "",
        "> 生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "",
        "## 一、两级终审流程",
        "",
        "### 第一级：智能体预审",
        "1. 接收企业上报数据，执行完整性校验",
        "2. 调用Stacking模型进行风险评级（红/橙/黄/蓝）",
        "3. 提取Top3特征贡献度，生成初步处置建议",
        "4. 对照合规执行书进行红线校验",
        "5. 输出预审报告，标记需要人工复核的项",
        "",
        "### 第二级：监管部门终审",
        "| 风险等级 | 终审部门 | 责任人 | 审批流程 | 时限要求 |",
        "|---------|---------|--------|---------|---------|",
        "| 红 | 省级监管部门 + 属地应急局 | 局领导/分管副厅 | 立即上报 → 联合执法 → 停产决定 | 2小时 |",
        "| 橙 | 属地应急管理局 + 行业主管 | 科长/处长 | 现场核查 → 整改通知 → 复查验收 | 24小时 |",
        "| 黄 | 区县级安监站 + 乡镇街道 | 站长/主任 | 现场检查 → 限期整改 → 跟踪闭环 | 7天 |",
        "| 蓝 | 企业安全管理部门 | 安全总监 | 自查自纠 → 记录归档 | 15天 |",
        "",
        "## 二、路由规则",
        "",
        "### 2.1 自动通过条件",
        "- 风险等级为蓝，且无红线违规项",
        "- 企业近3个月无新增重大隐患",
        "- 安全管理人员持证率 = 100%",
        "- 上次整改复查已通过",
        "",
        "### 2.2 强制人工复核条件",
        "- 风险等级为红或橙",
        "- 触发任何合规红线",
        "- 模型置信度 < 0.85",
        "- 企业近30天内发生过事故/事件",
        "- 关键传感器数据缺失超过 20%",
        "",
        "### 2.3 跨部门协同规则",
        "- 危化品企业红级 → 同步通知消防、环保、公安",
        "- 粉尘涉爆企业橙级 → 同步通知市场监管、消防",
        "- 有限空间作业黄级 → 同步通知人社、卫健",
        "- 钢铁企业红级 → 同步通知工信、能源部门",
        "",
        "## 三、责任人清单模板",
        "",
        "| 部门 | 姓名 | 职务 | 联系方式 | 负责领域 |",
        "|------|------|------|---------|---------|",
        "| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |",
        "",
    ]
    
    content = "\n".join(lines)
    if existing and len(existing) > 50:
        content = existing + "\n\n---\n\n## 增量更新 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + content
    
    _write_md(kb_dir, filename, content)


def generate_physics(kb_dir: str, dfs: Dict[str, pd.DataFrame]) -> None:
    """生成《工业物理常识及传感器时间序列逻辑.md》"""
    filename = "工业物理常识及传感器时间序列逻辑.md"
    existing = _read_existing_md(kb_dir, filename)
    
    # 从行业分类表统计设备类型分布
    equip_stats = {}
    if "szs_enterprise_industry_category" in dfs:
        df = dfs["szs_enterprise_industry_category"]
        for field in EQUIPMENT_FIELDS:
            if field in df.columns:
                non_null = df[field].dropna()
                if len(non_null) > 0:
                    # 对数值型统计有值的企业数
                    try:
                        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
                        count = (numeric > 0).sum()
                        if count > 0:
                            equip_stats[field] = int(count)
                    except Exception:
                        pass
    
    lines = [
        "# 工业物理常识及传感器时间序列逻辑",
        "",
        "> 生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "> 基于企业CSV设备字段自动生成".format(),
        "",
        "## 一、常见传感器参数范围与阈值",
        "",
    ]
    
    # 根据实际设备类型生成对应阈值表
    device_thresholds = [
        ("瓦斯（甲烷）传感器", "CH₄浓度", "0%~0.5%", "≥0.8%", "≥1.0%", "≥1.5%"),
        ("温度传感器", "环境温度", "15°C~30°C", "≥35°C", "≥40°C", "-"),
        ("温度传感器", "设备表面", "40°C~60°C", "≥70°C", "≥80°C", "-"),
        ("压力传感器", "管道压力", "0.3~0.6MPa", "<0.2MPa", ">0.8MPa", "-"),
        ("湿度传感器", "相对湿度", "40%~70%", ">85%", "<20%", "-"),
        ("粉尘浓度传感器", "涉粉作业区", "<10mg/m³", "≥20mg/m³", "≥50mg/m³", "-"),
        ("煤气传感器", "CO浓度", "0~24ppm", "≥50ppm", "≥100ppm", "≥200ppm"),
        ("液位传感器", "储罐液位", "20%~80%", "<10%", ">90%", "-"),
    ]
    
    lines.extend([
        "| 传感器类型 | 监测参数 | 正常范围 | 预警阈值 | 报警阈值 | 断电/紧急阈值 |",
        "|-----------|---------|---------|---------|---------|--------------|",
    ])
    for dev, param, normal, warn, alarm, emergency in device_thresholds:
        lines.append(f"| {dev} | {param} | {normal} | {warn} | {alarm} | {emergency} |")
    lines.append("")
    
    if equip_stats:
        lines.extend([
            "## 一（附）企业实际装备统计",
            "",
            "| 设备/系统类型 | 涉及企业数 |",
            "|-------------|-----------|",
        ])
        for field, count in sorted(equip_stats.items(), key=lambda x: -x[1]):
            lines.append(f"| {field} | {count} |")
        lines.append("")
    
    lines.extend([
        "## 二、时间序列异常判断规则",
        "",
        "1. **突变检测**：单点值偏离滑动窗口均值 3σ 以上，标记为异常突变",
        "2. **趋势检测**：连续5个点同向单调变化且斜率超过历史基线 20%",
        "3. **周期异常**：偏离日/周周期性规律的幅度超过 30%",
        "4. **关联异常**：",
        "   - 瓦斯浓度上升 + 温度下降 → 通风异常",
        "   - 温度上升 + 压力上升 → 燃烧/爆炸风险",
        "   - 湿度上升 + 电气设备温度上升 → 绝缘失效风险",
        "   - 振动上升 + 噪声上升 → 机械故障前兆",
        "   - 粉尘浓度上升 + 除尘系统电流下降 → 除尘失效",
        "   - 煤气柜压力上升 + 温度异常 → 泄漏/燃烧风险",
        "",
        "## 三、物理量关联逻辑与联动规则",
        "",
        "### 3.1 高炉/转炉区域",
        "- 炉顶温度 > 350°C 且 冷却水流量 < 基线 80% → 立即降负荷",
        "- 煤气含氧量 > 1% → 切断煤气并充氮",
        "- 炉壳温度 > 报警值 → 停炉检查耐火材料",
        "",
        "### 3.2 涉粉爆炸区域",
        "- 除尘系统压差 > 1500Pa → 清灰或更换滤袋",
        "- 作业区粉尘浓度 > 20mg/m³ 且 湿度 < 30% → 增加湿式清扫",
        "- 铝镁粉尘作业区温度 > 40°C → 停止作业并检查热源",
        "",
        "### 3.3 危化品储罐区",
        "- 储罐压力 > 设计压力 80% → 启动泄压阀",
        "- 液位变化速率 > 正常值 2倍 → 排查泄漏或误操作",
        "- 围堰内气体检测仪报警 → 禁止一切动火作业",
        "",
        "### 3.4 深井铸造区域",
        "- 铸造液位波动 > ±5% → 检查供液泵与流量阀",
        "- 提升装置速度偏差 > 10% → 立即停止并排查钢丝绳",
        "- 冷却水温度 > 进水温度 + 15°C → 增加冷却水流量",
        "",
    ])
    
    content = "\n".join(lines)
    if existing and len(existing) > 50:
        content = existing + "\n\n---\n\n## 增量更新 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + content
    
    _write_md(kb_dir, filename, content)


def generate_conditions(kb_dir: str, dfs: Dict[str, pd.DataFrame]) -> None:
    """生成《企业已具备的执行条件.md》"""
    filename = "企业已具备的执行条件.md"
    existing = _read_existing_md(kb_dir, filename)
    
    # 合并企业信息表、安全表、行业分类表
    merged = None
    if "szs_enterprise_information" in dfs:
        merged = dfs["szs_enterprise_information"].copy()
    if merged is not None and "szs_enterprise_safety" in dfs:
        safety = dfs["szs_enterprise_safety"]
        # 根据主键ID合并
        if "主键ID" in merged.columns and "主键ID" in safety.columns:
            # 避免列名冲突
            overlap = [c for c in safety.columns if c in merged.columns and c != "主键ID"]
            safety_renamed = safety.rename(columns={c: f"safety_{c}" for c in overlap})
            merged = merged.merge(safety_renamed, on="主键ID", how="left")
    if merged is not None and "szs_enterprise_industry_category" in dfs:
        industry = dfs["szs_enterprise_industry_category"]
        if "主键ID" in merged.columns and "主键ID" in industry.columns:
            overlap = [c for c in industry.columns if c in merged.columns and c != "主键ID"]
            industry_renamed = industry.rename(columns={c: f"industry_{c}" for c in overlap})
            merged = merged.merge(industry_renamed, on="主键ID", how="left")
    
    lines = [
        "# 企业已具备的执行条件",
        "",
        "> 生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "> 基于企业安全设施与人员资质数据自动生成".format(),
        "",
        "## 一、企业安全设施与人员配置清单",
        "",
    ]
    
    if merged is not None and len(merged) > 0:
        # 选取关键字段构建表格
        key_cols = ["主键ID"]
        if "企业名称" in merged.columns:
            key_cols.append("企业名称")
        elif "safety_企业主要负责人" in merged.columns:
            key_cols.append("safety_企业主要负责人")
        
        # 安全设施字段
        facility_cols = []
        for col in merged.columns:
            if any(k in col for k in EQUIPMENT_FIELDS):
                facility_cols.append(col)
        
        # 人员资质字段
        personnel_cols = []
        for col in merged.columns:
            if any(k in col for k in ["安全管理人员", "专职安全生产管理", "兼职安全生产管理", "特种作业", "企业职工总人数"]):
                personnel_cols.append(col)
        
        display_cols = key_cols + facility_cols + personnel_cols
        display_cols = [c for c in display_cols if c in merged.columns][:30]  # 限制列数
        
        if display_cols:
            sub_df = merged[display_cols].fillna("-")
            lines.append(_df_to_markdown_table(sub_df, max_rows=200))
            lines.append("")
            lines.append(f"> 共 {len(sub_df)} 家企业")
            lines.append("")
        
        # 按企业类型分类统计
        lines.append("## 二、企业类型分布")
        lines.append("")
        type_stats = {}
        for col in ENTERPRISE_TYPE_FIELDS:
            matched = [c for c in merged.columns if col in c]
            for m in matched:
                non_null = merged[m].dropna()
                if len(non_null) > 0:
                    try:
                        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
                        count = (numeric > 0).sum()
                        if count > 0:
                            type_stats[m] = int(count)
                    except Exception:
                        pass
        
        if type_stats:
            lines.append("| 企业类型 | 数量 |")
            lines.append("|---------|------|")
            for t, c in sorted(type_stats.items(), key=lambda x: -x[1]):
                lines.append(f"| {t} | {c} |")
            lines.append("")
        else:
            lines.append("（暂无可识别企业类型数据）")
            lines.append("")
    else:
        lines.append("（暂无企业数据）")
        lines.append("")
    
    lines.extend([
        "## 三、通用应急设备最低配置要求",
        "",
        "| 设备类别 | 最低配置要求 | 检查周期 | 有效期 |",
        "|---------|-------------|---------|--------|",
        "| 便携式气体检测仪 | 每班≥2台 | 每日 | 校准1年 |",
        "| 正压式空气呼吸器 | 从业人数10% | 每月 | 气瓶3年 |",
        "| 灭火器（干粉/CO₂） | 50m²配2具 | 每月 | 5年 |",
        "| 应急照明灯 | 疏散通道全覆盖 | 每月 | 电池2年 |",
        "| 逃生面罩 | 从业人数100% | 每季 | 3年 |",
        "| 防爆对讲机 | 每班≥1台 | 每周 | 5年 |",
        "",
        "## 四、人员资质要求",
        "",
        "1. **主要负责人**：必须持有安全生产知识和管理能力考核合格证",
        "2. **安全管理人员**：高危行业专职人员数量≥从业人数2%",
        "3. **特种作业人员**：100%持证上岗，证书在有效期内",
        "4. **一线操作工**：岗前安全培训≥72学时，每年再培训≥20学时",
        "",
        "## 五、基础处置能力标准",
        "",
        "1. 企业应在 5 分钟内启动应急响应程序",
        "2. 微型消防站人员应在 3 分钟内到达事发现场",
        "3. 应急物资应在 10 分钟内调取到位",
        "4. 每年至少组织 2 次综合应急演练",
        "",
    ])
    
    content = "\n".join(lines)
    if existing and len(existing) > 50:
        content = existing + "\n\n---\n\n## 增量更新 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + content
    
    _write_md(kb_dir, filename, content)


def generate_cases(kb_dir: str, dfs: Dict[str, pd.DataFrame]) -> None:
    """生成《类似事故处理案例.md》"""
    filename = "类似事故处理案例.md"
    existing = _read_existing_md(kb_dir, filename)
    
    lines = [
        "# 类似事故处理案例",
        "",
        "> 生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "> 来源: CSV中ACCIDENT=1记录 + 爬取事故调查报告".format(),
        "",
    ]
    
    # 尝试提取事故记录
    accident_records = []
    if "szs_enterprise_risk" in dfs:
        df = dfs["szs_enterprise_risk"]
        if "是否发生事故" in df.columns:
            accidents = df[df["是否发生事故"] == 1]
            if len(accidents) > 0:
                accident_records = accidents.to_dict("records")
        if "是否发生事件" in df.columns:
            events = df[df["是否发生事件"] == 1]
            if len(events) > 0:
                accident_records.extend(events.to_dict("records"))
    
    if accident_records:
        lines.append("## 一、企业历史事故/事件记录")
        lines.append("")
        for i, rec in enumerate(accident_records[:50], 1):
            risk_name = rec.get("风险名称", "未知风险")
            accident_desc = rec.get("事故概述", "未记录")
            lines.append(f"### 案例{i}：{risk_name}")
            lines.append("")
            lines.append(f"- **风险代码**: {rec.get('风险代码', 'N/A')}")
            lines.append(f"- **主要事故类别**: {rec.get('主要事故类别', 'N/A')}")
            lines.append(f"- **风险点**: {rec.get('风险点', 'N/A')}")
            lines.append(f"- **事故概述**: {accident_desc}")
            lines.append(f"- **管控措施**: {rec.get('管控措施详细信息', 'N/A')}")
            lines.append("")
    else:
        lines.extend([
            "## 一、企业历史事故/事件记录",
            "",
            "> 当前数据集中暂无 ACCIDENT=1 或 EVENT=1 的记录。以下为预置典型事故案例模板，供后续数据补充。",
            "",
        ])
    
    lines.extend([
        "## 二、典型事故案例模板",
        "",
        "### 案例A：某煤矿瓦斯超限事故（2023）",
        "- **事故原因**：通风系统局部短路，导致掘进工作面瓦斯积聚达2.3%",
        "- **处置流程**：",
        "  1. 传感器报警后30秒内切断电源并撤人",
        "  2. 通风科10分钟内调整风路，恢复正压通风",
        "  3. 瓦斯排放至0.5%以下后，佩戴呼吸器排查泄漏点",
        "- **整改措施**：优化通风系统设计，增设风速传感器4处，实现风量自动调节",
        "",
        "### 案例B：某化工厂反应釜超压泄漏（2022）",
        "- **事故原因**：冷却水系统故障，反应温度失控导致压力骤升",
        "- **处置流程**：",
        "  1. DCS系统自动触发紧急泄压阀",
        "  2. 消防队启动泡沫覆盖，防止蒸气云形成",
        "  3. 工艺人员逐步降低进料速率，转入安全停车程序",
        "- **整改措施**：增设独立安全仪表系统（SIS），反应釜压力与进料阀联锁",
        "",
        "### 案例C：某金属冶炼企业高温熔融金属喷溅（2024）",
        "- **事故原因**：炉体耐火材料侵蚀未及时发现",
        "- **处置流程**：",
        "  1. 红外热成像报警后，立即停炉并倾转炉体",
        "  2. 现场人员使用耐高温挡板隔离喷溅区域",
        "  3. 医疗救护队对灼伤人员进行紧急处置",
        "- **整改措施**：建立炉体厚度在线监测，每班人工复核，达到临界值强制更换",
        "",
        "## 三、爬取事故调查报告",
        "",
        "> 本区域由爬虫模块自动填充，存放从政府公开网站下载的事故调查报告原文。",
        "",
    ])
    
    # 尝试读取已爬取的事故报告
    raw_texts_dir = os.path.join(kb_dir, "raw_texts")
    if os.path.exists(raw_texts_dir):
        crawled_files = [f for f in os.listdir(raw_texts_dir) if f.endswith(".md")]
        if crawled_files:
            lines.append("### 已爬取报告列表")
            lines.append("")
            for cf in crawled_files:
                lines.append(f"- {cf}")
            lines.append("")
    
    content = "\n".join(lines)
    if existing and len(existing) > 50:
        content = existing + "\n\n---\n\n## 增量更新 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + content
    
    _write_md(kb_dir, filename, content)


def generate_history(kb_dir: str, dfs: Dict[str, pd.DataFrame]) -> None:
    """生成《预警历史经验与短期记忆摘要.md》"""
    filename = "预警历史经验与短期记忆摘要.md"
    existing = _read_existing_md(kb_dir, filename)
    
    lines = [
        "# 预警历史经验与短期记忆摘要",
        "",
        "> 本文件由系统在运行时自动写入，记录每次预警事件的处置经验与复盘总结",
        "> 生成时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "",
        "## 一、P0-P3 归档格式说明",
        "",
        "| 优先级 | 定义 | 保留策略 |",
        "|--------|------|---------|",
        "| **P0** | 核心指令/红线，永久保留 | 永久保留，不可清理 |",
        "| **P1** | 高优先级经验，最后清理 | 摘要存入长期记忆，详情保留最近100条 |",
        "| **P2** | 中优先级记录，优先压缩 | 压缩为摘要，保留最近50条 |",
        "| **P3** | 低优先级日志，最先移除 | 保留最近30天，超时自动清除 |",
        "",
        "## 二、记录格式模板",
        "",
        "| 时间戳 | 企业ID | 风险等级 | 触发特征 | 处置措施 | 效果评估 | 经验总结 | 优先级 |",
        "|--------|--------|---------|---------|---------|---------|---------|--------|",
        "| | | | | | | | |",
        "",
        "## 三、已记录事件",
        "",
        "### P0 级记录（永久）",
        "- 系统初始化完成，知识库生成完毕",
        "- 合规红线已绑定至所有处置决策节点",
        "",
        "### P1 级记录（高优）",
        "（暂无记录）",
        "",
        "### P2 级记录（中优）",
        "（暂无记录）",
        "",
        "### P3 级记录（低优）",
        "（暂无记录）",
        "",
    ]
    
    content = "\n".join(lines)
    if existing and len(existing) > 50:
        # 对于历史记录文件，保留现有内容并在末尾追加更新标记
        content = existing + "\n\n---\n\n## 增量更新 " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n"
    
    _write_md(kb_dir, filename, content)


def extract_feature_metadata(data_dir: str) -> str:
    """读取特征汇总Excel，提取字段注释作为元数据"""
    path = find_feature_summary(data_dir)
    if not path:
        logger.info("未找到特征汇总Excel文件，跳过字段元数据提取")
        return ""
    
    try:
        df = pd.read_excel(path)
        lines = []
        lines.append("| 字段名 | 说明 | 处理方法 |")
        lines.append("|--------|------|---------|")
        # 假设列名为：字段名、说明、处理方法
        for _, row in df.iterrows():
            field = row.get("字段名", row.iloc[0] if len(row) > 0 else "")
            desc = row.get("说明", row.iloc[1] if len(row) > 1 else "")
            method = row.get("处理方法", row.iloc[2] if len(row) > 2 else "")
            if pd.notna(field):
                lines.append(f"| {field} | {desc if pd.notna(desc) else ''} | {method if pd.notna(method) else ''} |")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"读取特征汇总Excel失败: {e}")
        return ""


def main():
    parser = argparse.ArgumentParser(description="初始化/增量更新知识库")
    parser.add_argument("--data-dir", type=str, default="datasets/raw/public", help="企业CSV数据根目录")
    parser.add_argument("--kb-dir", type=str, default="knowledge_base", help="知识库输出目录")
    parser.add_argument("--incremental", action="store_true", help="增量模式")
    args = parser.parse_args()
    
    kb_dir = args.kb_dir
    _ensure_kb_dir(kb_dir)
    
    logger.info(f"开始初始化知识库，数据目录: {args.data_dir}, 输出目录: {kb_dir}")
    
    # 查找并加载CSV
    files = find_csv_files(args.data_dir)
    dfs = load_dataframes(files)
    
    if not dfs:
        logger.error("未加载到任何企业数据，请检查 --data-dir 路径")
        sys.exit(1)
    
    # 提取特征元数据
    feature_meta = extract_feature_metadata(args.data_dir)
    
    # 生成6个核心文件
    generate_compliance(kb_dir, dfs, feature_meta)
    generate_sop(kb_dir, dfs)
    generate_physics(kb_dir, dfs)
    generate_conditions(kb_dir, dfs)
    generate_cases(kb_dir, dfs)
    generate_history(kb_dir, dfs)
    
    logger.info("知识库初始化完成")
    
    # 验证输出
    for fname in KNOWLEDGE_FILES:
        path = os.path.join(kb_dir, fname)
        if os.path.exists(path):
            size = os.path.getsize(path)
            logger.info(f"  {fname}: {size} bytes")
        else:
            logger.warning(f"  {fname}: 未生成")


if __name__ == "__main__":
    main()
