"""Custom pill-shaped widgets for TONYAgent."""

from __future__ import annotations

import customtkinter as ctk
from typing import Any, Callable, Optional

from tonyagent.ui.theme import theme_manager

# Every pill widget resolves its colors from theme_manager, so the palette in
# theme.py is actually used instead of customtkinter's built-in greys. Colors are
# always (light, dark) tuples, which keeps widgets following the theme live.
_TOKEN_FG = {
    "PillFrame": "surface",
    "PillScrollableFrame": "background",
}
_TOKEN_TEXT = {
    "PillLabel": "text_primary",
    "PillButton": "text_primary",
    "PillEntry": "text_primary",
    "PillComboBox": "text_primary",
    "PillTextbox": "text_primary",
}


def _pair(token: str) -> tuple:
    """Resolve a theme token to a (light, dark) color pair."""
    return theme_manager.get_color_pair(token)


def themed(widget: ctk.CTkBaseClass) -> ctk.CTkBaseClass:
    """Re-apply theme colors to a widget after a theme change."""
    cls = type(widget).__name__
    try:
        if cls in ("PillFrame", "PillScrollableFrame"):
            if getattr(widget, "_transparent", False):
                return widget
            widget.configure(fg_color=_pair(_TOKEN_FG[cls]))
        elif cls == "PillTextbox":
            widget.configure(
                fg_color=_pair("surface"),
                text_color=_pair("text_primary"),
            )
        elif cls == "PillLabel":
            if getattr(widget, "_uses_token", False):
                widget.configure(text_color=_pair(_TOKEN_TEXT[cls]))
        elif cls in ("PillButton", "PrimaryPillButton", "SecondaryPillButton",
                     "DangerPillButton", "GhostPillButton"):
            _restyle_button(widget)
        elif cls in ("PillEntry", "PillComboBox", "PillOptionMenu"):
            widget.configure(
                fg_color=_pair("surface"),
                border_color=_pair("border"),
                text_color=_pair("text_primary"),
                button_color=_pair("primary_hover")
                if cls == "PillEntry" else _pair("secondary"),
            )
    except Exception:
        pass
    return widget


def _restyle_button(widget) -> None:
    """Re-resolve a pill button's colors from its variant."""
    kind = type(widget).__name__
    if kind == "PrimaryPillButton":
        fg, hover, text = "primary", "primary_hover", "text_on_primary"
    elif kind == "DangerPillButton":
        fg, hover, text = "error", "error", "text_on_primary"
    elif kind == "SecondaryPillButton":
        fg, hover, text = "transparent", "surface_hover", "text_primary"
    else:
        fg, hover, text = "transparent", "surface_hover", "text_secondary"
    try:
        widget.configure(
            fg_color=_pair(fg),
            hover_color=_pair(hover),
            text_color=_pair(text),
        )
    except Exception:
        pass

class PillButton(ctk.CTkButton):
    """A pill-shaped button with consistent styling."""

    def __init__(
        self,
        master: Any,
        text: str = "",
        command: Optional[Callable] = None,
        width: int = 120,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        fg_color: Optional[str] = None,
        hover_color: Optional[str] = None,
        text_color: Optional[str] = None,
        border_width: int = 0,
        border_color: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            master,
            text=text,
            command=command,
            width=width,
            height=height,
            corner_radius=corner_radius,
            font=font,
            fg_color=fg_color,
            hover_color=hover_color,
            text_color=text_color,
            border_width=border_width,
            border_color=border_color,
            **kwargs
        )


class PrimaryPillButton(PillButton):
    """Primary action button - filled primary color."""

    def __init__(self, master: Any, **kwargs):
        super().__init__(
            master,
            fg_color=kwargs.pop("fg_color", None),
            hover_color=kwargs.pop("hover_color", None),
            text_color=kwargs.pop("text_color", "#FFFFFF"),
            border_width=kwargs.pop("border_width", 0),
            **kwargs
        )


class SecondaryPillButton(PillButton):
    """Secondary action button - outlined style."""

    def __init__(self, master: Any, **kwargs):
        super().__init__(
            master,
            fg_color=kwargs.pop("fg_color", "transparent"),
            hover_color=kwargs.pop("hover_color", None),
            border_width=kwargs.pop("border_width", 1),
            border_color=kwargs.pop("border_color", None),
            text_color=kwargs.pop("text_color", None),
            **kwargs
        )


class DangerPillButton(PillButton):
    """Danger/destructive action button - red."""

    def __init__(self, master: Any, **kwargs):
        super().__init__(
            master,
            fg_color=kwargs.pop("fg_color", "#DC2626"),
            hover_color=kwargs.pop("hover_color", "#EF4444"),
            text_color=kwargs.pop("text_color", "#FFFFFF"),
            **kwargs
        )


class GhostPillButton(PillButton):
    """Ghost button - minimal style for secondary actions."""

    def __init__(self, master: Any, **kwargs):
        super().__init__(
            master,
            fg_color=kwargs.pop("fg_color", "transparent"),
            hover_color=kwargs.pop("hover_color", None),
            text_color=kwargs.pop("text_color", None),
            border_width=0,
            **kwargs
        )


class PillEntry(ctk.CTkEntry):
    """A pill-shaped entry field."""

    def __init__(
        self,
        master: Any,
        placeholder_text: str = "",
        width: int = 200,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        show: str = "",
        **kwargs
    ):
        super().__init__(
            master,
            placeholder_text=placeholder_text,
            width=width,
            height=height,
            corner_radius=corner_radius,
            font=font,
            show=show,
            border_width=1,
            **kwargs
        )


#: Values ``CTkComboBox.get()`` returns when no value has actually been set.
#: customtkinter falls back to the widget's class name in that state, and that
#: string used to travel all the way into an API request as a model id.
_UNSET_SENTINELS = frozenset(
    {
        "CTkComboBox",
        "CTkOptionMenu",
        "CTkSegmentedButton",
        "PillComboBox",
        "PillOptionMenu",
        "PillSegmentedButton",
    }
)


class PillComboBox(ctk.CTkComboBox):
    """A pill-shaped combo box."""

    def __init__(
        self,
        master: Any,
        values: Optional[list[str]] = None,
        width: int = 200,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        dropdown_font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            values=list(values) if values else [],
            width=width,
            height=height,
            corner_radius=corner_radius,
            font=font,
            dropdown_font=dropdown_font,
            border_width=1,
            button_color=kwargs.pop("button_color", None),
            button_hover_color=kwargs.pop("button_hover_color", None),
            **kwargs
        )

    def get(self) -> str:
        """Return the current value, or "" when nothing is actually selected.

        ``CTkComboBox.get()`` falls back to the string ``"CTkComboBox"`` (its
        own class name) when no value has been set, which is the state a combo
        starts in when built with ``values=[]``. That sentinel then flowed
        straight into the provider factory and was sent to the API as a model
        id, producing "CTkComboBox is not a valid model ID".

        Treating "unset" as empty keeps the bug at the widget boundary instead
        of relying on every call site to remember the quirk.
        """
        try:
            value = super().get()
        except Exception:
            return ""
        if not isinstance(value, str):
            return ""
        # The customtkinter unset sentinel, and anything that is not a
        # plausible value we were actually given.
        if value in _UNSET_SENTINELS or not value.strip():
            return ""
        return value


class PillFrame(ctk.CTkFrame):
    """A pill-shaped frame/container."""

    def __init__(
        self,
        master: Any,
        corner_radius: int = 12,
        fg_color: Optional[str] = None,
        border_width: int = 0,
        border_color: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            master,
            corner_radius=corner_radius,
            fg_color=fg_color,
            border_width=border_width,
            border_color=border_color,
            **kwargs
        )


class PillScrollableFrame(ctk.CTkScrollableFrame):
    """A pill-shaped scrollable frame."""

    def __init__(
        self,
        master: Any,
        corner_radius: int = 12,
        fg_color: Optional[str] = None,
        border_width: int = 0,
        border_color: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            master,
            corner_radius=corner_radius,
            fg_color=fg_color,
            border_width=border_width,
            border_color=border_color,
            **kwargs
        )


class PillTextbox(ctk.CTkTextbox):
    """A pill-shaped text box."""

    def __init__(
        self,
        master: Any,
        width: int = 400,
        height: int = 200,
        corner_radius: int = 12,
        font: tuple = ("Consolas", 12),
        wrap: str = "word",
        **kwargs
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            corner_radius=corner_radius,
            font=font,
            wrap=wrap,
            border_width=1,
            activate_scrollbars=True,
            **kwargs
        )


class PillLabel(ctk.CTkLabel):
    """A label with consistent styling."""

    def __init__(
        self,
        master: Any,
        text: str = "",
        font: tuple = ("Segoe UI", 13),
        text_color: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            master,
            text=text,
            font=font,
            text_color=text_color,
            **kwargs
        )


class PillSegmentedButton(ctk.CTkSegmentedButton):
    """A pill-shaped segmented button."""

    def __init__(
        self,
        master: Any,
        values: Optional[list[str]] = None,
        width: int = 300,
        height: int = 36,
        corner_radius: int = 18,
        font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            values=list(values) if values else [],
            width=width,
            height=height,
            corner_radius=corner_radius,
            font=font,
            **kwargs
        )


class PillSwitch(ctk.CTkSwitch):
    """A pill-shaped switch/toggle."""

    def __init__(
        self,
        master: Any,
        text: str = "",
        width: int = 60,
        height: int = 30,
        corner_radius: int = 100,
        font: tuple = ("Segoe UI", 13),
        **kwargs
    ):
        super().__init__(
            master,
            text=text,
            width=width,
            height=height,
            corner_radius=corner_radius,
            font=font,
            **kwargs
        )


class PillSlider(ctk.CTkSlider):
    """A pill-shaped slider."""

    def __init__(
        self,
        master: Any,
        width: int = 200,
        height: int = 16,
        corner_radius: int = 100,
        **kwargs
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            corner_radius=corner_radius,
            **kwargs
        )


class PillProgressBar(ctk.CTkProgressBar):
    """A pill-shaped progress bar."""

    def __init__(
        self,
        master: Any,
        width: int = 200,
        height: int = 12,
        corner_radius: int = 100,
        **kwargs
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            corner_radius=corner_radius,
            **kwargs
        )


class ToolTip:
    """Simple tooltip for widgets."""

    def __init__(self, widget: ctk.CTkBaseClass, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip: Optional[ctk.CTkToplevel] = None
        self.after_id: Optional[str] = None

        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
        widget.bind("<ButtonPress>", self._on_leave)

    def _on_enter(self, event=None):
        self.after_id = self.widget.after(self.delay, self._show_tooltip)

    def _on_leave(self, event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        self._hide_tooltip()

    def _show_tooltip(self):
        if self.tooltip:
            return

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tooltip = ctk.CTkToplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        self.tooltip.attributes("-topmost", True)

        from tonyagent.ui.theme import theme_manager as _tm

        label = ctk.CTkLabel(
            self.tooltip,
            text=self.text,
            corner_radius=6,
            fg_color=_tm.get_color_pair("surface_active"),
            text_color=_tm.get_color_pair("text_primary"),
            padx=8,
            pady=4,
            font=("Segoe UI", 11),
        )
        label.pack()

    def _hide_tooltip(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


# --- Auto-styling -----------------------------------------------------------
# Wrap each pill class so the theme tokens are applied once at construction,
# instead of duplicating color lookups across eight class bodies. A widget that
# was given an explicit fg_color keeps it; only defaulted widgets are themed.
_AUTO = [
    "PillFrame", "PillScrollableFrame", "PillLabel", "PillTextbox",
    "PillComboBox", "PillOptionMenu", "PillEntry", "PillButton",
    "PrimaryPillButton", "SecondaryPillButton", "DangerPillButton",
    "GhostPillButton",
]


def _wrap(cls):
    original = cls.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        try:
            themed(self)
        except Exception:
            pass

    __init__.__doc__ = original.__doc__
    cls.__init__ = __init__
    return cls


for _name in _AUTO:
    _cls = globals().get(_name)
    if _cls is not None and issubclass(_cls, ctk.CTkBaseClass):
        _wrap(_cls)
