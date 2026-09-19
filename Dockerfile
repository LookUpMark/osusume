# --- build stage: bundle the React UI -------------------------------------------
FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN pnpm build

# --- runtime stage: hono server (TS via node type stripping) + static dist ------
FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# react/react-dom live in devDependencies: the UI is already bundled into dist/
RUN pnpm install --prod --frozen-lockfile
COPY --from=build /app/dist ./dist
COPY src/server ./src/server
COPY src/shared ./src/shared
# offline safety net: the auto-fallback to fixtures ships with the image
COPY fixtures ./fixtures
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT??3000)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "src/server/index.ts"]
