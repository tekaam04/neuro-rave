#pragma once

#include "miniaudio.h"
#include "fifo.h"

class AudioWriter {
public:
    AudioWriter(int sampleRate, ma_format format, MultiSignalFIFO<CircularFIFO>* fifo);
    ~AudioWriter();

    void play()  { ma_device_start(&device); }
    void stop()  { ma_device_stop(&device); }

private:
    ma_device_config config;
    ma_device device;

    static void dataCallback(ma_device* pDevice, void* pOutput, const void* pInput, ma_uint32 frameCount);
};

