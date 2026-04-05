#include <vector>
#include "fifo.h"
#include <stdexcept>
#include "signal_gen.h"
#include <cmath>
#include <random>
#include <numeric>

float dbToLinear(float amplitudeDB) {
    return pow(10.0, amplitudeDB) / 20.0;
}

float linearToDB(float amplitudeLin) {
    return 20.0 * std::log10(amplitudeLin);
}

Oscillator::Oscillator(float sampleRate, float freq, float amplitudeLin, float phase, SIGNAL_TYPE signalType, std::string name) 
    : sampleRate(sampleRate), freq(freq), amplitudeLin(amplitudeLin), phase(phase), signalType(signalType), name(std::move(name)) {
    if (amplitudeLin > 1.f || amplitudeLin < 0.f) {
        throw std::invalid_argument("Amplitude must be between 0 and 1, got: " + std::to_string(amplitudeLin));
    } 

    if (phase > 1.f || phase < -1.f) {
        throw std::invalid_argument("Phase must be between -1 and 1, got: " + std::to_string(phase));
    }

    if (signalType == WHITE_NOISE) {
        // set fields to -1 so we know it is unecessary
        freq = -1;
        phase = -1;
    }
}

std::vector<float> Oscillator::generateWaveChunk(int nSamples) {
    std::vector<float> result(nSamples);
    for (int i = 0; i < nSamples; i++) {
        result[i] = generateWaveSample();
    }
    return result;
}

void Oscillator::updatePhase() {
    phase += 2 * M_PI * freq / sampleRate;
    if (phase >= 2 * M_PI) phase -= 2 * M_PI; 
}

float Oscillator::generateWaveSample() {
    float result  = (this->*generators[signalType])();
    updatePhase();
    return result;
}

float Oscillator::generateSine() {
    return amplitudeLin * std::sin(phase);
}

float Oscillator::generateSquare() {
    float sine = generateSine();
    if (sine <= 0) {
        return -1.f;
    } else {
        return 1.f;
    }
}

float Oscillator::generateTriangle() {
    return M_2_PI * std::asin(std::sin(phase));
}

float Oscillator::generateSaw() {
    return -M_2_PI * std::atan(1 / std::tan(phase / 2));
}

float Oscillator::generateWhiteNoise() {
    std::default_random_engine generator;
    std::uniform_real_distribution<float> distribution(-1.0f, 1.0f);
    return amplitudeLin * distribution(generator);
}

// Synthesizer
Synthesizer::Synthesizer(float sampleRate, float amplitudeLin)
    : sampleRate(sampleRate), amplitudeLin(amplitudeLin) {}

Synthesizer::Synthesizer(std::vector<Oscillator> oscillators, float sampleRate, float amplitudeLin)
    : oscillators(std::move(oscillators)), sampleRate(sampleRate), amplitudeLin(amplitudeLin) {}

void Synthesizer::addOscillator(Oscillator oscillator) {
    oscillators.push_back(std::move(oscillator));
}


std::vector<float> Synthesizer::generateSignalsSample() {
    std::vector<float> result(oscillators.size());
    for (int i = 0; i < oscillators.size(); i++) {
        result[i] = oscillators[i].generateWaveSample();
    }
    return result;
}


int Synthesizer::getNumberOscillators() {
    return oscillators.size();
}

std::vector<std::vector<float>> Synthesizer::generateSignalsChunk(int nSamples) {
    int nOsc = getNumberOscillators();
    std::vector<std::vector<float>> result(nOsc);
    for (int i = 0; i < nOsc; i++) {
        result[i] = oscillators[i].generateWaveChunk(nSamples);
    }
    return result;
}

float Synthesizer::generateCombinedSample(bool weightOscEqually) {
    int nOsc = getNumberOscillators();
    std::vector<float> samples(nOsc);
    for (int i = 0; i < nOsc; i++) {
        samples[i] = oscillators[i].generateWaveSample();
    }

    float combined;
    if (weightOscEqually) {
        combined = std::accumulate(samples.begin(), samples.end(), 0.f) / nOsc;
    } else {
        auto amps = getOscillatorAmplitudes();
        combined = getWeightedAverage(samples, amps);
    }
    return amplitudeLin * combined;
}

std::vector<float> normalizeNumbers(std::vector<float>& numbers) {
    float sum = std::accumulate(numbers.begin(), numbers.end(), 0.f);
    std::vector<float> result(numbers.size());
    for (int i = 0; i < numbers.size(); i++) {
        result[i] = numbers[i] / sum;
    }
    return result;
}

float getWeightedAverage(std::vector<float>& values, std::vector<float>& weights) {
    auto normalized = normalizeNumbers(weights);
    float sum = 0.f;
    for (int i = 0; i < values.size(); i++) {
        sum += values[i] * normalized[i];
    }
    return sum;
}

std::vector<float> Synthesizer::generateCombinedChunk(int nSamples, bool weightOscEqually) {
    std::vector<float> result(nSamples);
    for (int i = 0; i < nSamples; i++) {
        result[i] = generateCombinedSample(weightOscEqually);
    }
    return result;
}

std::vector<Oscillator*> Synthesizer::getOscillatorsByField(std::function<bool(const Oscillator&)> predicate) {
    std::vector<Oscillator*> result;
    for (auto& osc : oscillators) {
        if (predicate(osc)) {
            result.push_back(&osc);
        }
    }
    return result;
}

std::vector<int> Synthesizer::getOscillatorIdxByField(std::function<bool(const Oscillator&)> predicate) {
    std::vector<int> result;
    for (int i = 0; i < oscillators.size(); i++) {
        if (predicate(oscillators[i])) {
            result.push_back(i);
        }
    }
    return result;
}

std::vector<std::vector<float>> Synthesizer::generateSignalsByField(std::function<bool(const Oscillator&)> predicate, int nSamples) {
    auto matches = getOscillatorsByField(predicate);
    std::vector<std::vector<float>> result(matches.size());
    for (int i = 0; i < matches.size(); i++) {
        result[i] = matches[i]->generateWaveChunk(nSamples);
    }
    return result;
}

// --- standardized queries ---

Oscillator* Synthesizer::getOscillatorByName(const std::string& name) {
    for (auto& osc : oscillators) {
        if (osc.name == name) return &osc;
    }
    throw std::invalid_argument("Oscillator not found: " + name);
}

std::vector<Oscillator*> Synthesizer::getOscillatorsByNames(const std::vector<std::string>& names) {
    return getOscillatorsByField([&names](const Oscillator& o) {
        for (auto& n : names) {
            if (o.name == n) return true;
        }
        return false;
    });
}

std::vector<std::vector<float>> Synthesizer::generateSignalsByNames(const std::vector<std::string>& names, int nSamples) {
    return generateSignalsByField([&names](const Oscillator& o) {
        for (auto& n : names) {
            if (o.name == n) return true;
        }
        return false;
    }, nSamples);
}

std::vector<Oscillator*> Synthesizer::getOscillatorsByType(SIGNAL_TYPE type) {
    return getOscillatorsByField([type](const Oscillator& o) {
        return o.signalType == type;
    });
}

std::vector<Oscillator*> Synthesizer::getOscillatorsByFreqRange(float minFreq, float maxFreq) {
    return getOscillatorsByField([minFreq, maxFreq](const Oscillator& o) {
        return o.freq >= minFreq && o.freq <= maxFreq;
    });
}

std::vector<std::string> Synthesizer::getOscillatorNames() {
    return getOscillatorFields<std::string>([](const Oscillator& o) { return o.name; });
}

std::vector<float> Synthesizer::getOscillatorFreqs() {
    return getOscillatorFields<float>([](const Oscillator& o) { return o.freq; });
}

std::vector<float> Synthesizer::getOscillatorAmplitudes() {
    return getOscillatorFields<float>([](const Oscillator& o) { return o.amplitudeLin; });
}
