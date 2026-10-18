# Dashboard screenshot artwork

The source image `monitoring-demo.jpg` is a real Grafana OSS 11.2.0 browser capture at
1600 × 1000. It shows the first viewport of this repository's
[`grafana/dashboards/inverter-overview.json`](../../grafana/dashboards/inverter-overview.json), with its panel layout,
titles, types and display options retained. The complete dashboard extends
below the captured viewport.

For this documentation capture only, a separate copy replaced the production
queries and data sources with Grafana's built-in TestData CSV scenario. Its fixed
synthetic series contain no device identifiers, credentials, production metrics
or customer data. The title explicitly identifies the synthetic demo. The
screenshot does not validate real data collection, query correctness or system
health. The production dashboard still uses its original data source.

The local capture used no external telemetry connection. The source image SHA-256
is `587dbc2f51e538b284d7b1f593fec08b199471ccbf4344522abc79a90ceb13ca`.

## Recreate the capture

Use a separate, loopback-only Grafana instance. Do not import the demo into a
production monitoring installation.

1. Add the built-in **TestData** data source with UID `synthetic-demo`.
2. Import [`demo-dashboard.json`](demo-dashboard.json). It is a documentation
   fixture, not a deployment configuration; it has its own dashboard UID.
3. Open the dashboard's stored time range, use the dark theme and a 1600 × 1000
   browser viewport. The original capture used the America/Los_Angeles time zone.
4. Capture the first viewport without browser chrome and review the flat image
   before replacing `monitoring-demo.jpg`. Update its hash and version information here.

## Regenerate the perspective image

With ImageMagick 7 installed, run from the repository root:

```sh
bash scripts/render-docs-hero.sh
```

The renderer checks the source dimensions, applies only a geometric projection,
rounded outer corners and a soft shadow, then writes a static 1600 × 1050 PNG.
It does not redraw the interface, values or graphs. The README links to the
retained flat screenshot for detailed viewing. Repeated rendering with the same
source and ImageMagick version is deterministic; resampling can differ between
versions. Initially rendered with ImageMagick 7.1.2-31.
