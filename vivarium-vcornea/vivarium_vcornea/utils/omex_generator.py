"""
OMEX Archive Generator for vCornea Simulations

Generates standards-compliant SED-ML L1V4 documents and COMBINE/OMEX archives
for CompuCell3D simulation runs.

This module uses pure Python (no compiled dependencies):
- xml.etree.ElementTree for XML generation
- zipfile for OMEX archive packaging
- json for metadata handling

Standards References:
- SED-ML L1V4: http://sed-ml.org/sed-ml/level1/version4
  (the "L1V5" spec document reuses the L1V4 XML schema/namespace; we emit version="4")
- COMBINE Archive: http://co.mbine.org/specifications/omex.version-1
- KiSAO: http://co.mbine.org/standards/kisao

Author: vCornea Team
Date: 2026
"""

import xml.etree.ElementTree as ET
import zipfile
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Union

# Canonical unit conversions (single source of truth: units.py). SimTime/InjuryTime
# are in DAYS; CC3D's native time unit is MCS. Import robustly so the module works
# both as a package member (vivarium_vcornea.utils.omex_generator) and when imported
# by filename (test harness / tools that put utils/ on sys.path).
try:
    from . import units
except ImportError:  # imported as a top-level module
    import units


# =============================================================================
# CONSTANTS - Standards URIs and Identifiers
# =============================================================================

# SED-ML Namespaces
# Per SED-ML L1V5 spec (sec 2.2.1.1/2.2.1.3): L1V5 reuses the L1V4 schema namespace
# and version="4". The "Level 1 Version 5" naming refers to the spec document;
# the XML schema itself was not bumped.
SEDML_NAMESPACE = "http://sed-ml.org/sed-ml/level1/version4"
SEDML_VERSION_ATTR = "4"
NUML_NAMESPACE = "http://www.numl.org/numl/level1/version1"
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC_NAMESPACE = "http://purl.org/dc/terms/"

# OMEX Manifest Namespace
OMEX_MANIFEST_NAMESPACE = "http://identifiers.org/combine.specifications/omex-manifest"

# OMEX Metadata (COMBINE spec) format URI — for the provenance metadata.rdf entry
OMEX_METADATA_FORMAT = "http://identifiers.org/combine.specifications/omex-metadata"

# Algorithm Identifier (KiSAO)
# KISAO:0000241 = Metropolis Monte Carlo algorithm (used for CPM/GGH models)
KISAO_ALGORITHM_ID = "KISAO:0000241"

# Symbol URN for the simulation independent variable (time)
SEDML_SYMBOL_TIME = "urn:sedml:symbol:time"

# Model Language URN (CompuCell3D - community-defined; type is URN per L1V5 sec 2.2.4)
MODEL_LANGUAGE_URI = "urn:sedml:language:compucell3d"

# Format URIs for OMEX manifest
FORMAT_URIS = {
    # COMBINE-registered formats
    # L1V5 reuses the L1V4 schema; the COMBINE format URI tracks the schema, not
    # the spec document version. BioSimulators/BioSimulations expect version-4.
    '.sedml': 'http://identifiers.org/combine.specifications/sed-ml.level-1.version-4',
    '.omex': 'http://identifiers.org/combine.specifications/omex',

    # Standard media types (via purl.org)
    '.csv': 'http://purl.org/NET/mediatypes/text/csv',
    '.json': 'http://purl.org/NET/mediatypes/application/json',
    '.txt': 'http://purl.org/NET/mediatypes/text/plain',
    '.log': 'http://purl.org/NET/mediatypes/text/plain',
    '.xml': 'http://purl.org/NET/mediatypes/application/xml',
    '.png': 'http://purl.org/NET/mediatypes/image/png',
    '.jpg': 'http://purl.org/NET/mediatypes/image/jpeg',
    '.jpeg': 'http://purl.org/NET/mediatypes/image/jpeg',

    # Custom/unregistered media types (allowed by OMEX spec)
    '.parquet': 'http://purl.org/NET/mediatypes/application/x-parquet',
    '.cc3d': 'http://purl.org/NET/mediatypes/application/x.compucell3d',
    '.py': 'http://purl.org/NET/mediatypes/text/x-python',
    '.piff': 'http://purl.org/NET/mediatypes/application/x.compucell3d-piff',
    '.bnd': 'http://purl.org/NET/mediatypes/text/x-maboss-bnd',
    '.cfg': 'http://purl.org/NET/mediatypes/text/x-maboss-cfg',
}

# Default format for unknown extensions
DEFAULT_FORMAT_URI = 'http://purl.org/NET/mediatypes/application/octet-stream'


# =============================================================================
# CSV OUTPUT SCHEMAS - Column definitions for known output files (Phase 2)
# =============================================================================

# Maps output file patterns to their column definitions
# Each column has: name, description, data_type, unit (optional)
CSV_OUTPUT_SCHEMAS = {
    'cell_count': {
        'description': 'Cell population counts by layer over time',
        'columns': [
            {'id': 'Superficial', 'name': 'Superficial Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Wing', 'name': 'Wing Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Basal', 'name': 'Basal Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Stem', 'name': 'Stem Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
    'cell_states': {
        'description': 'Cell fate states (survival, apoptosis, necrosis) by layer over time',
        'columns': [
            {'id': 'Survival', 'name': 'Surviving Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Apoptosis', 'name': 'Apoptotic Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Necrosis', 'name': 'Necrotic Cells', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Survival_Fraction', 'name': 'Survival Fraction', 'type': 'float', 'unit': 'dimensionless'},
            {'id': 'Apoptosis_Fraction', 'name': 'Apoptosis Fraction', 'type': 'float', 'unit': 'dimensionless'},
            {'id': 'Necrosis_Fraction', 'name': 'Necrosis Fraction', 'type': 'float', 'unit': 'dimensionless'},
            {'id': 'STEM_Survival', 'name': 'Stem Survival', 'type': 'integer', 'unit': 'cells'},
            {'id': 'STEM_Apoptosis', 'name': 'Stem Apoptosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'STEM_Necrosis', 'name': 'Stem Necrosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'BASAL_Survival', 'name': 'Basal Survival', 'type': 'integer', 'unit': 'cells'},
            {'id': 'BASAL_Apoptosis', 'name': 'Basal Apoptosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'BASAL_Necrosis', 'name': 'Basal Necrosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'WING_Survival', 'name': 'Wing Survival', 'type': 'integer', 'unit': 'cells'},
            {'id': 'WING_Apoptosis', 'name': 'Wing Apoptosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'WING_Necrosis', 'name': 'Wing Necrosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'SUPER_Survival', 'name': 'Superficial Survival', 'type': 'integer', 'unit': 'cells'},
            {'id': 'SUPER_Apoptosis', 'name': 'Superficial Apoptosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'SUPER_Necrosis', 'name': 'Superficial Necrosis', 'type': 'integer', 'unit': 'cells'},
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
    'maboss_states': {
        'description': 'MaBoSS signaling network states over time',
        # Time-only stub (see NOTE below); real value columns unverified.
        'columns': [
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
    'injury_edge': {
        'description': 'Spatial tracking of injury edge cell positions over time',
        'columns': [
            {'id': 'TNF_Active_Cells_Pos', 'name': 'TNF Active Cell Positions', 'type': 'array', 'unit': 'pixels'},
            {'id': 'Cycle_Arrest_Cells_Pos', 'name': 'Cycle Arrest Cell Positions', 'type': 'array', 'unit': 'pixels'},
            {'id': 'Apop_Cells_Pos', 'name': 'Apoptotic Cell Positions', 'type': 'array', 'unit': 'pixels'},
            {'id': 'Necro_Cells_Pos', 'name': 'Necrotic Cell Positions', 'type': 'array', 'unit': 'pixels'},
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
    'memb_disruption': {
        'description': 'Membrane disruption metrics over time',
        # Time-only stub (see NOTE below); real value columns unverified.
        'columns': [
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
    'surfactant': {
        'description': 'Surfactant concentration/effects over time',
        'columns': [
            {'id': 'Total Amount', 'name': 'Total Surfactant Amount', 'type': 'float', 'unit': 'a.u.'},
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
    'thickness': {
        'description': 'Epithelial thickness profile (Height per spatial Bin) over time',
        # Long-format parquet: each (Time, Bin) row carries one Height sample.
        'columns': [
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
            {'id': 'Bin', 'name': 'Spatial Bin (along cornea)', 'type': 'integer', 'unit': 'dimensionless'},
            {'id': 'Height', 'name': 'Epithelial Thickness (Height)', 'type': 'float', 'unit': 'voxel'},
        ]
    },
    # NOTE: the schemas below are Time-only stubs. The real output files for these
    # may carry additional value columns, but no verified example files were
    # available when these were written; columns are intentionally not invented.
    # Add value columns here once a real output file confirms their headers.
    'injury_tracking': {
        'description': 'Overall injury progression tracking',
        'columns': [
            {'id': 'Time', 'name': 'Simulation Time', 'type': 'float', 'unit': 'MCS'},
        ]
    },
}


def _safe_sid(raw: str) -> str:
    """
    Coerce an arbitrary string into a valid SED-ML SId.

    SId grammar (L1V5 sec 2.1.1.2): ( letter | '_' ) ( letter | digit | '_' )*
    """
    cleaned = []
    for ch in raw:
        if ch.isalnum() or ch == '_':
            cleaned.append(ch)
        else:
            cleaned.append('_')
    out = ''.join(cleaned)
    if not out or not (out[0].isalpha() or out[0] == '_'):
        out = '_' + out
    return out


def _match_output_schema(filename: str) -> Optional[Dict[str, Any]]:
    """
    Match a filename to its CSV schema definition.

    Args:
        filename: Name of the output file (e.g., 'cell_count_500.csv')

    Returns:
        Schema dict if matched, None otherwise
    """
    name_lower = filename.lower()
    for pattern, schema in CSV_OUTPUT_SCHEMAS.items():
        if pattern in name_lower:
            return schema
    return None


# =============================================================================
# SED-ML DOCUMENT GENERATION
# =============================================================================

def generate_sedml_document(
    run_metadata: Dict[str, Any],
    sim_params: Dict[str, Any],
    output_files: List[str],
    model_source: str = "model/vcornea.cc3d",
    num_replicates: int = 1,
    include_data_descriptions: bool = True
) -> str:
    """
    Generate a SED-ML Level 1 Version 5 document describing the simulation.

    The document references the existing run_metadata.json for detailed
    parameter provenance, following the Phase 1 approach of "valid SED-ML
    with pointers to existing JSON/CSV provenance".

    Phase 2 additions:
    - repeatedTask element when num_replicates > 1
    - listOfDataDescriptions for CSV output files

    Args:
        run_metadata: Dictionary from run_metadata.json
        sim_params: Simulation parameters used
        output_files: List of output file names generated
        model_source: Relative path to model file within archive
        num_replicates: Number of replicates (adds repeatedTask if > 1)
        include_data_descriptions: Whether to add dataDescription for CSV files

    Returns:
        XML string of the SED-ML document
    """
    # Register namespaces to get clean output
    ET.register_namespace('', SEDML_NAMESPACE)
    ET.register_namespace('html', XHTML_NAMESPACE)
    ET.register_namespace('rdf', RDF_NAMESPACE)
    ET.register_namespace('dc', DC_NAMESPACE)
    ET.register_namespace('math', MATHML_NAMESPACE)
    ET.register_namespace('numl', NUML_NAMESPACE)

    # Create root element with required attributes
    root = ET.Element('sedML')
    root.set('xmlns', SEDML_NAMESPACE)
    root.set('level', '1')
    root.set('version', SEDML_VERSION_ATTR)

    # Extract key metadata
    run_name = run_metadata.get('run_name', 'unnamed_run')
    created_at = run_metadata.get('created_at', datetime.now().isoformat())
    params_changed = run_metadata.get('parameters_changed', 0)
    # SimTime is specified in DAYS. CC3D's native time unit is MCS, so convert via
    # the canonical factors in units.py. (Previously the raw day value was emitted
    # and mislabelled as "MCS" — a factor-of-MCS_PER_DAY error in the time course.)
    sim_time_days = sim_params.get('SimTime', 500)
    sim_time_mcs = int(round(sim_time_days * units.MCS_PER_DAY))
    sim_time_hours = sim_time_mcs / units.MCS_PER_HOUR
    has_injury = sim_params.get('IsInjury', False)
    injury_type = run_metadata.get('simulation_config', {}).get('injury_type', 'unknown')

    # Per-run scan annotation: this archive holds the data for ONE point of a scan.
    # We document which point (and the full scan space) WITHOUT emitting a scan
    # repeatedTask here — that would over-claim, since only one point's data is
    # present. The executable scan repeatedTask lives in the experiment-level archive.
    scan_spec = run_metadata.get('parameter_scan')
    scan_point = run_metadata.get('scan_point')
    combo_index = run_metadata.get('combination_index')
    total_combos = run_metadata.get('total_combinations')

    # Add document-level notes
    notes = ET.SubElement(root, 'notes')
    body = ET.SubElement(notes, '{%s}body' % XHTML_NAMESPACE)

    h2 = ET.SubElement(body, '{%s}h2' % XHTML_NAMESPACE)
    h2.text = f"CompuCell3D Simulation: {run_name}"

    # Add informative paragraphs
    info_lines = [
        f"Created: {created_at}",
        f"Parameters changed from defaults: {params_changed}",
        f"Simulation time: {sim_time_days} days "
        f"(= {sim_time_mcs} MCS = {sim_time_hours:g} hours)",
        f"Injury simulation: {'Yes' if has_injury else 'No'}" + (f" ({injury_type})" if has_injury else ""),
        "",
        "This SED-ML file documents a CompuCell3D (CC3D) simulation executed via the "
        "vCornea CellFate schema-driven GUI (Vivarium wrapper).",
        "",
        "IMPORTANT: Authoritative parameter provenance is stored in run_metadata.json. "
        "This SED-ML file provides standards-compliant documentation but references "
        "the JSON file for complete parameter details.",
        "",
        "Time values in this document are CC3D Monte Carlo Steps (MCS), the model's "
        "native time unit. Conversions (from units.py): "
        f"1 day = {int(units.MCS_PER_DAY)} MCS, 1 hour = {int(units.MCS_PER_HOUR)} MCS, "
        f"1 MCS = {units.MINUTES_PER_MCS:g} minutes. The SimTime parameter is given in days."
    ]

    if scan_spec:
        scan_dims = "; ".join(f"{p} ∈ {list(v)}" for p, v in scan_spec.items())
        point_txt = (", ".join(f"{p}={v}" for p, v in scan_point.items())
                     if scan_point else "see key_parameters")
        pos = (f" (point {combo_index} of {total_combos})"
               if combo_index and total_combos else "")
        info_lines += [
            "",
            "PARAMETER SCAN: this archive contains the data for ONE point of a "
            f"multi-point scan{pos}. This run's swept values: {point_txt}.",
            f"Full scan space: {scan_dims}. The executable scan description "
            "(a repeatedTask over these ranges) is in the experiment-level scan "
            "archive at the batch root; this per-run archive deliberately does not "
            "restate it, since it holds only this point's results.",
        ]

    for line in info_lines:
        p = ET.SubElement(body, '{%s}p' % XHTML_NAMESPACE)
        p.text = line

    # List of Models
    list_of_models = ET.SubElement(root, 'listOfModels')
    model = ET.SubElement(list_of_models, 'model')
    model.set('id', 'model_cc3d')
    model.set('name', 'vCornea CellFate CC3D Model')
    model.set('source', model_source)
    model.set('language', MODEL_LANGUAGE_URI)

    # Model notes
    model_notes = ET.SubElement(model, 'notes')
    model_body = ET.SubElement(model_notes, '{%s}body' % XHTML_NAMESPACE)
    model_p = ET.SubElement(model_body, '{%s}p' % XHTML_NAMESPACE)
    model_p.text = ("Model source is the packaged CC3D project. "
                    "See run_metadata.json for the exact parameter values applied.")

    # Model annotation with RDF link to metadata
    annotation = ET.SubElement(model, 'annotation')
    rdf = ET.SubElement(annotation, '{%s}RDF' % RDF_NAMESPACE)
    desc = ET.SubElement(rdf, '{%s}Description' % RDF_NAMESPACE)
    desc.set('{%s}about' % RDF_NAMESPACE, '#model_cc3d')
    relation = ET.SubElement(desc, '{%s}relation' % DC_NAMESPACE)
    relation.set('{%s}resource' % RDF_NAMESPACE, 'run_metadata.json')

    # List of Simulations
    list_of_sims = ET.SubElement(root, 'listOfSimulations')
    sim = ET.SubElement(list_of_sims, 'uniformTimeCourse')
    sim.set('id', 'sim_mcs')
    sim.set('initialTime', '0')
    sim.set('outputStartTime', '0')
    sim.set('outputEndTime', str(sim_time_mcs))
    sim.set('numberOfSteps', str(sim_time_mcs))

    # Algorithm (KiSAO term for Metropolis Monte Carlo)
    algorithm = ET.SubElement(sim, 'algorithm')
    algorithm.set('kisaoID', KISAO_ALGORITHM_ID)

    # List of Tasks
    list_of_tasks = ET.SubElement(root, 'listOfTasks')
    task = ET.SubElement(list_of_tasks, 'task')
    task.set('id', 'task_run')
    task.set('modelReference', 'model_cc3d')
    task.set('simulationReference', 'sim_mcs')

    # Phase 2: Add repeatedTask if multiple replicates
    if num_replicates > 1:
        repeated_task = ET.SubElement(list_of_tasks, 'repeatedTask')
        repeated_task.set('id', 'repeated_task')
        repeated_task.set('resetModel', 'true')
        repeated_task.set('range', 'replicate_range')

        # Add notes explaining the replicates
        rep_notes = ET.SubElement(repeated_task, 'notes')
        rep_body = ET.SubElement(rep_notes, '{%s}body' % XHTML_NAMESPACE)
        rep_p = ET.SubElement(rep_body, '{%s}p' % XHTML_NAMESPACE)
        rep_p.text = (f"This experiment was run {num_replicates} times with identical parameters "
                      "but different random seeds. Each replicate produces independent stochastic outcomes.")

        # Define the range (list of replicates)
        list_of_ranges = ET.SubElement(repeated_task, 'listOfRanges')
        uniform_range = ET.SubElement(list_of_ranges, 'uniformRange')
        uniform_range.set('id', 'replicate_range')
        uniform_range.set('start', '1')
        uniform_range.set('end', str(num_replicates))
        uniform_range.set('numberOfSteps', str(num_replicates - 1))
        uniform_range.set('type', 'linear')

        # Reference the base task
        list_of_subtasks = ET.SubElement(repeated_task, 'listOfSubTasks')
        subtask = ET.SubElement(list_of_subtasks, 'subTask')
        subtask.set('task', 'task_run')
        subtask.set('order', '1')

    # Phase 2: Add listOfDataDescriptions for CSV outputs.
    # Spec sec 2.2.2: when format != NuML, dimensionDescription is REQUIRED.
    # Spec sec 2.2.3.3: slice/@reference must be a NuMLSIdRef pointing at an
    # index declared in the dimensionDescription, and slice/@value is the
    # specific value within that dimension. We model each CSV as
    # rows (rowIdx) × columns (columnIds) → atomic double values.
    #
    # data_source_index records (csv_filename, column_id) -> dataSource id, so
    # listOfDataGenerators (built next) can target these via "#dataSourceId".
    # Index both CSV and parquet outputs (parquet was previously excluded, leaving
    # the thickness profile invisible to the SED-ML). biosimulators-utils does not
    # deep-validate dataDescriptions, so a parquet source is structurally safe.
    data_source_index: List[Dict[str, str]] = []
    data_files = [f for f in output_files if f.endswith(('.csv', '.parquet'))]
    if include_data_descriptions and data_files:
        list_of_data_desc = ET.SubElement(root, 'listOfDataDescriptions')

        for csv_file in data_files:
            schema = _match_output_schema(csv_file)
            if not schema:
                continue

            dd_id_stem = csv_file.replace('.', '_').replace('-', '_')
            data_desc = ET.SubElement(list_of_data_desc, 'dataDescription')
            data_desc.set('id', f"data_{dd_id_stem}")
            data_desc.set('name', schema['description'])
            data_desc.set('source', csv_file)
            if csv_file.endswith('.parquet'):
                # No registered SED-ML format URN for parquet; use the OMEX media type.
                data_desc.set('format', FORMAT_URIS['.parquet'])
            else:
                data_desc.set('format', 'urn:sedml:format:csv')

            # Human-readable column listing in notes
            dd_notes = ET.SubElement(data_desc, 'notes')
            dd_body = ET.SubElement(dd_notes, '{%s}body' % XHTML_NAMESPACE)
            dd_p = ET.SubElement(dd_body, '{%s}p' % XHTML_NAMESPACE)
            dd_p.text = f"Columns: {', '.join(c['id'] for c in schema['columns'])}"

            # NuML dimensionDescription: rows × columnIds → double
            dim_desc = ET.SubElement(data_desc, 'dimensionDescription')
            outer = ET.SubElement(dim_desc, '{%s}compositeDescription' % NUML_NAMESPACE)
            outer.set('indexType', 'integer')
            outer.set('id', 'rowIdx')
            outer.set('name', 'Row')
            inner = ET.SubElement(outer, '{%s}compositeDescription' % NUML_NAMESPACE)
            inner.set('indexType', 'string')
            inner.set('id', 'columnIds')
            inner.set('name', 'Column')
            atomic = ET.SubElement(inner, '{%s}atomicDescription' % NUML_NAMESPACE)
            atomic.set('valueType', 'double')
            atomic.set('id', 'value')
            atomic.set('name', 'Value')

            # One dataSource per declared column, slicing on columnIds
            list_of_dsrc = ET.SubElement(data_desc, 'listOfDataSources')
            for col in schema['columns']:
                ds_id = _safe_sid(f"ds_{dd_id_stem}_{col['id']}")
                data_source = ET.SubElement(list_of_dsrc, 'dataSource')
                data_source.set('id', ds_id)
                data_source.set('name', col['name'])
                list_of_slices = ET.SubElement(data_source, 'listOfSlices')
                slice_elem = ET.SubElement(list_of_slices, 'slice')
                slice_elem.set('reference', 'columnIds')
                slice_elem.set('value', col['id'])

                data_source_index.append({
                    'csv': csv_file,
                    'column_id': col['id'],
                    'column_name': col['name'],
                    'data_source_id': ds_id,
                })

    # listOfDataGenerators: REQUIRED transit point between data and outputs.
    # Spec sec 2.2.10: "all variable and parameter values used in the Output
    # class need to be defined as a DataGenerator beforehand". A DataGenerator
    # holds a <math> over <variable> elements; each variable references either
    # a task observable (taskReference + symbol/target) or a DataSource in a
    # dataDescription (target="#dataSourceId").
    list_of_dgs = ET.SubElement(root, 'listOfDataGenerators')

    # Always emit a time data generator so even a no-CSV archive has one valid
    # output series. Uses the standard sed-ml time symbol on the base task.
    dg_time = ET.SubElement(list_of_dgs, 'dataGenerator')
    dg_time.set('id', 'dg_time')
    dg_time.set('name', 'Simulation Time (MCS)')
    lov = ET.SubElement(dg_time, 'listOfVariables')
    var_t = ET.SubElement(lov, 'variable')
    var_t.set('id', 'var_time')
    # Reference the repeatedTask when replicates exist so it contributes to an output
    # (avoids the "task does not contribute to outputs" dead-element warning).
    var_t.set('taskReference', 'repeated_task' if num_replicates > 1 else 'task_run')
    var_t.set('symbol', SEDML_SYMBOL_TIME)
    math_t = ET.SubElement(dg_time, '{%s}math' % MATHML_NAMESPACE)
    ci_t = ET.SubElement(math_t, '{%s}ci' % MATHML_NAMESPACE)
    ci_t.text = 'var_time'

    # One DataGenerator per CSV column we declared in listOfDataDescriptions.
    # The variable target uses the "#dataSourceId" form (spec sec 2.2.10).
    column_dg_index: List[Dict[str, str]] = []
    for entry in data_source_index:
        dg_id = _safe_sid(f"dg_{entry['data_source_id']}")
        var_id = _safe_sid(f"var_{entry['data_source_id']}")
        dg = ET.SubElement(list_of_dgs, 'dataGenerator')
        dg.set('id', dg_id)
        dg.set('name', entry['column_name'])
        lov_c = ET.SubElement(dg, 'listOfVariables')
        var_c = ET.SubElement(lov_c, 'variable')
        var_c.set('id', var_id)
        var_c.set('target', f"#{entry['data_source_id']}")
        math_c = ET.SubElement(dg, '{%s}math' % MATHML_NAMESPACE)
        ci_c = ET.SubElement(math_c, '{%s}ci' % MATHML_NAMESPACE)
        ci_c.text = var_id
        column_dg_index.append({
            'csv': entry['csv'],
            'column_id': entry['column_id'],
            'column_name': entry['column_name'],
            'data_generator_id': dg_id,
        })

    # listOfOutputs: a Report whose listOfDataSets references the
    # DataGenerators above. Spec sec 2.2.13.1: DataSet requires label and
    # dataReference (SIdRef to a DataGenerator).
    list_of_outputs = ET.SubElement(root, 'listOfOutputs')
    report = ET.SubElement(list_of_outputs, 'report')
    report.set('id', 'report_outputs')
    report.set('name', f"vCornea outputs: {run_name}")

    report_notes = ET.SubElement(report, 'notes')
    report_body = ET.SubElement(report_notes, '{%s}body' % XHTML_NAMESPACE)
    report_p1 = ET.SubElement(report_body, '{%s}p' % XHTML_NAMESPACE)
    report_p1.text = ("Standards-compliant report referencing the DataGenerators built "
                      "from the CSV outputs packaged in this archive.")
    ul = ET.SubElement(report_body, '{%s}ul' % XHTML_NAMESPACE)
    for fname in sorted(output_files):
        li = ET.SubElement(ul, '{%s}li' % XHTML_NAMESPACE)
        li.text = fname
    report_p2 = ET.SubElement(report_body, '{%s}p' % XHTML_NAMESPACE)
    report_p2.text = "See run_metadata.json for complete output inventory and derived metrics."

    list_of_datasets = ET.SubElement(report, 'listOfDataSets')
    ds_time = ET.SubElement(list_of_datasets, 'dataSet')
    ds_time.set('id', 'ds_time')
    ds_time.set('label', 'Time (MCS)')
    ds_time.set('dataReference', 'dg_time')
    for entry in column_dg_index:
        ds = ET.SubElement(list_of_datasets, 'dataSet')
        ds.set('id', _safe_sid(f"ds_{entry['data_generator_id']}"))
        ds.set('label', f"{entry['csv']}::{entry['column_id']}")
        ds.set('dataReference', entry['data_generator_id'])

    # Generate XML string with declaration
    xml_str = ET.tostring(root, encoding='unicode', method='xml')

    # Add XML declaration
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# =============================================================================
# PARAMETER SCAN SUPPORT (design scaffold — NOT yet wired into live generation)
# =============================================================================
#
# DESIGN NOTE (parameter scans / sweeps)
# --------------------------------------
# Today the generator only encodes replicates (a repeatedTask + uniformRange over a
# dummy index). A *parameter scan* is the other use of repeatedTask: re-running the
# model while varying one or more parameters. The intended GUI semantics:
#
#   * GUI passes a single value for a parameter  -> fixed parameter (current behaviour)
#   * GUI passes multiple values for a parameter -> a scan over that parameter
#   * GUI passes multiple SWEPT parameters       -> the cartesian product of their ranges
#
# In SED-ML this maps to:
#   <repeatedTask resetModel="true" range="range_outer">
#     <listOfRanges>
#       <vectorRange id="range_p0"> <value>..</value> ... </vectorRange>   (one per swept param)
#       <vectorRange id="range_p1"> ... </vectorRange>
#       ... functionalRange/nesting to express the cartesian product ...
#     </listOfRanges>
#     <listOfChanges>
#       <setValue modelReference="model_cc3d" range="range_p0" target="<param>"> ... </setValue>
#       ...
#     </listOfChanges>
#     <listOfSubTasks><subTask task="task_run" order="1"/></listOfSubTasks>
#   </repeatedTask>
#
# Blocker to going live: run_metadata.json currently records single scalar parameter
# values (e.g. "SimTime": 24), not value lists/ranges, so there is no scan spec to
# read yet. Recommendation: have the GUI/wrapper emit a `parameter_scan` block in
# run_metadata (e.g. {"SLS_Concentration": [250, 500, 750], "InjuryTime": [3, 6]})
# and pass it here; then call build_parameter_scan_repeated_task() below instead of
# the replicate-only repeatedTask. CC3D model targets are not XPath into an SBML
# model, so `target` should reference the Parameters.py symbol by name (documented as
# a CC3D-specific convention, consistent with how MODEL_LANGUAGE_URI is community-defined).

def build_parameter_scan_repeated_task(scan_spec: Dict[str, List[Any]],
                                       base_task_id: str = 'task_run',
                                       model_id: str = 'model_cc3d') -> Optional[ET.Element]:
    """Build a SED-ML <repeatedTask> encoding a (possibly multi-parameter) scan.

    The cartesian product of all swept parameters is FLATTENED to N points, encoded
    as one aligned vectorRange per parameter (each of length N). The repeatedTask
    iterates over the master range (N iterations); each per-parameter setValue picks
    that parameter's value for the current point from its aligned vectorRange. This
    correctly represents a multi-parameter scan without nested repeatedTasks.

    Used live by the experiment-level scan archive (create_experiment_scan_archive).

    Args:
        scan_spec: {parameter_name: [value, value, ...]} for each swept parameter.
                   Multiple keys denote a cartesian product of their value lists.
        base_task_id: id of the single-run task each scan point executes.
        model_id: id of the model whose parameters are set. CC3D targets are
                  Parameters.py symbol names (community convention), not XPath.

    Returns:
        An ElementTree <repeatedTask> Element, or None if scan_spec is empty.
    """
    if not scan_spec:
        return None

    from itertools import product
    param_names = list(scan_spec.keys())
    value_lists = [list(scan_spec[p]) for p in param_names]
    combinations = list(product(*value_lists))  # N flattened scan points

    repeated = ET.Element('repeatedTask')
    repeated.set('id', 'parameter_scan_task')
    repeated.set('resetModel', 'true')

    list_of_ranges = ET.SubElement(repeated, 'listOfRanges')
    list_of_changes = ET.SubElement(repeated, 'listOfChanges')

    # One aligned vectorRange (length N) + one setValue per swept parameter.
    range_ids = []
    for i, param in enumerate(param_names):
        range_id = _safe_sid(f"range_{param}")
        range_ids.append(range_id)
        vrange = ET.SubElement(list_of_ranges, 'vectorRange')
        vrange.set('id', range_id)
        for combo in combinations:
            ve = ET.SubElement(vrange, 'value')
            ve.text = str(combo[i])

        set_value = ET.SubElement(list_of_changes, 'setValue')
        set_value.set('modelReference', model_id)
        set_value.set('range', range_id)
        set_value.set('target', param)  # CC3D Parameters.py symbol name (not XPath)
        math_v = ET.SubElement(set_value, '{%s}math' % MATHML_NAMESPACE)
        ci_v = ET.SubElement(math_v, '{%s}ci' % MATHML_NAMESPACE)
        ci_v.text = range_id

    # All vectorRanges have length N and are index-aligned; the first drives iteration.
    repeated.set('range', range_ids[0])
    list_of_subtasks = ET.SubElement(repeated, 'listOfSubTasks')
    subtask = ET.SubElement(list_of_subtasks, 'subTask')
    subtask.set('task', base_task_id)
    subtask.set('order', '1')
    return repeated


def generate_omex_manifest(
    files: List[Dict[str, str]],
    sedml_location: str = "simulation.sedml"
) -> str:
    """
    Generate an OMEX manifest.xml listing all archive contents.

    Args:
        files: List of dicts with 'location' and optional 'format' keys
        sedml_location: Location of the main SED-ML file (will be marked master)

    Returns:
        XML string of the manifest
    """
    ET.register_namespace('', OMEX_MANIFEST_NAMESPACE)

    root = ET.Element('omexManifest')
    root.set('xmlns', OMEX_MANIFEST_NAMESPACE)

    # Root entry (the archive itself)
    root_content = ET.SubElement(root, 'content')
    root_content.set('location', '.')
    root_content.set('format', FORMAT_URIS['.omex'])

    # Add all files
    for file_info in files:
        location = file_info['location']

        # Determine format URI
        if 'format' in file_info:
            format_uri = file_info['format']
        else:
            ext = Path(location).suffix.lower()
            format_uri = FORMAT_URIS.get(ext, DEFAULT_FORMAT_URI)

        content = ET.SubElement(root, 'content')
        content.set('location', location)
        content.set('format', format_uri)

        # Mark the main SED-ML file as master
        if location == sedml_location:
            content.set('master', 'true')

    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# =============================================================================
# OMEX ARCHIVE CREATION
# =============================================================================

def _resolve_project_path(p):
    """Map a Windows/WSL UNC path (\\\\wsl.localhost\\<distro>\\home\\... or
    \\\\wsl$\\...) to its POSIX form so the model project resolves cross-platform."""
    if p is None:
        return None
    import re
    s = str(p)
    m = re.match(r'^\\\\wsl(?:\.localhost|\$)\\[^\\]+\\(.*)$', s)
    if m:
        s = '/' + m.group(1).replace('\\', '/')
    return Path(s)


def _collect_model_files(model_path):
    """Return ([(src_path, archive_path), ...], primary_cc3d_archive_path) for the
    CC3D project: the .cc3d descriptor(s), PIFF seeds, Simulation/ steppables+XML,
    and any MaBoSS files. The primary .cc3d (preferring vCornea_v2.cc3d) is what the
    SED-ML model/@source should point at."""
    model_path = Path(model_path)
    files, primary = [], None
    for cc3d in sorted(model_path.glob('*.cc3d')):
        ap = f"model/{cc3d.name}"
        files.append((cc3d, ap))
        if primary is None or cc3d.name == 'vCornea_v2.cc3d':
            primary = ap
    for piff in sorted(model_path.glob('*.piff')):
        files.append((piff, f"model/{piff.name}"))
    sim = model_path / 'Simulation'
    if sim.exists():
        for pat in ('*.py', '*.xml', '*.piff'):
            for f in sorted(sim.glob(pat)):
                files.append((f, f"model/Simulation/{f.name}"))
    mb = model_path / 'MaBoSS'
    if mb.exists():
        for pat in ('*.bnd', '*.cfg'):
            for f in sorted(mb.glob(pat)):
                files.append((f, f"model/MaBoSS/{f.name}"))
    return files, primary


def generate_omex_metadata_rdf(*, title, description=None, created=None, modified=None,
                               creators=None, license_uri=None, citation=None,
                               keywords=None, about='.'):
    """Build an OMEX-Metadata RDF/XML document (Dublin Core terms + vCard creators).

    Records the run's provenance: title, description, creator(s) (the person
    RESPONSIBLE for the parameter choices), created/modified dates, license, and a
    bibliographic citation. This is attribution/provenance — not authentication.
    """
    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    DCT = "http://purl.org/dc/terms/"
    VC = "http://www.w3.org/2006/vcard/ns#"
    ET.register_namespace('rdf', RDF)
    ET.register_namespace('dcterms', DCT)
    ET.register_namespace('vCard', VC)
    root = ET.Element('{%s}RDF' % RDF)
    desc = ET.SubElement(root, '{%s}Description' % RDF)
    desc.set('{%s}about' % RDF, about)

    def add(tag, text):
        e = ET.SubElement(desc, '{%s}%s' % (DCT, tag)); e.text = str(text)

    add('title', title)
    if description:
        add('description', description)
    for c in (creators or []):
        cr = ET.SubElement(desc, '{%s}creator' % DCT)
        li = ET.SubElement(cr, '{%s}Description' % RDF)
        nm = ET.SubElement(li, '{%s}hasName' % VC)
        nmd = ET.SubElement(nm, '{%s}Description' % RDF)
        if c.get('family'):
            ET.SubElement(nmd, '{%s}family-name' % VC).text = c['family']
        if c.get('given'):
            ET.SubElement(nmd, '{%s}given-name' % VC).text = c['given']
        if c.get('email'):
            ET.SubElement(li, '{%s}hasEmail' % VC).text = c['email']
        if c.get('orcid'):
            ET.SubElement(li, '{%s}identifier' % DCT).text = c['orcid']
    for tag, val in (('created', created), ('modified', modified or created)):
        if val:
            e = ET.SubElement(desc, '{%s}%s' % (DCT, tag))
            ET.SubElement(e, '{%s}W3CDTF' % DCT).text = str(val)
    if license_uri:
        add('license', license_uri)
    if citation:
        add('bibliographicCitation', citation)
    for kw in (keywords or []):
        add('subject', kw)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')


def create_omex_archive(
    run_output_dir: Union[str, Path],
    run_metadata: Dict[str, Any],
    sim_params: Dict[str, Any],
    include_model: bool = True,
    model_path: Optional[Path] = None,
    include_data_descriptions: bool = True,
    creator: Optional[Dict[str, str]] = None,
    license_uri: str = "https://spdx.org/licenses/CC-BY-4.0.html",
    description: Optional[str] = None,
    citation: str = ("Vanin et al. (2025). V-Cornea: a computational model of the "
                     "corneal epithelium."),
    keywords: Optional[List[str]] = None,
    failed: bool = False,
) -> Path:
    """
    Create a COMBINE/OMEX archive containing all simulation outputs.

    Failed runs (`failed=True`): the same container and typed manifest, carrying
    params/provenance, logs and any partial outputs that exist, but marked failed and
    WITHOUT asserting a reproducible experiment — the executable SED-ML is omitted
    (so a consumer cannot mistake it for a completed run), a machine-readable
    status.json is added, run_metadata.simulation_status='failed', and the provenance
    RDF states the failure.

    The archive structure follows OMEX conventions:
    - manifest.xml at root (required)
    - simulation.sedml (SED-ML L1V5, marked as master)
    - run_metadata.json (parameter provenance)
    - Parameters.py (CC3D parameters)
    - Output files (CSV, Parquet, etc.)
    - Optionally: model files

    Phase 2 additions:
    - Automatic model path detection from sim_params/run_metadata
    - More comprehensive model file packaging
    - Support for repeatedTask and dataDescription in SED-ML

    Args:
        run_output_dir: Directory containing simulation outputs
        run_metadata: Dictionary with run metadata (from run_metadata.json)
        sim_params: Simulation parameters
        include_model: Whether to include the CC3D model files
        model_path: Path to CC3D project (auto-detected if None and include_model=True)
        include_data_descriptions: Whether to include dataDescription for CSV files

    Returns:
        Path to the created .omex archive
    """
    run_output_dir = Path(run_output_dir)
    run_name = run_metadata.get('run_name', 'simulation')
    omex_path = run_output_dir / f"{run_name}.omex"
    num_replicates = run_metadata.get('total_replicates', 1)

    # Resolve the CC3D project path (auto-detect + UNC->POSIX mapping).
    if include_model and model_path is None:
        sim_config = run_metadata.get('simulation_config', {})
        model_path = (sim_config.get('vcornea_project_path')
                      or sim_params.get('vcornea_project_path'))
    model_path = _resolve_project_path(model_path) if (include_model and model_path) else None

    # Resolve the model files + the primary .cc3d BEFORE building SED-ML so that
    # model/@source points at a file that is actually bundled (self-containment).
    model_files = []
    model_source = "vcornea.cc3d"   # descriptive fallback if the project is absent
    if include_model and model_path and model_path.exists():
        model_files, primary = _collect_model_files(model_path)
        if primary:
            model_source = primary

    status = 'failed' if failed else 'success'

    output_files = [item.name for item in run_output_dir.iterdir()
                    if item.is_file() and item.suffix != '.omex']

    # A failed run omits the executable SED-ML entirely so a consumer cannot mistake
    # the archive for a completed, reproducible experiment.
    sedml_content = None if failed else generate_sedml_document(
        run_metadata=run_metadata,
        sim_params=sim_params,
        output_files=output_files,
        model_source=model_source,
        num_replicates=num_replicates,
        include_data_descriptions=include_data_descriptions,
    )

    # OMEX Metadata (provenance). Creator = whoever ran the experiment / set the
    # parameters; pulled from run_metadata if the GUI recorded it, else the arg.
    cr = creator or run_metadata.get('creator')
    creators = ([cr] if isinstance(cr, dict)
                else [{'given': str(cr)}] if cr else [])
    cfg = run_metadata.get('simulation_config', {})
    kp = run_metadata.get('key_parameters', {})
    status_phrase = ("FAILED run (incomplete; not a reproducible experiment). " if failed
                     else "")
    auto_desc = description or (
        f"{status_phrase}CompuCell3D V-Cornea run '{run_name}'. SimTime {cfg.get('sim_time')} days; "
        f"injury={'yes' if cfg.get('has_injury') else 'no'}"
        f"{(' (' + str(cfg.get('injury_type')) + ')') if cfg.get('has_injury') else ''}. "
        f"Key parameters: {', '.join(f'{k}={v}' for k, v in kp.items())}.")
    metadata_rdf = generate_omex_metadata_rdf(
        title=f"V-Cornea simulation: {run_name}" + (" [FAILED]" if failed else ""),
        description=auto_desc,
        created=run_metadata.get('created_at'),
        modified=datetime.now().isoformat(),
        creators=creators,
        license_uri=license_uri,
        citation=citation,
        keywords=keywords or ['CompuCell3D', 'cornea', 'epithelium',
                              'agent-based model', 'wound healing'],
    )

    manifest_entries = []
    with zipfile.ZipFile(omex_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. SED-ML (master) — successful runs only. A failed archive omits it so a
        #    consumer cannot mistake it for a completed, reproducible experiment.
        if sedml_content is not None:
            zf.writestr('simulation.sedml', sedml_content)
            manifest_entries.append({'location': 'simulation.sedml', 'format': FORMAT_URIS['.sedml']})

        # 2. OMEX Metadata (provenance)
        zf.writestr('metadata.rdf', metadata_rdf)
        manifest_entries.append({'location': 'metadata.rdf', 'format': OMEX_METADATA_FORMAT})

        # 2b. status.json — unambiguous machine-readable run status. Primary signal a
        #     consumer uses to tell a failed archive from a success.
        status_doc = {
            'status': status,
            'simulation_success': not failed,
            'executable_sedml_present': not failed,
            'run_name': run_name,
            'error_message': run_metadata.get('error_message'),
            'note': ('This run did NOT complete successfully. The archive preserves '
                     'parameters, provenance, logs and any partial outputs for audit, '
                     'but intentionally contains no executable SED-ML and asserts no '
                     'reproducible experiment.' if failed else
                     'Run completed successfully; simulation.sedml is the executable '
                     'master describing the reproducible experiment.'),
        }
        zf.writestr('status.json', json.dumps(status_doc, indent=2, default=str))
        manifest_entries.append({'location': 'status.json', 'format': FORMAT_URIS['.json']})

        # 3. Output files
        for item in run_output_dir.iterdir():
            if item.is_file() and item.suffix != '.omex':
                zf.write(item, item.name)
                manifest_entries.append({
                    'location': item.name,
                    'format': FORMAT_URIS.get(item.suffix.lower(), DEFAULT_FORMAT_URI)})

        # 4. Model files (so model/@source resolves — self-contained archive)
        for file_path, archive_path in model_files:
            zf.write(file_path, archive_path)
            manifest_entries.append({
                'location': archive_path,
                'format': FORMAT_URIS.get(file_path.suffix.lower(), DEFAULT_FORMAT_URI)})

        # 5. Manifest
        zf.writestr('manifest.xml', generate_omex_manifest(
            files=manifest_entries, sedml_location='simulation.sedml'))

    return omex_path


# =============================================================================
# EXPERIMENT-LEVEL PARAMETER-SCAN ARCHIVE
# =============================================================================

def generate_scan_sedml_document(
    scan_spec: Dict[str, List[Any]],
    combinations: List[Dict[str, Any]],
    run_name: str,
    sim_params: Dict[str, Any],
    num_replicates: int = 1,
) -> str:
    """Generate an experiment-level SED-ML describing a full parameter scan.

    Unlike the per-run document, this one DOES emit a scan repeatedTask (built by
    build_parameter_scan_repeated_task) — it is the executable description of the
    whole experiment, and the bundled scan_metadata.json maps each scan point to the
    folder holding its outputs.

    Args:
        scan_spec: {parameter: [values...]} for each swept parameter.
        combinations: list of per-point dicts; each may carry the point's swept
                      values plus a '_folder' (relative output path) and '_index'.
        run_name: experiment/batch name.
        sim_params: representative params (for the time course; SimTime in days).
        num_replicates: replicates per scan point (documented in notes).
    """
    ET.register_namespace('', SEDML_NAMESPACE)
    ET.register_namespace('html', XHTML_NAMESPACE)
    ET.register_namespace('math', MATHML_NAMESPACE)

    root = ET.Element('sedML')
    root.set('xmlns', SEDML_NAMESPACE)
    root.set('level', '1')
    root.set('version', SEDML_VERSION_ATTR)

    sim_time_days = sim_params.get('SimTime', 500)
    sim_time_mcs = int(round(sim_time_days * units.MCS_PER_DAY))
    n_points = len(combinations) if combinations else 1

    # Notes
    notes = ET.SubElement(root, 'notes')
    body = ET.SubElement(notes, '{%s}body' % XHTML_NAMESPACE)
    h2 = ET.SubElement(body, '{%s}h2' % XHTML_NAMESPACE)
    h2.text = f"CompuCell3D Parameter Scan: {run_name}"
    scan_dims = "; ".join(f"{p} ∈ {list(v)}" for p, v in scan_spec.items())
    info_lines = [
        f"This is the EXPERIMENT-level description of a parameter scan: {scan_dims}.",
        f"Scan points (cartesian product): {n_points}; replicates per point: "
        f"{num_replicates}; total simulations: {n_points * max(1, num_replicates)}.",
        f"Time course per run: {sim_time_days} days = {sim_time_mcs} MCS "
        f"(1 day = {int(units.MCS_PER_DAY)} MCS).",
        "",
        "The listOfTasks below contains a repeatedTask with one setValue per swept "
        "parameter (aligned vectorRanges encode the flattened cartesian product). "
        "Per-point output folders are listed in the bundled scan_metadata.json; each "
        "point also has its own per-run OMEX archive with that point's full data.",
    ]
    for line in info_lines:
        p = ET.SubElement(body, '{%s}p' % XHTML_NAMESPACE)
        p.text = line

    # Model
    list_of_models = ET.SubElement(root, 'listOfModels')
    model = ET.SubElement(list_of_models, 'model')
    model.set('id', 'model_cc3d')
    model.set('name', 'vCornea CellFate CC3D Model')
    model.set('source', 'vcornea.cc3d')
    model.set('language', MODEL_LANGUAGE_URI)

    # Simulation (single time course reused for every scan point)
    list_of_sims = ET.SubElement(root, 'listOfSimulations')
    sim = ET.SubElement(list_of_sims, 'uniformTimeCourse')
    sim.set('id', 'sim_mcs')
    sim.set('initialTime', '0')
    sim.set('outputStartTime', '0')
    sim.set('outputEndTime', str(sim_time_mcs))
    sim.set('numberOfSteps', str(sim_time_mcs))
    algorithm = ET.SubElement(sim, 'algorithm')
    algorithm.set('kisaoID', KISAO_ALGORITHM_ID)

    # Tasks: base single-run task + the scan repeatedTask
    list_of_tasks = ET.SubElement(root, 'listOfTasks')
    base_task = ET.SubElement(list_of_tasks, 'task')
    base_task.set('id', 'task_run')
    base_task.set('modelReference', 'model_cc3d')
    base_task.set('simulationReference', 'sim_mcs')
    scan_task = build_parameter_scan_repeated_task(scan_spec, base_task_id='task_run',
                                                   model_id='model_cc3d')
    if scan_task is not None:
        list_of_tasks.append(scan_task)

    # A time data generator referencing the scan task, so the scan contributes output
    list_of_dgs = ET.SubElement(root, 'listOfDataGenerators')
    dg_time = ET.SubElement(list_of_dgs, 'dataGenerator')
    dg_time.set('id', 'dg_time')
    dg_time.set('name', 'Simulation Time (MCS)')
    lov = ET.SubElement(dg_time, 'listOfVariables')
    var_t = ET.SubElement(lov, 'variable')
    var_t.set('id', 'var_time')
    var_t.set('taskReference', 'parameter_scan_task' if scan_task is not None else 'task_run')
    var_t.set('symbol', SEDML_SYMBOL_TIME)
    math_t = ET.SubElement(dg_time, '{%s}math' % MATHML_NAMESPACE)
    ci_t = ET.SubElement(math_t, '{%s}ci' % MATHML_NAMESPACE)
    ci_t.text = 'var_time'

    # Report
    list_of_outputs = ET.SubElement(root, 'listOfOutputs')
    report = ET.SubElement(list_of_outputs, 'report')
    report.set('id', 'report_scan')
    report.set('name', f"Parameter scan outputs: {run_name}")
    rnotes = ET.SubElement(report, 'notes')
    rbody = ET.SubElement(rnotes, '{%s}body' % XHTML_NAMESPACE)
    rp = ET.SubElement(rbody, '{%s}p' % XHTML_NAMESPACE)
    rp.text = ("Per-point outputs are catalogued in scan_metadata.json (folder per "
               "scan point). See each point's own OMEX for its full result files.")
    list_of_datasets = ET.SubElement(report, 'listOfDataSets')
    ds_time = ET.SubElement(list_of_datasets, 'dataSet')
    ds_time.set('id', 'ds_time')
    ds_time.set('label', 'Time (MCS)')
    ds_time.set('dataReference', 'dg_time')

    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


def _read_combo_summaries(batch_output_dir, combinations):
    """For each combination, read its per-replicate OMEX archives and return the
    REPLICATE-MEAN time series for each available metric (cell_count, surfactant,
    thickness spatial-mean).

    Returns an ordered list of {folder, label, metrics} where metrics maps a metric
    name to a DataFrame with a 'Time' column plus value columns. Empty if pandas is
    unavailable or no per-run archives are found (caller falls back to design-only).
    """
    import io
    try:
        import pandas as pd
    except Exception:
        return []
    batch_output_dir = Path(batch_output_dir)

    def _t(d):
        tk = next((c for c in d.columns if str(c).strip().lower() == 'time'), d.columns[-1])
        return d.rename(columns={tk: 'Time'}).set_index('Time')

    out = []
    for combo in combinations or []:
        folder = combo.get('_folder')
        if not folder:
            continue
        cdir = batch_output_dir / folder
        if not cdir.is_dir():
            continue
        cc, su, th = [], [], []
        for omex in sorted(cdir.rglob('*.omex')):
            try:
                with zipfile.ZipFile(omex) as zf:
                    names = zf.namelist()
                    if 'run_metadata.json' not in names:
                        continue

                    def _find(prefix, ext):
                        return next((n for n in names if Path(n).name.startswith(prefix)
                                     and n.endswith(ext)), None)
                    n = _find('cell_count', '.csv')
                    if n:
                        cc.append(_t(pd.read_csv(io.BytesIO(zf.read(n)))))
                    n = _find('surfactant', '.csv')
                    if n:
                        su.append(_t(pd.read_csv(io.BytesIO(zf.read(n)))))
                    n = _find('thickness', '.parquet')
                    if n:
                        d = pd.read_parquet(io.BytesIO(zf.read(n)))
                        if {'Time', 'Height'}.issubset(d.columns):
                            th.append(d.groupby('Time')['Height'].mean().to_frame('Height'))
            except Exception:
                continue
        metrics = {}
        if cc:
            metrics['cell_count'] = pd.concat(cc).groupby(level=0).mean(numeric_only=True).reset_index()
        if su:
            metrics['surfactant'] = pd.concat(su).groupby(level=0).mean(numeric_only=True).reset_index()
        if th:
            metrics['thickness'] = pd.concat(th).groupby(level=0).mean(numeric_only=True).reset_index()
        if not metrics:
            continue
        label = ", ".join(f"{k}={v}" for k, v in combo.items()
                          if not str(k).startswith('_')) or folder
        out.append({'folder': folder, 'label': label, 'metrics': metrics})
    return out


def generate_comparison_sedml_document(scan_spec, combo_info, run_name,
                                       sim_params, num_replicates=1):
    """Experiment-level SED-ML that COMPARES the combinations.

    On top of the scan repeatedTask, it adds, per (combination, metric), a
    dataDescription over the bundled replicate-mean CSV plus per-column
    dataGenerators, then one plot2D per (metric, signal) with a curve per
    combination (the side-by-side comparison) and a report listing every series.
    combo_info entries: {safe, label, metric, source, columns}.
    """
    ET.register_namespace('', SEDML_NAMESPACE)
    ET.register_namespace('html', XHTML_NAMESPACE)
    ET.register_namespace('math', MATHML_NAMESPACE)
    ET.register_namespace('numl', NUML_NAMESPACE)

    root = ET.Element('sedML')
    root.set('xmlns', SEDML_NAMESPACE)
    root.set('level', '1'); root.set('version', SEDML_VERSION_ATTR)

    sim_time_days = sim_params.get('SimTime', 500)
    sim_time_mcs = int(round(sim_time_days * units.MCS_PER_DAY))
    n_points = len({c['safe'] for c in combo_info})
    metrics_present = sorted({c['metric'] for c in combo_info})
    scan_dims = "; ".join(f"{p} ∈ {list(v)}" for p, v in scan_spec.items())

    notes = ET.SubElement(root, 'notes')
    body = ET.SubElement(notes, '{%s}body' % XHTML_NAMESPACE)
    h2 = ET.SubElement(body, '{%s}h2' % XHTML_NAMESPACE)
    h2.text = f"CompuCell3D Parameter Scan (comparison): {run_name}"
    for line in [
        f"Experiment-level COMPARISON of a parameter scan: {scan_dims}.",
        f"Combinations: {n_points}; replicates per point: {num_replicates}. Metrics "
        f"compared: {', '.join(metrics_present)} (bundled in combo_data/ as each "
        "combination's replicate-MEAN series).",
        "The repeatedTask documents the scan design; the plot2D outputs below place "
        "the combinations side by side (one curve per combination per signal).",
    ]:
        ET.SubElement(body, '{%s}p' % XHTML_NAMESPACE).text = line

    list_of_models = ET.SubElement(root, 'listOfModels')
    model = ET.SubElement(list_of_models, 'model')
    model.set('id', 'model_cc3d'); model.set('name', 'vCornea CellFate CC3D Model')
    model.set('source', 'vcornea.cc3d'); model.set('language', MODEL_LANGUAGE_URI)

    list_of_sims = ET.SubElement(root, 'listOfSimulations')
    sim = ET.SubElement(list_of_sims, 'uniformTimeCourse')
    sim.set('id', 'sim_mcs'); sim.set('initialTime', '0'); sim.set('outputStartTime', '0')
    sim.set('outputEndTime', str(sim_time_mcs)); sim.set('numberOfSteps', str(sim_time_mcs))
    ET.SubElement(sim, 'algorithm').set('kisaoID', KISAO_ALGORITHM_ID)

    list_of_tasks = ET.SubElement(root, 'listOfTasks')
    bt = ET.SubElement(list_of_tasks, 'task')
    bt.set('id', 'task_run'); bt.set('modelReference', 'model_cc3d')
    bt.set('simulationReference', 'sim_mcs')
    scan_task = build_parameter_scan_repeated_task(scan_spec)
    if scan_task is not None:
        list_of_tasks.append(scan_task)

    list_of_dd = ET.SubElement(root, 'listOfDataDescriptions')
    list_of_dgs = ET.SubElement(root, 'listOfDataGenerators')
    # (metric, col) -> [(label, time_dg, val_dg)]; preserves a plot2D per signal.
    signal_curves = {}
    signal_order = []
    report_sets = []   # (label, metric, col, dg_id)
    for c in combo_info:
        safe, metric, src, cols = c['safe'], c['metric'], c['source'], c['columns']
        ddid = _safe_sid(f"data_{safe}_{metric}")
        dd = ET.SubElement(list_of_dd, 'dataDescription')
        dd.set('id', ddid); dd.set('name', f"{c['label']} — {metric} (replicate-mean)")
        dd.set('source', src); dd.set('format', 'urn:sedml:format:csv')
        dim = ET.SubElement(dd, 'dimensionDescription')
        outer = ET.SubElement(dim, '{%s}compositeDescription' % NUML_NAMESPACE)
        outer.set('indexType', 'integer'); outer.set('id', 'rowIdx'); outer.set('name', 'Row')
        inner = ET.SubElement(outer, '{%s}compositeDescription' % NUML_NAMESPACE)
        inner.set('indexType', 'string'); inner.set('id', 'columnIds'); inner.set('name', 'Column')
        at = ET.SubElement(inner, '{%s}atomicDescription' % NUML_NAMESPACE)
        at.set('valueType', 'double'); at.set('id', 'value'); at.set('name', 'Value')
        los = ET.SubElement(dd, 'listOfDataSources')
        time_dg = None
        for col in ['Time'] + cols:
            dsid = _safe_sid(f"ds_{safe}_{metric}_{col}")
            dsrc = ET.SubElement(los, 'dataSource'); dsrc.set('id', dsid); dsrc.set('name', col)
            sl = ET.SubElement(ET.SubElement(dsrc, 'listOfSlices'), 'slice')
            sl.set('reference', 'columnIds'); sl.set('value', col)
            dgid = _safe_sid(f"dg_{safe}_{metric}_{col}")
            dg = ET.SubElement(list_of_dgs, 'dataGenerator')
            dg.set('id', dgid); dg.set('name', f"{c['label']} :: {metric} :: {col}")
            v = ET.SubElement(ET.SubElement(dg, 'listOfVariables'), 'variable')
            vid = _safe_sid(f"var_{safe}_{metric}_{col}")
            v.set('id', vid); v.set('target', f"#{dsid}")
            ET.SubElement(ET.SubElement(dg, '{%s}math' % MATHML_NAMESPACE),
                          '{%s}ci' % MATHML_NAMESPACE).text = vid
            if col == 'Time':
                time_dg = dgid
            else:
                key = (metric, col)
                if key not in signal_curves:
                    signal_curves[key] = []; signal_order.append(key)
                signal_curves[key].append((c['label'], time_dg, dgid))
                report_sets.append((c['label'], metric, col, dgid))

    list_of_outputs = ET.SubElement(root, 'listOfOutputs')
    # one plot2D per (metric, signal) — a curve per combination (the comparison)
    for (metric, col) in signal_order:
        plot = ET.SubElement(list_of_outputs, 'plot2D')
        plot.set('id', _safe_sid(f"plot_{metric}_{col}"))
        plot.set('name', f"{col} ({metric}) across combinations")
        loc = ET.SubElement(plot, 'listOfCurves')
        for i, (label, tdg, vdg) in enumerate(signal_curves[(metric, col)]):
            cur = ET.SubElement(loc, 'curve')
            cur.set('id', _safe_sid(f"curve_{metric}_{col}_{i}"))
            cur.set('logX', 'false'); cur.set('logY', 'false')
            cur.set('xDataReference', tdg); cur.set('yDataReference', vdg)
    # a report enumerating every (combination, metric, signal) series
    report = ET.SubElement(list_of_outputs, 'report')
    report.set('id', 'report_comparison')
    report.set('name', f"Comparison across combinations: {run_name}")
    lod = ET.SubElement(report, 'listOfDataSets')
    for i, (label, metric, col, dgid) in enumerate(report_sets):
        ds = ET.SubElement(lod, 'dataSet')
        ds.set('id', _safe_sid(f"out_{i}_{metric}_{col}"))
        ds.set('label', f"{label} :: {metric} :: {col}"); ds.set('dataReference', dgid)

    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


def create_experiment_scan_archive(
    batch_output_dir: Union[str, Path],
    scan_spec: Dict[str, List[Any]],
    combinations: List[Dict[str, Any]],
    sim_params: Dict[str, Any],
    run_name: Optional[str] = None,
    num_replicates: int = 1,
    creator: Optional[Dict[str, str]] = None,
    license_uri: str = "https://spdx.org/licenses/CC-BY-4.0.html",
    citation: str = ("Vanin et al. (2025). V-Cornea: a computational model of the "
                     "corneal epithelium."),
    keywords: Optional[List[str]] = None,
) -> Optional[Path]:
    """Create ONE experiment-level OMEX at the batch root documenting a full scan.

    Bundles: the scan SED-ML (master), a scan_metadata.json cataloguing every scan
    point and its output folder, a metadata.rdf (OMEX Metadata provenance), and the
    manifest. Per-point raw data stays in the per-run archives.

    Returns the .omex path, or None if there is nothing to scan (empty scan_spec).
    """
    if not scan_spec:
        return None
    batch_output_dir = Path(batch_output_dir)
    run_name = run_name or batch_output_dir.name or 'parameter_scan'
    omex_path = batch_output_dir / f"{run_name}_scan.omex"

    # Try to build the COMPARISON SED-ML from each combo's replicate-mean data
    # (read from the per-combo per-replicate OMEX). Falls back to the design-only
    # scan SED-ML when the per-run archives / pandas are unavailable.
    summaries = _read_combo_summaries(batch_output_dir, combinations)
    data_files = {}        # in-archive path -> CSV text
    if summaries:
        combo_info = []    # one entry per (combination, metric)
        for s in summaries:
            safe = _safe_sid(s['folder'])
            for metric, df in s['metrics'].items():
                src = f"combo_data/{safe}_{metric}.csv"
                data_files[src] = df.to_csv(index=False)
                combo_info.append({'safe': safe, 'label': s['label'], 'metric': metric,
                                   'source': src,
                                   'columns': [c for c in df.columns if c != 'Time']})
        sedml_content = generate_comparison_sedml_document(
            scan_spec, combo_info, run_name, sim_params, num_replicates)
    else:
        sedml_content = generate_scan_sedml_document(
            scan_spec=scan_spec, combinations=combinations, run_name=run_name,
            sim_params=sim_params, num_replicates=num_replicates)

    scan_metadata = {
        'run_name': run_name,
        'created_at': datetime.now().isoformat(),
        'vivarium_wrapper_version': '1.0.0',
        'archive_type': 'experiment_scan',
        'comparison': bool(summaries),
        'parameter_scan': scan_spec,
        'total_scan_points': len(combinations) if combinations else 0,
        'replicates_per_point': num_replicates,
        'total_simulations': (len(combinations) if combinations else 0) * max(1, num_replicates),
        'combinations': combinations,
    }

    # OMEX Metadata (provenance) for the experiment-level archive.
    cr = creator
    creators = ([cr] if isinstance(cr, dict) else [{'given': str(cr)}] if cr else [])
    scan_dims = "; ".join(f"{k} in {list(v)}" for k, v in scan_spec.items())
    metadata_rdf = generate_omex_metadata_rdf(
        title=f"V-Cornea parameter scan: {run_name}",
        description=(f"Experiment-level COMBINE archive for a parameter scan ({scan_dims}); "
                     f"{scan_metadata['total_scan_points']} points x {num_replicates} "
                     f"replicates. Compares the combinations via plot2D outputs."),
        created=scan_metadata['created_at'],
        modified=datetime.now().isoformat(),
        creators=creators,
        license_uri=license_uri,
        citation=citation,
        keywords=keywords or ['CompuCell3D', 'cornea', 'parameter scan',
                              'agent-based model', 'wound healing'],
    )

    with zipfile.ZipFile(omex_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('scan.sedml', sedml_content)
        zf.writestr('metadata.rdf', metadata_rdf)
        zf.writestr('scan_metadata.json', json.dumps(scan_metadata, indent=2, default=str))
        manifest_entries = [
            {'location': 'scan.sedml', 'format': FORMAT_URIS['.sedml']},
            {'location': 'metadata.rdf', 'format': OMEX_METADATA_FORMAT},
            {'location': 'scan_metadata.json', 'format': FORMAT_URIS['.json']},
        ]
        for src, text in data_files.items():
            zf.writestr(src, text)
            manifest_entries.append({'location': src, 'format': FORMAT_URIS['.csv']})
        manifest_content = generate_omex_manifest(manifest_entries, sedml_location='scan.sedml')
        zf.writestr('manifest.xml', manifest_content)

    return omex_path


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_format_uri(filename: str) -> str:
    """
    Get the format URI for a file based on its extension.

    Args:
        filename: Name or path of the file

    Returns:
        Format URI string
    """
    ext = Path(filename).suffix.lower()
    return FORMAT_URIS.get(ext, DEFAULT_FORMAT_URI)


def validate_sedml_structure(sedml_content: str) -> Dict[str, Any]:
    """
    Basic structural validation of SED-ML content.

    This performs basic checks without requiring libSEDML.
    For full validation, use the SED-ML Web Tools or libSEDML.

    Args:
        sedml_content: XML string of SED-ML document

    Returns:
        Dict with 'valid' bool and 'errors' list
    """
    errors = []

    try:
        root = ET.fromstring(sedml_content)
    except ET.ParseError as e:
        return {'valid': False, 'errors': [f'XML parse error: {e}']}

    # Check root element
    if not root.tag.endswith('sedML'):
        errors.append(f"Root element should be 'sedML', got '{root.tag}'")

    # Check required attributes (L1V5 schema is shared with L1V4)
    if root.get('level') != '1':
        errors.append("Missing or incorrect 'level' attribute (should be '1')")
    if root.get('version') != SEDML_VERSION_ATTR:
        errors.append(
            f"Missing or incorrect 'version' attribute "
            f"(should be '{SEDML_VERSION_ATTR}')"
        )

    # listOf* containers are formally optional, but a coherent simulation
    # description has Models, Simulations, Tasks, DataGenerators, and Outputs.
    # Any Output dataReference must resolve to a DataGenerator (sec 2.2.10).
    expected_sections = [
        'listOfModels', 'listOfSimulations', 'listOfTasks',
        'listOfDataGenerators', 'listOfOutputs',
    ]
    present = {child.tag.split('}', 1)[-1] for child in root}
    for section in expected_sections:
        if section not in present:
            errors.append(f"Missing expected section: {section}")

    return {
        'valid': len(errors) == 0,
        'errors': errors,
    }


def validate_omex_manifest(manifest_content: str, archive_files: List[str]) -> Dict[str, Any]:
    """
    Basic validation of OMEX manifest.

    Args:
        manifest_content: XML string of manifest
        archive_files: List of actual files in the archive

    Returns:
        Dict with 'valid' bool and 'errors' list
    """
    errors = []

    try:
        root = ET.fromstring(manifest_content)
    except ET.ParseError as e:
        return {'valid': False, 'errors': [f'XML parse error: {e}']}

    # Collect locations from manifest
    manifest_locations = set()
    has_master = False
    has_sedml = False

    for content in root.findall('.//{%s}content' % OMEX_MANIFEST_NAMESPACE):
        location = content.get('location')
        if location and location != '.':
            manifest_locations.add(location)
        if location and location.endswith('.sedml'):
            has_sedml = True
        if content.get('master') == 'true':
            has_master = True

    # A master entry is required only when the archive carries an executable SED-ML.
    # A failed-run archive deliberately omits the SED-ML (so it cannot be mistaken for
    # a reproducible success) and therefore has no master — that is valid.
    if has_sedml and not has_master:
        errors.append("No file marked as master='true'")

    # Check that all archive files are in manifest
    archive_set = set(archive_files)
    missing_in_manifest = archive_set - manifest_locations - {'manifest.xml'}
    if missing_in_manifest:
        errors.append(f"Files in archive but not in manifest: {missing_in_manifest}")

    # Check that all manifest files exist in archive
    missing_in_archive = manifest_locations - archive_set
    if missing_in_archive:
        errors.append(f"Files in manifest but not in archive: {missing_in_archive}")

    return {
        'valid': len(errors) == 0,
        'errors': errors
    }
