#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

VENVPATH="./venv"

venv() {
    local _bin="${VENVPATH}/bin"
    if [[ -d "${_bin}" ]]; then
        echo "source ${VENVPATH}/bin/activate"
    else
        echo "source ${VENVPATH}/Scripts/activate"
    fi
}

make_venv() {
    python -m venv "${VENVPATH}"
}

reset_venv() {
    rm -rf "${VENVPATH}"
    make_venv
}

wrapped_python() {
    local _bin="${VENVPATH}/bin"
    if [[ -d "${_bin}" ]]; then
        "${VENVPATH}"/bin/python "$@"
    else
        "${VENVPATH}"/Scripts/python "$@"
    fi
}

wrapped_pip() {
    wrapped_python -m pip "$@"
}

python_deps() {
    wrapped_pip install --upgrade pip setuptools wheel

    local pip_extras="${1:-}"
    if [[ -z "${pip_extras}" ]]; then
        wrapped_pip install -e .
    else
        wrapped_pip install -e ".[${pip_extras}]"
    fi
}

install() {
    if [[ -d "${VENVPATH}" ]]; then
        python_deps "$@"
    else
        make_venv && python_deps "$@"
    fi
}

build() {
    python -m build
}

publish() {
    lint && tests && clean && build
    python -m twine upload dist/*
}

mkdocs() {
    rm -rf docs/*
    mkdir -p docs
    wrapped_python -m pdoc -d google -o docs src/gstreasy
}

docs() {
    wrapped_python -m pdoc -n -d google src/gstreasy
}

clean() {
    rm -rf dist/
    rm -rf .eggs/
    rm -rf build/
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +
    find . -name '__pycache__' -exec rm -fr {} +
    find . -name '.mypy_cache' -exec rm -fr {} +
    find . -name '.pytest_cache' -exec rm -fr {} +
    find . -name '*.egg-info' -exec rm -fr {} +
}

lint() {
    clean
    wrapped_python -m flake8 src/ &&
    wrapped_python -m mypy src/
}

tests() {
    # wrapped_python -m tox -p 2
    wrapped_python -m pytest -rA tests/
}

default() {
    wrapped_python user_code.py
}

TIMEFORMAT="Task completed in %3lR"
time "${@:-default}"
