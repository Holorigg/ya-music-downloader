"""Check source and frozen worker command construction without launching services."""
from pathlib import Path
import os
import sys
import tempfile
from types import ModuleType
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix='ya-music-packaging-check-') as temporary:
    os.environ['MUSIC_DATA_DIR']=str(Path(temporary)/'data')
    from runtime_paths import resource_root,sync_worker_command

    source_root=Path(r'C:\work\desktop')
    source_pythonw=Path(r'C:\work\desktop\.venv\Scripts\pythonw.exe')
    program,args=sync_worker_command(gui=True,executable=source_pythonw,frozen=False,root=source_root)
    assert Path(program)==source_pythonw.with_name('python.exe')
    assert args==['-X','utf8',str(source_root/'run_standalone.py'),'--gui']

    bundled_root=Path(r'C:\portable\MyMusic\_internal')
    frozen_executable=Path(r'C:\portable\MyMusic\MyMusic.exe')
    program,args=sync_worker_command(gui=True,executable=frozen_executable,frozen=True,root=bundled_root)
    assert Path(program)==frozen_executable
    assert args==['--sync-worker','--gui']
    assert Path(program).name.casefold()!='python.exe'

    assert resource_root(frozen=False,module_file=source_root/'runtime_paths.py')==source_root
    assert resource_root(frozen=True,bundle_dir=bundled_root)==bundled_root

    app_source=Path(__file__).with_name('app.py').read_text(encoding='utf-8')
    assert 'sync_worker_command(gui=True)' in app_source
    assert "Path(sys.executable).with_name('python.exe')" not in app_source

    import entrypoint
    worker_module=ModuleType('run_standalone')
    worker_module.main=lambda:17
    gui_module=ModuleType('gui_launcher')
    gui_module.main=lambda:23
    self_test_module=ModuleType('bundle_self_test')
    self_test_module.main=lambda report:29 if report=='report.json' else 0
    previous={name:sys.modules.get(name) for name in ('run_standalone','gui_launcher','bundle_self_test')}
    try:
        sys.modules.update({'run_standalone':worker_module,'gui_launcher':gui_module,'bundle_self_test':self_test_module})
        assert entrypoint.main(['--sync-worker','--gui'])==17
        assert entrypoint.main([])==23
        assert entrypoint.main(['--bundle-self-test','report.json'])==29
    finally:
        for name,module in previous.items():
            if module is None:sys.modules.pop(name,None)
            else:sys.modules[name]=module

    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'tools'))
    from build_windows import build_environment
    unrelated=str(Path(temporary)/'unrelated-native-tools')
    with patch.dict(os.environ,{'PATH':unrelated,'PYTHONPATH':unrelated,'QT_PLUGIN_PATH':unrelated}):
        environment=build_environment(Path(temporary)/'build-profile')
        assert unrelated not in environment['PATH'].split(os.pathsep)
        assert str(Path(sys.executable).parent) in environment['PATH'].split(os.pathsep)
        assert 'PYTHONPATH' not in environment and 'QT_PLUGIN_PATH' not in environment
        assert environment['MUSIC_DATA_DIR']==str(Path(temporary)/'build-profile')
        assert os.environ['PATH']==unrelated

print('Source and frozen worker command checks passed')
