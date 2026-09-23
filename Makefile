.PHONY: install dev test run docker

install:
	python -m pip install -e .

dev:
	python -m pip install -e '.[dev,rich]'

test:
	pytest -q

run:
	contextmesh serve --host 127.0.0.1 --port 8765

docker:
	docker compose up --build
