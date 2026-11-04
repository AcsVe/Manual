"""Tables (borders, shading, contrast, cut-off tables fitted step by step, short tables kept on one page, related
tables together) and the formatting bar's «apply to» (font, size, text colour and highlight on a block, a section,
chosen sections, a range of pages or the whole manual), in the preview and in Word."""
import zipfile

from manual_app.core import doctor, formatting as FMT, tablefit
from manual_app.core.html import build_html
from manual_app.core.richtext import clean, runs


def _vision(db, manual):
    return next(s for s in db.sections(manual) if s['title_en'] == 'Vision')


def _table(rows=3, cols=2, **extra):
    return dict({'columns': [{'ar': f'عمود {i}', 'en': f'Col {i}'} for i in range(cols)],
                 'rows': [[{'ar': f'خلية {r}{c}', 'en': f'cell {r}{c}'} for c in range(cols)] for r in range(rows)]}, **extra)


# ── checks on the table colours ─────────────────────────────────────────
def test_borders_shading_and_contrast_found_fixed_and_undone(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(colors={'border': '#FFFFFF', 'head': '#FFFFFF', 'head_text': '#000000'})},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(colors={'head_text': '#1A50A0', 'text': '#DDDDDD'})},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(borders=False)},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table()},
    ])
    found = [(x['rule'], x['b']) for x in doctor.check(db, manual) if x['sid'] == v['id'] and x['cat'] == 'tables']
    assert ('table_no_border', 0) in found and ('table_no_shade', 0) in found
    assert ('table_contrast', 1) in found and ('table_no_border', 2) in found
    assert not [f for f in found if f[1] == 3]          # the manual's own table colours read well
    issues = [x for x in doctor.check(db, manual) if x['sid'] == v['id'] and x['cat'] == 'tables']
    _done, _skipped, undo = doctor.apply(db, manual, issues)
    assert not [x for x in doctor.check(db, manual) if x['sid'] == v['id'] and x['cat'] == 'tables']
    bl = db.blocks(v['id'])
    assert doctor.contrast(bl[1]['data']['colors']['text'], '#FFFFFF') >= 4.5
    assert 'borders' not in bl[2]['data']
    doctor.undo(db, undo)
    assert db.blocks(v['id'])[2]['data']['borders'] is False


def test_highlight_is_not_an_odd_text_colour_and_colour_fix_keeps_fonts(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'en': 'x',
                                 'ar': '<span style="background-color:#FFF59D">مظلل</span> و<span style="color:#123456;font-family:\'Amiri\'">ملون</span>'}])
    issues = [x for x in doctor.check(db, manual) if x['sid'] == v['id'] and x['rule'] == 'inline_colors']
    assert len(issues) == 1
    doctor.apply(db, manual, issues)
    ar = db.blocks(v['id'])[0]['ar']
    assert '#123456' not in ar and 'Amiri' in ar and 'background-color' in ar


# ── fitting step by step ─────────────────────────────────────────────────
def test_steps_stop_at_the_first_enough(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'table', 'ar': '', 'en': '', 'data': _table()},
                                {'kind': 'table', 'ar': '', 'en': '', 'data': _table()}])
    seen = []

    def measure(sids):              # the first table fits after two steps, the second never
        seen.append(sids)
        d0 = db.blocks(v['id'])[0]['data']
        return [r for r in (('b', v['id'], 0), ('b', v['id'], 1)) if not (r[2] == 0 and d0.get('scale'))]
    from manual_app.core.templates import layout_with_defaults
    portrait = layout_with_defaults(db.manual(manual)['layout'])['orientation'] == 'portrait'
    taken, pending = tablefit.fit(db, manual, [('b', v['id'], 0), ('b', v['id'], 1)], measure)
    # a landscape page is the last step, for a portrait manual only
    assert taken[('b', v['id'], 0)] == 'smaller' and taken[('b', v['id'], 1)] == ('landscape' if portrait else 'break')
    assert pending == [('b', v['id'], 1)]
    d0, d1 = (b['data'] for b in db.blocks(v['id']))
    assert d0.get('compact') and d0.get('scale') == tablefit.SMALL_SCALE and not d0.get('break_words')
    assert d1.get('compact') and d1.get('break_words') and bool(d1.get('landscape')) == portrait
    assert tablefit.level(d0) == 2 and tablefit.level(d1) == (4 if portrait else 3)
    tablefit.set_level(d1, 1)
    assert d1.get('compact') and 'scale' not in d1 and 'landscape' not in d1


def test_cut_off_table_measured_and_fitted(db, manual):
    from manual_app.core.pdf import audit_blocking, page_size_mm
    v = _vision(db, manual)
    word = 'Pneumonoultramicroscopic'
    data = _table(rows=2, cols=40)
    for r in data['rows']:
        for c in r:
            c['en'] = word
    db.replace_blocks(v['id'], [{'kind': 'table', 'ar': '', 'en': '', 'data': data}])
    a = audit_blocking(build_html(db, manual, 'print', only=[v['id']]), page_size_mm(db.manual(manual)), 240)
    issues = doctor.from_audit(db, manual, a)
    assert [x for x in issues if x['rule'] == 'table_clipped' and x['b'] == 0]
    refs = tablefit.clipped_refs(db, a)
    taken, pending = tablefit.fit(db, manual, refs, lambda sids: tablefit.measure_clipped(db, manual, sids, 240))
    assert taken and not pending
    assert tablefit.level(db.blocks(v['id'])[0]['data']) >= 1


def test_table_options_in_the_pages(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(keep=True, break_words=True, borders=False, caption_ar='عنوان', caption_en='Title')},
        {'kind': 'heading', 'ar': 'جدول أ', 'en': 'Table A'},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(group='g1')},
        {'kind': 'heading', 'ar': 'جدول ب', 'en': 'Table B'},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(group='g1')},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(landscape=True)},
    ])
    lay = dict(db.manual(manual)['layout'], orientation='portrait')
    db.save_manual({'layout': lay}, manual)
    html = build_html(db, manual, 'print')
    assert 'keep1' in html and ' brk' in html and ' nob' in html
    i = html.index('class="keep tgroup"')
    assert html.count('class="keep tgroup"') == 1 and 'جدول أ' in html[i:i + 4000] and 'جدول ب' in html[i:]
    assert 'class="pgoT"' in html                     # the landscape table on a turned page of its own


def test_fix_all_tables_plan(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'table', 'ar': '', 'en': '', 'data': _table(borders=False)},
                                {'kind': 'table', 'ar': '', 'en': '', 'data': _table(colors={'head': '#FFFFFF', 'head_text': '#000000'})}])
    issues = doctor.check(db, manual)
    counts, tables = tablefit.plan(issues)
    assert counts.get('table_no_border') == 1 and counts.get('table_no_shade') == 1 and len(tables) >= 2
    undo = tablefit.snapshot(db, manual, tablefit.table_sections(db, manual))
    doctor.apply(db, manual, [x for x in issues if x['cat'] == 'tables' and x['fix']])
    assert db.blocks(v['id'])[0]['data'].get('borders') is not False
    doctor.undo(db, undo)
    assert db.blocks(v['id'])[0]['data']['borders'] is False


# ── the formatting bar's «apply to» ──────────────────────────────────────
def test_rich_text_keeps_font_size_and_highlight():
    html = '<span style=" font-family:\'Amiri\'; font-size:14pt; color:#ff0000; background-color:#ffff00;">x</span> y'
    out = clean(html)
    assert "font-family" in out and 'font-size:14pt' in out and 'background-color:#ffff00' in out
    assert clean(out) == out
    r = runs(html)[0][1]
    assert r['font'] == 'Amiri' and r['pt'] == 14 and r['color'] == '#ff0000' and r['bg'].lower() == '#ffff00'


def test_scopes_and_filters(db, manual):
    v = _vision(db, manual)
    other = next(s for s in db.sections(manual) if s['id'] != v['id'] and s['kind'] in ('text', 'policy'))
    db.replace_blocks(v['id'], [{'kind': 'heading', 'ar': 'عنوان', 'en': 'Head'},
                                {'kind': 'paragraph', 'ar': 'فقرة', 'en': 'Para'},
                                {'kind': 'table', 'ar': '', 'en': '', 'data': _table()},
                                {'kind': 'pagebreak', 'ar': '', 'en': ''}])
    db.replace_blocks(other['id'], [{'kind': 'paragraph', 'ar': 'أخرى', 'en': 'Other'}])
    t = FMT.targets(db, manual, 'section', 'all', current=v['id'])
    assert t == [('b', v['id'], 0), ('b', v['id'], 1), ('b', v['id'], 2)]       # never a page break
    assert FMT.targets(db, manual, 'section', 'headings', current=v['id']) == [('b', v['id'], 0)]
    assert FMT.targets(db, manual, 'section', 'tables', current=v['id']) == [('b', v['id'], 2)]
    assert FMT.targets(db, manual, 'block', current=v['id'], block=1) == [('b', v['id'], 1)]
    chosen = FMT.targets(db, manual, 'sections', 'paragraphs', chosen=[v['id'], other['id']])
    assert ('b', other['id'], 0) in chosen and ('b', v['id'], 1) in chosen and ('b', v['id'], 0) not in chosen
    whole = FMT.targets(db, manual, 'manual', 'paragraphs')
    assert set(chosen) <= set(whole)
    pages = FMT.page_refs([{'b': [f'{v["id"]}:0'], 's': [v['id']]}, {'b': [f'{v["id"]}:1', f'{other["id"]}:0'], 's': []}], 2, 2)
    assert set(FMT.targets(db, manual, 'pages', 'all', pages=pages)) == {('b', v['id'], 1), ('b', other['id'], 0)}
    assert FMT.plan(db, chosen)['sections'] == 2


def test_apply_one_language_then_undo(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'فقرة عربية', 'en': 'English paragraph'},
                                {'kind': 'table', 'ar': '', 'en': '', 'data': _table()}])
    refs = FMT.targets(db, manual, 'section', 'all', current=v['id'])
    n, undo = FMT.apply(db, manual, refs, {'font': 'Amiri', 'pt': 13, 'color': '#AA0000', 'bg': '#FFF59D'}, 'ar')
    assert n == 2
    st = db.blocks(v['id'])[0]['style']
    assert st['ar'] == {'font': 'Amiri', 'pt': 13, 'color': '#AA0000', 'bg': '#FFF59D'} and 'en' not in st
    html = build_html(db, manual, 'print')
    assert "font-family:'Amiri';font-size:13pt;color:#AA0000;background-color:#FFF59D" in html
    assert html.count('background-color:#FFF59D') >= 1 + 4        # the paragraph and the table cells, Arabic only
    n, _u = FMT.apply(db, manual, refs[:1], {'pt': 12}, 'both')
    st = db.blocks(v['id'])[0]['style']
    assert st['pt'] == 12 and 'pt' not in st['ar']                  # the latest choice for both languages shows
    doctor.undo(db, undo)
    assert not (db.blocks(v['id'])[0].get('style') or {}).get('ar')


def test_block_fonts_found_everywhere(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': '<span style="font-family:\'Cairo\'">x</span>', 'en': 'y',
                                 'style': {'en': {'font': 'Amiri'}}}])
    fonts = db.block_fonts(manual)
    assert {'Cairo', 'Amiri'} <= fonts


def test_word_follows_the_preview(db, manual, tmp_path):
    from manual_app.core.docx_export import export_docx
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [
        {'kind': 'paragraph', 'ar': 'نص مظلل', 'en': 'English', 'style': {'ar': {'font': 'Amiri', 'pt': 15, 'bg': '#FFF59D'}}},
        {'kind': 'heading', 'ar': 'جدول', 'en': 'Table'},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(keep=True, compact=True, scale=80, caption_ar='عنوان الجدول',
                                                            colors={'border': '#336699'})},
        {'kind': 'table', 'ar': '', 'en': '', 'data': _table(landscape=True, break_words=True)},
    ])
    db.save_manual({'layout': dict(db.manual(manual)['layout'], orientation='portrait')}, manual)
    out = tmp_path / 'm.docx'
    export_docx(db, manual, str(out))
    xml = zipfile.ZipFile(out).read('word/document.xml').decode('utf-8')
    assert 'w:fill="FFF59D"' in xml and 'Amiri' in xml and 'w:sz w:val="30"' in xml       # 15 pt = 30 half-points
    assert 'w:color="336699"' in xml and 'w:cantSplit' in xml and 'w:keepNext' in xml
    assert 'عنوان الجدول' in xml and 'w:orient="landscape"' in xml and 'w:tblLayout w:type="fixed"' in xml


# ── the bar in the editor ────────────────────────────────────────────────
def test_format_bar_on_the_selection_and_scopes(db, manual):
    from manual_app.ui.editor import FormatBar, RichEdit
    bar = FormatBar()
    ed = RichEdit(True)
    ed.set_value('نص للتجربة')
    bar.set_target(ed)
    ed.selectAll()
    bar._set('font', 'Amiri')
    bar._set('pt', 16)
    bar._set('bg', '#FFF59D')
    v = ed.value()
    assert "Amiri" in v and 'font-size:16pt' in v and 'background-color:#fff59d' in v.lower()
    plain = RichEdit(False)
    plain.set_value('typed text')
    assert 'font-family' not in plain.value() and 'font-size' not in plain.value()
    bar.scope.setCurrentIndex(bar.scope.findData('pages'))
    assert not bar.page_from.isHidden() and bar.pick_secs.isHidden()
    bar.scope.setCurrentIndex(bar.scope.findData('sections'))
    assert not bar.pick_secs.isHidden() and bar.page_from.isHidden()
