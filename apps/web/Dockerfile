# syntax=docker/dockerfile:1
# OpenChart AI web app, served by nginx. Build from the repository root:
#   docker build -f apps/web/Dockerfile .

FROM node:25-alpine AS build
RUN corepack enable
WORKDIR /src
# Dependencies first, so code changes do not reinstall them.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/indicators/package.json packages/indicators/package.json
RUN pnpm install --frozen-lockfile --filter "@opencharts/web..."
COPY tsconfig.base.json ./
COPY packages/ui packages/ui
COPY packages/indicators/src packages/indicators/src
COPY apps/web apps/web
RUN pnpm --filter @opencharts/web build

# Unprivileged variant: runs as a non-root user and listens on 8080.
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx-proxy.conf /etc/nginx/openchart-proxy.conf
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
