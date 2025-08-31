USERNAME ?= konami98
SERVER_IMAGE ?= nodejs-backend
TAG ?= latest

.PHONY: build push run clean

build:
	docker build --no-cache -t $(USERNAME)/$(SERVER_IMAGE):$(TAG) .

push:
	docker push $(USERNAME)/$(SERVER_IMAGE):$(TAG)

run:
	docker run -p 3000:3000 $(USERNAME)/$(SERVER_IMAGE):$(TAG)

clean:
	docker rmi $(USERNAME)/$(SERVER_IMAGE):$(TAG) || true
