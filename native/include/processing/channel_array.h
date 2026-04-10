#pragma once

#include <span>
#include <vector>
#include <cstddef>

// Non-owning planar multi-channel view over float audio data.
// Lifetime is the caller's problem (just like std::span).
// Cheap to copy, safe to pass by value.
class ChannelArrayView {
public:
    ChannelArrayView(float* const* channels, int numChannels, int numFrames)
        : chans(channels), nChans(numChannels), nFrames(numFrames) {}

    int numChannels() const { return nChans; }
    int numFrames()   const { return nFrames; }

    std::span<float> channel(int ch) const {
        return {chans[ch], static_cast<size_t>(nFrames)};
    }

    float* const* data() const { return chans; }

private:
    float* const* chans;
    int nChans;
    int nFrames;
};

// Read-only counterpart. Separate type so const-correctness is enforced
// at the type level — you cannot accidentally write through it.
class ChannelArrayConstView {
public:
    ChannelArrayConstView(const float* const* channels, int numChannels, int numFrames)
        : chans(channels), nChans(numChannels), nFrames(numFrames) {}

    // Implicit promotion from a writable view.
    ChannelArrayConstView(const ChannelArrayView& v)
        : chans(reinterpret_cast<const float* const*>(v.data())),
          nChans(v.numChannels()),
          nFrames(v.numFrames()) {}

    int numChannels() const { return nChans; }
    int numFrames()   const { return nFrames; }

    std::span<const float> channel(int ch) const {
        return {chans[ch], static_cast<size_t>(nFrames)};
    }

    const float* const* data() const { return chans; }

private:
    const float* const* chans;
    int nChans;
    int nFrames;
};

// Owning planar multi-channel buffer. Allocates ONCE at construction
// (or via resize, which is a non-real-time operation). Hands out views
// into its storage for use on hot paths.
class ChannelArrayBuffer {
public:
    ChannelArrayBuffer(int numChannels, int numFrames)
        : storage(numChannels, std::vector<float>(numFrames, 0.f)),
          ptrs(numChannels),
          constPtrs(numChannels) {
        rebuildPtrs();
    }

    // Setup-time only — do not call from a real-time thread.
    void resize(int numChannels, int numFrames) {
        storage.assign(numChannels, std::vector<float>(numFrames, 0.f));
        ptrs.resize(numChannels);
        constPtrs.resize(numChannels);
        rebuildPtrs();
    }

    int numChannels() const { return static_cast<int>(storage.size()); }
    int numFrames()   const { return storage.empty() ? 0 : static_cast<int>(storage[0].size()); }

    ChannelArrayView view() {
        return {ptrs.data(), numChannels(), numFrames()};
    }

    ChannelArrayConstView view() const {
        return {constPtrs.data(), numChannels(), numFrames()};
    }

private:
    std::vector<std::vector<float>> storage;
    std::vector<float*> ptrs;
    std::vector<const float*> constPtrs;

    void rebuildPtrs() {
        for (int i = 0; i < static_cast<int>(storage.size()); i++) {
            ptrs[i]      = storage[i].data();
            constPtrs[i] = storage[i].data();
        }
    }
};
