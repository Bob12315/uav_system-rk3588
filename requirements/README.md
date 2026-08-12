# Dependency profiles and locks

`core.txt` is portable mission/config/fusion code. `telemetry.txt` owns
MAVLink, `web.txt` owns the Web UI, and `app.txt` combines those boundaries.
`rk3588-yolo.txt` is deliberately separate for Linux ARM64 RK3588 boards with
the matching RKNN Runtime/driver.

Root `requirements-*.txt` files are compatibility aggregators only. The lock
files record reviewed versions for Linux x86_64 app, Linux ARM64 app, and
RK3588 YOLO. Refresh only after a license scan and hardware validation.
