#!/bin/bash
set -eu
exec /bin/bash "$(dirname "$0")/install.sh" --uninstall
