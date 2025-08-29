import pytest

from smalldi.wrappers import staticclass


def test_staticclass_basic():
    """Test that staticclass prevents instantiation"""
    @staticclass
    class TestClass:
        @classmethod
        def class_method(cls):
            return "class method"

        @staticmethod
        def static_method():
            return "static method"

    with pytest.raises(TypeError):
        TestClass()

    assert TestClass.class_method() == "class method"
    assert TestClass.static_method() == "static method"


def test_staticclass_preserves_metadata():
    """Test that staticclass preserves class metadata"""
    @staticclass
    class TestClass:
        """Test docstring"""
        class_var = "class variable"

        @classmethod
        def method(cls):
            """Method docstring"""
            return cls.class_var

    assert TestClass.__name__ == "TestClass"
    assert TestClass.__doc__ == "Test docstring"
    assert TestClass.class_var == "class variable"
    assert TestClass.method.__doc__ == "Method docstring"
    assert TestClass.method() == "class variable"
