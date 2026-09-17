.PHONY: setup core wasm web check test demos connect preview camera
setup:
	uv sync --all-packages --extra dev
	pnpm install
core:
	cargo build --release -p rpi360-ffi -p rpi360-render
wasm:
	bash tools/release/build-wasm.sh
web: wasm
	pnpm dev
test: core wasm
	uv run --all-packages --extra dev pytest
	cargo test --workspace
	pnpm test
check: test
	uv run --extra dev ruff check .
	cargo fmt --all -- --check
	pnpm build
demos: core
	uv run --all-packages python tools/demos/build.py --source-root "$(SOURCE_ROOT)"
connect:
	bash tools/connect-camera.sh "$(CAMERA)"
preview:
	node tools/preview.mjs "$(CAMERA)"
camera:
	bash tools/run-camera.sh "$(CALIBRATION)"
