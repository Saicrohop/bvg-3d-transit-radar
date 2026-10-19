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
  type ScenegraphAssetErrorHandler,
} from './productionScenegraphLayers'
import type { CalibrationVehicleType } from './scenegraphCalibration'
import {
  createPreferredDeckDeviceProps,
  reportDeckRenderingDevice,
} from './renderingDevice'
import { createVehiclePointLayer } from './vehiclePointLayer'
import type { RadarMapProps } from './mapTypes'
import { planVehicleRendering, type RenderViewport } from './renderPolicy'
import { getLayerTransitionIdentity, getPositionTransitions } from './transitionIdentity'
import { useInitialMapActivation } from '../ui/usePageVisibility'

export type { RadarMapProps } from './mapTypes'

function createScenegraphEffects() {
  const scenegraphAmbientLight = new AmbientLight({
    color: [255, 255, 255],
    intensity: 1.5,
  })
  const scenegraphDirectionalLight = new DirectionalLight({
    color: [255, 244, 214],
    intensity: 2,
    direction: [-1, -3, -2],
  })
  return [
    new LightingEffect({
      ambientLight: scenegraphAmbientLight,
      directionalLight: scenegraphDirectionalLight,
    }),
  ]
}

function createProductionVehicleLayers(
  vehicles: readonly EstimatedVehiclePosition[],
  viewport: RenderViewport,
  failedVehicleTypes: ReadonlySet<CalibrationVehicleType>,
  onScenegraphAssetError: ScenegraphAssetErrorHandler,
) {
  const plan = planVehicleRendering(vehicles, viewport, failedVehicleTypes)
  return [
    createVehiclePointLayer(plan.points),
    ...createProductionScenegraphLayers(plan.models, {
      failedVehicleTypes,
      onScenegraphAssetError,
      labelVehicles: plan.labels,
    }),
  ]
}

function RadarMapView({
  vehicles,
  viewMode = '3d',
  cameraTarget = null,
  reducedMotion = false,
  onVehicleSelect,
}: RadarMapProps) {
  const activated = useInitialMapActivation()
  const [viewport, setViewport] = useState<RenderViewport | null>(null)
  const [failedVehicleTypes, setFailedVehicleTypes] = useState<
    ReadonlySet<CalibrationVehicleType>
  >(() => new Set())
  const container = useRef<HTMLDivElement | null>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const overlay = useRef<MapboxOverlay | null>(null)
  const scenegraphEffects = useRef<ReturnType<typeof createScenegraphEffects>>([])
  const appliedLayerIdentities = useRef(new Map<string, readonly string[]>())
  const pendingViewMode = useRef(false)
  const latestSelection = useRef({ vehicles, onVehicleSelect })
  latestSelection.current = { vehicles, onVehicleSelect }
  const latestCamera = useRef({ viewMode, cameraTarget, reducedMotion })
  latestCamera.current = { viewMode, cameraTarget, reducedMotion }
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
  const productionLayers = useMemo(
    () =>
      viewport === null ? [] : createProductionVehicleLayers(
        vehicles,
        viewport,
        failedVehicleTypes,
        reportScenegraphAssetError,
      ),
    [failedVehicleTypes, reportScenegraphAssetError, vehicles, viewport],
  )
  useEffect(() => {
    if (overlay.current === null) return
    const nextIdentities = new Map<string, readonly string[]>()
    const vehicleLayers = productionLayers.map((layer) => {
      const identity = getLayerTransitionIdentity(
        layer.id, layer.props.data as readonly EstimatedVehiclePosition[],
      )
      nextIdentities.set(layer.id, identity)
      return layer.clone({ transitions: getPositionTransitions(
        appliedLayerIdentities.current.get(layer.id), identity, reducedMotion,
      ) })
    })
    overlay.current.setProps({
      layers: vehicleLayers,
      effects: scenegraphEffects.current,
    })
    appliedLayerIdentities.current = nextIdentities
  }, [productionLayers, reducedMotion])

  const applyViewMode = useCallback(() => {
    if (map.current === null) return
    if (overlay.current === null) {
      pendingViewMode.current = true
      return
    }
    pendingViewMode.current = false
    const { viewMode: mode, reducedMotion: reduce } = latestCamera.current
    map.current.easeTo({
      pitch: mode === '3d' ? 55 : 0,
      ...(mode === '3d' ? { zoom: Math.max(13.5, map.current.getZoom()) } : {}),
      duration: reduce ? 0 : 700,
    })
  }, [])

  useEffect(() => {
    applyViewMode()
  }, [applyViewMode, viewMode])

  const applyCameraTarget = useCallback(() => {
    const { cameraTarget: target, viewMode: mode, reducedMotion: reduce } = latestCamera.current
    if (map.current === null || overlay.current === null || target === null) return
    map.current.easeTo({
      center: [target.longitude, target.latitude],
      zoom: 16.5,
      pitch: mode === '3d' ? 55 : 0,
      duration: reduce ? 0 : 700,
    })
  }, [])

  useEffect(() => {
    applyCameraTarget()
  }, [applyCameraTarget, cameraTarget?.requestId, cameraTarget?.longitude, cameraTarget?.latitude])

  useEffect(() => {
    if (container.current === null || !activated) {
      return undefined
    }

    let disposed = false
    const mapInstance = new maplibregl.Map({
      container: container.current,
      style: DARK_CARTO_STYLE_URL,
      maxPitch: 75,
      pixelRatio: 1,
      ...REALTIME_MAP_VIEW,
    })
    map.current = mapInstance
    mapInstance.addControl(
      new maplibregl.NavigationControl(),
      'bottom-right',
    )

    const updateViewport = () => {
      if (disposed || overlay.current === null) return
      const bounds = mapInstance.getBounds()
      setViewport({
        zoom: mapInstance.getZoom(),
        west: bounds.getWest(), east: bounds.getEast(),
        south: bounds.getSouth(), north: bounds.getNorth(),
      })
    }
    mapInstance.on('moveend', updateViewport)
    mapInstance.on('load', () => {
      if (disposed) {
        return
      }

      scenegraphEffects.current = createScenegraphEffects()

      if (mapInstance.getLayer(BUILDING_EXTRUSION_LAYER.id) === undefined) {
        const firstSymbolLayer = mapInstance
          .getStyle()
          .layers?.find((layer) => layer.type === 'symbol')?.id
        mapInstance.addLayer(BUILDING_EXTRUSION_LAYER, firstSymbolLayer)
      }

      const deckOverlay = new MapboxOverlay({
        interleaved: false,
        useDevicePixels: 1,
        deviceProps: createPreferredDeckDeviceProps(),
        onDeviceInitialized: reportDeckRenderingDevice,
        onClick: ({ object }: { object?: unknown }) => {
          if (typeof object !== 'object' || object === null ||
              !('trip_id' in object) || typeof object.trip_id !== 'string') return
          const { vehicles: currentVehicles, onVehicleSelect: select } = latestSelection.current
          const selectedVehicle = currentVehicles.find((vehicle) => vehicle.trip_id === object.trip_id)
          if (selectedVehicle) select?.(selectedVehicle.trip_id)
        },
        layers: [],
        effects: scenegraphEffects.current,
      })
      mapInstance.addControl(deckOverlay as unknown as IControl)
      overlay.current = deckOverlay
      updateViewport()
      if (latestCamera.current.cameraTarget !== null) {
        applyCameraTarget()
      } else if (latestCamera.current.viewMode === '2d' || pendingViewMode.current) {
        applyViewMode()
      }
    })

    return () => {
      disposed = true
      map.current = null
      overlay.current = null
      appliedLayerIdentities.current.clear()
      mapInstance.remove()
    }
  }, [activated, applyCameraTarget, applyViewMode, reportScenegraphAssetError])

  return <div ref={container} className="radar-map" aria-label="Mapa de Berlim" />
}

export const RadarMap = memo(RadarMapView)
