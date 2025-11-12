#!/bin/bash
# Pre-run script to set system volume and switch output to HDMI

set -e

echo "=== Pre-run audio setup ==="

# Try PulseAudio / PipeWire first
if command -v pactl &>/dev/null; then
    echo "Using PulseAudio / PipeWire..."

    # Find HDMI sink
    HDMI_SINK=$(pactl list short sinks | grep -i hdmi | awk '{print $2}' | head -n1)

    if [ -n "$HDMI_SINK" ]; then
        echo "Switching default sink to HDMI: $HDMI_SINK"
        pactl set-default-sink "$HDMI_SINK"

        # Move all current playback streams to HDMI
        for INPUT in $(pactl list short sink-inputs | awk '{print $1}'); do
            pactl move-sink-input "$INPUT" "$HDMI_SINK"
        done
    else
        echo "Warning: No HDMI sink found. Keeping default output."
    fi

    echo "Setting volume to 100%..."
    pactl set-sink-volume @DEFAULT_SINK@ 100% || pactl set-sink-volume 0 100%
fi

# ALSA fallback (for older systems)
if command -v amixer &>/dev/null; then
    echo "Using ALSA fallback..."
    amixer -c 0 set Master 100% unmute 2>/dev/null || \
    amixer set Master 100% unmute 2>/dev/null || \
    echo "Warning: Failed to set ALSA volume"
fi

echo "=== Audio setup complete ==="
