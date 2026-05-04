import {
  apiBase,
  fetchHealth,
  fetchLLMConfig,
  switchLLMProvider,
  updateLLMConfig,
} from "../api/client";
import { SCENARIO_CONFIG } from "../data/demoData";
import type {
  HealthResponse,
  LLMConfigResponse,
  LLMProvider,
  LLMUpdateRequest,
  ScenarioId,
} from "../api/types";
import { useEffect, useState } from "react";
import JsonView from "../components/JsonView";

interface Props {
  scenario: ScenarioId;
  health: HealthResponse | null;
}

type LLMFormState = Required<
  Pick<
    LLMUpdateRequest,
    | "provider"
    | "model"
    | "base_url"
    | "api_key"
    | "api_key_env"
    | "default_temperature"
    | "default_max_tokens"
    | "max_retries"
  >
>;

const EMPTY_LLM_FORM: LLMFormState = {
  provider: "",
  model: "",
  base_url: "",
  api_key: "",
  api_key_env: "",
  default_temperature: 0.3,
  default_max_tokens: 8192,
  max_retries: 3,
};

const API_TABLE = [
  { path: "POST /api/v1/agent/decision", desc: "触发完整决策工作流" },
  { path: "POST /api/v1/agent/decision/stream", desc: "SSE 流式节点状态" },
  { path: "POST /api/v1/agent/scenario/{id}", desc: "切换场景配置" },
  { path: "GET /api/v1/agent/llm", desc: "查询当前 LLM 模型配置" },
  { path: "POST /api/v1/agent/llm/{provider}", desc: "切换已配置的 LLM provider" },
  { path: "POST /api/v1/agent/llm", desc: "创建或更新自定义 OpenAI 兼容模型配置" },
  { path: "POST /api/v1/data/upload", desc: "数据文件上传（CSV/Excel）" },
  { path: "GET /api/v1/knowledge/list", desc: "知识库文件列表" },
  { path: "GET /api/v1/knowledge/read/{filename}", desc: "知识库文件读取" },
  { path: "GET /api/v1/iteration/status", desc: "迭代状态查询" },
  { path: "POST /api/v1/iteration/trigger", desc: "触发迭代流水线" },
  { path: "GET /api/v1/audit/query", desc: "审计日志查询" },
];

export default function SystemConfigPage({ scenario, health }: Props) {
  const [latestHealth, setLatestHealth] = useState<HealthResponse | null>(health);
  const [llmConfig, setLlmConfig] = useState<LLMConfigResponse | null>(null);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [llmMessage, setLlmMessage] = useState<string>("");
  const [llmForm, setLlmForm] = useState<LLMFormState>(EMPTY_LLM_FORM);

  useEffect(() => {
    fetchHealth().then(setLatestHealth);
    fetchLLMConfig().then(setLlmConfig);
  }, []);

  useEffect(() => {
    if (!llmConfig) return;
    setLlmForm((prev) => ({
      ...prev,
      provider: llmConfig.provider,
      model: llmConfig.model,
      base_url: llmConfig.base_url,
      default_temperature: llmConfig.default_temperature,
      default_max_tokens: llmConfig.default_max_tokens,
      max_retries: llmConfig.max_retries,
    }));
  }, [llmConfig]);

  const cfg = SCENARIO_CONFIG[scenario];
  const online = latestHealth?.status === "healthy";
  const activeProvider = llmConfig?.provider ?? "";
  const availableProviders = llmConfig?.available_providers ?? [];

  async function changeLLMProvider(provider: LLMProvider) {
    setSwitchingProvider(true);
    setLlmMessage("");
    const next = await switchLLMProvider(provider);
    if (next) {
      setLlmConfig(next);
      setLlmMessage(next.message || `LLM 已切换为 ${provider}`);
    } else {
      setLlmMessage("LLM 切换失败：请确认后端已启动，且 provider 配置有效。");
    }
    setSwitchingProvider(false);
  }

  async function saveLLMConfig() {
    if (!llmForm.provider.trim()) {
      setLlmMessage("LLM 配置保存失败：provider 不能为空。");
      return;
    }

    setSwitchingProvider(true);
    setLlmMessage("");
    const payload: LLMUpdateRequest = {
      provider: llmForm.provider.trim(),
      model: llmForm.model.trim() || undefined,
      base_url: llmForm.base_url.trim() || undefined,
      api_key: llmForm.api_key.trim() || undefined,
      api_key_env: llmForm.api_key_env.trim() || undefined,
      default_temperature: Number(llmForm.default_temperature),
      default_max_tokens: Number(llmForm.default_max_tokens),
      max_retries: Number(llmForm.max_retries),
    };
    const next = await updateLLMConfig(payload);
    if (next) {
      setLlmConfig(next);
      setLlmMessage(next.message || `LLM 配置已更新为 ${next.provider}`);
      setLlmForm((prev) => ({ ...prev, api_key: "" }));
    } else {
      setLlmMessage("LLM 配置保存失败：请确认后端已启动，且参数格式有效。");
    }
    setSwitchingProvider(false);
  }

  return (
    <div>
      <div className="section-title">⚙️ 系统配置与 API 文档</div>

      <div className="subtitle">🤖 后端连通状态</div>
      <div className={`alert ${online ? "success" : "error"}`}>
        {online
          ? `✅ FastAPI 后端已连通  (version=${latestHealth?.version ?? "—"})`
          : "❌ 后端未连通（前端将以本地 Mock 数据进行演示）"}
      </div>

      <div className="subtitle">🧠 大模型切换</div>
      <div className="scada-card" style={{ marginBottom: 16 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(180px, 260px) 1fr",
            gap: 16,
          }}
        >
          <div>
            <label className="scada-label" htmlFor="llm-provider">
              当前 LLM Provider
            </label>
            <select
              id="llm-provider"
              className="scada-select"
              value={activeProvider}
              disabled={!online || switchingProvider}
              onChange={(e) => changeLLMProvider(e.target.value as LLMProvider)}
            >
              {availableProviders.length === 0 && (
                <option value="">暂无已配置 provider</option>
              )}
              {availableProviders.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
            <div className="scada-card-sub">
              {!online
                ? "后端未连通，暂不可切换"
                : "选项来自后端 llm.providers 配置"}
            </div>
          </div>
          <div>
            <JsonView
              data={{
                provider: llmConfig?.provider ?? "unknown",
                model: llmConfig?.model ?? "unknown",
                base_url: llmConfig?.base_url ?? "unknown",
                api_key: llmConfig?.has_api_key ? "已配置" : "未配置",
                temperature: llmConfig?.default_temperature ?? "unknown",
                max_tokens: llmConfig?.default_max_tokens ?? "unknown",
                max_retries: llmConfig?.max_retries ?? "unknown",
              }}
              maxHeight={180}
            />
          </div>
        </div>
        {llmMessage && (
          <div
            className={`alert ${llmMessage.includes("失败") ? "error" : "success"}`}
            style={{ marginTop: 12 }}
          >
            {llmMessage}
          </div>
        )}
        {llmConfig && !llmConfig.has_api_key && (
          <div className="alert warning" style={{ marginTop: 12 }}>
            当前 provider 未检测到 API Key，实际决策可能进入 Mock 降级。请在后端环境变量中配置对应 Key。
          </div>
        )}

        <div className="divider" />
        <div className="subtitle">自定义 OpenAI 兼容模型</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            gap: 12,
          }}
        >
          <div>
            <label className="scada-label" htmlFor="llm-custom-provider">
              Provider 名称
            </label>
            <input
              id="llm-custom-provider"
              className="scada-input"
              value={llmForm.provider}
              placeholder="例如：qwen、siliconflow、local-openai"
              onChange={(e) => setLlmForm({ ...llmForm, provider: e.target.value })}
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-model">
              模型名称
            </label>
            <input
              id="llm-custom-model"
              className="scada-input"
              value={llmForm.model}
              placeholder="例如：qwen-plus、gpt-4o-mini、本地模型名"
              onChange={(e) => setLlmForm({ ...llmForm, model: e.target.value })}
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-base-url">
              Base URL
            </label>
            <input
              id="llm-custom-base-url"
              className="scada-input"
              value={llmForm.base_url}
              placeholder="https://.../v1"
              onChange={(e) => setLlmForm({ ...llmForm, base_url: e.target.value })}
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-key-env">
              API Key 环境变量名
            </label>
            <input
              id="llm-custom-key-env"
              className="scada-input"
              value={llmForm.api_key_env}
              placeholder="例如：CUSTOM_LLM_API_KEY"
              onChange={(e) => setLlmForm({ ...llmForm, api_key_env: e.target.value })}
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-api-key">
              API Key（可选，仅当前进程生效）
            </label>
            <input
              id="llm-custom-api-key"
              className="scada-input"
              value={llmForm.api_key}
              type="password"
              placeholder="留空则使用环境变量"
              onChange={(e) => setLlmForm({ ...llmForm, api_key: e.target.value })}
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-temperature">
              Temperature
            </label>
            <input
              id="llm-custom-temperature"
              className="scada-input"
              value={llmForm.default_temperature}
              type="number"
              min={0}
              max={2}
              step={0.1}
              onChange={(e) =>
                setLlmForm({ ...llmForm, default_temperature: Number(e.target.value) })
              }
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-max-tokens">
              Max Tokens
            </label>
            <input
              id="llm-custom-max-tokens"
              className="scada-input"
              value={llmForm.default_max_tokens}
              type="number"
              min={1}
              onChange={(e) =>
                setLlmForm({ ...llmForm, default_max_tokens: Number(e.target.value) })
              }
            />
          </div>
          <div>
            <label className="scada-label" htmlFor="llm-custom-retries">
              Max Retries
            </label>
            <input
              id="llm-custom-retries"
              className="scada-input"
              value={llmForm.max_retries}
              type="number"
              min={1}
              onChange={(e) =>
                setLlmForm({ ...llmForm, max_retries: Number(e.target.value) })
              }
            />
          </div>
        </div>
        <button
          className="scada-btn"
          style={{ marginTop: 12 }}
          disabled={!online || switchingProvider}
          onClick={saveLLMConfig}
        >
          保存并切换到该模型
        </button>
      </div>

      <div className="subtitle">🎛️ 当前场景配置参数</div>
      <JsonView data={cfg} maxHeight={220} />

      <div className="divider" />

      <div className="subtitle">📖 API 文档</div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          fontSize: 13,
          color: "#9ca3af",
        }}
      >
        <div>
          • <a href="/docs" target="_blank" rel="noreferrer">Swagger UI（同源代理）</a>
        </div>
        <div>
          • <a href="/redoc" target="_blank" rel="noreferrer">Redoc（同源代理）</a>
        </div>
        <div>
          • 健康检查:{" "}
          <span className="font-mono" style={{ color: "#e5e7eb" }}>
            GET /health
          </span>
        </div>
      </div>

      <div className="subtitle" style={{ marginTop: 16 }}>
        🔌 核心接口速查
      </div>
      <table className="scada-table">
        <thead>
          <tr>
            <th>接口</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {API_TABLE.map((r) => (
            <tr key={r.path}>
              <td className="font-mono">{r.path}</td>
              <td>{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="divider" />
      <div className="subtitle">ℹ️ 系统信息</div>
      <JsonView
        data={{
          backend_status: latestHealth?.status ?? "unknown",
          version: latestHealth?.version ?? "unknown",
          api_base: apiBase,
          frontend: "React + Vite + ECharts (SCADA Theme)",
          recommended_resolution: "1920×1080",
          theme: "Industrial Control Room Dark",
        }}
      />
    </div>
  );
}
