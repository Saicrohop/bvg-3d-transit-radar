import { Component, lazy, Suspense, useEffect, useRef, type ReactNode } from 'react'

import type { MapDisplayMode, RadarMapProps } from '../map/mapTypes'
import { usePageVisibility } from './usePageVisibility'

const DeferredRadarMap = lazy(async () => {
  const module = await import('../map/RadarMap')
  return { default: module.RadarMap }
})

const DeferredLiteMap = lazy(async () => {
  const module = await import('../map/MapLibreLite')
  return { default: module.MapLibreLite }
})

export function MapLoadingFallback() {
  return (
    <div className="map-status" role="status" aria-live="polite">
      Carregando cartografia Orbital…
    </div>
  )
}

type MapErrorBoundaryState = Readonly<{
  hasError: boolean
}>

type MapErrorBoundaryProps = Readonly<{
  children: ReactNode
}>

export class MapErrorBoundary extends Component<
  MapErrorBoundaryProps,
  MapErrorBoundaryState
> {
  state: MapErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): MapErrorBoundaryState {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="map-status map-status-error" role="alert">
          Cartografia indisponível no momento. Os painéis continuam ativos.
          Escolha Mapa Lite ou Sem mapa nos controles superiores.
        </div>
      )
    }

    return this.props.children
  }
}

export function LazyRadarMap({ mode = 'lite', ...props }: RadarMapProps & { mode?: MapDisplayMode }) {
  const pageVisible = usePageVisibility()
  const lastVisible = useRef<{ mode: MapDisplayMode; props: RadarMapProps } | null>(null)
  useEffect(() => {
    if (mode === 'off') lastVisible.current = null
    else if (pageVisible) lastVisible.current = { mode, props }
  }, [mode, pageVisible, props])
  if (mode === 'off') return <div className="map-status" role="status">Mapa desligado. Telemetria e painéis continuam ativos.</div>
  // Keep committed renderers mounted: hiding a tab must not reset camera or failure latches.
  const displayedProps = pageVisible ? props : lastVisible.current?.mode === mode ? lastVisible.current.props : null
  if (!displayedProps) return <div className="map-status" role="status">Mapa aguardando aba visível. Telemetria e painéis continuam ativos.</div>
  return (
    <MapErrorBoundary key={mode}>
      <Suspense fallback={<MapLoadingFallback />}>
        {mode === '3d' ? <DeferredRadarMap {...displayedProps} /> : <DeferredLiteMap {...displayedProps} />}
      </Suspense>
    </MapErrorBoundary>
  )
}
