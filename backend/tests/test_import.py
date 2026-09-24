def test_app_imports():
    from app.main import app
    assert app.title == "OptiGo Courier Tracking API"
    paths = {route.path for route in app.routes}
    assert "/api/auth/login" in paths
    assert "/api/track/{tracking_id}" in paths
    assert "/api/notifications" in paths
    assert "/api/complaints" in paths
    assert "/api/complaints/{complaint_id}" in paths
    assert "/api/shipments/{shipment_id}/assessment" in paths
    assert "/api/reports/delays" in paths
