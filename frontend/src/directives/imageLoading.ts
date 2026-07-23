import type { Directive } from 'vue'

type LoadingImage = HTMLImageElement & {
  __imageLoadingCleanup?: () => void
}

function watchImage(element: LoadingImage) {
  element.__imageLoadingCleanup?.()

  const finish = () => {
    element.removeEventListener('load', finish)
    element.removeEventListener('error', finish)
    element.classList.remove('is-image-loading')
  }

  element.__imageLoadingCleanup = finish

  if (element.complete) {
    finish()
    return
  }

  element.classList.add('is-image-loading')
  element.addEventListener('load', finish, { once: true })
  element.addEventListener('error', finish, { once: true })
}

export const imageLoadingDirective: Directive<LoadingImage, string | undefined> = {
  mounted(element) {
    watchImage(element)
  },
  updated(element, binding) {
    if (binding.value !== binding.oldValue) {
      watchImage(element)
    }
  },
  beforeUnmount(element) {
    element.__imageLoadingCleanup?.()
    delete element.__imageLoadingCleanup
  },
}
