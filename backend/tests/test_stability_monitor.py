from app.services.stability_monitor import StabilityMonitor


def test_stability_monitor_includes_configured_urls():
    down_msg = StabilityMonitor._build_nas_down_message("timeout", "https://render.example")
    assert "https://render.example" in down_msg

    recovery_msg = StabilityMonitor._build_nas_recovery_message(None)
    assert "(URL no configurada)" in recovery_msg
