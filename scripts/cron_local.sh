#!/usr/bin/env bash
# Local fallback scheduler (optional). Prefer Cursor Automation when available.
# Example crontab (Asia/Shanghai): 10 15 * * 1-5 /path/to/scripts/cron_local.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 scripts/run_daily.py
echo "Report ready: $ROOT/data/latest_report.json"
