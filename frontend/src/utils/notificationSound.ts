/**
 * Web Audio API notification chime — no external files needed.
 * Two tones: a gentle "pop" for chat messages, a "ding" for system alerts.
 */

let audioCtx: AudioContext | null = null

function ctx(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext()
  // Resume if suspended (browsers require user gesture first)
  if (audioCtx.state === 'suspended') void audioCtx.resume()
  return audioCtx
}

/** Short gentle pop — chat message received. */
export function playChatPop() {
  try {
    const c = ctx()
    const now = c.currentTime

    // Carrier: brief sine blip
    const osc = c.createOscillator()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(800, now)
    osc.frequency.exponentialRampToValueAtTime(1200, now + 0.04)
    osc.frequency.exponentialRampToValueAtTime(600, now + 0.12)

    const gain = c.createGain()
    gain.gain.setValueAtTime(0, now)
    gain.gain.linearRampToValueAtTime(0.12, now + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.14)

    osc.connect(gain).connect(c.destination)
    osc.start(now)
    osc.stop(now + 0.15)
  } catch {
    // Audio not available — silently skip
  }
}

/** Brighter two-tone ding — system / task notification. */
export function playSystemDing() {
  try {
    const c = ctx()
    const now = c.currentTime

    // First tone
    const osc1 = c.createOscillator()
    osc1.type = 'sine'
    osc1.frequency.setValueAtTime(880, now)
    osc1.frequency.exponentialRampToValueAtTime(1100, now + 0.06)

    const gain1 = c.createGain()
    gain1.gain.setValueAtTime(0, now)
    gain1.gain.linearRampToValueAtTime(0.1, now + 0.01)
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.1)

    osc1.connect(gain1).connect(c.destination)
    osc1.start(now)
    osc1.stop(now + 0.1)

    // Second tone (slightly delayed, higher)
    const osc2 = c.createOscillator()
    osc2.type = 'sine'
    osc2.frequency.setValueAtTime(1100, now + 0.08)
    osc2.frequency.exponentialRampToValueAtTime(1400, now + 0.14)

    const gain2 = c.createGain()
    gain2.gain.setValueAtTime(0, now + 0.08)
    gain2.gain.linearRampToValueAtTime(0.1, now + 0.09)
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.2)

    osc2.connect(gain2).connect(c.destination)
    osc2.start(now + 0.08)
    osc2.stop(now + 0.2)
  } catch {
    // Audio not available — silently skip
  }
}
