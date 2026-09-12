FROM node:22-alpine AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ARG LOOM_API_INTERNAL_URL
ARG LOOM_API_INTERNAL_HOSTPORT
ENV LOOM_API_INTERNAL_URL=$LOOM_API_INTERNAL_URL
ENV LOOM_API_INTERNAL_HOSTPORT=$LOOM_API_INTERNAL_HOSTPORT
COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend ./
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
