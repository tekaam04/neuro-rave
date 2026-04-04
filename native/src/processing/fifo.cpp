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

std::vector<std::vector<float>> create2DVector(int nRows, int nCols) {
    return std::vector<std::vector<float>>(nRows, std::vector<float>(nCols));
}
// implememnt timestamp later
// FIFO base class
FIFO::FIFO(int size, int nChannels)
    : size(size), nChannels(nChannels), timestamp(0.f), isFull(false), writeIdx(0), data(create2DVector(this->nChannels, this->size)) {

    }

FIFO::FIFO(float seconds, int sampleRate, int nChannels)
    : FIFO(secondsToSamples(seconds, sampleRate), nChannels) {
    }

void FIFO::addChunk(std::vector<std::vector<float>>& chunk) {
    for (std::vector<float> sample : chunk) {
        FIFO::addSample(sample);
    }
}

void FIFO::validateRange(int begin, int end, int maxSize, const std::string& name) {
    if (begin < 0 || end > maxSize || begin > end) {
        throw std::out_of_range(
            name + " range [" + std::to_string(begin) + ":" + std::to_string(end) +
            "] out of bounds for size " + std::to_string(maxSize));
    }
}

void FIFO::copySample(std::vector<float>& sample, int dataIndex) {
    if (sample.size() != nChannels) {
        throw std::invalid_argument(
            "Sample size (" + std::to_string(sample.size()) +
            ") does not match number of channels (" + std::to_string(nChannels) + ")");
    }
    validateRange(dataIndex, dataIndex + 1, data[0].size(), "data");
    for (int ch = 0; ch < nChannels; ch++) {
        data[ch][dataIndex] = sample[ch];
    }
}

void copy2DVector(std::vector<std::vector<float>>& source,
                  std::vector<std::vector<float>>& target,
                  int sourceBegin, int sourceEnd,
                  int targetBegin) {
    int nChannels = source.size();
    for (int ch = 0; ch < nChannels; ch++) {
        std::copy(source[ch].begin() + sourceBegin,
                  source[ch].begin() + sourceEnd,
                  target[ch].begin() + targetBegin);
    }
}

void FIFO::writeDataByRange(std::vector<std::vector<float>>& chunk,
                             int chunkBegin, int chunkEnd,
                             int dataBegin) {
    if (chunkEnd == -1) chunkEnd = chunk[0].size();
    int copyLen = chunkEnd - chunkBegin;

    validateRange(chunkBegin, chunkEnd, chunk[0].size(), "chunk");
    validateRange(dataBegin, dataBegin + copyLen, data[0].size(), "data");

    copy2DVector(chunk, data, chunkBegin, chunkEnd, dataBegin);
}

void FIFO::readDataByRange(std::vector<std::vector<float>>& result,
                            int dataBegin, int dataEnd,
                            int resultBegin) {
    if (dataEnd == -1) dataEnd = data[0].size();
    int copyLen = dataEnd - dataBegin;

    validateRange(dataBegin, dataEnd, data[0].size(), "data");
    validateRange(resultBegin, resultBegin + copyLen, result[0].size(), "result");

    copy2DVector(data, result, dataBegin, dataEnd, resultBegin);
}

std::pair<int, int> FIFO::getShape() {
    return {nChannels, isFull ? size : writeIdx};
}

// CircularFIFO class
CircularFIFO::CircularFIFO(int size, int nChannels) : FIFO::FIFO(size, nChannels) {}

CircularFIFO::CircularFIFO(float seconds, int sampleRate, int nChannels) : FIFO::FIFO(seconds, sampleRate, nChannels) {}

void CircularFIFO::addSample(std::vector<float>& sample) {
    copySample(sample, this->writeIdx);
    this->writeIdx = (this->writeIdx + 1) % this->size;

    if (this->writeIdx == 0) {
        this->isFull = true;
    }
}

void CircularFIFO::addChunk(std::vector<std::vector<float>>& chunk) {
    int nSamples = chunk[0].size();

    if (chunk.size() != this->nChannels) {
        throw std::invalid_argument(
            "Number of rows in chunk (" + std::to_string(chunk.size()) +
            ") does not match number of channels (" + std::to_string(this->nChannels) + ")");
    }

    if (nSamples > this->size) {
        throw std::invalid_argument(
            "Number of samples in chunk (" + std::to_string(nSamples) +
            ") is larger than buffer size (" + std::to_string(this->size) + ". This could lead to data loss. Split chunk into multiple chunks)");
    }

    // if chhunk fills entire buffer, we can just reset the buffer with the new data pointing to the chunk itself
    if (nSamples == this->size) {
        this->data = chunk;
        this->writeIdx = 0;
        this->isFull = true;
        return;
    }

    int end = this->writeIdx + nSamples;
    if (end <= this->size) {
        writeDataByRange(chunk, 0, nSamples, writeIdx);
    } else {
        int first = this->size - this->writeIdx;
        writeDataByRange(chunk, 0, first, 0);
        writeDataByRange(chunk, first, nSamples, 0);
    }

    this->writeIdx = end % this->size;

    if (end >= this->size) {
        this->isFull = true;
    }

}

std::vector<std::vector<float>> CircularFIFO::getData() {
    auto result = create2DVector(nChannels, size);
    if (!this->isFull) {
        readDataByRange(result, 0, this->writeIdx, 0);
    } else {
        int tail = size - this->writeIdx;;
        readDataByRange(result, this->writeIdx, -1, 0);
        readDataByRange(result, 0, this->writeIdx, tail);
    }

    return result;
}

MirrorCircularFIFO::MirrorCircularFIFO(int size, int nChannels) : FIFO::FIFO(size * 2, nChannels) {}

MirrorCircularFIFO::MirrorCircularFIFO(float seconds, int sampleRate, int nChannels) : MirrorCircularFIFO::MirrorCircularFIFO::MirrorCircularFIFO(secondsToSamples(seconds, sampleRate), nChannels) {}

void MirrorCircularFIFO::addSample(std::vector<float>& sample){
    FIFO::copySample(sample, writeIdx);
    FIFO::copySample(sample, writeIdx + size);

    this->writeIdx = (this->writeIdx + 1) % this->size;

    if (writeIdx == 0) {
        this->isFull = true;
    }
}

void MirrorCircularFIFO::addChunk(std::vector<std::vector<float>>& chunk) {
    int nSamples = chunk[0].size();

    if (chunk.size() != this->nChannels) {
        throw std::invalid_argument(
            "Number of rows in chunk (" + std::to_string(chunk.size()) +
            ") does not match number of channels (" + std::to_string(this->nChannels) + ")");
    }

    if (nSamples > this->size) {
        throw std::invalid_argument(
            "Number of samples in chunk (" + std::to_string(nSamples) +
            ") is larger than buffer size (" + std::to_string(this->size) + ". This could lead to data loss. Split chunk into multiple chunks)");
    }

    // if chhunk fills entire buffer, we can just reset the buffer with the new data pointing to the chunk itself
    if (nSamples == this->size) {
        writeDataByRange(chunk, 0, -1, 0);
        writeDataByRange(chunk, 0, -1, this->size);
        this->writeIdx = 0;
        this->isFull = true;
        return;
    }

    int end = this->writeIdx + nSamples;
    if (end <= this->size) {
        writeDataByRange(chunk, 0, -1, writeIdx);
        writeDataByRange(chunk, 0, -1, writeIdx + size);
    } else {
        int first = this->size - this->writeIdx;
        writeDataByRange(chunk, 0, first, writeIdx);
        writeDataByRange(chunk, 0, first, writeIdx + size);
        writeDataByRange(chunk, first, nSamples, 0);
        writeDataByRange(chunk, first, nSamples, size);
    }

    this->writeIdx = end % this->size;

    if (end >= this->size) {
        this->isFull = true;
    }
}

std::vector<std::vector<float>> MirrorCircularFIFO::getData() {
    auto result = create2DVector(nChannels, size);
    if (!this->isFull) {
        readDataByRange(result, 0, this->writeIdx, 0);
    } else {
        readDataByRange(result, this->writeIdx, this->writeIdx + this->size, 0);
    }

    return result;
}