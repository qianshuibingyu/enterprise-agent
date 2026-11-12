FROM node:20-bookworm-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:20-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY --from=build /app/dist ./dist
RUN useradd --create-home --uid 10001 bridge && mkdir -p /var/lib/whatsapp-auth && chown -R bridge:bridge /app /var/lib/whatsapp-auth
USER bridge
EXPOSE 8090
CMD ["node", "dist/index.js"]
