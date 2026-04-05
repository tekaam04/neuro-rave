#include <vector>
#include <string>
#include <stdexcept>
#include <cmath>
#include "fifo.h"
#include "filter.h"

// BaseFilter
BaseFilter::BaseFilter(float sampleRate, float freq, float q)
    : sampleRate(sampleRate), freq(freq), q(q) {}

void BaseFilter::setFreq(float freq) {
    this->freq = freq;
    calculateCoefficients();
}

void BaseFilter::setQ(float q) {
    this->q = q;
    calculateCoefficients();
}

float BaseFilter::getFreq() {
    return freq;
}

float BaseFilter::getQ() {
    return q;
}

float BaseFilter::getWeightedSum(std::vector<float>& coeffs, std::vector<float>& buffer) {
    if (buffer.size() < coeffs.size()) {
        throw std::invalid_argument(
            "Buffer size is too small (" + std::to_string(buffer.size()) +
            ") compared to number of coefficients in filter(" + std::to_string(coeffs.size()) + ")");
    }

    float filteredSample = 0.f;

    for (int i = 0; i < coeffs.size(); i++) {
        int bufferIdx = buffer.size() - 1 - i;
        filteredSample += coeffs[i] * buffer[bufferIdx];
    }

    return filteredSample;
}

// BasicFIRFilter
BasicFIRFilter::BasicFIRFilter(float sampleRate, std::vector<float>& preCoeffs)
    : BaseFilter(sampleRate), preCoeffs(preCoeffs) {}

float BasicFIRFilter::applyFilter(std::vector<float>& buffer) {
    return getWeightedSum(preCoeffs, buffer);
}

void BasicFIRFilter::calculateCoefficients() {
    // FIR coefficients are set directly, no recalculation needed
}

// BiquadIIRFilter
BiquadIIRFilter::BiquadIIRFilter(float sampleRate, float freq, float q)
    : BaseFilter(sampleRate, freq, q), outputHistory(2) {
    calculateCoefficients();
}

float BiquadIIRFilter::applyFilter(std::vector<float>& buffer) {
    auto history = outputHistory.getNSamples(postCoeffs.size());
    float output = getWeightedSum(preCoeffs, buffer) - getWeightedSum(postCoeffs, history);

    outputHistory.addSample(output);

    return output;
}

void BiquadIIRFilter::calculateCoefficients() {
    float k = std::tan(M_PI * freq / sampleRate);
    float k2 = k * k;
    float norm = 1.0f / (1.0f + k / q + k2);

    // Lowpass biquad coefficients
    float b0 = k2 * norm;
    float b1 = 2.0f * b0;
    float b2 = b0;
    float a1 = 2.0f * (k2 - 1.0f) * norm;
    float a2 = (1.0f - k / q + k2) * norm;

    preCoeffs = {b0, b1, b2};
    postCoeffs = {a1, a2};
}
