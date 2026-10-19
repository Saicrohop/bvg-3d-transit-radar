# Approved low-poly transit models

These five user-supplied Blender exports were approved for integration on **2026-10-18**. Their increased geometry is intentional and was retained byte-for-byte: no decimation, re-export, material conversion or texture generation was performed.

| Category | File | Length × width × height (m) | Triangles | GLB bytes |
|---|---|---|---:|---:|
| Bus | `bvg_bus_lowpoly_v3.glb` | 12 × 2.55 × 3.2 | 954 | 41160 |
| U-Bahn | `u_bahn_lowpoly_v2.glb` | 30 × 2.65 × 3.5 | 2686 | 126672 |
| S-Bahn | `s_bahn_lowpoly_v1.glb` | 36 × 3 × 3.6 | 2706 | 130360 |
| Tram | `bvg_tram_lowpoly_v1.glb` | 30 × 2.4 × 3.4 | 2270 | 107440 |
| Regional | `regional_lowpoly_v2.glb` | 40 × 2.8 × 4.6 | 4085 | 208860 |

Total for these GLBs: **614492 bytes**. Dimensions are schematic design targets, not official fleet specifications.

## Frame and integration contract

- GLB geometry: X width, Y height/up, Z length; author-declared front **+Z**.
- Identity root transform, centered X/Z, lowest Y=0.
- One mesh, one triangle primitive and one opaque PBR material per file.
- `COLOR_0`: normalized UNSIGNED_SHORT RGBA; no textures, animations or skins.
- Material metallic=0, roughness approximately 0.8, `doubleSided=true` retained.
- Deck.gl CPU frame conversion: `[pitch, yaw, roll] = [0, 180 - heading, 90]`, unit size scale and zero translation, verified against the installed matrix updater and exported bounds.
- Each production category has its own layer/failure key; U-Bahn no longer shares the bus asset. Failed models fall back to points, not legacy GLBs.
- Lite remains the default; no GLB prewarming at application startup. Optional 3D is still explicitly selected by the user.

File SHA-256 identities are asserted in `src/map/lowpolyAssets.test.ts`. Keep filenames versioned; adopt a later export only with its own hash and calibration tests.

## Evidence boundaries

Structural validation used Khronos glTF Validator and direct CPU decoding of the binaries. These results do **not** certify actual pixels, physical front, palette appearance, FPS, GPU memory or safe power draw. No Blender, browser or graphical renderer was launched during integration; visual acceptance remains manual/deferred for this machine.

The embedded generator string is `Khronos glTF Blender I/O v5.3.41`. A detailed authorship/license declaration was not supplied in the source inventory; it has not been inferred from that string or from the repository license.

Existing models in the parent directory are preserved as legacy files and are not selected by the new production mapping.
