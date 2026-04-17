#pragma once

#include <vector>
#include <span>
#include <cstdint>
#include <stdexcept>
#include <algorithm>
#include <string>

bool isPowerOfTwo(int n);

struct RingStorage {
    std::vector<float> data;
    int size;
    int mask;

    explicit RingStorage(int size)
        : data(size, 0.f), size(size), mask(size - 1) {
        if (!isPowerOfTwo(size)) {
            throw std::invalid_argument(
                "RingStorage size (" + std::to_string(size) + ") must be a power of two");
        }
    }

    float& at(int64_t idx)             { return data[idx & mask]; }
    const float& at(int64_t idx) const { return data[idx & mask]; }

    void writeChunk(std::span<const float> chunk, int64_t beginIdx) {
        int n = static_cast<int>(chunk.size());
        int w = static_cast<int>(beginIdx & mask);
        int end = w + n;

        if (end <= size) {
            writeDataByRange(chunk, 0, n, w);
        } else {
            int first = size - w;
            writeDataByRange(chunk, 0, first, w);
            writeDataByRange(chunk, first, n, 0);
        }
    }

    void readChunk(std::span<float> out, int64_t beginIdx) const {
        int n = static_cast<int>(out.size());
        int start = static_cast<int>(beginIdx & mask);

        if (start + n <= size) {
            readDataByRange(out, start, start + n, 0);
        } else {
            int tail = size - start;
            readDataByRange(out, start, size, 0);
            readDataByRange(out, 0, n - tail, tail);
        }
    }

protected:
    static void validateRange(int begin, int end, int maxSize, const std::string& name) {
        if (begin < 0 || end > maxSize || begin > end) {
            throw std::out_of_range(
                name + " range [" + std::to_string(begin) + ":" + std::to_string(end) +
                "] out of bounds for size " + std::to_string(maxSize));
        }
    }

    void writeDataByRange(std::span<const float> source,
                          int sourceBegin = 0, int sourceEnd = -1, int dataBegin = 0) {
        if (sourceEnd == -1) sourceEnd = static_cast<int>(source.size());
        int copyLen = sourceEnd - sourceBegin;

        validateRange(sourceBegin, sourceEnd, static_cast<int>(source.size()), "source");
        validateRange(dataBegin, dataBegin + copyLen, static_cast<int>(data.size()), "data");

        std::copy(source.begin() + sourceBegin, source.begin() + sourceEnd,
                  data.begin() + dataBegin);
    }

    void readDataByRange(std::span<float> result,
                         int dataBegin = 0, int dataEnd = -1, int resultBegin = 0) const {
        if (dataEnd == -1) dataEnd = static_cast<int>(data.size());
        int copyLen = dataEnd - dataBegin;

        validateRange(dataBegin, dataEnd, static_cast<int>(data.size()), "data");
        validateRange(resultBegin, resultBegin + copyLen, static_cast<int>(result.size()), "result");

        std::copy(data.begin() + dataBegin, data.begin() + dataEnd,
                  result.begin() + resultBegin);
    }
};

struct MirrorRingStorage {
    std::vector<float> data;
    int size;
    int mask;

    explicit MirrorRingStorage(int size)
        : data(static_cast<size_t>(size) * 2, 0.f), size(size), mask(size - 1) {
        if (!isPowerOfTwo(size)) {
            throw std::invalid_argument(
                "MirrorRingStorage size (" + std::to_string(size) + ") must be a power of two");
        }
    }

    void write(int64_t idx, float val) {
        int phys = static_cast<int>(idx & mask);
        data[phys] = val;
        data[phys + size] = val;
    }

    void writeChunk(std::span<const float> chunk, int64_t beginIdx) {
        int n = static_cast<int>(chunk.size());
        int w = static_cast<int>(beginIdx & mask);
        int end = w + n;

        if (end <= size) {
            writeDataByRange(chunk, 0, n, w);
            writeDataByRange(chunk, 0, n, w + size);
        } else {
            int first = size - w;
            writeDataByRange(chunk, 0, first, w);
            writeDataByRange(chunk, 0, first, w + size);
            writeDataByRange(chunk, first, n, 0);
            writeDataByRange(chunk, first, n, size);
        }
    }

    void readChunk(std::span<float> out, int64_t beginIdx) const {
        int n = static_cast<int>(out.size());
        int start = static_cast<int>(beginIdx & mask);
        int from = start + size - n;
        readDataByRange(out, from, from + n, 0);
    }

    std::span<const float> peek(int64_t writeIdx, int n) const {
        if (n > size) n = size;
        int w = static_cast<int>(writeIdx & mask);
        int start = w + size - n;
        return std::span<const float>(data.data() + start, static_cast<size_t>(n));
    }

protected:
    static void validateRange(int begin, int end, int maxSize, const std::string& name) {
        if (begin < 0 || end > maxSize || begin > end) {
            throw std::out_of_range(
                name + " range [" + std::to_string(begin) + ":" + std::to_string(end) +
                "] out of bounds for size " + std::to_string(maxSize));
        }
    }

    void writeDataByRange(std::span<const float> source,
                          int sourceBegin = 0, int sourceEnd = -1, int dataBegin = 0) {
        if (sourceEnd == -1) sourceEnd = static_cast<int>(source.size());
        int copyLen = sourceEnd - sourceBegin;

        validateRange(sourceBegin, sourceEnd, static_cast<int>(source.size()), "source");
        validateRange(dataBegin, dataBegin + copyLen, static_cast<int>(data.size()), "data");

        std::copy(source.begin() + sourceBegin, source.begin() + sourceEnd,
                  data.begin() + dataBegin);
    }

    void readDataByRange(std::span<float> result,
                         int dataBegin = 0, int dataEnd = -1, int resultBegin = 0) const {
        if (dataEnd == -1) dataEnd = static_cast<int>(data.size());
        int copyLen = dataEnd - dataBegin;

        validateRange(dataBegin, dataEnd, static_cast<int>(data.size()), "data");
        validateRange(resultBegin, resultBegin + copyLen, static_cast<int>(result.size()), "result");

        std::copy(data.begin() + dataBegin, data.begin() + dataEnd,
                  result.begin() + resultBegin);
    }
};
