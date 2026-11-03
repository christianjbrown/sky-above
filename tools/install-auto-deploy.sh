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
{ crontab -l 2>/dev/null | grep -v 'deploy-when-clear.sh' || true; echo "$line"; } | crontab -
echo "installed: $line"
