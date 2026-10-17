#!/usr/bin/env sh
# Pull fresh odds, recompute props, rebuild site/index.html. Python 3 standard library only.
set -e
cd "$(dirname "$0")"
python3 -m pipeline.fetch
python3 -m pipeline.props
python3 -m pipeline.build
