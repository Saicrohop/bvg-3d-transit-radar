import { webgpuAdapter } from '@luma.gl/webgpu'
import { describe, expect, it } from 'vitest'

import { createPreferredDeckDeviceProps } from './renderingDevice'

describe('createPreferredDeckDeviceProps', () => {
  it('prefers WebGPU and keeps the Deck WebGL2 fallback available', () => {
    const props = createPreferredDeckDeviceProps()

    expect(props.type).toBe('best-available')
    expect(props.adapters).toContain(webgpuAdapter)
    expect(props.createCanvasContext).toEqual({ alphaMode: 'premultiplied' })
  })
})
