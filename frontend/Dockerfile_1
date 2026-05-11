# =============================================================================
# 工矿企业风险预警智能体 — 前端镜像
# 多阶段构建：Node 构建 SPA → Nginx 托管静态资源 + 反向代理 /api 与 /health 至后端
# =============================================================================

# ---------- Build Stage ----------
FROM node:20-alpine AS builder

WORKDIR /app

# 优先复制锁文件以利用缓存
COPY package.json package-lock.json* ./

# 锁文件存在时使用 npm ci，否则退化为 npm install
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src

RUN npm run build

# ---------- Runtime Stage ----------
FROM nginx:alpine

# 内置 wget 用于 healthcheck（alpine 镜像默认带 wget，无需额外安装）

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O - http://localhost/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
