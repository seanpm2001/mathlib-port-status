from pathlib import Path
import jinja2
import networkx as nx
import re
from typing import Optional, List
from dataclasses import dataclass, field

from mathlibtools.file_status import PortStatus, FileStatus

from enum import Enum

def parse_imports(root_path):
    import_re = re.compile(r"^import ([^ ]*)")

    def mk_label(path: Path) -> str:
        return '.'.join(path.relative_to(root_path).with_suffix('').parts)

    graph = nx.DiGraph()

    for path in root_path.glob('**/*.lean'):
        if path.parts[1] in ['tactic', 'meta']:
            continue
        graph.add_node(mk_label(path))

    for path in root_path.glob('**/*.lean'):
        if path.parts[1] in ['tactic', 'meta']:
            continue
        label = mk_label(path)
        for line in path.read_text().split('\n'):
            m = import_re.match(line)
            if m:
                imported = m.group(1)
                if imported.startswith('tactic.') or imported.startswith('meta.'):
                    continue
                if imported not in graph.nodes:
                    if imported + '.default' in graph.nodes:
                        imported = imported + '.default'
                    else:
                        imported = 'lean_core.' + imported
                graph.add_edge(imported, label)
    return graph

class PortState(Enum):
    UNPORTED = 'UNPORTED'
    IN_PROGRESS = 'IN_PROGRESS'
    PORTED = 'PORTED'

@dataclass
class Mathlib3FileData:
    status: FileStatus
    lines: Optional[int]
    dependents: List['Mathlib3FileData'] = field(default_factory=list)
    dependencies: List['Mathlib3FileData'] = field(default_factory=list)

    @property
    def state(self):
        if self.status.ported:
            return PortState.PORTED
        elif self.status.mathlib4_pr:
            return PortState.IN_PROGRESS
        else:
            return PortState.UNPORTED
    
    @property
    def dep_counts(self):
        return [
            len([x for x in self.dependencies if x.state == s])
            for s in PortState]

status = PortStatus.deserialize_old()

build_dir = Path('build') 
build_dir.mkdir(parents=True, exist_ok=True)

template_loader = jinja2.FileSystemLoader(searchpath="templates/")
template_env = jinja2.Environment(loader=template_loader)
t = template_env.get_template('index.j2')

mathlib_dir = build_dir / 'repos' / 'mathlib'

graph = parse_imports(mathlib_dir / 'src')

(build_dir / 'html').mkdir(parents=True, exist_ok=True)
with (build_dir / 'html' / 'index.html').open('w') as index_f:
    data = {}
    for f_import, f_status in status.file_statuses.items():
        path = mathlib_dir / 'src' / Path(*f_import.split('.')).with_suffix('.lean')
        try:
            with path.open('r') as f_src:
                lines = len(f_src.readlines())
        except IOError:
            lines = None
        data[f_import] = Mathlib3FileData(
            status=f_status, 
            lines=lines,
        )
    ported = {}
    in_progress = {}
    unported = {}
    groups = {
        PortState.PORTED: ported,
        PortState.IN_PROGRESS: in_progress,
        PortState.UNPORTED: unported,
    }
    for f_import, f_data in data.items():
        f_data.dependents = [
            data[k] for k in nx.descendants(graph, f_import) if k in data
        ]
        f_data.dependencies = [
            data[k] for k in nx.ancestors(graph, f_import) if k in data
        ]
        groups[f_data.state][f_import] = f_data
    index_f.write(t.render(ported=ported, unported=unported, in_progress=in_progress))
