# Rebuild ../blackout-map.html from the template, data and base image in this folder.
import base64, pathlib

here = pathlib.Path(__file__).parent
read = lambda n: (here / n).read_text(encoding="utf8")
html = (read("template2.html")
        .replace("__LEAFLETCSS__", read("leaflet.css"))
        .replace("__EVENTS__", read("events.json"))
        .replace("__GEO__", read("geo.json"))
        .replace("__IMG__", "data:image/jpeg;base64," + base64.b64encode((here / "base.jpg").read_bytes()).decode()))
assert "__" not in html.split("<script>")[-1][:200], "unreplaced placeholder"
(here.parent / "blackout-map.html").write_text(html, encoding="utf8")
print("built", len(html) // 1024, "KB")
