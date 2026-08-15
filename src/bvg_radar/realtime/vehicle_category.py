from typing import Literal

VehicleCategory = Literal["u_bahn", "s_bahn", "bus", "tram", "regional"]


def classify_berlin_vehicle(
    route_type: int,
    route_short_name: str | None,
) -> VehicleCategory | None:
    """Return a supported category for basic GTFS and known VBB extended types."""
    if route_type in (1, 400):
        return "u_bahn"
    if (
        route_type in (2, 109)
        and route_short_name is not None
        and route_short_name.startswith("S")
    ):
        return "s_bahn"
    if route_type == 100:
        return "regional"
    if route_type in (3, 700):
        return "bus"
    if route_type in (0, 900):
        return "tram"
    return None
