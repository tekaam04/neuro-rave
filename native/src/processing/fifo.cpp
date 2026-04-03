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
    : size(size), nChannels(nChannels), timestamp(0.0), isFull(false), index(0), data(create2DVector(this->nChannels, this->size)) {

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

void FIFO::copyChunkRange(std::vector<std::vector<float>>& chunk,
                           int chunkBegin, int chunkEnd,
                           int dataBegin) {
    if (chunkEnd == -1) chunkEnd = chunk[0].size();
    int copyLen = chunkEnd - chunkBegin;
    
    validateRange(chunkBegin, chunkEnd, chunk[0].size(), "chunk");
    validateRange(dataBegin, dataBegin + copyLen, data[0].size(), "data");

    for (int ch = 0; ch < nChannels; ch++) {
        std::copy(chunk[ch].begin() + chunkBegin, 
                  chunk[ch].begin() + chunkEnd,
                  data[ch].begin() + dataBegin);
    }
}


// CircularFIFO class
CircularFIFO::CircularFIFO(int size, int nChannels) : FIFO::FIFO(size, nChannels) {}

CircularFIFO::CircularFIFO(float seconds, int sampleRate, int nChannels) : FIFO::FIFO(seconds, sampleRate, nChannels) {}

void CircularFIFO::addSample(std::vector<float>& sample) {
    copySample(sample, this->index);
    this->index = (this->index + 1) % this->size;

    if (this->index == 0) {
        this->isFull = true;
    }

void CircularFIFO::addChunk(std::vector<std::vector<float>& chunk) {
    int nSamples = chunk[0].size();

    if (chunk.size() != this->nChannels) {
        throw std::invalid_argument(
            "Number of rows in chunk (" + std::to_string(sample.size()) +
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
        this->index = 0;
        this->isFull = true;
    }

    int end = this->index + nSamples;
    if (end <= this->size) {
        FIFO::copyChunkRange(chunk, 0, chunk.size() - 1, index);
    } else {
        int first = this->size - this->index;
        FIFO::copyChunkRange(chunk, 0, first, 0);
        FIFO::copyChunkRange(chunk, first, chunk.size() - 1, 0);
    }

    this->index = end % this->size;

    if (end >= this->size) {
        this->isFull = true;
    }
        
}