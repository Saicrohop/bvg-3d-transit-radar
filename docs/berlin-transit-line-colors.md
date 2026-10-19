# Berlin S-Bahn / U-Bahn line colors

The per-line palette comes from the VBB official `Linienfarben` CSV (`background_Hex` values). The downloaded archive contained `20260828-linienfarben.csv`; the VBB dataset page labels the resource as last updated April 2026. I cross-checked the active line list against the current BVG/S-Bahn/VBB map published 15 June 2026 (the PDF itself prints “Stand: 30. März 2026”). The map shows S15 in the same magenta as S1, so S15 uses that value even though it is not present in the color CSV.

| System | Line(s) | Color |
|---|---|---|
| S-Bahn | S1, S15 | `#da6ba2` |
| S-Bahn | S2, S25, S26 | `#007734` |
| S-Bahn | S3 | `#0066ad` |
| S-Bahn | S41 | `#ad5937` |
| S-Bahn | S42 | `#cb6418` |
| S-Bahn | S46, S47 | `#cd9c53` |
| S-Bahn | S5 | `#eb7405` |
| S-Bahn | S7, S75 | `#816da6` |
| S-Bahn | S8, S85 | `#66aa22` |
| S-Bahn | S9 | `#992746` |
| U-Bahn | U1 | `#7dad4c` |
| U-Bahn | U2 | `#da421e` |
| U-Bahn | U3 | `#16683d` |
| U-Bahn | U4 | `#f0d722` |
| U-Bahn | U5 | `#7e5330` |
| U-Bahn | U6 | `#8c6dab` |
| U-Bahn | U7 | `#009bd5` |
| U-Bahn | U8 | `#224f86` |
| U-Bahn | U9 | `#f3791d` |

The frontend applies these values to route badges, the selected-trip inspector accent, native MapLibre vehicle markers, Deck point fallbacks, and 3D vehicle labels. Other categories retain their existing mode colors. S45 is intentionally omitted: S-Bahn Berlin discontinued it at the December 14, 2025 timetable change.

**Scope note:** station and stop icons are not yet wired into the frontend. The map currently draws estimated vehicle positions only; the read-only stops API exists in the backend, but no frontend stop/station layer consumes it yet. Add that as a separate UI increment with distinct station/platform symbols and viewport-bounded queries. No visual/browser/GPU acceptance was performed for this palette change.
