"""
Schema utilities for Angiogenesis GUI

This module extracts and organizes parameter information from the
AngiogenesisProcess ports_schema() for GUI generation.

Similar to vCornea-GUI's schema_utils.py but adapted for angiogenesis model.

Author: GUI Integration
Date: 2025
"""

from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


# =============================================================================
# TAB ORGANIZATION CONFIGURATION
# =============================================================================

# Maps schema _category to GUI Tab names
# This allows flexibility in organizing parameters differently in GUI vs schema
CATEGORY_TO_TAB_MAP = {
    'Cell Properties': 'Cell Behavior',
    'Growth Factors': 'VEGF Dynamics',
    'Simulation Setup': 'Simulation',
}

# Defines the order tabs appear in the GUI
TAB_ORDER = [
    'Cell Behavior',
    'VEGF Dynamics',
    'Simulation',
]


# =============================================================================
# CORE EXTRACTION FUNCTIONS
# =============================================================================

def get_parameter_structure(schema: Dict) -> Dict[str, Dict[str, Dict[str, str]]]:
    """
    Extracts the parameter structure (Tabs > Groups > Params) from the schema.

    This creates the hierarchical structure used by main_window.py to generate
    the tab-based parameter interface.

    Args:
        schema: The ports schema from AngiogenesisProcess.ports_schema()

    Returns:
        dict: {
            tab_name: {
                group_name: {
                    param_name: description,
                    ...
                },
                ...
            },
            ...
        }

    Example:
        {
            'Cell Behavior': {
                'Adhesion': {
                    'jee': 'EC-EC adhesion energy...',
                    'jem': 'EC-Medium adhesion energy...',
                },
                'Chemotaxis': {
                    'lchem': 'Chemotaxis strength...',
                }
            }
        }
    """
    # Initialize structure with correct tab order
    structure = {tab: {} for tab in TAB_ORDER}

    if 'inputs' not in schema:
        return structure

    for param_name, param_info in schema['inputs'].items():
        # Extract categorization from schema
        category = param_info.get('_category', 'General')
        subcategory = param_info.get('_subcategory', 'Parameters')
        description = param_info.get('_description', '')

        # Map schema category to GUI tab name
        tab_name = CATEGORY_TO_TAB_MAP.get(category, category)

        # Initialize tab and group if needed
        if tab_name not in structure:
            structure[tab_name] = {}
        if subcategory not in structure[tab_name]:
            structure[tab_name][subcategory] = {}

        # Add parameter to structure
        structure[tab_name][subcategory][param_name] = description

    # Clean up empty pre-defined tabs
    return {tab: groups for tab, groups in structure.items() if groups}


def get_display_name_mapping(schema: Dict) -> Dict[str, str]:
    """
    Extracts display name mappings from the schema.

    Args:
        schema: The ports schema from AngiogenesisProcess

    Returns:
        dict: {param_name: display_name, ...}

    Example:
        {'jee': 'EC-EC Adhesion Energy', 'jem': 'EC-Medium Adhesion Energy'}
    """
    display_mapping = {}

    if 'inputs' in schema:
        for param_name, param_info in schema['inputs'].items():
            # Use _display_name if available, otherwise format param_name
            fallback_name = param_name.replace('_', ' ').title()
            display_mapping[param_name] = param_info.get('_display_name', fallback_name)

    return display_mapping


def get_model_defaults(schema: Dict) -> Dict[str, Any]:
    """
    Extracts the default value for each parameter.

    This is used for "Reset to Default" functionality and parameter change detection.

    Args:
        schema: The ports schema from AngiogenesisProcess

    Returns:
        dict: {param_name: default_value, ...}

    Example:
        {'jee': 2.0, 'jem': 2.0, 'lchem': 500.0}
    """
    defaults = {}

    if 'inputs' in schema:
        for param_name, param_info in schema['inputs'].items():
            if '_default' in param_info:
                defaults[param_name] = param_info['_default']

    return defaults


def get_parameter_presets(schema: Dict) -> Dict[str, Dict[str, Any]]:
    """
    Extracts parameter presets from individual parameter schemas.

    Presets allow users to quickly apply common parameter combinations.

    Args:
        schema: The ports schema from AngiogenesisProcess

    Returns:
        dict: {
            preset_name: {
                param_name: value,
                ...
            },
            ...
        }

    Example:
        {
            'strong_adhesion': {'jee': 2.0, 'jem': 2.0},
            'weak_adhesion': {'jee': 8.0, 'jem': 8.0},
        }
    """
    presets = {}

    if 'inputs' in schema:
        for param_name, param_info in schema['inputs'].items():
            if '_presets' in param_info:
                for preset_name, preset_value in param_info['_presets'].items():
                    if preset_name not in presets:
                        presets[preset_name] = {}
                    presets[preset_name][param_name] = preset_value

    return presets


def get_parameters_by_expertise_level(schema: Dict, level: str = 'basic') -> List[str]:
    """
    Get parameters filtered by expertise level.

    This enables the GUI to show/hide parameters based on user expertise.

    Args:
        schema: The ports schema from AngiogenesisProcess
        level: 'basic', 'intermediate', or 'advanced'

    Returns:
        list: Parameter names at or below specified level
    """
    level_order = {'basic': 0, 'intermediate': 1, 'advanced': 2}
    target_level = level_order.get(level, 0)

    params = []
    if 'inputs' in schema:
        for param_name, param_info in schema['inputs'].items():
            param_level = param_info.get('_expert_level', 'advanced')
            if level_order.get(param_level, 2) <= target_level:
                # Check if explicitly hidden in basic mode
                if level == 'basic' and param_info.get('_hidden_basic', False):
                    continue
                params.append(param_name)

    return params


def get_reference_information(schema: Dict, param_name: str) -> Optional[Dict]:
    """
    Get complete reference information for a parameter.

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        dict or None: Reference information including DOI, citation, etc.
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return None

    param_info = schema['inputs'][param_name]
    return param_info.get('_reference_paper', None)


def get_validation_ranges(schema: Dict, param_name: str) -> Dict[str, Tuple]:
    """
    Get all validation ranges for a parameter.

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        dict: {
            'physiological': (min, max),
            'recommended': (min, max),
            'mathematical': (min, max),
        }
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return {}

    param_info = schema['inputs'][param_name]
    ranges = {}

    if '_physiological_range' in param_info:
        ranges['physiological'] = param_info['_physiological_range']
    if '_recommended_range' in param_info:
        ranges['recommended'] = param_info['_recommended_range']
    if '_mathematical_range' in param_info:
        ranges['mathematical'] = param_info['_mathematical_range']

    return ranges


def get_parameter_relationships(schema: Dict, param_name: str) -> Dict[str, List[str]]:
    """
    Get related and dependent parameters.

    This helps the GUI show parameter connections and dependencies.

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        dict: {
            'related': [param_names],  # Parameters that interact
            'depends_on': [param_names],  # Parameters this depends on
            'affects': [output_names],  # Outputs this affects
        }
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return {}

    param_info = schema['inputs'][param_name]

    return {
        'related': param_info.get('_related_parameters', []),
        'depends_on': param_info.get('_depends_on', []),
        'affects': param_info.get('_affects_output', []),
    }


def get_gui_hints(schema: Dict, param_name: str) -> Dict[str, Any]:
    """
    Get GUI-specific rendering hints for a parameter.

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        dict: GUI hints like widget_type, step size, etc.
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return {}

    param_info = schema['inputs'][param_name]
    return param_info.get('_gui_hints', {})


def should_show_parameter(schema: Dict, param_name: str,
                          current_params: Dict[str, Any]) -> bool:
    """
    Determine if a parameter should be displayed based on conditional logic.

    This enables context-sensitive parameter display (e.g., injury parameters
    only shown when injury is enabled).

    Args:
        schema: The ports schema
        param_name: Name of parameter
        current_params: Current parameter values

    Returns:
        bool: True if parameter should be shown
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return False

    param_info = schema['inputs'][param_name]

    # Check if there's a conditional display function
    if '_conditional_display' in param_info:
        condition_func = param_info['_conditional_display']
        try:
            return condition_func(current_params)
        except Exception:
            # If condition evaluation fails, default to showing
            return True

    return True


def get_value_mapping(schema: Dict, param_name: str) -> Optional[Dict]:
    """
    Get value mapping for categorical parameters.

    For parameters like binary choices, this maps internal values to
    user-friendly labels.

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        dict or None: {internal_value: display_label, ...}

    Example:
        {0.0: 'Linear Response', 0.1: 'Saturating Response'}
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return None

    param_info = schema['inputs'][param_name]
    return param_info.get('_value_mapping', None)


def get_biological_context(schema: Dict, param_name: str) -> Optional[str]:
    """
    Get biological meaning/context for a parameter.

    This provides high-level interpretation for biologists.

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        str or None: Biological meaning description
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return None

    param_info = schema['inputs'][param_name]
    return param_info.get('_biological_meaning', None)


# =============================================================================
# COMPREHENSIVE PARAMETER INFO EXTRACTOR
# =============================================================================

def get_full_parameter_info(schema: Dict, param_name: str) -> Dict[str, Any]:
    """
    Get complete information about a parameter in one call.

    This is useful for detailed parameter displays (tooltips, help panels, etc.)

    Args:
        schema: The ports schema
        param_name: Name of parameter

    Returns:
        dict: Complete parameter information
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return {}

    param_info = schema['inputs'][param_name].copy()

    # Add computed/extracted fields
    param_info['_relationships'] = get_parameter_relationships(schema, param_name)
    param_info['_validation_ranges'] = get_validation_ranges(schema, param_name)
    param_info['_display_name_mapped'] = get_display_name_mapping(schema).get(param_name, param_name)

    return param_info


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def validate_parameter_value(schema: Dict, param_name: str, value: Any) -> List[Dict]:
    """
    Validate a parameter value and return issues.

    Args:
        schema: The ports schema
        param_name: Name of parameter
        value: Value to validate

    Returns:
        list: [{'severity': str, 'message': str, 'reference': str}, ...]
    """
    if 'inputs' not in schema or param_name not in schema['inputs']:
        return [{'severity': 'ERROR', 'message': 'Parameter not found in schema'}]

    param_info = schema['inputs'][param_name]
    issues = []

    # Type checking
    expected_type = type(param_info['_default'])
    if not isinstance(value, expected_type):
        issues.append({
            'severity': 'ERROR',
            'message': f'Expected {expected_type.__name__}, got {type(value).__name__}'
        })
        return issues  # Stop further validation if type is wrong

    # Physiological range check
    if '_physiological_range' in param_info:
        min_val, max_val = param_info['_physiological_range']
        if value < min_val or value > max_val:
            ref = param_info.get('_reference_paper', {}).get('source', 'N/A')
            issues.append({
                'severity': 'WARNING',
                'message': f'Value {value} outside physiological range [{min_val}, {max_val}]',
                'reference': ref
            })

    # Mathematical stability check
    if '_mathematical_range' in param_info:
        min_val, max_val = param_info['_mathematical_range']
        if value < min_val or value > max_val:
            issues.append({
                'severity': 'ERROR',
                'message': f'Value {value} outside stable range [{min_val}, {max_val}]. Simulation may fail!'
            })

    # Warning threshold check
    if '_warning_threshold' in param_info:
        threshold = param_info['_warning_threshold']
        if value > threshold:
            issues.append({
                'severity': 'WARNING',
                'message': f'Value exceeds recommended threshold of {threshold}'
            })

    return issues


def validate_parameter_set(schema: Dict, params: Dict[str, Any]) -> Dict[str, List[Dict]]:
    """
    Validate entire parameter set.

    Args:
        schema: The ports schema
        params: Dictionary of parameter values

    Returns:
        dict: {param_name: [issues], ...}
    """
    all_issues = {}

    for param_name, value in params.items():
        issues = validate_parameter_value(schema, param_name, value)
        if issues:
            all_issues[param_name] = issues

    # Add cross-parameter validation here if needed
    # Example: Check if related parameters are consistent

    return all_issues


# =============================================================================
# EXPORT/IMPORT HELPERS
# =============================================================================

def schema_to_json_serializable(schema: Dict) -> Dict:
    """
    Convert schema to JSON-serializable format.

    Removes non-serializable objects like functions.

    Args:
        schema: The ports schema

    Returns:
        dict: JSON-serializable version of schema
    """
    import json
    import copy

    schema_copy = copy.deepcopy(schema)

    def remove_non_serializable(obj):
        """Recursively remove non-serializable items."""
        if isinstance(obj, dict):
            return {k: remove_non_serializable(v) for k, v in obj.items()
                    if not callable(v) and not k.startswith('_conditional')}
        elif isinstance(obj, (list, tuple)):
            return [remove_non_serializable(item) for item in obj]
        else:
            return obj

    return remove_non_serializable(schema_copy)


def extract_parameter_documentation(schema: Dict, output_format: str = 'markdown') -> str:
    """
    Generate documentation from schema.

    Args:
        schema: The ports schema
        output_format: 'markdown', 'html', or 'latex'

    Returns:
        str: Formatted documentation
    """
    if output_format != 'markdown':
        raise NotImplementedError(f"Format {output_format} not yet implemented")

    doc = "# Angiogenesis Model Parameters\n\n"

    structure = get_parameter_structure(schema)

    for tab_name, groups in structure.items():
        doc += f"## {tab_name}\n\n"

        for group_name, params in groups.items():
            doc += f"### {group_name}\n\n"

            for param_name, description in params.items():
                param_info = schema['inputs'][param_name]

                doc += f"#### `{param_name}` - {param_info.get('_display_name', param_name)}\n\n"
                doc += f"{description}\n\n"

                # Add details
                if '_unit' in param_info:
                    doc += f"- **Unit**: {param_info['_unit']}\n"
                if '_physiological_range' in param_info:
                    r = param_info['_physiological_range']
                    doc += f"- **Physiological Range**: [{r[0]}, {r[1]}]\n"
                if '_default' in param_info:
                    doc += f"- **Default**: {param_info['_default']}\n"

                # Add reference
                if '_reference_paper' in param_info:
                    ref = param_info['_reference_paper']
                    doc += f"- **Reference**: {ref.get('source', 'N/A')}\n"
                    if 'doi' in ref and ref['doi']:
                        doc += f"  - DOI: [{ref['doi']}](https://doi.org/{ref['doi']})\n"

                doc += "\n"

    return doc
