/**
 * Shared signal processing constants.
 * Single source of truth is config/constants.json at the project root.
 * Python reads the same file via src/constants.py.
 */
import constants from '@config/constants.json'

export const N_CHANNELS:  number = constants.N_CHANNELS
export const SAMPLE_RATE: number = constants.SAMPLE_RATE
export const WINDOW_SIZE: number = constants.WINDOW_SIZE
