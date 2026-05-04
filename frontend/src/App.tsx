import { useEffect, useState } from "react";
import {
  fetchHealth,
  fetchIterationStatus,
  switchScenario,
} from "./api/client";
import type {
  HealthResponse,
  IterationStatus,
  ScenarioId,
} from "./api/types";
import StatusBar from "./components/StatusBar";
import Sidebar from "./components/Sidebar";
import Tabs from "./components/Tabs";
import { SCENARIO_NAMES } from "./data/demoData";
import RiskPredictionPage from "./pages/RiskPredictionPage";
import KnowledgeMemoryPage from "./pages/KnowledgeMemoryPage";
import IterationPage from "./pages/IterationPage";
import SystemConfigPage from "./pages/SystemConfigPage";

const TAB_DEFS = [
  { id: "risk", label: "🎯 企业风险预测" },
  { id: "knowledge", label: "📚 知识库与记忆系统" },
  { id: "iteration", label: "🔄 模型迭代与CI/CD" },
  { id: "config", label: "⚙️ 系统配置与API文档" },
];

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [iteration, setIteration] = useState<IterationStatus | null>(null);
  const [scenario, setScenario] = useState<ScenarioId>("chemical");
  const [demoMode, setDemoMode] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("risk");

  useEffect(() => {
    fetchHealth().then(setHealth);
    fetchIterationStatus().then(setIteration);
    const id = setInterval(() => {
      fetchHealth().then(setHealth);
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  async function changeScenario(s: ScenarioId) {
    setScenario(s);
    await switchScenario(s);
  }

  return (
    <div className="app-shell">
      <StatusBar health={health} scenarioName={SCENARIO_NAMES[scenario]} />
      <div className="app-body">
        <Sidebar
          health={health}
          scenario={scenario}
          onScenarioChange={changeScenario}
          iteration={iteration}
          demoMode={demoMode}
          onDemoToggle={setDemoMode}
        />
        <main className="main-content">
          <Tabs
            tabs={TAB_DEFS}
            active={activeTab}
            onChange={setActiveTab}
          />
          {activeTab === "risk" && <RiskPredictionPage scenario={scenario} />}
          {activeTab === "knowledge" && <KnowledgeMemoryPage />}
          {activeTab === "iteration" && <IterationPage />}
          {activeTab === "config" && (
            <SystemConfigPage scenario={scenario} health={health} />
          )}
        </main>
      </div>
    </div>
  );
}
