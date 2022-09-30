from converter import artboard, group, oval, page, rectangle, shape_path, polygon, star, \
    shape_group, text, slice

CONVERTERS = {
    'CANVAS': page.convert,
    'ARTBOARD': artboard.convert,
    'GROUP': group.convert,
    'ROUNDED_RECTANGLE': rectangle.convert,
    'ELLIPSE': oval.convert,
    'VECTOR': shape_path.convert,
    'STAR': star.convert,
    'REGULAR_POLYGON': polygon.convert,
    'TEXT': text.convert,
    'BOOLEAN_OPERATION': shape_group.convert,
    'LINE': shape_path.convert_line,
    'SLICE': slice.convert
    # 'COMPONENT': lambda a, b: instance.convert(a, b, components),
    # 'INSTANCE': lambda a, b: instance.convert(a, b, components),
}

POST_PROCESSING = {
    'BOOLEAN_OPERATION': shape_group.post_process,
}


def convert_node(figma_node, indexed_components):
    name = figma_node['name']
    type_ = get_node_type(figma_node)
    print(f'{type_}: {name}')

    sketch_item = CONVERTERS[type_](figma_node, indexed_components)

    children = [convert_node(child, indexed_components) for child in
                figma_node.get('children', [])]
    sketch_item['layers'] = children

    post_process = POST_PROCESSING.get(type_)
    if post_process:
        post_process(figma_node, sketch_item)

    return sketch_item


def get_node_type(figma_node):
    match figma_node['type']:
        case 'FRAME':
            if figma_node['resizeToFit']:
                node_type = 'GROUP'
            else:
                node_type = 'ARTBOARD'
        case type_:
            node_type = type_

    return node_type


def find_shared_style(figma_node, indexed_components):
    match figma_node:
        case {'inheritFillStyleID': shared_style}:
            node_id = (shared_style['sessionID'], shared_style['localID'])
            return indexed_components[node_id]
        case _:
            return {}
