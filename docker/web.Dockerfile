# NexScout web (Next.js). The /api proxy target is read at runtime from NEXSCOUT_API_ORIGIN
# (src/proxy.ts), so one image works in compose, Easy mode and behind any backend address.
FROM node:24-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 NEXSCOUT_API_ORIGIN=http://api:8000
COPY --from=build --chown=node:node /app ./
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
