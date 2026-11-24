#!/bin/sh
set -eu

landing_dir=landing-source/finsolve_ai_landing

npm --prefix "$landing_dir" run build
REACT_APP_PUBLIC_DEMO_ENABLED=true npm --prefix frontend run build

# Stage the two static builds under their production URL prefixes.
rm -rf dist
mkdir -p dist/app
cp -R "$landing_dir/dist/." dist/
cp -R frontend/build/. dist/app/
