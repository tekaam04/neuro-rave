FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates \
    libwebsockets-dev \
    && rm -rf /var/lib/apt/lists/*

# Build liblsl from source — pin to v1.16.2 (works with CMake 3.25 in bookworm)
RUN git clone --depth 1 --branch v1.16.2 https://github.com/sccn/liblsl.git /tmp/liblsl \
    && cmake -S /tmp/liblsl -B /tmp/liblsl/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DLSL_BUILD_STATIC=OFF \
    && cmake --build /tmp/liblsl/build -j \
    && cmake --install /tmp/liblsl/build \
    && ldconfig \
    && rm -rf /tmp/liblsl \
    && mkdir -p /usr/local/include/lsl \
    && ln -sf /usr/local/include/lsl_c.h   /usr/local/include/lsl/lsl_c.h \
    && ln -sf /usr/local/include/lsl_cpp.h /usr/local/include/lsl/lsl_cpp.h

WORKDIR /app
COPY . /app/native

RUN cmake -S /app/native -B /app/native/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /app/native/build -j

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libwebsockets17 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/lib/liblsl* /usr/local/lib/
COPY --from=build /app/native/build/neuro_lsl_bridge   /usr/local/bin/
COPY --from=build /app/native/build/neuro_ws_server    /usr/local/bin/
COPY --from=build /app/native/build/neuro_lsl_bridge_c /usr/local/bin/
COPY --from=build /app/native/build/neuro_ws_server_c  /usr/local/bin/

RUN ldconfig

WORKDIR /app
CMD ["neuro_ws_server"]
