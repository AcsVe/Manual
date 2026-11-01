"""The manual checker: what it finds, what its fixes do, and that a fix can be undone."""
from manual_app.core import doctor
from manual_app.core.html import build_html


def _vision(db, manual):
    return next(s for s in db.sections(manual) if s['title_en'] == 'Vision')


def test_finds_and_fixes_text_points(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [
        {'kind': 'pagebreak', 'ar': '', 'en': ''},
        {'kind': 'paragraph', 'ar': '• البند الأول<br>• البند الثاني', 'en': '• first<br>• second'},
        {'kind': 'paragraph', 'ar': 'This is English text only', 'en': ''},
        {'kind': 'paragraph', 'ar': 'نص  عربي , مع مسافات ?‏', 'en': 'text'},
        {'kind': 'paragraph', 'ar': 'رمز  وحروف ﺠميﻊ و)قوس(', 'en': 'x'},
        {'kind': 'pagebreak', 'ar': '', 'en': ''}, {'kind': 'pagebreak', 'ar': '', 'en': ''},
        {'kind': 'paragraph', 'ar': 'خاتمة', 'en': 'End'},
    ])
    found = {x['rule'] for x in doctor.check(db, manual) if x['sid'] == v['id']}
    assert {'pb_first', 'manual_bullets', 'swapped', 'bidi_marks', 'spacing', 'ar_punct', 'pua_symbols', 'ar_forms',
            'brackets', 'pb_double'} <= found
    issues = [x for x in doctor.check(db, manual) if x['sid'] == v['id']]
    done, _skipped, undo = doctor.apply(db, manual, issues)
    assert done >= 10
    bl = db.blocks(v['id'])
    kinds = [b['kind'] for b in bl]
    assert kinds[0] == 'bullets' and kinds.count('pagebreak') == 1 and db.section(v['id'])['new_page'] == 1
    assert bl[0]['ar'] == 'البند الأول\nالبند الثاني' and bl[0]['en'] == 'first\nsecond'
    assert bl[1]['ar'] == '' and bl[1]['en'] == 'This is English text only'
    assert bl[2]['ar'] == 'نص عربي، مع مسافات؟'
    assert bl[3]['ar'] == 'رمز ✓ وحروف جميع و(قوس)'
    doctor.undo(db, undo)
    assert [b['kind'] for b in db.blocks(v['id'])][:2] == ['pagebreak', 'paragraph']
    assert db.section(v['id'])['new_page'] == 0


def test_tables_and_page_setup(db, manual):
    m = db.manual(manual)
    lay = dict(m['layout'], margins={'top': 10, 'bottom': 5, 'left': 14, 'right': 14},
               footer={'style': 'line', 'start': '{issue_date}', 'center': '{pg}', 'end': ''})
    db.save_manual({'layout': lay}, manual)
    v = _vision(db, manual)
    long_ = {'ar': 'نص طويل مدمج في عدة صفوف', 'en': 'Long text merged down the rows'}
    db.replace_blocks(v['id'], [{'kind': 'table', 'ar': '', 'en': '', 'data': {
        'columns': [{'ar': 'عنوان الجدول كاملاً', 'en': 'The whole table title'}] * 3 + [{'ar': '', 'en': ''}],
        'rows': [[{'ar': 'أ', 'en': 'A'}, {'ar': 'ب', 'en': 'B'}, {'ar': 'ج', 'en': 'C'}],
                 [long_, {'ar': 'نعم', 'en': 'R'}, {'ar': 'نعم', 'en': 'R'}],
                 [long_, {'ar': 'نعم', 'en': 'R'}, {'ar': 'نعم', 'en': 'R'}],
                 [long_, {'ar': 'نعم', 'en': 'R'}, {'ar': 'نعم', 'en': 'R'}],
                 [{'ar': '', 'en': ''}] * 4]}}])
    found = {x['rule']: x for x in doctor.check(db, manual)}
    for rule in ('margin_header', 'margin_small', 'no_page_number', 'unknown_token', 'table_merged', 'table_ragged',
                 'table_empty_col', 'table_empty_rows'):
        assert rule in found, rule
    doctor.apply(db, manual, [x for x in doctor.check(db, manual) if x['safe']])
    lay = db.manual(manual)['layout']
    assert lay['margins']['top'] >= 27 and lay['margins']['bottom'] >= 12
    assert '{page}' in lay['footer']['end'] and '{pg}' not in lay['footer']['center']
    d = db.blocks(v['id'])[0]['data']
    assert d['caption_en'] == 'The whole table title' and [c['en'] for c in d['columns']] == ['A', 'B', 'C']
    # merged text stays in its top cell; short repeated values are real data and stay
    assert [[c['en'] for c in r] for r in d['rows']] == [['Long text merged down the rows', 'R', 'R'], ['', 'R', 'R'], ['', 'R', 'R']]


def test_ignore_and_settings(db, manual):
    x = next(x for x in doctor.check(db, manual) if x['rule'] == 'logo_flag')
    doctor.ignore(db, manual, [x['key']])
    assert not any(y['key'] == x['key'] for y in doctor.check(db, manual))
    assert any(y['key'] == x['key'] and y['hidden'] for y in doctor.check(db, manual, {'show_hidden': True}))
    assert not any(y['rule'] == 'empty_block' for y in doctor.check(db, manual, {'disabled': ['empty_block']}))


def test_autofix_on_save_keeps_the_rest():
    blocks = [{'kind': 'paragraph', 'ar': 'نص‏  هنا', 'en': 'a  b'}, {'kind': 'paragraph', 'ar': '', 'en': ''}]
    out, n = doctor.autofix_blocks(blocks)
    assert n >= 2 and out[0]['ar'] == 'نص هنا' and out[0]['en'] == 'a b' and len(out) == 2


def test_page_numbering_options(db, manual):
    m = db.manual(manual)
    db.save_manual({'layout': dict(m['layout'], page_numbers={'digits': 'arabic', 'front': 'roman', 'start': 1,
                                                                 'count_cover': True})}, manual)
    html = build_html(db, manual, 'print')
    assert 'counter(page, arabic-indic)' in html and 'counter(page, lower-roman)' in html
    assert 'class="sec lvl0 k-disclaimer front' in html.replace('  ', ' ') or ' front' in html
    assert 'pgreset' in html and '--pagedjs-page-count' in html


def test_long_side_by_side_text_goes_in_pieces(db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'جملة عربية طويلة. ' * 120, 'en': 'A long English sentence. ' * 120}])
    html = build_html(db, manual, 'print', only=[v['id']])
    assert html.count('class="pair blk"') >= 4
    assert 'data-k=' in html and 'data-n=' in html
