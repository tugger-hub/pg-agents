import pytest

@pytest.fixture(autouse=True)
def clear_system_cache_before_test():
    """
    An autouse fixture to clear the system config cache before each integration test.
    This prevents state from leaking between tests that modify system config,
    particularly the kill switch setting.
    """
    try:
        from app.services import system
        system._config_cache = None
        system._cache_expiry = None
    except (ImportError, AttributeError):
        # If the module or variables don't exist for some reason, there's nothing to clear.
        pass
    yield
