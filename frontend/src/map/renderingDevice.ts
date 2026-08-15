import type { CreateDeviceProps, Device } from '@luma.gl/core'

export function createPreferredDeckDeviceProps(): CreateDeviceProps {
  return {
    type: 'webgl',
    powerPreference: 'high-performance',
    createCanvasContext: { alphaMode: 'premultiplied' },
  }
}

export function reportDeckRenderingDevice(device: Device): void {
  const renderingApi =
    device.type === 'webgpu'
      ? 'WebGPU'
      : device.type === 'webgl'
        ? 'WebGL2'
        : device.type

  console.info(`[BVG Transit Radar] Deck renderer: ${renderingApi}`, device.info)
}
