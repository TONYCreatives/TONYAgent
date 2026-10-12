"""How does Tencent Yuanbao's desktop pet get a non-rectangular window?

It is running on this machine, floating over the wallpaper with no rectangle around
it -- a shipping example of exactly the thing this repository is stuck on. So it can
be asked directly, and none of the answers depend on reading their code:

* **The window's styles** decide the mechanism. `WS_EX_LAYERED` plus no window region
  means per-pixel alpha (a smooth rim is then free); a region means a hard clipped
  rim; `WS_EX_NOREDIRECTIONBITMAP` means a composition surface.
* **The process's modules** say what is drawing it: Chromium/CEF/Electron, Qt, .NET,
  or a native Direct2D/Skia renderer. A webview route that works is worth more to us
  than a native one, because our pet is a page.
* **The pixels at the edge** corroborate it: a layered window shows blended pixels
  between the character and the wallpaper; a clipped one does not.

Writes .tmp-yuanbao.json and prints a summary.
"""

import ctypes
import json
import pathlib
import time
from ctypes import wintypes

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
psapi = ctypes.windll.psapi
kernel32 = ctypes.windll.kernel32

GWL_EXSTYLE = -20
WS_EX_FLAGS = {
    "topmost": 0x00000008,
    "transparent": 0x00000020,
    "toolwindow": 0x00000080,
    "layered": 0x00080000,
    "noactivate": 0x08000000,
    "noredirectionbitmap": 0x00200000,
}
REGIONS = {0: "none", 1: "empty", 2: "rect", 3: "complex"}

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

#: Module names that identify a rendering stack. Substring matches, lowercased.
TOOLKITS = {
    "libcef": "CEF (Chromium embedded)",
    "chrome_elf": "Chromium",
    "electron": "Electron",
    "node.dll": "Electron/Node",
    "msedgewebview2": "WebView2",
    "webview2loader": "WebView2",
    "qt6": "Qt 6",
    "qt5": "Qt 5",
    "coreclr": "NET Core/.NET",
    "clr.dll": ".NET Framework",
    "wxbase": "wxWidgets",
    "sdl2": "SDL2",
    "d3d11": "Direct3D 11",
    "d3d12": "Direct3D 12",
    "dcomp": "DirectComposition",
    "d2d1": "Direct2D",
    "libegl": "ANGLE/GPU",
    "libglesv2": "ANGLE/GPU",
    "skia": "Skia",
    "nvwgf2umx": "NVIDIA driver",
}

CANDIDATE_NAMES = ("yuanbao", "tencent", "qq", "txgame", "yuan")


def process_path(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def process_modules(pid: int) -> list[str]:
    """The loaded DLLs, which is what names the rendering stack."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return []
    try:
        needed = wintypes.DWORD()
        if not psapi.EnumProcessModules(handle, None, 0, ctypes.byref(needed)):
            return []
        count = needed.value // ctypes.sizeof(ctypes.c_void_p)
        modules = (ctypes.c_void_p * count)()
        if not psapi.EnumProcessModules(
            handle, modules, ctypes.sizeof(modules), ctypes.byref(needed)
        ):
            return []
        names = []
        for module in modules:
            name = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(handle, ctypes.c_void_p(module), name, 260):
                names.append(name.value)
        return names
    finally:
        kernel32.CloseHandle(handle)


def layered_attributes(hwnd: int) -> dict:
    """The colour key / alpha, when the window is layered."""
    key = wintypes.DWORD()
    alpha = wintypes.BYTE()
    flags = wintypes.DWORD()
    ok = user32.GetLayeredWindowAttributes(
        wintypes.HWND(hwnd), ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)
    )
    if not ok:
        return {"readable": False}
    return {
        "readable": True,
        "colour_key": hex(key.value) if flags.value & 0x1 else None,
        "alpha": alpha.value if flags.value & 0x2 else None,
        "flags": hex(flags.value),
    }


def children(hwnd: int, depth: int = 0, out: list | None = None) -> list:
    out = [] if out is None else out
    found: list[int] = []

    def visit(child, _lparam):
        found.append(int(child))
        return True

    user32.EnumChildWindows(wintypes.HWND(hwnd), WNDENUMPROC(visit), 0)
    for child in found:
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(child), name, 256)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(child), ctypes.byref(box))
        out.append(
            {
                "depth": depth,
                "class": name.value,
                "rect": [box.left, box.top, box.right - box.left, box.bottom - box.top],
                "visible": bool(user32.IsWindowVisible(wintypes.HWND(child))),
            }
        )
        children(child, depth + 1, out)
    return out


def edge_blend(hwnd: int) -> dict:
    """Is the rim blended into the wallpaper, or cut?

    A layered window with per-pixel alpha leaves partially-covered pixels along the
    edge; a clipped one jumps straight from the character to the wallpaper. Measured
    as the number of *distinct* colours in a two-pixel band just inside the bounding
    box against a band well inside the body: a hard edge over a photograph still has
    many colours from the photograph, so the useful number is the count of colours
    that are neither the body colour nor within a small distance of the neighbouring
    background sample.
    """
    from PIL import ImageGrab

    box = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
    left, top = box.left, box.top
    width, height = box.right - left, box.bottom - top
    if width < 8 or height < 8:
        return {}
    image = ImageGrab.grab(bbox=(left, top, box.right, box.bottom), all_screens=True)
    colours = image.convert("RGB").getcolors(maxcolors=1 << 24) or []
    unique = len(colours)
    return {
        "rect": [left, top, width, height],
        "unique_colours": unique,
        "top_left_pixel": image.getpixel((0, 0))[:3],
        "centre_pixel": image.getpixel((width // 2, height // 2))[:3],
        "outside_pixel": ImageGrab.grab(
            bbox=(left - 4, top - 4, left - 3, top - 3), all_screens=True
        ).getpixel((0, 0))[:3],
    }


def main() -> None:
    windows: list[dict] = []

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        path = process_path(pid.value)
        box = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(box))
        width, height = box.right - box.left, box.bottom - box.top
        klass = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(hwnd), klass, 256)
        user32.GetWindowTextW(wintypes.HWND(hwnd), title, 256)
        ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
        windows.append(
            {
                "hwnd": int(hwnd),
                "pid": pid.value,
                "process": pathlib.Path(path).name if path else "",
                "path": path,
                "class": klass.value,
                "title": title.value,
                "rect": [box.left, box.top, width, height],
                "ex_style": hex(ex),
                "styles": [name for name, bit in WS_EX_FLAGS.items() if ex & bit],
                "layered_attrs": layered_attributes(int(hwnd)),
                "region": REGIONS.get(
                    user32.GetWindowRgn(
                        wintypes.HWND(hwnd), gdi32.CreateRectRgn(0, 0, 1, 1)
                    ),
                    "?",
                ),
            }
        )
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)

    suspects = [
        info
        for info in windows
        if any(word in (info["process"] + info["path"]).lower() for word in CANDIDATE_NAMES)
    ]
    report: dict = {"suspects": suspects}

    for info in suspects:
        info["children"] = children(info["hwnd"])
        info["modules"] = process_modules(info["pid"])
        info["toolkits"] = sorted(
            {
                label
                for module in info["modules"]
                for token, label in TOOLKITS.items()
                if token in module.lower()
            }
        )
    # The pet is the small always-on-top one; probe the smallest suspect.
    floats = [info for info in suspects if 40 <= info["rect"][2] <= 420 and 40 <= info["rect"][3] <= 420]
    if floats:
        smallest = min(floats, key=lambda info: info["rect"][2] * info["rect"][3])
        report["probed"] = smallest["hwnd"]
        time.sleep(0.2)
        report["edge"] = edge_blend(smallest["hwnd"])

    pathlib.Path(".tmp-yuanbao.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    for info in suspects:
        print(
            f"pid={info['pid']:<7} {info['process']:<22} class={info['class'][:26]:26} "
            f"rect={info['rect']} styles={info['styles']} layered={info['layered_attrs']} "
            f"region={info['region']}"
        )
        if info["toolkits"]:
            print("    toolkits:", ", ".join(info["toolkits"]))
        for child in info["children"][:6]:
            print(f"      child d{child['depth']} {child['class'][:34]:34} rect={child['rect']}")
    if "edge" in report:
        print("edge probe:", json.dumps(report["edge"], default=str))


if __name__ == "__main__":
    main()
