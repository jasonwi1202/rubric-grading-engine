# syntax=docker/dockerfile:1

# ─── Base image ───────────────────────────────────────────────────────────────
FROM node:20-alpine AS base
WORKDIR /app

# Install libc6-compat in the shared base so all stages (build and runtime)
# have it available.  Some native npm packages need it at install time AND at
# container startup; putting it only in deps would leave the runner without it.
RUN apk add --no-cache libc6-compat

# ─── Dependencies ─────────────────────────────────────────────────────────────
FROM base AS deps

COPY package.json package-lock.json ./
RUN npm ci

# ─── Builder ──────────────────────────────────────────────────────────────────
FROM base AS builder

# Reuse the cached node_modules layer from deps to avoid a second npm ci.
COPY --from=deps /app/node_modules ./node_modules

# Copy source
COPY . .

# Build the Next.js application.
# NEXT_PUBLIC_* vars must be available at build time if used in SSG.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# ─── Runner ───────────────────────────────────────────────────────────────────
FROM base AS runner

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser  --system --uid 1001 nextjs

# Copy the standalone output and static assets produced by Next.js.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
