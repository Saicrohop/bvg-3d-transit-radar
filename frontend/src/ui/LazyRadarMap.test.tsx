// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const imports = vi.hoisted(() => ({ lite: vi.fn(), deck: vi.fn() }))
vi.mock('../map/RadarMap', () => {
  imports.deck()
  return { RadarMap: () => <output data-testid="lazy-map-loaded">map module loaded</output> }
})
vi.mock('../map/MapLibreLite', () => {
  imports.lite()
  return { MapLibreLite: () => <output data-testid="lite-map-loaded">Lite</output> }
})

import {
  LazyRadarMap,
  MapErrorBoundary,
  MapLoadingFallback,
} from './LazyRadarMap'

function ExplodingChild(): never {
  throw new Error('map import failed')
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('lazy map boundary', () => {
  it('does not import either map while off and never imports Deck in default Lite', async () => {
    const view = render(<LazyRadarMap mode="off" vehicles={[]} />)
    expect(imports.lite).not.toHaveBeenCalled()
    expect(imports.deck).not.toHaveBeenCalled()
    expect(screen.getByRole('status').textContent).toContain('Mapa desligado')
    view.rerender(<LazyRadarMap vehicles={[]} />)
    expect(await screen.findByTestId('lite-map-loaded')).toBeTruthy()
    expect(imports.deck).not.toHaveBeenCalled()
  })
  it('exposes a textual loading state before the map module is ready', () => {
    render(<MapLoadingFallback />)
    expect(screen.getByRole('status').textContent).toContain('Carregando cartografia')
  })

  it('contains a map loading failure without crashing the shell', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <MapErrorBoundary>
        <ExplodingChild />
      </MapErrorBoundary>,
    )
    expect(screen.getByRole('alert').textContent).toContain('Cartografia indisponível')
  })

  it('loads the map module through a separate lazy boundary', async () => {
    render(
      <LazyRadarMap
        mode="3d"
        vehicles={[]}
        viewMode="2d"
        cameraTarget={null}
        reducedMotion
      />,
    )
    expect(await screen.findByTestId('lazy-map-loaded')).toBeTruthy()
  })
})
