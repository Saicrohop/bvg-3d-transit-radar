import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import type { ShaderModule } from '@luma.gl/shadertools'

const VERTEX_COLOR_INPUT = `
#ifdef HAS_COLORS
in vec4 colors;
out highp vec4 bvgVertexColor;
#endif
`
const VERTEX_COLOR_ASSIGNMENT = `
#ifdef HAS_COLORS
  bvgVertexColor = colors;
#endif
`
const FRAGMENT_COLOR_INPUT = `
#ifdef HAS_COLORS
in highp vec4 bvgVertexColor;
#endif
`
const BASE_COLOR_MULTIPLIER = `
#ifdef HAS_COLORS
  baseColor *= bvgVertexColor;
#endif
`
const BASE_COLOR_ANCHOR = '\n#ifdef ALPHA_CUTOFF\n'

function withVertexColors(material: ShaderModule): ShaderModule {
  const fs = material.fs ?? ''
  // Installed luma has no baseColor hook. Fail closed if an upgrade moves this boundary.
  if (fs.split(BASE_COLOR_ANCHOR).length !== 2) {
    throw new Error('Scenegraph COLOR_0 adapter requires the PBR alpha-cutoff boundary')
  }
  return {
    ...material,
    // Do not reuse the SDK's normalized injection cache or change its shared module.
    instance: undefined,
    vs: VERTEX_COLOR_INPUT + material.vs,
    fs: FRAGMENT_COLOR_INPUT + fs.replace(BASE_COLOR_ANCHOR, BASE_COLOR_MULTIPLIER + BASE_COLOR_ANCHOR),
    inject: { ...material.inject, 'vs:#main-start': VERTEX_COLOR_ASSIGNMENT },
  }
}

/** GLSL-only COLOR_0 bridge; the geometry's normalized format supplies linear RGBA. */
export class VertexColorScenegraphLayer<DataT = unknown> extends ScenegraphLayer<DataT> {
  static layerName = 'VertexColorScenegraphLayer'

  getShaders() {
    const shaders = super.getShaders()
    if (this.props._lighting !== 'pbr') return shaders

    return {
      ...shaders,
      modules: shaders.modules.map((module: ShaderModule) => (
        module.name === 'pbrMaterial' ? withVertexColors(module) : module
      )),
    }
  }
}
