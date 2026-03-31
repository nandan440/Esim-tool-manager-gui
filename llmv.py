import os
import re
import shutil
import subprocess
import platform
from datetime import datetime

import yaml


INSTALL_DETAILS_FILE = os.path.join(os.path.dirname(__file__), "install_details.yml")


def get_os():
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    if "linux" in system:
        return "linux"
    if "darwin" in system:
        return "mac"
    return None


def tool_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(cmd, log=print, cwd=None):
    display_cmd = cmd if isinstance(cmd, str) else " ".join(cmd)
    log(f"> {display_cmd}")

    p = subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
    )

    if p.stdout:
        for line in p.stdout: 
            log(line.rstrip())

    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {display_cmd}")


def _load_install_details():
    try:
        if not os.path.exists(INSTALL_DETAILS_FILE):
            return {"important_packages": []}
        with open(INSTALL_DETAILS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {"important_packages": []}
        if "important_packages" not in data or not isinstance(data.get("important_packages"), list):
            data["important_packages"] = []
        return data
    except Exception:
        return {"important_packages": []}


def _save_install_details(data):
    with open(INSTALL_DETAILS_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def _upsert_install_details(package_name: str, installed: bool, version: str, install_directory: str):
    data = _load_install_details()
    pkgs = data.setdefault("important_packages", [])

    entry = None
    for p in pkgs:
        if isinstance(p, dict) and str(p.get("package_name", "")).lower() == package_name.lower():
            entry = p
            break

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "package_name": package_name,
        "version": version if installed else "-",
        "installed": "Yes" if installed else "No",
        "installed_date": now if installed else "-",
        "install_directory": install_directory if installed else "-",
    }

    if entry is None:
        pkgs.append(payload)
    else:
        entry.update(payload)

    _save_install_details(data)


def _detect_installed_llvm_version(log):
    try:
        if tool_exists("llvm-config"):
            out = subprocess.check_output(["llvm-config", "--version"], text=True).strip()
            return out or None
    except Exception as e:
        log(f"[WARN] llvm-config detection failed: {e}")

    try:
        if tool_exists("clang"):
            out = subprocess.check_output(["clang", "--version"], text=True).strip()
            m = re.search(r"clang version\s+(\d+(\.\d+){0,2})", out, re.IGNORECASE)
            if m:
                return m.group(1)
    except Exception as e:
        log(f"[WARN] clang detection failed: {e}")
    return None


def _choco_list_versions(log=print):
    try:
        result = subprocess.run(
            "choco search llvm --exact --all-versions",
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        versions = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.lower().startswith("llvm "):
                continue
            parts = line.split()
            if len(parts) >= 2:
                versions.append(parts[1].strip())
        return versions
    except Exception as e:
        log(f"Failed to fetch LLVM versions from Chocolatey: {e}")
        return []


def _pick_best_prefix_version(prefix: str, versions, log):
    prefix = (prefix or "").strip()
    if prefix == "" or prefix.lower() == "latest":
        return sorted(versions, reverse=True)[0] if versions else None
    if prefix in versions:
        return prefix

    if re.fullmatch(r"\d+\.\d+", prefix):
        pfx = prefix + "."
    elif re.fullmatch(r"\d+", prefix):
        pfx = prefix + "."
    else:
        pfx = prefix

    def _key(v: str):
        nums = re.split(r"[.-]", v)
        major = int(nums[0]) if len(nums) > 0 and nums[0].isdigit() else -1
        minor = int(nums[1]) if len(nums) > 1 and nums[1].isdigit() else -1
        patch = int(nums[2]) if len(nums) > 2 and nums[2].isdigit() else -1
        return (major, minor, patch, v)

    matches = [v for v in versions if isinstance(v, str) and v.startswith(pfx)]
    if not matches:
        # fallback: match major only
        m = re.match(r"^(\d+)", prefix)
        if m:
            maj = m.group(1) + "."
            matches = [v for v in versions if isinstance(v, str) and v.startswith(maj)]
    if not matches:
        return None
    return sorted(matches, key=_key, reverse=True)[0]


def install_llvm(version="latest", log=print):
    """
    Installs LLVM according to the selected version and OS.
    Writes install metadata to `install_details.yml`.
    """
    os_type = get_os()
    if os_type is None:
        log("Unsupported OS")
        return

    # If already installed, just record state and skip.
    if tool_exists("llvm-config") or tool_exists("clang"):
        installed_version = _detect_installed_llvm_version(log) or "-"
        install_dir = shutil.which("llvm-config") or shutil.which("clang") or "-"
        log(f"LLVM already installed (version: {installed_version}). Skipping installation.")
        _upsert_install_details("llvm", True, installed_version, install_dir)
        return

    req_version = (version or "").strip() or "latest"

    # ---------------- WINDOWS (Chocolatey) ----------------
    if os_type == "windows":
        if not tool_exists("choco"):
            raise RuntimeError("Chocolatey (choco) not found. Install Chocolatey first.")

        available = _choco_list_versions(log)

        if not available:
            if req_version == "latest":
              chosen = "latest"
            else:
              raise RuntimeError("No LLVM versions found via Chocolatey")
        else:
            chosen = _pick_best_prefix_version(req_version, available, log)

        if chosen is None:
            raise RuntimeError(f"Requested LLVM version '{req_version}' not found in Chocolatey.")

        if chosen == "latest":
            run("choco install -y llvm", log)
        else:
            run(f"choco install -y llvm --version={chosen}", log)

        installed_version = _detect_installed_llvm_version(log) or chosen
        install_dir = shutil.which("llvm-config") or shutil.which("clang") or "-"
        _upsert_install_details("llvm", True, installed_version, install_dir)
        log(f"LLVM installation complete (version: {installed_version})")
        return

    # ---------------- MAC (Homebrew) ----------------
    if os_type == "mac":
        if not tool_exists("brew"):
            raise RuntimeError("Homebrew (brew) not found. Install Homebrew first.")

        if req_version.lower() == "latest":
            run("brew install llvm", log)
            # llvm may not be linked into PATH; best effort record prefix
            prefix = subprocess.check_output(["brew", "--prefix", "llvm"], text=True).strip()
            installed_version = _detect_installed_llvm_version(log) or "latest"
            _upsert_install_details("llvm", True, installed_version, prefix or "-")
            log('⚠️ Add LLVM to PATH:')
            log('export PATH="$(brew --prefix llvm)/bin:$PATH"')
            log(f"LLVM installation complete (version: {installed_version})")
            return

        major = re.match(r"^(\d+)", req_version)
        if not major:
            raise RuntimeError(f"Invalid LLVM version: {req_version}")

        formula = f"llvm@{major.group(1)}"
        run(f"brew install {formula}", log)
        # Try to make it available on PATH for tools that expect clang/llvm-config
        run(f"brew link --force --overwrite {formula}", log)
        prefix = subprocess.check_output(["brew", "--prefix", formula], text=True).strip()
        installed_version = _detect_installed_llvm_version(log) or req_version
        _upsert_install_details("llvm", True, installed_version, prefix or "-")
        log('⚠️ Add LLVM to PATH:')
        log('export PATH="$(brew --prefix llvm)/bin:$PATH"')
        log(f"LLVM installation complete (version: {installed_version})")
        return

    # ---------------- LINUX (apt) ----------------
    if os_type == "linux":
        run("sudo apt-get update", log)
        run("sudo apt-get install -y build-essential", log)
        if req_version.lower() == "latest":
            run("sudo apt-get install -y llvm clang", log)
        else:
            major = re.match(r"^(\d+)", req_version)
            if not major:
                raise RuntimeError(f"Invalid LLVM version: {req_version}")
            m = major.group(1)
            run(f"sudo apt-get install -y llvm-{m} clang-{m}", log)

        installed_version = _detect_installed_llvm_version(log) or req_version
        install_dir = shutil.which("llvm-config") or shutil.which("clang") or "-"
        _upsert_install_details("llvm", True, installed_version, install_dir)
        log(f"LLVM installation complete (version: {installed_version})")
        return

    log("Unsupported OS")

## uninstall LLVM
def uninstall_llvm(log=print):
    """
    Uninstalls LLVM based on OS.
    Updates install_details.yml accordingly.
    """
    log("=== UNINSTALLING LLVM ===")
    os_type = get_os()
    if os_type is None:
        log("[ERROR] Unsupported OS")
        return

    # Check if installed
    if not (tool_exists("llvm-config") or tool_exists("clang")):
        log("[INFO] LLVM is not installed. Nothing to uninstall.")
        _upsert_install_details("llvm", False, "-", "-")
        return

    log("[INFO] Starting LLVM uninstall...")

    try:
        # ---------------- WINDOWS ----------------
        if os_type == "windows":
            if not tool_exists("choco"):
                raise RuntimeError("Chocolatey not found")

            run("choco uninstall -y llvm", log)

        # ---------------- MAC ----------------
        elif os_type == "mac":
            if not tool_exists("brew"):
                raise RuntimeError("Homebrew not found")

            # Try both generic and versioned uninstall
            try:
              run("brew uninstall llvm", log)
            except:
              log("[WARN] llvm not found in brew or already removed")
            run("brew cleanup llvm", log)

        # ---------------- LINUX ----------------
        elif os_type == "linux":
            # Remove common LLVM packages
            run("sudo apt-get remove -y 'llvm-*' 'clang-*'", log)
            run("sudo apt-get autoremove -y", log)

        else:
            log("[ERROR] Unsupported OS")
            return

        # Verify removal
        if tool_exists("llvm-config") or tool_exists("clang"):
            log("[WARN] LLVM may not be fully removed (some binaries still detected)")
        else:
            log("[SUCCESS] LLVM uninstalled successfully")

        # Update metadata
        if not (tool_exists("llvm-config") or tool_exists("clang")):
          _upsert_install_details("llvm", False, "-", "-")

    except Exception as e:
        log(f"[ERROR] Uninstall failed: {e}")