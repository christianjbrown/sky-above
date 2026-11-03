#!/bin/sh
# Every check the code has to pass, run by the pre-push hook and by CI alike: the
# compose file parses, the watcher is formatted, linted, strictly typed and fully
# covered by its tests, and the receiver's browser code is linted and fully covered.
set -e
cd "$(dirname "$0")/.."
docker compose --env-file .env.example config --quiet
echo "docker-compose.yml is valid"
(
  cd watcher
  uv run --frozen ruff format --check src tests
  uv run --frozen ruff check src tests
  uv run --frozen mypy
  uv run --frozen pytest -q
)
[ -d node_modules ] || npm ci --silent
npm run --silent check
