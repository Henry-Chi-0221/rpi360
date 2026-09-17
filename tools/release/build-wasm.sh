#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.cargo/bin:$PATH"
cargo build --release --target wasm32-unknown-unknown -p rpi360-render --lib
wasm-bindgen target/wasm32-unknown-unknown/release/rpi360_render.wasm --target web --out-dir packages/web-sdk/wasm
