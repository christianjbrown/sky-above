#!/usr/bin/env bash
# Brings the Pi up to date with main, without cutting a plane off mid-announcement.
#
# It builds the new images while the old ones carry on, then waits for the card to be
# clear before swapping them over: nothing overhead, nothing on its way and no followed
# flight showing. If the card is busy it leaves the swap for the next run, and quiet
# hours mean there is a clear moment every night. tools/install-auto-deploy.sh runs it
# every five minutes from cron.
set -euo pipefail

# All of it in a function, which bash reads in full before running, because the merge
# below can rewrite this very file.
main() {
    cd "$(dirname "$0")/.."

    # One run at a time: a build can take longer than five minutes.
    exec 9>"${TMPDIR:-/tmp}/sky-above-deploy.lock"
    flock -n 9 || exit 0

    deployed_file=.deployed
    git fetch -q origin main
    target=$(git rev-parse origin/main)
    [ "$target" = "$(cat "$deployed_file" 2>/dev/null)" ] && exit 0

    echo "deploying $(git log -1 --format='%h %s' "$target")"
    git merge -q --ff-only "$target"
    docker compose build -q

    live_port=$(sed -n 's/^LIVE_PORT=//p' .env 2>/dev/null | tail -1)
    card=$(curl -sf --max-time 5 "http://localhost:${live_port:-8091}/planes.json" || echo '{"type": "clear"}')
    if ! python3 -c 'import json, sys; sys.exit(json.loads(sys.argv[1]).get("type") != "clear")' "$card"; then
        echo "the card is busy, trying again next time"
        exit 0
    fi

    docker compose up -d --remove-orphans
    # nginx renders its templates only when it starts, and up leaves a receiver whose
    # compose settings are unchanged running, so a change to nginx/ needs a restart.
    deployed=$(cat "$deployed_file" 2>/dev/null || true)
    if [ -z "$deployed" ] || ! git diff --quiet "$deployed" "$target" -- nginx; then
        docker compose restart receiver
    fi
    echo "$target" > "$deployed_file"
    echo "deployed $(git log -1 --format='%h' "$target")"
}

main "$@"
exit
