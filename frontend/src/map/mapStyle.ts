import type { FillExtrusionLayerSpecification } from 'maplibre-gl'

export const BERLIN_CENTER: [number, number] = [13.405, 52.52]

export const REALTIME_MAP_VIEW = {
  center: BERLIN_CENTER,
  zoom: 12.6,
  pitch: 55,
  bearing: -18,
}

export const CALIBRATION_MAP_VIEW = {
  center: BERLIN_CENTER,
  zoom: 19,
  pitch: 70,
  bearing: 45,
}

export const DARK_CARTO_STYLE_URL =
  'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

export const BUILDING_EXTRUSION_LAYER: FillExtrusionLayerSpecification = {
  id: 'berlin-buildings-3d',
  type: 'fill-extrusion',
  source: 'carto',
  'source-layer': 'building',
  minzoom: 13,
  paint: {
    'fill-extrusion-color': '#1c2938',
    'fill-extrusion-height': [
      'coalesce',
      ['get', 'render_height'],
      ['get', 'height'],
      8,
    ],
    'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
    'fill-extrusion-opacity': 0.78,
    'fill-extrusion-vertical-gradient': true,
  },
}
