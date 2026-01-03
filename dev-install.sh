#!/bin/bash

# Install a development copy of BatteryWatch alongside the production version

DEV_DIR="/tmp/batterywatch-dev"
DEV_ID="com.github.itayavra.batterywatch.dev"
SOURCE_DIR="$(dirname "$(readlink -f "$0")")"

echo "Setting up BatteryWatch (Dev)..."

# Clean up any existing dev directory
rm -rf "$DEV_DIR"

# Copy source files
cp -r "$SOURCE_DIR" "$DEV_DIR"

# Remove build artifacts and git files from dev copy
rm -rf "$DEV_DIR/dist" "$DEV_DIR/.git"

# Change the plugin ID and name to make it a separate widget
sed -i 's/com.github.itayavra.batterywatch/'"$DEV_ID"'/g' "$DEV_DIR/metadata.json"
sed -i 's/"BatteryWatch"/"BatteryWatch (Dev)"/g' "$DEV_DIR/metadata.json"

# Rename translation files to match the new plugin ID
for locale_dir in "$DEV_DIR"/contents/locale/*/LC_MESSAGES/; do
    if [ -d "$locale_dir" ]; then
        old_mo="$locale_dir/plasma_applet_com.github.itayavra.batterywatch.mo"
        new_mo="$locale_dir/plasma_applet_${DEV_ID}.mo"
        if [ -f "$old_mo" ]; then
            mv "$old_mo" "$new_mo"
        fi
    fi
done

# Check if dev version is already installed
if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -q "$DEV_ID"; then
    echo "Upgrading existing dev installation..."
    kpackagetool6 --type Plasma/Applet --upgrade "$DEV_DIR"
else
    echo "Installing dev version..."
    kpackagetool6 --type Plasma/Applet --install "$DEV_DIR"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ BatteryWatch (Dev) installed successfully!"
    echo ""
    echo "Add the widget:"
    echo "  1. Right-click on your panel"
    echo "  2. Select 'Add Widgets...'"
    echo "  3. Search for 'BatteryWatch (Dev)'"
    echo ""
    echo "To update after changes: ./dev-install.sh"
    echo "To uninstall: ./dev-uninstall.sh"
else
    echo "✗ Installation failed"
    exit 1
fi

