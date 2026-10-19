type TransitionVehicle = Readonly<{ trip_id: string; route_short_name: string | null }>

export function getLayerTransitionIdentity(
  layerId: string,
  vehicles: readonly TransitionVehicle[],
): readonly string[] {
  // TextLayer expands strings into glyphs; matching trip IDs alone is not enough.
  return vehicles.map((vehicle) => layerId === 'vehicle-labels'
    ? JSON.stringify([vehicle.trip_id, vehicle.route_short_name])
    : vehicle.trip_id)
}

export function getPositionTransitions(
  previous: readonly string[] | undefined,
  current: readonly string[],
  reducedMotion: boolean,
): { getPosition?: number } {
  const sameOrderedIds = previous !== undefined && current.length > 0 &&
    previous.length === current.length && current.every((id, index) => previous[index] === id)
  return !reducedMotion && sameOrderedIds ? { getPosition: 1000 } : {}
}
