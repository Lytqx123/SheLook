# ---- 基础 ----
FROM node:22-alpine AS base
WORKDIR /app
# postinstall 会执行 fix-qrcode.mjs，依赖安装层必须同时包含该脚本。
COPY package.json package-lock.json fix-qrcode.mjs ./
RUN npm ci

# ---- 构建 ----
FROM base AS build
COPY . .
# 确保 public 目录存在（Next.js standalone 输出需要，本项目未使用 public 静态资源）
RUN mkdir -p public
RUN npm run build

# ---- 生产运行 ----
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1

# 安装 wget 用于 Docker 健康检查
RUN apk add --no-cache wget

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT 3000
ENV HOSTNAME "0.0.0.0"

CMD ["node", "server.js"]
