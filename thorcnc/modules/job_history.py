"""Job History Module for ThorCNC.

Beim *Load to machine* wird die G-Code-Datei immer zuerst lokal nach
``<PROGRAM_PREFIX>/jobs`` kopiert und von dort gefahren — nie direkt vom
USB-Stick oder einer instabilen SMB-Freigabe.

Ist die Job-History eingeschaltet (Settings ``job_history_enabled``), wird jede
Datei zusätzlich datiert unter ``jobs/JJJJ/MM/TT/HHMMSS_<name>.ngc`` abgelegt,
beim Laden ein Top-Ansicht-Screenshot des Backplots erzeugt und – sobald der Job
wirklich gestartet wurde – ein Eintrag in ``jobs/history.json`` protokolliert
(Status ok / cancelled / error). Der History-Tab unter *Status* listet die Jobs
mit Vorschaubild auf.
"""

import os
import json
import shutil
import linuxcnc
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtWidgets import (QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QListWidget, QListWidgetItem, QPushButton,
                               QMessageBox)

from .base import ThorModule
from ._theme_utils import theme_color
from ..i18n import _t

_STATUS_LABEL = {
    "running":   "running …",
    "ok":        "OK",
    "cancelled": "Cancelled",
    "error":     "Error",
}
_STATUS_COLOR_KEY = {
    "running":   "text.primary",
    "ok":        "success",
    "cancelled": "warning",
    "error":     "error",
}


class JobHistoryModule(ThorModule):
    """Staging nach jobs/, Job-Protokoll und History-Tab."""

    def setup(self):
        self._origin_map: dict[str, str] = {}   # staged (normpath) -> original
        self._pending: dict | None = None        # geladen, noch nicht gelaufen
        self._active: dict | None = None          # gerade laufender Eintrag
        self._run_had_error = False
        self._prev_interp = None
        self._history: list[dict] = []
        self._t._job_abort_requested = False

        # Programm-Ende entprellen: ein kurzer Read-Ahead-/MDI-bedingter IDLE
        # mitten im Lauf darf nicht als „fertig" gewertet werden.
        self._finalize_timer = QTimer()
        self._finalize_timer.setSingleShot(True)
        self._finalize_timer.setInterval(900)
        self._finalize_timer.timeout.connect(self._finalize_run)

        self._load_history()
        self._build_history_tab()
        self._refresh_history_list()

    def connect_signals(self):
        p = self._t.poller
        if not p:
            return
        p.interp_changed.connect(self._on_interp)
        p.error_message.connect(self._on_error_message)

    def teardown(self):
        # Nie gestartete, gestagete Datei (History an) wieder entfernen.
        if self._pending and not self._pending.get("_committed"):
            self._remove_files(self._pending)

    # ── Pfade ─────────────────────────────────────────────────────────────────

    def _nc_files_dir(self) -> str:
        d = getattr(self._t, "_nc_files_dir", None)
        if d and os.path.isdir(d):
            return d
        # Fallback: gleiche Auflösung wie der File-Browser.
        start = os.path.expanduser("~/linuxcnc/nc_files")
        if self._t.ini and self._t.ini_path:
            cfg = self._t.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if cfg:
                cfg = os.path.expanduser(cfg)
                if not os.path.isabs(cfg):
                    cfg = os.path.abspath(os.path.join(
                        os.path.dirname(self._t.ini_path), cfg))
                start = cfg
        return start

    def _jobs_root(self) -> str:
        root = os.path.join(self._nc_files_dir(), "jobs")
        os.makedirs(root, exist_ok=True)
        return root

    def _history_json(self) -> str:
        return os.path.join(self._jobs_root(), "history.json")

    # ── Staging ─────────────────────────────────────────────────────────────────

    def stage_job(self, src: str) -> str:
        """Kopiert ``src`` nach jobs/ und gibt den zu fahrenden Pfad zurück.

        Liegt ``src`` bereits in jobs/, wird er unverändert zurückgegeben.
        """
        if not src or not os.path.isfile(src):
            return src

        root = self._jobs_root()
        if os.path.normpath(src).startswith(os.path.normpath(root) + os.sep):
            return src  # bereits gestaged (z.B. Re-Run aus History)

        history_on = bool(self._t.settings.get("job_history_enabled", False))

        if not history_on:
            target = os.path.join(root, "tmp.ngc")
            try:
                shutil.copyfile(src, target)
            except Exception as e:
                self._t._status(_t("Job copy failed: {}").format(e), error=True)
                return src
            self._origin_map[os.path.normpath(target)] = src
            return target

        # History an: vorherigen, nie gestarteten Pending aufräumen.
        if self._pending and not self._pending.get("_committed"):
            self._remove_files(self._pending)

        now = datetime.now()
        day_dir = os.path.join(root, now.strftime("%Y"), now.strftime("%m"),
                               now.strftime("%d"))
        os.makedirs(day_dir, exist_ok=True)
        stamp = now.strftime("%H%M%S")
        base = os.path.basename(src)
        staged = os.path.join(day_dir, f"{stamp}_{base}")
        thumb = os.path.splitext(staged)[0] + ".png"
        try:
            shutil.copyfile(src, staged)
        except Exception as e:
            self._t._status(_t("Job-Kopie fehlgeschlagen: {}").format(e), error=True)
            return src

        self._origin_map[os.path.normpath(staged)] = src
        self._pending = {
            "id": now.strftime("%Y%m%d-%H%M%S"),
            "name": base,
            "original": src,
            "staged": staged,
            "thumbnail": None,
            "loaded_at": now.isoformat(timespec="seconds"),
            "_committed": False,
            "_thumb_path": thumb,
        }
        # Vorschau kurz nach dem Laden rendern (program_open zuerst durchlassen).
        QTimer.singleShot(50, self._capture_thumbnail)
        return staged

    def _capture_thumbnail(self):
        p = self._pending
        if not p or p.get("thumbnail"):
            return
        thumb = p.get("_thumb_path")
        # Vorschau deterministisch aus den geparsten Bahnen rendern (2D-Top-Ansicht).
        try:
            from ..gcode_parser import parse_file
            segments = parse_file(p["staged"])
        except Exception:
            segments = self._t._last_toolpath
        ok = self._render_thumbnail(thumb, segments)
        if not (ok and os.path.isfile(thumb)):
            return
        p["thumbnail"] = thumb
        # Falls der Job schon gestartet wurde, alle Einträge derselben Datei nachziehen.
        if p.get("_committed"):
            changed = False
            for entry in self._history:
                if entry.get("staged") == p.get("staged") and not entry.get("thumbnail"):
                    entry["thumbnail"] = thumb
                    changed = True
            if changed:
                self._save_history()
                self._refresh_history_list()

    def _render_thumbnail(self, path: str, segments, size=(640, 480)) -> bool:
        """Rendert die Toolpath als saubere 2D-Top-Ansicht (X-Y), zentriert und
        seitenrichtig — unabhängig von OpenGL/Treiber."""
        from PySide6.QtGui import QImage, QPainter, QPen, QColor
        from PySide6.QtCore import QPointF
        from ..gcode_parser import bounding_box, RAPID, FEED, ARC
        if not segments:
            return False
        mn_x, mx_x, mn_y, mx_y, _, _ = bounding_box(segments)
        w, h = int(size[0]), int(size[1])
        margin = 22.0
        span_x = max(mx_x - mn_x, 1e-6)
        span_y = max(mx_y - mn_y, 1e-6)
        scale = min((w - 2 * margin) / span_x, (h - 2 * margin) / span_y)
        off_x = margin + ((w - 2 * margin) - span_x * scale) / 2.0
        off_y = margin + ((h - 2 * margin) - span_y * scale) / 2.0

        def to_px(x, y):
            # Y nach unten kippen (G-Code +Y = oben, Bild +Y = unten).
            return QPointF(off_x + (x - mn_x) * scale,
                           off_y + (mx_y - y) * scale)

        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor("#0d1117"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = {RAPID: QColor(210, 70, 70), FEED: QColor(230, 230, 230),
               ARC: QColor(70, 200, 220)}
        for seg in segments:
            pts = seg.points
            if not pts or len(pts) < 2:
                continue
            pen = QPen(col.get(seg.kind, QColor(230, 230, 230)))
            pen.setWidthF(1.4)
            pen.setCosmetic(True)
            if seg.kind == RAPID:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            prev = to_px(pts[0][0], pts[0][1])
            for q in pts[1:]:
                cur = to_px(q[0], q[1])
                painter.drawLine(prev, cur)
                prev = cur
        painter.end()
        try:
            return bool(img.save(path))
        except Exception:
            return False

    # ── Run-Lifecycle ───────────────────────────────────────────────────────────

    def _on_error_message(self, _msg: str):
        if self._active:
            self._run_had_error = True

    def _on_interp(self, state: int):
        self._prev_interp = state

        if state == linuxcnc.INTERP_IDLE:
            # Mögliches Programmende — entprellt finalisieren (siehe _finalize_run).
            if self._active is not None:
                self._finalize_timer.start()
            return

        # Nicht-IDLE (READING/WAITING/PAUSED): definitiv kein Ende.
        self._finalize_timer.stop()

        try:
            auto = self._t.poller.stat.task_mode == linuxcnc.MODE_AUTO
        except Exception:
            auto = False
        running = state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        if auto and running and self._active is None and self._pending is not None:
            self._maybe_start_run()

    def _maybe_start_run(self):
        try:
            cur = os.path.normpath(self._t.poller.stat.file or "")
        except Exception:
            cur = ""
        staged = os.path.normpath(self._pending.get("staged", ""))
        user = os.path.normpath(getattr(self._t, "_user_program", "") or "")
        if cur != staged or staged != user:
            return  # läuft eine Sub (Probing/Surface), nicht das User-Programm

        entry = {k: self._pending[k] for k in
                 ("name", "original", "staged", "thumbnail", "loaded_at")}
        started = datetime.now()
        # Eindeutige id pro Lauf (mehrere Läufe derselben geladenen Datei möglich).
        base_id = started.strftime("%Y%m%d-%H%M%S")
        existing = {e.get("id") for e in self._history}
        job_id, n = base_id, 1
        while job_id in existing:
            n += 1
            job_id = f"{base_id}-{n}"
        entry["id"] = job_id
        entry["started_at"] = started.isoformat(timespec="seconds")
        entry["finished_at"] = None
        entry["status"] = "running"
        self._history.insert(0, entry)
        self._pending["_committed"] = True
        self._active = entry
        self._run_had_error = False
        self._t._job_abort_requested = False
        self._save_history()
        self._refresh_history_list()

    def _finalize_run(self):
        if not self._active:
            return
        # Nur finalisieren, wenn der Interpreter wirklich (noch) idle ist —
        # sonst war es nur ein kurzer Read-Ahead-Idle und der Lauf geht weiter.
        try:
            if self._t.poller.stat.interp_state != linuxcnc.INTERP_IDLE:
                return
        except Exception:
            pass
        aborted = bool(getattr(self._t, "_job_abort_requested", False))
        self._t._job_abort_requested = False
        if aborted:
            status = "cancelled"
        elif self._run_had_error:
            status = "error"
        else:
            status = "ok"
        self._active["status"] = status
        self._active["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self._active = None
        self._save_history()
        self._refresh_history_list()

    # ── Editier-Rückfrage ───────────────────────────────────────────────────────

    def maybe_write_back(self, saved_path: str, content: str):
        """Fragt nach dem Speichern einer gestageten Kopie, ob auch die
        Original-Quelldatei aktualisiert werden soll."""
        if not saved_path:
            return
        orig = self._origin_map.get(os.path.normpath(saved_path))
        if not orig or os.path.normpath(orig) == os.path.normpath(saved_path):
            return

        box = QMessageBox(self._t.ui)
        box.setWindowTitle(_t("Update original?"))
        box.setText(_t("The changes were saved to the job copy.\n"
                       "Update the original file as well?\n\n{}")
                    .format(orig))
        btn_orig = box.addButton(_t("Also original"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_t("Copy only"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is btn_orig:
            try:
                with open(orig, "w", encoding="utf-8") as f:
                    f.write(content)
                self._t._status(_t("Original updated: {}").format(
                    os.path.basename(orig)))
            except Exception as e:
                self._t._status(_t("Original update failed: {}").format(e),
                                error=True)

    # ── History-JSON ─────────────────────────────────────────────────────────────

    def _load_history(self):
        path = self._history_json()
        if not os.path.isfile(path):
            self._history = []
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._history = data.get("jobs", []) if isinstance(data, dict) else []
        except Exception:
            self._history = []

    def _save_history(self):
        try:
            with open(self._history_json(), "w", encoding="utf-8") as f:
                json.dump({"jobs": self._history}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._t._status(_t("Saving history failed: {}").format(e),
                            error=True)

    def _remove_files(self, entry: dict):
        # Gemeinsam genutzte Dateien schützen: referenziert ein anderer Eintrag
        # dieselbe gestagete Datei (mehrere Läufe einer Ladung), nichts löschen.
        staged = entry.get("staged")
        if staged:
            for e in self._history:
                if e is not entry and e.get("staged") == staged:
                    return
        for key in ("staged", "thumbnail", "_thumb_path"):
            p = entry.get(key)
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    # ── History-Tab (unter Status) ────────────────────────────────────────────

    def _build_history_tab(self):
        log = self._t.ui.findChild(QListWidget, "status_log")
        if log is None:
            return
        page = log.parentWidget()
        lay = page.layout() if page else None
        if lay is None:
            return

        lay.removeWidget(log)

        tabs = QTabWidget(page)
        tabs.setObjectName("status_subtabs")
        self._tabs = tabs

        log_page = QWidget()
        log_lay = QVBoxLayout(log_page)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.addWidget(log)
        tabs.addTab(log_page, _t("Log"))

        hist_page = QWidget()
        self._hist_page = hist_page
        hist_lay = QVBoxLayout(hist_page)
        hist_lay.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget()
        self._list.setObjectName("job_history_list")
        self._list.setViewMode(QListWidget.ViewMode.ListMode)
        self._list.setIconSize(QSize(120, 90))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setWordWrap(False)
        self._list.setSpacing(2)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(self._on_history_double_clicked)
        hist_lay.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_reload = QPushButton(_t("Reload"))
        btn_reload.setObjectName("btn_history_reload")
        btn_reload.clicked.connect(self._reload_selected)
        btn_del = QPushButton(_t("Delete"))
        btn_del.setObjectName("btn_history_delete")
        btn_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(btn_reload)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        hist_lay.addLayout(btn_row)

        lay.addWidget(tabs)
        # History-Tab nur einhängen, wenn die Option aktiv ist (siehe _update_history_tab).
        self._update_history_tab()

    def _update_history_tab(self):
        """Blendet den History-Tab je nach Setting ein/aus. Bei nur einem Tab
        wird die Tab-Leiste versteckt — sieht aus wie das einfache Log."""
        tabs = getattr(self, "_tabs", None)
        page = getattr(self, "_hist_page", None)
        if tabs is None or page is None:
            return
        enabled = bool(self._t.settings.get("job_history_enabled", False))
        idx = tabs.indexOf(page)
        if enabled and idx == -1:
            tabs.addTab(page, _t("History"))
        elif not enabled and idx != -1:
            tabs.removeTab(idx)
        if tabs.tabBar():
            tabs.tabBar().setVisible(tabs.count() > 1)

    def _refresh_history_list(self):
        lst = getattr(self, "_list", None)
        if lst is None:
            return
        lst.clear()
        for entry in self._history:
            status = entry.get("status", "")
            label = _t(_STATUS_LABEL.get(status, status))
            when = (entry.get("started_at") or entry.get("loaded_at") or "").replace("T", "  ")
            item = QListWidgetItem(f"{entry.get('name', '?')}   ·   {when}   ·   {label}")
            thumb = entry.get("thumbnail")
            if thumb and os.path.isfile(thumb):
                item.setIcon(QIcon(QPixmap(thumb)))
                # Mouseover: Vorschaubild vergrößert anzeigen (Rich-Text-Tooltip).
                item.setToolTip(f'<img src="{thumb}" width="520">')
            else:
                item.setToolTip(_t("No preview image"))
            col = theme_color(self._t, _STATUS_COLOR_KEY.get(status, "text.primary"))
            item.setForeground(QColor(col))
            lst.addItem(item)

    def _selected_row(self):
        # Zeilen-Index == Index in self._history (Liste wird in gleicher Reihenfolge
        # aufgebaut). Nicht über UserRole-dict gehen — PySide6 kopiert dicts beim
        # Auslesen, wodurch eine Identitätsprüfung fehlschlägt.
        lst = getattr(self, "_list", None)
        if lst is None:
            return None
        row = lst.currentRow()
        return row if 0 <= row < len(self._history) else None

    def _selected_entry(self):
        row = self._selected_row()
        return self._history[row] if row is not None else None

    def _is_busy(self) -> bool:
        """True solange ein Programm läuft/pausiert — dann kein Reload/Delete,
        sonst würde der laufende Job abgewürgt bzw. seine Datei gelöscht."""
        if self._active is not None:
            return True
        try:
            s = self._t.poller.stat
            if s.interp_state != linuxcnc.INTERP_IDLE:
                return True
            if s.task_mode == linuxcnc.MODE_AUTO and s.state == linuxcnc.RCS_EXEC:
                return True
        except Exception:
            pass
        return False

    def _on_history_double_clicked(self, _item):
        self._reload_selected()

    def _reload_selected(self):
        if self._is_busy():
            self._t._status(_t("A program is running — loading not possible."),
                            error=True)
            return
        entry = self._selected_entry()
        if not entry:
            return
        staged = entry.get("staged")
        if not staged or not os.path.isfile(staged):
            self._t._status(_t("Job file no longer exists."), error=True)
            return
        self._t._user_program = staged
        if self._t.poller:
            self._t.poller.reset_file_state()
        self._t.cmd.mode(linuxcnc.MODE_AUTO)
        self._t.cmd.wait_complete()
        self._t.cmd.program_open(staged)
        from PySide6.QtWidgets import QTabWidget
        if tab := self._t._w(QTabWidget, "tabWidget"):
            tab.setCurrentIndex(0)
        self._t._status(_t("Job reloaded: {}").format(entry.get("name", "")))

    def _delete_selected(self):
        if self._is_busy():
            self._t._status(_t("A program is running — deletion not possible."),
                            error=True)
            return
        row = self._selected_row()
        if row is None:
            return
        entry = self._history[row]
        name = entry.get("name", "")
        if QMessageBox.question(
                self._t.ui, _t("Delete entry"),
                _t("Delete history entry “{}” including files?").format(name)
        ) != QMessageBox.StandardButton.Yes:
            return
        self._remove_files(entry)   # entry ist das echte Objekt -> Schutzprüfung greift
        del self._history[row]
        self._save_history()
        self._refresh_history_list()
