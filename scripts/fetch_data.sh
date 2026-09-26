#!/usr/bin/env bash
# Fetch the card pool: card database (BabelCDB) + Lua card scripts (CardScripts).
#
# Both are pinned by commit hash into data/DATA_COMMITS so benchmark results
# stay reproducible after the format moves on. The core does not ship card
# data - it asks our callbacks for it, which is what makes pinning possible.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
mkdir -p "$DATA"

CDB_REF="${CDB_REF:-master}"
SCRIPTS_REF="${SCRIPTS_REF:-master}"
PUZZLES_REF="${PUZZLES_REF:-master}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

if [ ! -d "$DATA/BabelCDB/.git" ]; then
  log "cloning BabelCDB (card database)"
  git clone --depth 1 --branch "$CDB_REF" \
    https://github.com/ProjectIgnis/BabelCDB.git "$DATA/BabelCDB"
fi

if [ ! -d "$DATA/CardScripts/.git" ]; then
  log "cloning CardScripts (Lua card effects)"
  git clone --depth 1 --branch "$SCRIPTS_REF" \
    https://github.com/ProjectIgnis/CardScripts.git "$DATA/CardScripts"
fi

# EDOPro's puzzle collection. Each script builds a fixed field and demands a
# win in one turn, with the win condition enforced by the engine itself - so
# they are a harness stress test that needs no scoring function. EDOPro ships
# a copy, but reading whatever the install happens to hold today is not
# reproducible, hence our own pin.
if [ ! -d "$DATA/Puzzles/.git" ]; then
  log "cloning Puzzles (EDOPro puzzle collection)"
  git clone --depth 1 --branch "$PUZZLES_REF" \
    https://github.com/ProjectIgnis/Puzzles.git "$DATA/Puzzles"
fi

# The official rulebook. Fetched rather than vendored: this repo is public and
# the rulebook is Konami's, so it is pulled locally like the card data and
# never committed. Only our own summary of the rules ships, in llm/prompt.py.
RULEBOOK_URL="${RULEBOOK_URL:-https://img.yugioh-card.com/en/downloads/rulebook/SD_RuleBook_EN_10.pdf}"
mkdir -p "$DATA/rules"
if [ ! -f "$DATA/rules/rulebook.pdf" ]; then
  log "fetching the official rulebook"
  curl -sL -o "$DATA/rules/rulebook.pdf" "$RULEBOOK_URL" || \
    log "rulebook fetch failed - not fatal, only its summary is used"
fi
if [ -f "$DATA/rules/rulebook.pdf" ] && [ ! -f "$DATA/rules/rulebook.txt" ]; then
  python3 -c "
import sys
try:
    import pypdf
except ImportError:
    sys.exit('pypdf not installed - skipping text extraction')
r = pypdf.PdfReader('$DATA/rules/rulebook.pdf')
open('$DATA/rules/rulebook.txt','w').write(
    '\n'.join((p.extract_text() or '') for p in r.pages))
print(f'rulebook: {len(r.pages)} pages extracted')
" || true
fi

{
  echo "babelcdb  $(git -C "$DATA/BabelCDB" rev-parse HEAD)"
  echo "cardscripts $(git -C "$DATA/CardScripts" rev-parse HEAD)"
  echo "puzzles $(git -C "$DATA/Puzzles" rev-parse HEAD)"
  [ -f "$DATA/rules/rulebook.pdf" ] && \
    echo "rulebook $(shasum -a 256 "$DATA/rules/rulebook.pdf" | cut -c1-16)"
} > "$DATA/DATA_COMMITS"

log "card databases:"
ls -1 "$DATA/BabelCDB"/*.cdb 2>/dev/null | xargs -n1 basename | head -20
# Count with find, not `ls dir/*.lua`: ~13.5k absolute paths overflow ARG_MAX on macOS, ls fails with
# "Argument list too long", and with stderr discarded the count read "0 official" - which looks exactly
# like the no-card-effects failure (CLAUDE.md trap 1) when the scripts are all there.
count_lua() { find "$1" -maxdepth 1 -type f -name '*.lua' | wc -l | tr -d ' '; }
log "scripts: $(count_lua "$DATA/CardScripts/official") official, $(count_lua "$DATA/CardScripts") root"
cat "$DATA/DATA_COMMITS"
