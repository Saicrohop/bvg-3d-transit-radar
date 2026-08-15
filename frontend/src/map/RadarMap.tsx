import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AmbientLight, DirectionalLight, LightingEffect } from '@deck.gl/core'
import { MapboxOverlay } from '@deck.gl/mapbox'
import maplibregl, { type IControl } from 'maplibre-gl'

import type { EstimatedVehiclePosition } from '../realtime/vehiclePositions'
import {
  BUILDING_EXTRUSION_LAYER,
  DARK_CARTO_STYLE_URL,
  REALTIME_MAP_VIEW,
} from './mapStyle'
import {
  createProductionScenegraphLayers,
  getProductionScenegraphFallbackVehicles,
  type ScenegraphAssetErrorHandler,
} from './productionScenegraphLayers'
import type { CalibrationVehicleType } from './scenegraphCalibration'
import {
  createPreferredDeckDeviceProps,
  reportDeckRenderingDevice,
} from './renderingDevice'
import { createVehiclePointLayer } from './vehiclePointLayer'

const scenegraphAmbientLight = new AmbientLight({
  color: [255, 255, 255],
  intensity: 1.5,
})
const scenegraphDirectionalLight = new DirectionalLight({
  color: [255, 244, 214],
  intensity: 2,
  direction: [-1, -3, -2],
})
const SCENEGRAPH_EFFECTS = [
  new LightingEffect({
    ambientLight: scenegraphAmbientLight,
    directionalLight: scenegraphDirectionalLight,
  }),
]

function createProductionVehicleLayers(
  vehicles: readonly EstimatedVehiclePosition[],
  failedVehicleTypes: ReadonlySet<CalibrationVehicleType>,
  onScenegraphAssetError: ScenegraphAssetErrorHandler,
) {
  return [
    createVehiclePointLayer(
      getProductionScenegraphFallbackVehicles(vehicles, failedVehicleTypes),
    ),
    ...createProductionScenegraphLayers(vehicles, {
      failedVehicleTypes,
      onScenegraphAssetError,
    }),
  ]
}

export type RadarMapProps = Readonly<{
  vehicles: readonly EstimatedVehiclePosition[]
}>

function RadarMapView({ vehicles }: RadarMapProps) {
  const [failedVehicleTypes, setFailedVehicleTypes] = useState<
    ReadonlySet<CalibrationVehicleType>
  >(() => new Set())
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const overlay = useRef<MapboxOverlay | null>(null)
  const reportScenegraphAssetError = useCallback(
    (vehicleType: CalibrationVehicleType) => {
      setFailedVehicleTypes((current) => {
        if (current.has(vehicleType)) {
          return current
        }

        return new Set([...current, vehicleType])
      })
    },
    [],
  )
  const vehicleLayers = useMemo(
    () =>
      createProductionVehicleLayers(
        vehicles,
        failedVehicleTypes,
        reportScenegraphAssetError,
      ),
    [failedVehicleTypes, reportScenegraphAssetError, vehicles],
  )
  const latestVehicleLayers = useRef(vehicleLayers)
  latestVehicleLayers.current = vehicleLayers

  useEffect(() => {
    latestVehicleLayers.current = vehicleLayers
    overlay.current?.setProps({
      layers: vehicleLayers,
      effects: SCENEGRAPH_EFFECTS,
    })
  }, [failedVehicleTypes, reportScenegraphAssetError, vehicleLayers, vehicles])

  useEffect(() => {
    if (container.current === null) {
      return undefined
    }

    let disposed = false
    const mapInstance = new maplibregl.Map({
      container: container.current,
      style: DARK_CARTO_STYLE_URL,
      maxPitch: 75,
      ...REALTIME_MAP_VIEW,
    })
    map.current = mapInstance
    mapInstance.addControl(
      new maplibregl.NavigationControl(),
      'bottom-right',
    )

    mapInstance.on('load', () => {
      if (disposed) {
        return
      }

      if (mapInstance.getLayer(BUILDING_EXTRUSION_LAYER.id) === undefined) {
        const firstSymbolLayer = mapInstance
          .getStyle()
          .layers?.find((layer) => layer.type === 'symbol')?.id
        mapInstance.addLayer(BUILDING_EXTRUSION_LAYER, firstSymbolLayer)
      }

      const deckOverlay = new MapboxOverlay({
        interleaved: false,
        deviceProps: createPreferredDeckDeviceProps(),
        onDeviceInitialized: reportDeckRenderingDevice,
        layers: latestVehicleLayers.current,
        effects: SCENEGRAPH_EFFECTS,
      })
      mapInstance.addControl(deckOverlay as unknown as IControl)
      overlay.current = deckOverlay
    })

    return () => {
      disposed = true
      map.current = null
      overlay.current = null
      mapInstance.remove()
    }
  }, [reportScenegraphAssetError])

  return <div ref={container} className="radar-map" aria-label="Mapa de Berlim" />
}

export const RadarMap = memo(RadarMapView)
