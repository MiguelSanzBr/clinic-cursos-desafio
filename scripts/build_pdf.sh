#!/usr/bin/env bash
# DOCUMENTO.md -> build/doc.html -> DOCUMENTO.pdf (Python-Markdown + WeasyPrint). Falha se passar de 5 páginas.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
uv run --no-project --with markdown --with weasyprint python - <<'PY'
from pathlib import Path
import markdown
from weasyprint import HTML

body = markdown.markdown(Path("DOCUMENTO.md").read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
html = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<title>Rastreamento antes do CRM - Miguel Sanz Boragan</title>'
        f'<link rel="stylesheet" href="../print.css"></head><body>{body}</body></html>')
Path("build/doc.html").write_text(html, encoding="utf-8")
HTML("build/doc.html").write_pdf("DOCUMENTO.pdf")
PY
pages=$(pdfinfo DOCUMENTO.pdf | awk '/^Pages:/ {print $2}')
echo "DOCUMENTO.pdf: ${pages} páginas, $(wc -w < DOCUMENTO.md) palavras no .md"
if [ "$pages" -gt 5 ]; then echo "ERRO: passou de 5 páginas" >&2; exit 1; fi
