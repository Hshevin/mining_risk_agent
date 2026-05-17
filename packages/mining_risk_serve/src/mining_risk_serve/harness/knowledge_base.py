"""
多维知识库系?自动生成 6 个核?Markdown 知识库文件并管理版本
"""

import csv
import os
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.exceptions import KnowledgeBaseError
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


class MarkdownTablePrettifier:
    """Markdown Table Prettifier：将 CSV/TXT 转换为标?Markdown 表格"""

    @staticmethod
    def csv_to_markdown(csv_content: str, delimiter: str = ",") -> str:
        reader = csv.reader(StringIO(csv_content), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return ""
        
        header = rows[0]
        lines = ["| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


class KnowledgeBaseManager:
    """
    知识库管理器
    
    核心功能?    1. 自动生成 6 个核?Markdown 知识库文?    2. Markdown Table Prettifier
    3. 版本控制（Git?    4. 增删改查与版本回?    """

    KNOWLEDGE_FILES = [
        "工矿风险预警智能体合规执行书.md",
        "部门分级审核SOP.md",
        "工业物理常识及传感器时间序列逻辑.md",
        "企业已具备的执行条件.md",
        "类似事故处理案例.md",
        "预警历史经验与短期记忆摘要.md",
    ]

    def __init__(self, agentfs: Optional[AgentFS] = None):
        config = get_config()
        self.agentfs = agentfs or AgentFS()
        self.kb_dir = "knowledge_base"
        self._ensure_knowledge_files()

    def _ensure_knowledge_files(self) -> None:
        """确保知识库文件存在，不存在则生成默认内容"""
        for filename in self.KNOWLEDGE_FILES:
            path = f"{self.kb_dir}/{filename}"
            if not self.agentfs.exists(path):
                content = self._generate_default_content(filename)
                self.agentfs.write(path, content.encode("utf-8"))
                logger.info(f"生成默认知识库文? {path}")

    def _generate_default_content(self, filename: str) -> str:
        """生成默认知识库内容"""
        generators = {
            "工矿风险预警智能体合规执行书.md": self._gen_compliance,
            "部门分级审核SOP.md": self._gen_sop,
            "工业物理常识及传感器时间序列逻辑.md": self._gen_physics,
            "企业已具备的执行条件.md": self._gen_conditions,
            "类似事故处理案例.md": self._gen_cases,
            "预警历史经验与短期记忆摘要.md": self._gen_history,
        }
        gen = generators.get(filename, lambda: "# 待补充\n")
        return gen()

    def _gen_compliance(self) -> str:
        return """# 工矿风险预警智能体合规执行书

## 一、核心法规依?
### 1. 《中华人民共和国安全生产法》（2021 修订?- **第三?*：安全生产工作实行管行业必须管安全、管业务必须管安全、管生产经营必须管安全?- **第三十六?*：安全设备的设计、制造、安装、使用、检测、维修、改造和报废，应当符合国家标准或者行业标准?- **第四十一?*：生产经营单位应当建立安全风险分级管控和隐患排查治理双重预防工作机制?
### 2. 《工矿企业重大事故隐患判定标准》（应急管理部令第 4 号）
- **重大隐患判定**：涉及人员定位系统失效、通风系统不可靠、瓦斯超限作业、未按设计施工等情形直接判定为重大事故隐患?- **整改时限**：重大隐患应立即停产整改，一般隐患应?15 日内完成整改?
## 二、合规红线条?
| 序号 | 红线内容 | 违规后果 | 触发等级 |
|------|---------|---------|---------|
| 1 | 瓦斯浓度超限时未立即撤人、断?| 重大事故 | ?|
| 2 | 通风系统擅自停运或改?| 群死群伤 | ?|
| 3 | 特种作业人员无证上岗 | 行政处罚+停产 | ?|
| 4 | 重大危险源未登记建档 | 罚款+限期整改 | ?|
| 5 | 安全培训记录缺失 | 警告+补训 | ?|

## 三、禁止操作清

1. **严禁**在未取得安全生产许可证的情况下组织生产?2. **严禁**擅自关闭、破坏安全监控、报警、防护、救生设备设施?3. **严禁**超能力、超强度、超定员组织生产?4. **严禁**隐瞒不报、谎报或拖延不报生产安全事故?5. **严禁**使用国家明令淘汰或禁止使用的设备、工艺?"""

    def _gen_sop(self) -> str:
        return """# 部门分级审核 SOP

## 一、风险等级与审核部门对应?
| 风险等级 | 审核部门 | 责任?| 审批流程 | 时限要求 |
|---------|---------|--------|---------|---------|
| ?| 属地应急管理局 + 省级监管部门 | 局?分管副厅?| 立即上报 ?联合执法 ?停产决定 | 2 小时 |
| ?| 属地应急管理局 + 行业主管部门 | 科长/处长 | 现场核查 ?整改通知 ?复查验收 | 24 小时 |
| ?| ?区级安监?+ 乡镇街道 | 站长/主任 | 现场检??限期整改 ?跟踪闭环 | 7 ?|
| ?| 企业安全管理部门 | 安全总监 | 自查自纠 ?记录归档 | 15 ?|

## 二、红/橙级风险专项审批流程

1. **接报**：智能体推送预??值班员确认接收（5 分钟内）?2. **初核**：责任部?30 分钟内完成电?视频初核?3. **派单**：通过监管平台向企业、执法队同步派发任务?4. **现场核查**：携带检测设备，4 小时内到达现场?5. **处置决定**：根据现场情况作出停?限产/限期整改决定?6. **闭环归档**：整改完成后 3 个工作日内上传验收材料?
## 三、责任人清单（模板）

| 部门 | 姓名 | 职务 | 联系方式 | 负责领域 |
|------|------|------|---------|---------|
| 待填?| 待填?| 待填?| 待填?| 待填?|
"""

    def _gen_physics(self) -> str:
        return """# 工业物理常识及传感器时间序列逻辑

## 一、常见传感器参数范围

### 1. 瓦斯（甲烷）传感?| 参数 | 正常范围 | 预警阈?| 报警阈?| 断电阈?|
|------|---------|---------|---------|---------|
| CH?浓度 | 0% ~ 0.5% | ?0.8% | ?1.0% | ?1.5% |

### 2. 温度传感?| 参数 | 正常范围 | 高温预警 | 超温报警 |
|------|---------|---------|---------|
| 环境温度 | 15°C ~ 30°C | ?35°C | ?40°C |
| 设备表面 | 40°C ~ 60°C | ?70°C | ?80°C |

### 3. 压力传感?| 参数 | 正常范围 | 低压预警 | 高压预警 |
|------|---------|---------|---------|
| 管道压力 | 0.3 ~ 0.6 MPa | < 0.2 MPa | > 0.8 MPa |

### 4. 湿度传感?| 参数 | 正常范围 | 高湿预警 | 低湿预警 |
|------|---------|---------|---------|
| 相对湿度 | 40% ~ 70% | > 85% | < 20% |

## 二、时间序列异常判断规

1. **突变检?*：单点值偏离滑动窗口均?3σ 以上，标记为异常突变?2. **趋势检?*：连?5 个点同向单调变化且斜率超过历史基?20%?3. **周期异常**：偏离日/周周期性规律的幅度超过 30%?4. **关联异常**：瓦斯浓度上升同时温度下降（可能指示通风异常）?
## 三、物理量关联逻辑

- **瓦斯 ?+ 风???通风隐患**
- **温度 ?+ 压力 ??燃烧/爆炸风险**
- **湿度 ?+ 电气设备温度 ??绝缘失效风险**
- **振动 ?+ 噪声 ??机械故障前兆**
"""

    def _gen_conditions(self) -> str:
        return """# 企业已具备的执行条件

## 一、通用应急设备清?
| 设备类别 | 最低配置要?| 检查周?| 有效?|
|---------|-------------|---------|--------|
| 便携式气体检测仪 | 每班?2 ?| 每日 | 校准 1 ?|
| 正压式空气呼吸器 | 从业人数 10% | 每月 | 气瓶 3 ?|
| 灭火器（干粉/CO₂） | 50m² ?2 ?| 每月 | 5 ?|
| 应急照明灯 | 疏散通道全覆?| 每月 | 电池 2 ?|
| 逃生面罩 | 从业人数 100% | 每季 | 3 ?|
| 防爆对讲?| 每班?1 ?| 每周 | 5 ?|

## 二、人员资质要

1. **主要负责?*：必须持有安全生产知识和管理能力考核合格证?2. **安全管理人员**：高危行业专职人员数??从业人数 2%?3. **特种作业人员**?00% 持证上岗，证书在有效期内?4. **一线操作工**：岗前安全培??72 学时，每年再培训 ?20 学时?
## 三、基础处置能力标准

1. 企业应在 5 分钟内启动应急响应程序?2. 微型消防站人员应?3 分钟内到达事发现场?3. 应急物资应?10 分钟内调取到位?4. 每年至少组织 2 次综合应急演练?"""

    def _gen_cases(self) -> str:
        return """# 类似事故处理案例

## 案例 1：某煤矿瓦斯超限事故?023?- **事故原因**：通风系统局部短路，导致掘进工作面瓦斯积聚达?2.3%?- **处置流程**?  1. 传感器报警后 30 秒内切断电源并撤人?  2. 通风?10 分钟内调整风路，恢复正压通风
  3. 瓦斯排放?0.5% 以下后，佩戴呼吸器排查泄漏点?- **整改措施**：优化通风系统设计，增设风速传感器 4 处，实现风量自动调节?
## 案例 2：某化工厂反应釜超压泄漏?022?- **事故原因**：冷却水系统故障，反应温度失控导致压力骤升?- **处置流程**?  1. DCS 系统自动触发紧急泄压阀?  2. 消防队启动泡沫覆盖，防止蒸气云形成
  3. 工艺人员逐步降低进料速率，转入安全停车程序?- **整改措施**：增设独立安全仪表系统（SIS），反应釜压力与进料阀联锁?
## 案例 3：某金属冶炼企业高温熔融金属喷溅?024?- **事故原因**：炉体耐火材料侵蚀未及时发现?- **处置流程**?  1. 红外热成像报警后，立即停炉并倾转炉体?  2. 现场人员使用耐高温挡板隔离喷溅区域
  3. 医疗救护队对灼伤人员进行紧急处置?- **整改措施**：建立炉体厚度在线监测，每班人工复核，达到临界值强制更换?
## 案例 4-10：待补充...
（可根据实际事故报告持续扩充?"""

    def _gen_history(self) -> str:
        return """# 预警历史经验与短期记忆摘要
> 本文件由系统在运行时自动写入，记录每次预警事件的处置经验与复盘总结?
## 记录格式模板

| 时间?| 企业ID | 风险等级 | 触发特征 | 处置措施 | 效果评估 | 经验总结 |
|--------|--------|---------|---------|---------|---------|---------|
| | | | | | | |

## 已记录事?
（暂无记录）
"""

    def read(self, filename: str) -> str:
        """读取知识库文件"""
        path = f"{self.kb_dir}/{filename}"
        try:
            return self.agentfs.read(path).decode("utf-8")
        except Exception as e:
            raise KnowledgeBaseError(f"读取知识库失? {e}")

    def write(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
        """写入知识库文件"""
        path = f"{self.kb_dir}/{filename}"
        self.agentfs.write(path, content.encode("utf-8"), agent_id=agent_id)
        logger.info(f"知识库已更新: {path}")

    def append(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
        """追加内容到知识库文件"""
        existing = self.read(filename)
        new_content = existing + "\n\n" + content
        self.write(filename, new_content, agent_id=agent_id)

    def list_files(self) -> List[str]:
        """列出所有知识库文件"""
        return self.KNOWLEDGE_FILES

    def snapshot(self, commit_message: str, agent_id: Optional[str] = None) -> str:
        """生成知识库快照"""
        return self.agentfs.snapshot(commit_message, agent_id=agent_id)

    def rollback(self, commit_id: str) -> None:
        """回滚知识库到指定版本"""
        self.agentfs.rollback(commit_id)
