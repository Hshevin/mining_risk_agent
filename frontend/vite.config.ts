import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发期通过 Vite proxy 把 /api、/health 转发到 FastAPI
// 生产期由前端镜像内的 Nginx 反向代理（见 nginx.conf）
const backendTarget = process.env.VITE_DEV_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/health": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
});
