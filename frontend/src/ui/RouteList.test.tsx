// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import { createEstimatedVehiclePosition } from '../test/estimatedVehiclePositionFixture'
import { RouteList } from './RouteList'

describe('RouteList line identity', () => {
  it('colors the badge with the official line color instead of the S-Bahn mode color', () => {
    const vehicle = createEstimatedVehiclePosition({
      vehicle_category: 's_bahn',
      route_short_name: 'S41',
    })
    render(
      <RouteList
        vehicles={[vehicle]}
        selectedTripId={null}
        onSelect={vi.fn()}
      />,
    )

    const row = screen.getByRole('button', { name: /S41/ })
    expect(row.style.getPropertyValue('--mode-color')).toBe('#ad5937')
  })
})
