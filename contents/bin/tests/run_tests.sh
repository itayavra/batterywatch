#!/bin/bash

# Runs the HID helper and GVariant parser test suites, and summarizes.
# Usage: ./run_tests.sh [suite.py ...]   (defaults to all suites, including the JS one)

cd "$(dirname "$(readlink -f "$0")")"

if [ "$#" -gt 0 ]; then
    suites=("$@")
else
    suites=(test_read_hid_devices.py test_read_solaar_devices.py)
fi

failed=0
for suite in "${suites[@]}"; do
    if output=$(python3 "$suite" 2>&1); then
        echo "PASS  $suite  |  $(echo "$output" | tail -1)"
    else
        echo "FAIL  $suite"
        echo "$output" | tail -30
        failed=1
    fi
done

# The parser and provider suites run under node and live beside the UI code.
js_suites=(../../ui/GVariant.test.cjs ../../ui/providers.test.cjs ../../ui/DeviceUtils.test.cjs)
if [ "$#" -eq 0 ]; then
    if ! command -v node >/dev/null 2>&1; then
        for suite in "${js_suites[@]}"; do
            echo "SKIP  $suite  |  node not found"
        done
    else
        for suite in "${js_suites[@]}"; do
            if output=$(node --test --test-reporter=tap "$suite" 2>&1); then
                echo "PASS  $suite  |  $(echo "$output" | grep -E '^# (pass|tests)' | tr '\n' ' ')"
            else
                echo "FAIL  $suite"
                echo "$output" | tail -30
                failed=1
            fi
        done
    fi
fi

echo
if [ "$failed" -eq 0 ]; then
    echo "All test suites passed."
else
    echo "One or more test suites failed."
    exit 1
fi
