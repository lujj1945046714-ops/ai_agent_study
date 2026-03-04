import logging
from typing import Dict, List, Callable, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class HooksRegistry:
    """
    Registry for lifecycle hooks.

    Supported hooks:
    - on_startup, on_shutdown
    - before_message, after_message
    - before_tool, after_tool
    - on_error
    """

    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, hook_name: str, callback: Callable) -> None:
        """
        Register a hook callback.

        Args:
            hook_name: Hook name
            callback: Callback function(context: Dict) -> None
        """
        self._hooks[hook_name].append(callback)

    def unregister(self, hook_name: str, callback: Callable) -> None:
        """
        Unregister a hook callback.

        Args:
            hook_name: Hook name
            callback: Callback to remove
        """
        if hook_name in self._hooks:
            try:
                self._hooks[hook_name].remove(callback)
            except ValueError:
                pass

    def trigger(self, hook_name: str, context: Dict[str, Any]) -> None:
        """
        Trigger all callbacks for a hook.

        Args:
            hook_name: Hook name
            context: Context dict passed to callbacks
        """
        for callback in self._hooks.get(hook_name, []):
            try:
                callback(context)
            except Exception as e:
                logger.error(f"Hook {hook_name} callback failed: {e}", exc_info=True)
