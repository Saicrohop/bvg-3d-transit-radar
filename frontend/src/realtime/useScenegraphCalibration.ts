import { useEffect, useState } from 'react'

import {
  MOCK_CALIBRATION_VEHICLES,
  type ScenegraphCalibrationVehicle,
} from '../map/scenegraphCalibration'

export function useScenegraphCalibration(enabled: boolean) {
  const [vehicles, setVehicles] = useState<
    readonly ScenegraphCalibrationVehicle[]
  >([])

  useEffect(() => {
    if (!enabled) {
      setVehicles([])
      return undefined
    }

    const timeout = window.setTimeout(() => {
      setVehicles(MOCK_CALIBRATION_VEHICLES)
    }, 1_000)

    return () => {
      window.clearTimeout(timeout)
    }
  }, [enabled])

  return vehicles
}
