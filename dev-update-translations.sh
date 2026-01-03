#!/bin/sh
# Convenience script to merge and build translations in one go
# Usage: ./dev-update-translations.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "  BatteryWatch Translation Updater"
echo "========================================"
echo ""

# Step 1: Merge translations
echo "Step 1/2: Extracting and merging translation strings..."
cd "$SCRIPT_DIR/translate"
sh merge.sh
if [ $? -ne 0 ]; then
    echo "Error: merge.sh failed"
    exit 1
fi

echo ""
echo "Step 2/2: Building translation files..."
sh build.sh
if [ $? -ne 0 ]; then
    echo "Error: build.sh failed"
    exit 1
fi

echo ""
echo "========================================"
echo "✓ Translations updated successfully!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Run: ./dev-install.sh"
echo "  2. Run: ./dev-restart-plasma.sh"
echo "  3. Test with: LANGUAGE=pl plasmashell --replace"
echo "     (Available: 'hu' Hungarian, 'nl' Dutch, 'pl' Polish)"
echo ""

