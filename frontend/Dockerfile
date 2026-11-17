FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /app
ARG VITE_BUILD_SHA=dev
ARG VITE_BUILD_TIME=
ENV VITE_BUILD_SHA=$VITE_BUILD_SHA
ENV VITE_BUILD_TIME=$VITE_BUILD_TIME
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Exact version + digest: Renovate proposes version updates as readable PRs (stable branch only,
# i.e. even minor versions - see renovate-config) and upstream rebuilds of the same tag (security
# fixes in Alpine) as digest PRs.
FROM nginx:1.30.6-alpine@sha256:901e593c95dc85f5a729f5765516321366ef4ac401821431d408897e95287d0a
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
