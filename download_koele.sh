#!/usr/bin/env bash
# Contact: Wim Otte (w.m.otte@umcutrecht.nl)
#
# Download alle publieke video's van Gerrit Koele als mp3.
# Herhaald draaien is veilig: reeds gedownloade video's worden overgeslagen (archive.txt).
set -euo pipefail

CHANNEL="https://www.youtube.com/@GerritKoeleMusicus/videos"
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/mp3"
LOG="$DIR/download.log"
ARCHIVE="$DIR/archive.txt"

mkdir -p "$OUT"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

log "=== Start download: $CHANNEL ==="

yt-dlp \
  --extract-audio --audio-format mp3 --audio-quality 0 \
  --download-archive "$ARCHIVE" \
  --ignore-errors --no-overwrites \
  --sleep-interval 2 --max-sleep-interval 6 \
  --output "$OUT/%(upload_date>%Y-%m-%d)s - %(title)s [%(id)s].%(ext)s" \
  --print-to-file "%(upload_date>%Y-%m-%d)s | %(id)s | %(title)s" "$DIR/videos.txt" \
  --no-progress \
  "$CHANNEL" 2>&1 | tee -a "$LOG"

log "=== Klaar. Totaal in archief: $(wc -l < "$ARCHIVE" | tr -d ' ') video's, mp3's: $(ls "$OUT"/*.mp3 2>/dev/null | wc -l | tr -d ' ') ==="
