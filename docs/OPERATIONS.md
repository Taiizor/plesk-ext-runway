# Optional application operations

Open a configured domain's **Optional operations** panel. History, diagnostics, preflight,
isolated releases, notifications and recovery backups all start **off**. Save this panel
separately from application settings; saving does not start, build or restart the application.
The server-wide **Enforce Plesk service-plan policies** switch also starts off.

## Deployment history and audit

History retains completed build, fetch, restart and rollback attempts: actor, trigger source,
runtime/toolchain, timestamps, duration, outcome and selected release. The actor comes from the
authenticated panel session or `cli`, not a browser-supplied field. Start/stop requests and
health-watch restarts/pauses also produce bounded audit events.

Keep 1–200 deployment records (default 20). Each retains the last 256 KiB / 2,000 lines of deploy
log; the viewer returns at most 1,000 lines. Audit events retain at most five times that record
limit. Pruning happens after a deployment completes. Disabling history stops collecting it;
existing records remain root-only until pruned or the application is removed.

Known environment values of at least four characters are redacted from retained logs/messages.
This cannot identify arbitrary secrets printed by code or embedded in commands; treat deployment
logs as sensitive. An uncatchable process/server failure can leave an attempt without a completed
record. The existing current deploy log remains available independently of this feature.

## Diagnostics and preflight

Enable diagnostics, save, then select **Run diagnostics**. Checks cover the source directory,
subscription write access, installed toolchain and free disk reserve. JSON reports include
selected service/listener/health facts, without environment values, commands, webhook credentials
or logs. Review their domain/runtime/service metadata before sharing. This is on demand, not
another periodic monitor.

**Block deployments when preflight checks fail** is separate, effective only while diagnostics
is enabled. It checks before building/fetching/restarting. Disk reserve defaults to 256 MiB
(range 0–1,048,576 MiB). Release copy size is checked during preparation even with preflight off.
A check cannot reserve disk against other processes or prevent a custom build from filling it.

## Isolated releases and large shared directories

Future **build/fetch** deployments copy bounded sources into
`<subscription home>/.runway/releases/<domain id>/<release id>`, build as the subscription user,
then select the result for execution. The logical application root, trigger files and Plesk
document root stay in place. Working directory, `RUNWAY_APP_ROOT` and runtime setup use the
selected release. Plain restarts reuse that code. Saving without a build command creates no
release; use **Build & restart** to publish a snapshot.

Configure shared paths **before the first release**. Each is a directory relative to the logical
application root: an entire `wwwroot`, or selected subdirectories. Shared files stay in their
original directory. They are skipped before traversal, size estimation and copying; links are
attached **after** building. For .NET, links are also attached under an existing `publish/`.
The default `dotnet publish -c Release -o publish` therefore cannot copy a declared 200 GB
`wwwroot` into every release. Custom publish outputs need matching link placement in the build
command or the default `publish/` layout.
Frameworks that generate static-asset manifests at build time will not see excluded shared
media in those manifests. Serve mutable files through a runtime file provider (for example
ASP.NET `UseStaticFiles`) or explicit Plesk static paths.

Example for an application root `apps/api`:

```text
shared_paths:   wwwroot
exclude_paths:  .git
                .runway
release_limit:  3
release_max_mb: 2048
min_free_mb:    256
```

Video, GIF, image, executable and JSON files in `apps/api/wwwroot` remain there once. If versioned
code/output is 500 MiB, three releases cost roughly 1.5 GiB plus the original source/build tree,
a candidate while building, caches and extra protected slots. The 200 GB shared directory is not
multiplied. If `wwwroot` also contains versioned frontend assets, share only upload subdirectories
instead. Classification depends on whether data must survive deployments, not its extension.

Excluded paths are neither copied nor linked. `tmp` is always excluded; initial exclusions are
`.git` and `.runway`. Maximum 20 shared and 20 excluded paths: 255 characters per path and 1,024
per list. No absolute paths, traversal, overlapping shared/excluded paths or nested shared paths.
Shared paths cannot start with `.git`, `.runway` or `tmp`. Non-excluded source symlinks/special
files are rejected: declare directories shared or exclude them. Walks have entry, depth,
descriptor and time bounds; narrow broad/deep trees with exclusions. Release storage cannot be
inside the sources.

The maximum release size is 1–1,048,576 MiB (default 2,048), checked before copying and after
building. Preparation requires estimated copy size plus the free-space reserve. Build-generated
files must fit too. Build tools can use more disk before the final check; budget temporary
output and caches. Attachment refuses nonempty build-created shared directories: keep versioned
build output outside shared paths.

Keep 2–20 recent successful releases (default 3). Pruning follows successful deployments. All
slot-mapped releases stay protected and may exceed the count. Failed readiness restores the
earlier mapping. If a reload leaves traffic ownership uncertain, a running candidate and its
mapping are retained for convergence, never deleted underneath it.

**Roll back** selects compatible code with current environment, resource settings and commands.
Runtime, toolchain and start-command fingerprint must match. Database migrations/shared-file
changes are never undone. A stopped application stays stopped. Zero-downtime mode uses its
existing readiness/switch/drain mechanism; a classic failure restores previous mapping/units and
attempts to restart the previous code. An original in-place version predating release mode is
not a retained rollback target: publish successful releases before relying on the list.

Turning release mode off keeps the selected release until the next build/fetch, which uses the
original application directory and switches back to it. To delete retained code, turn release
mode off, stop the application and choose **Clear retained releases**. Original sources/shared
files remain. Removing a Runway application removes root metadata but preserves subscription
files, including releases; remove unwanted user files through the subscription file manager.
Clear releases before changing source/system-user identity, or clean old user files separately.

Plesk/nginx static paths still use the Plesk document root; they do not follow release snapshots.
Keep mutable static content shared; serve versioned assets through the app or publish separately
to a deliberately managed public directory. Build tools containing absolute installation paths,
such as Python virtual environments, should run inside the candidate; exclude existing `.venv`,
`obj`, `bin`, caches or dependencies as appropriate to the project.

## HTTPS webhook notifications

Set a public HTTPS endpoint, choose events and enable delivery. Payloads contain `id`, `event`,
UTC `time`, `domain` and metadata-only `detail`. Events cover deployment success/failure,
health-watch restart/pause and start/stop requests. Environment values, application logs and
error messages are never added. URLs may contain credentials in their path/query and remain in
root-only options and the authorized domain settings response.

An optional 16–256-character secret adds `X-Runway-Signature: sha256=<hex>` (HMAC-SHA256 over the
exact UTF-8 body). `X-Runway-Event` identifies the event. Verify signature and id/time at the
receiver. Empty password input keeps the secret; the remove checkbox clears it. Stored signing
secrets are never returned.

Sending runs as the subscription user. All resolved addresses must be public; connections use
those checked addresses with normal certificate/hostname verification. Proxies and redirects
are disabled. Bounds: 8 KiB body, 5-second HTTP timeout, 10-second child deadline. Delivery is one
attempt without a durable retry queue; errors never fail application control/deployments. The
panel shows the last attempt. Slack/Discord formats need an adapter for this generic JSON.

## Plesk backup and recovery

Enable recovery backup to add metadata through `pm_Hook_Backup_Domain` and enable configuration
JSON export/import. The disabled hook does not call the helper. Plesk's existing domain-settings
backup stays unchanged. This hook creates no second content archive, claims no shared-file
ownership and includes no release store/history in metadata. Select application/shared content
in Plesk's normal backup policy and verify coverage of the actual `apps/...` paths. A
configuration-only backup cannot recover application files.

Environment variables/webhook credentials are omitted by default. Include them only with the
explicit secrets checkbox. Recovery JSON then contains plaintext secrets; restrict access and
use encrypted backup storage. Build/start commands are always included and may also contain
secrets. Recovery JSON is bounded to 512 KiB; reduce or omit oversized environments.

For manual restore, stop the app and wait for deployments to finish. Import JSON; the separate
restore-secrets checkbox defaults off. Restore application/shared content separately, review
commands/toolchains and start manually. Destination domain, system user and document root stay;
source ports, live slot pointers and admin limits are omitted. Settings obey destination rules.
Import without secrets preserves existing environment values and disables restored webhooks.
Native restore rebuilds root state/ports and defaults to disabled/manual start. Explicit
**Start automatically after a Plesk restore** permits start only if the saved application was
enabled and prerequisites are available. Restore and build source files as needed; old release
pointers are not portable recovery state. Destination toolchains must already be installed.

## Optional service-plan policies

An administrator enables **Runway > Settings > Enforce Plesk service-plan policies**. Plesk plans
and subscription overrides expose nine runtime permissions and these custom limits:

| Limit | Meaning |
|---|---|
| `app_count` | Enabled apps in the subscription; default unlimited, explicit 0 denies new enables |
| `app_memory_mb` | Memory ceiling per application/slot, MiB |
| `app_cpu_percent` | CPU ceiling per application/slot; 100 means one core |
| `app_tasks` | Task ceiling per application/slot |

Resources default unlimited; zero leaves a resource uncapped. Runtime permissions default allowed
and are ignored while policies are off. Customers still need Runway management permission. New
apps, runtime changes and re-enables check runtime permission on the server. Existing enabled apps
can still be edited/stopped/disabled after a permission is revoked; sample creation checks before
writing. The existing global app-count limit also applies; the smaller allowance wins.

Positive caps apply even to admin overrides, whose original requested values stay stored. Save
or scheduled Reconcile applies cap changes; Reconcile restarts affected apps to enforce new
cgroup settings, preserving Stop. Turning policies off restores requested limits on Reconcile
only for previously policy-managed apps. Runtime/app-count reductions alone never terminate
existing apps. Review caps before enabling: lowering memory below usage can interrupt an app.

## Document root is optional

Keep **Change the Plesk document root** unchecked to preserve Plesk's root. An API without static
files needs no `wwwroot`. Choose a public-only folder when Plesk should directly serve files.
Do not choose the source directory: sources/configuration may become public when proxying is
disabled or removed. Release mode does not change the document root automatically.

## Protocol and storage

Domain-authorized `GET api/app/operations` returns options, history, audit events, releases and
last notification. `POST` accepts `action`: `save` (`options`), `history` (`id`), `diagnostics`,
`rollback` (`id`), `export`, `import` (`backup`, `restore_secrets`), or `clear-releases`. Existing
session/domain access and POST CSRF rules apply. Root command `operations` uses `domain_id` and
the same names, plus an internal `validate-import` action. Recovery bundles never supply a
public endpoint with a destination domain/user identity.

Root-only options: `/etc/runway/operations/<id>.json`; records/notification/release metadata:
`/var/lib/runway/operations/<id>/`. User code lives in subscription release directories; copying,
linking and removal use the subscription identity. The deployed helper stays one standalone
executable, assembled from `helper/operations/` and the other manifest sections.

## Verification

`tests/test_operations.py` covers disabled defaults, bounded/shared copies, symlink/descriptor
guards, classic and slot failures, stopped deployments, rollback compatibility, history
redaction/retention, secret opt-ins and webhook signing/error isolation without live services.
`tests/php/operations.php` covers plan enforcement and native recovery/backup using Plesk fixtures.
`tests/frontend/operations.test.js` covers document-root opt-in, settings conversion and recovery
parsing. CI runs these with the existing suites. Real Plesk backup/restore orchestration and
runtime-specific release builds still need integration testing; fixtures do not validate those
external services.

The labels are translated into every panel language, like the rest of the interface.
