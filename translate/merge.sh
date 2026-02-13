#!/bin/sh
# Version: 23

# https://techbase.kde.org/Development/Tutorials/Localization/i18n_Build_Systems
# https://techbase.kde.org/Development/Tutorials/Localization/i18n_Build_Systems/Outside_KDE_repositories
# https://invent.kde.org/sysadmin/l10n-scripty/-/blob/master/extract-messages.sh

DIR=`cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd`
plasmoidName=`jq -r '.KPlugin.Id' "$DIR/../metadata.json"`
widgetName="${plasmoidName##*.}" # Strip namespace
website=`jq -r '.KPlugin.Website' "$DIR/../metadata.json"`
bugAddress="$website"
packageRoot=".." # Root of translatable sources
projectName="plasma_applet_${plasmoidName}" # project name

### Colors
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
# https://stackoverflow.com/questions/911168/how-can-i-detect-if-my-shell-script-is-running-through-a-pipe
TC_Red='\033[31m'; TC_Orange='\033[33m';
TC_LightGray='\033[90m'; TC_LightRed='\033[91m'; TC_LightGreen='\033[92m'; TC_Yellow='\033[93m'; TC_LightBlue='\033[94m';
TC_Reset='\033[0m'; TC_Bold='\033[1m';
if [ ! -t 1 ]; then
	TC_Red=''; TC_Orange='';
	TC_LightGray=''; TC_LightRed=''; TC_LightGreen=''; TC_Yellow=''; TC_LightBlue='';
	TC_Bold=''; TC_Reset='';
fi
function echoTC() {
	text="$1"
	textColor="$2"
	echo -e "${textColor}${text}${TC_Reset}"
}
function echoGray { echoTC "$1" "$TC_LightGray"; }
function echoRed { echoTC "$1" "$TC_Red"; }
function echoGreen { echoTC "$1" "$TC_LightGreen"; }

#---
if [ -z "$plasmoidName" ]; then
	echoRed "[translate/merge] Error: Couldn't read plasmoidName."
	exit
fi

if [ -z "$(which xgettext)" ]; then
	echoRed "[translate/merge] Error: xgettext command not found. Need to install gettext"
	echoRed "[translate/merge] Running ${TC_Bold}'sudo apt install gettext'"
	sudo apt install gettext
	echoRed "[translate/merge] gettext installation should be finished. Going back to merging translations."
fi

#---
echoGray "[translate/merge] Extracting messages"
potArgs="--from-code=UTF-8 --width=200 --add-location=file"

# Note: xgettext v0.20.1 (Kubuntu 20.04) and below will attempt to translate Icon,
# so we need to specify Name, GenericName, Comment, and Keywords.
# https://github.com/Zren/plasma-applet-lib/issues/1
# https://savannah.gnu.org/support/?108887
find "${packageRoot}" -name '*.desktop' | sort > "${DIR}/infiles.list"
xgettext \
	${potArgs} \
	--files-from="${DIR}/infiles.list" \
	--language=Desktop \
	-k -kName -kGenericName -kComment -kKeywords \
	-D "${packageRoot}" \
	-D "${DIR}" \
	-o "template.pot.new" \
	|| \
	{ echoRed "[translate/merge] error while calling xgettext. aborting."; exit 1; }

sed -i 's/"Content-Type: text\/plain; charset=CHARSET\\n"/"Content-Type: text\/plain; charset=UTF-8\\n"/' "template.pot.new"

# See Ki18n's extract-messages.sh for a full example:
# https://invent.kde.org/sysadmin/l10n-scripty/-/blob/master/extract-messages.sh#L25
# The -kN_ and -kaliasLocale keywords are mentioned in the Outside_KDE_repositories wiki.
# We don't need -kN_ since we don't use intltool-extract but might as well keep it.
# I have no idea what -kaliasLocale is used for. Googling aliasLocale found only listed kde1 code.
# We don't need to parse -ki18nd since that'll extract messages from other domains.
find "${packageRoot}" -name '*.cpp' -o -name '*.h' -o -name '*.c' -o -name '*.qml' -o -name '*.js' | sort > "${DIR}/infiles.list"
xgettext \
	${potArgs} \
	--files-from="${DIR}/infiles.list" \
	-C -kde \
	-ci18n \
	-ki18n:1 -ki18nc:1c,2 -ki18np:1,2 -ki18ncp:1c,2,3 \
	-kki18n:1 -kki18nc:1c,2 -kki18np:1,2 -kki18ncp:1c,2,3 \
	-kxi18n:1 -kxi18nc:1c,2 -kxi18np:1,2 -kxi18ncp:1c,2,3 \
	-kkxi18n:1 -kkxi18nc:1c,2 -kkxi18np:1,2 -kkxi18ncp:1c,2,3 \
	-kI18N_NOOP:1 -kI18NC_NOOP:1c,2 \
	-kI18N_NOOP2:1c,2 -kI18N_NOOP2_NOSTRIP:1c,2 \
	-ktr2i18n:1 -ktr2xi18n:1 \
	-kN_:1 \
	-kaliasLocale \
	--package-name="${widgetName}" \
	--msgid-bugs-address="${bugAddress}" \
	-D "${packageRoot}" \
	-D "${DIR}" \
	--join-existing \
	-o "template.pot.new" \
	|| \
	{ echoRed "[translate/merge] error while calling xgettext. aborting."; exit 1; }

sed -i 's/# SOME DESCRIPTIVE TITLE./'"# Translation of ${widgetName} in LANGUAGE"'/' "template.pot.new"
sed -i 's/# Copyright (C) YEAR THE PACKAGE'"'"'S COPYRIGHT HOLDER/'"# Copyright (C) $(date +%Y)"'/' "template.pot.new"

if [ -f "template.pot" ]; then
	newPotDate=`grep "POT-Creation-Date:" template.pot.new | sed 's/.\{3\}$//'`
	oldPotDate=`grep "POT-Creation-Date:" template.pot | sed 's/.\{3\}$//'`
	sed -i 's/'"${newPotDate}"'/'"${oldPotDate}"'/' "template.pot.new"
	changes=`diff "template.pot" "template.pot.new"`
	if [ ! -z "$changes" ]; then
		# There's been changes
		sed -i 's/'"${oldPotDate}"'/'"${newPotDate}"'/' "template.pot.new"
		mv "template.pot.new" "template.pot"

		addedKeys=`echo "$changes" | grep "> msgid" | cut -c 9- | sort`
		removedKeys=`echo "$changes" | grep "< msgid" | cut -c 9- | sort`
		echo ""
		echoGreen "Added Keys:"
		echoGreen "$addedKeys"
		echo ""
		echoRed "Removed Keys:"
		echoRed "$removedKeys"
		echo ""

	else
		# No changes
		rm "template.pot.new"
	fi
else
	# template.pot didn't already exist
	mv "template.pot.new" "template.pot"
fi

potMessageCount=`expr $(grep -Pzo 'msgstr ""\n(\n|$)' "template.pot" | grep -c 'msgstr ""')`
statusHeader="| Locale | Language | Status | % Done |"
statusDivider="|--------|----------|--------|--------|"
echo "$statusHeader" > "./Status.md"
echo "$statusDivider" >> "./Status.md"
entryFormat="| %-6s | %-12s | %-12s | %6s |"

rm "${DIR}/infiles.list"
echoGray "[translate/merge] Done extracting messages"

#---
echoGray "[translate/merge] Merging messages"
catalogs=`find . -name '*.po' | sort`
for cat in $catalogs; do
	echoGray "[translate/merge] Updating ${cat}"
	catLocale=`basename ${cat%.*}`

	widthArg=""
	catUsesGenerator=`grep "X-Generator:" "$cat"`
	if [ -z "$catUsesGenerator" ]; then
		widthArg="--width=400"
	fi

	compendiumArg=""
	if [ ! -z "$COMPENDIUM_DIR" ]; then
		langCode=`basename "${cat%.*}"`
		compendiumPath=`realpath "$COMPENDIUM_DIR/compendium-${langCode}.po"`
		if [ -f "$compendiumPath" ]; then
			echo "compendiumPath=$compendiumPath"
			compendiumArg="--compendium=$compendiumPath"
		fi
	fi

	cp "$cat" "$cat.new"
	sed -i 's/"Content-Type: text\/plain; charset=CHARSET\\n"/"Content-Type: text\/plain; charset=UTF-8\\n"/' "$cat.new"

	msgmerge \
		${widthArg} \
		--add-location=file \
		--no-fuzzy-matching \
		${compendiumArg} \
		-o "$cat.new" \
		"$cat.new" "${DIR}/template.pot"

	sed -i 's/# SOME DESCRIPTIVE TITLE./'"# Translation of ${widgetName} in ${catLocale}"'/' "$cat.new"
	sed -i 's/# Translation of '"${widgetName}"' in LANGUAGE/'"# Translation of ${widgetName} in ${catLocale}"'/' "$cat.new"
	sed -i 's/# Copyright (C) YEAR THE PACKAGE'"'"'S COPYRIGHT HOLDER/'"# Copyright (C) $(date +%Y)"'/' "$cat.new"

	poEmptyMessageCount=`expr $(grep -Pzo 'msgstr ""\n(\n|$)' "$cat.new" | grep -c 'msgstr ""')`
	poMessagesDoneCount=`expr $potMessageCount - $poEmptyMessageCount`
	poCompletion=`perl -e "printf(\"%d\", $poMessagesDoneCount * 100 / $potMessageCount)"`
	
	# Get Language Name from PO header or fallback to locale
	langName=$(grep "# Translation of .* in " "$cat.new" | head -n 1 | sed 's/.* in //')
	if [ -z "$langName" ] || [ "$langName" = "LANGUAGE" ] || [ "$langName" = "$catLocale" ]; then
		# Fallback to a few known ones or just use the locale capitalized
		case "$catLocale" in
			he) langName="Hebrew" ;;
			hu) langName="Hungarian" ;;
			nl) langName="Dutch" ;;
			pl) langName="Polish" ;;
			*) langName=$(echo "$catLocale" | awk '{print toupper(substr($0,1,1))tolower(substr($0,2))}') ;;
		esac
	fi

	statusIcon="🟡 In Progress"
	if [ "$poCompletion" -eq 100 ]; then
		statusIcon="✅ Complete"
	elif [ "$poCompletion" -eq 0 ]; then
		statusIcon="🔴 Not Started"
	fi

	poLine=`perl -e "printf(\"$entryFormat\", \"$catLocale\", \"$langName\", \"$statusIcon\", \"${poCompletion}%\")"`
	echo "$poLine" >> "./Status.md"

	# mv "$cat" "$cat.old"
	mv "$cat.new" "$cat"
done
echoGray "[translate/merge] Done merging messages"

#---
echoGray "[translate/merge] Updating .desktop file"

# Generate LINGUAS for msgfmt
if [ -f "$DIR/LINGUAS" ]; then
	rm "$DIR/LINGUAS"
fi
touch "$DIR/LINGUAS"
for cat in $catalogs; do
	catLocale=`basename ${cat%.*}`
	echo "${catLocale}" >> "$DIR/LINGUAS"
done

cp -f "$DIR/../metadata.desktop" "$DIR/template.desktop"
sed -i '/^Name\[/ d; /^GenericName\[/ d; /^Comment\[/ d; /^Keywords\[/ d' "$DIR/template.desktop"

msgfmt \
	--desktop \
	--template="$DIR/template.desktop" \
	-d "$DIR/" \
	-o "$DIR/new.desktop"

# Delete empty msgid messages that used the po header
if [ ! -z "$(grep '^Name=$' "$DIR/new.desktop")" ]; then
	echo "[translate/merge] Name in metadata.desktop is empty!"
	sed -i '/^Name\[/ d' "$DIR/new.desktop"
fi
if [ ! -z "$(grep '^GenericName=$' "$DIR/new.desktop")" ]; then
	echo "[translate/merge] GenericName in metadata.desktop is empty!"
	sed -i '/^GenericName\[/ d' "$DIR/new.desktop"
fi
if [ ! -z "$(grep '^Comment=$' "$DIR/new.desktop")" ]; then
	echo "[translate/merge] Comment in metadata.desktop is empty!"
	sed -i '/^Comment\[/ d' "$DIR/new.desktop"
fi
if [ ! -z "$(grep '^Keywords=$' "$DIR/new.desktop")" ]; then
	echo "[translate/merge] Keywords in metadata.desktop is empty!"
	sed -i '/^Keywords\[/ d' "$DIR/new.desktop"
fi

# Place translations at the bottom of the desktop file.
translatedLines=`cat "$DIR/new.desktop" | grep "]="`
if [ ! -z "${translatedLines}" ]; then
	sed -i '/^Name\[/ d; /^GenericName\[/ d; /^Comment\[/ d; /^Keywords\[/ d' "$DIR/new.desktop"
	if [ "$(tail -c 2 "$DIR/new.desktop" | wc -l)" != "2" ]; then
		# Does not end with 2 empty lines, so add an empty line.
		echo "" >> "$DIR/new.desktop"
	fi
	echo "${translatedLines}" >> "$DIR/new.desktop"
fi

# Cleanup
mv "$DIR/new.desktop" "$DIR/../metadata.desktop"
rm "$DIR/template.desktop"
rm "$DIR/LINGUAS"

#---
# Populate root README.md with translation status
echoGray "[translate/merge] Updating root README.md"
statusFile="./Status.md"
readmeFile="../README.md"

if [ -f "$readmeFile" ] && [ -f "$statusFile" ]; then
    # Create a temporary file
    tmpReadme="${readmeFile}.tmp"
    
    # Use awk to replace content between markers
    awk -v status="$(cat $statusFile)" '
        BEGIN { p=1 }
        /<!-- TRANSLATIONS_START -->/ { print; print status; p=0 }
        /<!-- TRANSLATIONS_END -->/ { p=1 }
        p { if (!/<!-- TRANSLATIONS_START -->/) print }
    ' "$readmeFile" > "$tmpReadme"
    
    mv "$tmpReadme" "$readmeFile"
    rm "$statusFile"
else
    echoRed "[translate/merge] Warning: Could not find root README.md or Status.md"
fi

echoGreen "[translate/merge] Done merge script"