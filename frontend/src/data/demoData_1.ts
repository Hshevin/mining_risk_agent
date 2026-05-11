/**
 * 演示数据与 Mock 降级生成器
 * 与后端 frontend/demo_data.py 保持一致，确保后端不可用时仍可路演
 */

import type { DecisionResponse, ScenarioId } from "../api/types";

export const SCENARIO_NAMES: Record<ScenarioId, string> = {
  chemical: "危险化学品",
  metallurgy: "冶金",
  dust: "粉尘涉爆",
};

export const SCENARIO_LABELS: Record<ScenarioId, string> = {
  chemical: "🧪 危险化学品",
  metallurgy: "🔩 冶金",
  dust: "💨 粉尘涉爆",
};

export const DEMO_CHEMICAL = {
  企业ID: "CHEM-2024-001",
  企业名称: "宏达危化品储运有限公司",
  管理类别: 1003,
  风险等级: 4,
  是否发生事故: 1,
  安全生产标准化建设情况: 2,
  企业职工总人数: 320,
  专职安全生产管理人员数: 4,
  兼职安全生产管理人员数: 2,
  上一年经营收入: 8500,
  固定资产: 12000,
  "是否发现问题隐患 0-否 1-是": 1,
  具体风险描述:
    "3号储罐区可燃气体浓度异常升高，达到爆炸下限的38%，同时通风系统2号风机故障停运",
  管控措施: "立即切断储罐进料阀门，启动备用通风系统，撤离非必要人员",
  安全等级: "C级",
  企业规模: "中型",
  行业监管大类: "危险化学品",
  国民经济大类: "化学原料和化学制品制造业",
  危化品储罐数量: 12,
  重大危险源数量: 3,
  消防设施完好率: 0.78,
  气体检测仪在线率: 0.65,
};

export const DEMO_METALLURGY = {
  企业ID: "META-2024-002",
  企业名称: "金泰钢铁集团炼铁厂",
  管理类别: 2001,
  风险等级: 3,
  是否发生事故: 0,
  安全生产标准化建设情况: 3,
  企业职工总人数: 580,
  专职安全生产管理人员数: 12,
  兼职安全生产管理人员数: 6,
  上一年经营收入: 45000,
  固定资产: 180000,
  "是否发现问题隐患 0-否 1-是": 1,
  具体风险描述:
    "高炉煤气管道压力波动异常，TRT透平机振动值超标，炉顶温度连续3小时高于警戒值",
  管控措施: "降低鼓风量至正常值的85%，增加炉顶打水频率，密切监控煤气成分",
  安全等级: "B级",
  企业规模: "大型",
  行业监管大类: "冶金",
  国民经济大类: "黑色金属冶炼和压延加工业",
  高炉容积_m3: 3200,
  煤气柜容量_万m3: 15,
  铁水包在线数量: 8,
  炉壳温度测点完好率: 0.82,
  煤气报警器覆盖率: 0.91,
};

export const DEMO_DUST = {
  企业ID: "DUST-2024-003",
  企业名称: "鑫源铝镁粉尘制品厂",
  管理类别: 3002,
  风险等级: 4,
  是否发生事故: 1,
  安全生产标准化建设情况: 1,
  企业职工总人数: 85,
  专职安全生产管理人员数: 1,
  兼职安全生产管理人员数: 1,
  上一年经营收入: 1200,
  固定资产: 800,
  "是否发现问题隐患 0-否 1-是": 1,
  具体风险描述:
    "抛光车间铝镁粉尘浓度达到爆炸极限的45%，湿式除尘系统水位不足，电气设备未按要求防爆",
  管控措施: "立即停止抛光作业，补充除尘水位，切断非防爆电源",
  安全等级: "D级",
  企业规模: "小型",
  行业监管大类: "粉尘涉爆",
  国民经济大类: "金属制品业",
  抛光工位数量: 12,
  湿式除尘器数量: 3,
  粉尘清扫制度执行率: 0.45,
  防爆电气覆盖率: 0.6,
  静电接地完好率: 0.55,
};

export const DEMO_ENTERPRISES: Record<ScenarioId, Record<string, unknown>> = {
  chemical: DEMO_CHEMICAL,
  metallurgy: DEMO_METALLURGY,
  dust: DEMO_DUST,
};

export function getDemoDataJson(scenarioId: ScenarioId): string {
  const data = DEMO_ENTERPRISES[scenarioId] ?? DEMO_CHEMICAL;
  return JSON.stringify(data, null, 2);
}

function mockChemical(enterpriseId: string): DecisionResponse {
  return {
    enterprise_id: enterpriseId,
    scenario_id: "chemical",
    final_status: "HUMAN_REVIEW",
    predicted_level: "红",
    probability_distribution: { 红: 0.82, 橙: 0.13, 黄: 0.03, 蓝: 0.02 },
    shap_contributions: [
      { feature: "可燃气体浓度", contribution: 0.42 },
      { feature: "通风系统状态", contribution: 0.31 },
      { feature: "消防设施完好率", contribution: 0.18 },
      { feature: "专职安全生产管理人员数", contribution: -0.08 },
      { feature: "企业规模", contribution: 0.05 },
    ],
    risk_level_and_attribution: {
      level: "红",
      root_cause: "可燃气体浓度逼近爆炸下限且通风系统故障",
    },
    government_intervention: {
      department_primary: {
        name: "属地应急管理局-危化品安全监督管理科",
        contact_role: "科长",
        action: "立即签发《重大事故隐患整改通知书》，24小时内携带气体检测仪登门核查",
      },
      department_assist: {
        name: "应急管理综合行政执法大队",
        action: "协助现场核查并责令停产整顿",
      },
      actions: [
        "24小时内组织联合执法小组登门核查",
        "责令立即停止3号储罐区所有作业",
        "委托第三方机构进行全面安全评估",
      ],
      deadline_hours: 24,
      follow_up: "整改完成后3个工作日内复查，复查不合格提请关闭",
    },
    enterprise_control: {
      equipment_id: "3号储罐区T-301A/B/C、通风风机2号",
      operation: "立即通过DCS控制系统执行紧急停车并切断进料",
      parameters: {
        dcs_tag: "FIC-301A/B/C",
        target_values: "进料流量=0 t/h, 罐内温度≤40°C",
        monitoring_interval_minutes: 15,
        可燃气体报警设定值: "25%LEL",
      },
      emergency_resources: ["正压式呼吸器6套", "防爆气体检测仪2台", "防爆风机1台"],
      personnel_actions: [
        "撤离储罐区30米内所有非必要人员",
        "启动公司级应急响应小组",
        "通知周边企业联防联动",
      ],
    },
    march_result: { passed: true, reason: "Mock: 所有原子命题通过三重隔离校验", retry_count: 1 },
    monte_carlo_result: {
      passed: false,
      confidence: 0.78,
      threshold: 0.9,
      valid_count: 15,
      total_samples: 20,
      status: "HUMAN_REVIEW",
      samples: [],
    },
    three_d_risk: {
      severity: "极高",
      relevance: "极高",
      irreversibility: "极高",
      total_score: 3.8,
      risk_level: "EXTREME",
      blocked: true,
      reason: "Mock: 三维风险评分 3.8 ≥ 阈值 2.2，触发人工审核",
    },
    node_status: [
      { node: "data_ingestion", status: "completed", detail: "Mock: 特征工程完成，输入维度=28" },
      { node: "risk_assessment", status: "completed", detail: "Mock: 预测等级: 红（置信度0.82）" },
      { node: "memory_recall", status: "completed", detail: "Mock: 召回 5 条危化品事故处置记忆" },
      {
        node: "decision_generation",
        status: "completed",
        detail: "Mock: 决策生成，MARCH通过，蒙特卡洛未通过（0.78<0.90）",
      },
      { node: "result_push", status: "completed", detail: "Mock: 最终状态: HUMAN_REVIEW（已拦截，转人工审核）" },
    ],
    mock: true,
  };
}

function mockMetallurgy(enterpriseId: string): DecisionResponse {
  return {
    enterprise_id: enterpriseId,
    scenario_id: "metallurgy",
    final_status: "APPROVE",
    predicted_level: "橙",
    probability_distribution: { 红: 0.18, 橙: 0.65, 黄: 0.12, 蓝: 0.05 },
    shap_contributions: [
      { feature: "高炉煤气压力", contribution: 0.35 },
      { feature: "TRT透平机振动值", contribution: 0.22 },
      { feature: "炉顶温度", contribution: 0.16 },
      { feature: "炉壳温度测点完好率", contribution: -0.1 },
      { feature: "煤气报警器覆盖率", contribution: -0.05 },
    ],
    risk_level_and_attribution: {
      level: "橙",
      root_cause: "高炉煤气系统多参数同时逼近警戒值",
    },
    government_intervention: {
      department_primary: {
        name: "属地应急管理局-冶金工贸安全监督管理科",
        contact_role: "副科长",
        action: "3日内组织煤气安全专项检查，责令限期整改",
      },
      department_assist: { name: "冶金行业技术服务中心", action: "提供专家技术支持" },
      actions: [
        "72小时内组织煤气安全专项检查",
        "核查TRT机组运行维护记录",
        "校验炉顶温度与压力联锁保护装置",
      ],
      deadline_hours: 72,
      follow_up: "整改完成后7个工作日内复查",
    },
    enterprise_control: {
      equipment_id: "1号高炉、TRT透平机、煤气主管网",
      operation: "降低鼓风量至设计值的85%，增加炉顶打水频率",
      parameters: {
        dcs_tag: "BIC-101, PIC-201",
        target_values: "鼓风量=3400 Nm³/min, 炉顶温度≤220°C",
        monitoring_interval_minutes: 30,
        煤气压力报警设定值: "8.5kPa",
      },
      emergency_resources: ["便携式CO检测仪4台", "空气呼吸器4套", "煤气堵漏工具包2套"],
      personnel_actions: ["增加高炉巡检频次至每2小时一次", "TRT控制室双人值守", "通知煤气防护站待命"],
    },
    march_result: { passed: true, reason: "Mock: 所有原子命题通过三重隔离校验", retry_count: 0 },
    monte_carlo_result: {
      passed: true,
      confidence: 0.88,
      threshold: 0.85,
      valid_count: 17,
      total_samples: 20,
      status: "APPROVE",
      samples: [],
    },
    three_d_risk: {
      severity: "高",
      relevance: "高",
      irreversibility: "中",
      total_score: 2.4,
      risk_level: "HIGH",
      blocked: false,
      reason: "Mock: 三维风险评分 2.4 < 阈值 2.5，通过",
    },
    node_status: [
      { node: "data_ingestion", status: "completed", detail: "Mock: 特征工程完成，输入维度=32" },
      { node: "risk_assessment", status: "completed", detail: "Mock: 预测等级: 橙（置信度0.65）" },
      { node: "memory_recall", status: "completed", detail: "Mock: 召回 4 条高炉煤气泄漏处置记忆" },
      { node: "decision_generation", status: "completed", detail: "Mock: 决策生成并通过全部校验" },
      { node: "result_push", status: "completed", detail: "Mock: 最终状态: APPROVE" },
    ],
    mock: true,
  };
}

function mockDust(enterpriseId: string): DecisionResponse {
  return {
    enterprise_id: enterpriseId,
    scenario_id: "dust",
    final_status: "REJECT",
    predicted_level: "红",
    probability_distribution: { 红: 0.88, 橙: 0.08, 黄: 0.03, 蓝: 0.01 },
    shap_contributions: [
      { feature: "粉尘浓度", contribution: 0.48 },
      { feature: "湿式除尘系统水位", contribution: 0.25 },
      { feature: "防爆电气覆盖率", contribution: 0.15 },
      { feature: "静电接地完好率", contribution: 0.08 },
      { feature: "粉尘清扫制度执行率", contribution: 0.04 },
    ],
    risk_level_and_attribution: {
      level: "红",
      root_cause: "铝镁粉尘浓度达爆炸极限且湿式除尘失效、电气不防爆",
    },
    government_intervention: {
      department_primary: {
        name: "属地应急管理局-工贸行业安全监督管理科",
        contact_role: "科长",
        action: "立即责令全面停产停业整顿，依法实施行政处罚",
      },
      department_assist: { name: "粉尘涉爆专家库", action: "48小时内到场进行深度隐患排查" },
      actions: [
        "立即下达《现场处理措施决定书》",
        "责令抛光车间全面停产",
        "对主要负责人进行约谈",
      ],
      deadline_hours: 12,
      follow_up: "整改验收合格前不得恢复生产",
    },
    enterprise_control: {
      equipment_id: "抛光车间全部12个工位、湿式除尘器W-01/02/03",
      operation: "立即切断抛光车间所有动力电源，停止产尘作业",
      parameters: {
        dcs_tag: "无",
        target_values: "抛光机转速=0 rpm, 车间湿度≥65%",
        monitoring_interval_minutes: 10,
        粉尘浓度报警设定值: "20%MEC",
      },
      emergency_resources: ["防爆吸尘器2台", "防静电工作服10套", "增湿器4台"],
      personnel_actions: [
        "立即疏散抛光车间全部人员",
        "设置30米警戒隔离区",
        "清点人数确认无滞留",
      ],
    },
    march_result: {
      passed: false,
      reason: "Mock: 处置可行性校验失败——建议立即停用湿式除尘但未给出替代防火花措施",
      retry_count: 3,
    },
    monte_carlo_result: {
      passed: false,
      confidence: 0.72,
      threshold: 0.85,
      valid_count: 14,
      total_samples: 20,
      status: "REJECT",
      samples: [],
    },
    three_d_risk: {
      severity: "极高",
      relevance: "极高",
      irreversibility: "极高",
      total_score: 3.9,
      risk_level: "EXTREME",
      blocked: true,
      reason: "Mock: 三维风险评分 3.9 ≥ 阈值 2.5，触发阻断",
    },
    node_status: [
      { node: "data_ingestion", status: "completed", detail: "Mock: 特征工程完成，输入维度=24" },
      { node: "risk_assessment", status: "completed", detail: "Mock: 预测等级: 红（置信度0.88）" },
      { node: "memory_recall", status: "completed", detail: "Mock: 召回 6 条粉尘爆炸事故处置记忆" },
      {
        node: "decision_generation",
        status: "failed",
        detail: "Mock: MARCH校验3次重试后仍失败，决策被拦截",
      },
      { node: "result_push", status: "completed", detail: "Mock: 最终状态: REJECT（已拦截，禁止自动推送）" },
    ],
    mock: true,
  };
}

export function generateMockDecision(
  scenarioId: ScenarioId,
  enterpriseId = "ENT-DEMO",
): DecisionResponse {
  if (scenarioId === "metallurgy") return mockMetallurgy(enterpriseId);
  if (scenarioId === "dust") return mockDust(enterpriseId);
  return mockChemical(enterpriseId);
}

export const SCENARIO_CONFIG: Record<ScenarioId, Record<string, unknown>> = {
  chemical: {
    场景名称: "危险化学品",
    置信度阈值: 0.9,
    风险阈值: 2.2,
    校验严格度: "strict",
    "记忆召回 top_k": 5,
  },
  metallurgy: {
    场景名称: "冶金",
    置信度阈值: 0.85,
    风险阈值: 2.5,
    校验严格度: "standard",
    "记忆召回 top_k": 5,
  },
  dust: {
    场景名称: "粉尘涉爆",
    置信度阈值: 0.85,
    风险阈值: 2.5,
    校验严格度: "standard",
    "记忆召回 top_k": 5,
  },
};
