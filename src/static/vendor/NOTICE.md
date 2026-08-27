# Third-Party Libraries

This directory contains vendored copies of third-party JavaScript libraries used by the application.

| Library | Version | Source | License |
| --- | --- | --- | --- |
| DOMPurify | 3.2.7 | https://cdn.jsdelivr.net/npm/dompurify@3.2.7/dist/purify.min.js | Apache-2.0 / MPL-2.0 |
| marked | 15.0.12 | https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js | MIT |
| mermaid | 11.x | https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js | MIT |
| KaTeX | 0.16.22 | https://registry.npmjs.org/katex/-/katex-0.16.22.tgz | MIT |

## KaTeX Layout

`katex/` 包含完整发布包：`katex.min.js`、`katex.min.css`、`contrib/auto-render.min.js`、
`contrib/mhchem.min.js`、`fonts/`。字体目录必须与 `katex.min.css` 的相对路径引用保持一致，
更新时请整目录同步替换并保留 LICENSE（MIT）。

## Update Instructions

1. Replace the `.min.js` file with the new version from jsDelivr or npm.
2. Update the version in this NOTICE.md.
3. Verify the application renders Markdown, Mermaid charts, KaTeX math, and SVG previews correctly.
