#pragma once

#include <vector>
#include <string>
#include <functional>
#include "fifo.h"
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

class Oscillator {
public:
    Oscillator(float sampleRate, float freq = 440.f, float amplitudeLin = 0.5, float phase = 0.f, SIGNAL_TYPE signalType=SINE, std::string name = "");
    float sampleRate;
    float freq;
    float phase;
    float amplitudeLin;
    SIGNAL_TYPE signalType;
    std::string name;

    float generateWaveSample();
    std::vector<float> generateWaveChunk(int nSamples);
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

// handles multiple oscillators
class Synthesizer {
public:
    std::vector<Oscillator> oscillators;
    float amplitudeLin;
    float sampleRate;

    Synthesizer(float sampleRate, float amplitudeLin);
    Synthesizer(std::vector<Oscillator> oscillators, float sampleRate, float amplitudeLin);

    void addOscillator(Oscillator oscillator);


    std::vector<float> generateSignalsSample();
    std::vector<std::vector<float>> generateSignalsChunk(int nSamples);

    // gets weighted average of all signals
    float generateCombinedSample(bool weightOscEqually=false);
    std::vector<float> generateCombinedChunk(int nSamples, bool weightOscEqually=false);

    int getNumberOscillators();

    // helpers — predicate-based filtering
    std::vector<Oscillator*> getOscillatorsByField(std::function<bool(const Oscillator&)> predicate);
    std::vector<int> getOscillatorIdxByField(std::function<bool(const Oscillator&)> predicate);

    // field extraction
    template<typename T>
    std::vector<T> getOscillatorFields(std::function<T(const Oscillator&)> getter) {
        std::vector<T> result(oscillators.size());
        for (int i = 0; i < oscillators.size(); i++) {
            result[i] = getter(oscillators[i]);
        }
        return result;
    }

    // convenience: generate signals for oscillators matching a predicate
    std::vector<std::vector<float>> generateSignalsByField(std::function<bool(const Oscillator&)> predicate, int nSamples);

    // --- standardized field queries ---

    // by name
    Oscillator* getOscillatorByName(const std::string& name);
    std::vector<Oscillator*> getOscillatorsByNames(const std::vector<std::string>& names);
    std::vector<std::vector<float>> generateSignalsByNames(const std::vector<std::string>& names, int nSamples);

    // by signal type
    std::vector<Oscillator*> getOscillatorsByType(SIGNAL_TYPE type);

    // by frequency range
    std::vector<Oscillator*> getOscillatorsByFreqRange(float minFreq, float maxFreq);

    // field getters
    std::vector<std::string> getOscillatorNames();
    std::vector<float> getOscillatorFreqs();
    std::vector<float> getOscillatorAmplitudes();
};

float getWeightedAverage(std::vector<float> numbers);