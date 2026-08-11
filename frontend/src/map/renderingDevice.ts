import type { CreateDeviceProps, Device } from '@luma.gl/core'
import { webgpuAdapter } from '@luma.gl/webgpu'

export function createPreferredDeckDeviceProps(): CreateDeviceProps {
  return {
    type: 'best-available',
    adapters: [webgpuAdapter],
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
