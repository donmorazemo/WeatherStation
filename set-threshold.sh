#!/bin/bash
# Usage: ./set-threshold.sh 25.5
# Updates the temperature threshold in .env — takes effect within 60 seconds, no restart needed.

if [ -z "$1" ]; then
    current=$(grep "^TEMP_THRESHOLD_C=" "$(dirname "$0")/.env" | cut -d= -f2)
    echo "Current threshold: ${current}°C"
    echo "Usage: $0 <temperature_in_celsius>"
    exit 0
fi

value="$1"
if ! echo "$value" | grep -qE '^-?[0-9]+(\.[0-9]+)?$'; then
    echo "Error: '$value' is not a valid number"
    exit 1
fi

env_file="$(dirname "$0")/.env"
if grep -q "^TEMP_THRESHOLD_C=" "$env_file"; then
    sed -i "s/^TEMP_THRESHOLD_C=.*/TEMP_THRESHOLD_C=$value/" "$env_file"
else
    echo "TEMP_THRESHOLD_C=$value" >> "$env_file"
fi

echo "Threshold updated to ${value}°C"
sudo systemctl restart collector
echo "Collector restarted — new threshold active immediately"
