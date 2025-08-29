import pytest
from typing import Any, List, Dict

from smalldi.annotation import _Provide, Provide


def test_provide_unwrap_valid():
    """Test unwrapping valid Provide annotations"""
    assert _Provide.unwrap(Provide[str]) is str
    assert _Provide.unwrap(Provide[int]) is int
    assert _Provide.unwrap(Provide[List[int]]) is List[int]
    assert _Provide.unwrap(Provide[Dict[str, Any]]) is Dict[str, Any]


def test_provide_unwrap_invalid():
    """Test unwrapping invalid annotations raises TypeError"""
    with pytest.raises(TypeError):
        _Provide.unwrap(str)

    with pytest.raises(TypeError):
        _Provide.unwrap(int)

    with pytest.raises(TypeError):
        _Provide.unwrap(List[int])

    with pytest.raises(TypeError):
        _Provide.unwrap(None)

def test_iter_annotations_empty():
    """Test iteration over function without Provide annotations"""
    def func(a: str, b: int):
        pass

    annotations = list(_Provide.iter_annotations(func))
    assert len(annotations) == 0
