#!/usr/bin/env bash
# Brings the Pi up to date with main, straight away. Run it on the Pi after a change has
# landed, from anywhere:
#
#     ~/sky-above/tools/deploy.sh
#
# It pulls main, rebuilds what changed and swaps it in. Nothing runs it on a schedule.
set -euo pipefail

# All of it in a function, which bash reads in full before running, because the merge
# below can rewrite this very file.
main() {
    cd "$(dirname "$0")/.."

    before=$(git rev-parse HEAD)
    git fetch -q origin main
    git merge -q --ff-only origin/main
    after=$(git rev-parse HEAD)

    docker compose up -d --build --remove-orphans
    # nginx renders its templates only when it starts, and up leaves a receiver whose
    # compose settings are unchanged running, so a change to nginx/ needs a restart.
    if ! git diff --quiet "$before" "$after" -- nginx; then
        docker compose restart receiver
    fi
    echo "deployed $(git log -1 --format='%h %s')"
}

main "$@"
exit
