set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments

container-image := env_var_or_default("CONTAINER_IMAGE", "localhost/web-app-launcher-test:latest")
container-data-volume := env_var_or_default("CONTAINER_DATA_VOLUME", "web-app-launcher-data")

default:
    @just --list

alias setup := sync

# Sync runtime and development dependencies
[group('local')]
sync:
    uv sync --all-extras

# Run the application with debug logging
[group('local')]
run: sync
    uv run --no-sync python -m web_app_launcher.main --log-level debug gui

# Run all tests headlessly
[group('local')]
test *args="-q": sync
    QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests "$@"

# Run unit tests headlessly
[group('local')]
test-unit *args="-q": sync
    QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/unit "$@"

# Run integration tests headlessly
[group('local')]
test-integration *args="-q": sync
    QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/integration "$@"

# Run existing hooks on all tracked and untracked files, or selected paths
[group('local')]
pre-commit *files:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "$#" -gt 0 ]; then
        uvx pre-commit run --files "$@"
    else
        uvx pre-commit run --all-files
        git ls-files --others --exclude-standard -z | xargs -0 -r uvx pre-commit run --files
    fi

# Run pre-commit and the complete test suite sequentially
[group('local')]
test-all:
    just pre-commit
    just test

# Build the test image (optional flags: --no-cache --pull=always)
[group('container')]
container-build-image *args:
    podman build "$@" -f tests/Containerfile -t "{{ container-image }}" tests

# Run all tests in the container
[group('container')]
container-test *args="-q":
    just _container-run test "$@"

# Run unit tests in the container
[group('container')]
container-test-unit *args="-q":
    just _container-run test-unit "$@"

# Run integration tests in the container
[group('container')]
container-test-integration *args="-q":
    just _container-run test-integration "$@"

# Run existing hooks in the container, optionally on selected paths
[group('container')]
container-pre-commit *files:
    just _container-run pre-commit "$@"

# Run pre-commit and the complete test suite in the container sequentially
[group('container')]
container-test-all:
    just container-pre-commit
    just container-test

# Reuse local recipes without touching the host virtual environment or tool caches.
[private]
_container-run recipe *args:
    #!/usr/bin/env bash
    set -euo pipefail
    podman run --rm --pull=never \
        -v "{{ justfile_directory() }}:/workspace:z" \
        -v "{{ container-data-volume }}:/container-data:z" \
        -w /workspace \
        -e UV_PROJECT_ENVIRONMENT=/container-data/.venv \
        -e UV_CACHE_DIR=/container-data/cache/uv \
        -e PRE_COMMIT_HOME=/container-data/cache/pre-commit \
        -e PYTEST_ADDOPTS='-o cache_dir=/container-data/cache/pytest' \
        "{{ container-image }}" just "$@"
