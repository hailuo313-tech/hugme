from main import app


def test_attribution_admin_summary_route_is_mounted() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/v1/admin/attribution/summary" in paths
