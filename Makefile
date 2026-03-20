IMAGE_NAME = paperforge


build:
	docker build --platform linux/amd64 -t $(IMAGE_NAME) .

up:
	docker-compose up -d

down:
	docker-compose down
