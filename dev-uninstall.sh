#!/bin/bash

# Uninstall the development copy of BatteryWatch

DEV_ID="com.github.itayavra.batterywatch.dev"
DEV_DIR="/tmp/batterywatch-dev"

echo "Uninstalling BatteryWatch (Dev)..."

kpackagetool6 --type Plasma/Applet --remove "$DEV_ID"

if [ $? -eq 0 ]; then
    # Clean up temp directory
    rm -rf "$DEV_DIR"
    echo "✓ BatteryWatch (Dev) uninstalled successfully!"
else
    echo "✗ Uninstall failed (widget may not be installed)"
    exit 1
fi

