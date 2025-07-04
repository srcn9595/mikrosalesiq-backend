#!/bin/bash
set -e

# PostgreSQL hazır olana kadar bekle
until pg_isready -h host.docker.internal -p 5432 -U "$KC_DB_USERNAME"; do
  echo "[entrypoint] Postgres bekleniyor…"
  sleep 2
done

# (compose’ta tanımlamadıysanız) DB adını JDBC URL’den çek
: "${KC_DB_DATABASE:=keycloak}"

# Şema yoksa oluştur – idempotent
PGPASSWORD="$KC_DB_PASSWORD" \
psql -h host.docker.internal -U "$KC_DB_USERNAME" -d "$KC_DB_DATABASE" \
     -c "CREATE SCHEMA IF NOT EXISTS \"$KC_DB_SCHEMA\" AUTHORIZATION \"$KC_DB_USERNAME\";"

echo "[entrypoint] Keycloak başlatılıyor…"
exec /opt/keycloak/bin/kc.sh "$@"          #   docker-compose’ta verdiğiniz “start-dev”
