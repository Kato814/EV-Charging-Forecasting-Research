.PHONY: validate test queue

validate:
	python scripts/validate_library.py

queue:
	python scripts/build_reading_queue.py

test:
	python -m pytest code/tests
