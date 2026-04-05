#pragma once

#include <vector>
#include <string>
#include "fifo.h"

class BaseFilter {
public:
    BaseFilter(float sampleRate, float freq = 0.f, float q = 0.707f);
    virtual ~BaseFilter() = default;

    virtual float applyFilter(std::vector<float>& buffer) = 0;
    virtual std::vector<float> applyFilterChunk(std::vector<float>& buffer);

    void setFreq(float freq);
    void setQ(float q);
    float getFreq();
    float getQ();

protected:
    static float getWeightedSum(std::vector<float>& coeffs, std::vector<float>& buffer);
    virtual void calculateCoefficients() = 0;
    virtual void calculateFreqAndQ() = 0;

    float sampleRate;
    float freq;
    float q;
};

class FIRFilter : public BaseFilter {
public:
    FIRFilter(float sampleRate, float freq, float q = 0.707f);
    FIRFilter(float sampleRate, std::vector<float> preCoeffs);

    float applyFilter(std::vector<float>& buffer) override = 0;

protected:
    void calculateCoefficients() override = 0;
    void calculateFreqAndQ() override = 0;
    std::vector<float> preCoeffs;
};

class BasicFIRFilter : public FIRFilter {
public:
    BasicFIRFilter(float sampleRate, float freq, float q = 0.707f);
    BasicFIRFilter(float sampleRate, std::vector<float> preCoeffs);

    float applyFilter(std::vector<float>& buffer) override;

protected:
    void calculateCoefficients() override;
    void calculateFreqAndQ() override;
};

class IIRFilter : public BaseFilter {
public:
    IIRFilter(float sampleRate, float freq, float q = 0.707f);
    IIRFilter(float sampleRate, std::vector<float> preCoeffs, std::vector<float> postCoeffs);

    float applyFilter(std::vector<float>& buffer) override = 0;

protected:
    void calculateCoefficients() override = 0;
    void calculateFreqAndQ() override = 0;
    std::vector<float> preCoeffs;
    std::vector<float> postCoeffs;
    MirrorCircularFIFO outputHistory;
};

class BiquadIIRLowPassFilter : public IIRFilter {
public:
    BiquadIIRLowPassFilter(float sampleRate, float freq, float q = 0.707f);
    BiquadIIRLowPassFilter(float sampleRate, std::vector<float> preCoeffs, std::vector<float> postCoeffs);

    float applyFilter(std::vector<float>& buffer) override;

protected:
    void calculateCoefficients() override;
    void calculateFreqAndQ() override;
};
