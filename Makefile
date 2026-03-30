# Docker image name and tag
BEETDECK_IMAGE ?= semsemyonoff/beetdeck
BEETDECK_TAG ?= latest
# Target platforms for multi-arch build
BEETDECK_PLATFORMS ?= linux/amd64,linux/arm64

export BEETDECK_IMAGE BEETDECK_TAG BEETDECK_PLATFORMS

.PHONY: build

# Build multi-arch image and push to registry
build:
	./build.sh
