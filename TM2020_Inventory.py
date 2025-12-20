bl_info = {
    "name": "Trackmania 2020 Inventory",
    "author": "BigthirstyTM & AI Assistant",
    "version": (4, 1),
    "blender": (5, 0, 0),
    "location": "View3D > Press Ctrl + Shift + I to open",
    "description": "TM2020 Inventory - Fixed Right-Click passthrough for Outliner/Blender UI.",
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
from gpu_extras.batch import batch_for_shader

# --- ONLINE CONFIGURATION ---
BLOCKS_JSON_URL = "https://raw.githubusercontent.com/BigthirstyTM/TM2020-Inventory-Data/main/BlockInfoInventory.gbx.json"
ITEMS_JSON_URL = "https://raw.githubusercontent.com/BigthirstyTM/TM2020-Inventory-Data/main/ItemInventory.gbx.json"
ZIP_URL = "https://github.com/BigthirstyTM/TM2020-Inventory-Data/archive/refs/heads/main.zip"

# --- LOCAL IMPORT PATHS ---
BLOCK_IMPORT_PATH = r"C:\Users\PC\OpenplanetNext\Extract\GameData\Stadium\GameCtnBlockInfo\GameCtnBlockInfoClassic"
ITEM_IMPORT_PATH = r"C:\Users\PC\OpenplanetNext\Extract\GameData\Stadium\Items"

CACHE_DIR = os.path.join(bpy.utils.user_resource('SCRIPTS'), "presets", "tm_inventory_cache")
ICONS_DIR = os.path.join(CACHE_DIR, "icons")
BLOCKS_JSON_FILE = os.path.join(CACHE_DIR, "blocks.json")
ITEMS_JSON_FILE = os.path.join(CACHE_DIR, "items.json")

class TM_Inventory_Manager:
    def __init__(self):
        self.block_roots = []
        self.item_roots = []
        self.icons = {} 
        self.active_rows = [] 
        self.selected_indices = [] 
        self.search_results = []
        self.selected_block_name = "None"
        self.selected_search_idx = -1
        self.search_query = ""
        self.is_searching = False
        self.loading_status = "IDLE"
        self.current_mode = "BLOCKS"
        
        # PERSISTENT UI STATE
        self.ui_pos_x = 150
        self.ui_pos_y = 200
        self.ui_width = 830.0
        self.base_width = 830.0
        self.current_bar_width = 830.0

    def request_url(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        return urllib.request.urlopen(req)

    def start_load(self):
        if self.loading_status == "READY": return
        os.makedirs(ICONS_DIR, exist_ok=True)
        if not os.path.exists(BLOCKS_JSON_FILE) or not os.listdir(ICONS_DIR):
            self.loading_status = "DOWNLOADING"
            self.download_all()
        self.load_from_cache()

    def download_all(self):
        try:
            with self.request_url(BLOCKS_JSON_URL) as r:
                with open(BLOCKS_JSON_FILE, 'w', encoding='utf-8') as f: f.write(r.read().decode())
            with self.request_url(ITEMS_JSON_URL) as r:
                with open(ITEMS_JSON_FILE, 'w', encoding='utf-8') as f: f.write(r.read().decode())
            with urllib.request.urlopen(ZIP_URL) as response:
                zip_data = response.read()
            self.loading_status = "EXTRACTING"
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                for member in z.namelist():
                    if member.lower().endswith(".png"):
                        filename = os.path.basename(member)
                        if not filename: continue
                        with z.open(member) as source, open(os.path.join(ICONS_DIR, filename), "wb") as target:
                            shutil.copyfileobj(source, target)
        except Exception as e: print(f"Download Error: {e}")

    def load_from_cache(self):
        self.loading_status = "LOADING_GPU"
        def process_json(path):
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        clean = re.sub(r",\s*(?=[}\]])", "", content)
                        data = json.loads(clean)
                        roots = data.get("RootChilds", data.get("Childs", []))
                        return [item for item in roots if item.get("Name", "").lower() != "dev"]
                except: pass
            return []

        self.block_roots = process_json(BLOCKS_JSON_FILE)
        self.item_roots = process_json(ITEMS_JSON_FILE)
        self.reset_navigation()
        
        if os.path.exists(ICONS_DIR):
            for f in os.listdir(ICONS_DIR):
                if f.endswith(".png"):
                    name = f.replace(".png", "")
                    try:
                        img = bpy.data.images.load(os.path.join(ICONS_DIR, f), check_existing=True)
                        img.alpha_mode = 'STRAIGHT'
                        self.icons[name] = gpu.texture.from_image(img)
                        bpy.data.images.remove(img)
                    except: pass
        self.loading_status = "READY"

    def set_mode(self, mode):
        self.current_mode = mode
        self.reset_navigation()

    def reset_navigation(self):
        self.active_rows = [self.block_roots if self.current_mode == "BLOCKS" else self.item_roots]
        self.selected_indices = [-1]
        self.search_query = ""
        self.search_results = []
        self.selected_block_name = "None"
        self.selected_search_idx = -1

    def find_first_block_name(self, item):
        if not item.get("IsFolder", False): return item.get("Name")
        children = item.get("Childs", [])
        return self.find_first_block_name(children[0]) if children else None

    def update_live_search(self):
        if self.search_query != "":
            self.active_rows = [self.block_roots if self.current_mode == "BLOCKS" else self.item_roots]
            self.selected_indices = [-1]
        query = self.search_query.lower()
        results = []
        if query:
            def walk(items):
                for item in items:
                    if not item.get("IsFolder"):
                        if query in item.get("Name", "").lower(): results.append(item)
                    else: walk(item.get("Childs", []))
            walk(self.block_roots if self.current_mode == "BLOCKS" else self.item_roots)
        self.search_results = results[:70]
        self.selected_search_idx = -1

    def select_item(self, row_idx, item_idx, is_search_result=False):
        item = self.search_results[item_idx] if is_search_result else self.active_rows[row_idx][item_idx]
        
        if is_search_result:
            self.selected_search_idx = item_idx
        else:
            self.active_rows = self.active_rows[:row_idx + 1]
            self.selected_indices = self.selected_indices[:row_idx + 1]
            self.selected_indices[row_idx] = item_idx

        if item.get("IsFolder") and item.get("Childs"):
            if not is_search_result:
                self.active_rows.append(item.get("Childs"))
                self.selected_indices.append(-1)
        else:
            self.selected_block_name = item.get("Name")
            self.import_gbx(self.selected_block_name)

    def import_gbx(self, name):
        if self.current_mode == "BLOCKS":
            filename = f"{name}.EDClassic.Gbx"
            filepath = os.path.join(BLOCK_IMPORT_PATH, filename)
        else:
            filename = f"{name}.Item.Gbx"
            filepath = os.path.join(ITEM_IMPORT_PATH, filename)

        if os.path.exists(filepath):
            try:
                bpy.ops.view3d.tm_nice_import_gbx(
                    'EXEC_DEFAULT',
                    filepath=filepath,
                    files=[{"name": os.path.basename(filepath)}]
                )
            except Exception as e:
                print(f"[TM2020] Operator Error: {e}")
        else:
            print(f"[TM2020] File not found: {filepath}")

    def go_back(self):
        if len(self.active_rows) > 1:
            self.active_rows.pop()
            self.selected_indices.pop()
            self.selected_indices[-1] = -1

tm_manager = TM_Inventory_Manager()

# --- DRAW HELPERS ---
def draw_rect(x, y, w, h, color, shader):
    vertices = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})
    shader.bind(); shader.uniform_float("color", color); batch.draw(shader)

def draw_card(x, y, item, index, is_active, is_leaf, is_last_sel, scale, shader_flat, shader_img):
    is_folder = item.get("IsFolder", False)
    cw, ch = 105 * scale, 130 * scale
    if is_last_sel: base_col, tab_col = (0.95, 0.95, 0.95, 1.0), (0.4, 0.6, 1.0, 1.0)
    elif is_active: base_col, tab_col = (0.1, 0.85, 0.45, 0.95), (0.0, 1.0, 0.6, 1.0)
    elif is_leaf and not is_folder: base_col, tab_col = (0.5, 0.5, 0.5, 0.8), (0.3, 0.3, 0.3, 1.0)
    else: base_col, tab_col = (1.0, 0.75, 0.0, 0.95), (0.0, 0.7, 0.3, 1.0)
    draw_rect(x, y, cw, ch * 0.85, base_col, shader_flat)
    draw_rect(x, y + (ch * 0.85) - (4 * scale), 38 * scale, 22 * scale, tab_col, shader_flat)
    blf.color(0, 1, 1, 1, 1); blf.size(0, round(15 * scale))
    blf.position(0, x + (8 * scale), y + (ch * 0.85) + (2 * scale), 0); blf.draw(0, str(index + 1))
    icon_name = item.get("Name") if not is_folder else tm_manager.find_first_block_name(item)
    if icon_name and icon_name in tm_manager.icons:
        tex = tm_manager.icons.get(icon_name)
        if tex:
            si = 95 * scale
            ix, iy = x + (cw - si)/2, y + (6 * scale)
            gpu.state.blend_set('ALPHA')
            v = ((ix, iy), (ix + si, iy), (ix + si, iy + si), (ix, iy + si))
            batch = batch_for_shader(shader_img, 'TRI_FAN', {"pos": v, "texCoord": ((0,0),(1,0),(1,1),(0,1))})
            shader_img.bind(); shader_img.uniform_sampler("image", tex); batch.draw(shader_img)

def draw_callback_px(self, context):
    gpu.state.blend_set('ALPHA')
    shader_flat, shader_img = gpu.shader.from_builtin('UNIFORM_COLOR'), gpu.shader.from_builtin('IMAGE')
    if tm_manager.loading_status != "READY":
        ww, wh = context.area.width, context.area.height
        draw_rect(ww/2 - 200, wh/2 - 50, 400, 100, (0,0,0,0.8), shader_flat)
        blf.size(0, 25); blf.color(0, 1, 1, 1, 1); blf.position(0, ww/2 - 180, wh/2 - 10, 0); blf.draw(0, f"LOADING: {tm_manager.loading_status}")
        return

    s = tm_manager.ui_width / tm_manager.base_width
    row_h, margin, bar_h = 145 * s, 10 * s, 35 * s
    slot_w = 105 * s + margin
    tm_manager.current_bar_width = (7 * slot_w) + margin
    has_search = tm_manager.search_query != ""
    search_rows = ((len(tm_manager.search_results) - 1) // 7 + 1) if has_search else 0
    
    # Bottom bar
    draw_rect(tm_manager.ui_pos_x, tm_manager.ui_pos_y - bar_h, tm_manager.current_bar_width, bar_h, (0.01, 0.01, 0.01, 1.0), shader_flat)
    draw_rect(tm_manager.ui_pos_x + tm_manager.current_bar_width - bar_h, tm_manager.ui_pos_y - bar_h, bar_h, bar_h, (0.3, 0.3, 0.3, 1.0), shader_flat)
    hx = tm_manager.ui_pos_x + tm_manager.current_bar_width - (bar_h * 2) - 2
    draw_rect(hx, tm_manager.ui_pos_y - bar_h, bar_h, bar_h, (0.2, 0.2, 0.2, 1.0), shader_flat)
    blf.size(0, round(20 * s)); blf.color(0, 1, 1, 1, 1)
    q_tw, q_th = blf.dimensions(0, "?")
    blf.position(0, hx + (bar_h - q_tw)/2, (tm_manager.ui_pos_y - bar_h) + (bar_h - q_th)/2 + (2*s), 0); blf.draw(0, "?")
    
    search_w = 280 * s
    sx, sy_s = hx - search_w - (5 * s), tm_manager.ui_pos_y - bar_h + (3 * s)
    draw_rect(sx, sy_s, search_w, bar_h - (6*s), (0.05, 0.35, 0.7, 1.0) if tm_manager.is_searching else (0.1, 0.1, 0.1, 1.0), shader_flat)
    blf.size(0, round(13 * s)); blf.color(0, 1, 1, 1, 1); blf.position(0, sx + 10, sy_s + 7, 0)
    blf.draw(0, f"{tm_manager.search_query}|" if tm_manager.is_searching else (tm_manager.search_query if has_search else "Search..."))
    blf.size(0, round(16 * s)); blf.color(0, 1, 1, 1, 1); blf.position(0, tm_manager.ui_pos_x + 10, tm_manager.ui_pos_y - (bar_h * 0.7), 0)
    avail = sx - tm_manager.ui_pos_x - 15*s
    full_n = f"TM2020 | {tm_manager.selected_block_name}"
    tw_f, _ = blf.dimensions(0, full_n)
    if tw_f > avail: full_n = full_n[:int(len(full_n)*(avail/tw_f))-3] + "..."
    blf.draw(0, full_n)

    # Mode Bar
    draw_rect(tm_manager.ui_pos_x, tm_manager.ui_pos_y, tm_manager.current_bar_width, bar_h, (0.0, 0.45, 0.2, 0.95), shader_flat)
    icon_s = 28 * s
    for i, m_name in enumerate(["BLOCKS", "ITEMS"]):
        bx = tm_manager.ui_pos_x + 12 + (i * (icon_s + 18))
        by = tm_manager.ui_pos_y + (bar_h - icon_s)/2
        if tm_manager.current_mode == m_name: draw_rect(bx - 4, by - 4, icon_s + 8, icon_s + 8, (0, 0, 0, 0.2), shader_flat)
        tex_n = "Editor_Blocks" if m_name == "BLOCKS" else "Editor_Items"
        if tex_n in tm_manager.icons:
            v = ((bx, by), (bx + icon_s, by), (bx + icon_s, by + icon_s), (bx, by + icon_s))
            batch = batch_for_shader(shader_img, 'TRI_FAN', {"pos": v, "texCoord": ((0,0),(1,0),(1,1),(0,1))})
            shader_img.bind(); shader_img.uniform_sampler("image", tm_manager.icons[tex_n]); batch.draw(shader_img)

    # Cards
    start_y = tm_manager.ui_pos_y + bar_h + 10*s
    for r_idx, row_items in enumerate(tm_manager.active_rows):
        ry = start_y + (r_idx * row_h)
        sel_i = tm_manager.selected_indices[r_idx]
        is_leaf = not any(i.get("IsFolder") for i in row_items)
        is_deepest = (r_idx == len(tm_manager.active_rows) - 1) and not has_search
        for i, item in enumerate(row_items):
            rx = tm_manager.ui_pos_x + margin + i * slot_w
            isp, isls = (i == sel_i), (item.get("Name") == tm_manager.selected_block_name) or ((i == sel_i) and is_deepest)
            draw_card(rx, ry, item, i, isp, is_leaf, isls, s, shader_flat, shader_img)

    if has_search:
        sry = start_y + (len(tm_manager.active_rows) * row_h)
        for i, item in enumerate(tm_manager.search_results):
            rx, ry = tm_manager.ui_pos_x + margin + (i % 7) * slot_w, sry + (i // 7) * row_h
            draw_card(rx, ry, item, i, False, True, (item.get("Name") == tm_manager.selected_block_name), s, shader_flat, shader_img)

    if self.is_hovering_help:
        tw_p, th_p = 380 * s, 260 * s
        tx, ty = tm_manager.ui_pos_x + tm_manager.current_bar_width + 10, tm_manager.ui_pos_y - bar_h
        draw_rect(tx, ty, tw_p, th_p, (0, 0, 0, 0.95), shader_flat)
        blf.size(0, round(15 * s)); blf.color(0, 1, 1, 1, 1)
        lines = ["--- TM2020 INVENTORY HELP ---", "", "- L-Click Block: IMPORT to scene", "- L-Click Mode Bar: Switch Blocks/Items", "- L-Click Map: Open Folder", "- R-Click Window: Go back one level", "- Mouse-Drag: Move window", "- Bottom-Right Corner: Resize UI", "- TYPE in Search Box: Filter results", "- DELETE Key: Clear search field", "- Ctrl+V: Paste block name", "- Click Bottom Bar: Copy name to clipboard", "- Press ESC Key: Close Addon"]
        for i, line in enumerate(lines): blf.position(0, tx + 15, ty + th_p - (21 * s * (i+1)), 0); blf.draw(0, line)

class VIEW3D_OT_tm_inventory(bpy.types.Operator):
    bl_idname = "view3d.tm_inventory"
    bl_label = "Trackmania Inventory"
    is_dragging, is_scaling, is_hovering_help = False, False, False
    drag_offset = [0, 0]
    _handle = None

    def modal(self, context, event):
        if context.area: context.area.tag_redraw()
        if tm_manager.loading_status != "READY":
            if event.type == 'ESC': return {'CANCELLED'}
            return {'RUNNING_MODAL'}

        s = tm_manager.ui_width / tm_manager.base_width
        bar_h, row_h = 35 * s, 145 * s
        mx, my = event.mouse_region_x, event.mouse_region_y
        cur_w = tm_manager.current_bar_width
        hx = tm_manager.ui_pos_x + cur_w - (bar_h * 2) - 2
        sx, sy_s = hx - (280 * s) - (5 * s), tm_manager.ui_pos_y - bar_h

        # Zones
        in_search = (sx <= mx <= sx + 280*s) and (sy_s <= my <= sy_s + bar_h)
        in_help = (hx <= mx <= hx + bar_h) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)
        in_mode_bar = (tm_manager.ui_pos_x <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y <= my <= tm_manager.ui_pos_y + bar_h)
        in_bottom_bar = (tm_manager.ui_pos_x <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)
        in_resize = (tm_manager.ui_pos_x + cur_w - bar_h <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)
        
        has_search = tm_manager.search_query != ""
        total_rows = ((len(tm_manager.search_results) - 1) // 7 + 1) if has_search else len(tm_manager.active_rows)
        max_row_items = max(len(r) for r in tm_manager.active_rows) if tm_manager.active_rows else 0
        full_content_w = max(cur_w, (max_row_items * (105*s + 10*s)) + (10*s))
        in_ui_body = (tm_manager.ui_pos_x <= mx <= tm_manager.ui_pos_x + full_content_w) and (tm_manager.ui_pos_y <= my <= tm_manager.ui_pos_y + total_rows * row_h + bar_h + 10*s)

        is_over_ui = in_ui_body or in_bottom_bar or in_search or in_resize or in_mode_bar
        self.is_hovering_help = in_help

        # Keyboard Search
        if tm_manager.is_searching:
            if event.value in {'PRESS', 'REPEAT'}:
                if event.type == 'BACKSPACE': tm_manager.search_query = tm_manager.search_query[:-1]; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.type == 'DEL': tm_manager.search_query = ""; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.ctrl and event.type == 'V': tm_manager.search_query += context.window_manager.clipboard; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.type in {'RET', 'NUMPAD_ENTER', 'ESC'}: tm_manager.is_searching = False; return {'RUNNING_MODAL'}
                elif event.unicode and ord(event.unicode) > 31: tm_manager.search_query += event.unicode; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and not in_search: tm_manager.is_searching = False
            else: return {'RUNNING_MODAL'}

        # Mouse Click
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if in_resize: self.is_scaling = True; return {'RUNNING_MODAL'}
            if in_search: tm_manager.is_searching = True; return {'RUNNING_MODAL'}
            if in_mode_bar:
                btn_size = 34 * s
                for i, m in enumerate(["BLOCKS", "ITEMS"]):
                    bx = tm_manager.ui_pos_x + 10 + (i * (btn_size + 15))
                    if bx <= mx <= bx + btn_size: tm_manager.set_mode(m); return {'RUNNING_MODAL'}
            
            if in_bottom_bar and not in_help:
                if tm_manager.selected_block_name != "None":
                    context.window_manager.clipboard = tm_manager.selected_block_name
                    self.report({'INFO'}, f"Copied: {tm_manager.selected_block_name}")
                self.is_dragging = True; self.drag_offset = [tm_manager.ui_pos_x - mx, tm_manager.ui_pos_y - my]; return {'RUNNING_MODAL'}
            
            if in_ui_body:
                tm_manager.is_searching = False
                item_hit = False
                sy_cards = tm_manager.ui_pos_y + bar_h + 10*s
                if has_search:
                    for i, _ in enumerate(tm_manager.search_results):
                        ix, iy = tm_manager.ui_pos_x + (10*s) + (i % 7) * (115*s), sy_cards + (len(tm_manager.active_rows) * row_h) + (i // 7) * row_h
                        if ix < mx < ix + 105*s and iy < my < iy + 130*s: tm_manager.select_item(0, i, True); item_hit = True; break
                if not item_hit:
                    for r_idx, row in enumerate(tm_manager.active_rows):
                        for i, _ in enumerate(row):
                            ix, iy = tm_manager.ui_pos_x + (10*s) + i * (115*s), sy_cards + (r_idx * row_h)
                            if ix < mx < ix + 105*s and iy < my < iy + 130*s:
                                if r_idx == 0: tm_manager.reset_navigation()
                                tm_manager.select_item(r_idx, i); item_hit = True; break
                        if item_hit: break
                if not item_hit: self.is_dragging = True; self.drag_offset = [tm_manager.ui_pos_x - mx, tm_manager.ui_pos_y - my]
                return {'RUNNING_MODAL'}

        # Fix for Right-Click Passthrough
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if is_over_ui:
                tm_manager.go_back()
                return {'RUNNING_MODAL'}
            else:
                return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE': self.is_dragging = self.is_scaling = False
        if event.type == 'MOUSEMOVE':
            if self.is_dragging: tm_manager.ui_pos_x, tm_manager.ui_pos_y = mx + self.drag_offset[0], my + self.drag_offset[1]; return {'RUNNING_MODAL'}
            if self.is_scaling: tm_manager.ui_width = max(620, mx - tm_manager.ui_pos_x); return {'RUNNING_MODAL'}
        if event.type == 'ESC': bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW'); return {'CANCELLED'}
        
        # If mouse is outside the UI entirely, let Blender handle other inputs
        if not is_over_ui and not self.is_dragging:
            return {'PASS_THROUGH'}
        
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        tm_manager.start_load()
        self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

def register():
    bpy.utils.register_class(VIEW3D_OT_tm_inventory)
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
        km.keymap_items.new(VIEW3D_OT_tm_inventory.bl_idname, 'I', 'PRESS', ctrl=True, shift=True)

def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_tm_inventory)

if __name__ == "__main__": register()