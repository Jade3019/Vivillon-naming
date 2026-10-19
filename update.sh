#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python build_image_bank.py
git add -A
if git diff --cached --quiet; then
    echo "Nothing new to commit."
else
    git commit -m "Update Pokémon images and image bank"
fi
git push
