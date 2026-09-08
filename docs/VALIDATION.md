# Validation for 0.1

Validated on September 8, 2026:

- Eight Python tests passed on the development Mac with Python 3.14.7, including real HTTP enrollment and agent job completion.
- Resource warnings promoted to errors; database connections explicitly closed.
- JavaScript syntax check passed.
- Browser sign-in, inventory display, narrower-window layout, and inventory refresh queueing verified against a disposable local test server using inventory collected from the development Mac.
- Normal dashboard starts empty. Browser test data lives in a separate temporary database.

GitHub Actions checks the same suite on Ubuntu with Python 3.11 and 3.14. Consult the repository's Checks workflow for the current hosted result.

Not yet validated: a persistent Linux service, a separate remote Linux device, privileged operations, production deployment, native Windows/macOS management, mobile layout, assistive-technology interaction, or load/failure recovery beyond the tested inventory job lease.
