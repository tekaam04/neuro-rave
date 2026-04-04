#include <vector>
#include <string>

bool isPowerOfTwo(int n);

int secondsToSamples(float seconds, int sampleRate);

float samplesToSeconds(int samples, int sampleRate);

void applyWindow(std::vector<std::vector<float>>& data, std::string windowType); 

std::vector<std::vector<float>> create2DVector(int nRows, int nCols);

void copy2DVector(std::vector<std::vector<float>>& source,
                  std::vector<std::vector<float>>& target,
                  int sourceBegin, int sourceEnd,
                  int targetBegin);

class FIFO {
public:
    int size;
    int nChannels;
    float timestamp; // timestamp of most recent sample
    bool isFull;
    
    FIFO(int size, int nChannels);
    
    FIFO(float seconds, int sampleRate, int nChannels);
    
    ~FIFO();

    virtual void addSample(std::vector<float>& sample);

    virtual void addChunk(std::vector<std::vector<float>>& chunk);

    virtual std::vector<std::vector<float>>  getData();

    std::pair<int, int> getShape();

protected:
    std::vector<std::vector<float>> data;
    int writeIdx;
    // implement later if needed
    // int readIdx;

    void validateRange(int begin, int end, int maxSize, const std::string& name);
    void copySample(std::vector<float>& sample, int dataIndex);
    void writeDataByRange(std::vector<std::vector<float>>& chunk,
                          int chunkBegin = 0, int chunkEnd = -1, int dataBegin = 0);
    void readDataByRange(std::vector<std::vector<float>>& result,
                         int dataBegin = 0, int dataEnd = -1, int resultBegin = 0);
};

class CircularFIFO : public FIFO {
public:
    CircularFIFO(int size, int nChannels);
    
    CircularFIFO(float seconds, int sampleRate, int nChannels);

    ~CircularFIFO();

    void addSample(std::vector<float>& sample);

    void addChunk(std::vector<std::vector<float>>& chunk);

    std::vector<std::vector<float>> getData();
};


class MirrorCircularFIFO : public FIFO {
public:
    
    MirrorCircularFIFO(int size, int nChannels);
    
    MirrorCircularFIFO(float seconds, int sampleRate, int nChannels);

    ~MirrorCircularFIFO();

    void addSample(std::vector<float>& sample);

    void addChunk(std::vector<std::vector<float>>& chunk);

    std::vector<std::vector<float>> getData();
};