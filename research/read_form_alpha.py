import json
import pathlib

d = json.loads(pathlib.Path(".tmp-form-alpha.json").read_text(encoding="utf-8"))
print("native:", d.get("native_type"), "| error:", d.get("error"))
for key in ("before", "after_form_transparent", "after_browser_transparent"):
    s = d.get(key)
    if not s:
        continue
    print(key, "-> corners", s["corners"], "centre", s["centre"], "colours", s["unique_colours"])
print("browser background:", d.get("browser_default_background"))
print("--- controls as found ---")
for c in d.get("controls_before", []):
    print("   ", "  " * c["depth"], c["type"], "| BackColor", c["back_colour"])
print("--- after making them transparent ---")
for c in d.get("controls_after", []):
    print("   ", "  " * c["depth"], c["type"], "|", c.get("set_transparent"), "| was", c["back_colour"])
