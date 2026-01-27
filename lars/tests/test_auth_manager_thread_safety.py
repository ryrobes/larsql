import threading


def test_auth_manager_init_is_thread_safe(monkeypatch):
    """
    Regression test for a race where AuthManager could be observed without
    `.config` set, raising: AttributeError: 'AuthManager' object has no attribute 'config'
    """
    from lars.auth.config import AuthConfig
    from lars.auth.manager import AuthManager
    import lars.auth.manager as auth_manager_module

    # Reset singleton between tests
    AuthManager._instance = None

    config_requested = threading.Event()
    allow_config_return = threading.Event()

    def slow_get_auth_config() -> AuthConfig:
        config_requested.set()
        allow_config_return.wait(timeout=5)
        return AuthConfig(enabled=True, secret_key="test", algorithm="HS256")

    monkeypatch.setattr(auth_manager_module, "get_auth_config", slow_get_auth_config)

    t1 = threading.Thread(target=lambda: AuthManager())
    t1.start()

    assert config_requested.wait(timeout=2), "Timed out waiting for first init to request config"

    result = {}
    t2_started = threading.Event()

    def create_and_check():
        t2_started.set()
        try:
            mgr = AuthManager.get_instance()
            result["enabled"] = mgr.is_enabled()
        except Exception as e:  # pragma: no cover
            result["error"] = e

    t2 = threading.Thread(target=create_and_check)
    t2.start()
    assert t2_started.wait(timeout=2), "Timed out waiting for second thread to start"

    # If init is thread-safe, thread 2 should block while thread 1 is still initializing.
    t2.join(timeout=0.5)
    assert t2.is_alive(), "Second thread should wait for initialization to complete"

    allow_config_return.set()

    t1.join(timeout=5)
    t2.join(timeout=5)

    assert "error" not in result
    assert result["enabled"] is True
