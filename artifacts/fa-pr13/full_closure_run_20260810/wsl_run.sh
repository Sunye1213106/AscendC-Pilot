#!/usr/bin/env bash
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=run_env.sh
source "$SCRIPT_DIR/run_env.sh"
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
exec "$@"
