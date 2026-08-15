import { describe, expect, it } from 'vitest'

import { createPreferredDeckDeviceProps } from './renderingDevice'

describe('createPreferredDeckDeviceProps', () => {
  it('forces the production Deck renderer to WebGL2', () => {
    const props = createPreferredDeckDeviceProps()

    expect(props.type).toBe('webgl')
    expect(props.adapters).toBeUndefined()
    expect(props.createCanvasContext).toEqual({ alphaMode: 'premultiplied' })
  })
})
