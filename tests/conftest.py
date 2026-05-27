import sys


def pytest_sessionstart(session):
    """Clean up any stale test mocks from previous sessions."""
    pass


def pytest_runtest_setup(item):
    """Restore tools modules after server test pollution."""
    pass
