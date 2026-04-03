#include <vector>
#include <string>

bool isPowerOfTwo(int n);

int secondsToSamples(float seconds, int sampleRate);

float samplesToSeconds(int samples, int sampleRate);

void applyWindow(std::vector<std::vector<float>>& data, std::string windowType); 

std::vector<std::vector<float>> create2DVector(int nRows, int nCols);

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

protected:
    std::vector<std::vector<float>> data;
    int index;

    void validateRange(int begin, int end, int maxSize, const std::string& name);
    void copySample(std::vector<float>& sample, int dataIndex);
    void copyChunkRange(std::vector<std::vector<float>>& chunk,
                        int chunkBegin = 0, int chunkEnd = -1, int dataBegin = 0);
};

class CircularFIFO : public FIFO {
public:
    CircularFIFO(int size, int nChannels);
    
    CircularFIFO(float seconds, int sampleRate, int nChannels);

    ~CircularFIFO();

    void addSample(std::vector<float>& sample);

    void addChunk(std::vector<std::vector<float>>& chunk);

    std::vector<std::vector<float>> getData();

    std::vector<int> getShape();
};


class MirrorCircularFIFO : public FIFO {
public:
    bool isFull;
    
    MirrorCircularFIFO(int size, int nChannels);
    
    MirrorCircularFIFO(float seconds, int sampleRate, int nChannels);

    ~MirrorCircularFIFO();

    void addSample(std::vector<float>& sample);

    void addChunk(std::vector<std::vector<float>>& chunk);

    std::vector<std::vector<float>> getData();

    std::vector<int> getShape();

};