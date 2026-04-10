#pragma once

#include <vector>
#include <span>
#include <string>
#include <functional>
#include "fifo.h"
#include "channel_array.h"
#include <stdexcept>

enum SIGNAL_TYPE {
    SINE,
    SQUARE,
    SAW,
    TRIANGLE,
    WHITE_NOISE,
    PINK_NOISE
};

float dbToLinear(float amplitudeDB);

float linearToDB(float amplitudeLin);

void normalizeNumbers(std::span<const float> in,
                      std::span<float> out);

float getWeightedAverage(std::span<const float> values,
                         std::span<const float> weights);

class Oscillator {
public:
    Oscillator(float sampleRate, float freq = 440.f, float amplitudeLin = 0.5, float phase = 0.f, SIGNAL_TYPE signalType = SINE, const std::string& name = "");
    float sampleRate;
    float freq;
    float phase;
    float amplitudeLin;
    SIGNAL_TYPE signalType;
    std::string name;

    float generateWaveSample();
    void generateWaveChunk(std::span<float> out);

protected:
    float generateSine();
    float generateSquare();
    float generateSaw();
    float generateTriangle();
    float generateWhiteNoise();
    float generatePinkNoise();

private:
    using GeneratorFunc = float (Oscillator::*)();
    static constexpr GeneratorFunc generators[] = {
        &Oscillator::generateSine,
        &Oscillator::generateSquare,
        &Oscillator::generateSaw,
        &Oscillator::generateTriangle,
        &Oscillator::generateWhiteNoise,
        &Oscillator::generatePinkNoise,
    };
    void updatePhase();
};

// Handles multiple oscillators.
class Synthesizer {
public:
    std::vector<Oscillator> oscillators;
    float amplitudeLin;
    float sampleRate;

    Synthesizer(float sampleRate, float amplitudeLin);
    Synthesizer(const std::vector<Oscillator>& oscillators, float sampleRate, float amplitudeLin);
    Synthesizer(std::vector<Oscillator>&& oscillators, float sampleRate, float amplitudeLin);

    void addOscillator(const Oscillator& oscillator);
    void addOscillator(Oscillator&& oscillator);

    template<typename... Args>
    Oscillator& emplaceOscillator(Args&&... args) {
        Oscillator& osc = oscillators.emplace_back(std::forward<Args>(args)...);
        invalidateCache();
        return osc;
    }

    // Hot-path generators — caller provides the output storage.
    void generateSignalsSample(std::span<float> out);                // out.size() == nOsc
    void generateSignalsChunk(const ChannelArrayView& out);                 // one channel per oscillator

    // Weighted average across oscillators.
    float generateCombinedSample(bool weightOscEqually = false);
    void generateCombinedChunk(std::span<float> out, bool weightOscEqually = false);

    int getNumberOscillators();

    // Predicate-based filtering. Caller provides reusable output vectors.
    void getOscillatorsByField(const std::function<bool(const Oscillator&)>& predicate,
                               std::vector<Oscillator*>& out);
    void getOscillatorIdxByField(const std::function<bool(const Oscillator&)>& predicate,
                                 std::vector<int>& out);

    // Field extraction — caller-provided output span.
    template<typename T>
    void getOscillatorFields(const std::function<T(const Oscillator&)>& getter,
                             std::span<T> out) {
        for (size_t i = 0; i < oscillators.size(); i++) {
            out[i] = getter(oscillators[i]);
        }
    }

    // Generate one channel per matching oscillator into the provided view.
    // Caller is responsible for sizing the view to match the number of matches.
    void generateSignalsByField(const std::function<bool(const Oscillator&)>& predicate,
                                const ChannelArrayView& out);

    // --- standardized field queries ---

    Oscillator* getOscillatorByName(const std::string& name);
    void getOscillatorsByNames(const std::vector<std::string>& names,
                               std::vector<Oscillator*>& out);

    void getOscillatorsByType(SIGNAL_TYPE type, std::vector<Oscillator*>& out);

    void getOscillatorsByFreqRange(float minFreq, float maxFreq,
                                   std::vector<Oscillator*>& out);

    // Cached field getters — return const refs to internal cache (no copy).
    const std::vector<std::string>& getOscillatorNames();
    const std::vector<float>& getOscillatorFreqs();
    const std::vector<float>& getOscillatorAmplitudes();
    const std::vector<float>& getNormalizedAmplitudes();

    // Call after modifying oscillator fields directly.
    void invalidateCache();

private:
    bool cacheDirty = true;
    int cachedNumOscillators = 0;
    std::vector<std::string> cachedNames;
    std::vector<float> cachedFreqs;
    std::vector<float> cachedAmplitudes;
    std::vector<float> cachedNormalizedAmps;

    void rebuildCache();
};
