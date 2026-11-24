#!/usr/bin/env bash
# Usage: scripts/package-release.sh v0.6.0 /path/to/output
set -euo pipefail
if [[ $# != 2 || ! $1 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo 'Usage: package-release.sh vMAJOR.MINOR.PATCH OUTPUT_DIRECTORY' >&2
    exit 2
fi
tag=$1
mkdir -p "$2"
output=$(cd "$2" && pwd)
cd "$(dirname "$0")/.."
commit=$(git rev-parse --verify "refs/tags/$tag^{commit}")
export TZ=UTC
common=(AGENTS.md LICENSE README.md SECURITY.md install.sh uninstall.sh lib skills tests/test_core.py tests/test_shell.py tests/test_agent_skill.py tests/test_upgrade.py)
prefix="bitwarden-window-${tag#v}"
linux="$prefix-omarchy.tar.gz"
mac="$prefix-macos.zip"
git archive --format=tar.gz --prefix="$prefix-omarchy/" --output="$output/$linux" \
    "$commit" -- "${common[@]}" omarchy tests/test_install.py
git archive --format=zip --prefix="$prefix-macos/" --output="$output/$mac" \
    "$commit" -- "${common[@]}" osx tests/test_macos.py
cd "$output"
if command -v sha256sum >/dev/null; then
    sha256sum "$linux" "$mac" > SHA256SUMS
else
    shasum -a 256 "$linux" "$mac" > SHA256SUMS
fi
