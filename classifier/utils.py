# Paths in the inotify log always come from the GitHub Actions Linux
# runner, regardless of what OS this analysis code itself runs on -- so the
# separator must always be '/', never os.sep (which is '\\' on Windows and
# would corrupt every path below when this runs on a Windows host).
PATH_SEP = '/'


def classify_files(inotify_log: str) -> tuple[set[str], set[str], dict[str, str]]:
    unused_files = set()
    used_files = set()
    timestamps = dict()

    for line in inotify_log.splitlines():
        timestamp, directory, filename, event = line.split(';')
        directory += PATH_SEP

        event = event.split(',')
        full_path = directory + filename
        if 'IN_ISDIR' in event and filename != '':
            full_path += PATH_SEP

        if 'IN_CREATE' in event:
            used_files.discard(full_path)
            unused_files.add(full_path)
            timestamps[full_path] = timestamp
        elif 'IN_ACCESS' in event:
            used_files.add(full_path)
            unused_files.discard(full_path)
            timestamps.pop(full_path, None)

    return unused_files, used_files, timestamps
