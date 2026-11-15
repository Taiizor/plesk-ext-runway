# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Ruby (detected) ----------------------------------------------------------

class RubyRuntime(Runtime):
    key = "ruby"
    label = "Ruby"
    toolchain = "detected"
    version_re = r"^(system|\d+\.\d+\.\d+)$"
    hint = "Uses the Ruby versions of the Plesk Ruby extension (/opt/plesk/ruby) or the system Ruby."
    install_help = ("Runway uses the Ruby versions already on the server. Install them with the Plesk Ruby "
                    "extension (plesk bin extension --install ruby) or the distribution packages (apt-get install "
                    "ruby-full ruby-dev / dnf install ruby ruby-devel). Native gems also need the build dependencies.")
    docs_url = "https://www.ruby-lang.org/en/documentation/"
    public_dirs = ("public",)
    # The defaults of the system Ruby depend on whether Bundler is available (see system_bundle()).
    defaults_per_toolchain = True
    _installed = None
    wrapper_dir = BASE_DIR + "/ruby/system/bin"

    def prefix(self, version):
        return "/usr" if version == "system" else "/opt/plesk/ruby/" + version

    def system_bundle(self):
        """The Bundler executable of the system Ruby: /usr/bin/bundle, or the versioned
        /usr/bin/bundle<X.Y> that Debian and Ubuntu ship without the ruby-bundler package."""
        if os.path.isfile("/usr/bin/bundle"):
            return "/usr/bin/bundle"
        try:
            match = re.search(r"ruby (\d+\.\d+)", run(["/usr/bin/ruby", "--version"], timeout=10).stdout)
        except HelperError:
            match = None
        if match and os.path.isfile("/usr/bin/bundle" + match.group(1)):
            return "/usr/bin/bundle" + match.group(1)
        return None

    def ensure_wrappers(self):
        """Root: bundle/bundler wrappers for the versioned Bundler of the system Ruby, in a directory
        on the PATH of system-Ruby applications (like the composer wrapper of PHP)."""
        bundle = self.system_bundle() if os.path.isfile("/usr/bin/ruby") else None
        if not bundle or bundle == "/usr/bin/bundle":
            return
        ensure_dir(os.path.dirname(os.path.dirname(self.wrapper_dir)))
        ensure_dir(os.path.dirname(self.wrapper_dir))
        ensure_dir(self.wrapper_dir)
        for name, target in (("bundle", bundle), ("bundler", bundle.replace("/bundle", "/bundler", 1))):
            if not os.path.isfile(target):
                target = bundle
            content = ("#!/bin/sh\n# Managed by the Plesk Runway extension: the Bundler of the system Ruby.\n"
                       "exec %s \"$@\"\n" % target)
            path = os.path.join(self.wrapper_dir, name)
            if _read_text(path) != content.strip():
                write_file_atomic(path, content, 0o755)

    def list_installed(self):
        if self._installed is not None:
            return self._installed
        found = set()
        for name in _listdir("/etc/psa/ruby_versions.d"):
            data = read_json(os.path.join("/etc/psa/ruby_versions.d", name)) if name.endswith(".json") else None
            version = str((data or {}).get("version") or "") if isinstance(data, dict) else ""
            if re.match(r"^\d+\.\d+\.\d+$", version) and data.get("path") == self.prefix(version):
                found.add(version)
        for name in _listdir("/opt/plesk/ruby"):
            if re.match(r"^\d+\.\d+\.\d+$", name):
                found.add(name)
        result = [{"id": v, "label": "Ruby %s (Plesk)" % v, "path": self.prefix(v)}
                  for v in sorted(found, key=num_key, reverse=True) if os.path.isfile(self.prefix(v) + "/bin/ruby")]
        if os.path.isfile("/usr/bin/ruby"):
            match = None
            try:
                match = re.search(r"ruby (\d+\.\d+\.\d+)", run(["/usr/bin/ruby", "--version"], timeout=10).stdout)
            except HelperError:
                pass
            result.append({"id": "system", "label": "Ruby %s (system /usr/bin/ruby)" % (match.group(1) if match else "?"),
                           "path": "/usr"})
        self._installed = result
        return result

    def env(self, home, version, app_dir=None):
        rw = os.path.join(home, ".runway")
        gems = rw + "/gems"
        paths = [gems + "/bin", self.prefix(version) + "/bin"]
        if version == "system":
            try:
                self.ensure_wrappers()
            except OSError:
                pass
            paths.append(self.wrapper_dir)
        # No GEM_PATH: RubyGems then searches GEM_HOME plus the interpreter's default directory,
        # which holds the bundled gems (rexml, csv, ...) of Ruby 3.x.
        return {
            "PATH": paths,
            "GEM_HOME": gems,
            "GEM_SPEC_CACHE": gems + "/specs",
            "BUNDLE_PATH": rw + "/bundle",
            "BUNDLE_APP_CONFIG": rw + "/bundle-config",
            "BUNDLE_USER_HOME": rw + "/bundle-user",
            "BUNDLE_USER_CACHE": rw + "/bundle-user/cache",
            "BUNDLE_JOBS": "4",
            "BUNDLE_WITHOUT": "development:test",
            "BUNDLE_RETRY": "3",
            "BUNDLE_SILENCE_ROOT_WARNING": "1",
            "RAILS_ENV": "production",
            "RACK_ENV": "production",
            "RAILS_LOG_TO_STDOUT": "1",
            "MALLOC_ARENA_MAX": "2",
        }

    def inspect(self, app_dir):
        found = _files(app_dir, "Gemfile", "Gemfile.lock", "config.ru", "config/puma.rb", "bin/rails", "app.rb",
                       ".ruby-version", "config/database.yml")
        if not found:
            return None
        info = {"gemfile": "Gemfile" in found, "lockfile": "Gemfile.lock" in found, "rack": "config.ru" in found,
                "puma_config": "config/puma.rb" in found, "rails": "bin/rails" in found, "gems": [],
                "script": "app.rb" if "app.rb" in found else None, "ruby_version": None}
        if info["gemfile"]:
            text = _read_small(os.path.join(app_dir, "Gemfile"), 65536)
            info["gems"] = [g for g in ("puma", "unicorn", "rails", "sinatra", "falcon")
                            if re.search(r"^\s*gem\s+['\"]%s['\"]" % g, text, re.M)]
        if ".ruby-version" in found:
            match = re.search(r"(\d+\.\d+(\.\d+)?)", _read_small(os.path.join(app_dir, ".ruby-version"), 256))
            info["ruby_version"] = match.group(1) if match else None
        return info

    def defaults(self, inspect, listen="tcp", toolchain=""):
        info = (inspect or {}).get("ruby") or {}
        unix = listen == "unix"
        steps = []
        if info.get("gemfile"):
            if toolchain == "system" and not self.system_bundle():
                # No Bundler at all for the system Ruby: install it into GEM_HOME (on PATH) first.
                steps.append("gem install --no-document bundler")
            steps.append("bundle install")
        if info.get("rails"):
            # Through Bundler, not bin/rails: uploads (FTP, File Manager) often lose the exec bit.
            steps.append("SECRET_KEY_BASE_DUMMY=1 bundle exec rails assets:precompile")
        build = " && ".join(steps)
        gems = info.get("gems") or []
        result = {"build_cmd": build}
        if info.get("puma_config") and (info.get("rails") or "puma" in gems):
            # The project's config/puma.rb decides where puma listens (a command-line -b would replace
            # every bind of the file); it reads RUNWAY_SOCKET or PORT, see examples/ruby-hello.
            start = "bundle exec puma -C config/puma.rb -e production"
        elif info.get("rails") or (info.get("rack") and "puma" in gems):
            bind = '"unix://$RUNWAY_SOCKET?umask=0117"' if unix else "tcp://$HOST:$PORT"
            start = "bundle exec puma -e production -b %s" % bind
        elif "unicorn" in gems:
            start = "bundle exec unicorn -E production -l %s" % ("$RUNWAY_SOCKET" if unix else "$HOST:$PORT")
        elif info.get("rack"):
            # rackup has no unix socket option: TCP only.
            start = "bundle exec rackup -E production -o $HOST -p $PORT"
            result["unix_supported"] = False
        else:
            start = "ruby " + (info.get("script") or "app.rb")
        result["start_cmd"] = start
        return result

    def sample(self, listen, toolchain=""):
        return {"app.rb": (SAMPLE_RUBY, 0o640)}

    def build_deps(self):
        return ["cc", "make"]
