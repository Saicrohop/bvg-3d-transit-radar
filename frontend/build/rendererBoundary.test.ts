import { describe, expect, it } from 'vitest'
import { assertRendererIsolation, publicModuleId } from './rendererBoundary'

const graph = [
  { fileName: 'entry.js', isEntry: true, facadeModuleId: '/src/main.tsx', imports: ['shared.js'], modules: ['/src/ui/LazyRadarMap.tsx'] },
  { fileName: 'shared.js', isEntry: false, facadeModuleId: null, imports: [], modules: ['/node_modules/react/index.js'] },
  { fileName: 'lite.js', isEntry: false, facadeModuleId: '/src/map/MapLibreLite.tsx', imports: ['shared.js', 'maplibre.js'], modules: ['/src/map/MapLibreLite.tsx'] },
  { fileName: 'maplibre.js', isEntry: false, facadeModuleId: null, imports: [], modules: ['/node_modules/maplibre-gl/dist/maplibre-gl.js'] },
  { fileName: '3d.js', isEntry: false, facadeModuleId: '/src/map/RadarMap.tsx', imports: ['shared.js', 'maplibre.js'], modules: ['/node_modules/@deck.gl/core/index.js', '/node_modules/@luma.gl/core/index.js'] },
]

describe('production renderer bundle boundary', () => {
  it('redacts absolute build-host paths in the public inventory including the HTML entry', () => {
    const root = 'C:/Users/private/project/frontend'
    expect(publicModuleId(`${root}/index.html`, root)).toBe('index.html')
    expect(publicModuleId(`${root}/src/map/MapLibreLite.tsx`, root)).toBe('src/map/MapLibreLite.tsx')
    expect(publicModuleId('C:\\Users\\private\\project\\frontend\\node_modules\\react\\index.js', root)).toBe('node_modules/react/index.js')
    expect(publicModuleId('D:/external/lib/runtime.js', root)).toBe('[external]/runtime.js')
    expect(publicModuleId('/home/private/external.js', root)).toBe('[external]/external.js')
  })
  it('permits shared MapLibre but fails if a transitive static Lite dependency imports Deck', () => {
    expect(() => assertRendererIsolation(graph)).not.toThrow()
    const polluted = graph.map(chunk => chunk.fileName === 'maplibre.js'
      ? { ...chunk, imports: ['3d.js'] } : chunk)
    expect(() => assertRendererIsolation(polluted)).toThrow(/Lite.*Deck|Lite.*deck/i)
  })

  it('independently rejects entry contamination even when Lite is isolated', () => {
    const polluted = graph.map(chunk => chunk.fileName === 'entry.js'
      ? { ...chunk, imports: [...chunk.imports, '3d.js'] } : chunk)
    expect(() => assertRendererIsolation(polluted)).toThrow(/entry statically includes Deck/)
  })

  it.each(['@luma.gl/core', '@loaders.gl/gltf'])('rejects %s hidden in a shared chunk', dependency => {
    const polluted = graph.map(chunk => chunk.fileName === 'shared.js'
      ? { ...chunk, modules: [...chunk.modules, `/node_modules/${dependency}/index.js`] } : chunk)
    expect(() => assertRendererIsolation(polluted)).toThrow(/Lite statically includes Deck/)
  })

  it('fails closed on an unresolved static import', () => {
    const broken = graph.map(chunk => chunk.fileName === 'entry.js'
      ? { ...chunk, imports: ['missing.js'] } : chunk)
    expect(() => assertRendererIsolation(broken)).toThrow('Unresolved bundle import: missing.js')
  })

  it('terminates cycles in an isolated shared dependency graph', () => {
    const cycle = graph.map(chunk => chunk.fileName === 'shared.js'
      ? { ...chunk, imports: ['entry.js'] } : chunk)
    expect(() => assertRendererIsolation(cycle)).not.toThrow()
  })

  it('requires every renderer facade instead of claiming isolation for a partial graph', () => {
    expect(() => assertRendererIsolation(graph.filter(chunk => chunk.fileName !== '3d.js')))
      .toThrow('Missing entry or explicit Lite/3D chunk boundary')
  })
})
