## Translation Workflow

### Quick Start

To update all translations (extract strings + compile):
```bash
cd ..
./dev-update-translations.sh
```

### Individual Steps

If you need to run steps separately:

1. **Extract and merge strings** (after code changes):
   ```bash
   ./merge.sh
   ```

2. **Build compiled translations**:
   ```bash
   ./build.sh
   ```

### Adding a New Language

1. Create a new `.po` file:
   ```bash
   msginit --locale=LANG --input=template.pot --output=LANG.po
   # Example: msginit --locale=de --input=template.pot --output=de.po
   ```

2. Edit the `.po` file and translate the `msgstr` fields

3. Run the build script:
   ```bash
   ./dev-update-translations.sh
   ```

4. Add translations to `metadata.desktop`:
   ```ini
   Name[LANG]=TranslatedName
   ```

5. Optionally add to `metadata.json`:
   ```json
   "Name[LANG]": "TranslatedName",
   "Description[LANG]": "Translated description",
   "Category[LANG]": "Translated category"
   ```

### Testing Translations

After building:
```bash
# Install dev version
cd ..
./dev-install.sh

# Test with specific language (this replaces plasmashell)
LANGUAGE=he plasmashell --replace  # Hebrew
LANGUAGE=pl plasmashell --replace  # Polish
LANGUAGE=hu plasmashell --replace  # Hungarian
LANGUAGE=nl plasmashell --replace  # Dutch

# When done testing (Ctrl+C), restart normally with:
./dev-restart-plasma.sh
# or
kstart plasmashell
```

**Important:** After testing with `LANGUAGE=xx plasmashell --replace`:
- Press `Ctrl+C` to stop the test session
- Run `./dev-restart-plasma.sh` or `kstart plasmashell` to go back to your system language
- Plasmashell won't auto-restart after `Ctrl+C`, so you need to start it manually

### File Structure

- `*.po` - Translation source files (human-editable)
- `template.pot` - Master template (generated from source code)
- `merge.sh` - Extracts i18n strings from QML files
- `build.sh` - Compiles .po → .mo files
- `update-translations.sh` - Convenience script (merge + build)
- `../contents/locale/*/LC_MESSAGES/*.mo` - Compiled translations (generated)

### Current Languages

| Locale | Language | Status |
|--------|----------|--------|
| hu | Hungarian | ✅ Complete |
| he | Hebrew | ✅ Complete |
| nl | Dutch | ✅ Complete |
| pl | Polish | ✅ Complete |

### Notes

- The scripts now use `jq` to read from `metadata.json` (KDE Plasma 6)
- Old scripts used `kreadconfig5` which is no longer needed
- Always run `./dev-install.sh` after updating translations to test them

