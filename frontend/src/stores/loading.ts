import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const SHOW_DELAY_MS = 140
const COMPLETE_HOLD_MS = 220

export const useLoadingStore = defineStore('loading', () => {
  const activeCount = ref(0)
  const visible = ref(false)
  const progress = ref(0)

  let showTimer: ReturnType<typeof setTimeout> | null = null
  let hideTimer: ReturnType<typeof setTimeout> | null = null
  let progressTimer: ReturnType<typeof setInterval> | null = null

  const loading = computed(() => activeCount.value > 0)

  function stopProgressTimer() {
    if (progressTimer) {
      clearInterval(progressTimer)
      progressTimer = null
    }
  }

  function runProgressTimer() {
    stopProgressTimer()
    progressTimer = setInterval(() => {
      // Ease towards 92% while work remains. Completion owns the final 8%.
      const remaining = 92 - progress.value
      if (remaining <= 0) return
      progress.value = Math.min(
        92,
        progress.value + Math.max(0.35, remaining * (0.045 + Math.random() * 0.035)),
      )
    }, 240)
  }

  function reveal() {
    showTimer = null
    if (activeCount.value === 0) return
    visible.value = true
    progress.value = Math.max(10, Math.min(progress.value, 28))
    runProgressTimer()
  }

  function start() {
    activeCount.value += 1

    if (hideTimer) {
      clearTimeout(hideTimer)
      hideTimer = null
    }
    if (visible.value) {
      // 已在显示中：保持当前进度单向推进。并发请求到达时若已接近完成，
      // 平滑回落到 90% 继续，而不是硬重置回 24%，避免进度条反复横跳。
      if (progress.value >= 100) progress.value = 90
      runProgressTimer()
      return
    }
    if (!showTimer) showTimer = setTimeout(reveal, SHOW_DELAY_MS)
  }

  function finish() {
    activeCount.value = Math.max(0, activeCount.value - 1)
    if (activeCount.value > 0) return

    if (showTimer) {
      clearTimeout(showTimer)
      showTimer = null
    }
    stopProgressTimer()
    if (!visible.value) {
      progress.value = 0
      return
    }

    progress.value = 100
    hideTimer = setTimeout(() => {
      visible.value = false
      progress.value = 0
      hideTimer = null
    }, COMPLETE_HOLD_MS)
  }

  return { loading, visible, progress, start, finish }
})
