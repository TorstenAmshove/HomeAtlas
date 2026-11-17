FROM node:lts-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94 AS build
WORKDIR /app
ARG VITE_BUILD_SHA=dev
ARG VITE_BUILD_TIME=
ENV VITE_BUILD_SHA=$VITE_BUILD_SHA
ENV VITE_BUILD_TIME=$VITE_BUILD_TIME
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# nginx's own "stable" line, digest-pinned (same idea as node:lts-alpine above): Renovate proposes
# every rebuild - security fixes and the yearly move to the next stable branch - as a digest PR.
# A fixed minor tag like 1.27-alpine stops receiving rebuilds once that branch is retired.
FROM nginx:stable-alpine@sha256:901e593c95dc85f5a729f5765516321366ef4ac401821431d408897e95287d0a
COPY --from=build /app/dist /usr/share/nginx/html
# The nginx image runs envsubst over /etc/nginx/templates/*.template at startup, which is how
# HOMEATLAS_PORT reaches the config -- with network_mode host a compose `ports:` mapping is
# ignored, so the listen port has to be baked into nginx itself.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV HOMEATLAS_PORT=8280
ENV HOMEATLAS_API_PORT=8281
# Restrict envsubst to our own variables. Without the filter it substitutes every variable that
# happens to be set, which would eat nginx's own $host / $remote_addr / $uri if the environment
# ever contained a same-named variable.
ENV NGINX_ENVSUBST_FILTER="^HOMEATLAS_"
