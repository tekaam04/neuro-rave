#pragma once

#include <vector>
#include <span>
#include <complex>
#include "channel_array.h"

using cpx = std::complex<float>;

int nextPowerOfTwo(int n);

class FFT {
public:
    static std::vector<cpx> forward(std::span<const float> input);
    static std::vector<float> inverse(std::span<const cpx> input);

    static void forward(const ChannelArrayConstView& in, std::vector<std::vector<cpx>>& out);
    static void inverse(const std::vector<std::vector<cpx>>& in, const ChannelArrayView& out);

private:
    static void bitReverseCopy(std::vector<cpx>& data);
    static void fftIterative(std::vector<cpx>& data);
    static cpx twiddleFactor(int k, int n);
};
