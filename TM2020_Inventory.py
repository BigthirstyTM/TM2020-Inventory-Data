bl_info = {
    "name": "Trackmania 2020 Inventory",
    "author": "BigthirstyTM & AI Assistant",
    "version": (5, 87),
    "blender": (5, 0, 0),
    "location": "View3D > Press Ctrl + Shift + I to open",
    "description": "TM2020 Style Inventory - Fixed UI Hitboxes & G-Key",
    "category": "Interface",
}

import bpy
import gpu
import json
import os
import blf
import re
import urllib.request
import zipfile
import io
import shutil
import math
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector, Euler, Matrix
from bpy.props import StringProperty, FloatVectorProperty, FloatProperty, EnumProperty, BoolProperty

# --- CONFIG & PATHS ---
BLOCKS_JSON_URL = "https://raw.githubusercontent.com/BigthirstyTM/TM2020-Inventory-Data/main/BlockInfoInventory.gbx.json"
ITEMS_JSON_URL = "https://raw.githubusercontent.com/BigthirstyTM/TM2020-Inventory-Data/main/ItemInventory.gbx.json"
ZIP_URL = "https://github.com/BigthirstyTM/TM2020-Inventory-Data/archive/refs/heads/main.zip"

CACHE_DIR = os.path.join(bpy.utils.user_resource('SCRIPTS'), "presets", "tm_inventory_cache")
ICONS_DIR = os.path.join(CACHE_DIR, "icons")
BLOCKS_JSON_FILE = os.path.join(CACHE_DIR, "blocks.json")
ITEMS_JSON_FILE = os.path.join(CACHE_DIR, "items.json")

# --- PREFERENCES ---
def update_theme(self, context):
    if self.theme_preset == 'DARK':
        self.ui_bg_color = (0.02, 0.02, 0.02, 0.95); self.ui_accent_color = (0.1, 0.1, 0.1, 1.0)
        self.ui_text_color = (1.0, 1.0, 1.0, 1.0); self.ghost_color = (0.2, 0.6, 1.0, 0.05); self.ghost_outline_color = (0.4, 0.8, 1.0, 1.0)
    elif self.theme_preset == 'LIGHT':
        self.ui_bg_color = (0.9, 0.9, 0.9, 0.95); self.ui_accent_color = (0.7, 0.7, 0.7, 1.0)
        self.ui_text_color = (0.05, 0.05, 0.05, 1.0); self.ghost_color = (1.0, 0.5, 0.0, 0.05); self.ghost_outline_color = (1.0, 0.4, 0.0, 1.0)
    elif self.theme_preset == 'CLASSIC':
        self.ui_bg_color = (0.01, 0.01, 0.01, 1.0); self.ui_accent_color = (0.0, 0.45, 0.2, 0.95)
        self.ui_text_color = (1.0, 1.0, 1.0, 1.0); self.ghost_color = (0.0, 1.0, 0.4, 0.05); self.ghost_outline_color = (0.2, 1.0, 0.4, 0.8)

class TM2020_Inventory_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    path_blocks: StringProperty(name="Blocks Path", default=r"C:\Users\PC\OpenplanetNext\Extract\GameData\Stadium\GameCtnBlockInfo\GameCtnBlockInfoClassic", subtype='DIR_PATH')
    path_items: StringProperty(name="Items Path", default=r"C:\Users\PC\OpenplanetNext\Extract\GameData\Stadium\Items", subtype='DIR_PATH')
    visible_only: BoolProperty(name="Visible part only", default=True)
    merge_objects: BoolProperty(name="Merge objects (Importer)", default=False)
    auto_join: BoolProperty(name="Auto-join meshes", default=True)
    lod: EnumProperty(name="LOD", default="highest", items=(("highest", "Highest", ""), ("lowest", "Lowest", ""), ("all", "All", "")))
    theme_preset: EnumProperty(name="Theme Preset", items=[('CLASSIC', "Classic TM", ""), ('DARK', "Deep Dark", ""), ('LIGHT', "Clean Light", "")], default='CLASSIC', update=update_theme)
    ui_bg_color: FloatVectorProperty(name="UI Background", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.01, 0.01, 0.01, 1.0))
    ui_accent_color: FloatVectorProperty(name="UI Accent (Bar)", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 0.45, 0.2, 0.95))
    ui_text_color: FloatVectorProperty(name="Text Color", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0))
    ghost_color: FloatVectorProperty(name="Ghost Fill", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.0, 1.0, 0.4, 0.05))
    ghost_outline_color: FloatVectorProperty(name="Ghost Outline", subtype='COLOR', size=4, min=0.0, max=1.0, default=(0.2, 1.0, 0.4, 0.8))
    ghost_outline_width: FloatProperty(name="Outline Width", default=2.0, min=0.5, max=10.0)

    def draw(self, context):
        layout = self.layout; row = layout.row()
        col1 = row.column(); box_p = col1.box(); box_p.label(text="Data Paths", icon='FILE_FOLDER'); box_p.prop(self, "path_blocks"); box_p.prop(self, "path_items")
        box_i = col1.box(); box_i.label(text="Import Settings", icon='IMPORT'); box_i.prop(self, "visible_only"); box_i.prop(self, "merge_objects"); box_i.prop(self, "auto_join"); box_i.prop(self, "lod")
        col2 = row.column(); box_a = col2.box(); box_a.label(text="Appearance", icon='RESTRICT_COLOR_ON'); box_a.prop(self, "theme_preset", text="Quick Theme")
        c = box_a.column(align=True); c.prop(self, "ui_bg_color"); c.prop(self, "ui_accent_color"); c.prop(self, "ui_text_color")
        box_g = col2.box(); box_g.label(text="Ghost Visuals", icon='GHOST_ENABLED'); c = box_g.column(align=True); c.prop(self, "ghost_color"); c.prop(self, "ghost_outline_color"); c.prop(self, "ghost_outline_width")

# --- MANAGER ---
class TM_Inventory_Manager:
    def __init__(self):
        self.block_roots = []; self.item_roots = []; self.icons = {} 
        self.active_rows = []; self.selected_indices = []; self.search_results = []
        self.selected_block_name = "None"; self.search_query = ""; self.is_searching = False
        self.loading_status = "IDLE"; self.current_mode = "BLOCKS"
        self.is_ghosting = False; self.ghost_pos = Vector((0, 0, 0))
        
        # New Rotation System (XYZ Euler)
        self.ghost_rotation_euler = Vector((0.0, 0.0, 0.0))
        
        self.ghost_z_offset = 0.0; self.active_item_name = ""
        self.ui_pos_x, self.ui_pos_y = 150, 200; self.ui_width = 830.0; self.base_width = 830.0; self.is_open = False
        self.copy_feedback_timer = 0; self.current_bar_width = 830.0
        self.active_preview_obj = None
        self.active_preview_colls = []
        self.is_hovering_help = False
        # Mesh-driven bounds for ghost drawing
        self.ghost_min = Vector((0, 0, 0)) 
        self.ghost_max = Vector((1, 1, 1))

    def start_load(self):
        if self.loading_status == "READY": return
        os.makedirs(ICONS_DIR, exist_ok=True)
        if not os.path.exists(BLOCKS_JSON_FILE) or not os.listdir(ICONS_DIR): self.download_all()
        self.load_from_cache()

    def download_all(self):
        try:
            with urllib.request.urlopen(BLOCKS_JSON_URL) as r:
                with open(BLOCKS_JSON_FILE, 'w', encoding='utf-8') as f: f.write(r.read().decode())
            with urllib.request.urlopen(ITEMS_JSON_URL) as r:
                with open(ITEMS_JSON_FILE, 'w', encoding='utf-8') as f: f.write(r.read().decode())
            with urllib.request.urlopen(ZIP_URL) as response:
                with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                    for m in z.namelist():
                        if m.lower().endswith(".png"):
                            fname = os.path.basename(m)
                            if fname:
                                with z.open(m) as s, open(os.path.join(ICONS_DIR, fname), "wb") as t: shutil.copyfileobj(s, t)
        except: pass

    def load_from_cache(self):
        def process_json(path):
            if not os.path.exists(path): return []
            with open(path, 'r', encoding='utf-8') as f:
                data = json.loads(re.sub(r",\s*(?=[}\]])", "", f.read()))
                roots = data.get("RootChilds", data.get("Childs", []))
                return [i for i in roots if i.get("Name", "").lower() != "dev"]
        self.block_roots = process_json(BLOCKS_JSON_FILE); self.item_roots = process_json(ITEMS_JSON_FILE)
        self.reset_navigation()
        if os.path.exists(ICONS_DIR):
            for f in os.listdir(ICONS_DIR):
                name = f.replace(".png", "")
                if name not in self.icons:
                    try:
                        img = bpy.data.images.load(os.path.join(ICONS_DIR, f), check_existing=True)
                        self.icons[name] = gpu.texture.from_image(img); bpy.data.images.remove(img)
                    except: pass
        self.loading_status = "READY"

    def set_mode(self, mode):
        self.current_mode = mode; self.reset_navigation()

    def reset_navigation(self):
        self.active_rows = [self.block_roots if self.current_mode == "BLOCKS" else self.item_roots]
        self.selected_indices = [-1]; self.search_query = ""; self.search_results = []
        self.selected_block_name = "None"; self.is_ghosting = False

    def find_first_block_name(self, item):
        if not item.get("IsFolder", False): return item.get("Name")
        children = item.get("Childs", [])
        return self.find_first_block_name(children[0]) if children else None

    def update_live_search(self):
        if self.search_query != "":
            self.active_rows = [self.block_roots if self.current_mode == "BLOCKS" else self.item_roots]
            self.selected_indices = [-1]
        q = self.search_query.lower(); res = []
        if q:
            def walk(items):
                for i in items:
                    if not i.get("IsFolder"):
                        if q in i.get("Name", "").lower(): res.append(i)
                    else: walk(i.get("Childs", []))
            walk(self.block_roots if self.current_mode == "BLOCKS" else self.item_roots)
        self.search_results = res[:70]

    def select_item(self, r_idx, i_idx, is_search=False):
        item = self.search_results[i_idx] if is_search else self.active_rows[r_idx][i_idx]
        is_folder = item.get("IsFolder", False)
        if not is_search:
            self.active_rows = self.active_rows[:r_idx+1]; self.selected_indices = self.selected_indices[:r_idx+1]; self.selected_indices[r_idx] = i_idx
        if is_folder and item.get("Childs"):
            if not is_search: self.active_rows.append(item.get("Childs")); self.selected_indices.append(-1)
            self.is_ghosting = False; return False
        else:
            self.selected_block_name = item.get("Name"); self.active_item_name = self.selected_block_name
            self.is_ghosting = True
            return True

tm_manager = TM_Inventory_Manager()

# --- DRAWING HELPERS ---
def draw_rect(x, y, w, h, col, shader):
    v = ((x, y), (x+w, y), (x+w, y+h), (x, y+h))
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": v})
    shader.bind(); shader.uniform_float("color", col); batch.draw(shader)

def draw_card(x, y, item, index, is_active, is_leaf, is_last_sel, scale, shader_flat, shader_img, prefs):
    is_folder = item.get("IsFolder", False); cw, ch = 105 * scale, 130 * scale
    if is_last_sel: base_col, tab_col = (0.95, 0.95, 0.95, 1.0), (0.4, 0.6, 1.0, 1.0)
    elif is_active: base_col, tab_col = (0.1, 0.85, 0.45, 0.95), (0.0, 1.0, 0.6, 1.0)
    elif is_leaf and not is_folder: base_col, tab_col = (0.5, 0.5, 0.5, 0.8), (0.3, 0.3, 0.3, 1.0)
    else: base_col, tab_col = (1.0, 0.75, 0.0, 0.95), (0.0, 0.7, 0.3, 1.0)
    draw_rect(x, y, cw, ch * 0.85, base_col, shader_flat)
    draw_rect(x, y + (ch * 0.85) - (4 * scale), 38 * scale, 22 * scale, tab_col, shader_flat)
    blf.color(0, prefs.ui_text_color[0], prefs.ui_text_color[1], prefs.ui_text_color[2], prefs.ui_text_color[3]); blf.size(0, round(15 * scale))
    blf.position(0, x + (8 * scale), y + (ch * 0.85) + (2 * scale), 0); blf.draw(0, str(index + 1))
    icon_name = item.get("Name") if not is_folder else tm_manager.find_first_block_name(item)
    if is_folder and not icon_name: icon_name = "FolderClassic"
    if icon_name in tm_manager.icons:
        tex = tm_manager.icons[icon_name]
        if tex:
            si = 95 * scale; ix, iy = x + (cw - si)/2, y + (8 * scale)
            v = ((ix, iy), (ix + si, iy), (ix + si, iy + si), (ix, iy + si))
            batch = batch_for_shader(shader_img, 'TRI_FAN', {"pos": v, "texCoord": ((0,0),(1,0),(1,1),(0,1))})
            gpu.state.blend_set('ALPHA'); shader_img.bind(); shader_img.uniform_sampler("image", tex); batch.draw(shader_img)

def draw_3d_ghost(context, pos, rot_euler, fill_col, line_col, line_w):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    
    # 1. Full 3D Rotation Matrix for the Shell (X, Y, Z)
    rot_mat_full = Euler(rot_euler, 'XYZ').to_matrix()
    
    # 2. Z-Only Rotation Matrix for the Footprint (Ground Projection)
    # This ensures the white line stays a flat rectangle on the ground, regardless of tilt
    rot_mat_z = Euler((0.0, 0.0, rot_euler.z), 'XYZ').to_matrix()
    
    gpu.state.blend_set('ALPHA')
    
    # 1. Main Ghost Shell
    min_x, max_x = tm_manager.ghost_min.x, tm_manager.ghost_max.x
    min_y, max_y = tm_manager.ghost_min.y, tm_manager.ghost_max.y
    min_z, max_z = tm_manager.ghost_min.z, tm_manager.ghost_max.z
    
    c = []
    # Calculate corners using Full Matrix Rotation
    for dx in [min_x, max_x]:
        for dy in [min_y, max_y]:
            for dz in [min_z, max_z]:
                local_v = Vector((dx, dy, dz))
                rotated_v = rot_mat_full @ local_v
                c.append((pos.x + rotated_v.x, pos.y + rotated_v.y, pos.z + rotated_v.z))
    
    # Fill Box
    indices = [(0,1,3,2), (4,5,7,6), (0,1,5,4), (2,3,7,6), (0,2,6,4), (1,3,7,5)]
    for face in indices:
        bf = batch_for_shader(shader, 'TRI_FAN', {"pos": [c[i] for i in face]}); shader.bind(); shader.uniform_float("color", fill_col); bf.draw(shader)
    # Outline Box
    lines = [c[0],c[1], c[1],c[3], c[3],c[2], c[2],c[0], c[4],c[5], c[5],c[7], c[7],c[6], c[6],c[4], c[0],c[4], c[1],c[5], c[2],c[6], c[3],c[7]]
    batch_l = batch_for_shader(shader, 'LINES', {"pos": lines}); shader.bind(); shader.uniform_float("color", line_col); gpu.state.line_width_set(line_w); batch_l.draw(shader)
    
    # 2. Ground Footprint (Flattened Z, using only Z rotation)
    gv = []
    for corner in [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]:
        local_v = Vector((corner[0], corner[1], min_z))
        rotated_v = rot_mat_z @ local_v  # Use Z-only matrix here
        gv.append((pos.x + rotated_v.x, pos.y + rotated_v.y, 0)) # Absolute Ground 0
        
    bg = batch_for_shader(shader, 'LINES', {"pos": [gv[0],gv[1], gv[1],gv[2], gv[2],gv[3], gv[3],gv[0]]})
    shader.bind(); shader.uniform_float("color", (1, 1, 1, 0.6)); gpu.state.line_width_set(1.5); bg.draw(shader)

def draw_callback_px(context):
    prefs = context.preferences.addons[__name__].preferences
    if tm_manager.loading_status != "READY": return
    gpu.state.blend_set('ALPHA'); shader_flat, shader_img = gpu.shader.from_builtin('UNIFORM_COLOR'), gpu.shader.from_builtin('IMAGE')
    s = tm_manager.ui_width / 830.0; bar_h, slot_w = 35 * s, 115 * s
    cur_w = tm_manager.current_bar_width = (7 * slot_w) + 10 * s
    draw_rect(tm_manager.ui_pos_x, tm_manager.ui_pos_y - bar_h, cur_w, bar_h, prefs.ui_bg_color, shader_flat)
    hx = tm_manager.ui_pos_x + cur_w - (bar_h * 2) - 2; draw_rect(hx, tm_manager.ui_pos_y - bar_h, bar_h, bar_h, (0.2, 0.2, 0.2, 1.0), shader_flat)
    blf.color(0, prefs.ui_text_color[0], prefs.ui_text_color[1], prefs.ui_text_color[2], prefs.ui_text_color[3]); blf.size(0, round(20 * s)); blf.position(0, hx + (bar_h - 10*s)/2, tm_manager.ui_pos_y - bar_h + 10*s, 0); blf.draw(0, "?")
    name_text = f"TM2020 | {tm_manager.selected_block_name}"; blf.size(0, round(16 * s)); blf.position(0, tm_manager.ui_pos_x + 10, tm_manager.ui_pos_y - (bar_h * 0.7), 0); blf.draw(0, name_text)
    sx = hx - (280 * s) - (5 * s); draw_rect(sx, tm_manager.ui_pos_y - bar_h + 3*s, 280*s, bar_h - 6*s, (0.05, 0.35, 0.7, 1.0) if tm_manager.is_searching else (0.1, 0.1, 0.1, 1.0), shader_flat)
    blf.size(0, round(13 * s)); blf.color(0, 1, 1, 1, 1); blf.position(0, sx + 10, tm_manager.ui_pos_y - bar_h + 10*s, 0); blf.draw(0, tm_manager.search_query or "Search...")
    draw_rect(tm_manager.ui_pos_x, tm_manager.ui_pos_y, cur_w, bar_h, prefs.ui_accent_color, shader_flat)
    for i, m in enumerate(["Editor_Blocks", "Editor_Items"]):
        bx, by = tm_manager.ui_pos_x + 12 + (i * 45*s), tm_manager.ui_pos_y + (bar_h - 28*s)/2
        if m in tm_manager.icons:
            v = ((bx, by), (bx+28*s, by), (bx+28*s, by+28*s), (bx, by+28*s))
            bt = batch_for_shader(shader_img, 'TRI_FAN', {"pos": v, "texCoord": ((0,0),(1,0),(1,1),(0,1))}); shader_img.bind(); shader_img.uniform_sampler("image", tm_manager.icons[m]); bt.draw(shader_img)
    sy_cards, row_h = tm_manager.ui_pos_y + bar_h + 10*s, 145 * s
    for r_idx, row in enumerate(tm_manager.active_rows):
        ry = sy_cards + r_idx * row_h
        for i, item in enumerate(row):
            rx = tm_manager.ui_pos_x + 10*s + i * slot_w; draw_card(rx, ry, item, i, (i == tm_manager.selected_indices[r_idx]), not any(i.get("IsFolder") for i in row), (item.get("Name") == tm_manager.selected_block_name), s, shader_flat, shader_img, prefs)
    if tm_manager.search_query != "":
        sry = sy_cards + (len(tm_manager.active_rows) * row_h)
        for i, item in enumerate(tm_manager.search_results):
            rx_s, ry_s = tm_manager.ui_pos_x + 10*s + (i % 7) * slot_w, sry + (i // 7) * row_h
            draw_card(rx_s, ry_s, item, i, False, True, (item.get("Name") == tm_manager.selected_block_name), s, shader_flat, shader_img, prefs)
    if tm_manager.is_hovering_help:
        tx, ty = tm_manager.ui_pos_x + cur_w + 10, tm_manager.ui_pos_y - bar_h; draw_rect(tx, ty, 380*s, 260*s, (0,0,0,0.95), shader_flat)
        blf.size(0, round(15 * s)); blf.color(0, 1, 1, 1, 1); lines = ["--- TM2020 INVENTORY HELP ---", "", "- L-Click Viewport: COMMIT (PLACE)", "- R-Click Viewport: ROTATE Z -90° (CW)", "- Arrows Left/Right: ROTATE X 22.5°", "- Arrows Up/Down: ROTATE Y 22.5°", "- / Key: RESET ROTATION", "- G-Key: TOGGLE GHOST MODE", "- Mouse-Wheel: Z-HEIGHT", "- Alt+Wheel: ZOOM TO GHOST"]
        for i, line in enumerate(lines): blf.position(0, tx + 15, ty + 260*s - (21 * s * (i+1)), 0); blf.draw(0, line)

def draw_callback_view(context):
    if tm_manager.is_ghosting:
        p = context.preferences.addons[__name__].preferences; draw_3d_ghost(context, tm_manager.ghost_pos, tm_manager.ghost_rotation_euler, p.ghost_color, p.ghost_outline_color, p.ghost_outline_width)

class VIEW3D_OT_tm_inventory(bpy.types.Operator):
    bl_idname = "view3d.tm_inventory"; bl_label = "Trackmania Inventory"
    is_dragging = is_scaling = _is_warping = False; drag_offset = [0, 0]; _h2d = _h3d = None

    def cleanup_preview(self):
        if tm_manager.active_preview_obj:
            try: bpy.data.objects.remove(tm_manager.active_preview_obj, do_unlink=True)
            except: pass
            tm_manager.active_preview_obj = None
        for coll in list(tm_manager.active_preview_colls):
            if coll and coll.name in bpy.data.collections:
                for o in list(coll.objects): bpy.data.objects.remove(o, do_unlink=True)
                for scene in bpy.data.scenes:
                    if coll.name in scene.collection.children: scene.collection.children.unlink(coll)
                bpy.data.collections.remove(coll)
        tm_manager.active_preview_colls.clear()
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

    def import_as_preview(self, context, name):
        self.cleanup_preview()
        p = context.preferences.addons[__name__].preferences; b = p.path_blocks if tm_manager.current_mode == "BLOCKS" else p.path_items
        f = next((path for e in [".EDClassic.Gbx", ".Item.Gbx", ".Gbx"] if os.path.exists(path := os.path.join(b, f"{name}{e}"))), None)
        if f:
            pre_colls, pre_objs = set(bpy.data.collections), set(bpy.data.objects)
            bpy.ops.view3d.tm_nice_import_gbx('EXEC_DEFAULT', filepath=f, files=[{"name": os.path.basename(f)}], visible_only=p.visible_only, merge_objects=p.merge_objects, lod=p.lod)
            tm_manager.active_preview_colls.extend(list(set(bpy.data.collections) - pre_colls))
            new_objs = [o for o in bpy.data.objects if o not in pre_objs]
            mesh_objs = [o for o in new_objs if o.type == 'MESH' and o.name in context.view_layer.objects]
            
            if mesh_objs:
                bpy.ops.object.select_all(action='DESELECT')
                for o in mesh_objs: o.select_set(True)
                context.view_layer.objects.active = mesh_objs[0]
                if p.auto_join and len(mesh_objs) > 1: bpy.ops.object.join()
                tm_manager.active_preview_obj = context.view_layer.objects.active
                obj = tm_manager.active_preview_obj
                
                # --- ROTATION FIX ---
                obj.rotation_mode = 'XYZ'
                obj.rotation_euler = (0, 0, 0)
                
                # --- PIVOT FIX & BOUNDS CALCULATION ---
                bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                min_x, max_x = min(v.x for v in bbox), max(v.x for v in bbox)
                min_y, max_y = min(v.y for v in bbox), max(v.y for v in bbox)
                min_z, max_z = min(v.z for v in bbox), max(v.z for v in bbox)

                size_x = max_x - min_x
                size_y = max_y - min_y
                size_z = max_z - min_z

                grid_w = max(32, math.ceil((size_x - 1.0) / 32) * 32)
                grid_d = max(32, math.ceil((size_y - 1.0) / 32) * 32)
                grid_h = max(8, math.ceil((size_z - 0.1) / 8) * 8)

                center_x, center_y, bottom_z = (min_x + max_x) / 2, (min_y + max_y) / 2, min_z
                saved_cursor = context.scene.cursor.location.copy()
                context.scene.cursor.location = (center_x, center_y, bottom_z)
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
                context.scene.cursor.location = saved_cursor

                tm_manager.ghost_min = Vector((-grid_w / 2, -grid_d / 2, 0))
                tm_manager.ghost_max = Vector((grid_w / 2, grid_d / 2, grid_h))
                
                # Force an update to recalculate the snapped position with current rotation
                # Pass 0,0 and force_snap=True to avoid relying on mouse ray (which requires 3d context)
                self.update_ghost_location(context, 0, 0, sync_mouse=False, force_snap=True)
                
                self.sync_preview_pos()

    def sync_preview_pos(self):
        if tm_manager.active_preview_obj:
            tm_manager.active_preview_obj.location = tm_manager.ghost_pos
            tm_manager.active_preview_obj.rotation_euler = tm_manager.ghost_rotation_euler

    def commit_block(self, context):
        if not tm_manager.active_preview_obj: return
        block_name = tm_manager.active_item_name
        root_name = f"TM_{block_name}"
        root_coll = bpy.data.collections.get(root_name) or bpy.data.collections.new(root_name)
        if root_name not in context.scene.collection.children: context.scene.collection.children.link(root_coll)
        obj = tm_manager.active_preview_obj; tm_manager.active_preview_obj = None 
        for coll in list(obj.users_collection): coll.objects.unlink(obj)
        root_coll.objects.link(obj); obj.name = f"{block_name}_Placed"
        self.cleanup_preview(); self.import_as_preview(context, block_name)

    def update_ghost_location(self, context, mx, my, sync_mouse=False, force_snap=False):
        region = context.region
        # Safely get rv3d, though we only strictly need it if NOT force_snap
        rv3d = getattr(context.space_data, 'region_3d', None) if context.space_data else None
        
        # 1. Plane Intersection Calculation
        if force_snap:
            # If forced, we don't rely on mouse ray, just re-evaluate current pos
            loc = tm_manager.ghost_pos
        else:
            if not rv3d: return # Can't calculate 3D projection without View3D context
            
            if sync_mouse:
                new_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, tm_manager.ghost_pos)
                if new_2d: 
                    self._is_warping = True
                    context.window.cursor_warp(int(new_2d.x + region.x), int(new_2d.y + region.y))
                
                # CRITICAL: Even if warping, we must apply Z changes immediately
                tm_manager.ghost_pos.z = tm_manager.ghost_z_offset
                self.sync_preview_pos()
                return # Skip calculation during warp

            ro = view3d_utils.region_2d_to_origin_3d(region, rv3d, (mx, my))
            rd = view3d_utils.region_2d_to_vector_3d(region, rv3d, (mx, my))
            
            if abs(rd.z) > 0.0001:
                t = (tm_manager.ghost_z_offset - ro.z) / rd.z
                loc = ro + rd * t if t > 0 else ro + rd * 100
            else: loc = ro + rd * 100
            
        # 2. INTELLIGENT OFFSET CALCULATION
        base_w = tm_manager.ghost_max.x - tm_manager.ghost_min.x
        base_d = tm_manager.ghost_max.y - tm_manager.ghost_min.y
        
        # Determine visual "width" vs "depth" based on Z-rotation.
        # We snap to nearest 90 degrees to determine grid offset logic.
        z_rot_deg = math.degrees(tm_manager.ghost_rotation_euler.z) % 360
        snap_idx = int(round(z_rot_deg / 90)) % 4
        
        is_rotated_90 = (snap_idx % 2 == 1)
        final_w = base_d if is_rotated_90 else base_w
        final_d = base_w if is_rotated_90 else base_d
        
        off_x = (final_w % 64.0) / 2.0
        off_y = (final_d % 64.0) / 2.0
        
        tm_manager.ghost_pos.x = (math.floor(loc.x / 32.0) * 32.0) + off_x
        tm_manager.ghost_pos.y = (math.floor(loc.y / 32.0) * 32.0) + off_y
        tm_manager.ghost_pos.z = tm_manager.ghost_z_offset
            
        self.sync_preview_pos()

    def modal(self, context, event):
        if context.area: context.area.tag_redraw()
        mx, my, s = event.mouse_region_x, event.mouse_region_y, tm_manager.ui_width / 830.0
        
        # --- RECALCULATE UI GEOMETRY EXACTLY LIKE DRAW() ---
        # This ensures the click-zones (hitboxes) match the visual zones 100%
        slot_w = 115 * s
        bar_h = 35 * s
        cur_w = (7 * slot_w) + 10 * s
        tm_manager.current_bar_width = cur_w
        
        hx = tm_manager.ui_pos_x + cur_w - (bar_h * 2) - 2 # Exact Help X
        sx = hx - (280 * s) - (5 * s) # Exact Search X
        search_w = 280 * s
        
        sy_cards, row_h = tm_manager.ui_pos_y + bar_h + 10*s, 145 * s
        sh_rows = math.ceil(len(tm_manager.search_results) / 7) if tm_manager.search_query else 0
        
        in_ui = (tm_manager.ui_pos_x <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y - bar_h <= my <= sy_cards + (len(tm_manager.active_rows) + sh_rows) * row_h)
        tm_manager.is_hovering_help = (hx <= mx <= hx + bar_h) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)

        if not in_ui and context.region.type != 'WINDOW': return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE' and self._is_warping: self._is_warping = False; return {'RUNNING_MODAL'}
        
        # --- KEYBOARD SHORTCUTS ---
        if event.value == 'PRESS':
            # Escape to clear Search, then Close
            if event.type == 'ESC':
                if tm_manager.is_searching:
                    tm_manager.is_searching = False
                    return {'RUNNING_MODAL'}
                else:
                    self.cleanup_preview()
                    tm_manager.is_open = False
                    bpy.types.SpaceView3D.draw_handler_remove(self._h2d, 'WINDOW')
                    bpy.types.SpaceView3D.draw_handler_remove(self._h3d, 'WINDOW')
                    return {'CANCELLED'}

            if not tm_manager.is_searching:
                if event.type == 'G':
                    tm_manager.is_ghosting = not tm_manager.is_ghosting
                    if tm_manager.is_ghosting: self.import_as_preview(context, tm_manager.active_item_name)
                    else: self.cleanup_preview()
                    return {'RUNNING_MODAL'}
                
                # Rotation Logic
                rot_step = math.radians(22.5)
                update_rot = False
                
                if event.type == 'LEFT_ARROW':
                    tm_manager.ghost_rotation_euler.x -= rot_step # X-Axis Tilt
                    update_rot = True
                elif event.type == 'RIGHT_ARROW':
                    tm_manager.ghost_rotation_euler.x += rot_step # X-Axis Tilt
                    update_rot = True
                elif event.type == 'UP_ARROW':
                    tm_manager.ghost_rotation_euler.y -= rot_step # Y-Axis Roll
                    update_rot = True
                elif event.type == 'DOWN_ARROW':
                    tm_manager.ghost_rotation_euler.y += rot_step # Y-Axis Roll
                    update_rot = True
                elif event.type == 'SLASH' or event.type == 'NUMPAD_SLASH': # / to Reset
                    tm_manager.ghost_rotation_euler = Vector((0.0, 0.0, 0.0))
                    update_rot = True

                if update_rot:
                    # Force re-snap because rotation might change offset requirements
                    self.update_ghost_location(context, mx, my, sync_mouse=False, force_snap=True)
                    return {'RUNNING_MODAL'}

        # --- SEARCH INPUT ---
        if tm_manager.is_searching and not (event.type == 'LEFTMOUSE' and event.value == 'PRESS'):
            if event.value in {'PRESS', 'REPEAT'}:
                if event.type == 'BACKSPACE': tm_manager.search_query = tm_manager.search_query[:-1]; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.type == 'DEL': tm_manager.search_query = ""; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.type in {'RET', 'NUMPAD_ENTER', 'ESC'}: tm_manager.is_searching = False; return {'RUNNING_MODAL'}
                elif event.unicode: tm_manager.search_query += event.unicode; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}
        
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if in_ui:
                # 1. UI: Search Bar Click (Exact Hitbox)
                # Check height first (Black bar zone)
                if (tm_manager.ui_pos_y - bar_h) <= my <= tm_manager.ui_pos_y:
                    # Search
                    if sx <= mx <= sx + search_w:
                        tm_manager.is_searching = True
                        return {'RUNNING_MODAL'}
                    # Copy Name (Left of search)
                    if tm_manager.ui_pos_x <= mx <= sx:
                        bpy.context.window_manager.clipboard = tm_manager.active_item_name
                        self.report({'INFO'}, f"Copied: {tm_manager.active_item_name}")
                        return {'RUNNING_MODAL'}
                    # Resize (Right Edge)
                    if mx > tm_manager.ui_pos_x + cur_w - (20 * s):
                        self.is_scaling = True
                        return {'RUNNING_MODAL'}

                # General UI Click reset
                if tm_manager.is_searching: tm_manager.is_searching = False
                
                if tm_manager.ui_pos_y <= my <= tm_manager.ui_pos_y + bar_h:
                    for i in range(2):
                        if tm_manager.ui_pos_x + 10 + i*45*s <= mx <= tm_manager.ui_pos_x + 40 + i*45*s: tm_manager.set_mode("BLOCKS" if i==0 else "ITEMS"); self.cleanup_preview(); return {'RUNNING_MODAL'}
                hit, is_block = False, False
                for r_idx, row in enumerate(tm_manager.active_rows):
                    for i, it in enumerate(row):
                        ix, iy = tm_manager.ui_pos_x + 10*s + i*slot_w, sy_cards + r_idx*row_h
                        if ix <= mx <= ix+105*s and iy <= my <= iy+110*s:
                            if r_idx == 0: tm_manager.search_query = ""; tm_manager.update_live_search()
                            is_block = tm_manager.select_item(r_idx, i); hit = True; break
                    if hit: break
                if not hit and tm_manager.search_query != "":
                    sry = sy_cards + (len(tm_manager.active_rows) * row_h)
                    for i, it in enumerate(tm_manager.search_results):
                        ix_s, iy_s = tm_manager.ui_pos_x + 10*s + (i % 7) * 115*s, sry + (i // 7) * row_h
                        if ix_s <= mx <= ix_s+105*s and iy_s <= my <= iy_s+110*s: is_block = tm_manager.select_item(0, i, True); hit = True; break
                if hit:
                    if is_block: self.import_as_preview(context, tm_manager.active_item_name)
                    else: self.cleanup_preview()
                    tm_manager.is_searching = False; return {'RUNNING_MODAL'}
                self.is_dragging = True; self.drag_offset = [tm_manager.ui_pos_x - mx, tm_manager.ui_pos_y - my]; return {'RUNNING_MODAL'}
            elif tm_manager.is_ghosting and context.region.type == 'WINDOW':
                self.commit_block(context); return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if in_ui:
                if len(tm_manager.active_rows) > 1: tm_manager.active_rows.pop(); tm_manager.selected_indices.pop(); tm_manager.selected_indices[-1] = -1
                self.cleanup_preview(); return {'RUNNING_MODAL'}
            elif tm_manager.is_ghosting and context.region.type == 'WINDOW' and tm_manager.active_preview_obj:
                # Rotate Clockwise on Z axis (-90 degrees)
                tm_manager.ghost_rotation_euler.z -= math.radians(90)
                # Re-calculate snap immediately
                self.update_ghost_location(context, mx, my, sync_mouse=False, force_snap=True)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            if self.is_dragging: tm_manager.ui_pos_x, tm_manager.ui_pos_y = mx + self.drag_offset[0], my + self.drag_offset[1]
            if self.is_scaling: tm_manager.ui_width = max(620, mx - tm_manager.ui_pos_x)
            if tm_manager.is_ghosting and context.region.type == 'WINDOW' and not in_ui: self.update_ghost_location(context, mx, my)
            return {'PASS_THROUGH'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and tm_manager.is_ghosting and not in_ui:
            mult = 1 if event.type == 'WHEELUPMOUSE' else -1
            if event.alt:
                rv3d = context.space_data.region_3d; rv3d.view_distance = max(1.0, rv3d.view_distance - (mult * rv3d.view_distance * 0.1))
                self.update_ghost_location(context, mx, my, sync_mouse=True)
            elif not event.shift:
                tm_manager.ghost_z_offset = max(0.0, tm_manager.ghost_z_offset + mult * 8.0)
                tm_manager.ghost_pos.z = tm_manager.ghost_z_offset
                self.update_ghost_location(context, mx, my, sync_mouse=True)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE': self.is_dragging = self.is_scaling = False
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        tm_manager.start_load(); self._h2d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (context,), 'WINDOW', 'POST_PIXEL')
        self._h3d = bpy.types.SpaceView3D.draw_handler_add(draw_callback_view, (context,), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self); return {'RUNNING_MODAL'}

# --- REGISTRATION ---
classes = (TM2020_Inventory_Preferences, VIEW3D_OT_tm_inventory); addon_keymaps = []
def register():
    for cls in classes: bpy.utils.register_class(cls)
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new(VIEW3D_OT_tm_inventory.bl_idname, 'I', 'PRESS', ctrl=True, shift=True)
        addon_keymaps.append((km, kmi))
def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    for km, kmi in addon_keymaps: km.keymap_items.remove(kmi)
    addon_keymaps.clear()
if __name__ == "__main__": register()