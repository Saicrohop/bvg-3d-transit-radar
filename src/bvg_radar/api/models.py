from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..realtime.vehicle_category import VehicleCategory

PunctualityVehicleCategory = Literal[
    "u_bahn", "s_bahn", "bus", "tram", "regional", "unknown"
]


class RouteListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    route_short_name: str | None
    route_type: int
    vehicle_category: VehicleCategory | None
    active_vehicles: int


class RouteListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routes: list[RouteListItem]


class GeoJSONLineString(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]


class RouteShape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shape_id: str
    trip_count: int
    geojson: GeoJSONLineString


class RoutePathStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_sequence: int
    stop_id: str
    stop_name: str | None
    lon: float
    lat: float


class ScheduledOffset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_sequence: int
    arrival_offset_s: int | None


class RoutePathResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    route_short_name: str | None
    vehicle_category: VehicleCategory | None
    shapes: list[RouteShape]
    stops: list[RoutePathStop]
    scheduled_offsets: list[ScheduledOffset]
    bounds: tuple[float, float, float, float] | None


class StopItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_id: str
    name: str | None
    location_type: int
    lat: float
    lon: float
    modes: list[VehicleCategory]


class StopsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox: tuple[float, float, float, float]
    stops: list[StopItem]


class DailyPunctualityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    route_id: str
    route_short_name: str | None
    vehicle_category: PunctualityVehicleCategory
    samples: int
    on_time_ratio: float
    mean_delay_seconds: float


class DailyPunctualityTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routes: int
    route_categories: int
    samples: int
    on_time: int
    late: int


class DailyPunctualityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    most_punctual: list[DailyPunctualityEntry]
    least_punctual: list[DailyPunctualityEntry]
    totals: DailyPunctualityTotals
