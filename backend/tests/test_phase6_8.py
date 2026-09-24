from app.services import haversine_km, optimize_route, parse_gps_location


def test_gps_parser_accepts_valid_coordinates():
    assert parse_gps_location("GPS: 19.076000, 72.877700") == (19.076, 72.8777)


def test_gps_parser_rejects_non_gps_text():
    assert parse_gps_location("Mumbai hub") is None


def test_route_optimizer_orders_stops_and_returns_distance():
    result = optimize_route(
        {"latitude": 19.076, "longitude": 72.8777},
        [
            {"stop_id": "far", "label": "Far", "latitude": 19.2, "longitude": 72.95},
            {"stop_id": "near", "label": "Near", "latitude": 19.08, "longitude": 72.88},
        ],
    )
    assert result["stops"][0]["stop_id"] == "near"
    assert result["total_distance_km"] > 0
    assert haversine_km(0, 0, 0, 0) == 0
