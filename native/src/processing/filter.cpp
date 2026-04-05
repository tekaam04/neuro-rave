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

// FIRFilter
FIRFilter::FIRFilter(float sampleRate, float freq, float q)
    : BaseFilter(sampleRate, freq, q) {}

FIRFilter::FIRFilter(float sampleRate, std::vector<float> preCoeffs)
    : BaseFilter(sampleRate), preCoeffs(std::move(preCoeffs)) {}

// BasicFIRFilter
BasicFIRFilter::BasicFIRFilter(float sampleRate, float freq, float q)
    : FIRFilter(sampleRate, freq, q) {
    calculateCoefficients();
}

BasicFIRFilter::BasicFIRFilter(float sampleRate, std::vector<float> preCoeffs)
    : FIRFilter(sampleRate, std::move(preCoeffs)) {
    calculateFreqAndQ();
}

float BasicFIRFilter::applyFilter(std::vector<float>& buffer) {
    return getWeightedSum(preCoeffs, buffer);
}

void BasicFIRFilter::calculateCoefficients() {
    // FIR coefficients are set directly, no recalculation needed
}

void BasicFIRFilter::calculateFreqAndQ() {
    // No meaningful freq/q derivation for arbitrary FIR coefficients
}

// IIRFilter
IIRFilter::IIRFilter(float sampleRate, float freq, float q)
    : BaseFilter(sampleRate, freq, q), outputHistory(2) {}

IIRFilter::IIRFilter(float sampleRate, std::vector<float> preCoeffs, std::vector<float> postCoeffs)
    : BaseFilter(sampleRate), outputHistory(2), preCoeffs(std::move(preCoeffs)), postCoeffs(std::move(postCoeffs)) {}

// BiquadIIRLowPassFilter
BiquadIIRLowPassFilter::BiquadIIRLowPassFilter(float sampleRate, float freq, float q)
    : IIRFilter(sampleRate, freq, q) {
    calculateCoefficients();
}

BiquadIIRLowPassFilter::BiquadIIRLowPassFilter(float sampleRate, std::vector<float> preCoeffs, std::vector<float> postCoeffs)
    : IIRFilter(sampleRate, std::move(preCoeffs), std::move(postCoeffs)) {
    calculateFreqAndQ();
}

float BiquadIIRLowPassFilter::applyFilter(std::vector<float>& buffer) {
    auto history = outputHistory.getNSamples(postCoeffs.size());
    float output = getWeightedSum(preCoeffs, buffer) - getWeightedSum(postCoeffs, history);

    outputHistory.addSample(output);

    return output;
}

void BiquadIIRLowPassFilter::calculateCoefficients() {
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

void BiquadIIRLowPassFilter::calculateFreqAndQ() {
    float b0 = preCoeffs[0];
    float a1 = postCoeffs[0];
    float a2 = postCoeffs[1];

    float norm = b0 > 0.f ? b0 / ((1.0f + a1 + a2) / 4.0f) > 0.f ? (1.0f + a1 + a2) / (4.0f * b0) : 1.0f : 1.0f;
    norm = (1.0f - a1 + a2) / 4.0f;
    float k2 = b0 / norm;
    float k = std::sqrt(k2);

    freq = std::atan(k) * sampleRate / M_PI;

    float kOverQ = 1.0f / norm - 1.0f - k2;
    q = k / kOverQ;
}
