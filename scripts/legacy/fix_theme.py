"""Theme system for TONYAgent using customtkinter."""

from __future__ import annotations

from typing import Callable, Literal

import customtkinter as ctk
from loguru import logger

from tonyagent.config.settings import settings


class ThemeManager:
    """Manages application theming using customtkinter's built-in themes."""

    def __init__(self):
        self._current_mode: str = "system"
        self._observers: list[Callable[[str], None]] = []

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
        """Get a color token value for current theme."""
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
            }
            return light_colors.get(token, light_colors["text_primary"])

    def set_custom_color(self, token: str, value: str) -> None:
        """Set a custom color override (not fully supported in this simple implementation)."""
        # For a full implementation, we would need to create a custom theme JSON file
        pass


# Global theme manager instance
theme_manager = ThemeManager()