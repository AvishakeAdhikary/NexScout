# NexScout web (Next.js). UNVERIFIED until Docker is available. See docs/ROADMAP.md.
# Rewrites are resolved at build time, so NEXSCOUT_API_ORIGIN must be given as a build arg.
FROM node:24-alpine AS build
WORKDIR /app
ARG NEXSCOUT_API_ORIGIN=http://api:8000
ENV NEXSCOUT_API_ORIGIN=$NEXSCOUT_API_ORIGIN NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
