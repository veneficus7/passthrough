"""Panels and scene properties.

Milestone 1 adds the output location and the pass-setup button. Add-on
preferences (AE project dir, pixels per unit, RAM budget) belong to prefs.py
and arrive with a later milestone.
"""

import bpy

from . import (
    pass_spec,
    passes,
    prefs,
    scene_capture,
    scene_doctor,
    template_build,
    template_spec,
)


class PassthroughSceneSettings(bpy.types.PropertyGroup):
    """Per-scene Passthrough settings, reachable as ``scene.passthrough``."""

    output_root: bpy.props.StringProperty(
        name="Output Root",
        description="Folder that shot subfolders are written into",
        subtype="DIR_PATH",
        default="//renders",
    )
    shot_name: bpy.props.StringProperty(
        name="Shot Name",
        description="Subfolder for this shot; each pass gets a folder inside it",
        default="shot",
    )
    last_estimate: bpy.props.IntProperty(
        name="Last Estimate",
        description="Projected peak memory from the most recent scene check, in bytes",
        default=0,
    )


class PASSTHROUGH_PT_main(bpy.types.Panel):
    """Root Passthrough panel, hosted in Render Properties."""

    bl_idname = "PASSTHROUGH_PT_main"
    bl_label = "Passthrough"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.passthrough

        if not passes.is_eevee(context.scene.render.engine):
            layout.label(text="Passthrough targets EEVEE", icon="ERROR")

        col = layout.column()
        col.use_property_split = True
        col.prop(settings, "output_root")
        col.prop(settings, "shot_name")

        col = layout.column(align=True)
        col.operator(passes.PASSTHROUGH_OT_setup_passes.bl_idname, icon="NODETREE")
        col.operator(scene_capture.PASSTHROUGH_OT_export_jsx.bl_idname, icon="TEXT")

        col = layout.column(align=True)
        col.operator(
            scene_capture.PASSTHROUGH_OT_render_headless.bl_idname,
            text="Render Headless",
            icon="RENDER_ANIMATION",
        ).close_ui = False
        col.operator(
            scene_capture.PASSTHROUGH_OT_render_headless.bl_idname,
            text="Render and Quit Blender",
            icon="QUIT",
        ).close_ui = True
        col.label(text=f"Frames {context.scene.frame_start}-{context.scene.frame_end}")


class PASSTHROUGH_PT_passes(bpy.types.Panel):
    """Shows where each pass will be written, so the paths are checkable."""

    bl_idname = "PASSTHROUGH_PT_passes"
    bl_label = "Passes"
    bl_parent_id = "PASSTHROUGH_PT_main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        settings = context.scene.passthrough
        shot = pass_spec.sanitize_shot_name(settings.shot_name)
        col = self.layout.column(align=True)
        for spec in pass_spec.PASSES:
            row = col.row()
            row.label(text=spec.label)
            row.label(text=f"{spec.key}/{pass_spec.frame_filename(spec.key, 1)}")
        col.separator()
        col.label(text=pass_spec.shot_dir(settings.output_root, shot), icon="FILE_FOLDER")


class PASSTHROUGH_PT_doctor(bpy.types.Panel):
    """Projected memory cost, before committing to a long render."""

    bl_idname = "PASSTHROUGH_PT_doctor"
    bl_label = "Scene Doctor"
    bl_parent_id = "PASSTHROUGH_PT_main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.passthrough
        budget = prefs.memory_budget(context)

        col = layout.column(align=True)
        col.operator(scene_capture.PASSTHROUGH_OT_diagnose.bl_idname, icon="MEMORY")

        if settings.last_estimate:
            over = settings.last_estimate > budget
            box = layout.box()
            box.label(
                text=f"Projected {scene_doctor.format_bytes(settings.last_estimate)}",
                icon="ERROR" if over else "CHECKMARK",
            )
            box.label(text=f"Budget {scene_doctor.format_bytes(budget)}")
            if over:
                box.operator(scene_capture.PASSTHROUGH_OT_auto_fix.bl_idname, icon="MODIFIER")
        else:
            layout.label(text="Not checked yet")


class PASSTHROUGH_PT_templates(bpy.types.Panel):
    """Build a shot without touching Blender's node editors."""

    bl_idname = "PASSTHROUGH_PT_templates"
    bl_label = "Shot Templates"
    bl_parent_id = "PASSTHROUGH_PT_main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.passthrough

        layout.prop(settings, "template", text="")

        templates = template_spec.load_templates()
        template = templates.get(settings.template)
        if template is None:
            layout.label(text="No template selected", icon="ERROR")
            return

        layout.label(text=template.description)

        group = getattr(settings, template_build.group_name(template.key), None)
        if group is not None:
            column = layout.column()
            column.use_property_split = True
            for parameter in template.parameters:
                column.prop(group, parameter.key)

        layout.operator(template_build.PASSTHROUGH_OT_build_template.bl_idname, icon="SCENE_DATA")


_CLASSES = (
    PassthroughSceneSettings,
    PASSTHROUGH_PT_main,
    PASSTHROUGH_PT_templates,
    PASSTHROUGH_PT_passes,
    PASSTHROUGH_PT_doctor,
)


def attach_template_properties():
    """Give the scene settings one property per template, from the schemas.

    Done here rather than in the class body because the schemas are only read at
    registration, and the generated PropertyGroups have to exist first. Called
    before PassthroughSceneSettings is registered.
    """
    templates = template_spec.load_templates()
    annotations = PassthroughSceneSettings.__annotations__
    annotations["template"] = bpy.props.EnumProperty(
        name="Template",
        description="Shot template to build",
        items=list(template_spec.enum_items(templates)),
    )
    for key, group in template_build.PROPERTY_GROUPS.items():
        annotations[template_build.group_name(key)] = bpy.props.PointerProperty(type=group)


def register():
    attach_template_properties()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.passthrough = bpy.props.PointerProperty(type=PassthroughSceneSettings)


def unregister():
    del bpy.types.Scene.passthrough
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
