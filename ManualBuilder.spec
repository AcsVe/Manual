# PyInstaller spec — one folder (fast start) that Inno Setup packs into ManualBuilderSetup.exe
# Build:  pyinstaller --noconfirm ManualBuilder.spec
# The built-in browser engine (Qt WebEngine) draws the preview and the PDF, so it and what it needs (QtQuick, QtQml,
# QtWebChannel, QtPositioning) are kept; modules the program never uses are left out.
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

EXCLUDE = ['PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtQuick3D', 'PySide6.QtMultimedia', 'PySide6.QtCharts',
           'PySide6.QtDataVisualization', 'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSensors',
           'PySide6.QtSerialPort', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtWebSockets', 'PySide6.QtSpatialAudio',
           'PySide6.QtTextToSpeech', 'PySide6.QtGraphs', 'tkinter']

datas = [('assets', 'assets')] + collect_data_files('docx') + collect_data_files('pdfminer')
a = Analysis(['run.py'], pathex=[], binaries=[], datas=datas,
             hiddenimports=['pypdf', 'PySide6.QtNetwork', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'PySide6.QtPdf', 'PySide6.QtWebEngineCore',
                            'PySide6.QtWebEngineWidgets', 'PySide6.QtPrintSupport', 'pdfminer', 'docx', 'lxml.html'],
             hookspath=[], runtime_hooks=[], excludes=EXCLUDE, cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ManualBuilder', debug=False, strip=False, upx=False,
          console=False, icon='assets/icon.ico', version=None)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='ManualBuilder')
