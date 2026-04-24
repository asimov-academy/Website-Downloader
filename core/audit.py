"""
Audit system - text-only snapshots at each pipeline stage for comparison.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

_TEXT_EXTENSIONS = frozenset({
    '.html', '.css', '.js', '.mjs', '.cjs', '.json', '.svg', '.md', '.txt',
    '.xml', '.webmanifest',
})


class AuditRecorder:
    """Captures text-only snapshots of clean/ at each pipeline stage."""

    def __init__(self, audit_dir, log_callback=None):
        self.audit_dir = Path(audit_dir)
        self.log = log_callback or (lambda msg: None)
        self.stages = []
        self._init()

    def _init(self):
        if self.audit_dir.exists():
            shutil.rmtree(self.audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self, stage_label: str, source_dir, description: str = '') -> dict:
        """Copy text-only files from source_dir into audit/<stage_label>/."""
        source_dir = Path(source_dir)
        if not source_dir.exists():
            return {}

        stage_dir = self.audit_dir / stage_label
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)

        files_captured = 0
        bytes_captured = 0

        for path in sorted(source_dir.rglob('*')):
            if not path.is_file():
                continue
            if path.name == 'serve.py':
                continue
            if path.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            # Never capture from inside audit/ itself
            try:
                path.relative_to(self.audit_dir)
                continue
            except ValueError:
                pass

            try:
                relative = path.relative_to(source_dir)
                target = stage_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files_captured += 1
                bytes_captured += path.stat().st_size
            except Exception:
                pass

        info = {
            'name': stage_label,
            'description': description,
            'timestamp': datetime.now().isoformat(),
            'files': files_captured,
            'bytes': bytes_captured,
        }
        self.stages.append(info)
        (stage_dir / '_info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
        self.log(
            f'   Audit [{stage_label}]: {files_captured} arquivos '
            f'({bytes_captured // 1024} KB)'
        )
        return info

    def generate_report(self) -> dict:
        """Compare all snapshots and write audit_report.json."""
        comparisons = []
        for i in range(1, len(self.stages)):
            a = self.stages[i - 1]
            b = self.stages[i]
            comparisons.append(self._compare_stages(
                self.audit_dir / a['name'],
                self.audit_dir / b['name'],
                a['name'], b['name'],
            ))

        report = {
            'generated_at': datetime.now().isoformat(),
            'stages': self.stages,
            'comparisons': comparisons,
        }

        report_path = self.audit_dir / 'audit_report.json'
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        self.log(
            f'   Audit: relatório salvo '
            f'({len(self.stages)} estágios, {len(comparisons)} comparações)'
        )
        return report

    def _compare_stages(
        self, a_dir: Path, b_dir: Path, a_name: str, b_name: str
    ) -> dict:
        a_files = self._index_dir(a_dir)
        b_files = self._index_dir(b_dir)
        all_keys = set(a_files) | set(b_files)

        added = sorted(f for f in all_keys if f not in a_files)
        removed = sorted(f for f in all_keys if f not in b_files)
        changed = []
        bytes_before = sum(a_files.values())
        bytes_after = sum(b_files.values())

        for f in sorted(all_keys):
            if f in a_files and f in b_files and a_files[f] != b_files[f]:
                diff = b_files[f] - a_files[f]
                changed.append({
                    'file': f,
                    'before': a_files[f],
                    'after': b_files[f],
                    'diff': diff,
                })

        changed.sort(key=lambda x: abs(x['diff']), reverse=True)

        return {
            'from': a_name,
            'to': b_name,
            'files_added': len(added),
            'files_removed': len(removed),
            'files_changed': len(changed),
            'bytes_before': bytes_before,
            'bytes_after': bytes_after,
            'bytes_saved': bytes_before - bytes_after,
            'pct_reduction': round(
                (bytes_before - bytes_after) / max(bytes_before, 1) * 100, 1
            ),
            'added': added[:20],
            'removed': removed[:20],
            'top_changes': changed[:15],
        }

    def _index_dir(self, directory: Path) -> dict:
        result = {}
        if not directory.exists():
            return result
        for p in directory.rglob('*'):
            if p.is_file() and p.name != '_info.json':
                try:
                    result[p.relative_to(directory).as_posix()] = p.stat().st_size
                except Exception:
                    pass
        return result
