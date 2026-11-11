# php-hello

Minimal PHP application (`public/index.php`, no dependencies) for Runway. It runs with the
PHP built-in web server of a Plesk PHP handler or with FrankenPHP (installed from
*Runway > Toolchains*).

| Listen | With FrankenPHP | With PHP only |
|---|---|---|
| TCP port | `frankenphp php-server --listen $HOST:$PORT -r public/` | `php -S $HOST:$PORT -t public` |
| Unix socket | `frankenphp php-server --listen "unix/$RUNWAY_SOCKET\|0660" -r public/` | not supported (`php -S` is TCP only) |

Build command: none (for Composer projects
`composer install --no-dev --optimize-autoloader --no-interaction`). Health check path:
`/healthz`.

Always pass `--listen` to FrankenPHP (its default is `:80` on all interfaces) and the `|0660`
socket mode (the default socket mode would lock out the web server). Never use `-d/--domain`
behind nginx. `php -S` serves one request at a time: fine for tests, use FrankenPHP for
production traffic.
