#include "audio_writer.h"

AudioWriter::AudioWriter(int sampleRate, ma_format format, MultiSignalFIFO<CircularFIFO>* fifo) {
    config = ma_device_config_init(ma_device_type_playback);
    config.playback.format   = format;
    config.playback.channels = fifo->nChannels;
    config.sampleRate        = sampleRate;
    config.dataCallback      = AudioWriter::dataCallback;
    config.pUserData         = fifo;

    ma_device_init(NULL, &config, &device);
}

AudioWriter::~AudioWriter() {
    ma_device_uninit(&device);
}

void AudioWriter::dataCallback(ma_device* pDevice, void* pOutput, const void* pInput, ma_uint32 frameCount) {
    auto* fifo = static_cast<MultiSignalFIFO<CircularFIFO>*>(pDevice->pUserData);
    float* out = static_cast<float*>(pOutput);

    int nChannels = fifo->nChannels;
    auto samples = fifo->getNSamples(frameCount);

    for (ma_uint32 frame = 0; frame < frameCount; frame++) {
        for (int ch = 0; ch < nChannels; ch++) {
            out[frame * nChannels + ch] = samples[ch][frame];
        }
    }
}