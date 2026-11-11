#!/usr/bin/env bash
# Локальная проверка перед коммитом: не пустить в историю секреты.
# Установка:  bash scripts/install-hooks.sh   (ставит симлинк в .git/hooks)
# Обход:      git commit --no-verify  — поэтому одного хука мало, нужен CI и review.
set -euo pipefail

fail=0

blocked_names='(^|/)(config\.txt|\.env|proxies[^/]*\.txt|.*\.bak.*|.*\.session|.*\.db|.*\.jsonl|pending_code\.json|report_data\.json)$'
staged=$(git diff --cached --name-only --diff-filter=ACMR)

blocked=$(printf '%s\n' "$staged" | grep -Ei "$blocked_names" | grep -v 'proxies.example.txt' || true)
if [ -n "$blocked" ]; then
    echo "✗ запрещённые файлы в коммите:" >&2
    printf '   %s\n' $blocked >&2
    fail=1
fi

# Содержимое: ключи, токены, приватные ключи, строки подключения с паролем
patterns='(api[_-]?key|secret|passw|token)[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9_\-]{12,}|socks5://[^:[:space:]]+:[^@[:space:]]+@|-----BEGIN [A-Z ]*PRIVATE KEY-----|[0-9]{10}:[A-Za-z0-9_-]{30,}'
for file in $staged; do
    [ -f "$file" ] || continue
    # файлы проверки содержат свои же шаблоны — себя не сканируют
    case "$file" in
        .github/workflows/secret-scan.yml|scripts/pre-commit-secrets.sh) continue ;;
    esac
    if grep -Eiq "$patterns" "$file"; then
        echo "✗ похоже на секрет в файле: $file" >&2
        fail=1
    fi
done

if [ "$fail" -ne 0 ]; then
    echo "" >&2
    echo "Коммит остановлен. Уберите секрет в .env или в локальный файл без коммита." >&2
    exit 1
fi
echo "✓ проверка секретов пройдена"
