"""Arnés de auditoría — SOLO LECTURA sobre el repositorio.

No importa main.py, no toca la base de datos, no hace red. Solo analiza
el código fuente con AST y expresiones regulares, y emite señales
compactas para clasificar cada módulo.
"""
import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / 'main.py'
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)

AUTH_DEPS = ('get_current_user', 'get_verified_user', 'get_optional_user')

# Agrupación por dominio funcional, en el orden de los 10 puntos de JC
DOMAINS = [
    ('1. Registro e identidad',      ('/auth', '/voter/register', '/verify', '/users')),
    ('2. Consultas: crear/segmentar',('/debates', '/organizer/consultations', '/organizers/debates')),
    ('3. Debate/voto/resultados',    ('/debates/', '/opinions', '/r/')),
    ('5-6. Campañas y publicidad',   ('/marketer', '/advertiser', '/ads', '/campaign')),
    ('6b. Pagos y ledger',           ('/payments', '/admin/ledger', '/admin/payments')),
    ('7. Portales',                  ('/voter', '/marketer-portal', '/organizer', '/marketers', '/organizers')),
    ('8. Apps/idiomas/Prefy',        ('/prefy', '/lang.js', '/translate.js', '/countries', '/geo')),
    ('9. Admin/seguridad/ops',       ('/admin', '/health', '/ping')),
]


def route_domain(path):
    for name, prefixes in DOMAINS:
        for p in prefixes:
            if path.startswith(p):
                return name
    return 'otros'


def routes():
    out = []
    for n in ast.walk(TREE):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
                continue
            if getattr(d.func.value, 'id', '') != 'app':
                continue
            if d.func.attr not in ('get', 'post', 'put', 'patch', 'delete'):
                continue
            if not (d.args and isinstance(d.args[0], ast.Constant)):
                continue
            seg = ast.get_source_segment(SRC, n) or ''
            args = [a.arg for a in n.args.args]
            calls = {c.func.id for c in ast.walk(n)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            out.append({
                'method': d.func.attr.upper(),
                'path': str(d.args[0].value),
                'fn': n.name,
                'line': n.lineno,
                'lines': (n.end_lineno or n.lineno) - n.lineno,
                'session': any(f'Depends({x})' in seg for x in AUTH_DEPS),
                'secret': ('ADMIN_SECRET' in seg or '_check_admin' in calls
                           or 'x_agent_secret' in args),
                'mutating': d.func.attr in ('post', 'put', 'patch', 'delete'),
            })
    return out


def stub_signals():
    """Funciones vacías, NotImplementedError, y marcadores de trabajo pendiente."""
    empty, notimpl = [], []
    for n in ast.walk(TREE):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = [s for s in n.body if not (isinstance(s, ast.Expr)
                                          and isinstance(s.value, ast.Constant)
                                          and isinstance(s.value.value, str))]
        if not body or all(isinstance(s, ast.Pass) for s in body):
            empty.append(n.name)
        for s in ast.walk(n):
            if isinstance(s, ast.Raise) and isinstance(s.exc, (ast.Call, ast.Name)):
                nm = getattr(s.exc, 'id', None) or getattr(getattr(s.exc, 'func', None), 'id', None)
                if nm == 'NotImplementedError':
                    notimpl.append(n.name)
    return empty, sorted(set(notimpl))


def markers():
    pats = {
        'TODO': r'\bTODO\b', 'FIXME': r'\bFIXME\b', 'XXX': r'\bXXX\b',
        'HACK': r'\bHACK\b', 'pendiente': r'\bpendiente\b',
        'placeholder': r'\bplaceholder\b', 'por implementar': r'por implementar',
        'no implementado': r'no implementad[oa]',
        'simulado/mock': r'\bmock\b|\bsimulad[oa]\b|\bfake\b|\bstub\b',
        'provisional': r'\bprovisional\b|\btemporal\b|\bpor ahora\b',
    }
    counts = {}
    files = [p for p in ROOT.glob('*.py')] + [p for p in ROOT.glob('*.html')]
    for k, pat in pats.items():
        tot = 0
        per = defaultdict(int)
        for f in files:
            try:
                t = f.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            c = len(re.findall(pat, t, re.I))
            if c:
                per[f.name] = c
                tot += c
        counts[k] = (tot, dict(sorted(per.items(), key=lambda x: -x[1])[:4]))
    return counts


def business_gates():
    """Constantes que declaran que algo NO está aprobado/activo."""
    found = []
    for n in TREE.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            nm = n.targets[0].id
            if isinstance(n.value, ast.Constant) and isinstance(n.value.value, bool):
                if nm.isupper():
                    found.append((nm, n.value.value, n.lineno))
    return found


def env_dependencies():
    """Variables de entorno de las que depende una función, con el patrón
    'si no está, la función se desactiva o falla'."""
    envs = defaultdict(set)
    for m in re.finditer(r"os\.(?:getenv|environ\.get)\(\s*'([A-Z0-9_]+)'", SRC):
        ln = SRC[:m.start()].count('\n') + 1
        envs[m.group(1)].add(ln)
    return {k: len(v) for k, v in sorted(envs.items())}


def test_inventory():
    out = []
    for f in sorted(ROOT.glob('test_*.py')):
        t = f.read_text(encoding='utf-8', errors='ignore')
        n_test = len(re.findall(r'\n\s*def test_', t))
        out.append((f.name, n_test, len(t.splitlines())))
    for f in sorted(ROOT.glob('test_*.mjs')):
        t = f.read_text(encoding='utf-8', errors='ignore')
        n_test = len(re.findall(r"\b(?:test|it)\s*\(", t))
        out.append((f.name, n_test, len(t.splitlines())))
    return out


def module_test_coverage():
    """¿Qué módulos .py son mencionados por alguna prueba?"""
    mods = {f.stem for f in ROOT.glob('*.py') if not f.name.startswith('test_')}
    tested = set()
    tests = list(ROOT.glob('test_*.py')) + list(ROOT.glob('test_*.mjs'))
    blob = ''
    for f in tests:
        blob += f.read_text(encoding='utf-8', errors='ignore')
    for m in mods:
        if re.search(rf'\b{re.escape(m)}\b', blob):
            tested.add(m)
    return sorted(tested), sorted(mods - tested)


# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    R = routes()
    print('=' * 72)
    print(f'RUTAS HTTP: {len(R)} totales')
    print('=' * 72)
    by = defaultdict(list)
    for r in R:
        by[route_domain(r['path'])].append(r)
    for name, _ in DOMAINS + [('otros', ())]:
        rs = by.get(name, [])
        if not rs:
            continue
        mut = sum(1 for r in rs if r['mutating'])
        noauth = sum(1 for r in rs if not r['session'] and not r['secret'])
        noauth_mut = sum(1 for r in rs if r['mutating'] and not r['session'] and not r['secret'])
        loc = sum(r['lines'] for r in rs)
        print(f'  {name:32} rutas={len(rs):4}  mutan={mut:3}  '
              f'sin_auth={noauth:3}  sin_auth_y_mutan={noauth_mut:3}  loc={loc}')

    print()
    print('=' * 72)
    print('PRUEBAS')
    print('=' * 72)
    ti = test_inventory()
    for nm, n, loc in ti:
        print(f'  {nm:46} {n:4} pruebas  {loc:5} líneas')
    print(f'  {"TOTAL":46} {sum(t[1] for t in ti):4} pruebas en {len(ti)} archivos')

    print()
    tested, untested = module_test_coverage()
    print(f'  módulos mencionados por pruebas ({len(tested)}): {", ".join(tested)}')
    print()
    print(f'  SIN mención en ninguna prueba ({len(untested)}): {", ".join(untested)}')

    print()
    print('=' * 72)
    print('SEÑALES DE TRABAJO INCOMPLETO')
    print('=' * 72)
    for k, (tot, per) in markers().items():
        if tot:
            det = '  '.join(f'{f}:{c}' for f, c in per.items())
            print(f'  {k:18} {tot:5}   {det}')

    empty, notimpl = stub_signals()
    print()
    print(f'  funciones vacías (solo pass/docstring): {len(empty)}'
          + (f' -> {", ".join(empty[:8])}' if empty else ''))
    print(f'  NotImplementedError: {len(notimpl)}'
          + (f' -> {", ".join(notimpl[:8])}' if notimpl else ''))

    print()
    print('=' * 72)
    print('BANDERAS BOOLEANAS DE NIVEL MÓDULO (aprobaciones de negocio / activación)')
    print('=' * 72)
    for nm, val, ln in business_gates():
        flag = '  <-- DESACTIVADO' if val is False else ''
        print(f'  L{ln:<6} {nm:46} = {val}{flag}')

    print()
    print('=' * 72)
    print('VARIABLES DE ENTORNO REFERENCIADAS (nº de puntos de lectura)')
    print('=' * 72)
    ev = env_dependencies()
    for k, c in ev.items():
        print(f'  {k:34} {c}')
    print(f'  TOTAL: {len(ev)} variables distintas')
