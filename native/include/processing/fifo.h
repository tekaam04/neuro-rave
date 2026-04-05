#pragma once

#include <vector>
#include <string>
#include <stdexcept>

bool isPowerOfTwo(int n);

int secondsToSamples(float seconds, int sampleRate);

float samplesToSeconds(int samples, int sampleRate);

void applyWindow(std::vector<std::vector<float>>& data, std::string windowType);

// Single-channel FIFO base class
class FIFO {
public:
    int size;
    std::string channelName;
    bool isFull;

    FIFO(int size, const std::string& channelName = "");
    virtual ~FIFO() = default;

    virtual void addSample(float sample) = 0;
    virtual void addChunk(std::vector<float>& chunk) = 0;
    virtual std::vector<float> getData() = 0;
    virtual std::vector<float> getNSamples(int n) = 0;

    int getFilledSize();

protected:
    std::vector<float> data;
    int writeIdx;

    void validateRange(int begin, int end, int maxSize, const std::string& name);
    void writeDataByRange(std::vector<float>& source,
                          int sourceBegin = 0, int sourceEnd = -1, int dataBegin = 0);
    void readDataByRange(std::vector<float>& result,
                         int dataBegin = 0, int dataEnd = -1, int resultBegin = 0);
};

class CircularFIFO : public FIFO {
public:
    CircularFIFO(int size, const std::string& channelName = "");

    void addSample(float sample) override;
    void addChunk(std::vector<float>& chunk) override;
    std::vector<float> getData() override;
    std::vector<float> getNSamples(int n) override;
};

class MirrorCircularFIFO : public FIFO {
public:
    MirrorCircularFIFO(int size, const std::string& channelName = "");

    void addSample(float sample) override;
    void addChunk(std::vector<float>& chunk) override;
    std::vector<float> getData() override;
    std::vector<float> getNSamples(int n) override;
};

// Multi-signal buffer that manages per-channel FIFOs
template<typename T>
class MultiSignalFIFO {
public:
    int nChannels;
    int size;
    float timestamp;

    MultiSignalFIFO(int size, int nChannels,
                    const std::vector<std::string>& channelNames = {})
        : nChannels(nChannels), size(size), timestamp(0.f) {
        channels.reserve(nChannels);
        for (int i = 0; i < nChannels; i++) {
            std::string name = (i < channelNames.size()) ? channelNames[i] : "";
            channels.emplace_back(size, name);
        }
    }

    MultiSignalFIFO(float seconds, int sampleRate, int nChannels,
                    const std::vector<std::string>& channelNames = {})
        : MultiSignalFIFO(secondsToSamples(seconds, sampleRate), nChannels, channelNames) {}

    void addSample(std::vector<float>& sample) {
        if (sample.size() != nChannels) {
            throw std::invalid_argument(
                "Sample size (" + std::to_string(sample.size()) +
                ") does not match number of channels (" + std::to_string(nChannels) + ")");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].addSample(sample[ch]);
        }
    }

    void addChunk(std::vector<std::vector<float>>& chunk) {
        if (chunk.size() != nChannels) {
            throw std::invalid_argument(
                "Number of rows in chunk (" + std::to_string(chunk.size()) +
                ") does not match number of channels (" + std::to_string(nChannels) + ")");
        }
        for (int ch = 0; ch < nChannels; ch++) {
            channels[ch].addChunk(chunk[ch]);
        }
    }

    std::vector<std::vector<float>> getData() {
        std::vector<std::vector<float>> result;
        result.reserve(nChannels);
        for (int ch = 0; ch < nChannels; ch++) {
            result.push_back(channels[ch].getData());
        }
        return result;
    }

    std::vector<std::vector<float>> getNSamples(int n) {
        std::vector<std::vector<float>> result;
        result.reserve(nChannels);
        for (int ch = 0; ch < nChannels; ch++) {
            result.push_back(channels[ch].getNSamples(n));
        }
        return result;
    }

    std::pair<int, int> getShape() {
        return {nChannels, channels[0].getFilledSize()};
    }

    T& getChannel(int ch) { return channels[ch]; }

    T& getChannel(const std::string& name) {
        for (auto& ch : channels) {
            if (ch.channelName == name) return ch;
        }
        throw std::invalid_argument("Channel not found: " + name);
    }

    std::vector<std::string> getChannelNames() {
        std::vector<std::string> result(nChannels);
        for (int i = 0; i < nChannels; i++) {
            result[i] = channels[i].channelName;
        }
        return result;
    }

private:
    std::vector<T> channels;
};
