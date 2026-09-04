#!/usr/bin/env bash
set -euo pipefail

# Start the gateway from this checkout regardless of the caller's working directory.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$script_dir"

venv_python="./.venv/bin/python"
settings_path="./gateway-settings.toml"

if [[ ! -x "$venv_python" ]]; then
    echo "Cannot find virtual-environment Python: $script_dir/${venv_python#./}" >&2
    echo "Run 'uv sync' in $script_dir before starting the gateway." >&2
    exit 1
fi

if [[ ! -f "$settings_path" ]]; then
    echo "Cannot find gateway settings: $script_dir/${settings_path#./}" >&2
    echo "Copy gateway-settings.toml.template to gateway-settings.toml and configure it." >&2
    exit 1
fi

export PYTHONUNBUFFERED=1
echo "Starting the SPD3000 gateway from: $script_dir"

# exec lets Supervisor own and signal the actual gateway process.
exec "$venv_python" -m siglent_spd3000.cli gateway serve --config "$settings_path" "$@"
