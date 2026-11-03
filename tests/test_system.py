"""System initialisation, going to a page in the preview, and the speed fixes when a manual opens."""
import os

from manual_app.core import cleanup, license as lic


def test_initialise_removes_working_files_only(db, manual, tmp_path, monkeypatch):
    data = os.path.dirname(db.path)
    for f in ('preview', 'export', 'logs', 'backups'):
        os.makedirs(os.path.join(data, f), exist_ok=True)
        with open(os.path.join(data, f, 'x.txt'), 'w') as fh:
            fh.write('x')
    temp = tmp_path / 'temp'
    (temp / 'ManualBuilder').mkdir(parents=True)
    (temp / 'mb-1.pdf').write_bytes(b'%PDF')
    (temp / 'other.pdf').write_bytes(b'%PDF')
    monkeypatch.setattr(cleanup.tempfile, 'gettempdir', lambda: str(temp))
    sections = len(db.sections(manual))
    done = cleanup.initialise(db, data)
    assert done['db_ok'] and done['files'] == 5
    for f in ('preview', 'export', 'logs'):
        assert not os.path.exists(os.path.join(data, f))
    assert os.path.isfile(os.path.join(data, 'backups', 'x.txt'))         # backups are never touched
    assert (temp / 'other.pdf').exists() and not (temp / 'mb-1.pdf').exists()
    assert len(db.sections(manual)) == sections and db.manual(manual)
    assert cleanup.initialise(db, data)['files'] == 0                      # nothing left the second time


def test_fingerprint_is_worked_out_once(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lic, '_KNOWN', {})
    monkeypatch.setattr(lic, '_read_fingerprint', lambda d=None: calls.append(d) or 'ABCDEF0123456789')
    assert lic.machine_fingerprint(str(tmp_path)) == lic.machine_fingerprint(str(tmp_path)) == 'ABCDEF0123456789'
    assert len(calls) == 1


def test_save_keeps_every_block(db, manual):
    s = db.sections(manual)[3]
    blocks = [{'kind': 'paragraph', 'ar': f'فقرة {i}', 'en': f'Paragraph {i}'} for i in range(30)]
    db.replace_blocks(s['id'], blocks)
    assert [b['en'] for b in db.blocks(s['id'])] == [b['en'] for b in blocks]


def test_editor_opens_the_first_section_and_goes_to_a_page(tmp_path, monkeypatch, manual, db):
    import manual_app.ui.editor as editor_mod
    from manual_app.main import AppContext
    from manual_app.ui.main_window import MainWindow
    shown = []
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: shown.append(html))
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    w = MainWindow(ctx)
    ctx.window = w
    w.show()
    w.show_page(w.editor)
    ed = w.editor
    first = db.flat(manual)[0][0]
    assert ed.sid == first['id']                       # a section opens, not the whole manual in the preview
    p = ed.preview
    p._page_count(12)
    assert p.page_no.maximum() == 12 and p.page_no.isEnabled() and '12' in p.page_of.text()
    p.go_to_page(5)                                    # no page view yet: nothing happens, nothing breaks
    w.close()


def test_org_chart_drawn_only_when_shown(tmp_path, monkeypatch, manual, db):
    from manual_app.core import orgchart
    from manual_app.main import AppContext
    from manual_app.ui.main_window import MainWindow
    import manual_app.ui.editor as editor_mod
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: None)
    drawn = []
    real = orgchart.render_svg
    monkeypatch.setattr(orgchart, 'render_svg', lambda *a, **k: drawn.append(1) or real(*a, **k))
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    w = MainWindow(ctx)
    ctx.window = w
    w.show()
    assert not drawn
    w.show_page(w.org)
    assert drawn
    w.close()


def test_whole_manual_preview_waits_for_refresh_while_typing(tmp_path, monkeypatch, manual, db):
    import manual_app.ui.editor as editor_mod
    from manual_app.main import AppContext
    from manual_app.ui.main_window import MainWindow
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: None)
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    w = MainWindow(ctx)
    ctx.window = w
    w.show()
    w.show_page(w.editor)
    ed = w.editor
    ed._touch()
    assert ed._ptimer.isActive()                       # one section: laid out again after a pause
    ed._ptimer.stop()
    ed.preview.scope.setCurrentIndex(ed.preview.scope.findData('all'))
    ed._touch()
    assert not ed._ptimer.isActive() and ed.preview.state.text()
    w.close()
