# Shield Remote - MicroPython BLE HID for Nvidia Shield
PROJECT_BASE := $(shell pwd)
BOARD ?= ATOM_ECHO
BOARD_DIR := $(PROJECT_BASE)/board/$(BOARD)

# Docker configuration
IMAGE := shield-remote-build
ifneq ("$(wildcard /.dockerenv)","")
  RUN_IN_DOCKER := 0
else
  RUN_IN_DOCKER := 1
  DOCKER := docker run --rm -v "$(PROJECT_BASE):/project" -w /project $(IMAGE)
  DOCKER_USB := docker run --rm -v "$(PROJECT_BASE):/project" -w /project --privileged -v /dev:/dev $(IMAGE)
endif

.PHONY: help
help:
	@echo "Shield Remote Build System"
	@echo ""
	@echo "Targets:"
	@echo "  docker-build  - Build the Docker image (run first)"
	@echo "  build         - Build MicroPython firmware"
	@echo "  flash         - Flash firmware to device (PORT=/dev/ttyUSB0)"
	@echo "  clean         - Remove build artifacts"
	@echo "  shell         - Open shell in build container"

.PHONY: docker-build
docker-build:
	@echo "Building Docker image..."
	docker build -t $(IMAGE) .

.PHONY: build
build:
ifeq ($(RUN_IN_DOCKER), 1)
	@echo "Building in Docker container..."
	$(DOCKER) make build
else
	@echo "Building MicroPython firmware for $(BOARD)..."
	cd /opt/micropython/ports/esp32 && \
		make BOARD_DIR=$(BOARD_DIR) -j$$(nproc)
	@echo ""
	@echo "Build complete!"
	@echo "Firmware: /opt/micropython/ports/esp32/build-$(BOARD)/firmware.bin"
endif

.PHONY: flash
flash:
ifeq ($(RUN_IN_DOCKER), 1)
	@echo "Flashing from Docker container..."
	$(DOCKER_USB) make flash PORT=$(PORT)
else
	@echo "Flashing to $(PORT)..."
	cd /opt/micropython/ports/esp32 && \
		make BOARD_DIR=$(BOARD_DIR) PORT=$(PORT) deploy
endif

.PHONY: clean
clean:
ifeq ($(RUN_IN_DOCKER), 1)
	$(DOCKER) make clean
else
	rm -rf /opt/micropython/ports/esp32/build-$(BOARD)
endif

.PHONY: shell
shell:
	docker run -it --rm -v "$(PROJECT_BASE):/project" -w /project $(IMAGE) bash

.PHONY: copy-firmware
copy-firmware:
ifeq ($(RUN_IN_DOCKER), 1)
	$(DOCKER) make copy-firmware
else
	@mkdir -p $(PROJECT_BASE)/build
	cp /opt/micropython/ports/esp32/build-$(BOARD)/firmware.bin $(PROJECT_BASE)/build/
	cp /opt/micropython/ports/esp32/build-$(BOARD)/bootloader/bootloader.bin $(PROJECT_BASE)/build/
	cp /opt/micropython/ports/esp32/build-$(BOARD)/partition_table/partition-table.bin $(PROJECT_BASE)/build/
	@echo "Firmware copied to $(PROJECT_BASE)/build/"
endif
