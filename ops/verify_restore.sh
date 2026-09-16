#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
test -f .env
set -a
# shellcheck disable=SC1091
. ./.env
set +a
: "${DATABASE_USER:?required}"

mkdir -p artifacts
compose=(docker compose -f compose.yaml -f compose.test.yaml)
run_id="$(date -u +%Y%m%d%H%M%S)_$$"
source_db="restore_source_${run_id}"
target_db="restore_target_${run_id}"
dump_path="artifacts/phase1_${run_id}.dump"
media_dump_path="artifacts/phase2_${run_id}.tar.gz"
source_media="/app/private-media/restore_source_${run_id}"
target_media="/app/private-media/restore_target_${run_id}"
result_tmp="artifacts/restore-result_${run_id}.txt"
result_path="artifacts/restore-result.txt"
rm -f -- "$result_path"

cleanup() {
  status=$?
  trap - EXIT
  set +e
  cleanup_failed=0
  "${compose[@]}" exec -T postgres-test dropdb --if-exists --maintenance-db=postgres --username "$DATABASE_USER" "$target_db" >/dev/null 2>&1 || cleanup_failed=1
  "${compose[@]}" exec -T postgres-test dropdb --if-exists --maintenance-db=postgres --username "$DATABASE_USER" "$source_db" >/dev/null 2>&1 || cleanup_failed=1
  rm -f -- "$dump_path" "$media_dump_path" || cleanup_failed=1
  "${compose[@]}" run --rm --no-deps -T test rm -rf -- "$source_media" "$target_media" >/dev/null 2>&1 || cleanup_failed=1
  if [[ -n "$result_tmp" ]]; then
    rm -f -- "$result_tmp" || cleanup_failed=1
  fi
  if [[ "$cleanup_failed" -ne 0 ]]; then
    rm -f -- "$result_path"
    status=1
  fi
  exit "$status"
}

"${compose[@]}" up -d --wait postgres-test
trap cleanup EXIT
"${compose[@]}" build test
"${compose[@]}" exec -T postgres-test createdb --maintenance-db=postgres --username "$DATABASE_USER" "$source_db"
"${compose[@]}" run --rm -e DATABASE_NAME="$source_db" test python manage.py migrate --noinput
"${compose[@]}" run --rm -e DATABASE_NAME="$source_db" -e CATALOG_MEDIA_ROOT="$source_media" test python manage.py seed_restore_probe --marker "$run_id"
{
  printf 'database=source\n'
  "${compose[@]}" run --rm -e DATABASE_NAME="$source_db" -e CATALOG_MEDIA_ROOT="$source_media" -e PGOPTIONS="-c default_transaction_read_only=on" test python manage.py verify_restore_probe --marker "$run_id"
} > "$result_tmp"
"${compose[@]}" exec -T postgres-test pg_dump --username "$DATABASE_USER" --format=custom --dbname "$source_db" > "$dump_path"
"${compose[@]}" run --rm --no-deps -T test tar -czf - -C "$source_media" . > "$media_dump_path"
"${compose[@]}" exec -T postgres-test createdb --maintenance-db=postgres --username "$DATABASE_USER" "$target_db"
"${compose[@]}" exec -T postgres-test pg_restore --username "$DATABASE_USER" --exit-on-error --no-owner --dbname "$target_db" < "$dump_path"
if "${compose[@]}" run --rm --no-deps -T -e DATABASE_NAME="$target_db" -e CATALOG_MEDIA_ROOT="$target_media" -e PGOPTIONS="-c default_transaction_read_only=on" test python manage.py verify_restore_probe --marker "$run_id" >/dev/null 2>&1; then
  printf 'Verification unexpectedly accepted a database without restored photos.\n' >&2
  exit 1
fi
"${compose[@]}" run --rm --no-deps -T test sh -c 'mkdir -p "$1" && tar -xzf - -C "$1"' sh "$target_media" < "$media_dump_path"
{
  printf 'database=target\n'
  "${compose[@]}" run --rm -e DATABASE_NAME="$target_db" test python manage.py migrate --check
  "${compose[@]}" run --rm -e DATABASE_NAME="$target_db" -e CATALOG_MEDIA_ROOT="$target_media" -e PGOPTIONS="-c default_transaction_read_only=on" test python manage.py verify_restore_probe --marker "$run_id"
  printf 'media=restored_from_archive\n'
} >> "$result_tmp"
mv -- "$result_tmp" "$result_path"
result_tmp=""
