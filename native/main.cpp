#include <optional>
#include <utility>
#include <vector>

#include "audio_writer.h"
#include "channel_array.h"
#include "config.h"
#include "fifo.h"
#include "filter.h"
#include "signal_gen.h"
#include "ws_server.h"
#include "lsl_bridge.h"

int main(int argc, char* argv[]) {
    NeuroRaveConfig config = config_load("config/constants.json");

    MultiSignalFIFO<MirrorCircularFIFO> rawFIFO(config.window_size, config.n_channels);
    AudioWriter audioWriter(config.sample_rate, ma_format_f32, &rawFIFO);

    // Pre-allocated planar scratch shared by both branches: simulate fills it
    // directly via generateSignalsChunk; live mode transposes the LSL chunk
    // into it. Sized once at setup, no allocations on the loop.
    ChannelArrayBuffer chunkBuffer(config.n_channels, config.window_size);

    // Producer-side state. Exactly one branch populates these. std::optional
    // gives us value semantics with deferred construction (none of these
    // classes are default-constructible) and avoids any heap allocation.
    //
    // Declaration order matters: LSLBridge holds references to tcp, decoder,
    // and publisher, so it must be declared *after* them so it is destroyed
    // *before* them.
    std::optional<Synthesizer>         synth;
    std::optional<TCPSource>           tcp;
    std::optional<BioSemi24BitDecoder> decoder;
    std::optional<LSLPublisher>        publisher;
    std::optional<LSLBridge>           bridge;
    std::optional<LSLConsumer>         consumer;
    std::optional<EEGWebSocketServer>  ws_server;

    if (config.simulate == 1) {
        std::vector<Oscillator> oscillators(
            config.n_channels, Oscillator(config.sample_rate));
        synth.emplace(std::move(oscillators), config.sample_rate, 0.5f);
    } else {
        tcp.emplace(config.biosemi_host, config.biosemi_port);
        decoder.emplace(config.n_channels);
        publisher.emplace("BioSemiEEG", "EEG",
                          config.n_channels, config.sample_rate,
                          "biosemi_tcp_bridge");
        bridge.emplace(*tcp, *decoder, *publisher);
        bridge->start();

        consumer.emplace("EEG");
        ws_server.emplace(config.ws_host, config.ws_port);
        ws_server->start();
    }

    audioWriter.play();

    while (true) {
        ChannelArrayView view = chunkBuffer.view();

        if (config.simulate) {
            synth->generateSignalsChunk(view);
            rawFIFO.addChunk(view);
        } else {
            std::pair<std::vector<double>, std::vector<std::vector<float>>> chunk =
                consumer->get_chunk(config.window_size);
            const std::vector<std::vector<float>>& samples = chunk.second;
            int nFrames = static_cast<int>(samples.size());

            for (int ch = 0; ch < config.n_channels; ch++) {
                std::span<float> channelOut = view.channel(ch);
                for (int f = 0; f < nFrames; f++) {
                    channelOut[f] = samples[f][ch];
                }
            }

            ChannelArrayView populated(view.data(), config.n_channels, nFrames);
            rawFIFO.addChunk(populated);
        }
    }
}
