#!/bin/sh
set -e

# Espera pela base de dados e pelo broker antes de arrancar.
wait_for() {
    host=$1; port=$2
    until nc -z "$host" "$port"; do
        echo "À espera de $host:$port..."
        sleep 1
    done
}

wait_for "${POSTGRES_HOST:-db}" "${POSTGRES_PORT:-5432}"
wait_for "${REDIS_BROKER_HOST:-redis-broker}" 6379

exec "$@"
