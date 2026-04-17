#pragma once

#include <cstring>
#include "channel_array.h"

class OverlapAddBuffer {
public:
    OverlapAddBuffer(int nChannels, int blockSize, int hopSize)
        : accum(nChannels, blockSize), blockSize(blockSize), hopSize(hopSize) {}

    void addBlock(const ChannelArrayConstView& block) {
        for (int ch = 0; ch < accum.numChannels(); ch++) {
            std::span<float> dst = accum.view().channel(ch);
            std::span<const float> src = block.channel(ch);
            for (int i = 0; i < blockSize; i++) {
                dst[i] += src[i];
            }
        }
    }

    void popHop(const ChannelArrayView& out) {
        for (int ch = 0; ch < accum.numChannels(); ch++) {
            std::span<float> buf = accum.view().channel(ch);
            std::span<float> dst = out.channel(ch);

            std::copy(buf.begin(), buf.begin() + hopSize, dst.begin());

            std::copy(buf.begin() + hopSize, buf.begin() + blockSize, buf.begin());
            std::fill(buf.begin() + (blockSize - hopSize), buf.begin() + blockSize, 0.f);
        }
    }

private:
    ChannelArrayBuffer accum;
    int blockSize;
    int hopSize;
};
