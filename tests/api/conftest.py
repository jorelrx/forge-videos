import pytest
from forge.api.app import create_app, ApiServices


@pytest.fixture
def api_factory():
    def _factory(services=None):
        return create_app(services)
    return _factory
