#!/usr/bin/env python3
"""Verifies the locale files of the extension (src/plib/resources/locales):

  <locale>.php          loader: $messages = server/<locale>.php + ['app' => app/<locale>.php]
  server/<locale>.php   flat keys used by PHP (pm_Locale::lmsg), including the
                        "cli.commands.<command>" descriptions of "plesk ext runway --help"
  app/<locale>.php      nested keys of the React frontend (arrive flattened: "Domain.title")

Checks:
- every locale has a loader that requires its server and app file;
- every key used by PHP (lmsg('...'), dynamic keys below, one "cli.commands.<command>" per
  <command>Command() method of hooks/ApiCli.php) exists in every server file;
- every key used by the frontend (<Translate content="..."/>, content={'...'},
  translate('...') / lmsg('...') / t('...'), and keys listed in "// i18n-keys: A.b C.d"
  comments for keys built at runtime) exists in every app file;
- every locale defines the same keys as en-US, with the same %%placeholders%%;
- every locale file (loader, server, app) mirrors its en-US counterpart line for line: only the
  string values and line 3 (a comment naming the language) differ, so a key has the same line
  number in every locale.

Unused server keys are reported as warnings only.
"""

import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
LOCALES = os.path.join(ROOT, "plib", "resources", "locales")
FRONTEND = os.path.join(ROOT, "frontend")
CLI_HOOK = os.path.join(ROOT, "plib", "hooks", "ApiCli.php")
REFERENCE = "en-US.php"

# Server keys built dynamically in PHP code.
DYNAMIC = {
    "fieldMemoryMb", "fieldCpuPercent", "fieldTasks",
    "messageAction_start", "messageAction_stop", "messageAction_restart",
}

# Frontend keys looked up by the SDK itself: the page title of every route component.
DYNAMIC_APP = {"Overview.title", "Toolchains.title", "Settings.title", "Domain.title"}

RE_ENTRY = re.compile(r"""^\s*'([A-Za-z0-9_.-]+)'\s*=>\s*(?:'((?:[^'\\]|\\.)*)'|(\[))\s*,?\s*$""")
RE_CLOSE = re.compile(r"^\s*\],?\s*;?\s*$")
RE_PLACEHOLDER = re.compile(r"%%(\w+)%%")
RE_VALUE = re.compile(r"""^(\s*'[A-Za-z0-9_.-]+'\s*=>\s*)'(?:[^'\\]|\\.)*'(\s*,?\s*)$""")
# Line 3 of a translation names its language (a comment); en-US has "//" there.
LANGUAGE_LINE = 3


def parse_file(path, nested):
    """Returns {dotted key: value} of a locale file that returns an array (one entry per line)."""
    keys = {}
    stack = []
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            match = RE_ENTRY.match(line)
            if match:
                key, value, opens = match.groups()
                if opens:
                    if not nested:
                        raise SystemExit("%s:%d: nested section %s in a flat locale file" % (path, number, key))
                    stack.append(key)
                    continue
                keys[".".join(stack + [key])] = value
                continue
            if RE_CLOSE.match(line) and stack:
                stack.pop()
    return keys


def check_loader(path, name):
    """The loader must require server/<name> and app/<name>."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    problems = []
    for part in ("server", "app"):
        if not re.search(r"require\s+__DIR__\s*\.\s*'/%s/%s'" % (part, re.escape(name)), text):
            problems.append("%s: the loader does not require %s/%s" % (name, part, name))
    if "$messages['app']" not in text:
        problems.append("%s: the loader does not set $messages['app']" % name)
    return problems


def shape(line):
    """The line with its string value blanked: what has to match en-US line for line."""
    return RE_VALUE.sub(r"\1''\2", line)


def check_layout(label, path, reference_path, code):
    """A locale file mirrors its en-US counterpart line for line (the same comments, brackets and
    keys on the same lines; the locale code in place of en-US); only the string values and line
    LANGUAGE_LINE differ. Reports the first difference."""
    if not (os.path.isfile(path) and os.path.isfile(reference_path)):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    with open(reference_path, encoding="utf-8", newline="") as fh:
        reference = fh.read().split("\n")
    for number, (line, ref) in enumerate(zip(lines, reference), 1):
        if number == LANGUAGE_LINE:
            if not line.startswith("//"):
                return ["%s:%d: line %d must be the comment that names the language" % (label, number, number)]
        elif shape(line) != shape(ref.replace("en-US", code)):
            return ["%s:%d: differs from line %d of %s (every locale mirrors it line for line; only the "
                    "string values and line %d may differ)" % (label, number, number, REFERENCE, LANGUAGE_LINE)]
    if len(lines) != len(reference):
        return ["%s: %d lines, %s has %d (every locale mirrors it line for line)"
                % (label, len(lines), REFERENCE, len(reference))]
    return []


def cli_keys():
    """One "cli.commands.<command>" key per <command>Command() method of the CLI hook."""
    if not os.path.isfile(CLI_HOOK):
        return set()
    with open(CLI_HOOK, encoding="utf-8") as fh:
        text = fh.read()
    keys = set()
    for method in re.findall(r"function\s+([a-z][A-Za-z0-9]*)Command\s*\(", text):
        keys.add("cli.commands." + re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), method))
    return keys


def php_keys():
    required, mentioned = set(DYNAMIC) | cli_keys(), set(DYNAMIC) | cli_keys()
    literal = re.compile(r"lmsg\(\s*'([A-Za-z0-9_.-]+)'\s*[,)]")
    quoted = re.compile(r"'([A-Za-z][A-Za-z0-9_.-]*)'")
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "plib")):
        if os.path.abspath(dirpath).startswith(os.path.abspath(LOCALES)):
            continue
        for name in files:
            if name.endswith((".php", ".phtml")):
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    text = fh.read()
                required.update(literal.findall(text))
                mentioned.update(quoted.findall(text))
    return required, mentioned


def frontend_keys():
    required = set(DYNAMIC_APP)
    patterns = [
        re.compile(r"""content=["']([A-Za-z0-9_.-]+)["']"""),
        re.compile(r"""content=\{\s*["']([A-Za-z0-9_.-]+)["']\s*\}"""),
        re.compile(r"""\b(?:translate|lmsg|t)\(\s*["']([A-Za-z0-9_.-]+)["']"""),
    ]
    listed = re.compile(r"//\s*i18n-keys:\s*([^\n]+)")
    if not os.path.isdir(FRONTEND):
        return required
    for dirpath, _dirs, files in os.walk(FRONTEND):
        for name in files:
            if name.endswith((".js", ".jsx")):
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    text = fh.read()
                for pattern in patterns:
                    required.update(pattern.findall(text))
                for group in listed.findall(text):
                    required.update(re.findall(r"[A-Za-z0-9_.-]+", group))
    return required


def compare(kind, name, keys, reference, required, errors):
    for key in sorted((required | set(reference)) - set(keys)):
        errors.append("%s/%s: missing key %s" % (kind, name, key))
    if name == REFERENCE:
        return
    for key in sorted(set(keys) - set(reference)):
        errors.append("%s/%s: key %s is not in %s" % (kind, name, key, REFERENCE))
    for key, value in reference.items():
        if key in keys and sorted(set(RE_PLACEHOLDER.findall(value))) != sorted(set(RE_PLACEHOLDER.findall(keys[key]))):
            errors.append("%s/%s: placeholder mismatch in %s" % (kind, name, key))


def main():
    php_required, php_mentioned = php_keys()
    app_required = frontend_keys()
    errors, warnings = [], []
    loaders = sorted(f for f in os.listdir(LOCALES) if f.endswith(".php"))
    if REFERENCE not in loaders:
        errors.append("%s is missing" % REFERENCE)
    data = {}
    for name in loaders:
        errors.extend(check_loader(os.path.join(LOCALES, name), name))
        parts = {}
        for kind, nested in (("server", False), ("app", True)):
            path = os.path.join(LOCALES, kind, name)
            if not os.path.isfile(path):
                errors.append("%s/%s is missing" % (kind, name))
                parts[kind] = {}
            else:
                parts[kind] = parse_file(path, nested)
        data[name] = parts
    for kind in ("server", "app"):
        directory = os.path.join(LOCALES, kind)
        for name in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
            if name.endswith(".php") and name not in data:
                errors.append("%s/%s has no loader %s" % (kind, name, name))
    reference = data.get(REFERENCE, {"server": {}, "app": {}})
    for name, parts in data.items():
        compare("server", name, parts["server"], reference["server"], php_required, errors)
        compare("app", name, parts["app"], reference["app"], app_required, errors)
        if name != REFERENCE:
            code = name[:-len(".php")]
            for part in ("", "server", "app"):
                label = "%s/%s" % (part, name) if part else name
                errors.extend(check_layout(label, os.path.join(LOCALES, part, name),
                                           os.path.join(LOCALES, part, REFERENCE), code))
    for key in sorted(set(reference["server"]) - php_mentioned):
        warnings.append("server/%s: unused key %s" % (REFERENCE, key))
    for line in warnings:
        print("warning: " + line)
    for line in errors:
        print("error: " + line)
    print("%d server keys used by PHP, %d app keys used by the frontend, %d locales, %d warnings, %d errors"
          % (len(php_required), len(app_required), len(data), len(warnings), len(errors)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
