#!/usr/bin/env bash
set -euo pipefail

repo="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
source="$repo/vendor/wiicompiled"
stage="$repo/build/wiicompiled-fpscr"

# Keep the established output path for translator and native-registration callers.
# Maintained source lives in Git; this command never replays translator patches.
if [[ ! -f "$source/translator/src/Translator.Cli/Translator.Cli.csproj" ]]; then
  echo 'ERROR: missing tracked WiiCompiled translator source' >&2
  exit 1
fi
python3 "$repo/scripts/stage-maintained-translator.py" "$stage"

# KartPad Shadow: prefer an explicit/PATH dotnet (CI uses actions/setup-dotnet,
# Linux hosts use ~/.dotnet); fall back to the Homebrew dotnet@8 layout.
dotnet_bin="${DOTNET_BIN:-$(command -v dotnet || true)}"
if [[ -z "$dotnet_bin" ]]; then
  dotnet_bin=/opt/homebrew/opt/dotnet@8/bin/dotnet
fi
project="$stage/translator/src/Translator.Cli/Translator.Cli.csproj"
"$dotnet_bin" build "$project" -c Release
