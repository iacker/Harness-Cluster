audit_to_db, vendored from https://github.com/nhranitzky/hermes_audit_db_plugin @ 531c85c (MIT, see LICENSE).
Local change: audit_to_db.yaml no longer captures args of browser_type, browser_console, execute_code, text_to_speech (secrets/PII).
Shipped to the pod by the init container (configMapGenerator hermes-audit-plugin).
