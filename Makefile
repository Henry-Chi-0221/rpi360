.PHONY: setup core wasm web check test demos connect preview preview-status preview-stop camera ipad tailscale
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
preview-status:
	node tools/preview.mjs status
preview-stop:
	node tools/preview.mjs stop
camera:
	bash tools/run-camera.sh "$(CALIBRATION)"
ipad:
	python3 tools/install-ipad.py $(if $(CALIBRATION),--calibration "$(CALIBRATION)")
tailscale:
	python3 tools/install-ipad.py --configure-tailscale
