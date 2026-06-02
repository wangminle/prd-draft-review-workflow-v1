# Third-Party Libraries

This directory contains vendored copies of third-party JavaScript libraries used by the application.

| Library | Version | Source | License |
| --- | --- | --- | --- |
| DOMPurify | 3.2.7 | https://cdn.jsdelivr.net/npm/dompurify@3.2.7/dist/purify.min.js | Apache-2.0 / MPL-2.0 |
| marked | 15.0.12 | https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js | MIT |
| mermaid | 11.x | https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js | MIT |

## Update Instructions

1. Replace the `.min.js` file with the new version from jsDelivr or npm.
2. Update the version in this NOTICE.md.
3. Verify the application renders Markdown and Mermaid charts correctly.
