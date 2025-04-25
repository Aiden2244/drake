#!/bin/bash

# Internal script to prepare the build location.

set -eu -o pipefail

readonly d="$(mktemp -d ~/.cache/drake-wheel-build/XXXXXXXXXX)"
ln -nsf "${d}" /tmp/drake-wheel-build
