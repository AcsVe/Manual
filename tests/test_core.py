import os

from manual_app.core import importer, orgchart, templates
from manual_app.core.html import build_html
from manual_app.core.richtext import clean, lines, plain


def test_starter_structure(db, manual):
    flat = db.flat(manual)
    kinds = [s['kind'] for s, _ in flat]
    assert kinds[:4] == ['cover', 'disclaimer', 'toc', 'doc_control']
    assert 'policy' in kinds and 'orgchart' in kinds and 'compliance' in kinds and 'table' in kinds
    pol = next(s for s, _ in flat if s['kind'] == 'policy')
    assert [b['kind'] for b in db.blocks(pol['id'])][:2] == ['heading', 'paragraph']


def test_tree_moves_and_protected_delete(db, manual):
    chapter = next(s for s in db.sections(manual) if s['kind'] == 'chapter')
    child = next(s for s in db.sections(manual) if s['parent_id'] == chapter['id'])
    assert db.delete_sections([chapter['id']]) == [chapter['id']]          # has sub-sections: kept
    assert not db.move_section(chapter['id'], child['id'])                 # never inside its own child
    assert db.move_section(child['id'], None)
    assert db.section(child['id'])['parent_id'] is None


def test_revisions_bump_version(db, manual):
    pol = next(s for s in db.sections(manual) if s['kind'] == 'policy')
    db.add_revision(pol['id'], '1.1', 'تحديث', 'Update', 'FH', '2026-02-01')
    s = db.section(pol['id'])
    assert s['version'] == '1.1' and db.revisions(pol['id'])[0]['changes_en'] == 'Update'


def test_html_contains_content_both_languages(db, manual):
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'رؤيتنا <b>واضحة</b>', 'en': 'Our vision'},
                                {'kind': 'bullets', 'ar': 'أ\nب', 'en': 'a\nb'}])
    html = build_html(db, manual, 'print')
    assert 'رؤيتنا <b>واضحة</b>' in html and 'Our vision' in html and '<li>ب</li>' in html
    assert '@page' in html and 'counter(pages)' in html and 'Paged' in html
    web = build_html(db, manual, 'web')
    assert 'id="q"' in web and 'Paged' not in web and 'Our vision' in web


def test_language_modes(db, manual):
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'نص عربي', 'en': 'English text'}])
    m = db.manual(manual)
    for mode, has_ar, has_en in (('ar', True, False), ('en', False, True), ('bi_stack', True, True)):
        db.save_manual({'layout': dict(m['layout'], lang_mode=mode)}, manual)
        html = build_html(db, manual, 'print', only=[v['id']])
        assert ('نص عربي' in html) == has_ar and ('English text' in html) == has_en


def test_orgchart_svg(db, manual):
    roots = db.org_tree(manual)
    svg = orgchart.render_svg(roots, 'bi_side')
    assert svg.startswith('<svg') and 'المدير العام' in svg and 'General manager' in svg


def test_richtext_is_safe():
    assert clean('<script>x</script><b>a</b>') == 'x<b>a</b>'
    assert 'onclick' not in clean('<a href="https://x.org" onclick="y">l</a>')
    assert clean('<a href="javascript:alert(1)">l</a>') == 'l'
    assert plain('<p>a</p><p>b</p>') == 'a\nb'
    assert lines('• one\n- two\n\n') == ['one', 'two']


def test_fix_arabic_from_pdf():
    assert importer.fix_arabic('يبرعلا دئارلا ةسردم') == 'مدرسة الرائد العربي'
    assert importer.fix_arabic('األولى') == 'الأولى'


def test_merge_language_runs():
    secs = [importer._new(2, '', 'Purpose'), importer._new(2, '', 'Scope'), importer._new(2, 'الغاية', ''), importer._new(2, 'النطاق', '')]
    secs[0]['blocks'] = [{'kind': 'paragraph', 'ar': '', 'en': 'p'}]
    secs[2]['blocks'] = [{'kind': 'paragraph', 'ar': 'غ', 'en': ''}]
    out = importer.merge_language_runs(secs)
    assert [(s['title_ar'], s['title_en']) for s in out] == [('الغاية', 'Purpose'), ('النطاق', 'Scope')]
    assert out[0]['blocks'][0] == {'kind': 'paragraph', 'ar': 'غ', 'en': 'p'}


def test_word_export_and_import_round_trip(db, manual, tmp_path):
    from manual_app.core.docx_export import export_docx
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'رؤية المدرسة', 'en': 'The school vision'}])
    path = export_docx(db, manual, str(tmp_path / 'm.docx'))
    assert os.path.getsize(path) > 5000
    secs, imgs = importer.import_docx(path)
    titles = [s['title_en'] for s in secs]
    assert 'Vision' in titles
    vis = secs[titles.index('Vision')]
    assert any('رؤية المدرسة' in (b.get('ar') or '') and 'The school vision' in (b.get('en') or '') for b in vis['blocks'])
    ids = importer.add_to_manual(db, manual, secs, imgs)
    assert len(ids) == len(secs)


def test_html_import(tmp_path, db, manual):
    p = tmp_path / 'p.html'
    p.write_text('<html><head><title>دليل</title></head><body><h1>الفصل الأول</h1><p>نص عربي</p><p>English text</p>'
                 '<ul><li>a</li><li>b</li></ul><h2>Scope</h2><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>',
                 encoding='utf-8')
    secs, _ = importer.import_html(str(p))
    assert secs[0]['title_ar'] == 'الفصل الأول'
    assert secs[0]['blocks'][0] == {'kind': 'paragraph', 'ar': 'نص عربي', 'en': 'English text'}
    assert secs[0]['blocks'][1]['kind'] == 'bullets'
    assert secs[1]['blocks'][0]['kind'] == 'table'


def test_assets_protected(db, manual):
    aid = db.add_asset('x.png', b'123', 'image/png')
    db.save_manual({'logo_id': aid}, manual)
    assert db.delete_assets([aid]) == [aid]
    db.save_manual({'logo_id': None}, manual)
    assert db.delete_assets([aid]) == []


def test_duplicate_manual(db, manual):
    new = db.duplicate_manual(manual)
    assert len(db.sections(new)) == len(db.sections(manual))
    assert len(db.org_units(new)) == len(db.org_units(manual))


def test_users_protection(db):
    a = db.save_user({'name': 'A', 'username': 'a', 'password': 'secret1', 'role': 'admin'})
    assert db.check_user('a', 'secret1') and not db.check_user('a', 'wrong')
    assert db.delete_users([a], current_id=a) == [a]


def test_license_salt_differs():
    from manual_app.core import license as lic
    assert lic.SALT == 'MANUAL-BUILDER|'


def test_layout_defaults_merge():
    lay = templates.layout_with_defaults({'colors': {'primary': '#000000'}})
    assert lay['colors']['primary'] == '#000000' and lay['colors']['accent'] == templates.DEFAULT_LAYOUT['colors']['accent']
