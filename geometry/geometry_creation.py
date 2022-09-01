"""Module for assisting with the creation of geometry objects"""
from typing import Optional, Tuple
import numpy as np
import meshio

import rigatoni

from .geometry_objects import AttributeInput, GeometryPatchInput

SIZES = {
    # in bytes
    "U8": 1,
    "U16": 2,
    "U32": 4,
    "U8VEC4": 4,
    "U16VEC2": 4,
    "VEC2": 8,
    "VEC3": 12,
    "VEC4": 16,
    "MAT3": 36,
    "MAT4": 64
}

FORMAT_MAP = {
        "U8": np.int8,
        "U16": np.int16,
        "U32": np.int32,
        "U8VEC4": np.int8,
        "U16VEC2": np.int16,
        "VEC2": np.single,
        "VEC3": np.single,
        "VEC4": np.single,
        "MAT3": np.single,
        "MAT4": np.single
    }

DEFAULT_POSITION = [0.0, 0.0, 0.0, 0.0]
DEFAULT_COLOR = [1.0, 1.0, 1.0, 1.0]
DEFAULT_ROTATION = [0.0, 0.0, 0.0, 0.0]
DEFAULT_SCALE = [1.0, 1.0, 1.0, 0.0]


def get_format(num_vertices: int) -> str:
    """Helper to get format that can accomadate number of vertices"""

    if num_vertices < 256:
        return 'U8'
    elif num_vertices < 65536:
        return 'U16'
    else:
        return 'U32'


def set_up_attributes(input: GeometryPatchInput):
    """Constructs attribute info from input lists"""

    # Add attribute info based on the input lists
    attribute_info = [] 
    position = AttributeInput(
        semantic = "POSITION",
        format = "VEC3",
        normalized = False,
    )
    attribute_info.append(position)

    if input.normals:
        normal = AttributeInput(
            semantic = "NORMAL",
            format = "VEC3",
            normalized = False,
        )
        attribute_info.append(normal)

    if input.tangents:
        tangent = AttributeInput(
            semantic = "TANGENT",
            format = "VEC3",
            normalized = False,
        )
        attribute_info.append(tangent)

    if input.textures:
        texture = AttributeInput(
            semantic = "TEXTURE",
            format = "U16VEC2",
            normalized = True,
        )
        attribute_info.append(texture)

    if input.colors:
        color = AttributeInput(
            semantic = "COLOR",
            format = "U8VEC4",
            normalized = True,
            )
        attribute_info.append(color)

    # Use input to get offsets
    offset = 0
    for attribute in attribute_info:
        attribute.offset = offset
        offset += SIZES[attribute.format]

    # Use final offset to get stride
    for attribute in attribute_info:
        attribute.stride = offset

    return attribute_info

            
def build_geometry_buffer(server: rigatoni.Server, name, input: GeometryPatchInput, 
    index_format: str, attribute_info: list[AttributeInput]) -> Tuple[rigatoni.Buffer, int]:

    # Build the buffer
    data = [x for x in [input.vertices, input.normals, input.tangents, input.textures, input.colors] if x]
    buffer_bytes = bytearray(0)
    points = zip(*data)
    for point in points:
        for info, attr in zip(point, attribute_info):

            attr_size = FORMAT_MAP[attr.format]
            new_bytes = np.array(info, dtype=attr_size).tobytes(order='C')
            buffer_bytes.extend(new_bytes)

    index_offset = len(buffer_bytes)
    index_bytes = np.array(input.indices, dtype=FORMAT_MAP[index_format]).tobytes(order='C')
    buffer_bytes.extend(index_bytes)

    size = len(buffer_bytes)
    if size > 1000:
        # TODO - uri bytes
        # raise Exception("TOO BIG")
        buffer = server.create_component(
            rigatoni.Buffer,
            name = name,
            size = size,
            inline_bytes = buffer_bytes
        )
        return buffer, index_offset
    else:
        buffer = server.create_component(
            rigatoni.Buffer,
            name = name,
            size = size,
            inline_bytes = buffer_bytes
        )
        return buffer, index_offset


def build_geometry_patch(server: rigatoni.Server, name: str, input: GeometryPatchInput):


    vert_count = len(input.vertices)
    index_count = len(input.indices) * len(input.indices[0])
    index_format = get_format(vert_count)            

    # Set up attributes with given lists
    attribute_info = set_up_attributes(input)

    # Build buffer with given lists
    buffer: rigatoni.Buffer
    buffer, index_offset = build_geometry_buffer(server, name, input, index_format, attribute_info)

    # Make buffer component
    buffer_view: rigatoni.BufferView = server.create_component(
        rigatoni.BufferView,
        name = name,
        source_buffer = buffer.id,
        type = "GEOMETRY",
        offset = 0, # What is this? cant always assume 0
        length = buffer.size
    )

    # Create attribute objects from buffer view and attribute info
    attributes = []
    for attribute in attribute_info:
        attr_obj = rigatoni.Attribute(view=buffer_view.id, **dict(attribute))
        attributes.append(attr_obj)

    # Make index to describe indices at end of buffer
    index = rigatoni.Index(
        view = buffer_view.id,
        count = index_count,
        offset = index_offset,
        format = index_format
    )

    # Finally create patch 
    patch = rigatoni.GeometryPatch(
        attributes = attributes, 
        vertex_count = vert_count, 
        indices = index, 
        type = input.index_type, 
        material = input.material
    )

    return patch


def build_instance_buffer(server, name, matrices) -> rigatoni.Buffer:
    """Build MAT4 Buffer"""
    
    buffer_bytes = np.array(matrices, dtype=np.single).tobytes(order='C')

    buffer = server.create_component(
        rigatoni.Buffer,
        name = f"Instance buffer for {name}",
        size = len(buffer_bytes),
        inline_bytes = buffer_bytes
    )

    #print(f"100th Instance: {np.frombuffer(buffer_bytes[6400:6464], dtype=np.single)}")

    return buffer


def build_entity(server: rigatoni.Server, geometry: rigatoni.Geometry, instances: rigatoni.Mat4=None):
    """Build Entity from Geometry
    
    Can specify instances here or add later with create_instances
    """

    name = geometry.name if geometry.name else None

    if instances:
        buffer = build_instance_buffer(server, name, instances)
        buffer_view = server.create_component(
            rigatoni.BufferView,
            name = f"Instance View for {name}",
            source_buffer = buffer.id,
            type = "UNK",
            offset = 0,
            length = buffer.size
        )
        instance = rigatoni.InstanceSource(view=buffer_view.id, stride=0, bb=None)
    else:
        instance = None

    rep = rigatoni.RenderRepresentation(mesh=geometry.id, instances=instance)

    entity = server.create_component(rigatoni.Entity, name=name, render_rep=rep)
    
    return entity


def padded(lst: list):
    lst = list(lst)
    if len(lst) < 4:
        lst += [0.0] * (4 - len(lst))
    return lst


def create_instances(
    positions: list[rigatoni.Vec3] = [], 
    colors: list[rigatoni.Vec4] = [], 
    rotations: list[rigatoni.Vec4] = [], 
    scales: list[rigatoni.Vec3] = []):
    """Create new instances for an entity
    
    All lists are optional and will be filled with defaults
    By default one instance is created at least
    Lists are padded out to 4 values
    """

    # If no inputs specified create one default instance
    if not (positions or colors or rotations or scales):
        positions = [DEFAULT_POSITION]

    # Use longest input as number of instances
    num_instances = max([len(l) for l in [positions, colors, rotations, scales]])

    # Build the matrices and extend
    instances = []
    for i in range(num_instances):
        position = padded(positions[i]) if i < len(positions) else DEFAULT_POSITION
        color = padded(colors[i]) if i < len(colors) else DEFAULT_COLOR
        rotation = padded(rotations[i]) if i < len(rotations) else DEFAULT_ROTATION
        scale = padded(scales[i]) if i < len(scales) else DEFAULT_SCALE
        instances.extend([position, color, rotation, scale])

    return instances


def update_entity(server: rigatoni.Server, entity: rigatoni.Entity, geometry: rigatoni.Geometry=None, instances: list=None):
    
    name = entity.name if entity.name else None

    # Get render rep and ensure entity is working with geometry
    old_rep = entity.render_rep
    if not old_rep:
        raise Exception("Entity isn't renderable")

    if geometry:
        mesh = geometry.id
    else:
        mesh = old_rep.mesh

    # Build new buffer / view for instances or use existing instances
    if instances:
        buffer = build_instance_buffer(server, name, instances)
        buffer_view = server.create_component(
            rigatoni.BufferView,
            name = f"Instance View for {name}",
            source_buffer = buffer.id,
            type = "UNK",
            offset = 0,
            length = buffer.size
        )
        instance = rigatoni.InstanceSource(view=buffer_view.id, stride=0, bb=None)
    else:
        instance = old_rep.instances

    # Create new render rep for entity and update entity
    rep = rigatoni.RenderRepresentation(mesh=mesh, instances=instance)
    entity.render_rep = rep
    entity = server.update_component(entity)

    # Clean up with deletes
    if instances:
        server.delete_component(server.components[old_rep.instances.view].source_buffer)
        server.delete_component(old_rep.instances.view)
    elif geometry:
        server.delete_component(old_rep.mesh)
    
    return entity


def add_instances(server: rigatoni.Server, entity: rigatoni.Entity, instances: list):
    
    try:
        rep = entity.render_rep
    except:
        raise Exception("Entity isn't renderable")

    if rep:
        old_view: rigatoni.BufferView = server.components[rep.instances.view]
        old_buffer: rigatoni.Buffer = server.components[old_view.source_buffer]
        old_instances = np.frombuffer(old_buffer.inline_bytes, dtype=np.single)
        print(f"Old instances from buffer: {old_instances}")
        combined = np.append(old_instances, instances)

    update_entity(server, entity, instances=combined.tolist())


def get_mesh_attr(mesh, attr: str):
    """Helper to get attribute from mesh object"""

    for cell in mesh.cells:
        if cell.type == attr:
            return cell.data.tolist()
    return None


def geometry_from_mesh(server: rigatoni.Server, file, material: rigatoni.Material, mesh_name: Optional[str]=None):
    
    # Create meshio mesh object to extract data from file
    mesh = meshio.read(file)
    vertices = mesh.points.tolist()
    # Need to check meshio key words for other attributes
    indices = get_mesh_attr(mesh, "triangle")
    normals = get_mesh_attr(mesh, "normal")
    tangents = get_mesh_attr(mesh, "tangent")
    textures = get_mesh_attr(mesh, "texture")
    colors = get_mesh_attr(mesh, "color")

    # Create patch / geometry for point geometry
    patches = []
    patch_info = GeometryPatchInput(
        vertices = vertices, 
        indices = indices, 
        index_type = "TRIANGLES",
        material = material.id,
        normals = normals,
        tangents = tangents,
        textures = textures,
        colors = colors)
    patches.append(build_geometry_patch(server, mesh_name, patch_info))
    geometry = server.create_component(rigatoni.Geometry, name=mesh_name, patches=patches)

    return geometry
    

def export_mesh(server: rigatoni.Server, geometry: rigatoni.Geometry, new_file_name: str):
    """Interface to export noodles geometry to mesh file"""

    points = []
    indices = []
    point_data = {}
    for patch in geometry.patches:

        # Extract info from patch
        index = patch.indices
        view: rigatoni.BufferView = server.get_component(index.view)
        bytes = server.get_component(view.source_buffer).inline_bytes

        # Get indicies
        raw_indices = np.frombuffer(bytes, dtype=FORMAT_MAP[index.format], count=index.count, offset=index.offset)
        grouped = [list(x) for x in zip(*(iter(raw_indices),) * 3)]
        indices.extend(grouped)

        # Get Attributes, positions and any others
        attribute_bytes  = bytes[:index.offset]

        i = 0
        while i < len(attribute_bytes):
            for attribute in patch.attributes:
                format = attribute.format
                current_chunk = attribute_bytes[i:i + SIZES[format]]
                attr_name = attribute.semantic
                attr_data = np.frombuffer(current_chunk, dtype=FORMAT_MAP[format]).tolist()
                i += SIZES[format]
                if attr_name == "POSITION":
                    points.append(attr_data)
                else:
                    point_data.setdefault(attr_name,[]).append(attr_data) 
            print(f"{i}/{len(attribute_bytes)}")

    mesh = meshio.Mesh(
        points,
        [("triangle", indices)],
        point_data = point_data
    )

    mesh.write(new_file_name)
