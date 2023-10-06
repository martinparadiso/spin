## This makefile is a wrapper around the other build tools
## in the project. It is provided as a convenience to ease
## the execution of common build operations.
## 

PYTHON_VERSION != python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'

help:							## Print this small help message
	@sed -ne '/@sed/!s/## //p' $(MAKEFILE_LIST)

docs:							## Build the docs
	sphinx-build -W -b html docs/source docs/build/html/

quick-test:						## Run a quick test suite, ~0.5s in modern machines
	py.test -m 'not slow'

test:							## Run the entire unit test-suite
	coverage run --include="spin/*" --data-file=coverage.pytest.$(PYTHON_VERSION) --include="spin/**/*" -m pytest -rs

test-full:
	coverage run --include="spin/*" --data-file=coverage.pytest.$(PYTHON_VERSION) --include="spin/**/*" -m pytest -rs --super-slow --requires-backend

mypy:							## Run MyPy/static type-checking
	@mkdir -p .mypy_cache/
	mypy --install-types --non-interactive --cache-dir=.mypy_cache/ spin/ tests/

test-format:						## Validate the formatting
	black --check spin/ tests/

## 
test-all: mypy test test-format ## 

.PHONY: docs tests
