# Copyright 2026 Taiizor. Licensed under the MIT License.

class Runtime(object):
    """Common interface of the runtime adapters (docs/DESIGN.md section 5.1)."""
    key = ""
    label = ""
    toolchain = "managed"   # managed | detected | none
    version_re = ""
    hint = ""
    docs_url = ""
    default_listen = "tcp"
    supports_build = True
    install_help = ""
    # Toolchains whose default start command can listen on a unix socket ("" = all of them).
    unix_toolchain_re = ""
    # The default commands differ per toolchain (app-page then adds variants per installed toolchain).
    defaults_per_toolchain = False
    # Directories directly inside an application root that usually hold the files a web server can
    # serve itself, in the order the settings form suggests them as the document root (the
    # inspection reports the existing ones: public_dirs, docs/DESIGN.md section 7). Only folders whose
    # content mirrors the URL: a static path /static/x is <document root>/static/x, so a folder that
    # applications serve under a prefix of its own name (static, staticfiles) is no document root.
    public_dirs = ("public", "dist", "wwwroot")

    def meta(self):
        # hint_key / install_help_key: locale keys of the panel for the English hint/install_help
        # (the panel translates them and falls back to the English text).
        return {"key": self.key, "label": self.label, "toolchain": self.toolchain,
                "version_re": self.version_re, "hint": self.hint, "docs_url": self.docs_url,
                "default_listen": self.default_listen, "supports_build": self.supports_build,
                "install_help": self.install_help, "detected_only": self.toolchain == "detected",
                "unix_toolchain_re": self.unix_toolchain_re,
                "hint_key": "Runtime.%s.hint" % self.key if self.hint else "",
                "install_help_key": "Runtime.%s.installHelp" % self.key if self.install_help else ""}

    def check_version(self, value):
        value = str(value if value is not None else "").strip()
        if not self.version_re or not re.match(self.version_re, value):
            raise HelperError("Invalid %s version '%s'" % (self.label, value[:64]))
        return value

    def resolve(self, version):
        """The installed toolchain id a configured version uses (e.g. a Java major)."""
        return version

    def may_use(self, configured, build):
        """True when the configured id is a channel that can resolve to the installed build."""
        return False

    def list_installed(self):
        return []

    def is_installed(self, version):
        version = self.resolve(version)
        return any(item.get("id") == version for item in self.list_installed())

    def list_available(self, force=False):
        return []

    def check_installable(self, version):
        if self.toolchain != "managed":
            raise HelperError(self.install_help or "The %s runtime has no installable toolchain" % self.label)

    def updatable(self, version):
        return False

    def install(self, version, log):
        raise HelperError(self.install_help or "The %s runtime has no installable toolchain" % self.label)

    def update(self, version, log):
        raise HelperError("Only channel toolchains can be updated: install the newer version, then remove the old one")

    def remove(self, version):
        raise HelperError("%s versions provided by the system cannot be removed by Runway" % self.label)

    def env(self, home, version, app_dir=None):
        return {"PATH": []}

    def listen_env(self, state):
        return {}

    def inspect(self, app_dir):
        return None

    def defaults(self, inspect, listen="tcp", toolchain=""):
        return {"build_cmd": "", "start_cmd": "./app"}

    def sample(self, listen, toolchain=""):
        return {}

    def prepare_start(self, state, pw):
        """Runs as root before every start of the application unit (see prepare_start())."""
        return None

    def build_deps(self):
        return []

    def _remove_dir(self, root, name):
        path = os.path.join(root, name)
        if not os.path.isdir(path) or os.path.islink(path):
            raise HelperError("%s %s is not installed" % (self.label, name))
        shutil.rmtree(path)
