#include "audio_writer.h"

AudioWriter::AudioWriter(int sampleRate, ma_format format, MultiSignalFIFO<MirrorCircularFIFO>* fifo) {
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

void AudioWriter::dataCallback(ma_device* pDevice, void* pOutput, const void* /*pInput*/, ma_uint32 frameCount) {
    auto* fifo = static_cast<MultiSignalFIFO<MirrorCircularFIFO>*>(pDevice->pUserData);
    fifo->readNSamplesInterleaved(static_cast<float*>(pOutput), static_cast<int>(frameCount));
}