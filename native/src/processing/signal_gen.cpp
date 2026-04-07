#include <vector>
#include <span>
#include <stdexcept>
#include <cmath>
#include <random>
#include <numeric>
#include "fifo.h"
#include "channel_array.h"
#include "signal_gen.h"

float dbToLinear(float amplitudeDB) {
    return std::pow(10.0f, amplitudeDB) / 20.0f;
}

float linearToDB(float amplitudeLin) {
    return 20.0f * std::log10(amplitudeLin);
}

void normalizeNumbers(std::span<const float> in,
                      std::span<float> out) {
    float sum = std::accumulate(in.begin(), in.end(), 0.f);
    for (size_t i = 0; i < in.size(); i++) {
        out[i] = in[i] / sum;
    }
}

float getWeightedAverage(std::span<const float> values,
                         std::span<const float> weights) {
    float sumW = std::accumulate(weights.begin(), weights.end(), 0.f);
    float sum = 0.f;
    for (size_t i = 0; i < values.size(); i++) {
        sum += values[i] * (weights[i] / sumW);
    }
    return sum;
}

Oscillator::Oscillator(float sampleRate, float freq, float amplitudeLin, float phase, SIGNAL_TYPE signalType, const std::string& name)
    : sampleRate(sampleRate), freq(freq), phase(phase), amplitudeLin(amplitudeLin), signalType(signalType), name(name) {
    if (amplitudeLin > 1.f || amplitudeLin < 0.f) {
        throw std::invalid_argument("Amplitude must be between 0 and 1, got: " + std::to_string(amplitudeLin));
    }

    if (phase > 1.f || phase < -1.f) {
        throw std::invalid_argument("Phase must be between -1 and 1, got: " + std::to_string(phase));
    }

    if (signalType == WHITE_NOISE) {
        // set fields to -1 so we know they are unnecessary
        this->freq = -1;
        this->phase = -1;
    }
}

void Oscillator::generateWaveChunk(std::span<float> out) {
    for (size_t i = 0; i < out.size(); i++) {
        out[i] = generateWaveSample();
    }
}

void Oscillator::updatePhase() {
    phase += 2 * M_PI * freq / sampleRate;
    if (phase >= 2 * M_PI) phase -= 2 * M_PI;
}

float Oscillator::generateWaveSample() {
    float result = (this->*generators[signalType])();
    updatePhase();
    return result;
}

float Oscillator::generateSine() {
    return amplitudeLin * std::sin(phase);
}

float Oscillator::generateSquare() {
    float sine = generateSine();
    return sine <= 0 ? -1.f : 1.f;
}

float Oscillator::generateTriangle() {
    return M_2_PI * std::asin(std::sin(phase));
}

float Oscillator::generateSaw() {
    return -M_2_PI * std::atan(1 / std::tan(phase / 2));
}

float Oscillator::generateWhiteNoise() {
    static thread_local std::default_random_engine generator;
    static thread_local std::uniform_real_distribution<float> distribution(-1.0f, 1.0f);
    return amplitudeLin * distribution(generator);
}

float Oscillator::generatePinkNoise() {
    return generateWhiteNoise();  // placeholder
}

// Synthesizer
Synthesizer::Synthesizer(float sampleRate, float amplitudeLin)
    : amplitudeLin(amplitudeLin), sampleRate(sampleRate) {}

Synthesizer::Synthesizer(const std::vector<Oscillator>& oscillators, float sampleRate, float amplitudeLin)
    : oscillators(oscillators), amplitudeLin(amplitudeLin), sampleRate(sampleRate) {
    invalidateCache();
}

Synthesizer::Synthesizer(std::vector<Oscillator>&& oscillators, float sampleRate, float amplitudeLin)
    : oscillators(std::move(oscillators)), amplitudeLin(amplitudeLin), sampleRate(sampleRate) {
    invalidateCache();
}

void Synthesizer::addOscillator(const Oscillator& oscillator) {
    oscillators.emplace_back(oscillator);
    invalidateCache();
}

void Synthesizer::addOscillator(Oscillator&& oscillator) {
    oscillators.emplace_back(std::move(oscillator));
    invalidateCache();
}

void Synthesizer::invalidateCache() {
    cacheDirty = true;
}

void Synthesizer::rebuildCache() {
    if (!cacheDirty) return;
    cachedNumOscillators = static_cast<int>(oscillators.size());
    cachedNames.resize(cachedNumOscillators);
    cachedFreqs.resize(cachedNumOscillators);
    cachedAmplitudes.resize(cachedNumOscillators);
    cachedNormalizedAmps.resize(cachedNumOscillators);
    for (int i = 0; i < cachedNumOscillators; i++) {
        cachedNames[i] = oscillators[i].name;
        cachedFreqs[i] = oscillators[i].freq;
        cachedAmplitudes[i] = oscillators[i].amplitudeLin;
    }
    normalizeNumbers(std::span<const float>(cachedAmplitudes),
                     std::span<float>(cachedNormalizedAmps));
    cacheDirty = false;
}

void Synthesizer::generateSignalsSample(std::span<float> out) {
    for (size_t i = 0; i < oscillators.size(); i++) {
        out[i] = oscillators[i].generateWaveSample();
    }
}

int Synthesizer::getNumberOscillators() {
    rebuildCache();
    return cachedNumOscillators;
}

void Synthesizer::generateSignalsChunk(const ChannelArrayView& out) {
    int nOsc = getNumberOscillators();
    if (out.numChannels() != nOsc) {
        throw std::invalid_argument(
            "generateSignalsChunk: output channels (" + std::to_string(out.numChannels()) +
            ") != number of oscillators (" + std::to_string(nOsc) + ")");
    }
    for (int i = 0; i < nOsc; i++) {
        oscillators[i].generateWaveChunk(out.channel(i));
    }
}

float Synthesizer::generateCombinedSample(bool weightOscEqually) {
    int nOsc = getNumberOscillators();
    float combined = 0.f;
    if (weightOscEqually) {
        for (int i = 0; i < nOsc; i++) {
            combined += oscillators[i].generateWaveSample();
        }
        if (nOsc > 0) combined /= nOsc;
    } else {
        // rebuildCache() already called via getNumberOscillators().
        for (int i = 0; i < nOsc; i++) {
            combined += oscillators[i].generateWaveSample() * cachedNormalizedAmps[i];
        }
    }
    return amplitudeLin * combined;
}

void Synthesizer::generateCombinedChunk(std::span<float> out, bool weightOscEqually) {
    for (size_t i = 0; i < out.size(); i++) {
        out[i] = generateCombinedSample(weightOscEqually);
    }
}

void Synthesizer::getOscillatorsByField(const std::function<bool(const Oscillator&)>& predicate,
                                        std::vector<Oscillator*>& out) {
    out.clear();
    out.reserve(oscillators.size());
    for (auto& osc : oscillators) {
        if (predicate(osc)) {
            out.emplace_back(&osc);
        }
    }
}

void Synthesizer::getOscillatorIdxByField(const std::function<bool(const Oscillator&)>& predicate,
                                          std::vector<int>& out) {
    out.clear();
    out.reserve(oscillators.size());
    for (int i = 0; i < static_cast<int>(oscillators.size()); i++) {
        if (predicate(oscillators[i])) {
            out.emplace_back(i);
        }
    }
}

void Synthesizer::generateSignalsByField(const std::function<bool(const Oscillator&)>& predicate,
                                         const ChannelArrayView& out) {
    int writeCh = 0;
    for (auto& osc : oscillators) {
        if (predicate(osc)) {
            if (writeCh >= out.numChannels()) {
                throw std::invalid_argument("generateSignalsByField: output has too few channels");
            }
            osc.generateWaveChunk(out.channel(writeCh));
            writeCh++;
        }
    }
}

// --- standardized queries ---

Oscillator* Synthesizer::getOscillatorByName(const std::string& name) {
    for (auto& osc : oscillators) {
        if (osc.name == name) return &osc;
    }
    throw std::invalid_argument("Oscillator not found: " + name);
}

void Synthesizer::getOscillatorsByNames(const std::vector<std::string>& names,
                                        std::vector<Oscillator*>& out) {
    getOscillatorsByField([&names](const Oscillator& o) {
        for (auto& n : names) {
            if (o.name == n) return true;
        }
        return false;
    }, out);
}

void Synthesizer::getOscillatorsByType(SIGNAL_TYPE type, std::vector<Oscillator*>& out) {
    getOscillatorsByField([type](const Oscillator& o) {
        return o.signalType == type;
    }, out);
}

void Synthesizer::getOscillatorsByFreqRange(float minFreq, float maxFreq,
                                            std::vector<Oscillator*>& out) {
    getOscillatorsByField([minFreq, maxFreq](const Oscillator& o) {
        return o.freq >= minFreq && o.freq <= maxFreq;
    }, out);
}

const std::vector<std::string>& Synthesizer::getOscillatorNames() {
    rebuildCache();
    return cachedNames;
}

const std::vector<float>& Synthesizer::getOscillatorFreqs() {
    rebuildCache();
    return cachedFreqs;
}

const std::vector<float>& Synthesizer::getOscillatorAmplitudes() {
    rebuildCache();
    return cachedAmplitudes;
}

const std::vector<float>& Synthesizer::getNormalizedAmplitudes() {
    rebuildCache();
    return cachedNormalizedAmps;
}
