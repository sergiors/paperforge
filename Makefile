SERVER_IMAGE ?= paperforge-server
CLIENT_IMAGE ?= paperforge-client
DOCKER_PLATFORM ?= linux/amd64


build-server:
	docker build --platform $(DOCKER_PLATFORM) -t $(SERVER_IMAGE) ./api

build-client:
	docker build --platform $(DOCKER_PLATFORM) -t $(CLIENT_IMAGE) ./app

build: build-server build-client

up:
	docker compose up -d

down:
	docker compose down
