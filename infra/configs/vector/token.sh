apk add --no-cache curl jq
sleep 30
auth=$(echo -n $TOKEN_USER:$TOKEN_PASSWORD | base64)
output=$(curl -s -X 'GET' 'http://openobserve:5080/api/default/passcode' -H 'accept: application/json' -H 'Authorization: Basic '$auth'' | jq -r '.data.passcode')
awk -v r="$output" '/auth.password =/ { sub(/=.*/, "= \"" r "\""); } { print; }' /etc/vector/vector.toml > temp && mv -f temp /etc/vector/vector.toml
