#! /bin/bash

export MAHIMAHI_CERT_DIR=$(pwd)/../mahimahi/src/frontend/certs
export CHROME_HAR_CAPTURER_BIN=$(pwd)/third_party/node/capture_har.js
export PWMETRICS_BIN=$(pwd)/third_party/node/node_modules/.bin/pwmetrics
export LOG_LEVEL=debug

