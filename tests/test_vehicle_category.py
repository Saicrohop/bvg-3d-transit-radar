from bvg_radar.realtime.vehicle_category import classify_berlin_vehicle


def test_classifies_u8_subway_as_u_bahn() -> None:
    assert classify_berlin_vehicle(route_type=1, route_short_name="U8") == "u_bahn"


def test_classifies_vbb_u8_metro_service_as_u_bahn() -> None:
    assert classify_berlin_vehicle(route_type=400, route_short_name="U8") == "u_bahn"


def test_classifies_s41_rail_as_s_bahn() -> None:
    assert classify_berlin_vehicle(route_type=2, route_short_name="S41") == "s_bahn"


def test_classifies_vbb_s41_suburban_rail_as_s_bahn() -> None:
    assert classify_berlin_vehicle(route_type=109, route_short_name="S41") == "s_bahn"


def test_classifies_vbb_regional_rail_service_as_regional() -> None:
    assert classify_berlin_vehicle(route_type=100, route_short_name="FEX") == "regional"


def test_classifies_bus_route_as_bus() -> None:
    assert classify_berlin_vehicle(route_type=3, route_short_name="100") == "bus"


def test_classifies_vbb_bus_service_as_bus() -> None:
    assert classify_berlin_vehicle(route_type=700, route_short_name="100") == "bus"


def test_classifies_tram_route_as_tram() -> None:
    assert classify_berlin_vehicle(route_type=0, route_short_name="M4") == "tram"


def test_classifies_vbb_tram_service_as_tram() -> None:
    assert classify_berlin_vehicle(route_type=900, route_short_name="M4") == "tram"
