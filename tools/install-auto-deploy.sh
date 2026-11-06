#!/usr/bin/env bash
# Has the Pi deploy main by itself (see tools/deploy-when-clear.sh), from cron every
# five minutes, logging to the system journal as sky-above-deploy:
#
#     journalctl -t sky-above-deploy
#
# Run it once on the Pi from the checkout. It counts what is running now as deployed.
set -euo pipefail
cd "$(dirname "$0")/.."
here=$(pwd)
git rev-parse HEAD > .deployed
line="*/5 * * * * $here/tools/deploy-when-clear.sh 2>&1 | logger -t sky-above-deploy"
# Only this checkout's own line is replaced: another app on the Pi may have a
# deploy-when-clear.sh of its own in the same crontab.
{ crontab -l 2>/dev/null | grep -vF "$here/tools/deploy-when-clear.sh" || true; echo "$line"; } | crontab -
echo "installed: $line"
