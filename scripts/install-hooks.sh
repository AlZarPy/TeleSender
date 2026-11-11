#!/usr/bin/env bash
# Ставит локальный хук, который блокирует коммит с секретами.
# Запуск: bash scripts/install-hooks.sh
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
hook="$repo_root/.git/hooks/pre-commit"

cp "$repo_root/scripts/pre-commit-secrets.sh" "$hook"
chmod +x "$hook"
echo "хук установлен: $hook"
echo "проверить вручную: bash scripts/pre-commit-secrets.sh"
echo "обход (не рекомендуется): git commit --no-verify"
