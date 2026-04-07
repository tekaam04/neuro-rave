#pragma once

#include <vector>
#include <string>
#include <span>
#include <stdexcept>
#include <cstring>
#include "channel_array.h"

bool isPowerOfTwo(int n);

int secondsToSamples(float seconds, int sampleRate);

float samplesToSeconds(int samples, int sampleRate);

void applyWindow(const ChannelArrayView& data, const std::string& windowType);

// Single-channel FIFO base class
class FIFO {
public:
    int size;
    std::string channelName;
    bool isFull;

    FIFO(int size, const std::string& channelName = "");
    virtual ~FIFO() = default;

    virtual void addSample(float sample) = 0;
    virtual void addChunk(std::span<const float> chunk) = 0;

    // Fills out.size() samples (the most-recent ones).
    virtual void readNSamples(std::span<float> out) = 0;
    // Fills the entire filled portion. out.size() must equal getFilledSize().
    virtual void readAll(std::span<float> out) = 0;

    int getFilledSize() const;

protected:
    std::vector<float> data;
    int writeIdx;

    static void validateRange(int begin, int end, int maxSize, const std::string& name);
    void writeDataByRange(std::span<const float> source,
                          int sourceBegin = 0, int sourceEnd = -1, int dataBegin = 0);
    void readDataByRange(std::span<float> result,
                         int dataBegin = 0, int dataEnd = -1, int resultBegin = 0) const;
};

class CircularFIFO : public FIFO {
public:
    CircularFIFO(int size, const std::string& channelName = "");

    void addSample(float sample) override;
    void addChunk(std::span<const float> chunk) override;
    void readNSamples(std::span<float> out) override;
    void readAll(std::span<float> out) override;
};

// Circular FIFO with a duplicated mirror of the data stored immediately after
// the primary region. `size` is the logical capacity (same semantics as
// CircularFIFO); the underlying storage is 2*size so the n most-recent
// samples are always contiguous in memory.
class MirrorCircularFIFO : public FIFO {
public:
    MirrorCircularFIFO(int size, const std::string& channelName = "");

    void addSample(float sample) override;
    void addChunk(std::span<const float> chunk) override;
    void readNSamples(std::span<float> out) override;
    void readAll(std::span<float> out) override;

    // Zero-copy view into the internal mirror buffer for the n most-recent samples.
    // Valid until the next write to this FIFO.
    std::span<const float> peekNSamples(int n) const;
};

// Multi-signal buffer that manages per-channel FIFOs.
template<typename T>
class MultiSignalFIFO {
public:
    int nChannels;
    int size;
    float timestamp;

    MultiSignalFIFO(int size, int nChannels,
                    const std::vector<std::string>& channelNames = {})
        : nChannels(nChannels), size(size), timestamp(0.f), cachedNames(nChannels) {
        channels.reserve(nChannels);
        for (int i = 0; i < nChannels; i++) {
            std::string name = (i < static_cast<int>(channelNames.size())) ? channelNames[i] : "";
            channels.emplace_back(size, name);
            cachedNames[i] = channels[i].channelName;
        }
    }

    MultiSignalFIFO(float seconds, int sampleRate, int nChannels,
                    const std::vector<std::string>& channelNames = {})
        : MultiSignalFIFO(secondsToSamples(seconds, sampleRate), nChannels, channelNames) {}

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

    // Reads n frames from each channel into the matching channel of `out`.
    // Zero-allocation hot path.
    void readNSamples(const ChannelArrayView& out, int n) {
        if (out.numChannels() != nChannels) {
            throw std::invalid_argument(
                "Output channel count (" + std::to_string(out.numChannels()) +
                ") does not match number of channels (" + std::to_string(nChannels) + ")");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].readNSamples(out.channel(ch).first(n));
        }
    }

    // Reads all filled samples per channel into `out`. Each channel must
    // be sized to the filled length of the corresponding FIFO.
    void readAll(const ChannelArrayView& out) {
        if (out.numChannels() != nChannels) {
            throw std::invalid_argument("Output channel count mismatch");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].readAll(out.channel(ch));
        }
    }

    // Hot path for the audio callback. Writes the n most-recent frames per
    // channel into a miniaudio-style interleaved buffer of length frames*nChannels.
    // Zero allocations.
    void readNSamplesInterleaved(float* interleavedOut, int frames) {
        for (int ch = 0; ch < nChannels; ch++) {
            T& fifo = channels[ch];
            int filled = fifo.getFilledSize();
            int n = frames > filled ? filled : frames;
            int pad = frames - n;

            for (int i = 0; i < pad; i++) {
                interleavedOut[i * nChannels + ch] = 0.f;
            }

            if constexpr (std::is_same_v<T, MirrorCircularFIFO>) {
                // Zero-copy peek into contiguous mirror storage.
                std::span<const float> src = fifo.peekNSamples(n);
                for (int i = 0; i < n; i++) {
                    interleavedOut[(pad + i) * nChannels + ch] = src[i];
                }
            } else {
                // CircularFIFO: read into a fixed stack scratch then deinterleave.
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
