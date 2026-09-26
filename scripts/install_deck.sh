#!/usr/bin/env bash
# Copy this repo's decks into an EDOPro install so they appear in the client's
# deck list at startup.
#
# EDOPro reads ~/Applications/ProjectIgnis/deck/*.ydk on launch; the filename
# (minus .ydk) is the name shown in the deck selector. Point elsewhere with
# EDOPRO_DIR (default ~/Applications/ProjectIgnis), the same lookup as
# scripts/verify_yrp.py, engine/puzzle.py and tests/test_yrp_edopro.py.
#
# Copies rather than symlinks on purpose: EDOPro rewrites a deck file when you
# edit it in the client, and a symlink would push those edits back into the
# repo's pinned list.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDOPRO="${EDOPRO_DIR:-$HOME/Applications/ProjectIgnis}"
DEST="$EDOPRO/deck"

if [ ! -d "$DEST" ]; then
  echo "no EDOPro deck directory at $DEST" >&2
  echo "install EDOPro, or set EDOPRO_DIR to point at it" >&2
  exit 1
fi

shopt -s nullglob
for src in "$ROOT"/data/decks/*.ydk; do
  cp "$src" "$DEST/"
  echo "installed $(basename "$src") -> $DEST"
done
