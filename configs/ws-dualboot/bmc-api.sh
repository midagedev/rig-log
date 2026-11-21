#!/bin/bash
# bmc-api.sh METHOD PATH [JSON-FILE] — one call on the ASMB9 (AMI MegaRAC SP-X) web API with a fresh session.
# The web API, not Redfish: on firmware 1.17 an IPMI-made user logs into /api/session but Redfish answers 401.
# Env: BMC (https://<address>), BMC_USER, BMC_PASS_FILE (a 600 file holding the password).
set -u
: "${BMC:?https://<bmc address>}" "${BMC_USER:?user}" "${BMC_PASS_FILE:?password file}"
J=$(mktemp); trap 'rm -f "$J"' EXIT
R=$(curl -sk -m 20 -c "$J" -X POST "$BMC/api/session" --data-urlencode "username=$BMC_USER" --data-urlencode "password=$(cat "$BMC_PASS_FILE")")
T=$(echo "$R" | python3 -c "import json,sys;print(json.load(sys.stdin)['CSRFToken'])") || { echo "login refused: $R" >&2; exit 1; }
A=(-sk -m 120 -b "$J" -H "X-CSRFTOKEN: $T" -H "Content-Type: application/json")
if [ -n "${3:-}" ]; then curl "${A[@]}" -X "$1" "$BMC$2" -d @"$3" -w "\nHTTP %{http_code}\n"
else curl "${A[@]}" -X "$1" "$BMC$2" -w "\nHTTP %{http_code}\n"; fi
curl "${A[@]}" -X DELETE "$BMC/api/session" -o /dev/null
