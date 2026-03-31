import subprocess
import re
from packaging import version as vparse

# -----------useful functions---------
def parse_version(v):
    return tuple(map(int, v.split(".")))

def max_version(versions):
    """
    Return the highest version string from an iterable of version strings.
    Ignores non-string / unparsable entries.
    """
    if not versions:
        return None
    parsed = []
    for item in versions:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        try:
            parsed.append((vparse.parse(s), s))
        except Exception:
            continue
    if not parsed:
        return None
    parsed.sort(key=lambda t: t[0], reverse=True)
    return parsed[0][1]


def compare_versions(installed, target):
    """
    Compare installed version with target version.

    Returns:
        -1 → installed < target  (outdated)
         0 → installed == target
         1 → installed > target
        None → comparison failed
    """
    try:
        i = vparse.parse(installed)
        t = vparse.parse(target)

        if i < t:
            return -1
        elif i > t:
            return 1
        else:
            return 0
    except Exception:
        return None



def get_version(commands):
    if not commands:
        return None

    # 🔥 FIX: ensure list
    if isinstance(commands, str):
        commands = [commands]

    for cmd in commands:
        try:
            result = subprocess.run(
                cmd.split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            output = (result.stdout or result.stderr)
            if not output:
                continue

            match = re.search(r"(\d+\.\d+(\.\d+)?)", output)
            if match:
                return match.group(1)

        except Exception:
            continue

    return None



 
#   -----Version Check--------


def check_tool_version(tool_cfg):
    installed = get_version(tool_cfg["version_cmd"][0])

    if not installed:
        return "not_installed"

    min_v = tool_cfg.get("min_version")
    rec_v = tool_cfg.get("recommended_version")

    # compare_versions: -1 outdated, 0 equal, 1 newer, None failed
    if min_v and compare_versions(installed, min_v) == -1:
        return "too_old"

    if rec_v:
        cmp = compare_versions(installed, rec_v)
        if cmp == 0 or cmp == 1:
            return "up_to_date"
        if cmp == -1:
            return "outdated"

    return "up_to_date"
