# Frontend (React + Vite SPA)

工矿企业风险预警智能体的独立前端工程。原 Streamlit 单文件版已迁移至 React，
保留 `app_legacy_streamlit.py` 仅作历史参考，**不再纳入 docker-compose 默认启动**。

## 目录

```
frontend/
├── Dockerfile               # 多阶段构建（node 构建 → nginx 托管）
├── nginx.conf               # 反向代理 /api、/health、/docs 至后端
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── public/                  # 静态资源
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/                 # API 客户端、类型声明、SSE 流式解析
│   ├── components/          # SCADA 通用组件、ECharts 图表
│   ├── data/demoData.ts     # 演示企业 / Mock 决策（与后端 demo_data.py 一致）
│   ├── pages/               # 4 个 Tab 页面
│   └── styles/scada.css     # 工业控制室暗色主题
├── demo_data.py             # 后端 prediction.py mock 降级仍依赖此模块
├── __init__.py
└── app_legacy_streamlit.py  # 旧 Streamlit 单文件实现（已停用，仅作参考）
```

## 本地开发

```bash
npm install
npm run dev          # http://localhost:5173 ，Vite 代理 /api 至 http://localhost:8000
```

可通过 `VITE_DEV_API_TARGET` 改写后端地址：

```bash
VITE_DEV_API_TARGET=http://192.168.1.10:8000 npm run dev
```

## 生产构建

```bash
npm run build        # 输出到 dist/
npm run preview      # 4173 本地预览
```

## 容器一键部署

直接在 `mining_risk_agent/` 目录执行：

```bash
docker compose up --build
```

- 浏览器访问 `http://localhost:8501`
- 后端 Swagger：`http://localhost:8501/docs` 或 `http://localhost:8000/docs`
