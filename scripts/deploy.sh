#!/usr/bin/env bash
# Deploy the backend from a git tag or SHA on the production host (WHI-849).
#
# Intended to run ON the VPS (or: ssh host 'sudo -E DEPLOY_REF=vX.Y.Z ./scripts/deploy.sh').
# Never rsyncs a developer working tree — the running revision is always a git object.
#
# Required:
#   DEPLOY_REF   tag (preferred) or full/short git SHA to check out
#
# Optional (defaults match docs/DEPLOYMENT.md):
#   APP_DIR              app checkout (default: /opt/spread-comparison-tools)
#   ENV_FILE             secrets file (default: /etc/spread-comparison/env)
#   HOST_CONFIG_DIR      host overlays source (default: /etc/spread-comparison/config)
#   REVISION_FILE        deployed-revision record (default: /etc/spread-comparison/deployed-revision)
#   SERVICE_NAME         systemd unit without .service (default: spread-comparison)
#   HEALTH_URL           post-restart check (default: http://127.0.0.1:8000/health)
#   HEALTH_TIMEOUT_SEC   seconds to wait for /health (default: 60)
#   SECRETS_SRC          if set, install this file to ENV_FILE (mode 0600, root-owned)
#   SKIP_SECRETS_SYNC    set to 1 to refuse secret install even if SECRETS_SRC is set
#   SKIP_RESTART         set to 1 to skip systemctl restart (debug only)
#   DRY_RUN              set to 1 to print steps without mutating (git fetch still runs)
#
# Exit non-zero on any failure; /health must report HTTP 200 + JSON status ok.
set -euo pipefail

log() { printf 'deploy: %s\n' "$*"; }
die() { printf 'deploy: ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

APP_DIR="${APP_DIR:-/opt/spread-comparison-tools}"
ENV_FILE="${ENV_FILE:-/etc/spread-comparison/env}"
HOST_CONFIG_DIR="${HOST_CONFIG_DIR:-/etc/spread-comparison/config}"
REVISION_FILE="${REVISION_FILE:-/etc/spread-comparison/deployed-revision}"
SERVICE_NAME="${SERVICE_NAME:-spread-comparison}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-60}"
SECRETS_SRC="${SECRETS_SRC:-}"
SKIP_SECRETS_SYNC="${SKIP_SECRETS_SYNC:-0}"
SKIP_RESTART="${SKIP_RESTART:-0}"
DRY_RUN="${DRY_RUN:-0}"

DEPLOY_REF="${DEPLOY_REF:-}"
[[ -n "${DEPLOY_REF}" ]] || die "DEPLOY_REF is required (tag or SHA)"

require_cmd git
require_cmd uv
require_cmd curl
if [[ "${SKIP_RESTART}" != "1" && "${DRY_RUN}" != "1" ]]; then
  require_cmd systemctl
fi

[[ -d "${APP_DIR}/.git" ]] || die "APP_DIR is not a git checkout: ${APP_DIR}"
[[ -f "${ENV_FILE}" || -n "${SECRETS_SRC}" ]] || die \
  "secrets file missing: ${ENV_FILE} (set SECRETS_SRC to install one)"

run() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "DRY_RUN: $*"
    return 0
  fi
  "$@"
}

# --- 1. Sync code (git) -------------------------------------------------------
log "step 1/6: sync code (git fetch + checkout ${DEPLOY_REF})"
cd "${APP_DIR}"

prev_sha="$(git rev-parse HEAD 2>/dev/null || echo none)"
log "current HEAD: ${prev_sha}"

run git fetch --tags --prune origin
# Resolve ref after fetch so tags/SHAs that only exist on origin work.
if [[ "${DRY_RUN}" == "1" ]]; then
  new_sha="(dry-run)"
else
  if ! new_sha="$(git rev-parse --verify "${DEPLOY_REF}^{commit}" 2>/dev/null)"; then
    if ! new_sha="$(git rev-parse --verify "origin/${DEPLOY_REF}^{commit}" 2>/dev/null)"; then
      die "cannot resolve DEPLOY_REF=${DEPLOY_REF} after fetch"
    fi
  fi
  log "target SHA: ${new_sha}"
  if [[ "${prev_sha}" != "${new_sha}" ]]; then
    log "commits being deployed:"
    git --no-pager log --oneline "${prev_sha}..${new_sha}" 2>/dev/null || true
  else
    log "already at ${new_sha} (idempotent re-apply)"
  fi
  # Detached HEAD at an immutable object — never deploy a moving branch tip.
  git checkout --detach "${new_sha}"
fi

# --- 2. Sync secrets ----------------------------------------------------------
log "step 2/6: sync secrets"
if [[ -n "${SECRETS_SRC}" && "${SKIP_SECRETS_SYNC}" != "1" ]]; then
  [[ -f "${SECRETS_SRC}" ]] || die "SECRETS_SRC not a file: ${SECRETS_SRC}"
  log "installing secrets from ${SECRETS_SRC} -> ${ENV_FILE}"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "DRY_RUN: install -m 0600 ${SECRETS_SRC} ${ENV_FILE}"
  else
    install -d -m 0750 "$(dirname "${ENV_FILE}")"
    # Preserve root ownership when running as root; otherwise keep current owner.
    if [[ "$(id -u)" -eq 0 ]]; then
      install -m 0600 -o root -g root "${SECRETS_SRC}" "${ENV_FILE}"
    else
      install -m 0600 "${SECRETS_SRC}" "${ENV_FILE}"
      log "warning: not root — could not chown root:root; fix ownership manually"
    fi
  fi
elif [[ -n "${SECRETS_SRC}" && "${SKIP_SECRETS_SYNC}" == "1" ]]; then
  log "SKIP_SECRETS_SYNC=1 — leaving ${ENV_FILE} unchanged"
else
  log "SECRETS_SRC unset — keeping existing ${ENV_FILE}"
fi
[[ -f "${ENV_FILE}" ]] || die "secrets file still missing after sync: ${ENV_FILE}"
# Never print file contents. Only confirm presence + mode.
if stat --version >/dev/null 2>&1; then
  env_mode="$(stat -c '%a' "${ENV_FILE}")"
else
  env_mode="$(stat -f '%OLp' "${ENV_FILE}")"
fi
log "secrets file present mode=${env_mode} path=${ENV_FILE}"
# Accept 600 / 0600 (GNU vs BSD stat).
case "${env_mode}" in
  600|0600) ;;
  *) die "secrets file must be mode 0600 (got ${env_mode})" ;;
esac

# --- 3. Re-apply host config overlays -----------------------------------------
log "step 3/6: re-apply host config from ${HOST_CONFIG_DIR}"
# Drop any *.local.yaml that might have leaked into the tree (old rsync, laptop
# checkout), then install only what the host inventory deliberately provides.
if [[ "${DRY_RUN}" != "1" ]]; then
  find "${APP_DIR}/config" -name '*.local.yaml' -type f -print -delete 2>/dev/null || true
fi
applied=0
if [[ -d "${HOST_CONFIG_DIR}" ]]; then
  shopt -s nullglob
  for src in "${HOST_CONFIG_DIR}"/*.local.yaml; do
    base="$(basename "${src}")"
    dest="${APP_DIR}/config/${base}"
    log "host overlay: ${src} -> ${dest}"
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "DRY_RUN: install -m 0644 ${src} ${dest}"
    else
      install -m 0644 "${src}" "${dest}"
    fi
    applied=$((applied + 1))
  done
  if [[ -d "${HOST_CONFIG_DIR}/fees" ]]; then
    for src in "${HOST_CONFIG_DIR}/fees"/*.local.yaml; do
      base="$(basename "${src}")"
      dest="${APP_DIR}/config/fees/${base}"
      log "host overlay: ${src} -> ${dest}"
      if [[ "${DRY_RUN}" == "1" ]]; then
        log "DRY_RUN: install -m 0644 ${src} ${dest}"
      else
        install -d -m 0755 "${APP_DIR}/config/fees"
        install -m 0644 "${src}" "${dest}"
      fi
      applied=$((applied + 1))
    done
  fi
  shopt -u nullglob
  log "host overlays applied: ${applied}"
else
  log "HOST_CONFIG_DIR absent (${HOST_CONFIG_DIR}) — committed config only"
fi

# --- 4. Dependencies ----------------------------------------------------------
log "step 4/6: uv sync --locked --no-dev"
run uv sync --locked --no-dev --directory "${APP_DIR}"

# --- 5. Restart ---------------------------------------------------------------
log "step 5/6: restart ${SERVICE_NAME}"
if [[ "${SKIP_RESTART}" == "1" ]]; then
  log "SKIP_RESTART=1 — not restarting"
elif [[ "${DRY_RUN}" == "1" ]]; then
  log "DRY_RUN: systemctl restart ${SERVICE_NAME}"
else
  systemctl restart "${SERVICE_NAME}"
fi

# --- 6. Verify health + record revision ---------------------------------------
log "step 6/6: verify ${HEALTH_URL}"
if [[ "${DRY_RUN}" == "1" ]]; then
  log "DRY_RUN: skip health poll and revision write"
  log "done (dry-run)"
  exit 0
fi

if [[ "${SKIP_RESTART}" == "1" ]]; then
  log "SKIP_RESTART=1 — skipping health poll"
else
  deadline=$((SECONDS + HEALTH_TIMEOUT_SEC))
  body=""
  http_code=""
  health_tmp="$(mktemp)"
  trap 'rm -f "${health_tmp}"' EXIT
  while (( SECONDS < deadline )); do
    http_code="$(curl -sS -o "${health_tmp}" \
      -w '%{http_code}' --max-time 5 "${HEALTH_URL}" || true)"
    if [[ "${http_code}" == "200" ]]; then
      body="$(cat "${health_tmp}" 2>/dev/null || true)"
      # Require JSON status field "ok" without depending on jq.
      if printf '%s' "${body}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
        log "health ok: ${body}"
        break
      fi
    fi
    log "health not ready yet (http=${http_code:-none}); retrying..."
    sleep 1
  done
  if [[ "${http_code}" != "200" ]] || ! printf '%s' "${body}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    die "service unhealthy after ${HEALTH_TIMEOUT_SEC}s (http=${http_code:-none} body=${body:-<empty>})"
  fi
fi

deployed_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"
deployed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
install -d -m 0755 "$(dirname "${REVISION_FILE}")"
{
  echo "sha=${deployed_sha}"
  echo "ref=${DEPLOY_REF}"
  echo "deployed_at=${deployed_at}"
} >"${REVISION_FILE}.tmp"
mv "${REVISION_FILE}.tmp" "${REVISION_FILE}"
log "recorded revision at ${REVISION_FILE}:"
cat "${REVISION_FILE}"

log "done"
