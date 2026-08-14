#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$1"
if [[ "${output_dir}" != /* && ! "${output_dir}" =~ ^[A-Za-z]:[\\/] ]] \
  || [[ "${output_dir}" == "/" || "${output_dir}" == "${repo_dir}" ]]; then
  echo "unsafe bundle output: ${output_dir}" >&2
  exit 1
fi

rm -rf "${output_dir}"
mkdir -p "${output_dir}"

cp "${repo_dir}/static-replay-viewer/index.html" "${output_dir}/index.html"
# The League theater opens league.html in the same bundle; the ledger viewer
# already reads as a broadcast, so the theater shows the same document.
cp "${repo_dir}/static-replay-viewer/index.html" "${output_dir}/league.html"
