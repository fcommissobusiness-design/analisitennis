#!/bin/bash
# Installa il LaunchAgent per la pipeline giornaliera 07:00
set -e

PLIST_SRC="$(dirname "$0")/com.analisitennis.daily.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.analisitennis.daily.plist"

cp "$PLIST_SRC" "$PLIST_DST"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "LaunchAgent installato in: $PLIST_DST"
echo "Esecuzione quotidiana programmata alle 07:00"
echo ""
echo "Per verificare: launchctl list | grep analisitennis"
echo "Per eseguire subito a mano: launchctl start com.analisitennis.daily"
echo "Per rimuovere: launchctl unload $PLIST_DST && rm $PLIST_DST"
