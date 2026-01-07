# MicroPython ESP32 build environment
FROM espressif/idf:v5.2.2

# Install additional tools
RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone MicroPython
RUN git clone --depth 1 --branch v1.24.1 https://github.com/micropython/micropython.git /opt/micropython \
    && cd /opt/micropython \
    && git submodule update --init --depth 1 lib/micropython-lib \
    && git submodule update --init --depth 1 lib/berkeley-db-1.xx \
    && git submodule update --init --depth 1 lib/tinyusb

# Build mpy-cross
RUN cd /opt/micropython && make -C mpy-cross -j$(nproc)

# Set working directory
WORKDIR /project

# Default command
CMD ["bash"]
