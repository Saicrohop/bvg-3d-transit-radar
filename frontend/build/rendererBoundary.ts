export type ChunkModules = Readonly<{
  fileName: string
  isEntry: boolean
  facadeModuleId: string | null
  imports: readonly string[]
  modules: readonly string[]
}>

export function publicModuleId(moduleId: string, root: string): string {
  const id = moduleId.replaceAll('\\', '/').replaceAll('\0', '')
  const prefix = `${root.replaceAll('\\', '/').replace(/\/$/, '')}/`
  const dependency = id.lastIndexOf('/node_modules/')
  if (dependency >= 0) return id.slice(dependency + 1)
  if (id.startsWith(prefix)) return id.slice(prefix.length)
  if (/^(?:[A-Za-z]:\/|\/)/.test(id)) return `[external]/${id.split('/').at(-1)}`
  return id
}

export function assertRendererIsolation(chunks: readonly ChunkModules[]) {
  const byFile = new Map(chunks.map(chunk => [chunk.fileName, chunk]))
  const lite = chunks.find(chunk => chunk.facadeModuleId?.replaceAll('\\', '/').endsWith('/src/map/MapLibreLite.tsx'))
  const deck = chunks.find(chunk => chunk.facadeModuleId?.replaceAll('\\', '/').endsWith('/src/map/RadarMap.tsx'))
  const entries = chunks.filter(chunk => chunk.isEntry)
  if (!lite || !deck || entries.length === 0) throw new Error('Missing entry or explicit Lite/3D chunk boundary')
  for (const [name, roots] of [['Lite', [lite]], ['entry', entries]] as const) {
    const visited = new Set<string>()
    const visit = (chunk: ChunkModules) => {
      if (visited.has(chunk.fileName)) return
      visited.add(chunk.fileName)
      for (const id of chunk.modules) {
        if (/@(?:deck|luma|loaders)\.gl\//.test(id.replaceAll('\\', '/')) || /\/src\/map\/(?:RadarMap|scenegraph)/.test(id)) {
          throw new Error(`${name} statically includes Deck/3D dependency: ${id}`)
        }
      }
      for (const dependency of chunk.imports) {
        const next = byFile.get(dependency)
        if (!next) throw new Error(`Unresolved bundle import: ${dependency}`)
        visit(next)
      }
    }
    for (const root of roots) visit(root)
  }
}
