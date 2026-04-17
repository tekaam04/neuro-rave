#pragma once

#include <functional>
#include <thread>
#include <atomic>
#include <chrono>
#include <string>
#include <vector>
#include "fifo.h"
#include "overlap_add.h"
#include "channel_array.h"

template<typename InFifo, typename OutFifo = MirrorCircularFIFOTS>
class BlockProcessor {
public:
    using ProcessFn = std::function<void(const ChannelArrayConstView& in,
                                         const ChannelArrayView& out)>;

    BlockProcessor(MultiSignal<InFifo>* inFifo,
                   MultiSignal<OutFifo>* outFifo,
                   int blockSize, int hopSize,
                   const std::string& windowType,
                   ProcessFn processFn)
        : reader(inFifo, blockSize, hopSize),
          ola(inFifo->nChannels, blockSize, hopSize),
          inBlock(inFifo->nChannels, blockSize),
          outBlock(inFifo->nChannels, blockSize),
          hopOut(inFifo->nChannels, hopSize),
          windowCoeffs(blockSize),
          outFifo(outFifo),
          processFn(std::move(processFn)) {
        if (windowType == "hann") {
            generateHannWindow(windowCoeffs);
        } else if (windowType == "hamming") {
            generateHammingWindow(windowCoeffs);
        }
        // "rectangular" leaves coeffs as default (unused — readBlock skips multiply)
    }

    ~BlockProcessor() {
        stop();
    }

    void start() {
        running.store(true, std::memory_order_relaxed);
        worker = std::thread(&BlockProcessor::runLoop, this);
    }

    void stop() {
        running.store(false, std::memory_order_relaxed);
        if (worker.joinable()) {
            worker.join();
        }
    }

private:
    void runLoop() {
        while (running.load(std::memory_order_relaxed)) {
            if (reader.poll()) {
                reader.readBlock(inBlock.view(), windowCoeffs);
                processFn(inBlock.view(), outBlock.view());
                ola.addBlock(outBlock.view());
                ola.popHop(hopOut.view());
                outFifo->addChunk(hopOut.view());
            } else {
                std::this_thread::sleep_for(std::chrono::microseconds(200));
            }
        }
    }

    BlockReader<InFifo> reader;
    OverlapAddBuffer ola;
    ChannelArrayBuffer inBlock;
    ChannelArrayBuffer outBlock;
    ChannelArrayBuffer hopOut;
    std::vector<float> windowCoeffs;
    MultiSignal<OutFifo>* outFifo;
    ProcessFn processFn;
    std::atomic<bool> running{false};
    std::thread worker;
};
