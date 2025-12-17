@app.get("/healthz", include_in_schema=False)
def healthz():
    """Direct health check on root app to avoid router issues."""
    return {"status": "ok", "service": "bolus-ai-backend"}
