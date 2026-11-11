<?php
// Minimal PHP app for testing Runway (Plesk extension). No dependencies.
// Served by `frankenphp php-server -r public/` (tcp or unix socket) or `php -S` (tcp only).
header("Content-Type: text/plain; charset=utf-8");
if (parse_url($_SERVER["REQUEST_URI"] ?? "/", PHP_URL_PATH) === "/healthz") {
    echo "ok\n";
    return;
}
echo "Hello from PHP " . PHP_VERSION . " (" . php_sapi_name() . ")\n";
