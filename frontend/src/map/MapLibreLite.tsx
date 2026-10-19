import { memo, useEffect, useRef, useState } from 'react'
import maplibregl, { type GeoJSONSource } from 'maplibre-gl'
import { DARK_CARTO_STYLE_URL, REALTIME_MAP_VIEW } from './mapStyle'
import { createLiteVehicleData, LITE_VEHICLE_LAYER, LITE_VEHICLE_SOURCE } from './liteVehicleLayer'
import type { RadarMapProps } from './mapTypes'
import { useInitialMapActivation } from '../ui/usePageVisibility'

function MapLibreLiteView({ vehicles, cameraTarget = null, reducedMotion = false, onVehicleSelect }: RadarMapProps) {
  const activated = useInitialMapActivation()
  const [resourceError, setResourceError] = useState(false)
  const [failure, setFailure] = useState<'initialization' | 'context-lost' | null>(null)
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const ready = useRef(false)
  const latest = useRef({ vehicles, cameraTarget, reducedMotion, onVehicleSelect })
  latest.current = { vehicles, cameraTarget, reducedMotion, onVehicleSelect }

  useEffect(() => {
    if (ready.current) {
      const source = map.current?.getSource(LITE_VEHICLE_SOURCE) as GeoJSONSource | undefined
      source?.setData(createLiteVehicleData(vehicles))
    }
  }, [vehicles])

  useEffect(() => {
    const { cameraTarget: target, reducedMotion: reduce } = latest.current
    if (ready.current && target) map.current?.easeTo({
      center: [target.longitude, target.latitude], zoom: 16.5,
      pitch: 0, duration: reduce ? 0 : 700,
    })
  }, [cameraTarget?.requestId, cameraTarget?.longitude, cameraTarget?.latitude])

  useEffect(() => {
    if (!container.current || failure || !activated) return
    let disposed = false
    let created: maplibregl.Map | null = null
    const dispose = () => {
      if (disposed) return
      disposed = true
      ready.current = false
      map.current = null
      created?.remove()
    }
    try {
      const instance = new maplibregl.Map({
        container: container.current, style: DARK_CARTO_STYLE_URL,
        ...REALTIME_MAP_VIEW, pitch: 0, maxPitch: 0, touchPitch: false, pixelRatio: 1,
      })
      created = instance
      map.current = instance
      instance.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'bottom-right')
      instance.on('error', () => { if (!disposed) setResourceError(true) })
      instance.on('webglcontextlost', () => {
        if (disposed) return
        dispose()
        setFailure('context-lost')
      })
      instance.on('load', () => {
        if (disposed) return
        try {
          instance.addSource(LITE_VEHICLE_SOURCE, {
            type: 'geojson', data: createLiteVehicleData(latest.current.vehicles),
          })
          instance.addLayer(LITE_VEHICLE_LAYER)
          const { cameraTarget: target, reducedMotion: reduce } = latest.current
          if (target) instance.easeTo({
            center: [target.longitude, target.latitude], zoom: 16.5,
            pitch: 0, duration: reduce ? 0 : 700,
          })
          ready.current = true
        } catch {
          dispose()
          setFailure('initialization')
        }
      })
      instance.on('click', event => {
        if (disposed || !ready.current) return
        const id = instance.queryRenderedFeatures(event.point, { layers: [LITE_VEHICLE_LAYER.id] })[0]?.properties?.trip_id
        if (typeof id === 'string' && latest.current.vehicles.some(vehicle => vehicle.trip_id === id)) {
          latest.current.onVehicleSelect?.(id)
        }
      })
    } catch {
      dispose()
      setFailure('initialization')
    }
    return dispose
  }, [activated, failure])

  if (failure) return <div className="map-status map-status-error" role="alert">{failure === 'context-lost' ? 'Contexto gráfico perdido.' : 'Não foi possível iniciar o mapa.'} Use Sem mapa; os painéis continuam ativos.</div>
  return <>
    <div ref={container} className="radar-map" aria-label="Mapa Lite de Berlim" />
    {resourceError && <p className="map-resource-warning" role="status">Alguns recursos do mapa não carregaram. A telemetria permanece disponível nos painéis.</p>}
  </>
}

export const MapLibreLite = memo(MapLibreLiteView)
