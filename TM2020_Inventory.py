bl_info = {
    "name": "Trackmania 2020 Inventory",
    "author": "BigthirstyTM & AI Assistant",
    "version": (2, 13),
    "blender": (5, 0, 0),
    "location": "View3D > Press Ctrl + Shift + I to open",
    "description": "TM2020 Style Inventory - Standardized grid math for perfect click detection.",
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
JSON_URL = "https://raw.githubusercontent.com/BigthirstyTM/TM2020-Inventory-Data/main/BlockInfoInventory.gbx.json"
ZIP_URL = "https://github.com/BigthirstyTM/TM2020-Inventory-Data/archive/refs/heads/main.zip"
CACHE_DIR = os.path.join(bpy.utils.user_resource('SCRIPTS'), "presets", "tm_inventory_cache")
ICONS_DIR = os.path.join(CACHE_DIR, "icons")
JSON_FILE = os.path.join(CACHE_DIR, "data.json")

class TM_Inventory_Manager:
    def __init__(self):
        self.root_items = []
        self.icons = {} 
        self.active_rows = [] 
        self.selected_indices = [] 
        self.search_results = []
        self.selected_block_name = "None"
        self.selected_search_idx = -1
        self.search_query = ""
        self.is_searching = False
        self.loading_status = "IDLE"
        
        # PERSISTENT UI STATE
        self.ui_pos_x = 150
        self.ui_pos_y = 200
        self.ui_width = 1100.0
        self.base_width = 1100.0
        self.current_visible_width = 1100.0

    def start_load(self):
        if self.loading_status == "READY": return
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR, exist_ok=True)
            os.makedirs(ICONS_DIR, exist_ok=True)
        if not os.path.exists(JSON_FILE) or not os.listdir(ICONS_DIR):
            self.loading_status = "DOWNLOADING"
            self.download_all()
        self.load_from_cache()

    def download_all(self):
        try:
            with urllib.request.urlopen(JSON_URL) as url:
                content = url.read().decode()
                with open(JSON_FILE, 'w', encoding='utf-8') as f: f.write(content)
            with urllib.request.urlopen(ZIP_URL) as response:
                zip_data = response.read()
            self.loading_status = "EXTRACTING"
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                for member in z.namelist():
                    if member.lower().endswith(".png"):
                        filename = os.path.basename(member)
                        with z.open(member) as source, open(os.path.join(ICONS_DIR, filename), "wb") as target:
                            shutil.copyfileobj(source, target)
        except Exception as e: print(f"Download Error: {e}")

    def load_from_cache(self):
        self.loading_status = "LOADING_GPU"
        if os.path.exists(JSON_FILE):
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                clean = re.sub(r",\s*(?=[}\]])", "", content)
                data = json.loads(clean)
                raw_roots = data.get("RootChilds", [])
                self.root_items = [item for item in raw_roots if item.get("Name") != "DEV"]
                self.active_rows = [self.root_items]
                self.selected_indices = [-1]
        
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

    def update_live_search(self):
        if self.search_query != "":
            self.active_rows = [self.root_items]
            self.selected_indices = [-1]
        query = self.search_query.lower()
        results = []
        if query:
            def walk(items):
                for item in items:
                    if not item.get("IsFolder"):
                        if query in item.get("Name", "").lower(): results.append(item)
                    else: walk(item.get("Childs", []))
            walk(self.root_items)
        self.search_results = results[:80] # Slightly more results
        self.selected_search_idx = -1

    def reset_navigation(self):
        self.active_rows = [self.root_items]
        self.selected_indices = [-1]
        self.search_query = ""
        self.search_results = []
        self.selected_search_idx = -1

    def find_first_block_name(self, item):
        if not item.get("IsFolder", False): return item.get("Name")
        children = item.get("Childs", [])
        return self.find_first_block_name(children[0]) if children else None

    def select_item(self, row_idx, item_idx, is_search_result=False):
        if is_search_result:
            item = self.search_results[item_idx]
            self.selected_block_name = item.get("Name")
            self.selected_search_idx = item_idx
            return
        
        item = self.active_rows[row_idx][item_idx]
        self.active_rows = self.active_rows[:row_idx + 1]
        self.selected_indices = self.selected_indices[:row_idx + 1]
        self.selected_indices[row_idx] = item_idx
        
        if item.get("IsFolder") and item.get("Childs"):
            self.active_rows.append(item.get("Childs"))
            self.selected_indices.append(-1)
        else:
            self.selected_block_name = item.get("Name")

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
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)

def draw_card(x, y, item, index, is_active, is_leaf, is_last_sel, scale, shader_flat, shader_img):
    is_folder = item.get("IsFolder", False)
    cw, ch = 105 * scale, 130 * scale
    
    if is_last_sel:
        base_col, tab_col = (0.95, 0.95, 0.95, 1.0), (0.4, 0.6, 1.0, 1.0)
    elif is_active:
        base_col, tab_col = (0.1, 0.85, 0.45, 0.95), (0.0, 1.0, 0.6, 1.0)
    elif is_leaf and not is_folder:
        base_col, tab_col = (0.5, 0.5, 0.5, 0.8), (0.3, 0.3, 0.3, 1.0)
    else:
        base_col, tab_col = (1.0, 0.75, 0.0, 0.95), (0.0, 0.7, 0.3, 1.0)

    draw_rect(x, y, cw, ch * 0.85, base_col, shader_flat)
    draw_rect(x, y + (ch * 0.85) - (4 * scale), 38 * scale, 22 * scale, tab_col, shader_flat)
    blf.color(0, 1, 1, 1, 1); blf.size(0, round(15 * scale))
    blf.position(0, x + (8 * scale), y + (ch * 0.85) + (2 * scale), 0); blf.draw(0, str(index + 1))
    
    icon_name = item.get("Name") if not is_folder else tm_manager.find_first_block_name(item)
    if icon_name and icon_name in tm_manager.icons:
        tex = tm_manager.icons.get(icon_name)
        if tex:
            si = 95 * scale
            ix, iy = x + (cw - si)/2, y + (8 * scale)
            gpu.state.blend_set('ALPHA')
            v = ((ix, iy), (ix + si, iy), (ix + si, iy + si), (ix, iy + si))
            uv = ((0,0),(1,0),(1,1),(0,1)); batch = batch_for_shader(shader_img, 'TRI_FAN', {"pos": v, "texCoord": uv})
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
    has_search = tm_manager.search_query != ""
    
    # Standardize Column calculation
    cols = max(1, int(tm_manager.ui_width // slot_w))

    # Width Calculation
    max_items_in_tree = max(len(row) for row in tm_manager.active_rows)
    search_row_width = min(len(tm_manager.search_results), cols) if has_search else 0
    tm_manager.current_visible_width = max((max(max_items_in_tree, search_row_width) * slot_w) + margin, 620 * s) 

    search_rows_count = ((len(tm_manager.search_results) - 1) // cols + 1) if has_search else 0
    total_h = (len(tm_manager.active_rows) + search_rows_count) * row_h
    
    # Bottom bar
    draw_rect(tm_manager.ui_pos_x, tm_manager.ui_pos_y - bar_h, tm_manager.current_visible_width, bar_h, (0.01, 0.01, 0.01, 1.0), shader_flat)
    draw_rect(tm_manager.ui_pos_x + tm_manager.current_visible_width - bar_h, tm_manager.ui_pos_y - bar_h, bar_h, bar_h, (0.3, 0.3, 0.3, 1.0), shader_flat)
    
    hx = tm_manager.ui_pos_x + tm_manager.current_visible_width - (bar_h * 2) - 2
    draw_rect(hx, tm_manager.ui_pos_y - bar_h, bar_h, bar_h, (0.2, 0.2, 0.2, 1.0), shader_flat)
    blf.size(0, round(20 * s)); blf.color(0, 1, 1, 1, 1)
    q_tw, q_th = blf.dimensions(0, "?")
    blf.position(0, hx + (bar_h - q_tw)/2, (tm_manager.ui_pos_y - bar_h) + (bar_h - q_th)/2 + (2*s), 0); blf.draw(0, "?")

    search_w = 280 * s
    sx, sy = hx - search_w - (5 * s), tm_manager.ui_pos_y - bar_h + (3 * s)
    search_bg = (0.05, 0.35, 0.7, 1.0) if tm_manager.is_searching else (0.1, 0.1, 0.1, 1.0)
    draw_rect(sx, sy, search_w, bar_h - (6*s), search_bg, shader_flat)
    blf.size(0, round(14 * s)); blf.color(0, 1, 1, 1, 1); blf.position(0, sx + 10, sy + 7, 0)
    blf.draw(0, f"{tm_manager.search_query}|" if tm_manager.is_searching else (tm_manager.search_query if has_search else "Search..."))
    
    # Footer Truncation
    available_text_space = sx - tm_manager.ui_pos_x - (20 * s)
    full_text = f"TM2020 | {tm_manager.selected_block_name}" if tm_manager.selected_block_name != "None" else "TM2020 | Select a block"
    blf.size(0, round(17 * s)); blf.color(0, 1, 1, 1, 1)
    tw_text, _ = blf.dimensions(0, full_text)
    d_text = full_text
    if tw_text > available_text_space and available_text_space > 50:
        d_text = full_text[:int(len(full_text) * (available_text_space / tw_text)) - 3] + "..."
    if available_text_space > 30:
        blf.position(0, tm_manager.ui_pos_x + 10, tm_manager.ui_pos_y - (bar_h * 0.7), 0); blf.draw(0, d_text)

    # Render contents
    for r_idx, row_items in enumerate(tm_manager.active_rows):
        ry = tm_manager.ui_pos_y + (r_idx * row_h) + (10 * s)
        sel_i = tm_manager.selected_indices[r_idx]
        is_leaf = not any(i.get("IsFolder") for i in row_items)
        is_deepest_row = (r_idx == len(tm_manager.active_rows) - 1) and not has_search
        for i, item in enumerate(row_items):
            rx = tm_manager.ui_pos_x + margin + i * slot_w
            if rx + (105 * s) > tm_manager.ui_pos_x + tm_manager.current_visible_width: break
            is_in_path = (i == sel_i)
            is_last_sel = (item.get("Name") == tm_manager.selected_block_name) or (is_in_path and is_deepest_row)
            draw_card(rx, ry, item, i, is_in_path, is_leaf, is_last_sel, s, shader_flat, shader_img)

    if has_search:
        start_row_idx = len(tm_manager.active_rows)
        for i, item in enumerate(tm_manager.search_results):
            rx = tm_manager.ui_pos_x + margin + (i % cols) * slot_w
            ry = tm_manager.ui_pos_y + ((start_row_idx + (i // cols)) * row_h) + (10 * s)
            is_last_sel = (item.get("Name") == tm_manager.selected_block_name)
            draw_card(rx, ry, item, i, False, True, is_last_sel, s, shader_flat, shader_img)

    if self.is_hovering_help:
        tw_p, th_p = 380 * s, 260 * s
        tx, ty = tm_manager.ui_pos_x + tm_manager.current_visible_width + 10, tm_manager.ui_pos_y - bar_h
        draw_rect(tx, ty, tw_p, th_p, (0, 0, 0, 0.95), shader_flat)
        blf.size(0, round(15 * s)); blf.color(0, 1, 1, 1, 1)
        lines = ["--- TM2020 INVENTORY HELP ---", "", "- L-Click Map: Open Folder", "- L-Click Block: Select Block", "- R-Click Window: Go back one level", "- Mouse-Drag: Move window", "- Bottom-Right Corner: Resize UI", "- TYPE in Search: Auto-filter blocks", "- DELETE Key: Clear search field", "- Ctrl+V: Paste block name", "- Click Bottom Bar: Copy name to clipboard", "- Press ESC Key: Close Addon"]
        for i, line in enumerate(lines):
            blf.position(0, tx + 15, ty + th_p - (21 * s * (i+1)), 0); blf.draw(0, line)

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
        slot_w = 105 * s + 10 * s
        cols = max(1, int(tm_manager.ui_width // slot_w))
        mx, my = event.mouse_region_x, event.mouse_region_y
        cur_w = tm_manager.current_visible_width
        hx = tm_manager.ui_pos_x + cur_w - (bar_h * 2) - 2
        sx, sy = hx - (280 * s) - (5 * s), tm_manager.ui_pos_y - bar_h

        # Zones
        in_search = (sx <= mx <= sx + 280*s) and (sy <= my <= sy + bar_h)
        in_help = (hx <= mx <= hx + bar_h) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)
        in_bottom_bar = (tm_manager.ui_pos_x <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)
        in_resize = (tm_manager.ui_pos_x + cur_w - bar_h <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y - bar_h <= my <= tm_manager.ui_pos_y)
        
        has_search = tm_manager.search_query != ""
        search_rows = ((len(tm_manager.search_results) - 1) // cols + 1) if has_search else 0
        total_h = (len(tm_manager.active_rows) + search_rows) * row_h
        in_ui_body = (tm_manager.ui_pos_x <= mx <= tm_manager.ui_pos_x + cur_w) and (tm_manager.ui_pos_y <= my <= tm_manager.ui_pos_y + total_h)

        self.is_hovering_help = in_help

        if tm_manager.is_searching:
            if event.value in {'PRESS', 'REPEAT'}:
                if event.type == 'BACKSPACE': 
                    tm_manager.search_query = tm_manager.search_query[:-1]; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.type == 'DEL': 
                    tm_manager.search_query = ""; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.ctrl and event.type == 'V': 
                    tm_manager.search_query += context.window_manager.clipboard; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
                elif event.type in {'RET', 'NUMPAD_ENTER', 'ESC'}: 
                    tm_manager.is_searching = False; return {'RUNNING_MODAL'}
                elif event.unicode and ord(event.unicode) > 31: 
                    tm_manager.search_query += event.unicode; tm_manager.update_live_search(); return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and not in_search:
                tm_manager.is_searching = False
            else: return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Priority: Resize
            if in_resize: self.is_scaling = True; return {'RUNNING_MODAL'}
            # Priority: Search
            if in_search: tm_manager.is_searching = True; return {'RUNNING_MODAL'}
            # Priority: Copy Bar
            if in_bottom_bar and not in_help:
                if tm_manager.selected_block_name != "None":
                    context.window_manager.clipboard = tm_manager.selected_block_name
                    self.report({'INFO'}, f"Copied: {tm_manager.selected_block_name}")
                self.is_dragging = True; self.drag_offset = [tm_manager.ui_pos_x - mx, tm_manager.ui_pos_y - my]
                return {'RUNNING_MODAL'}

            if in_ui_body:
                tm_manager.is_searching = False
                item_hit = False
                # 1. Check Search Results
                if has_search:
                    start_row_idx = len(tm_manager.active_rows)
                    for i, _ in enumerate(tm_manager.search_results):
                        ix = tm_manager.ui_pos_x + (10*s) + (i % cols) * slot_w
                        iy = tm_manager.ui_pos_y + (10*s) + ((start_row_idx + (i // cols)) * row_h)
                        if ix < mx < ix + 105*s and iy < my < iy + 130*s:
                            tm_manager.select_item(0, i, True); item_hit = True; break
                # 2. Check Nav Tree
                if not item_hit:
                    r_idx = int((my - tm_manager.ui_pos_y - (10 * s)) // row_h)
                    if 0 <= r_idx < len(tm_manager.active_rows):
                        for i, _ in enumerate(tm_manager.active_rows[r_idx]):
                            ix = tm_manager.ui_pos_x + (10*s) + i * slot_w
                            if ix < mx < ix + 105*s:
                                if r_idx == 0: tm_manager.reset_navigation()
                                tm_manager.select_item(r_idx, i); item_hit = True; break
                # 3. Default Drag
                if not item_hit: self.is_dragging = True; self.drag_offset = [tm_manager.ui_pos_x - mx, tm_manager.ui_pos_y - my]
                return {'RUNNING_MODAL'}

        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS' and (in_ui_body or in_bottom_bar):
            tm_manager.go_back(); return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE': self.is_dragging = self.is_scaling = False
        if event.type == 'MOUSEMOVE':
            if self.is_dragging: tm_manager.ui_pos_x, tm_manager.ui_pos_y = mx + self.drag_offset[0], my + self.drag_offset[1]; return {'RUNNING_MODAL'}
            if self.is_scaling: 
                tm_manager.ui_width = max(620, mx - tm_manager.ui_pos_x)
                return {'RUNNING_MODAL'}
        if event.type == 'ESC':
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            return {'CANCELLED'}
        return {'PASS_THROUGH'} if not (in_ui_body or in_bottom_bar or in_search or self.is_dragging) else {'RUNNING_MODAL'}

    def invoke(self, context, event):
        tm_manager.start_load()
        self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

addon_keymaps = []
def register():
    bpy.utils.register_class(VIEW3D_OT_tm_inventory)
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new(VIEW3D_OT_tm_inventory.bl_idname, 'I', 'PRESS', ctrl=True, shift=True)
        addon_keymaps.append((km, kmi))

def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_tm_inventory)
    for km, kmi in addon_keymaps: km.keymap_items.remove(kmi)
    addon_keymaps.clear()

if __name__ == "__main__":
    register()