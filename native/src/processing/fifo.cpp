#include <vector>
#include <span>
#include <string>
#include <stdexcept>
#include <algorithm>
#include "fifo.h"

bool isPowerOfTwo(int n) {
    return (n != 0) && ((n & (n - 1)) == 0);
}

int secondsToSamples(float seconds, int sampleRate) {
    return int(seconds * sampleRate);
}

float samplesToSeconds(int samples, int sampleRate) {
     return samples / float(sampleRate);
}

void applyWindow(const ChannelArrayView& data, const std::string& windowType);

// FIFO base class
FIFO::FIFO(int size, const std::string& channelName)
    : size(size), channelName(channelName), isFull(false), data(size, 0.f), writeIdx(0) {}

void FIFO::validateRange(int begin, int end, int maxSize, const std::string& name) {
    if (begin < 0 || end > maxSize || begin > end) {
        throw std::out_of_range(
            name + " range [" + std::to_string(begin) + ":" + std::to_string(end) +
            "] out of bounds for size " + std::to_string(maxSize));
    }
}

void FIFO::writeDataByRange(std::span<const float> source,
                             int sourceBegin, int sourceEnd,
                             int dataBegin) {
    if (sourceEnd == -1) sourceEnd = static_cast<int>(source.size());
    int copyLen = sourceEnd - sourceBegin;

    validateRange(sourceBegin, sourceEnd, static_cast<int>(source.size()), "source");
    validateRange(dataBegin, dataBegin + copyLen, static_cast<int>(data.size()), "data");

    std::copy(source.begin() + sourceBegin, source.begin() + sourceEnd,
              data.begin() + dataBegin);
}

void FIFO::readDataByRange(std::span<float> result,
                            int dataBegin, int dataEnd,
                            int resultBegin) const {
    if (dataEnd == -1) dataEnd = static_cast<int>(data.size());
    int copyLen = dataEnd - dataBegin;

    validateRange(dataBegin, dataEnd, static_cast<int>(data.size()), "data");
    validateRange(resultBegin, resultBegin + copyLen, static_cast<int>(result.size()), "result");

    std::copy(data.begin() + dataBegin, data.begin() + dataEnd,
              result.begin() + resultBegin);
}

int FIFO::getFilledSize() const {
    return isFull ? size : writeIdx;
}

// CircularFIFO
CircularFIFO::CircularFIFO(int size, const std::string& channelName)
    : FIFO(size, channelName) {}

void CircularFIFO::addSample(float sample) {
    data[writeIdx] = sample;
    writeIdx = (writeIdx + 1) % size;
    if (writeIdx == 0) isFull = true;
}

void CircularFIFO::addChunk(std::span<const float> chunk) {
    int nSamples = static_cast<int>(chunk.size());

    if (nSamples > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(nSamples) +
            ") is larger than buffer size (" + std::to_string(size) +
            ". This could lead to data loss. Split chunk into multiple chunks)");
    }

    if (nSamples == size) {
        writeDataByRange(chunk, 0, nSamples, 0);
        writeIdx = 0;
        isFull = true;
        return;
    }

    int end = writeIdx + nSamples;
    if (end <= size) {
        writeDataByRange(chunk, 0, nSamples, writeIdx);
    } else {
        int first = size - writeIdx;
        writeDataByRange(chunk, 0, first, writeIdx);
        writeDataByRange(chunk, first, nSamples, 0);
    }

    writeIdx = end % size;
    if (end >= size) isFull = true;
}

void CircularFIFO::readNSamples(std::span<float> out) {
    int n = static_cast<int>(out.size());
    int filled = getFilledSize();
    if (n > filled) n = filled;

    int start = (writeIdx - n + size) % size;

    if (start + n <= size) {
        readDataByRange(out, start, start + n, 0);
    } else {
        int tail = size - start;
        readDataByRange(out, start, size, 0);
        readDataByRange(out, 0, n - tail, tail);
    }
}

void CircularFIFO::readAll(std::span<float> out) {
    int filled = getFilledSize();
    if (static_cast<int>(out.size()) < filled) {
        throw std::invalid_argument("readAll output buffer too small");
    }
    if (!isFull) {
        readDataByRange(out, 0, writeIdx, 0);
    } else {
        int tail = size - writeIdx;
        readDataByRange(out, writeIdx, size, 0);
        readDataByRange(out, 0, writeIdx, tail);
    }
}

// MirrorCircularFIFO — `size` is the logical capacity. The underlying `data`
// vector is sized to 2*size so the n most-recent samples are always contiguous.
MirrorCircularFIFO::MirrorCircularFIFO(int size, const std::string& channelName)
    : FIFO(size, channelName) {
    data.assign(static_cast<size_t>(size) * 2, 0.f);
}

void MirrorCircularFIFO::addSample(float sample) {
    data[writeIdx] = sample;
    data[writeIdx + size] = sample;
    writeIdx = (writeIdx + 1) % size;
    if (writeIdx == 0) isFull = true;
}

void MirrorCircularFIFO::addChunk(std::span<const float> chunk) {
    int nSamples = static_cast<int>(chunk.size());

    if (nSamples > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(nSamples) +
            ") is larger than buffer size (" + std::to_string(size) +
            ". This could lead to data loss. Split chunk into multiple chunks)");
    }

    if (nSamples == size) {
        writeDataByRange(chunk, 0, nSamples, 0);
        writeDataByRange(chunk, 0, nSamples, size);
        writeIdx = 0;
        isFull = true;
        return;
    }

    int end = writeIdx + nSamples;
    if (end <= size) {
        writeDataByRange(chunk, 0, nSamples, writeIdx);
        writeDataByRange(chunk, 0, nSamples, writeIdx + size);
    } else {
        int first = size - writeIdx;
        writeDataByRange(chunk, 0, first, writeIdx);
        writeDataByRange(chunk, 0, first, writeIdx + size);
        writeDataByRange(chunk, first, nSamples, 0);
        writeDataByRange(chunk, first, nSamples, size);
    }

    writeIdx = end % size;
    if (end >= size) isFull = true;
}

std::span<const float> MirrorCircularFIFO::peekNSamples(int n) const {
    int filled = getFilledSize();
    if (n > filled) n = filled;
    int start = writeIdx + size - n;
    return std::span<const float>(data.data() + start, static_cast<size_t>(n));
}

void MirrorCircularFIFO::readNSamples(std::span<float> out) {
    int n = static_cast<int>(out.size());
    auto src = peekNSamples(n);
    std::copy(src.begin(), src.end(), out.begin());
}

void MirrorCircularFIFO::readAll(std::span<float> out) {
    int filled = getFilledSize();
    if (static_cast<int>(out.size()) < filled) {
        throw std::invalid_argument("readAll output buffer too small");
    }
    if (!isFull) {
        readDataByRange(out, 0, writeIdx, 0);
    } else {
        readDataByRange(out, writeIdx, writeIdx + size, 0);
    }
}
