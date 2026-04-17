#include "fft.h"
#include "ring_storage.h"
#include <cmath>
#include <stdexcept>
#include <algorithm>

int nextPowerOfTwo(int n) {
    if (n <= 0) return 1;
    int power = 1;
    while (power < n) {
        power *= 2;
    }
    return power;
}

std::vector<cpx> FFT::forward(std::span<const float> input) {
    int n = static_cast<int>(input.size());
    if (!isPowerOfTwo(n)) {
        throw std::invalid_argument("FFT length must be power of 2, got: " + std::to_string(n));
    }

    std::vector<cpx> data(n);
    for (int i = 0; i < n; i++) {
        data[i] = cpx(input[i], 0.f);
    }

    bitReverseCopy(data);
    fftIterative(data);
    return data;
}

std::vector<float> FFT::inverse(std::span<const cpx> input) {
    int n = static_cast<int>(input.size());

    std::vector<cpx> data(n);
    for (int i = 0; i < n; i++) {
        data[i] = std::conj(input[i]);
    }

    bitReverseCopy(data);
    fftIterative(data);

    std::vector<float> result(n);
    for (int i = 0; i < n; i++) {
        result[i] = std::conj(data[i]).real() / n;
    }
    return result;
}

void FFT::forward(const ChannelArrayConstView& in, std::vector<std::vector<cpx>>& out) {
    int nCh = in.numChannels();
    out.resize(nCh);
    for (int ch = 0; ch < nCh; ch++) {
        out[ch] = forward(in.channel(ch));
    }
}

void FFT::inverse(const std::vector<std::vector<cpx>>& in, const ChannelArrayView& out) {
    int nCh = static_cast<int>(in.size());
    for (int ch = 0; ch < nCh; ch++) {
        auto result = inverse(in[ch]);
        std::span<float> dst = out.channel(ch);
        int n = static_cast<int>(result.size());
        if (n > out.numFrames()) n = out.numFrames();
        std::copy(result.begin(), result.begin() + n, dst.begin());
    }
}

void FFT::bitReverseCopy(std::vector<cpx>& data) {
    unsigned int n = static_cast<unsigned int>(data.size());
    unsigned int j = 0;
    unsigned int mask;

    for (unsigned int i = 0; i < n; i++) {
        if (j > i) {
            std::swap(data[i], data[j]);
        }

        mask = n >> 1;
        while (j & mask) {
            j &= ~mask;
            mask >>= 1;
        }
        j |= mask;
    }
}

void FFT::fftIterative(std::vector<cpx>& data) {
    int n = static_cast<int>(data.size());
    int stages = static_cast<int>(std::log2(n));

    for (int s = 1; s <= stages; s++) {
        int m = 1 << s;
        cpx w_m = twiddleFactor(1, m);

        for (int k = 0; k < n; k += m) {
            cpx w(1.f, 0.f);
            for (int j = 0; j < m / 2; j++) {
                cpx t = w * data[k + j + m / 2];
                cpx u = data[k + j];
                data[k + j] = u + t;
                data[k + j + m / 2] = u - t;
                w *= w_m;
            }
        }
    }
}

cpx FFT::twiddleFactor(int k, int n) {
    float angle = -2.0f * static_cast<float>(M_PI) * k / n;
    return cpx(std::cos(angle), std::sin(angle));
}
