import { useEffect, useState, useSyncExternalStore } from 'react'

function subscribe(onChange: () => void) {
  if (typeof document === 'undefined') return () => {}
  document.addEventListener('visibilitychange', onChange)
  return () => document.removeEventListener('visibilitychange', onChange)
}

function getSnapshot() {
  return typeof document !== 'undefined' && document.visibilityState === 'visible'
}

export function usePageVisibility() {
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

export function useInitialMapActivation() {
  const pageVisible = usePageVisibility()
  const [activated, setActivated] = useState(pageVisible)
  useEffect(() => {
    if (pageVisible && !activated) setActivated(true)
  }, [activated, pageVisible])
  return activated
}
