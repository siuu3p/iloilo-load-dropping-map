# Rebuild ../index.html from the template, data and base image in this folder.
import base64, pathlib

here = pathlib.Path(__file__).parent
read = lambda n: (here / n).read_text(encoding="utf8")
html = (read("template2.html")
        .replace("__LEAFLETCSS__", read("leaflet.css"))
        .replace("__EVENTS__", read("events.json"))
        .replace("__GEO__", read("geo.json"))
        .replace("__IMG__", "data:image/webp;base64," + base64.b64encode((here / "base.webp").read_bytes()).decode()))
assert "__" not in html.split("<script>")[-1][:200], "unreplaced placeholder"
# Leaflet goes in last so the replacements above never scan its source
html = html.replace("__LEAFLETJS__", read("leaflet.js"))
assert "__LEAFLETJS__" not in html, "unreplaced placeholder"
(here.parent / "index.html").write_text(html, encoding="utf8")
print("built", len(html) // 1024, "KB")
