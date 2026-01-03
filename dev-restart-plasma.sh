#!/bin/bash

# Restart Plasma Shell to reload widgets

echo "Restarting Plasma Shell..."

# Kill plasmashell (try graceful first, then force if needed)
kquitapp6 plasmashell 2>/dev/null || killall plasmashell 2>/dev/null

# Wait a moment for it to fully stop
sleep 1

# Start plasmashell in the background
kstart plasmashell &

echo "✓ Plasma Shell restarted"

