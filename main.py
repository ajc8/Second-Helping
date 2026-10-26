"""Second Helping: use your food, or share it, before it goes to waste."""
import os
import threading
import uuid
import flet as ft
import pantry
import scanner

UPLOAD_DIR = "uploads"
WIDE = 860
GREEN = ft.Colors.GREEN_700
COLORS = {"now": ft.Colors.RED_700, "soon": ft.Colors.ORANGE_700,
          "give": ft.Colors.BLUE_700, "ok": ft.Colors.GREEN_700}
FOOD_BANKS = "https://www.feedingamerica.org/find-your-local-foodbank"
EXTS = ["jpg", "jpeg", "png", "webp", "gif", "pdf"]
SMALL = ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=10, vertical=2))


def main(page: ft.Page):
    page.title = "Second Helping"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.GREEN)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.GREEN)
    page.padding = 0
    if not page.web and page.platform in (ft.PagePlatform.WINDOWS,
                                          ft.PagePlatform.MACOS, ft.PagePlatform.LINUX):
        page.window.width, page.window.height = 1180, 720
        page.window.min_width, page.window.min_height = 760, 560

    state = pantry.load(page.client_storage)

    def persist():
        pantry.save(page.client_storage, state)

    name = ft.TextField(label="Food", max_length=50, dense=True)
    best_by = ft.TextField(label="Best by date", hint_text="YYYY-MM-DD, e.g. 2026-12-31",
                           dense=True, keyboard_type=ft.KeyboardType.DATETIME)
    kind = ft.Dropdown(label="Type", value="shelf", dense=True, options=[
        ft.dropdown.Option("shelf", "Shelf-stable (cans, rice, flour)"),
        ft.dropdown.Option("fresh", "Fresh or refrigerated")])
    msg = ft.Text(size=14, expand=True)
    busy = ft.ProgressRing(visible=False, width=22, height=22)
    items_view = ft.ListView(spacing=8, expand=True)
    review_view = ft.ListView(spacing=8, expand=True)
    rows = []
    used_t, gave_t, tossed_t = (ft.Text("0", size=24, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.WHITE) for _ in range(3))

    def say(text, error=False):
        msg.value = text
        msg.color = ft.Colors.RED_700 if error else None
        page.update()

    def panel(title, body, extra=None, fill=False):
        col = ft.Column([ft.Row([ft.Text(title, size=16, weight=ft.FontWeight.W_600,
                                         expand=True)] + ([extra] if extra else [])),
                         *body], spacing=10, expand=fill)
        box = ft.Container(col, padding=14, border_radius=12, expand=fill,
                           bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
                           border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT))
        return box, col

    def stat(value, label):
        return ft.Container(ft.Column([value, ft.Text(label, size=11, color=ft.Colors.WHITE70)],
                                      spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.symmetric(horizontal=14, vertical=6),
                            border_radius=10, bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.WHITE))

    # pantry actions
    def act(item, key):
        state["items"] = [i for i in state["items"] if i["id"] != item["id"]]
        state[key] += 1
        persist()
        msg.color = None
        msg.value = {"gave": f"Thank you. {item['name']} is going to someone who needs it.",
                     "used": f"{item['name']} eaten in time.",
                     "tossed": f"{item['name']} removed."}[key]
        render()

    def card(item):
        level, label, hint = pantry.status(item)
        btns = [ft.OutlinedButton("I ate it", style=SMALL, on_click=lambda e: act(item, "used"))]
        if pantry.can_donate(item):
            btns.append(ft.OutlinedButton("I donated it", style=SMALL,
                                          on_click=lambda e: act(item, "gave")))
        btns.append(ft.OutlinedButton("Threw it out", style=SMALL,
                                      on_click=lambda e: act(item, "tossed")))
        body = [ft.Row([ft.Text(item["name"], weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(label, color=COLORS[level], weight=ft.FontWeight.W_600)])]
        if hint:
            body.append(ft.Text(hint, size=12))
        body.append(ft.Row(btns, wrap=True, spacing=6))
        side = ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)
        return ft.Container(ft.Column(body, spacing=4), padding=10, border_radius=10,
                            border=ft.border.only(left=ft.BorderSide(6, COLORS[level]),
                                                  top=side, right=side, bottom=side))

    def add_by_hand(e):
        food = (name.value or "").strip()
        d = pantry.parse_date(best_by.value or "")
        if not food:
            return say("Enter the name of the food.", True)
        if d is None:
            return say("Enter the date as YYYY-MM-DD, for example 2026-12-31.", True)
        state["items"].append({"id": uuid.uuid4().hex, "name": food,
                               "date": d.isoformat(), "type": kind.value})
        persist()
        name.value = best_by.value = ""
        msg.color = None
        msg.value = f"{food} added."
        render()

    # review of scanned items
    def show_review(found):
        rows.clear()
        review_view.controls = []
        for it in found:
            r = {"item": it, "use": ft.Checkbox(value=True),
                 "name": ft.TextField(value=it["name"], expand=True, dense=True),
                 "date": ft.TextField(value=it["date"], width=140, dense=True)}
            note = "Date read from the label." if it["read"] else \
                "Estimated date. Change it if you know the real one."
            rows.append(r)
            review_view.controls.append(ft.Container(ft.Column([
                ft.Row([r["use"], r["name"]]),
                ft.Row([r["date"], ft.Text(note, size=12, expand=True)])], spacing=2),
                padding=8, border_radius=10, border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT)))

    def discard(e=None):
        rows.clear()
        review_view.controls = []
        render()

    def confirm(e):
        added, bad = 0, 0
        for r in list(rows):
            if not r["use"].value:
                rows.remove(r)
                continue
            d = pantry.parse_date(r["date"].value or "")
            nm = (r["name"].value or "").strip()
            if not nm or d is None:
                bad += 1
                continue
            state["items"].append({"id": uuid.uuid4().hex, "name": nm,
                                   "date": d.isoformat(), "type": r["item"]["type"]})
            added += 1
            rows.remove(r)
        persist()
        if bad:
            msg.color = ft.Colors.RED_700
            msg.value = f"{added} added. {bad} still need a name and a date like 2026-12-31."
        else:
            msg.color = None
            msg.value = f"{added} item{'s' if added != 1 else ''} added to your pantry."
            review_view.controls = []
        render()

    # scanning
    def scan_worker(paths, cleanup=False):
        found, error = [], None
        for p in paths:
            try:
                found += scanner.scan_image(p)
            except scanner.ScanError as err:
                error = str(err)
                break
            except Exception as err:  # never fail silently
                error = f"Unexpected error: {err}"
                break
        if cleanup:
            for p in paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
        busy.visible = False
        if error:
            msg.color, msg.value = ft.Colors.RED_700, error
        elif not found:
            msg.color, msg.value = ft.Colors.RED_700, "No food found. Try a clearer photo."
        else:
            msg.color = None
            msg.value = f"Found {len(found)} item{'s' if len(found) != 1 else ''}. Check them and tap Add."
            show_review(found)
        render()

    up = {"dest": {}, "paths": [], "left": 0, "done": set()}

    def start_scan(paths, cleanup):
        threading.Thread(target=scan_worker, args=(paths, cleanup), daemon=True).start()

    def on_picked(e: ft.FilePickerResultEvent):
        files = e.files or []
        if not files:
            return
        busy.visible = True
        say(f"Reading {len(files)} file{'s' if len(files) != 1 else ''}... this takes a few seconds.")
        if page.web:
            up.update(dest={}, paths=[], left=len(files), done=set())
            uploads = []
            for f in files:
                dest = uuid.uuid4().hex + os.path.splitext(f.name)[1].lower()
                up["dest"][f.name] = dest
                uploads.append(ft.FilePickerUploadFile(
                    f.name, upload_url=page.get_upload_url(dest, 120)))
            picker.upload(uploads)
        else:
            start_scan([f.path for f in files if f.path], False)

    def on_upload(e: ft.FilePickerUploadEvent):
        if e.error:
            busy.visible = False
            return say("The upload failed. Try again.", True)
        if e.progress == 1.0 and e.file_name not in up["done"]:
            up["done"].add(e.file_name)
            up["paths"].append(os.path.join(UPLOAD_DIR, up["dest"][e.file_name]))
            if len(up["done"]) == up["left"]:
                start_scan(up["paths"], True)

    picker = ft.FilePicker(on_result=on_picked, on_upload=on_upload)
    page.overlay.append(picker)

    def pick(e):
        picker.pick_files(allow_multiple=True, file_type=ft.FilePickerFileType.CUSTOM,
                          allowed_extensions=EXTS)

    # panels
    scan_box, _ = panel("Scan photos or a receipt", [
        ft.Text("Photograph your groceries, or upload a bill. You check what it "
                "found before anything is added.", size=13),
        ft.Row([ft.FilledButton("Choose photos or PDF", icon=ft.Icons.PHOTO_CAMERA,
                                on_click=pick), busy]),
        ft.Text("Files are sent to Google's Gemini to be read. On the free tier Google "
                "may use them to improve its products, so crop out names and card numbers.",
                size=11)])
    add_box, _ = panel("Add by hand", [
        name, best_by, kind, ft.FilledButton("Add to pantry", on_click=add_by_hand)])
    pantry_box, pantry_col = panel(
        "Your pantry", [items_view], fill=True,
        extra=ft.TextButton("Find a food bank", icon=ft.Icons.OPEN_IN_NEW, url=FOOD_BANKS))
    review_box, review_col = panel(
        "Is this right?", [
            ft.Text("Uncheck anything wrong and fix names or dates.", size=13),
            review_view,
            ft.Row([ft.FilledButton("Add checked items", on_click=confirm),
                    ft.TextButton("Discard", on_click=discard)])], fill=True)

    def render():
        used_t.value, gave_t.value, tossed_t.value = (
            str(state["used"]), str(state["gave"]), str(state["tossed"]))
        items_view.controls = [card(i) for i in pantry.sort_items(state["items"])] or [
            ft.Text("Nothing here yet. Scan a photo or add what's in your kitchen, "
                    "and we'll tell you what to eat first.")]
        review_box.visible = bool(rows)
        pantry_box.visible = not rows
        page.update()

    mode = {"wide": None}

    def build():
        wide = (page.width or 1000) >= WIDE
        mode["wide"] = wide
        for box, col, view in ((pantry_box, pantry_col, items_view),
                               (review_box, review_col, review_view)):
            box.expand = col.expand = view.expand = wide
            view.height = None if wide else 340
        header = ft.Container(ft.Row([
            ft.Column([ft.Text("Second Helping", size=26, weight=ft.FontWeight.BOLD,
                               color=ft.Colors.WHITE),
                       ft.Text("Eat it, or share it, before it goes to waste.",
                               color=ft.Colors.WHITE70)], spacing=0),
            ft.Row([stat(used_t, "eaten in time"), stat(gave_t, "donated"),
                    stat(tossed_t, "wasted")], spacing=8)],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
            bgcolor=GREEN, padding=ft.padding.symmetric(horizontal=20, vertical=12))
        footer = ft.Container(ft.Row([msg]), padding=ft.padding.symmetric(horizontal=20, vertical=8),
                              border=ft.border.only(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)))
        right = ft.Column([pantry_box, review_box], spacing=12, expand=wide)
        if wide:
            left = ft.Column([scan_box, add_box], spacing=12, width=390)
            body = ft.Container(ft.Row([left, right], spacing=16, expand=True,
                                       vertical_alignment=ft.CrossAxisAlignment.START),
                                padding=16, expand=True)
            root = ft.Column([header, body, footer], spacing=0, expand=True)
            page.scroll = None
        else:
            body = ft.Container(ft.Column([scan_box, add_box, right], spacing=12), padding=12)
            root = ft.Column([header, body, footer], spacing=0)
            page.scroll = ft.ScrollMode.AUTO
        page.controls.clear()
        page.add(ft.SafeArea(root, expand=wide))
        render()

    def on_resize(e):
        if ((page.width or 1000) >= WIDE) != mode["wide"]:
            build()

    page.on_resize = on_resize
    build()


os.makedirs(UPLOAD_DIR, exist_ok=True)
if os.getenv("PORT"):
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0",
           port=int(os.environ["PORT"]), upload_dir=UPLOAD_DIR)
else:
    ft.app(target=main, upload_dir=UPLOAD_DIR)
