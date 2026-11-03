"""System initialisation: removes what the program makes for itself while it works (the preview and export pages,
the error logs, the temporary files) and tidies the database file. The manuals, the pictures, the backups, the
licence and the settings are never touched."""
import glob
import os
import shutil
import tempfile

# folders inside the data folder that hold only working files, made again when needed
WORK_FOLDERS = ('preview', 'export', 'logs')


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _remove(path, out):
    size = _size(path)
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError:
        out['kept'] += 1                    # in use now (an open file): left for the next time
        return
    out['files'] += 1
    out['bytes'] += size


def working_files(data_dir):
    """Everything the initialisation removes: the work folders in the data folder and the program's temporary
    files in the Windows temporary folder."""
    paths = [os.path.join(data_dir, f) for f in WORK_FOLDERS if os.path.exists(os.path.join(data_dir, f))]
    tmp = tempfile.gettempdir()
    paths += [p for p in [os.path.join(tmp, 'ManualBuilder')] if os.path.exists(p)]
    paths += glob.glob(os.path.join(tmp, 'mb-*.pdf')) + glob.glob(os.path.join(tmp, 'manual-selftest-*'))
    return paths


def initialise(db, data_dir):
    """Removes the working files and tidies the database. Returns what was done:
    ``files`` removed, ``bytes`` freed, ``kept`` (in use, left), ``db_ok`` (the database check passed)."""
    out = {'files': 0, 'bytes': 0, 'kept': 0, 'db_ok': True}
    for p in working_files(data_dir):
        _remove(p, out)
    before = _size(db.path) + _size(db.path + '-wal')
    db.conn.commit()
    out['db_ok'] = db.conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    if out['db_ok']:
        db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.conn.execute('VACUUM')               # gives back the room left by deleted pictures and sections
        db.conn.execute('PRAGMA optimize')
    out['bytes'] += max(0, before - _size(db.path) - _size(db.path + '-wal'))
    from . import textmeasure
    textmeasure._FACES.clear()                  # the measured fonts are read again when next needed
    return out
