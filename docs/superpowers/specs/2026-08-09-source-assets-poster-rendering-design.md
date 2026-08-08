# Source Assets Poster Rendering Design

## Goal

Improve poster fidelity by rendering equations and tables from their source
LaTeX and figures from their source PDF. Keep poster generation robust by
falling back to existing PNG assets only when the preferred source asset
cannot be compiled or read.

## Scope

- Preserve the existing three-column poster structure and panel order.
- Prefer source LaTeX for equations and tables.
- Prefer source PDF for figures.
- Increase body-text line spacing from `1.05` to `1.15`.
- Preserve every row and column of selected tables, especially primary
  experimental tables.
- Do not change content selection, RAG, summarization, or panel ordering.

## Asset Selection

### Figures

Use `pdf_path` when it points to a readable PDF. Insert it with
`\includegraphics` using `keepaspectratio`, without cropping. If the PDF is
missing or invalid, use `png_path`.

### Equations

Use `tex_file` as the preferred source. Copy a normalized fragment into
`poster/latex/assets/equations/` and include that fragment from the panel.
Wrap bare expressions in display math. Fragments that already contain an
appropriate math environment must not receive a duplicate math wrapper.
If isolated compilation fails after loading the paper environment, use
`png_file` and record the fallback.

### Tables

Use `tex_file` as the preferred source. Copy a normalized fragment into
`poster/latex/assets/tables/` and include the entire fragment inside a
width-constrained box. Scale to `\linewidth` while retaining every source row
and column; never crop or extract only selected rows.

A selected table with asset importance `5` is treated as a primary
experimental table. Its completeness has priority over column-height balance.
If it causes overflow, report the overflow during layout review rather than
silently removing content. Compilation failure falls back to `png_file` and is
logged.

## Paper LaTeX Environment

Search `output/arxiv/<paper_id>/source` for the paper master document. Reuse
the paper preamble definitions needed by asset fragments, including packages,
custom commands, environments, and colors. Do not import the paper's page
geometry, title construction, document body, or document class into the poster
document.

Each source fragment is validated independently before it is selected for the
poster. Validation uses XeLaTeX with shell escape disabled. A validation error
must include the paper ID, asset ID, source path, and a concise LaTeX error in
the log. The rendering pipeline then selects the PNG fallback and continues.

## Layout Metrics

Asset metadata in `poster_layout.json` records both the preferred source path
and fallback path, together with the selected render mode (`tex`, `pdf`, or
`png`). Figure aspect-ratio estimation uses the existing PNG dimensions when
necessary; the final rendering still uses the source PDF.

Body line spacing is configured as `1.15`. The same value drives estimated
text height and the rendered `\fontsize{font size}{line height}` so that layout
estimation and TeX output remain consistent.

Panel order is immutable. Column splitting may rebalance only at boundaries
between contiguous panels. Primary-table completeness outranks the target
column utilization and height-difference goals.

## Template Behavior

The panel template dispatches by asset render mode:

- `pdf` and `png`: `\includegraphics` with width and height bounds and
  `keepaspectratio`.
- equation `tex`: centered `\input` of the normalized equation fragment.
- table `tex`: centered, complete `\input` constrained to `\linewidth`.

Captions remain omitted in this change to avoid consuming poster space and to
keep the scope focused on source fidelity.

## Failure Handling

- Missing source PDF: select PNG and log a warning.
- Missing source TeX: select PNG and log a warning.
- Source fragment validation failure: select PNG and log the LaTeX failure.
- Missing preferred and fallback assets: raise an error with paper and asset
  IDs; do not silently drop a selected poster asset.
- Primary table overflow: preserve the table and report overflow for review.

## Verification

Automated tests must cover:

1. Figures select PDF and fall back to PNG when PDF is unavailable.
2. Equations and tables select source TeX and preserve their source content.
3. A failing source fragment selects PNG without stopping the paper pipeline.
4. A primary experimental table is not truncated.
5. Relative output directories compile correctly.
6. Estimated and rendered line spacing both use `1.15`.
7. Three column previews and the final poster compile with XeLaTeX.

