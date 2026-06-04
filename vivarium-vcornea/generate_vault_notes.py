"""Generate Obsidian vault notes for every GUI parameter (knob), from the schema.

Single source of truth = the schema. This projects each input parameter into a
vault-format note (frontmatter + details + GUI/implementation + conceptual hint +
governing equations + typed connections) and writes a sidecar map
`vcornea_kb_map.json` (schema_param -> note/id/value) for the GUI<->vault bridge.

Runs either way:
  * in the `vc` env it imports the real schema (VCorneaProcess.ports_schema());
  * otherwise it extracts the schema literals straight from the source via AST.

Usage:  python vivarium-vcornea/generate_vault_notes.py
"""
import ast
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "vivarium-vcornea/vivarium_vcornea/processes/vcornea_process.py"
OUT = ROOT / "Docs/vault/03-Parameters/GUI Knobs"
MAP = ROOT / "Docs/vault/vcornea_kb_map.json"


def _load(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

units = _load("units", ROOT / "vivarium-vcornea/vivarium_vcornea/utils/units.py")
eqs = _load("equations", ROOT / "vivarium-vcornea/vivarium_vcornea/utils/equations.py")
refs_db = _load("references", ROOT / "vivarium-vcornea/vivarium_vcornea/utils/references.py")


def get_inputs():
    """Real schema if importable, else AST-extracted literals from the source."""
    try:
        from vivarium_vcornea.processes.vcornea_process import VCorneaProcess
        return VCorneaProcess({}).ports_schema()["inputs"]
    except Exception:
        tree = ast.parse(SRC.read_text())
        inputs_node = None
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value == "inputs" and isinstance(v, ast.Dict):
                        inputs_node = v
                        break
            if inputs_node:
                break
        result = {}
        for k, v in zip(inputs_node.keys, inputs_node.values):
            if not (isinstance(k, ast.Constant) and isinstance(v, ast.Dict)):
                continue
            fields = {}
            for fk, fv in zip(v.keys, v.values):
                if not isinstance(fk, ast.Constant):
                    continue
                try:
                    fields[fk.value] = ast.literal_eval(fv)
                except Exception:
                    fields[fk.value] = "<expr>"  # lambda / computed
            result[k.value] = fields
        return result


DIM_SCALE = {
    "length": ["[[Spatial Scale Voxel to Micrometers]]"],
    "area": ["[[Area Scale Pixel to Square Micrometers]]"],
    "diffusion": ["[[Spatial Scale Voxel to Micrometers]]", "[[Temporal Scale MCS to Minutes]]"],
    "rate": ["[[Temporal Scale MCS to Minutes]]"],
    "time": ["[[Temporal Scale MCS to Minutes]]"],
}
SUBCAT_ENTITY = {
    "Stem Cells": "[[Limbal Epithelial Stem Cell (LESC)]]",
    "Basal Cells": "[[Basal Epithelial Cell]]",
    "Wing Cells": "[[Wing Cell]]",
    "Superficial Cells": "[[Superficial Cell]]",
}
# Knob -> curated concept note (hand-verified; links the schema-generated note into
# the existing concept graph without duplicating it).
KNOB_TO_CONCEPT = {
    "EGF_GlobalDecay": "EGF Global Decay Rate",
    "EGF_SUPERDiffCoef": "EGF Diffusion Coefficient in Superficial Cells",
    "EGF_STEM_HalfMaxValue": "Half-Max EGF for Stem Cells",
    "EGF_BASAL_HalfMaxValue": "Half-Max EGF for Basal Cells",
    "DensitySTEM_HalfMaxValue": "Half-Max Pressure for Contact Inhibition",
    "DensityBASAL_HalfMaxValue": "Half-Max Pressure for Contact Inhibition",
    "SLS_Concentration": "SLS Chemical Concentration",
    "InitSTEM_TargetVolume": "InitialTarget Cell Volume",
    "InitBASAL_TargetVolume": "InitialTarget Cell Volume",
    "InitWING_TargetVolume": "InitialTarget Cell Volume",
    "InitSUPER_TargetVolume": "InitialTarget Cell Volume",
}
SAFE = re.compile(r"[^A-Za-z0-9 _.()-]")


def disp_name(info, pname):
    return info.get("_display_name", pname)


def render(pname, info, name_lookup):
    dim = info.get("_dimension")
    du = info.get("_display_unit")
    default = info.get("_default")
    is_num = isinstance(default, (int, float)) and not isinstance(default, bool)
    unit = info.get("_unit", "")
    phys_range = info.get("_physiological_range")
    rec_range = info.get("_recommended_range")
    rng = phys_range or rec_range
    grounding = ("physical (measured / geometric)" if phys_range
                 else "arbitrary / proxy (CPM unit or abstraction)" if rec_range
                 else "n/a")

    fm = {
        "id": f"param:{pname.lower()}",
        "type": "PARAMETER",
        "subtype": "gui_knob",
        "schema_param": pname,
        "python_variable": pname,
        "value": default,
        "unit": unit,
        "dimension": dim or "",
        "aliases": [disp_name(info, pname), pname],
    }
    if is_num and dim:
        fm["display_value"] = round(units.to_display(default, dim, du), 4)
        fm["display_unit"] = units.display_unit_label(dim, du)
    fm_lines = ["---"]
    for k, v in fm.items():
        fm_lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    fm_lines.append("---")

    L = ["\n".join(fm_lines), ""]
    L.append(f"# ⚙️ {disp_name(info, pname)}")
    L.append("")
    L.append(f"> {info.get('_description', 'No description.')}")
    L.append("")

    # Parameter details
    L.append("## Parameter Details")
    L.append(f"**Schema parameter:** `{pname}`")
    if is_num and dim and abs(units.factor(dim, du) - 1.0) > 1e-12:
        dv = units.to_display(default, dim, du)
        L.append(f"**Simulation value:** `{default}` {units.sim_unit_label(dim)}")
        L.append(f"**Physical value:** `{dv:g}` {units.display_unit_label(dim, du)} "
                 f"*(display = sim × {units.factor(dim, du):g})*")
    else:
        L.append(f"**Value:** `{default}` {unit}")
    L.append(f"**Dimension:** `{dim or 'n/a'}`  ·  **Grounding:** {grounding}")
    if rng:
        if is_num and dim and abs(units.factor(dim, du) - 1.0) > 1e-12:
            dr = units.convert_range(rng, dim, du)
            label = "Physiological range" if phys_range else "Recommended range (exploratory)"
            L.append(f"**{label}:** {tuple(rng)} {units.sim_unit_label(dim)} = "
                     f"[{dr[0]:g}, {dr[1]:g}] {units.display_unit_label(dim, du)}")
        else:
            label = "Physiological range" if phys_range else "Recommended range (exploratory, not physiological)"
            L.append(f"**{label}:** {tuple(rng)} {unit}")
    ref = info.get("_reference_paper")
    if isinstance(ref, dict):
        L.append(f"**Source:** {ref.get('source', 'Vanin et al., 2025')}")
    L.append("")

    # GUI / implementation
    L.append("## GUI / Implementation")
    if is_num and dim and abs(units.factor(dim, du) - 1.0) > 1e-12:
        L.append(f"- Displayed in GUI as **{units.to_display(default, dim, du):g} "
                 f"{units.display_unit_label(dim, du)}** (façade converts via `_dimension`).")
    L.append(f"- Written to `Parameters.py` as `{pname}={default!r}` (sim-canonical).")
    if info.get("_conditional_display") == "<expr>" or "_conditional_display" in info:
        L.append("- Conditionally shown (depends on injury/mode flags).")
    if info.get("_model_context"):
        L.append(f"- Model context: {info['_model_context']}")
    if info.get("_implementation_pattern"):
        L.append(f"- Implementation: {info['_implementation_pattern']}")
    L.append("")

    if info.get("_conceptual_hint"):
        L.append("## Conceptualization Hints")
        L.append(info["_conceptual_hint"])
        L.append("")

    # Governing equations
    eqmap = eqs.equations_for_param(pname)
    if eqmap:
        L.append("## Governing Equations")
        for eid, e in eqmap.items():
            L.append(f"**{e['name']}** · {e.get('paper_ref', '')}")
            L.append("$$")
            L.append(e["latex"])
            L.append("$$")
            if e.get("description"):
                L.append(f"*{e['description']}*")
            erefs = eqs.refs_for(eid) if hasattr(eqs, "refs_for") else []
            if erefs:
                parts = []
                for n in erefs:
                    r = refs_db.REFERENCES.get(n, {})
                    lbl = refs_db.short(n)
                    parts.append(f"[{lbl}](https://doi.org/{r['doi']})" if r.get("doi") else lbl)
                L.append(f"Refs: {', '.join(parts)}")
            L.append("")

    # Connections
    conns = []
    if pname in KNOB_TO_CONCEPT:
        conns.append(f"- \U0001f9e0 Concept → [[{KNOB_TO_CONCEPT[pname]}]]")
    for rp in info.get("_related_parameters", []) or []:
        if rp == "<expr>":
            continue
        dn = name_lookup.get(rp)
        conns.append(f"- \U0001f517 Related → [[{dn} (GUI knob)]]" if dn else f"- \U0001f517 Related → `{rp}`")
    for s in DIM_SCALE.get(dim, []):
        conns.append(f"- \U0001f4cf Unit conversion → {s}")
    ent = SUBCAT_ENTITY.get(info.get("_subcategory", ""))
    if ent:
        conns.append(f"- \U0001f9ec Applies to → {ent}")
    for eid, e in eqmap.items():
        if e.get("vault_id"):
            conns.append(f"- \U0001f4d0 Equation → see registry `{eid}`")
    if conns:
        L.append("## Connections")
        L.extend(conns)
        L.append("")

    if isinstance(ref, dict):
        L.append("## Paper References")
        L.append(f"- {ref.get('source', 'Vanin et al., 2025')}")
        if ref.get("detail"):
            L.append(f"- {ref['detail']}")
        L.append("")

    lit = info.get("_literature")
    if lit:
        L.append("## Literature")
        for item in lit:
            if isinstance(item, int):
                r = refs_db.REFERENCES.get(item, {})
                line = r.get("cite", f"[ref {item}]")
                if r.get("doi"):
                    line += f" · [doi:{r['doi']}](https://doi.org/{r['doi']})"
                elif r.get("pmid"):
                    line += f" · PMID:{r['pmid']}"
                L.append(f"- {line}")
            elif isinstance(item, dict):
                line = item.get("cite", "")
                if item.get("doi"):
                    line += f" · [doi:{item['doi']}](https://doi.org/{item['doi']})"
                L.append(f"- {line}")
            else:
                L.append(f"- {item}")
        L.append("")

    return "\n".join(L)


def main():
    inputs = get_inputs()
    # only real, GUI-facing knobs: have a _default and are not wrapper-scope outputs
    knobs = {k: v for k, v in inputs.items()
             if "_default" in v and v.get("_scope") != "wrapper"}
    name_lookup = {k: disp_name(v, k) for k, v in knobs.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    kbmap = {}
    for pname, info in knobs.items():
        note = render(pname, info, name_lookup)
        fname = SAFE.sub("", f"{disp_name(info, pname)} (GUI knob)") + ".md"
        (OUT / fname).write_text(note, encoding="utf-8")
        kbmap[pname] = {
            "note": f"03-Parameters/GUI Knobs/{fname}",
            "id": f"param:{pname.lower()}",
            "value": info.get("_default"),
            "dimension": info.get("_dimension", ""),
        }
    MAP.write_text(json.dumps(kbmap, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"generated {len(kbmap)} knob notes -> {OUT}")
    print(f"sidecar map -> {MAP}")


if __name__ == "__main__":
    main()
