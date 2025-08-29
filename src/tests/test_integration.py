import pytest
from typing import List, Dict, Optional

from smalldi import Injector
from smalldi.annotation import Provide


@pytest.fixture
def reset_injector():
    """Reset Injector state before each test"""
    old_singletons = Injector.singletons_available.copy()
    Injector.singletons_available.clear()
    yield
    Injector.singletons_available.clear()
    Injector.singletons_available.update(old_singletons)


def test_simple_injection(reset_injector):
    """Test simple dependency injection in real code"""

    @Injector.singleton
    class ConfigService:
        def get_config(self, key: str) -> str:
            return f"config:{key}"

    @Injector.singleton
    class UserService:
        @Injector.inject
        def __init__(self, config: Provide[ConfigService]):
            self.config = config

        def get_user(self, user_id: int) -> Dict[str, str]:
            api_key = self.config.get_config("api_key")
            return {"id": str(user_id), "name": f"User_{user_id}", "api_key": api_key}

    @Injector.inject
    def get_user_handler(user_id: int, user_service: Provide[UserService]) -> Dict[str, str]:
        return user_service.get_user(user_id)

    result = get_user_handler(user_id=123)
    assert result["id"] == "123"
    assert result["name"] == "User_123"
    assert result["api_key"] == "config:api_key"

def test_nested_injection(reset_injector, monkeypatch):
    """Test nested dependency injection"""
    @Injector.singleton
    class DatabaseService:
        def query(self, sql: str) -> List[Dict[str, str]]:
            return [{"result": f"db:{sql}"}]

    @Injector.singleton
    class LogService:
        def log(self, message: str) -> None:
            pass

    @Injector.singleton
    class UserRepository:
        @Injector.inject
        def __init__(self, db: Provide[DatabaseService], logger: Provide[LogService]):
            self.db = db
            self.logger = logger

        def find_user(self, user_id: int) -> Optional[Dict[str, str]]:
            self.logger.log(f"Finding user {user_id}")
            results = self.db.query(f"SELECT * FROM users WHERE id = {user_id}")
            return results[0] if results else None

    @Injector.singleton
    class UserService:
        @Injector.inject
        def __init__(self, repository: Provide[UserRepository]):
            self.repository = repository

        def get_user_data(self, user_id: int) -> Dict[str, str]:
            user = self.repository.find_user(user_id)
            if not user:
                return {"error": "User not found"}
            return user

    @Injector.inject
    def user_api(user_id: int, service: Provide[UserService]) -> Dict[str, str]:
        return service.get_user_data(user_id)

    result = user_api(user_id=42)
    assert "result" in result
    assert result["result"] == "db:SELECT * FROM users WHERE id = 42"
