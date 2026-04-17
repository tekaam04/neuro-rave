#include <vector>
#include <span>
#include <string>
#include <stdexcept>
#include <algorithm>
#include <cmath>
#include "fifo.h"

int secondsToSamples(float seconds, int sampleRate) {
    return int(seconds * sampleRate);
}

float samplesToSeconds(int samples, int sampleRate) {
    return samples / float(sampleRate);
}

// ─── Window generation ──────────────────────────────────────────────────────

void generateHannWindow(std::span<float> out) {
    int n = static_cast<int>(out.size());
    for (int i = 0; i < n; i++) {
        out[i] = 0.5f * (1.0f - std::cos(2.0f * M_PI * i / (n - 1)));
    }
}

void generateHammingWindow(std::span<float> out) {
    int n = static_cast<int>(out.size());
    for (int i = 0; i < n; i++) {
        out[i] = 0.54f - 0.46f * std::cos(2.0f * M_PI * i / (n - 1));
    }
}

void applyWindow(const ChannelArrayView& data, std::span<const float> coeffs) {
    int nFrames = data.numFrames();
    int nCoeffs = static_cast<int>(coeffs.size());
    int n = nFrames < nCoeffs ? nFrames : nCoeffs;

    for (int ch = 0; ch < data.numChannels(); ch++) {
        std::span<float> chan = data.channel(ch);
        for (int i = 0; i < n; i++) {
            chan[i] *= coeffs[i];
        }
    }
}

void applyWindow(const ChannelArrayView& data, const std::string& windowType) {
    if (windowType == "rectangular") return;

    int n = data.numFrames();
    std::vector<float> coeffs(n);

    if (windowType == "hann") {
        generateHannWindow(coeffs);
    } else if (windowType == "hamming") {
        generateHammingWindow(coeffs);
    } else {
        throw std::invalid_argument("Unknown window type: " + windowType);
    }

    applyWindow(data, coeffs);
}

// ─── CircularFIFO ───────────────────────────────────────────────────────────

CircularFIFO::CircularFIFO(int size, const std::string& channelName)
    : size(size), mask(size - 1), channelName(channelName), storage(size) {}

void CircularFIFO::addSample(float sample) {
    storage.at(writeIdx) = sample;
    writeIdx++;
}

void CircularFIFO::addChunk(std::span<const float> chunk) {
    int n = static_cast<int>(chunk.size());
    if (n > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(n) +
            ") is larger than buffer size (" + std::to_string(size) + ")");
    }
    storage.writeChunk(chunk, writeIdx);
    writeIdx += n;
}

void CircularFIFO::readNSamples(std::span<float> out) const {
    int n = static_cast<int>(out.size());
    if (n > size) n = size;
    int64_t startIdx = writeIdx - n;
    if (startIdx < 0) startIdx = 0;
    int actual = static_cast<int>(writeIdx - startIdx);
    storage.readChunk(out.first(actual), startIdx);
}

void CircularFIFO::readAll(std::span<float> out) const {
    if (static_cast<int>(out.size()) < size) {
        throw std::invalid_argument("readAll output buffer too small");
    }
    int filled = getFilledSize();
    int64_t startIdx = writeIdx - filled;
    storage.readChunk(out.first(filled), startIdx);
}

int CircularFIFO::getFilledSize() const {
    return writeIdx < size ? static_cast<int>(writeIdx) : size;
}

// ─── MirrorCircularFIFO ─────────────────────────────────────────────────────

MirrorCircularFIFO::MirrorCircularFIFO(int size, const std::string& channelName)
    : size(size), mask(size - 1), channelName(channelName), storage(size) {}

void MirrorCircularFIFO::addSample(float sample) {
    storage.write(writeIdx, sample);
    writeIdx++;
}

void MirrorCircularFIFO::addChunk(std::span<const float> chunk) {
    int n = static_cast<int>(chunk.size());
    if (n > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(n) +
            ") is larger than buffer size (" + std::to_string(size) + ")");
    }
    storage.writeChunk(chunk, writeIdx);
    writeIdx += n;
}

void MirrorCircularFIFO::readNSamples(std::span<float> out) const {
    auto src = peekNSamples(static_cast<int>(out.size()));
    std::copy(src.begin(), src.end(), out.begin());
}

void MirrorCircularFIFO::readAll(std::span<float> out) const {
    if (static_cast<int>(out.size()) < size) {
        throw std::invalid_argument("readAll output buffer too small");
    }
    auto src = peekNSamples(getFilledSize());
    std::copy(src.begin(), src.end(), out.begin());
}

std::span<const float> MirrorCircularFIFO::peekNSamples(int n) const {
    return storage.peek(writeIdx, n);
}

int MirrorCircularFIFO::getFilledSize() const {
    return writeIdx < size ? static_cast<int>(writeIdx) : size;
}

// ─── CircularFIFOTS (thread-safe SPSC) ──────────────────────────────────────

CircularFIFOTS::CircularFIFOTS(int size, const std::string& channelName)
    : size(size), mask(size - 1), channelName(channelName), storage(size) {}

void CircularFIFOTS::addSample(float sample) {
    int64_t w = writeIdx.load(std::memory_order_relaxed);
    storage.at(w) = sample;
    writeIdx.store(w + 1, std::memory_order_release);
}

void CircularFIFOTS::addChunk(std::span<const float> chunk) {
    int n = static_cast<int>(chunk.size());
    if (n > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(n) +
            ") is larger than buffer size (" + std::to_string(size) + ")");
    }
    int64_t w = writeIdx.load(std::memory_order_relaxed);
    storage.writeChunk(chunk, w);
    writeIdx.store(w + n, std::memory_order_release);
}

void CircularFIFOTS::readNSamples(std::span<float> out) const {
    int64_t w = writeIdx.load(std::memory_order_acquire);
    int n = static_cast<int>(out.size());
    if (n > size) n = size;
    int64_t startIdx = w - n;
    if (startIdx < 0) startIdx = 0;
    int actual = static_cast<int>(w - startIdx);
    storage.readChunk(out.first(actual), startIdx);
}

void CircularFIFOTS::readAll(std::span<float> out) const {
    if (static_cast<int>(out.size()) < size) {
        throw std::invalid_argument("readAll output buffer too small");
    }
    int64_t w = writeIdx.load(std::memory_order_acquire);
    int filled = getFilledSize();
    int64_t startIdx = w - filled;
    storage.readChunk(out.first(filled), startIdx);
}

int CircularFIFOTS::getFilledSize() const {
    int64_t w = writeIdx.load(std::memory_order_acquire);
    return w < size ? static_cast<int>(w) : size;
}

// ─── MirrorCircularFIFOTS (thread-safe SPSC) ────────────────────────────────

MirrorCircularFIFOTS::MirrorCircularFIFOTS(int size, const std::string& channelName)
    : size(size), mask(size - 1), channelName(channelName), storage(size) {}

void MirrorCircularFIFOTS::addSample(float sample) {
    int64_t w = writeIdx.load(std::memory_order_relaxed);
    storage.write(w, sample);
    writeIdx.store(w + 1, std::memory_order_release);
}

void MirrorCircularFIFOTS::addChunk(std::span<const float> chunk) {
    int n = static_cast<int>(chunk.size());
    if (n > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(n) +
            ") is larger than buffer size (" + std::to_string(size) + ")");
    }
    int64_t w = writeIdx.load(std::memory_order_relaxed);
    storage.writeChunk(chunk, w);
    writeIdx.store(w + n, std::memory_order_release);
}

void MirrorCircularFIFOTS::readNSamples(std::span<float> out) const {
    auto src = peekNSamples(static_cast<int>(out.size()));
    std::copy(src.begin(), src.end(), out.begin());
}

void MirrorCircularFIFOTS::readAll(std::span<float> out) const {
    if (static_cast<int>(out.size()) < size) {
        throw std::invalid_argument("readAll output buffer too small");
    }
    auto src = peekNSamples(getFilledSize());
    std::copy(src.begin(), src.end(), out.begin());
}

std::span<const float> MirrorCircularFIFOTS::peekNSamples(int n) const {
    int64_t w = writeIdx.load(std::memory_order_acquire);
    return storage.peek(w, n);
}

int MirrorCircularFIFOTS::getFilledSize() const {
    int64_t w = writeIdx.load(std::memory_order_acquire);
    return w < size ? static_cast<int>(w) : size;
}
