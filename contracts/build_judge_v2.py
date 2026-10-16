"""Builds the two v2 judge contracts: contracts/judge_mail.py (late) and
contracts/judge_subjective.py (not_as_described and not_delivered), each from its template plus the
common part (contracts/judge_common.py).

The contracts carry short copies of the measured logic, without dead or duplicated code, and
tests/judge_v2_stub_run.py compares them with the modules in arbiter/. Prompt texts and tables are
not copied by hand: this builder reads them from the measured modules and inserts them as constants
in place of # <<CONST>>, so they cannot drift. Then everything goes through ast.unparse (comments
and docstrings go away; literals stay the same) and indentation becomes one space per level, to
stay under the deploy gas cap. The leading comment lines (Depends and license) are kept.

Usage: py -3.12 contracts/build_judge_v2.py
"""
import ast
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arbiter"))
import mail_llm_v2  # noqa: E402
import mail_llm_v3  # noqa: E402
import not_delivered  # noqa: E402
import subjective  # noqa: E402
import subjective_v3  # noqa: E402

COMMON = ROOT / "contracts" / "judge_common.py"


def mail_consts():
    h = mail_llm_v3.HEADER
    assert mail_llm_v3.TYPE_RULES.startswith(h) and mail_llm_v3.DATE_RULES.startswith(h)
    return {"H": h, "QT": mail_llm_v3.TYPE_RULES[len(h):], "QD": mail_llm_v3.DATE_RULES[len(h):],
            "TYPES": mail_llm_v3.TYPES, "DATE_TYPES": mail_llm_v3.DATE_TYPES, "MONTHS": mail_llm_v2.MONTHS,
            "WEEKDAYS": mail_llm_v2.WEEKDAYS}, (ROOT / "arbiter" / "mail_llm_v3.py", ROOT / "arbiter" / "mail_llm_v2.py",
                                                ROOT / "arbiter" / "mail_llm.py")


class Expr(str):
    """A constant written as an expression (slices of constants already defined)."""


def compose(target, bases, min_len=40):
    """target as a sum of slices of bases (name -> text already in the contract) and literals, so no
    text is repeated. Checked to give exactly target."""
    if not target:
        return []
    best = None
    for name, text in bases.items():
        m = difflib.SequenceMatcher(None, text, target, autojunk=False).find_longest_match(0, len(text), 0, len(target))
        if m.size >= min_len and (best is None or m.size > best[1].size):
            best = (name, m)
    if best is None:
        return [repr(target)]
    name, m = best
    return (compose(target[:m.b], bases, min_len) + ["%s[%d:%d]" % (name, m.a, m.a + m.size)]
            + compose(target[m.b + m.size:], bases, min_len))


def subjective_consts():
    h = subjective_v3.HEADER
    assert subjective_v3.Q1_RULES.startswith(h) and subjective_v3.Q2_RULES.startswith(h)
    assert not_delivered.RULES.startswith(not_delivered.HEADER)
    values = {"H": h, "T1": subjective_v3.Q1_RULES[len(h):], "T2": subjective_v3.Q2_RULES[len(h):],
              "KINDS": subjective.PROOF_KINDS}
    bases = {k: values[k] for k in ("H", "T1", "T2")}
    for name, text in (("NH", not_delivered.HEADER), ("NT", not_delivered.RULES[len(not_delivered.HEADER):])):
        expr = " + ".join(compose(text, bases))
        assert eval(expr, {}, dict(bases)) == text
        values[name] = Expr(expr)
    return values, (ROOT / "arbiter" / "subjective_v3.py", ROOT / "arbiter" / "subjective.py",
                    ROOT / "arbiter" / "not_delivered.py")


CONTRACTS = {"judge_mail": (ROOT / "contracts" / "judge_mail_template.py", mail_consts),
             "judge_subjective": (ROOT / "contracts" / "judge_subjective_template.py", subjective_consts)}


def strip_docstrings(tree):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            n.body = n.body[1:] or [ast.Pass()]
    return tree


def short_locals(tree):
    """Short local names in every module-level function (nested ones included). Only renames
    variables and parameters (Name, arg and except ... as nodes): never strings, dictionary keys,
    attributes, global names or the contract's methods (its ABI)."""
    import builtins
    import keyword
    glob = set(dir(builtins)) | set(keyword.kwlist)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            glob |= {a.asname or a.name.split(".")[0] for a in node.names}
        if isinstance(node, ast.ImportFrom):
            glob |= {"gl", "Address", "TreeMap", "u256", "DynArray", "StorageType"}  # from genlayer import *
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        bound = []
        for n in ast.walk(node):
            names = []
            if isinstance(n, ast.arg):
                names = [n.arg]
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names = [n.id]
            elif isinstance(n, ast.ExceptHandler) and n.name:
                names = [n.name]
            elif isinstance(n, ast.FunctionDef) and n is not node:
                names = [n.name]
            for x in names:
                if x not in bound:
                    bound.append(x)
        module_level = {b.name for b in tree.body if isinstance(b, (ast.FunctionDef, ast.ClassDef))} | {
            t.id for b in tree.body if isinstance(b, ast.Assign) for t in ast.walk(b) if isinstance(t, ast.Name)}
        free = (chr(c1) + chr(c2) if c2 else chr(c1) for c1 in range(97, 123) for c2 in [0] + list(range(97, 123)))
        mapping = {}
        for x in bound:
            if x in module_level or len(x) == 1:
                continue  # never shadow a global name; a one-letter name is already short
            new = next(free)
            while new in glob or new in module_level or new in bound or new in mapping.values():
                new = next(free)
            mapping[x] = new
        for n in ast.walk(node):
            if isinstance(n, ast.arg) and n.arg in mapping:
                n.arg = mapping[n.arg]
            elif isinstance(n, ast.Name) and n.id in mapping:
                n.id = mapping[n.id]
            elif isinstance(n, ast.ExceptHandler) and n.name in mapping:
                n.name = mapping[n.name]
            elif isinstance(n, ast.FunctionDef) and n is not node and n.name in mapping:
                n.name = mapping[n.name]
    return tree


def one_space(text):
    out = []
    for line in text.split("\n"):
        lead = len(line) - len(line.lstrip(" "))
        assert lead % 4 == 0, line
        out.append(" " * (lead // 4) + line[lead:])
    return "\n".join(out)


def build(name):
    template_path, consts = CONTRACTS[name]
    values, sources = consts()
    template = template_path.read_text(encoding="ascii")
    assert template.count("# <<CONST>>") == 1 and template.count("# <<COMMON>>") == 1
    # The loop over the submissions comes from each template (the mail judge lists what it ignored;
    # the subjective one, at the edge of the deploy gas cap, does not), into # <<EACH>> in common.
    a, b = template.index("# <<EACH-BEGIN>>\n"), template.index("# <<EACH-END>>\n")
    each = template[a + len("# <<EACH-BEGIN>>\n"):b]
    template = template[:a] + template[b + len("# <<EACH-END>>\n"):]
    common = COMMON.read_text(encoding="ascii")
    marker = next(line for line in common.split("\n") if line.strip().startswith("# <<EACH>>"))
    common = common.replace(marker + "\n", each)
    const = "\n".join("%s = %s" % (k, v if isinstance(v, Expr) else repr(v)) for k, v in values.items())
    joined = template.replace("# <<CONST>>", const).replace("# <<COMMON>>", common)
    lines = joined.split("\n")
    head = 0
    while lines[head].startswith("#"):
        head += 1
    # Provenance goes to contracts/judge_build.json, not into the contract (every byte costs deploy gas).
    prov = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (template_path, COMMON) + sources}
    body = ast.unparse(short_locals(strip_docstrings(ast.parse("\n".join(lines[head:])))))
    body = one_space(body.encode("ascii", "backslashreplace").decode())
    # The runner reads the leading comment block as the Depends JSON: line 1 has to stand alone,
    # followed by a blank line (Bradbury rejected the first deploy with "trailing characters at line 1
    # column 84" when the license comment followed it directly).
    assert lines[0].startswith('# { "Depends":') and lines[0].rstrip().endswith("}")
    built = lines[0] + "\n\n" + "\n".join(lines[1:head]) + "\n\n" + body + "\n"
    assert built.split("\n")[1] == ""
    compile(built, name, "exec")
    built.encode("ascii")
    out = ROOT / "contracts" / (name + ".py")
    out.write_text(built, encoding="ascii", newline="\n")
    return out, built, prov


if __name__ == "__main__":
    manifest = {}
    for contract in CONTRACTS:
        path, text, prov = build(contract)
        sha = hashlib.sha256(text.encode()).hexdigest()
        manifest[path.relative_to(ROOT).as_posix()] = {"bytes": len(text.encode()), "sha256": sha, "built_from": prov}
        print(path.relative_to(ROOT).as_posix(), len(text.encode()), "bytes, sha256", sha)
    (ROOT / "contracts" / "judge_build.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                                         encoding="ascii", newline="\n")
