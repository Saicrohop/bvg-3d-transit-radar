import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { assertRendererIsolation, publicModuleId } from './build/rendererBoundary.js'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), {
    name: 'enforce-lite-renderer-boundary',
    generateBundle(_options, bundle) {
      const chunks = Object.values(bundle).flatMap(output => output.type === 'chunk' ? [{
        fileName: output.fileName, isEntry: output.isEntry,
        facadeModuleId: output.facadeModuleId,
        imports: output.imports, dynamicImports: output.dynamicImports,
        modules: Object.keys(output.modules).map(id => id.replaceAll('\\', '/')),
      }] : [])
      assertRendererIsolation(chunks)
      this.emitFile({ type: 'asset', fileName: 'renderer-boundary.json', source: JSON.stringify({
        isolation: 'passed',
        chunks: chunks.map(chunk => ({ ...chunk,
          facadeModuleId: chunk.facadeModuleId ? publicModuleId(chunk.facadeModuleId, process.cwd()) : null,
          modules: chunk.modules.map(id => publicModuleId(id, process.cwd())),
        })),
      }, null, 2) })
    },
  }],
  build: { manifest: true },
})
