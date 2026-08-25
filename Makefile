SERVER_IMAGE ?= paperforge
DOCKER_PLATFORM ?= linux/amd64

build:
	docker build --platform $(DOCKER_PLATFORM) -t $(SERVER_IMAGE) .

up:
	docker compose up -d

down:
	docker compose down
