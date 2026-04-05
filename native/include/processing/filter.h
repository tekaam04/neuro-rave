#pragma once

#include <vector>
#include <string>
#include "fifo.h"

class BaseFilter {
public:
    BaseFilter(float sampleRate, float freq = 0.f, float q = 0.707f);
    virtual ~BaseFilter() = default;

    virtual float applyFilter(std::vector<float>& buffer) = 0;

    void setFreq(float freq);
    void setQ(float q);
    float getFreq();
    float getQ();

protected:
    static float getWeightedSum(std::vector<float>& coeffs, std::vector<float>& buffer);
    virtual void calculateCoefficients() = 0;

    float sampleRate;
    float freq;
    float q;
};

class BasicFIRFilter : public BaseFilter {
public:
    BasicFIRFilter(float sampleRate, std::vector<float>& preCoeffs);

    float applyFilter(std::vector<float>& buffer) override;

protected:
    void calculateCoefficients() override;
    std::vector<float> preCoeffs;
};

class BiquadIIRFilter : public BaseFilter {
public:
    BiquadIIRFilter(float sampleRate, float freq, float q = 0.707f);

    float applyFilter(std::vector<float>& buffer) override;

protected:
    void calculateCoefficients() override;
    std::vector<float> preCoeffs;
    std::vector<float> postCoeffs;
    MirrorCircularFIFO outputHistory;
};
