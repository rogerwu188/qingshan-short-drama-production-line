.PHONY: install install-media init doctor test test-full

install:
	python3 -m pip install -e .

install-media:
	python3 -m pip install -e '.[media,asr,cloud]'

init:
	qingshan init --workspace .qingshan-workspace

doctor:
	python3 -m qingshan_engine.cli doctor --profile core

test:
	python3 tools/run_portable_ci.py

# Historical tests require private episode media/manifests and are intentionally
# separate from the clean-clone CI contract.
test-full:
	python3 -m unittest discover -s tools/tests -t .
