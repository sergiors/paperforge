IMAGE_NAME = paperforge
AWS_ACCOUNT := $(shell aws sts get-caller-identity --query "Account" --output text)
AWS_REGION := $(shell aws configure get region)

export:
	uv export --no-emit-project --no-editable --frozen --no-dev -o requirements.txt

build: export
	docker build --platform linux/amd64 -t $(IMAGE_NAME) .

login:
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com

tag: build
	docker tag $(IMAGE_NAME):latest $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com/$(IMAGE_NAME):latest

push: tag login
	docker push $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com/$(IMAGE_NAME):latest

up:
	docker-compose up -d

down:
	docker-compose down