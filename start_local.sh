#!/usr/bin/env bash
# Lança o Factos localmente.
#
# Por omissão (dev, com hot reload): Postgres, Redis, workers Celery e beat em Docker; o backend Django
# (runserver) e o frontend (Vite) correm na máquina. Os workers e o beat reiniciam sozinhos quando o código
# Python muda (watchfiles). Ctrl+C pára o backend e o frontend; o Docker continua (docker compose down pára).
#
# Uso: ./start_local.sh [--docker] [--no-build]
#   --docker    tudo em Docker, incluindo backend e frontend (profile docker-app), sem processos na máquina
#   --no-build  não reconstrói as imagens
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$PWD"

ALL_DOCKER=0
BUILD="--build"
for arg in "$@"; do
    case "$arg" in
        --docker) ALL_DOCKER=1 ;;
        --no-build) BUILD="" ;;
        *) echo "Opção desconhecida: $arg" >&2; exit 1 ;;
    esac
done

if ! docker info >/dev/null 2>&1; then
    echo "O Docker não está a correr. Abre o Docker Desktop e tenta de novo." >&2
    exit 1
fi

if [ ! -f .env ]; then
    echo "Sem .env: a criar a partir do .env.example"
    cp .env.example .env
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a
BACKEND_PORT="${BACKEND_HOST_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_HOST_PORT:-5180}"
DB_PORT="${POSTGRES_HOST_PORT:-5442}"
BROKER_PORT="${REDIS_BROKER_HOST_PORT:-6390}"
CACHE_PORT="${REDIS_CACHE_HOST_PORT:-6391}"

wait_health() {
    printf "À espera do backend"
    for _ in $(seq 1 60); do
        if curl -sf "http://localhost:${BACKEND_PORT}/api/health/" >/dev/null 2>&1; then
            echo " ok"
            return 0
        fi
        printf "."
        sleep 2
    done
    echo
    return 1
}

print_urls() {
    cat <<EOF

Factos a correr:
  Frontend   http://localhost:${FRONTEND_PORT}
  API        http://localhost:${BACKEND_PORT}/api/
  API docs   http://localhost:${BACKEND_PORT}/api/docs/
  Admin      http://localhost:${BACKEND_PORT}/admin/
  Dashboard  http://localhost:${BACKEND_PORT}/dashboard/crawl/
  Postgres   localhost:${DB_PORT}  (user ${POSTGRES_USER}, bd ${POSTGRES_DB})

Logs Docker: docker compose logs -f [serviço]
Parar tudo:  docker compose down
EOF
}

# --- Tudo em Docker --------------------------------------------------------------------------------------------
if [ "$ALL_DOCKER" = "1" ]; then
    docker compose --profile docker-app up -d $BUILD
    wait_health || { docker compose ps -a; docker compose logs --tail 30 migrate backend; exit 1; }
    docker compose --profile docker-app ps --format 'table {{.Service}}\t{{.Status}}'
    print_urls
    exit 0
fi

# --- Dev: infra + workers em Docker, backend e frontend na máquina -------------------------------------------------
# Se o backend/frontend estiverem a correr em Docker (arranque anterior com --docker), saem para libertar as portas.
docker compose --profile docker-app rm -sf backend frontend >/dev/null 2>&1 || true
docker compose up -d $BUILD

# Python: venv em backend/.venv (reinstala quando o requirements.txt muda).
VENV="$ROOT/backend/.venv"
if [ ! -x "$VENV/bin/python" ] || [ "$ROOT/backend/requirements.txt" -nt "$VENV/.installed" ]; then
    echo "A preparar o venv do backend (backend/.venv)..."
    if command -v uv >/dev/null 2>&1; then
        [ -x "$VENV/bin/python" ] || uv venv "$VENV" --python 3.13 -q
        uv pip install -q --python "$VENV/bin/python" -r backend/requirements.txt
    else
        [ -x "$VENV/bin/python" ] || python3.13 -m venv "$VENV"
        "$VENV/bin/pip" install -q -r backend/requirements.txt
    fi
    touch "$VENV/.installed"
fi

# Node: dependências do frontend (registo público; o npm local aponta para um Nexus privado).
if [ ! -d frontend/node_modules ] || [ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]; then
    echo "A instalar as dependências do frontend..."
    (cd frontend && npm ci --registry https://registry.npmjs.org --no-audit --no-fund)
fi

# O .env é escrito para a rede do Docker; na máquina os serviços estão nas portas publicadas.
export POSTGRES_HOST=localhost
export POSTGRES_PORT="$DB_PORT"
export REDIS_BROKER_URL="redis://localhost:${BROKER_PORT}/0"
export CELERY_RESULT_BACKEND="redis://localhost:${BROKER_PORT}/1"
export REDIS_CACHE_URL="redis://localhost:${CACHE_PORT}/0"
export RAW_HTML_ROOT="$ROOT/backend/data/raw"
export ARTICLES_IMPORT_DIR="$ROOT/sites/out"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS},localhost,127.0.0.1"

# Pára o backend e o frontend no fim (Ctrl+C ou erro).
trap 'trap - INT TERM EXIT; kill 0 2>/dev/null' INT TERM EXIT

(cd backend && exec "$VENV/bin/python" manage.py runserver "0.0.0.0:${BACKEND_PORT}") 2>&1 \
    | sed -u 's/^/[backend]  /' &
(cd frontend && VITE_API_PROXY_TARGET="http://localhost:${BACKEND_PORT}" \
    exec npx vite --port "${FRONTEND_PORT}" --strictPort) 2>&1 | sed -u 's/^/[frontend] /' &

if ! wait_health; then
    echo "O backend não ficou saudável. Estado do Docker:" >&2
    docker compose ps -a
    exit 1
fi
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
print_urls
echo "Backend e frontend na máquina, com hot reload. Ctrl+C pára-os."
wait
