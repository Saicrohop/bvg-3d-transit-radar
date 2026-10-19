// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { usePageVisibility } from './usePageVisibility'

let visibility: DocumentVisibilityState = 'visible'
beforeEach(() => {
  visibility = 'visible'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('tracks page visibility and releases its listener on unmount', () => {
  const add = vi.spyOn(document, 'addEventListener')
  const remove = vi.spyOn(document, 'removeEventListener')
  const hook = renderHook(() => usePageVisibility())
  expect(hook.result.current).toBe(true)
  act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
  expect(hook.result.current).toBe(false)
  act(() => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
  expect(hook.result.current).toBe(true)
  const handler = add.mock.calls.find(([event]) => event === 'visibilitychange')?.[1]
  expect(handler).toBeTypeOf('function')
  hook.unmount()
  expect(remove.mock.calls.some(([event, callback]) => event === 'visibilitychange' && callback === handler)).toBe(true)
})
