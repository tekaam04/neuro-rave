#include <vector>
#include <string>
#include <stdexcept>
#include "fifo.h"

bool isPowerOfTwo(int n) {
    return (n != 0) && (n & (n - 1) == 0);
}

int secondsToSamples(float seconds, int sampleRate) {
    return int(seconds * sampleRate);
}

float samplesToSeconds(int samples, int sampleRate) {
     return samples / sampleRate;
}

void applyWindow(std::vector<std::vector<float>>& data, std::string windowType);

// FIFO base class
FIFO::FIFO(int size, const std::string& channelName)
    : size(size), channelName(channelName), isFull(false), writeIdx(0), data(size, 0.f) {}

void FIFO::validateRange(int begin, int end, int maxSize, const std::string& name) {
    if (begin < 0 || end > maxSize || begin > end) {
        throw std::out_of_range(
            name + " range [" + std::to_string(begin) + ":" + std::to_string(end) +
            "] out of bounds for size " + std::to_string(maxSize));
    }
}

void FIFO::writeDataByRange(std::vector<float>& source,
                             int sourceBegin, int sourceEnd,
                             int dataBegin) {
    if (sourceEnd == -1) sourceEnd = source.size();
    int copyLen = sourceEnd - sourceBegin;

    validateRange(sourceBegin, sourceEnd, source.size(), "source");
    validateRange(dataBegin, dataBegin + copyLen, data.size(), "data");

    std::copy(source.begin() + sourceBegin, source.begin() + sourceEnd,
              data.begin() + dataBegin);
}

void FIFO::readDataByRange(std::vector<float>& result,
                            int dataBegin, int dataEnd,
                            int resultBegin) {
    if (dataEnd == -1) dataEnd = data.size();
    int copyLen = dataEnd - dataBegin;

    validateRange(dataBegin, dataEnd, data.size(), "data");
    validateRange(resultBegin, resultBegin + copyLen, result.size(), "result");

    std::copy(data.begin() + dataBegin, data.begin() + dataEnd,
              result.begin() + resultBegin);
}

int FIFO::getFilledSize() {
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

void CircularFIFO::addChunk(std::vector<float>& chunk) {
    int nSamples = chunk.size();

    if (nSamples > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(nSamples) +
            ") is larger than buffer size (" + std::to_string(size) +
            ". This could lead to data loss. Split chunk into multiple chunks)");
    }

    if (nSamples == size) {
        data = chunk;
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

std::vector<float> CircularFIFO::getData() {
    int filled = getFilledSize();
    std::vector<float> result(filled, 0.f);
    if (!isFull) {
        readDataByRange(result, 0, writeIdx, 0);
    } else {
        int tail = size - writeIdx;
        readDataByRange(result, writeIdx, -1, 0);
        readDataByRange(result, 0, writeIdx, tail);
    }
    return result;
}

std::vector<float> CircularFIFO::getNSamples(int n) {
    int filled = getFilledSize();
    if (n > filled) n = filled;

    std::vector<float> result(n, 0.f);
    int start = (writeIdx - n + size) % size;

    if (start + n <= size) {
        readDataByRange(result, start, start + n, 0);
    } else {
        int tail = size - start;
        readDataByRange(result, start, size, 0);
        readDataByRange(result, 0, n - tail, tail);
    }
    return result;
}

// MirrorCircularFIFO
MirrorCircularFIFO::MirrorCircularFIFO(int size, const std::string& channelName)
    : FIFO(size * 2, channelName) {}

void MirrorCircularFIFO::addSample(float sample) {
    data[writeIdx] = sample;
    data[writeIdx + size] = sample;
    writeIdx = (writeIdx + 1) % size;
    if (writeIdx == 0) isFull = true;
}

void MirrorCircularFIFO::addChunk(std::vector<float>& chunk) {
    int nSamples = chunk.size();

    if (nSamples > size) {
        throw std::invalid_argument(
            "Chunk size (" + std::to_string(nSamples) +
            ") is larger than buffer size (" + std::to_string(size) +
            ". This could lead to data loss. Split chunk into multiple chunks)");
    }

    if (nSamples == size) {
        writeDataByRange(chunk, 0, -1, 0);
        writeDataByRange(chunk, 0, -1, size);
        writeIdx = 0;
        isFull = true;
        return;
    }

    int end = writeIdx + nSamples;
    if (end <= size) {
        writeDataByRange(chunk, 0, -1, writeIdx);
        writeDataByRange(chunk, 0, -1, writeIdx + size);
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

std::vector<float> MirrorCircularFIFO::getNSamples(int n) {
    int filled = getFilledSize();
    if (n > filled) n = filled;

    std::vector<float> result(n, 0.f);
    int start = writeIdx + size - n;
    readDataByRange(result, start, start + n, 0);
    return result;
}

std::vector<float> MirrorCircularFIFO::getData() {
    int filled = getFilledSize();
    std::vector<float> result(filled, 0.f);
    if (!isFull) {
        readDataByRange(result, 0, writeIdx, 0);
    } else {
        readDataByRange(result, writeIdx, writeIdx + size, 0);
    }
    return result;
}
