#include <vector>
#include <string>
#include "fifo.h"

class BaseFilter {
public:
    BaseFilter(std::vector<float> coeffs);

    virtual void applyFilter(std::vector<std::vector<float>>& buffer);
    

protected:
    std::vector<float> coeffs;

    flpoapply

};


class BasicFIRFilter : public BaseFilter {
public:
    BasicFIRFilter(std::vector<float> coeffs);

    std::vector<float> applyFilter(std::vector<std::vector<float>>& buffer);
};