"""Theme system for TONYAgent using customtkinter."""

from __future__ import annotations

from typing import Callable, Literal

import customtkinter as ctk
from loguru import logger

from tonyagent.config.settings import settings


#: Tokens that are literal CSS keywords rather than themed colours. They must
#: resolve to themselves in both themes instead of falling back to text_primary.
LITERAL_COLORS = {
    "transparent": "transparent",
    "clear": "transparent",
    "": "transparent",
}


class ThemeManager:
    """Manages application theming using customtkinter's built-in themes."""

    def __init__(self):
        self._current_mode: str = "system"
        self._observers: list[Callable[[str], None]] = []
        self._overrides: dict[str, str] = {}

    def initialize(self) -> None:
        """Initialize the theme system."""
        self._current_mode = settings.ui.theme
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply the current theme to customtkinter."""
        mode = self._current_mode
        if mode == "system":
            ctk.set_appearance_mode("system")
            actual_mode = ctk.get_appearance_mode().lower()
        else:
            ctk.set_appearance_mode(mode)
            actual_mode = mode

        # Use customtkinter's default theme (blue) and just set the mode
        # The default theme has all the required widget keys
        logger.info(f"Applied theme: {actual_mode}")

    def set_theme(self, mode: Literal["light", "dark", "system"]) -> None:
        """Set the theme mode."""
        if mode not in ("light", "dark", "system"):
            raise ValueError(f"Invalid theme mode: {mode}")
        self._current_mode = mode
        settings.ui.theme = mode
        self._apply_theme()
        self._notify_observers(mode)

    def get_theme(self) -> str:
        """Get the current theme mode."""
        return self._current_mode

    def get_actual_theme(self) -> str:
        """Get the actual resolved theme (light/dark)."""
        if self._current_mode == "system":
            return ctk.get_appearance_mode().lower()
        return self._current_mode

    def toggle_theme(self) -> str:
        """Toggle between light and dark."""
        actual = self.get_actual_theme()
        new_mode = "dark" if actual == "light" else "light"
        self.set_theme(new_mode)
        return new_mode

    def register_observer(self, callback: Callable[[str], None]) -> None:
        """Register a callback for theme changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def unregister_observer(self, callback: Callable[[str], None]) -> None:
        """Unregister a theme change callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify_observers(self, mode: str) -> None:
        """Notify all observers of theme change."""
        for callback in self._observers:
            try:
                callback(mode)
            except Exception as e:
                logger.error(f"Theme observer error: {e}")

    def get_color(self, token: str) -> str:
        """Get a color token value for current theme (custom overrides win)."""
        override = self._overrides.get(token)
        if override:
            return override
        actual = self.get_actual_theme()
        # Return default colors based on theme
        if actual == "dark":
            dark_colors = {
                "primary": "#3B82F6",
                "primary_hover": "#60A5FA",
                "primary_active": "#93C5FD",
                "secondary": "#94A3B8",
                "secondary_hover": "#CBD5E1",
                "surface": "#1E293B",
                "surface_hover": "#334155",
                "surface_active": "#475569",
                "background": "#0F172A",
                "background_secondary": "#1E293B",
                "border": "#334155",
                "border_focus": "#3B82F6",
                "text_primary": "#F8FAFC",
                "text_secondary": "#CBD5E1",
                "text_muted": "#64748B",
                "text_on_primary": "#0F172A",
                "success": "#34D399",
                "success_bg": "#064E3B",
                "warning": "#FBBF24",
                "warning_bg": "#78350F",
                "error": "#F87171",
                "error_bg": "#7F1D1D",
                "info": "#60A5FA",
                "info_bg": "#1E3A5F",
                "shadow": "rgba(0, 0, 0, 0.3)",
                "overlay": "rgba(0, 0, 0, 0.7)",
                # Chat bubbles. The user's own message uses the primary tint so
                # it reads as "outgoing" without needing a label to explain it.
                "bubble_user": "#1E3A8A",
                "bubble_user_text": "#EFF6FF",
                "bubble_ai": "#1E293B",
                "bubble_ai_text": "#E2E8F0",
                "bubble_error": "#7F1D1D",
                "bubble_error_text": "#FECACA",
            }
            return dark_colors.get(token, dark_colors["text_primary"])
        else:
            light_colors = {
                "primary": "#2563EB",
                "primary_hover": "#1D4ED8",
                "primary_active": "#1E40AF",
                "secondary": "#64748B",
                "secondary_hover": "#475569",
                "surface": "#FFFFFF",
                "surface_hover": "#F8FAFC",
                "surface_active": "#F1F5F9",
                "background": "#F8FAFC",
                "background_secondary": "#FFFFFF",
                "border": "#E2E8F0",
                "border_focus": "#2563EB",
                "text_primary": "#0F172A",
                "text_secondary": "#475569",
                "text_muted": "#94A3B8",
                "text_on_primary": "#FFFFFF",
                "success": "#059669",
                "success_bg": "#ECFDF5",
                "warning": "#D97706",
                "warning_bg": "#FFF8ED",
                "error": "#DC2626",
                "error_bg": "#FEF2F2",
                "info": "#2563EB",
                "info_bg": "#EFF6FF",
                "shadow": "rgba(0, 0, 0, 0.1)",
                "overlay": "rgba(0, 0, 0, 0.5)",
                "bubble_user": "#DBEAFE",
                "bubble_user_text": "#1E3A8A",
                "bubble_ai": "#FFFFFF",
                "bubble_ai_text": "#0F172A",
                "bubble_error": "#FEF2F2",
                "bubble_error_text": "#991B1B",
            }
            return light_colors.get(token, light_colors["text_primary"])

    def get_color_pair(self, token: str) -> tuple[str, str]:
        """Return a (light, dark) pair, i.e. a customtkinter color tuple.

        Use this for text_color / fg_color so widgets keep following the theme
        instead of being frozen into a single hex value.
        """
        # Literal CSS keywords are their own value in both themes. Without this
        # an unknown token fell through to ``text_primary``, so "transparent"
        # resolved to near-white in dark mode and ghost/secondary buttons turned
        # into white-on-white blocks that were only visible on hover.
        if token in LITERAL_COLORS:
            return (LITERAL_COLORS[token], LITERAL_COLORS[token])
        override = self._overrides.get(token)
        if override:
            return (override, override)
        previous = self._current_mode
        try:
            self._current_mode = "light"
            light = self.get_color(token)
            self._current_mode = "dark"
            dark = self.get_color(token)
        finally:
            self._current_mode = previous
        return (light, dark)

    def set_custom_color(self, token: str, value: str) -> None:
        """Override a color token and refresh observers so the change is visible."""
        self._overrides[token] = value
        self._notify_observers(self._current_mode)

    def clear_custom_colors(self) -> None:
        """Drop every custom color override."""
        self._overrides.clear()
        self._notify_observers(self._current_mode)


# Global theme manager instance
theme_manager = ThemeManager()