#!/usr/bin/env bash
# DOCUMENTO.md -> build/doc.html -> DOCUMENTO.pdf (Python-Markdown + WeasyPrint). Falha se passar de 5 páginas.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
uv run --no-project --with markdown --with weasyprint python - <<'PY'
from pathlib import Path
import re
import markdown
from weasyprint import HTML

# smarty: aspas curvas e reticências reais, sem mexer no .md
body = markdown.markdown(Path("DOCUMENTO.md").read_text(encoding="utf-8"),
                         extensions=["tables", "fenced_code", "smarty"])
# espaço não separável entre número e unidade (fora de <pre>, para não desalinhar o diagrama)
UNIT = re.compile(r"(\d) (h|min|dias?|semanas?|GB|vCPU|p\.p\.|caracteres|leads?|conversas)\b|(US\$) (?=\d)")
body = "".join(part if part.startswith("<pre") else UNIT.sub(lambda m: f"{m[1] or m[3]} {m[2] or ''}", part)
               for part in re.split(r"(<pre.*?</pre>)", body, flags=re.S))
html = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<title>Rastreamento antes do CRM - Miguel Sanz Boragan</title>'
        f'<link rel="stylesheet" href="../print.css"></head><body>{body}</body></html>')
Path("build/doc.html").write_text(html, encoding="utf-8")
HTML("build/doc.html").write_pdf("DOCUMENTO.pdf")
PY
pages=$(pdfinfo DOCUMENTO.pdf | awk '/^Pages:/ {print $2}')
echo "DOCUMENTO.pdf: ${pages} páginas, $(wc -w < DOCUMENTO.md) palavras no .md"
if [ "$pages" -gt 5 ]; then echo "ERRO: passou de 5 páginas" >&2; exit 1; fi
