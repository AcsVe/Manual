"""The default page design of a new manual and the starter structures a manual can be created from."""
import copy

DEFAULT_LAYOUT = {
    'page_size': 'A4', 'orientation': 'landscape',
    'margins': {'top': 30, 'bottom': 18, 'left': 14, 'right': 14},          # millimetres
    'lang_mode': 'bi_side',            # bi_side (Arabic and English side by side) | bi_stack | ar | en
    'fonts': {'ar': 'Tajawal', 'en': 'Tajawal', 'size': 10.5, 'line': 1.45},
    'colors': {'primary': '#0B3D91', 'secondary': '#1F6FD1', 'accent': '#F28C28', 'text': '#1E293B',
               'heading': '#0B3D91', 'table_head': '#0B3D91', 'table_head_text': '#FFFFFF', 'box_border': '#9FB3D1',
               'callout': '#FFF4E0'},
    'header': {'style': 'wave', 'height': 24, 'logo': True, 'start': '', 'center': '', 'end': '{title}',
               'image_id': None},
    'footer': {'style': 'line', 'start': '{issue_label} {issue_date}', 'center': '', 'end': '{page_label} {page} | {pages}'},
    'boxes': True,                      # each section framed (as in many institutional manuals)
    'numbering': False,                 # 1, 1.1, 1.1.1 before the titles
    'toc_depth': 2,
    'watermark': '',
    'page_bg_id': None, 'page_bg_opacity': 0.06,    # older manuals; the full description is page_bg
    'page_bg': None,                    # see backgrounds.py
    'align': 'justify',                 # text alignment: justify | start (right in Arabic, left in English) | center
    'cover': {'style': 'wave', 'bg_id': None, 'bg_opacity': 1.0},
    'policy_footer': True,              # «responsible to maintain» + change history at the end of every policy
    'draft_mark': True,                 # sections not yet approved carry a «draft» mark (when the workflow is on)
    # page numbers: digits latin (1 2 3) | arabic (١ ٢ ٣); front matter (disclaimer, document control, contents)
    # numbered on with the rest (same), in small roman figures (roman) or not numbered (hidden) — the body then
    # starts again at «start»; count_cover: the cover counts as page 1
    'page_numbers': {'digits': 'latin', 'front': 'same', 'start': 1, 'count_cover': True},
}
FRONT_KINDS = ('cover', 'disclaimer', 'doc_control', 'toc')
ALIGNMENTS = {'justify': ('ضبط الطرفين', 'Justified'), 'start': ('من بداية السطر (يمين العربية ويسار الإنجليزية)', 'From the line start (right in Arabic, left in English)'),
              'center': ('توسيط', 'Centred')}
BLOCK_ALIGN = {'': ('كإعداد الدليل', 'As the manual'), 'right': ('يمين', 'Right'), 'center': ('وسط', 'Centre'),
               'left': ('يسار', 'Left'), 'justify': ('ضبط الطرفين', 'Justified')}
PAGE_DIGITS = {'latin': ('أرقام لاتينية (1، 2، 3)', 'Western digits (1, 2, 3)'),
               'arabic': ('أرقام عربية مشرقية (١، ٢، ٣)', 'Arabic-Indic digits (١, ٢, ٣)')}
FRONT_NUMBERING = {'same': ('متصل مع بقية الدليل', 'Continuous with the rest of the manual'),
                   'roman': ('أرقام رومانية صغيرة (i، ii، iii)', 'Small roman figures (i, ii, iii)'),
                   'hidden': ('دون أرقام', 'Not numbered')}
PAGE_NUMBER_FORMATS = {
    'label_of': ('صفحة 3 من 20', 'Page 3 of 20', '{page_label} {page} {of} {pages}'),
    'label_bar': ('صفحة 3 | 20', 'Page 3 | 20', '{page_label} {page} | {pages}'),
    'slash': ('3 / 20', '3 / 20', '{page} / {pages}'),
    'dash': ('- 3 -', '- 3 -', '- {page} -'),
    'plain': ('3', '3', '{page}'),
}

PAGE_SIZES = {'A4': (210, 297), 'A3': (297, 420), 'A5': (148, 210), 'Letter': (216, 279), 'Legal': (216, 356)}
FONTS = {
    'Tajawal': 'tajawal', 'Cairo': 'cairo', 'Noto Naskh Arabic': 'noto-naskh-arabic', 'Amiri': 'amiri',
}
HEADER_STYLES = {'wave': ('موجة', 'Wave'), 'band': ('شريط ملوّن', 'Colour band'), 'line': ('خط سفلي', 'Underline'),
                 'image': ('صورة', 'Image'), 'none': ('بدون', 'None')}
LANG_MODES = {'bi_side': ('عربي وإنجليزي جنباً إلى جنب', 'Arabic and English side by side'),
              'bi_stack': ('عربي ثم إنجليزي', 'Arabic, then English'),
              'ar': ('عربي فقط', 'Arabic only'), 'en': ('إنجليزي فقط', 'English only')}
TOKENS = {
    '{title}': ('عنوان الدليل', 'Manual title'), '{org}': ('اسم المؤسسة', 'Organisation'),
    '{chapter}': ('الباب الحالي', 'Current chapter'), '{section}': ('القسم الحالي', 'Current section'),
    '{issue_no}': ('رقم الإصدار', 'Issue number'), '{issue_date}': ('تاريخ الإصدار', 'Issue date'),
    '{edition}': ('النسخة', 'Edition'), '{page}': ('رقم الصفحة', 'Page number'),
    '{pages}': ('عدد الصفحات', 'Page count'), '{issue_label}': ('عبارة «تاريخ الإصدار»', '«Issue date» label'),
    '{page_label}': ('عبارة «صفحة»', '«Page» label'), '{of}': ('عبارة «من»', '«of» label'),
}

TABLE_PRESETS = {
    'custom': (('جدول', 'Table'), []),
    'authority': (('مصفوفة الصلاحيات والمسؤوليات', 'Authority & responsibility matrix'),
                  [('المهمة', 'Task'), ('مجلس الإدارة', 'Board'), ('المدير العام', 'General manager'),
                   ('مدير الدائرة', 'Head of department'), ('الموظف المختص', 'Officer')]),
    'raci': (('مصفوفة RACI', 'RACI matrix'),
             [('النشاط', 'Activity'), ('المسؤول عن التنفيذ (R)', 'Responsible (R)'),
              ('صاحب القرار (A)', 'Accountable (A)'), ('يُستشار (C)', 'Consulted (C)'), ('يُبلَّغ (I)', 'Informed (I)')]),
    'action_plan': (('خطة تنفيذية', 'Action plan'),
                    [('الهدف', 'Objective'), ('المبادرة / النشاط', 'Initiative / activity'), ('المسؤول', 'Responsible'),
                     ('الإطار الزمني', 'Timeframe'), ('مؤشر الأداء', 'KPI'), ('الموازنة', 'Budget'), ('الحالة', 'Status')]),
    'strategy': (('الخطة الاستراتيجية', 'Strategic plan'),
                 [('المحور', 'Pillar'), ('الهدف الاستراتيجي', 'Strategic goal'), ('المبادرات', 'Initiatives'),
                  ('مؤشرات الأداء', 'KPIs'), ('المستهدف', 'Target')]),
    'risk': (('سجل المخاطر', 'Risk register'),
             [('الخطر', 'Risk'), ('الاحتمالية', 'Likelihood'), ('الأثر', 'Impact'), ('الإجراء الوقائي', 'Mitigation'),
              ('المسؤول', 'Owner')]),
    'kpi': (('مؤشرات الأداء', 'Key performance indicators'),
            [('المؤشر', 'Indicator'), ('طريقة القياس', 'Measure'), ('المستهدف', 'Target'), ('الدورية', 'Frequency'),
             ('المسؤول', 'Owner')]),
    'committee': (('اللجان', 'Committees'),
                  [('اللجنة', 'Committee'), ('الرئيس', 'Chair'), ('الأعضاء', 'Members'), ('المهام', 'Duties'),
                   ('دورية الاجتماع', 'Meeting frequency')]),
}

POLICY_HEADINGS = [('الغاية', 'Purpose'), ('النطاق', 'Scope'), ('التعريفات', 'Definitions'), ('السياسة', 'Policy'),
                   ('الإجراءات', 'Procedures'), ('المسؤوليات', 'Responsibilities'),
                   ('الوثائق ذات العلاقة', 'Related documents')]


def layout_with_defaults(saved):
    """A saved layout merged over the defaults, so a setting added later appears in old manuals too."""
    out = copy.deepcopy(DEFAULT_LAYOUT)
    for k, v in (saved or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def table_data(preset):
    cols = TABLE_PRESETS.get(preset, TABLE_PRESETS['custom'])[1] or [('العمود 1', 'Column 1'), ('العمود 2', 'Column 2')]
    return {'preset': preset, 'columns': [{'ar': a, 'en': e} for a, e in cols],
            'rows': [[{'ar': '', 'en': ''} for _ in cols]], 'first_col_bold': True, 'numbered': True}


def policy_blocks():
    out = []
    for ar, en in POLICY_HEADINGS:
        out.append({'kind': 'heading', 'ar': ar, 'en': en})
        out.append({'kind': 'paragraph', 'ar': '', 'en': ''})
    return out


# A starter structure: (kind, title_ar, title_en, children, extra)
_INSTITUTIONAL = [
    ('cover', 'الغلاف', 'Cover', [], {'in_toc': 0}),
    ('disclaimer', 'تنويه', 'Disclaimer', [], {'in_toc': 0}),
    ('toc', 'الفهرس', 'Contents', [], {'in_toc': 0, 'new_page': 1}),
    ('doc_control', 'توثيق إعداد الدليل', 'Document control', [], {'new_page': 1}),
    ('chapter', 'مقدمة', 'Introduction', [
        ('text', 'نبذة عن المؤسسة', 'About the organisation', [], {}),
        ('text', 'الرؤية', 'Vision', [], {}),
        ('text', 'الرسالة', 'Mission', [], {}),
        ('text', 'القيم', 'Values', [], {}),
        ('text', 'الأهداف', 'Objectives', [], {}),
    ], {}),
    ('chapter', 'الإطار الاستراتيجي والحوكمة', 'Strategic framework & governance', [
        ('text', 'مجلس الإدارة', 'The board', [], {}),
        ('orgchart', 'الهيكل التنظيمي', 'Organisational chart', [], {'new_page': 1}),
        ('table', 'مصفوفة الصلاحيات والمسؤوليات', 'Authority & responsibility matrix', [], {'preset': 'authority'}),
        ('table', 'اللجان', 'Committees', [], {'preset': 'committee'}),
        ('table', 'الخطة الاستراتيجية', 'Strategic plan', [], {'preset': 'strategy'}),
        ('table', 'الخطة التنفيذية', 'Action plan', [], {'preset': 'action_plan'}),
        ('table', 'مؤشرات الأداء', 'Key performance indicators', [], {'preset': 'kpi'}),
        ('table', 'سجل المخاطر', 'Risk register', [], {'preset': 'risk'}),
    ], {}),
    ('chapter', 'الأنظمة والتشريعات', 'Regulations', [
        ('text', 'النظام الداخلي', 'Internal bylaws', [], {}),
        ('text', 'النظام المالي', 'Financial regulation', [], {}),
        ('text', 'نظام المشتريات', 'Purchasing regulation', [], {}),
    ], {}),
    ('chapter', 'السياسات والإجراءات', 'Policies & procedures', [
        ('policy', 'سياسة الموارد البشرية', 'Human resources policy', [], {}),
        ('policy', 'سياسة تكنولوجيا المعلومات', 'Information technology policy', [], {}),
        ('policy', 'سياسة الصحة والسلامة', 'Health & safety policy', [], {}),
        ('policy', 'مدونة قواعد السلوك', 'Code of conduct', [], {}),
    ], {}),
    ('chapter', 'الالتزام والجودة', 'Compliance & quality', [
        ('compliance', 'سجل الالتزام', 'Compliance register', [], {}),
        ('text', 'ضبط الوثائق', 'Document control', [], {}),
    ], {}),
    ('chapter', 'الاعتمادات والمراجع', 'Accreditations & references', [
        ('links', 'روابط ومراجع', 'Links & references', [], {}),
    ], {}),
]
_POLICIES = [
    ('cover', 'الغلاف', 'Cover', [], {'in_toc': 0}),
    ('toc', 'الفهرس', 'Contents', [], {'in_toc': 0, 'new_page': 1}),
    ('doc_control', 'توثيق الإعداد', 'Document control', [], {'new_page': 1}),
    ('policy', 'سياسة 1', 'Policy 1', [], {}),
]
_HANDBOOK = [
    ('cover', 'الغلاف', 'Cover', [], {'in_toc': 0}),
    ('toc', 'الفهرس', 'Contents', [], {'in_toc': 0, 'new_page': 1}),
    ('chapter', 'مرحباً بك', 'Welcome', [('text', 'كلمة الإدارة', 'A word from the management', [], {})], {}),
    ('chapter', 'العمل اليومي', 'Daily work', [('text', 'الدوام والحضور', 'Working hours & attendance', [], {}),
                                                ('text', 'قواعد السلوك', 'Code of conduct', [], {})], {}),
    ('chapter', 'الحقوق والواجبات', 'Rights & duties', [('text', 'الإجازات', 'Leave', [], {}),
                                                         ('text', 'التظلم', 'Grievances', [], {})], {}),
    ('links', 'روابط مفيدة', 'Useful links', [], {}),
]
STARTERS = {
    'institutional': (('دليل مؤسسي كامل (حوكمة، استراتيجية، سياسات، التزام)',
                       'Complete institutional manual (governance, strategy, policies, compliance)'), _INSTITUTIONAL),
    'policies': (('مجموعة سياسات وإجراءات', 'A set of policies & procedures'), _POLICIES),
    'handbook': (('دليل تعريفي (للموظف أو الطالب)', 'Handbook (staff or students)'), _HANDBOOK),
    'blank': (('دليل فارغ', 'Blank manual'), [('cover', 'الغلاف', 'Cover', [], {'in_toc': 0})]),
}


def create_from_starter(db, key, fields):
    """Creates a manual with the starter structure ``key``. ``fields``: the manual's own fields (titles, org…)."""
    data = dict(fields)
    data.setdefault('layout', DEFAULT_LAYOUT)
    mid = db.save_manual(data)
    if key == 'institutional':
        top = db.save_unit({'manual_id': mid, 'kind': 'unit', 'name_ar': 'مجلس الإدارة', 'name_en': 'Board'})
        db.save_unit({'manual_id': mid, 'parent_id': top, 'kind': 'position', 'name_ar': 'المدير العام',
                      'name_en': 'General manager'})

    def add(items, parent):
        for kind, ar, en, children, extra in items:
            sec = {'manual_id': mid, 'parent_id': parent, 'kind': kind, 'title_ar': ar, 'title_en': en,
                   'in_toc': extra.get('in_toc', 1), 'new_page': extra.get('new_page', 1 if kind == 'chapter' else 0)}
            if kind == 'table':
                sec['data'] = table_data(extra.get('preset', 'custom'))
            if kind == 'orgchart':
                sec['data'] = {'root_id': None, 'depth': 0, 'direction': 'down'}
            sid = db.save_section(sec)
            if kind == 'policy':
                db.replace_blocks(sid, policy_blocks())
            elif kind == 'text':
                db.replace_blocks(sid, [{'kind': 'paragraph', 'ar': '', 'en': ''}])
            elif kind == 'links':
                db.replace_blocks(sid, [{'kind': 'links', 'data': {'items': []}}])
            add(children, sid)
    add(STARTERS[key][1], None)
    return mid
