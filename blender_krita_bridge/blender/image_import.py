"""Create camera-aligned image planes (renderable) for the Krita -> Blender return path.

The export rendered the Grease Pencil object from the scene camera into a
``W x H`` image. Krita returns transparent PNGs of exactly the same size, so to
make the painting land **exactly over the GP outline** we place each PNG on a
plane that occupies the camera's view rectangle at the GP object's depth.
"""

from __future__ import annotations

import os
import shutil

import bpy
from mathutils import Euler, Matrix, Vector


def _preload_image(img):
    """Force an image's pixels into memory (and best-effort GPU upload).

    ``bpy.data.images.load`` reads only the file header — the pixels are decoded
    lazily on first use, which is the ~0.5 s hitch the first time a keyframe's
    texture is shown. Preloading at import time makes every keyframe switch
    instant instead of stalling once per texture.
    """
    try:
        if not img.has_data:
            img.pixels[:]  # forces the file read + decode into Blender's buffer
    except Exception:  # noqa: BLE001
        pass
    try:
        img.gl_load()  # best-effort GPU texture upload (needs an active GL context)
    except Exception:  # noqa: BLE001
        pass


def _load_image(path):
    """Load an image and pre-warm it (see ``_preload_image``)."""
    img = bpy.data.images.load(path)
    _preload_image(img)
    return img


def _refresh_view_layer(scene):
    """Force object transforms to be evaluated (matrix_world can be stale)."""
    try:
        view_layer = bpy.context.view_layer
    except Exception:  # noqa: BLE001
        view_layer = None
    if view_layer is None and scene.view_layers:
        view_layer = scene.view_layers[0]
    if view_layer is not None:
        view_layer.update()


def camera_view_rect(scene, target_obj):
    """Return the world-space rectangle the camera sees at ``target_obj``'s depth.

    Returns ``(center, right, up, width, height)`` where ``right``/``up`` are
    world unit vectors along the camera's local X/Y axes.
    """
    _refresh_view_layer(scene)
    cam_obj = scene.camera
    cam = cam_obj.data
    cam_mat = cam_obj.matrix_world

    cam_loc = cam_mat.translation
    right = cam_mat.col[0].xyz.normalized()
    up = cam_mat.col[1].xyz.normalized()
    back = cam_mat.col[2].xyz.normalized()  # camera local +Z points away from the scene
    forward = -back

    target = target_obj.matrix_world.translation
    depth = (target - cam_loc).dot(forward)
    if depth <= 1e-6:
        depth = 1.0  # degenerate: fall back to 1 unit in front of the camera

    # Use the camera's own view frame (accounts for sensor fit + render aspect).
    # The frame corners are given at some distance along -Z; scale their x/y
    # extents to `depth`.
    frame = cam.view_frame(scene=scene)
    z_dist = abs(frame[0].z)
    if z_dist < 1e-6:
        z_dist = 1.0
    xs = [v.x for v in frame]
    ys = [v.y for v in frame]
    width = (max(xs) - min(xs)) * depth / z_dist
    height = (max(ys) - min(ys)) * depth / z_dist

    center = cam_loc + forward * depth
    return center, right, up, width, height


def _link_or_copy(src, dst):
    """Copy ``src`` to ``dst`` as a hard link when possible (zero extra disk
    space on NTFS), falling back to a real copy. Overwrites an existing ``dst``
    and tolerates ``src``/``dst`` being the same file (re-send case)."""
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    try:
        os.remove(dst)
    except OSError:
        pass
    try:
        os.link(src, dst)
    except OSError:
        try:
            shutil.copyfile(src, dst)
        except shutil.SameFileError:
            pass


def build_sequence_files(keyframes, end_frame, seq_dir):
    """Write a contiguous ``frame_XXXX.png`` sequence with hold fills.

    ``keyframes`` = sorted ``[{frame, file}]``. Frames between keyframes reuse
    the previous keyframe's file (hold) so the sparse Krita keyframes play at
    the correct timeline positions via the image sequence's auto-advance.
    Returns ``(first_path, file_count, first_frame, markers)`` where ``markers``
    = ``[(timeline_frame, file_number)]`` for each real keyframe (used to place
    Dope Sheet keyframes).
    """
    keyframes = sorted(keyframes, key=lambda k: int(k.get("frame", 0)))
    by_num = {int(k.get("frame", 0)): k["file"] for k in keyframes}
    nums = sorted(by_num)
    first_frame = nums[0]
    # Start fresh each send (a previous send may have left hard-linked files).
    if os.path.isdir(seq_dir):
        shutil.rmtree(seq_dir, ignore_errors=True)
    os.makedirs(seq_dir, exist_ok=True)
    kf_idx = 0
    count = 0
    first_path = None
    markers = []
    for f in range(first_frame, end_frame + 1):
        while kf_idx + 1 < len(nums) and nums[kf_idx + 1] <= f:
            kf_idx += 1
        count += 1
        dst = os.path.join(seq_dir, f"frame_{count:04d}.png")
        _link_or_copy(by_num[nums[kf_idx]], dst)
        if first_path is None:
            first_path = dst
        if nums[kf_idx] == f:
            markers.append((f, count))
    return first_path, count, first_frame, markers


def _set_constant_interpolation(nt, data_path):
    """Set CONSTANT interpolation on every keyframe of ``data_path`` (holds each
    frame until the next keyframe — limited-animation style)."""
    ad = nt.animation_data
    if not ad or not ad.action:
        return
    action = ad.action
    # Blender 5.x layered actions.
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    if fc.data_path == data_path:
                        for kp in fc.keyframe_points:
                            kp.interpolation = "CONSTANT"
    # Blender 4.x / legacy flat actions.
    for fc in getattr(action, "fcurves", []):
        if fc.data_path == data_path:
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"


def _add_frame_switch_driver(nt, mix_node, obj, factor_index):
    """Drive a Mix factor from ``obj['bridge_frame']``.

    The factor is 1 when ``bridge_frame > factor_index`` (i.e. the chain has
    switched past this Mix) and 0 otherwise — so the active texture is the one
    whose index equals ``bridge_frame``.
    """
    fc = nt.driver_add(f'nodes["{mix_node.name}"].inputs[0].default_value')
    driver = fc.driver
    var = driver.variables.new()
    var.name = "bf"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = obj
    var.targets[0].data_path = '["bridge_frame"]'
    driver.expression = f"min(max(bf - {factor_index}, 0.0), 1.0)"
    return driver


def _socket(node, kind, identifier):
    """Find a node socket by RNA identifier (Mix nodes repeat names like 'A')."""
    coll = node.inputs if kind == "input" else node.outputs
    for s in coll:
        if s.identifier == identifier:
            return s
    raise KeyError(identifier)


def create_image_plane(
    scene, image_path: str, target_obj, name: str, z_offset: float = 0.0, collection=None
):
    """Create a renderable camera-aligned plane textured with a SINGLE image.

    ``z_offset`` shifts the plane along the camera's forward axis (used to stack
    several layers without z-fighting). ``collection`` is the collection to link
    into (defaults to the target object's collection).
    """
    image = _load_image(image_path)
    return _build_plane(scene, image, target_obj, name, z_offset, collection)[0]


def _build_single_material(name, image):
    """Build an unlit emission + transparent material textured with ``image``."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.blend_method = "BLEND"
    material.use_transparent_shadow = False
    material.use_backface_culling_shadow = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for n in list(nodes):
        if n.type == "BSDF_PRINCIPLED":
            nodes.remove(n)
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    emission = nodes.new("ShaderNodeEmission")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    out = nodes.get("Material Output") or nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return material


def _build_sequence_material(obj, name, keyframes):
    """Build the mix-shader material (one texture per keyframe + drivers)."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.blend_method = "BLEND"
    material.use_transparent_shadow = False
    material.use_backface_culling_shadow = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nt = material.node_tree
    # Drop the default Principled BSDF (we use unlit emission) — keep the graph
    # clean so the per-frame texture nodes are easy to read.
    for n in list(nodes):
        if n.type == "BSDF_PRINCIPLED":
            nodes.remove(n)

    row_spacing = 260.0
    tex_nodes = []
    for i, k in enumerate(keyframes):
        frame = int(k.get("frame", 0))
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = _load_image(k["file"])
        tex.name = f"Frame_{frame:04d}"
        tex.label = f"Frame {frame}"
        tex.location = (0.0, -i * row_spacing)
        # Stable per-keyframe identity: lets us rename the node when the user
        # moves its bridge_frame keyframe (the frame number is derived, not fixed).
        tex["bridge_index"] = i + 1
        tex_nodes.append(tex)

    color_sock = tex_nodes[0].outputs["Color"]
    alpha_sock = tex_nodes[0].outputs["Alpha"]
    for i in range(1, len(tex_nodes)):
        frame = int(keyframes[i].get("frame", 0))
        # Color mix (RGBA).
        mix_c = nodes.new("ShaderNodeMix")
        mix_c.data_type = "RGBA"
        mix_c.name = f"Switch_{frame:04d}"
        mix_c.label = f"-> {frame}"
        mix_c.location = (420.0, -i * row_spacing + 80.0)
        links.new(color_sock, _socket(mix_c, "input", "A_Color"))
        links.new(tex_nodes[i].outputs["Color"], _socket(mix_c, "input", "B_Color"))
        color_sock = _socket(mix_c, "output", "Result_Color")
        # Alpha mix (FLOAT).
        mix_a = nodes.new("ShaderNodeMix")
        mix_a.data_type = "FLOAT"
        mix_a.location = (420.0, -i * row_spacing - 80.0)
        links.new(alpha_sock, _socket(mix_a, "input", "A_Float"))
        links.new(tex_nodes[i].outputs["Alpha"], _socket(mix_a, "input", "B_Float"))
        alpha_sock = _socket(mix_a, "output", "Result_Float")
        # Drivers: both factors switch together based on bridge_frame.
        _add_frame_switch_driver(nt, mix_c, obj, i)
        _add_frame_switch_driver(nt, mix_a, obj, i)

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (840.0, 0.0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (840.0, -160.0)
    mix_shader = nodes.new("ShaderNodeMixShader")
    mix_shader.location = (1000.0, -80.0)
    out = nodes.get("Material Output") or nodes.new("ShaderNodeOutputMaterial")
    out.location = (1200.0, -80.0)
    links.new(color_sock, emission.inputs["Color"])
    links.new(alpha_sock, mix_shader.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix_shader.inputs[1])
    links.new(emission.outputs["Emission"], mix_shader.inputs[2])
    links.new(mix_shader.outputs["Shader"], out.inputs["Surface"])
    return material


def _set_bridge_frame_keyframes(obj, keyframes):
    obj["bridge_frame"] = 1
    for j, k in enumerate(keyframes, start=1):
        obj["bridge_frame"] = j
        obj.keyframe_insert(data_path='["bridge_frame"]', frame=int(k.get("frame", 0)))
    _set_constant_interpolation(obj, '["bridge_frame"]')
    obj["bridge_frames"] = [int(k.get("frame", 0)) for k in keyframes]


def _clear_bridge_frame(obj):
    """Remove only the bridge_frame FCurve (keeps other object keyframes)."""
    ad = obj.animation_data
    if not ad or not ad.action:
        return
    for layer in ad.action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for bag in strip.channelbags:
                for fc in list(bag.fcurves):
                    if fc.data_path == '["bridge_frame"]':
                        bag.fcurves.remove(fc)


def update_plane_textures(obj, keyframes):
    """Replace an existing image plane's material + bridge_frame in place.

    Keeps the object's transform/modifiers (parallax/rotation keyframes are
    preserved); only the image texture + animation markers change.
    """
    keyframes = sorted(keyframes, key=lambda k: int(k.get("frame", 0)))
    if not keyframes:
        return obj
    _clear_bridge_frame(obj)
    if len(keyframes) < 2:
        image = _load_image(keyframes[0]["file"])
        material = _build_single_material(obj.name, image)
        if "bridge_frame" in obj:
            del obj["bridge_frame"]
    else:
        material = _build_sequence_material(obj, obj.name, keyframes)
        _set_bridge_frame_keyframes(obj, keyframes)
    old = list(obj.data.materials)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for m in old:
        if m.users == 0:
            bpy.data.materials.remove(m)
    return obj


def create_image_plane_sequence(
    scene,
    keyframes,
    end_frame,
    seq_dir,
    target_obj,
    name: str,
    z_offset: float = 0.0,
    collection=None,
):
    """Create a camera-aligned plane that plays an animated image sequence.

    One texture node is created per keyframe (arranged vertically like an
    animation sheet and labelled with its frame number), mixed together by a
    chain of Mix nodes. A single keyframed ``bridge_frame`` property (CONSTANT
    interpolation) drives the Mix factors, so the keyframes are REAL and
    editable: moving a keyframe moves when the image switches.

    ``keyframes`` = sorted ``[{frame, file}]`` (the Krita keyframes).
    """
    keyframes = sorted(keyframes, key=lambda k: int(k.get("frame", 0)))
    if len(keyframes) < 2:
        if keyframes:
            return create_image_plane(
                scene, keyframes[0]["file"], target_obj, name, z_offset, collection
            )
        return None

    center, right, up, width, height = camera_view_rect(scene, target_obj)

    # --- Plane mesh + transform (same as _build_plane) ---
    mesh = bpy.data.meshes.new(name)
    verts = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    uv = mesh.uv_layers.new(name="UV")
    uv.data[0].uv = (0.0, 1.0)
    uv.data[1].uv = (1.0, 1.0)
    uv.data[2].uv = (1.0, 0.0)
    uv.data[3].uv = (0.0, 0.0)

    obj = bpy.data.objects.new(name, mesh)
    back = scene.camera.matrix_world.col[2].xyz.normalized()
    forward = -back
    basis = Matrix((right, -up, -back)).to_3x3().transposed()
    obj.rotation_euler = basis.to_euler()
    obj.scale = (width, height, 1.0)
    obj.location = center + forward * z_offset
    obj.visible_shadow = False

    material = _build_sequence_material(obj, name, keyframes)
    mesh.materials.append(material)

    if collection is None:
        collection = (target_obj.users_collection or [None])[0] or scene.collection
    collection.objects.link(obj)

    _set_bridge_frame_keyframes(obj, keyframes)
    return obj


def _bridge_frame_points(obj):
    """Return sorted [(frame, value)] from the bridge_frame FCurve."""
    points = []
    ad = obj.animation_data
    if not ad or not ad.action:
        return points
    for layer in ad.action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    if fc.data_path == '["bridge_frame"]':
                        for kp in fc.keyframe_points:
                            points.append((int(kp.co[0]), int(kp.co[1])))
    points.sort()
    return points


def sync_bridge_node_labels(obj):
    """Rename the per-keyframe texture nodes to match the bridge_frame keyframes.

    Called when the user moves a keyframe: the node labels then reflect the new
    timeline frames (so `Frame 2` moved to frame 4 becomes `Frame 4`).
    """
    points = _bridge_frame_points(obj)
    if not points:
        return
    frames = [f for f, _ in points]
    if frames == list(obj.get("bridge_frames", [])):
        return
    obj["bridge_frames"] = frames
    if not obj.data or not obj.data.materials:
        return
    mat = obj.data.materials[0]
    if not mat.use_nodes:
        return
    by_value = {v: f for f, v in points}
    for node in mat.node_tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        idx = node.get("bridge_index")
        if idx is None:
            continue
        frame = by_value.get(int(idx))
        if frame is None:
            continue
        new_name = f"Frame_{frame:04d}"
        if new_name != node.name and new_name not in mat.node_tree.nodes:
            node.name = new_name
        node.label = f"Frame {frame}"


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    """Sync node labels when a bridge_frame keyframe is moved.

    ``@persistent`` keeps this handler registered across File > New/Open, which
    otherwise removes it (so node labels would stop syncing after a file load).
    """
    try:
        for update in depsgraph.updates:
            obj = update.id
            if isinstance(obj, bpy.types.Object) and "bridge_frame" in obj:
                sync_bridge_node_labels(obj)
    except Exception as exc:  # noqa: BLE001
        print("BRIDGE: depsgraph sync error:", type(exc).__name__, exc)


def register_handler():
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister_handler():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)


def _build_plane(scene, image, target_obj, name: str, z_offset: float = 0.0, collection=None):
    """Shared core: build the camera-aligned textured plane. Returns (obj, tex_node)."""
    center, right, up, width, height = camera_view_rect(scene, target_obj)
    # Keep the default sRGB color space: the PNGs are normal sRGB artwork, and
    # the scene's own color management should apply (same as importing a texture).

    mesh = bpy.data.meshes.new(name)
    verts = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    uv = mesh.uv_layers.new(name="UV")
    # The plane's local +Y maps to camera "down" (see rotation below), so V is
    # inverted to keep the image upright.
    uv.data[0].uv = (0.0, 1.0)
    uv.data[1].uv = (1.0, 1.0)
    uv.data[2].uv = (1.0, 0.0)
    uv.data[3].uv = (0.0, 0.0)

    obj = bpy.data.objects.new(name, mesh)

    # Proper (reflection-free) rotation: local X -> camera right, local Y -> -up
    # (so the +Z normal faces back toward the camera), local Z -> forward.
    back = scene.camera.matrix_world.col[2].xyz.normalized()
    forward = -back
    basis = Matrix((right, -up, -back)).to_3x3().transposed()
    obj.rotation_euler = basis.to_euler()
    obj.scale = (width, height, 1.0)
    obj.location = center + forward * z_offset
    # Never cast shadows (the flat 2D art must not darken/block the scene).
    obj.visible_shadow = False

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.blend_method = "BLEND"
    # Transparent material: disable transparent shadows + backface shadow culling
    # so the plane casts no shadow at all (EEVEE).
    material.use_transparent_shadow = False
    material.use_backface_culling_shadow = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    # Unlit (emission) so the 2D artwork reproduces its colors flatly, mixed
    # with transparency driven by the image alpha.
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    emission = nodes.new("ShaderNodeEmission")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    out = nodes.get("Material Output") or nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    mesh.materials.append(material)

    if collection is None:
        collection = (target_obj.users_collection or [None])[0] or scene.collection
    collection.objects.link(obj)
    return obj, tex


def apply_layer_transform(plane, target_obj, transform_info):
    """Apply a captured GP layer transform to an image plane.

    The plane's base (camera-aligned) transform reproduces the UNtransformed
    drawing — the export renders with layer transforms zeroed, so the PNG has
    no baked position. Conjugating the layer's local transform by the GP
    object's world matrix gives the world-space delta that moves/rotates/scales
    the plane so it lands where the layer was (editable object transform).
    """
    if not transform_info:
        return plane

    keyframes = transform_info.get("keyframes") or []
    # Reconstruct the plane's base world matrix from its explicit transform
    # (matrix_world can be stale right after creation, before a depsgraph eval).
    base = Matrix.LocRotScale(plane.location, plane.rotation_euler, plane.scale)

    def matrix_for(t, r, s):
        local = Matrix.LocRotScale(Vector(t), Euler(r), Vector(s))
        delta = target_obj.matrix_world @ local @ target_obj.matrix_world.inverted()
        return delta @ base

    if not keyframes:
        plane.matrix_world = matrix_for(
            transform_info["translation"],
            transform_info["rotation"],
            transform_info["scale"],
        )
        return plane

    # Animated transform: keyframe the plane at every transform keyframe.
    # (bridge_frame keyframes use a different data_path, so they don't clash.)
    for kf in keyframes:
        frame = int(kf.get("frame", 1))
        plane.matrix_world = matrix_for(
            kf["translation"], kf["rotation"], kf["scale"]
        )
        plane.keyframe_insert(data_path="location", frame=frame)
        plane.keyframe_insert(data_path="rotation_euler", frame=frame)
        plane.keyframe_insert(data_path="scale", frame=frame)
    # The layer's transform keyframes are CONSTANT holds (limited-animation);
    # mirror that on the plane so it reproduces the same stepped motion.
    for data_path in ("location", "rotation_euler", "scale"):
        _set_constant_interpolation(plane, data_path)
    return plane
