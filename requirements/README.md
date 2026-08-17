# Dependency profiles and reviewed version snapshots

`requirements/` is the only Python dependency source:

```text
core.txt
├─ telemetry.txt
├─ web.txt
├─ app.txt = telemetry + web
├─ dev.txt = app + test/lint/type-check tools
└─ rk3588-yolo.txt = core + RKNNLite + OpenCV
```

The root compatibility aggregators (`requirements-app.txt`,
`requirements-dev.txt`, and `requirements-yolo.txt`) were removed after all
repository callers moved to these canonical profiles. Do not recreate them or
copy package/version lists into `environment-*.yml`.

The three root `environment-*.yml` files own Conda environment names, Python
and Node versions, and delegate Python package installation to the profiles in
this directory. The install scripts run `conda env create/update` once; they
must not run a second `pip install -r` for the same profile.

Files under `locks/` are reviewed version snapshots for Linux x86_64 app,
Linux ARM64 app, and RK3588 YOLO. They are not current installer inputs and do
not guarantee a reproducible install until a dedicated lock workflow consumes
them. Refresh them only after dependency resolution on the matching platform,
license review, and—for RK3588 YOLO—hardware validation.
