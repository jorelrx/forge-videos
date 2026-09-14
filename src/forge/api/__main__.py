def main() -> None:
    import uvicorn
    from forge.api.app import create_app
    from forge.infrastructure.config import get_settings
    settings = get_settings()
    uvicorn.run(
        "forge.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=settings.studio_api_port,
        log_level=settings.log_level.lower(),
    )
