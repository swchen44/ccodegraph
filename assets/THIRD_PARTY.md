# Third-party vendored assets

These UMD bundles are embedded verbatim (`go:embed`) to keep `ccodegraph.py viz --format html2d|html3d` a single offline file. No network at runtime.

| File | Package | License | Source |
|------|---------|---------|--------|
| `fg2d.js`  | force-graph        | MIT | https://unpkg.com/force-graph/dist/force-graph.min.js |
| `tfg3d.js` | 3d-force-graph (bundles three.js) | MIT | https://unpkg.com/3d-force-graph/dist/3d-force-graph.min.js |

three.js is MIT-licensed and bundled inside `3d-force-graph`.
