#pragma once

#include <vector>
#include <string>
#include <span>
#include <stdexcept>
#include <cstring>
#include <cstdint>
#include <atomic>
#include "ring_storage.h"
#include "channel_array.h"

int secondsToSamples(float seconds, int sampleRate);

float samplesToSeconds(int samples, int sampleRate);

void applyWindow(const ChannelArrayView& data, std::span<const float> coeffs);
void applyWindow(const ChannelArrayView& data, const std::string& windowType);

void generateHannWindow(std::span<float> out);
void generateHammingWindow(std::span<float> out);

// ─── Non-thread-safe FIFOs (intra-thread use) ───────────────────────────────

class CircularFIFO {
public:
    int size;
    int mask;
    std::string channelName;

    CircularFIFO(int size, const std::string& channelName = "");

    void addSample(float sample);
    void addChunk(std::span<const float> chunk);
    void readNSamples(std::span<float> out) const;
    void readAll(std::span<float> out) const;

    int getFilledSize() const;
    int64_t getTotalWritten() const { return writeIdx; }

protected:
    RingStorage storage;
    int64_t writeIdx = 0;
};

class MirrorCircularFIFO {
public:
    int size;
    int mask;
    std::string channelName;

    MirrorCircularFIFO(int size, const std::string& channelName = "");

    void addSample(float sample);
    void addChunk(std::span<const float> chunk);
    void readNSamples(std::span<float> out) const;
    void readAll(std::span<float> out) const;

    std::span<const float> peekNSamples(int n) const;

    int getFilledSize() const;
    int64_t getTotalWritten() const { return writeIdx; }

protected:
    MirrorRingStorage storage;
    int64_t writeIdx = 0;
};

// ─── Thread-safe SPSC FIFOs (cross-thread use) ─────────────────────────────
//
// Safe for exactly ONE writer thread and ONE reader thread with no mutex.
// writeIdx uses memory_order_release on store and memory_order_acquire on load.

class CircularFIFOTS {
public:
    int size;
    int mask;
    std::string channelName;

    CircularFIFOTS(int size, const std::string& channelName = "");

    void addSample(float sample);
    void addChunk(std::span<const float> chunk);
    void readNSamples(std::span<float> out) const;
    void readAll(std::span<float> out) const;

    int getFilledSize() const;
    int64_t getTotalWritten() const { return writeIdx.load(std::memory_order_acquire); }

protected:
    RingStorage storage;
    std::atomic<int64_t> writeIdx{0};
};

class MirrorCircularFIFOTS {
public:
    int size;
    int mask;
    std::string channelName;

    MirrorCircularFIFOTS(int size, const std::string& channelName = "");

    void addSample(float sample);
    void addChunk(std::span<const float> chunk);
    void readNSamples(std::span<float> out) const;
    void readAll(std::span<float> out) const;

    std::span<const float> peekNSamples(int n) const;

    int getFilledSize() const;
    int64_t getTotalWritten() const { return writeIdx.load(std::memory_order_acquire); }

protected:
    MirrorRingStorage storage;
    std::atomic<int64_t> writeIdx{0};
};

// ─── MultiSignal: per-channel container ─────────────────────────────────────

template<typename T>
class MultiSignal {
public:
    int nChannels;
    int size;
    float timestamp;

    MultiSignal(int size, int nChannels,
                const std::vector<std::string>& channelNames = {})
        : nChannels(nChannels), size(size), timestamp(0.f), cachedNames(nChannels) {
        channels.reserve(nChannels);
        for (int i = 0; i < nChannels; i++) {
            std::string name = (i < static_cast<int>(channelNames.size())) ? channelNames[i] : "";
            channels.emplace_back(size, name);
            cachedNames[i] = channels[i].channelName;
        }
    }

    MultiSignal(float seconds, int sampleRate, int nChannels,
                const std::vector<std::string>& channelNames = {})
        : MultiSignal(secondsToSamples(seconds, sampleRate), nChannels, channelNames) {}

    void addSample(std::span<const float> sample) {
        if (static_cast<int>(sample.size()) != nChannels) {
            throw std::invalid_argument(
                "Sample size (" + std::to_string(sample.size()) +
                ") does not match number of channels (" + std::to_string(nChannels) + ")");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].addSample(sample[ch]);
        }
    }

    void addChunk(const ChannelArrayConstView& chunk) {
        if (chunk.numChannels() != nChannels) {
            throw std::invalid_argument(
                "Number of channels in chunk (" + std::to_string(chunk.numChannels()) +
                ") does not match number of channels (" + std::to_string(nChannels) + ")");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].addChunk(chunk.channel(ch));
        }
    }

    void readNSamples(const ChannelArrayView& out, int n) const {
        if (out.numChannels() != nChannels) {
            throw std::invalid_argument(
                "Output channel count (" + std::to_string(out.numChannels()) +
                ") does not match number of channels (" + std::to_string(nChannels) + ")");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].readNSamples(out.channel(ch).first(n));
        }
    }

    void readAll(const ChannelArrayView& out) const {
        if (out.numChannels() != nChannels) {
            throw std::invalid_argument("Output channel count mismatch");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].readAll(out.channel(ch));
        }
    }

    void readNSamplesInterleaved(float* interleavedOut, int frames) const {
        int n = frames > size ? size : frames;
        int pad = frames - n;
        for (int ch = 0; ch < nChannels; ch++) {
            const T& fifo = channels[ch];

            for (int i = 0; i < pad; i++) {
                interleavedOut[i * nChannels + ch] = 0.f;
            }

            if constexpr (requires { fifo.peekNSamples(n); }) {
                std::span<const float> src = fifo.peekNSamples(n);
                for (int i = 0; i < n; i++) {
                    interleavedOut[(pad + i) * nChannels + ch] = src[i];
                }
            } else {
                constexpr int kStackBufferMax = 8192;
                float scratch[kStackBufferMax];
                int chunk = n;
                if (chunk > kStackBufferMax) chunk = kStackBufferMax;
                fifo.readNSamples(std::span<float>(scratch, chunk));
                for (int i = 0; i < chunk; i++) {
                    interleavedOut[(pad + i) * nChannels + ch] = scratch[i];
                }
            }
        }
    }

    std::pair<int, int> getShape() const {
        return {nChannels, channels[0].getFilledSize()};
    }

    T& getChannel(int ch) { return channels[ch]; }
    const T& getChannel(int ch) const { return channels[ch]; }

    T& getChannel(const std::string& name) {
        for (auto& ch : channels) {
            if (ch.channelName == name) return ch;
        }
        throw std::invalid_argument("Channel not found: " + name);
    }

    const std::vector<std::string>& getChannelNames() const { return cachedNames; }

private:
    std::vector<T> channels;
    std::vector<std::string> cachedNames;
};

// ─── SampleCounter ──────────────────────────────────────────────────────────

class SampleCounter {
public:
    int count;
    int resetThresh;

    SampleCounter(int count = 0, int resetThresh = -1)
        : count(count), resetThresh(resetThresh) {
        if (resetThresh == 0 || resetThresh < -1) {
            throw std::invalid_argument(
                "resetThresh must be a positive number or -1 (indicates no reset threshold) "
                + std::to_string(resetThresh));
        }
    }

    void resetCount() { count = 0; }

    bool incrementByN(int n = 1) {
        int temp = count + n;
        if (temp >= resetThresh && resetThresh != -1) {
            count = temp % resetThresh;
            return true;
        }
        count = temp;
        return false;
    }
};

// ─── BlockReader ────────────────────────────────────────────────────────────

template<typename T>
class BlockReader {
public:
    BlockReader() = default;

    BlockReader(MultiSignal<T>* fifo, int blockSize, int hopSize)
        : fifo(fifo), blockSize(blockSize), hopSize(hopSize),
          counter(0, hopSize),
          lastSeenTotal(fifo->getChannel(0).getTotalWritten()) {}

    bool poll() {
        int64_t total = fifo->getChannel(0).getTotalWritten();
        int newSamples = static_cast<int>(total - lastSeenTotal);
        lastSeenTotal = total;
        return counter.incrementByN(newSamples);
    }

    void readBlock(const ChannelArrayView& out,
                   std::span<const float> windowCoeffs) {
        fifo->readNSamples(out, blockSize);
        applyWindow(out, windowCoeffs);
    }

    int getBlockSize() const { return blockSize; }
    int getHopSize()   const { return hopSize; }

private:
    MultiSignal<T>* fifo = nullptr;
    int blockSize = 0;
    int hopSize = 0;
    SampleCounter counter;
    int64_t lastSeenTotal = 0;
};
