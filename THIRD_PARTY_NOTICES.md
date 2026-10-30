# Third-party notices

Swagger UI distribution **5.34.0** is vendored in `app/static/vendor/` for offline,
self-hosted API documentation. Source: https://github.com/swagger-api/swagger-ui
and the `swagger-ui-dist` npm package. License: Apache-2.0, included at
`app/static/vendor/LICENSE`. These assets were downloaded from the versioned package
on jsDelivr; the running app does not contact that CDN.

Python packages retain their individual licenses and are installed by pip from the
locked requirements. PostgreSQL and Keycloak retain their respective upstream
licenses and are consumed as container images. The project's MIT license does not
replace third-party licenses.
