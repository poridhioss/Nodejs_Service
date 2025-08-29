USERNAME ?= konami98
IMAGE ?= nodejs-backend
TAG ?= latest

.PHONY: build push run clean

build:
	docker build --no-cache -t $(USERNAME)/$(IMAGE):$(TAG) .

push:
	docker push $(USERNAME)/$(IMAGE):$(TAG)

run:
	docker run -p 3000:3000 $(USERNAME)/$(IMAGE):$(TAG)

clean:
	docker rmi $(USERNAME)/$(IMAGE):$(TAG) || true
