#!/bin/bash
# Pre-run script to set system volume to 100%

set -e  # Exit on error

echo "Setting system volume to 100%..."

# Try PulseAudio first (common on modern Ubuntu systems)
if command -v pactl &> /dev/null; then
    echo "Using PulseAudio to set volume..."
    pactl set-sink-volume @DEFAULT_SINK@ 100% || {
        # Try with sink index 0 if @DEFAULT_SINK@ doesn't work
        pactl set-sink-volume 0 100% || echo "Warning: Failed to set PulseAudio volume"
    }
fi

# Try ALSA as fallback (common on Raspberry Pi)
if command -v amixer &> /dev/null; then
    echo "Using ALSA to set volume..."
    # Try different ALSA cards (0 is usually the default)
    amixer -c 0 set Master 100% unmute 2>/dev/null || \
    amixer set Master 100% unmute 2>/dev/null || \
    amixer -D pulse set Master 100% unmute 2>/dev/null || \
    echo "Warning: Failed to set ALSA volume"
fi

echo "Volume setup complete."

