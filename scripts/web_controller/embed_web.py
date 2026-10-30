"""Build web/ into web_files.h, so the connect page stays normal HTML, CSS and JS files.

    python embed_web.py
"""
import pathlib

here = pathlib.Path(__file__).parent
out = "// Made by embed_web.py from web/: edit those, not this.\n#pragma once\n\n"
for f in sorted((here / "web").iterdir()):
    name = "WEB_" + f.name.replace(".", "_").upper()
    out += f'static const char {name}[] = R"WEBFILE({f.read_text(encoding="utf-8")})WEBFILE";\n\n'
(here / "web_files.h").write_text(out, encoding="utf-8", newline="\n")
print("made web_files.h")
