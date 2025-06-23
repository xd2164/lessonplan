.PHONY: build run-interactive run-writer

# Build the Docker image
build:
	docker build -t narcissus .

# Run interactive shell
run-interactive:
	docker run -it --env-file .env -v "${PWD}/src:/app/src" narcissus

# Run writer workflow
run-writer:
	docker run --env-file .env -v "${PWD}/src:/app/src" narcissus python -m narcissus.workflows.writer 