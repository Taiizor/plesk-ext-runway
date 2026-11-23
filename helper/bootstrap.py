#!/usr/bin/python3 -I
# -*- coding: utf-8 -*-
# Copyright 2026 Taiizor. Licensed under the MIT License.
#
# Runway for Plesk - privileged helper.
#
# This program runs as root. It is invoked either by the Plesk panel through
# pm_ApiCli::callSbin() on behalf of the extension UI, or by systemd units that
# this program generates itself (deploy jobs and toolchain jobs).
#
# Every input is treated as untrusted and validated here, even though the PHP
# side validates it too. Anything that touches files owned by a hosting
# customer is done in a child process that has dropped root privileges, so a
# customer can never trick this program into following a symlink as root.
#
# Protocol:  runway-helper <command>            (JSON payload on stdin)
#            runway-helper <command> <base64>   (manual debugging only: argv is visible
#                                             to every local user through ps)
# Output:    exactly one JSON object on stdout:
#              {"ok": true, ...}  or  {"ok": false, "error": "..."}
#            The exit code is 0 on success and 1 on failure.
#
# Compatible with Python 3.8+ (Ubuntu 20.04 and newer, Debian 11+, EL8+).

import base64
import datetime
import fcntl
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import pwd
import grp
import re
import resource
import select
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
import zipfile
from types import SimpleNamespace

VERSION = "1.3.0"

BASE_DIR = "/opt/runway"
BIN_DIR = BASE_DIR + "/bin"
HELPER_COPY = BIN_DIR + "/runway-helper"
GO_ROOT_DIR = BASE_DIR + "/go"
RUST_ROOT_DIR = BASE_DIR + "/rust"
RUSTUP_HOME = RUST_ROOT_DIR + "/rustup"
RUSTUP_CARGO_HOME = RUST_ROOT_DIR + "/cargo"

STATE_DIR = "/var/lib/runway"
APPS_DIR = STATE_DIR + "/apps"
JOBS_DIR = STATE_DIR + "/jobs"
LOCK_DIR = STATE_DIR + "/locks"
CACHE_DIR = STATE_DIR + "/cache"

CONF_DIR = "/etc/runway"
ENV_DIR = CONF_DIR + "/env"
UNIT_DIR = "/etc/systemd/system"
# systemd-tmpfiles entries recreate /run/runway/<id> (unix socket mode) at boot, before any unit
# starts: runway.conf for /run/runway itself, runway-<id>.conf per application.
TMPFILES_DIR = "/etc/tmpfiles.d"
TMPFILES_BASE = TMPFILES_DIR + "/runway.conf"

ROOT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
USER_PATH = "/usr/local/bin:/usr/bin:/bin"

UNIT_APP = "runway-app-%d.service"
UNIT_DEPLOY = "runway-deploy-%d.service"
UNIT_PATH = "runway-deploy-%d.path"
UNIT_ADMIN_JOB = "runway-job-admin.service"
# Zero-downtime deployments (docs/DESIGN.md section 12): two slot units per application, the
# live one carries the traffic; runway-converge.service repairs interrupted switches at boot.
UNIT_SLOT = "runway-app-%d-%s.service"
UNIT_CONVERGE = "runway-converge.service"
SLOTS = ("a", "b")
# Health watch: installed while an application has it on (sync_health_units).
UNIT_HEALTH = "runway-health.service"
UNIT_HEALTH_TIMER = "runway-health.timer"
UNIT_METRICS = "runway-metrics.service"
UNIT_METRICS_TIMER = "runway-metrics.timer"
UNIT_PUBLIC_FILES = "runway-public-files-%d.service"
UNIT_PUBLIC_FILES_TIMER = "runway-public-files-%d.timer"

# Unix socket mode: /run/runway/<id>/app.sock, directory owned by the system user with the
# web server group (nginx and Apache are members of psaserv, hosting customers are not).
RUN_DIR = "/run/runway"
WEB_GROUP = "psaserv"
# Zero-downtime: root-owned include files of tcp applications (the live port) and the readiness
# and drain limits of a switch.
WEB_DIR = CONF_DIR + "/web"
ZD_READY_DEFAULT = 60
ZD_DRAIN_DEFAULT = 10
# Allowance of a switch beyond readyTimeout + drainSeconds: marker wait and httpdmng, starts,
# reload confirmation and the stop of the old version.
ZD_SWITCH_EXTRA = 300
# TimeoutStopSec of the deploy unit of a switchable application: ends an interrupted switch.
ZD_DEPLOY_STOP = 300
ZD_MARKER = "# Runway: zero-downtime #%d"
# Seconds a switch waits for Plesk's regeneration of the domain configuration, and for httpdmng.
ZD_MARKER_WAIT = 60
ZD_HTTPDMNG_TIMEOUT = 120
# Seconds a reload of the web server may take until its new worker generation is confirmed.
ZD_RELOAD_WAIT = 60
# Confirmed reloads per web server unit (web_effective()): the modification time of a stamp file
# touched just before the reload, i.e. on the same (coarse) clock as the configuration files.
WEB_RELOADS = "/var/lib/runway/web-reloads.json"
WEB_RELOAD_STAMP = "/var/lib/runway/web-reload.stamp"
# Root-only test flag: "<kill|term>:<phase>" makes the switch job signal itself in that phase.
SWITCH_FAULT_FLAG = "/var/lib/runway/test-switch-fault"

TRIGGER_DEPLOY = "tmp/deploy.txt"
TRIGGER_RESTART = "tmp/restart.txt"

LOG_CAP = 8 * 1024 * 1024
LOG_READ_CAP = 2 * 1024 * 1024
LOG_LINE_CAP = 4096
LOCK_TIMEOUT = 60
CHILD_TIMEOUT = 30
# Resource limits of the children that run as the customer (call_as_user): they are forked from
# the panel's helper invocation, outside any per-subscription cgroup.
CHILD_MEMORY = 512 * 1024 * 1024
CHILD_FSIZE = 64 * 1024 * 1024
# Directory listings in those children: names kept per listing, and the most entries counted.
LIST_KEEP_ROOT = 10000
LIST_COUNT_CAP = 10000
# The step that makes the files in a document root inside the application root readable for the
# web server (open_public_files, docs/DESIGN.md section 7, Public files): at most this many entries,
# seconds and directory levels per run.
PUBLIC_FILES_MAX = 200000
PUBLIC_FILES_SECONDS = 60
PUBLIC_FILES_DEPTH = 100
DEFAULT_BUILD_TASKS = 4096
# Crash-loop guard of the app units: systemd gives up after this many starts within 120 s.
APP_START_LIMIT_BURST = 10
MAX_PAYLOAD = 1024 * 1024
HTTP_TIMEOUT = 60
USER_AGENT = "plesk-runway/" + VERSION

# Variables that Runway manages itself; users must not override them.
RESERVED_ENV = frozenset([
    "PORT", "HOST", "LISTEN_ADDR", "RUNWAY_APP_ROOT", "RUNWAY_START_CMD",
    "RUNWAY_SOCKET", "RUNWAY_LISTEN",
    "RUNWAY_ISOLATION_COMMAND",
    "HOME", "USER", "LOGNAME",
])
# Variables of the dynamic loader and the C library that change what a process loads. They are
# refused in the environment file (defence in depth: no unit line runs as root with the customer's
# environment); an application that needs one sets it in its start command.
LOADER_ENV = frozenset(["LD_PRELOAD", "LD_AUDIT", "GCONV_PATH", "GLIBC_TUNABLES"])

RE_GO_VERSION = re.compile(r"^1\.\d{1,3}(\.\d{1,3})?((rc|beta)\d{1,2})?$")
RE_RUST_TOOLCHAIN = re.compile(r"^(stable|beta|nightly(-\d{4}-\d{2}-\d{2})?|1\.\d{1,3}(\.\d{1,3})?)$")
RE_SYSUSER = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")
RE_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
RE_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._@+/-]{1,1023}$")
RE_REL_PATH = re.compile(r"^[A-Za-z0-9._@+-]+(/[A-Za-z0-9._@+-]+)*$")
RE_DOMAIN = re.compile(r"^[^\s/\\'\"`$;&|<>(){}\[\]*?!#%=,]{1,253}$")
RE_CTRL_ANY = re.compile(r"[\x00-\x1f\x7f]")
RE_CTRL_BUT_NL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")

# Listen modes, application modes and URL rules (docs/DESIGN.md section 5.3). The runtime
# adapters (RUNTIMES, RUNTIME_KEYS) are defined in the "Runtime adapters" section below.
LISTEN_MODES = ("tcp", "unix", "none")
APP_MODES = ("web", "path", "worker")
RE_URL_PREFIX = re.compile(r"^/[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$")
RE_HEALTH_PATH = re.compile(r"^/[A-Za-z0-9._~%/?=&+,:@-]{0,511}$")
RE_FETCH_NAME = re.compile(r"^[A-Za-z0-9_+-][A-Za-z0-9._+-]{0,127}$")
MAX_STATIC_PATHS = 20
FETCH_MAX_BYTES = 500 * 1024 * 1024
FETCH_TIMEOUT = 1800
HEALTH_TIMEOUT = 2.0
# Health watch (docs/DESIGN.md section 7, health watch): runway-health.timer runs "_health" every
# HEALTH_WATCH_TICK seconds while an application has it on; each application is checked every
# health_interval seconds once its instance has run HEALTH_WATCH_GRACE seconds, and restarted in
# place after health_failures failed checks in a row, at most HEALTH_WATCH_MAX_RESTARTS times per
# HEALTH_WATCH_WINDOW seconds (a wrong health path must not restart it for ever).
HEALTH_WATCH_DIR = STATE_DIR + "/health"
HEALTH_WATCH_TIMEOUT = 5.0
HEALTH_WATCH_TICK = 10
HEALTH_WATCH_GRACE = 60
HEALTH_WATCH_MAX_RESTARTS = 3
HEALTH_WATCH_WINDOW = 3600
HEALTH_WATCH_INTERVAL_DEFAULT = 30
HEALTH_WATCH_FAILURES_DEFAULT = 3
# Expected response content of the health check (docs/DESIGN.md section 7, health_match): at
# most HEALTH_MATCH_MAX characters without control characters (C0, DEL and C1); with it the
# response is read up to HEALTH_BODY_MAX bytes (status line, headers and body together).
HEALTH_MATCH_MAX = 200
HEALTH_BODY_MAX = 64 * 1024
RE_CTRL_UNICODE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# PHP's trim() characters: the panel and the helper trim the expected content alike.
HEALTH_MATCH_TRIM = " \t\n\r\x00\x0b"
RE_CHUNK_SIZE = re.compile(br"[0-9A-Fa-f]{1,8}")
# Root-owned switch for tests only: allows http:// and non-public addresses in fetch mode.
FETCH_INSECURE_FLAG = CONF_DIR + "/allow-insecure-fetch"
# Root-only test flag: while it exists (and is younger than RECONCILE_PAUSE_MAX seconds) the
# panel's Reconcile leaves helper apps alone, so tests can use fake domain ids.
RECONCILE_PAUSE_FLAG = STATE_DIR + "/pause-reconcile"
RECONCILE_PAUSE_MAX = 3600

# Built-in updater (docs/DESIGN.md section 7): the newest release of the GitHub repository.
# URLs of the API answer are only accepted as exactly <UPDATE_ASSET_PREFIX><tag>/<asset name>
# and <UPDATE_PAGE_PREFIX><tag> of the validated tag (_update_url).
EXTENSION_ID = "runway"
UPDATE_REPO = "Taiizor/plesk-ext-runway"
UPDATE_API = "https://api.github.com/repos/%s/releases/latest" % UPDATE_REPO
UPDATE_ASSET_PREFIX = "https://github.com/%s/releases/download/" % UPDATE_REPO
UPDATE_PAGE_PREFIX = "https://github.com/%s/releases/tag/" % UPDATE_REPO
# Redirects of the updater's requests (GitHub sends downloads to its asset host once).
UPDATE_MAX_REDIRECTS = 5
# Plesk's copy of the installed package's meta.xml (the installed version and release).
INSTALLED_META = "/usr/local/psa/admin/plib/modules/%s/meta.xml" % EXTENSION_ID
UPDATE_CACHE = CACHE_DIR + "/update.json"
UPDATE_WORK_DIR = CACHE_DIR + "/update"
UPDATE_CHECK_INTERVAL = 12 * 3600
# A forced check ("Check now") within this many seconds of the last one answers from the cache.
UPDATE_FORCE_MIN_AGE = 60
# Automatic installation does not retry a version that failed within this many seconds.
UPDATE_RETRY_AFTER = 24 * 3600
UPDATE_API_TIMEOUT = 20
UPDATE_SUMS_MAX = 64 * 1024
UPDATE_ZIP_MAX = 200 * 1024 * 1024
UPDATE_META_MAX = 256 * 1024
UPDATE_INSTALL_TIMEOUT = 1800
# Root-owned switch for tests only (ignored when it or CONF_DIR is writable by group or others):
# one line with another releases/latest URL (https, or http while FETCH_INSECURE_FLAG exists);
# asset and page URLs must then lie below its origin.
UPDATE_SOURCE_FLAG = CONF_DIR + "/update-source"
RE_UPDATE_TAG = re.compile(r"^v(\d{1,6}\.\d{1,6}\.\d{1,6})(?:-(\d{1,6}))?$")
RE_UPDATE_ZIP = re.compile(r"^runway-(\d{1,6}\.\d{1,6}\.\d{1,6})-(\d{1,6})\.zip$")
RE_UPDATE_FULL = re.compile(r"^(\d{1,6}\.\d{1,6}\.\d{1,6})-(\d{1,6})$")
RE_UPDATE_VERSION = re.compile(r"^\d{1,6}\.\d{1,6}\.\d{1,6}$")


class HelperError(Exception):
    """An expected failure whose message is safe to show in the UI. "code" is an optional
    machine-readable reason (e.g. "not_empty") that the panel can map to a form field."""

    def __init__(self, message, code=None):
        Exception.__init__(self, message)
        self.code = code
