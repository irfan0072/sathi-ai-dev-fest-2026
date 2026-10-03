#!/usr/bin/env bash
# Role-split smoke test against a running API (default http://localhost:18000, override with SMOKE_API).
set -euo pipefail
API="${SMOKE_API:-http://localhost:18000}"
token() {
  curl -s -X POST "$API/api/v1/auth/demo-login" -H 'Content-Type: application/json' \
    -d "{\"principal\":\"$1\",\"pin\":\"$2\"}" \
    | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["access_token"])'
}
check() {  # token expected path
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $1" "$API$3")
  mark=$([ "$code" = "$2" ] && echo ok || echo FAIL)
  printf "  %-4s %-45s -> %s (want %s)\n" "$mark" "$3" "$code" "$2"
}
SUP=$(token sup_nadia 3456)
ADM=$(token demo_admin 7890)

echo "Supervisor (sup_nadia):"
for p in /api/v1/workdesk/summary "/api/v1/callcenter/queue?scope=pending" \
         "/api/v1/workdesk/cases?scope=pending" /api/v1/workdesk/reports; do check "$SUP" 200 "$p"; done
for p in /api/v1/admin/overview /api/v1/admin/users /api/v1/admin/staff /api/v1/settings \
         /api/v1/ops/overview /api/v1/callcenter/stats; do check "$SUP" 403 "$p"; done

echo "Super admin (demo_admin):"
for p in /api/v1/admin/overview "/api/v1/admin/users?limit=5" "/api/v1/admin/agents?limit=5" \
         /api/v1/admin/staff "/api/v1/admin/transactions?limit=5" /api/v1/callcenter/stats \
         "/api/v1/callcenter/queue?scope=all" "/api/v1/workdesk/cases?scope=all" /api/v1/settings; do
  check "$ADM" 200 "$p"
done
