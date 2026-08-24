run:
	python src/main.py

test:
	python -m unittest discover -s tests -p "test_*.py" -v

lint:
	ruff check src
