#
# This script can be used to generate a summary of licenses for third-party
# dependencies. Use it like this:
#
#    $> python license_summary.py <package name>
#
# It shells out to `cargo metadata` to gather information about the full
# dependency tree and to `cargo tree` to limit it to just the dependencies
# of the target package.
#

import os.path
import argparse
import subprocess
import json
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def print_license_summary(package, as_json=False):
    # Find the named package, and its manifest file.
    metadata = get_workspace_metadata()
    # Get the dependency tree of the specified package.
    # We're in a virtual workspace so we have to pass its manifest file explicitly.
    p = subprocess.run([
        'cargo', 'tree',
        '--manifest-path', metadata["packages"][package]["manifest_path"],
        '--frozen',
        '--all',
        '--no-dev-dependencies',
        '--no-indent',
        '--format', '{p}',
    ], stdout=subprocess.PIPE, universal_newlines=True)
    p.check_returncode()
    deps = set()
    for ln in p.stdout.split("\n"):
        ln = ln.strip()
        if ln:
            name = ln.strip().split()[0]
            deps.add(name)
    # Print license info for each dependency.
    if as_json:
        print("[")
    else:
        print("-------------")
    for i, name in enumerate(sorted(deps)):
        if is_local_package(metadata, name):
            continue
        pkgInfo = fetch_license_info(metadata, name)
        if as_json:
            print(json.dumps(pkgInfo))
            print("]" if i == len(deps) - 1 else ",")
        else:
            print("Name: {}".format(pkgInfo["name"]))
            print("Authors: {}".format(", ".join(pkgInfo["authors"])))
            print("Repository: {}".format(pkgInfo["repository"]))
            if pkgInfo["license"] is not None:
                print("License: {}".format(pkgInfo["license"]))
            print("License Text:")
            print("")
            print(pkgInfo["license_text"])
            print("-------------")
    

def get_workspace_metadata():
    # Get full metadata for the workspace.
    # This does a union of all features required by all packages in the workspace,
    # so we can't use it to find the real dependency treat of a single package.
    # For the output format, ref https://doc.rust-lang.org/cargo/commands/cargo-metadata.html
    p = subprocess.run([
        'cargo', 'metadata', '--frozen', '--format-version', '1'
    ], stdout=subprocess.PIPE, universal_newlines=True)
    p.check_returncode()
    metadata = json.loads(p.stdout)
    # Convert "packages" into a map keyed by package name.
    pkgInfoByName = {}
    for pkgInfo in metadata["packages"]:
        assert pkgInfo["id"] not in pkgInfoByName
        pkgInfoByName[pkgInfo["name"]] = pkgInfo
    metadata["packages"] = pkgInfoByName
    return metadata


def is_local_package(metadata, name):
    pkgInfo = metadata["packages"][name]
    if pkgInfo["source"] is not None:
        return False
    manifest = pkgInfo["manifest_path"]
    root = os.path.commonprefix([manifest, metadata["workspace_root"]])
    if root != metadata["workspace_root"]:
        return False
    return True


def fetch_license_info(metadata, dep):
    pkgInfo = metadata["packages"][dep]
    licenseInfo = {
        "name": dep,
        "authors": pkgInfo["authors"],
        "repository": pkgInfo["repository"],
        "license": pkgInfo["license"],
    }
    licenseInfo["license_text"] = fetch_license_text(pkgInfo)
    return licenseInfo


def fetch_license_text(pkgInfo):
    # Look for a local copy in the package index.
    pkgRoot = os.path.dirname(pkgInfo["manifest_path"])
    if os.path.isdir(pkgRoot):
        slurp = lambda *p: open(os.path.join(*p)).read()
        if pkgInfo["license_file"] is not None:
            filename = os.path.join(pkgRoot, pkgInfo["license_file"])
            if os.path.isfile(filename):
                return slurp(filename)
        for nm in sorted(os.listdir(pkgRoot)):
            if nm.lower() == "copying":
                return slurp(pkgRoot, nm)
            if nm.lower() == "license":
                return slurp(pkgRoot, nm)
            if nm.lower().startswith("license."):
                return slurp(pkgRoot, nm)
            if nm.lower().startswith("license-"):
                return slurp(pkgRoot, nm)
    # Darn, we're going to have to hit the network.
    # Currently only github repos are supported, yay rust ecosystem consistency.
    repo = pkgInfo["repository"]
    if repo and repo.startswith("https://github.com/"):
        orgAndName = repo[len("https://github.com/"):]
        if orgAndName.endswith(".git"):
            orgAndName = orgAndName[:-4]
        tryFiles = []
        if pkgInfo["license_file"] is not None:
            tryFiles.append(pkgInfo["license_file"])
        tryFiles.extend([
            "LICENSE-APACHE", "LICENSE-MIT", "LICENSE",
            "LICENCE-APACHE", "LICENCE-MIT", "LICENCE",
            "COPYING",
        ])
        for nm in tryFiles:
            tryUrl = "https://raw.githubusercontent.com/" + orgAndName + "/master/" + nm
            r = requests.get(tryUrl)
            if r.status_code == 200:
                return r.content.decode("utf8")
    raise RuntimeError("Could not find license file for '{name}'".format(**pkgInfo))
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="summarize dependency licenses")
    parser.add_argument('package', type=str)
    parser.add_argument('--json', action="store_true")
    args = parser.parse_args()
    print_license_summary(args.package, as_json=args.json)

