def run(path="."):
    """List a directory's entries. Returns a dict with name, dirs, files, and errors.

    Never raises for a bad path; reports it in 'error' instead.
    """
    import os

    try:
        entries = sorted(os.listdir(path))
    except (OSError, TypeError) as exc:
        return {"name": str(path), "dirs": [], "files": [], "error": str(exc)}

    dirs = []
    files = []
    for entry in entries:
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            dirs.append(entry)
        else:
            files.append(entry)
    return {"name": path, "dirs": dirs, "files": files, "error": None}
