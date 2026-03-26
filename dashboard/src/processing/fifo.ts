import { WINDOW_SIZE, N_CHANNELS } from '../constants'

function isPowerOfTwo(n: number): boolean {
    return n !== 0 && (n & (n - 1)) === 0
}

/** Numeric typed array types — constrain T to one of these. */
export type NumericArray =
    | Int8Array
    | Int16Array
    | Int32Array
    | Uint8Array
    | Uint16Array
    | Uint32Array
    | Float32Array
    | Float64Array

/**
 * Data layout (channel-major):
 *   data[channel]  →  T  (a typed array of sample values)
 *
 * Chunk input (sample-major, matches how samples arrive):
 *   chunk[sample_index][channel]
 */
abstract class FIFO<T extends NumericArray> {
    readonly size:        number
    readonly numChannels: number
    isFull:               boolean
    protected data:       T[]    // [channel] → typed array of samples
    protected index:      number

    constructor(size: number = WINDOW_SIZE, numChannels: number = N_CHANNELS) {
        this.size        = size
        this.numChannels = numChannels
        this.isFull      = false
        this.data        = this.instData()
        this.index       = 0
    }

    /** Allocate the underlying channel arrays. */
    protected abstract instData(): T[]

    abstract addSample(sample: ArrayLike<number>): void
    abstract addChunk(chunk: ArrayLike<number>[]): void

    /** Return chronologically ordered data as plain number[][] for easy consumption. */
    getData(): number[][] {
        if (!this.isFull) {
            return this.data.map(ch => Array.from(ch).slice(0, this.index))
        }
        return this.data.map(ch => {
            const arr = Array.from(ch)
            return [...arr.slice(this.index), ...arr.slice(0, this.index)]
        })
    }

    get length(): number {
        return this.isFull ? this.size : this.index
    }

    /** Write one sample across all channels at a given index. */
    protected writeAt(sample: ArrayLike<number>, idx: number): void {
        for (let ch = 0; ch < this.numChannels; ch++) {
            (this.data[ch] as unknown as number[])[idx] = sample[ch]
        }
    }
}


abstract class CircularFIFO<T extends NumericArray> extends FIFO<T> {

    constructor(size: number = WINDOW_SIZE, numChannels: number = N_CHANNELS) {
        if (!isPowerOfTwo(size))
            console.warn('Buffer size should be a power of 2 for optimal FFT performance.')
        super(size, numChannels)
    }

    addSample(sample: ArrayLike<number>): void {
        if (sample.length !== this.numChannels)
            throw new RangeError(`Sample must have ${this.numChannels} channels, got ${sample.length}`)
        this.writeAt(sample, this.index)
        this.index = (this.index + 1) % this.size
        if (this.index === 0) this.isFull = true
    }

    addChunk(chunk: ArrayLike<number>[]): void {
        const n = chunk.length

        if (n >= this.size) {
            const tail = chunk.slice(-this.size)
            for (let i = 0; i < this.size; i++) this.writeAt(tail[i], i)
            this.index  = 0
            this.isFull = true
            return
        }

        const end = this.index + n
        if (end <= this.size) {
            for (let i = 0; i < n; i++) this.writeAt(chunk[i], this.index + i)
        } else {
            const first = this.size - this.index
            for (let i = 0; i < first; i++)     this.writeAt(chunk[i],       this.index + i)
            for (let i = 0; i < n - first; i++) this.writeAt(chunk[first + i], i)
        }

        this.index = end % this.size
        if (end >= this.size) this.isFull = true
    }
}


export abstract class MirrorCircleFIFO<T extends NumericArray> extends FIFO<T> {
    /**
     * Each channel array is size * 2.
     * Every write goes to both index and index + size, so getData() is always
     * a single contiguous slice — O(1) with no concatenation.
     */

    constructor(size: number = WINDOW_SIZE, numChannels: number = N_CHANNELS) {
        if (!isPowerOfTwo(size))
            console.warn('Buffer size should be a power of 2 for optimal FFT performance.')
        super(size, numChannels)
    }

    private mirrorWriteAt(sample: ArrayLike<number>, idx: number): void {
        this.writeAt(sample, idx)
        this.writeAt(sample, idx + this.size)
    }

    addSample(sample: ArrayLike<number>): void {
        if (sample.length !== this.numChannels)
            throw new RangeError(`Sample must have ${this.numChannels} channels, got ${sample.length}`)
        this.mirrorWriteAt(sample, this.index)
        this.index = (this.index + 1) % this.size
        if (this.index === 0) this.isFull = true
    }

    addChunk(chunk: ArrayLike<number>[]): void {
        const n = chunk.length

        if (n >= this.size) {
            const tail = chunk.slice(-this.size)
            for (let i = 0; i < this.size; i++) this.mirrorWriteAt(tail[i], i)
            this.index  = 0
            this.isFull = true
            return
        }

        const end   = this.index + n
        const first = Math.min(n, this.size - this.index)

        for (let i = 0; i < first; i++) this.mirrorWriteAt(chunk[i], this.index + i)
        for (let i = first; i < n; i++) this.mirrorWriteAt(chunk[i], i - first)

        this.index = end % this.size
        if (end >= this.size) this.isFull = true
    }

    override getData(): number[][] {
        if (!this.isFull) {
            return this.data.map(ch => Array.from(ch).slice(0, this.index))
        }
        // O(1): mirror writes guarantee this slice is always chronological
        return this.data.map(ch => Array.from(ch).slice(this.index, this.index + this.size))
    }
}


// ── Circular ──────────────────────────────────────────────────────────────────

export class Int8CircularFIFO extends CircularFIFO<Int8Array> {
    protected instData(): Int8Array[] {
        return Array.from({ length: this.numChannels }, () => new Int8Array(this.size))
    }
}
export class Int16CircularFIFO extends CircularFIFO<Int16Array> {
    protected instData(): Int16Array[] {
        return Array.from({ length: this.numChannels }, () => new Int16Array(this.size))
    }
}
export class Int32CircularFIFO extends CircularFIFO<Int32Array> {
    protected instData(): Int32Array[] {
        return Array.from({ length: this.numChannels }, () => new Int32Array(this.size))
    }
}
export class Uint8CircularFIFO extends CircularFIFO<Uint8Array> {
    protected instData(): Uint8Array[] {
        return Array.from({ length: this.numChannels }, () => new Uint8Array(this.size))
    }
}
export class Uint16CircularFIFO extends CircularFIFO<Uint16Array> {
    protected instData(): Uint16Array[] {
        return Array.from({ length: this.numChannels }, () => new Uint16Array(this.size))
    }
}
export class Uint32CircularFIFO extends CircularFIFO<Uint32Array> {
    protected instData(): Uint32Array[] {
        return Array.from({ length: this.numChannels }, () => new Uint32Array(this.size))
    }
}
export class Float32CircularFIFO extends CircularFIFO<Float32Array> {
    protected instData(): Float32Array[] {
        return Array.from({ length: this.numChannels }, () => new Float32Array(this.size))
    }
}
export class Float64CircularFIFO extends CircularFIFO<Float64Array> {
    protected instData(): Float64Array[] {
        return Array.from({ length: this.numChannels }, () => new Float64Array(this.size))
    }
}

// ── Mirror circular ───────────────────────────────────────────────────────────

export class Int8MirrorCircleFIFO extends MirrorCircleFIFO<Int8Array> {
    protected instData(): Int8Array[] {
        return Array.from({ length: this.numChannels }, () => new Int8Array(this.size * 2))
    }
}
export class Int16MirrorCircleFIFO extends MirrorCircleFIFO<Int16Array> {
    protected instData(): Int16Array[] {
        return Array.from({ length: this.numChannels }, () => new Int16Array(this.size * 2))
    }
}
export class Int32MirrorCircleFIFO extends MirrorCircleFIFO<Int32Array> {
    protected instData(): Int32Array[] {
        return Array.from({ length: this.numChannels }, () => new Int32Array(this.size * 2))
    }
}
export class Uint8MirrorCircleFIFO extends MirrorCircleFIFO<Uint8Array> {
    protected instData(): Uint8Array[] {
        return Array.from({ length: this.numChannels }, () => new Uint8Array(this.size * 2))
    }
}
export class Uint16MirrorCircleFIFO extends MirrorCircleFIFO<Uint16Array> {
    protected instData(): Uint16Array[] {
        return Array.from({ length: this.numChannels }, () => new Uint16Array(this.size * 2))
    }
}
export class Uint32MirrorCircleFIFO extends MirrorCircleFIFO<Uint32Array> {
    protected instData(): Uint32Array[] {
        return Array.from({ length: this.numChannels }, () => new Uint32Array(this.size * 2))
    }
}
export class Float32MirrorCircleFIFO extends MirrorCircleFIFO<Float32Array> {
    protected instData(): Float32Array[] {
        return Array.from({ length: this.numChannels }, () => new Float32Array(this.size * 2))
    }
}
export class Float64MirrorCircleFIFO extends MirrorCircleFIFO<Float64Array> {
    protected instData(): Float64Array[] {
        return Array.from({ length: this.numChannels }, () => new Float64Array(this.size * 2))
    }
}


// ── Buffer types ──────────────────────────────────────────────────────────────

export interface EEGBuffer {
    channels:  Float32Array[]
    timestamp: number
}

export interface UseEEGStreamResult {
    buffer:    EEGBuffer | null
    connected: boolean
}
