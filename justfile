default:
    @just --list

# Set up development environment
setup:
    #!/usr/bin/env bash
    uv sync --all-extras

# Clean build artifacts and cache files
clean:
    #!/usr/bin/env bash
    uv clean

# Run the application
run:
    #!/usr/bin/env bash
    set -e
    uv run python -m web_app_launcher.main --log-level debug gui

# Build Python package
build: clean
    uv build

# Sync dependencies
sync:
    uv sync

test-image := "localhost/web-app-launcher-test"

# Build the podman image used for running tests
test-build:
    podman build -f tests/Containerfile -t {{test-image}} .

# Run pytest in podman (paths: tests, tests/unit, tests/integration)
_test-run paths args:
    #!/usr/bin/env bash
    set -euo pipefail
    podman run --rm \
        -e QT_QPA_PLATFORM=offscreen \
        -v "${PWD}:/app:Z" \
        -w /app \
        {{test-image}} \
        bash -lc 'uv sync --all-extras && uv run pytest {{paths}} {{args}}'

# Run all tests inside podman
test *args="-q": test-build
    just _test-run tests {{args}}

# Run unit tests only
test-unit *args="-q": test-build
    just _test-run tests/unit {{args}}

# Run integration tests only
test-integration *args="-q": test-build
    just _test-run tests/integration {{args}}
