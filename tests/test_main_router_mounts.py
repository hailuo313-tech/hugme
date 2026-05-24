from main import app


def test_attribution_admin_summary_route_is_mounted() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/v1/admin/attribution/summary" in paths


def test_ai_ops_admin_routes_are_mounted() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/v1/ai-ops/admin/script-templates" in paths
    assert "/api/v1/ai-ops/admin/persona-prompts" in paths
    assert "/api/v1/ai-ops/admin/intent-rules" in paths
    assert "/api/v1/ai-ops/admin/redlines" in paths
