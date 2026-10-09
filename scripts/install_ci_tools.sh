#!/usr/bin/env bash
# Install fixed tool versions after verifying their release checksums.
set -euo pipefail
platform=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$(uname -m)" in
  x86_64) action_arch=amd64; leaks_arch=x64 ;;
  arm64|aarch64) action_arch=arm64; leaks_arch=arm64 ;;
  *) echo 'Unsupported CI tool architecture' >&2; exit 1 ;;
esac
tool_dir=${1:-.ci-tools}
mkdir -p "$tool_dir"
tool_dir=$(cd "$tool_dir" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
install_tool() {
  local repo=$1 version=$2 archive=$3 binary=$4
  local release="https://github.com/$repo/releases/download/v$version"
  curl --fail --silent --show-error --location "$release/$archive" -o "$work/$archive"
  curl --fail --silent --show-error --location "$release/${binary}_${version}_checksums.txt" -o "$work/checksums.txt"
  python3 - "$work" "$archive" <<'PY'
import hashlib
import pathlib
import sys
work, archive = pathlib.Path(sys.argv[1]), sys.argv[2]
expected = dict(line.split()[::-1] for line in (work / 'checksums.txt').read_text().splitlines())
actual = hashlib.sha256((work / archive).read_bytes()).hexdigest()
if actual != expected[archive]:
    raise SystemExit('CI tool checksum mismatch')
PY
  tar -xzf "$work/$archive" -C "$tool_dir" "$binary"
}
install_tool rhysd/actionlint 1.7.12 "actionlint_1.7.12_${platform}_${action_arch}.tar.gz" actionlint
install_tool gitleaks/gitleaks 8.30.1 "gitleaks_8.30.1_${platform}_${leaks_arch}.tar.gz" gitleaks
