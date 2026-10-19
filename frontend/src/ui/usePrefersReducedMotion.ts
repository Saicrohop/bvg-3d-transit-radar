import { useSyncExternalStore } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribe(notify: () => void) {
  const media = window.matchMedia?.(QUERY)
  media?.addEventListener('change', notify)
  return () => media?.removeEventListener('change', notify)
}

function getPreference() {
  return window.matchMedia?.(QUERY).matches ?? false
}

export function usePrefersReducedMotion() {
  return useSyncExternalStore(subscribe, getPreference, () => false)
}
