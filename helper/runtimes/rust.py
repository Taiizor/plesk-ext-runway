# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Rust -----------------------------------------------------------------

class RustRuntime(Runtime):
    key = "rust"
    label = "Rust"
    version_re = RE_RUST_TOOLCHAIN.pattern
    hint = "Installed with rustup (minimal profile). Channels (stable, beta, nightly) can be updated later."
    docs_url = "https://doc.rust-lang.org/cargo/"
    install_help = "Rust needs a C linker: install the build dependencies once."

    def list_installed(self):
        result = []
        for item in installed_rust():
            label = "Rust " + item["name"]
            match = re.search(r"rustc (\S+)", item.get("version") or "")
            if match and match.group(1) != item["name"]:
                label += " (%s)" % match.group(1)
            result.append({"id": item["name"], "label": label, "path": rust_toolchain_dir(item["name"]),
                           "version": item.get("version") or ""})
        return result

    def list_available(self, force=False):
        stable = rust_latest_stable(force)
        available = [
            {"id": "stable", "label": "stable (%s)" % stable if stable else "stable"},
            {"id": "beta", "label": "beta"},
            {"id": "nightly", "label": "nightly"},
        ]
        if stable:
            available.append({"id": stable, "label": stable})
        return available

    def install(self, version, log):
        job_install_rust(version, log)

    def updatable(self, version):
        return version in ("stable", "beta") or version.startswith("nightly")

    def update(self, version, log):
        job_update_rust(version, log)

    def remove(self, version):
        version = self.check_version(version)
        if not os.path.isfile(rustup_bin()):
            raise HelperError("rustup is not installed")
        run([rustup_bin(), "toolchain", "uninstall", version], env=rust_env(), check=True, timeout=600)

    def env(self, home, version, app_dir=None):
        tcdir = rust_toolchain_dir(version)
        cargo_home = os.path.join(home, ".runway", "cargo")
        return {
            "PATH": [tcdir + "/bin", cargo_home + "/bin"],
            "RUSTUP_HOME": RUSTUP_HOME,
            "RUSTUP_TOOLCHAIN": version,
            "CARGO_HOME": cargo_home,
            "RUSTC": tcdir + "/bin/rustc",
            "RUSTDOC": tcdir + "/bin/rustdoc",
        }

    def inspect(self, app_dir):
        cargo = os.path.join(app_dir, "Cargo.toml")
        if not os.path.isfile(cargo):
            return None
        info = _parse_cargo_toml(_read_small(cargo))
        toolchain_file = os.path.join(app_dir, "rust-toolchain.toml")
        if os.path.isfile(toolchain_file):
            channel = re.search(r'channel\s*=\s*"([^"]+)"', _read_small(toolchain_file))
            info["toolchain_file"] = channel.group(1) if channel else True
        return info

    def defaults(self, inspect, listen="tcp", toolchain=""):
        rust = (inspect or {}).get("rust") or {}
        bins = [b for b in rust.get("bins") or [] if isinstance(b, str)]
        paths = rust.get("bin_paths") if isinstance(rust.get("bin_paths"), dict) else {}
        # An explicit [[bin]] for src/main.rs replaces the binary named after the package; a single
        # declared [[bin]] is the application; otherwise cargo names the binary after the package.
        main_bin = next((b for b in bins if paths.get(b) in ("src/main.rs", "./src/main.rs")), None)
        name = main_bin or (bins[0] if len(bins) == 1 else None) or rust.get("package") or (bins or [None])[0]
        binary = name if isinstance(name, str) and re.match(r"^[A-Za-z0-9_-]+$", name) else "app"
        return {"build_cmd": "cargo build --release", "start_cmd": "./target/release/" + binary}

    def sample(self, listen, toolchain=""):
        return {"Cargo.toml": (SAMPLE_CARGO, 0o640), "src/main.rs": (SAMPLE_RUST, 0o640)}

    def build_deps(self):
        return ["cc", "pkg-config"]
