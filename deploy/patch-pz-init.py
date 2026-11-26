"""Prepare the image's native launcher for a JVM agent without changing game JARs."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('stock', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
text = a.stock.read_text(encoding='utf-8')
anchor = 'ARGS+=("--")'
if text.count(anchor) != 1 or 'DNTSNE_JAVA_AGENT' in text:
    raise SystemExit('Unexpected or already modified native launcher')
text = text.replace(anchor, '[[ -n "${DNTSNE_JAVA_AGENT:-}" ]] && ARGS+=("${DNTSNE_JAVA_AGENT}")\n'+anchor)
# Native arguments include credentials. Suppress argument-list logging only.
lines = text.splitlines(keepends=True)
text = ''.join(line for line in lines if not ('echo ' in line and 'ARGS[' in line))
with a.output.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(text)
a.output.chmod(0o755)
print('Native launcher prepared; original input preserved')
