from . import base, group
import utils
from .context import context
import copy
from sketchformat.style import Style


def convert(figma_instance):
    all_overrides = get_all_overrides(figma_instance)
    sketch_overrides = convert_overrides(all_overrides)

    if sketch_overrides is None:
        # Modify Figma tree in place, with the detached symbol subtree
        detach_symbol(figma_instance, all_overrides, figma_instance['derivedSymbolData'])
        return group.convert(figma_instance)
    else:
        obj = {
            **base.base_shape(figma_instance),
            '_class': 'symbolInstance',
            'symbolID': utils.gen_object_id(figma_instance['symbolData']['symbolID']),
            'overrideValues': sketch_overrides,
            'preservesSpaceWhenHidden': False,
            'scale': 1,
        }
        # Replace style
        obj['style'] = Style(do_objectID=utils.gen_object_id(figma_instance['guid'], b'style'))

        return obj


def master_instance(figma_symbol):
    obj = {
        **base.base_shape(figma_symbol),
        '_class': 'symbolInstance',
        'do_objectID': utils.gen_object_id(figma_symbol['guid'], b'master_instance'),
        'symbolID': utils.gen_object_id(figma_symbol['guid']),
        'preservesSpaceWhenHidden': False,
        'overrideValues': [],
        'scale': 1
    }

    # Replace style
    obj['style'] = Style(
        do_objectID=utils.gen_object_id(figma_symbol['guid'], b'master_instance_style'))

    return obj


def convert_overrides(all_overrides):
    sketch_overrides = []
    for override in all_overrides:
        sk = convert_override(override)
        if sk is None:
            # Something cannot be converted, trigger dettach code
            return None
        else:
            sketch_overrides += sk

    return sketch_overrides


def get_all_overrides(figma_instance):
    """Gets all overrides of a symbol, including component assignments"""

    # Convert top-level properties to overrides
    figma_master = context.figma_node(figma_instance['symbolData']['symbolID'])
    all_overrides = convert_properties_to_overrides(figma_master, figma_instance.get('componentPropAssignments', []))

    # Sort overrides by length of path. This ensures top level overrides are processed before nested ones
    # which is required because a top override may change the symbol instance that is used by child overrides
    for override in sorted(figma_instance['symbolData']['symbolOverrides'], key=lambda x: len(x['guidPath']['guids'])):
        guid_path = override['guidPath']['guids']
        new_override = {'guidPath': override['guidPath']}
        for prop, value in override.items():
            if prop == 'componentPropAssignments':
                nested_master = find_symbol_master(figma_master, guid_path, all_overrides)
                all_overrides += convert_properties_to_overrides(nested_master, value, guid_path)
            else:
                new_override[prop] = value

        all_overrides.append(new_override)

    return all_overrides


def convert_override(override):
    sketch_overrides = []

    # Convert uuids in the path from top symbol to child instance
    sketch_path = [utils.gen_object_id(guid) for guid in override['guidPath']['guids']]
    sketch_path_str = '/'.join(sketch_path)

    for prop, value in override.items():
        if prop == 'guidPath':
            continue
        if prop == 'textData':
            # Text override.
            if 'styleOverrideTable' in value:
                # Sketch does not support multiple styles in text overrides -> detach
                print(f"Unsupported override: text with mixed styles. Will detach")
                return None

            sketch_overrides.append({
                '_class': 'overrideValue',
                'overrideName': f'{sketch_path_str}_stringValue',
                'value': value['characters']
            })
        elif prop == 'overriddenSymbolID':
            sketch_overrides.append({
                '_class': 'overrideValue',
                'overrideName': f'{sketch_path_str}_symbolID',
                'value': utils.gen_object_id(value)
            })
        elif prop == 'componentPropAssignments':
            sketch_overrides += [convert_prop_assigment(figma_master, prop, sketch_path) for prop in value]
        elif prop in ['size', 'pluginData']:
            pass
        else:
            # Unknown override
            print(f"Unsupported override: {prop}. Will detach")
            return None

    return sketch_overrides


def find_symbol_master(root_symbol, guid_path, overrides):
    current_symbol = root_symbol
    path = []
    for guid in guid_path:
        path.append(guid)
        # See if we have overriden the symbol_id
        symbol_id = [o['overriddenSymbolID'] for o in overrides if o['guidPath']['guids'] == path and 'overriddenSymbolID' in o]
        if symbol_id:
            symbol_id = symbol_id[0]
        else:
            # Otherwise, find the instance
            instance = context.figma_node(guid)
            symbol_id = instance['symbolData']['symbolID']

        current_symbol = context.figma_node(symbol_id)

    return current_symbol


def convert_properties_to_overrides(figma_master, properties, guid_path=[]):
    """Convert Figma property assigments to Figma overrides.
       This makes it easier to work with them in a unified way."""
    overrides = []

    for prop in properties:
        for (ref_prop, ref_guid) in find_refs(figma_master, prop['defID']):
            if ref_prop['componentPropNodeField'] == 'OVERRIDDEN_SYMBOL_ID':
                override = { 'overriddenSymbolID': prop['value']['guidValue'] }
            elif ref_prop['componentPropNodeField'] == 'TEXT_DATA':
                override = {'textData': prop['value']['textValue']}
            elif ref_prop['componentPropNodeField'] == 'VISIBLE':
                override = {'visible': prop['value']['boolValue']}
            else: # INHERIT_FILL_STYLE_ID
                raise Exception(f"Unexpected property {ref_prop['componentPropNodeField']}")

            overrides.append({
                **override,
                "guidPath": {
                    "guids": guid_path + [ref_guid]
                }
            })

    return overrides


def find_refs(node, ref_id):
    """Find all usages of a property in a symbol, recursively"""
    refs = [(ref, node['guid']) for ref in node.get('componentPropRefs', []) if
            ref['defID'] == ref_id and not ref['isDeleted']]

    for ch in node['children']:
        refs += find_refs(ch, ref_id)

    return refs


def detach_symbol(figma_instance, all_overrides, derived_symbol_data, path=[]):
    # Find symbol master
    figma_master = context.figma_node(figma_instance['symbolData']['symbolID'])
    detached_children = copy.deepcopy(figma_master['children'], {})

    # Recalculate size
    derived = [d for d in derived_symbol_data if d['guidPath']['guids'] == path]
    if derived:
        figma_instance['size'] = derived[0]['size']
        figma_instance['transform'] = derived[0]['transform']

    # Apply overrides to children
    for c in detached_children:
        apply_overrides(c, figma_instance['guid'], all_overrides, derived_symbol_data, path)

    figma_instance['children'] = detached_children


def apply_overrides(figma, instance_id, overrides, derived_symbol_data, path=[]):
    guid = figma['guid']

    # Apply overrides
    ov = [o for o in overrides if o['guidPath']['guids'] == path + [figma['guid']]]
    for o in ov:
        for k,v in o.items():
            if k == 'guidPath':
                continue
            elif k == 'overriddenSymbolID':
                figma['symbolData']['symbolID'] = v
            else:
                print(f"{k}={v}")
                figma[k] = v

    # Recalculate size
    derived = [d for d in derived_symbol_data if d['guidPath']['guids'] == path + [guid]]
    if derived:
        figma['size'] = derived[0]['size']
        figma['transform'] = derived[0]['transform']

    # Generate a unique ID by concatenating instance_id + node_id
    figma['guid'] = tuple(j for i in (instance_id, *path, guid) for j in i)

    # If it's an instance, dettach it. Otherwise, convert the children
    if figma['type'] == 'INSTANCE':
        figma['type'] = 'FRAME'
        detach_symbol(figma, overrides, derived_symbol_data, path + [guid])
    else:
        for c in figma['children']:
            apply_overrides(c, instance_id, derived_symbol_data, overrides)
