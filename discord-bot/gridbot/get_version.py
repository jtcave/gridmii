import subprocess

def get_git_version() -> str|None:
    """Get the current version from the git repo we live in"""
    argv = "git describe --dirty --always --tags".split()
    try:
        git_proc = subprocess.run(argv, capture_output=True)
    except FileNotFoundError:
        # no git
        return None

    if git_proc.returncode == 0:
        return git_proc.stdout.decode()
    else:
        return None

GIT_VERSION = get_git_version()