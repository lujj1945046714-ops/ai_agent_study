import pytest
from core.gateway.hooks import HooksRegistry


def test_register_hook():
    """Can register a hook"""
    hooks = HooksRegistry()
    called = []

    def callback(context):
        called.append(context)

    hooks.register("on_startup", callback)
    hooks.trigger("on_startup", {"data": "test"})

    assert len(called) == 1
    assert called[0] == {"data": "test"}


def test_trigger_multiple_hooks():
    """Multiple hooks execute in order"""
    hooks = HooksRegistry()
    order = []

    def callback1(ctx):
        order.append(1)

    def callback2(ctx):
        order.append(2)

    hooks.register("before_tool", callback1)
    hooks.register("before_tool", callback2)
    hooks.trigger("before_tool", {})

    assert order == [1, 2]


def test_unregister_hook():
    """Can unregister a hook"""
    hooks = HooksRegistry()
    called = []

    def callback(ctx):
        called.append(1)

    hooks.register("on_error", callback)
    hooks.unregister("on_error", callback)
    hooks.trigger("on_error", {})

    assert len(called) == 0


def test_trigger_nonexistent_hook():
    """Triggering nonexistent hook does nothing"""
    hooks = HooksRegistry()

    # Should not raise error
    hooks.trigger("nonexistent", {})


def test_hook_exception_handling():
    """Hook exceptions are caught and logged"""
    hooks = HooksRegistry()
    called = []

    def bad_callback(ctx):
        raise ValueError("Hook error")

    def good_callback(ctx):
        called.append(1)

    hooks.register("after_tool", bad_callback)
    hooks.register("after_tool", good_callback)

    # Should not raise, good_callback should still run
    hooks.trigger("after_tool", {})

    assert len(called) == 1
