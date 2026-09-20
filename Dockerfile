# --- build stage: bundle the React UI -------------------------------------------
FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html tsconfig.json vite.config.ts ./
COPY public ./public
COPY frontend ./frontend
RUN pnpm build

# --- runtime stage: FastAPI backend (uv-managed venv) + static dist --------------
FROM python:3.12-slim
WORKDIR /app
# official uv install pattern (docs.astral.sh/uv): binary from the distroless image
# (pinned to the current stable minor — 0.12.x, tag verified on ghcr)
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
# venv built from the locked deps; then the rest of backend/ (app/, run_dev.py, …)
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --frozen --no-dev
COPY --from=build /app/dist ./dist
COPY backend ./backend
# offline safety net: the auto-fallback to fixtures ships with the image
COPY fixtures ./fixtures
ENV HOST=0.0.0.0 PORT=3000 DIST_DIR=/app/dist ALR_DATA_DIR=/app/data
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=10 --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','3000')+'/api/health')"
# venv python directly: no uv on the runtime path, no interpreter probing.
# cwd stays /app — fixtures/ and data/ resolve cwd-relative.
CMD ["/app/backend/.venv/bin/python", "/app/backend/pyserver_main.py"]
