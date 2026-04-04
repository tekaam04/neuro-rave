#include <vector>
#include <string>
#include <stdexcept>
#include "fifo.h"
#include "filter.h"


BaseFilter::BaseFilter(std::vector<float> coeffs) : coeffs(coeffs) {}

BasicFIRFilter::BasicFIRFilter(std::vector<float> coeffs) : BaseFilter(coeffs) {}

std::vector<float> BasicFIRFilter::applyFilter(std::vector<std::vector<float>>& buffer) {
    if (buffer[0].size() < coeffs.size()) {
        throw std::invalid_argument(
            "Buffer size is too small (" + std::to_string(buffer.size()() +
            ") compared to number of coefficients in filter(" + std::to_string(coeffs.size()) + ")");
    }

    std::vector<float> filteredSample = std::vector<float>(buffer.size());

    for (int i = 0; i < this->coeffs.size(); i++) {
        int bufferIdx = buffer.size() - i;
        filteredSample += this->coeffs[i] * buffer[bufferIdx];
    }
}
