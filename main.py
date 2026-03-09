import sys
import os
import json
import re
import html
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import time
import subprocess
import requests
from datetime import datetime
from typing import Any

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QComboBox, QDialog, QSlider,
    QPushButton, QGraphicsDropShadowEffect, QLineEdit, QMessageBox, QFrame,
    QListWidget, QListWidgetItem, QCheckBox, QSpinBox, QMenu, QListView, QDoubleSpinBox, QFileDialog
)
from PyQt6.QtGui import QPixmap, QCursor, QPainter, QColor, QAction, QDesktopServices
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRect, QSettings, QPoint, QTimer, pyqtSignal, QStandardPaths, QUrl
)

if getattr(sys, "frozen", False):
    # In PyInstaller builds, keep app data beside the executable.
    PROJECT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(PROJECT_DIR, "saved_library.json")
COLLECTIONS_FILE = os.path.join(PROJECT_DIR, "collections.json")
APPID_CACHE_FILE = os.path.join(PROJECT_DIR, "steam_appid_cache.json")
STEAM_TAGS_CACHE_FILE = os.path.join(PROJECT_DIR, "steam_tags_cache.json")
COVERS_DIR = os.path.join(PROJECT_DIR, "covers")
CUSTOM_COVERS_DIR = os.path.join(COVERS_DIR, "custom")
MISSING_COVERS_FILE = os.path.join(PROJECT_DIR, "missing_covers.json")
NEW_COLLECTION_OPTION = "*Add New Collection*"


def extract_steam_id64(raw_value: str):
    value = str(raw_value or "").strip()
    if value.isdigit():
        return value
    match = re.search(r"\b(\d{17})\b", value)
    if match:
        return match.group(1)
    return ""

# ---------------- TOP BAR BUTTON STYLE ----------------

def make_topbar_button(text, kind="menu"):
    b = QPushButton(text)
    if kind == "window":
        b.setFixedSize(42, 28)
        b.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #c7d5e0;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.08);
                color: white;
            }
        """)
    else:
        b.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #c7d5e0;
                padding: 6px 10px;
                border: none;
                font-size: 13px;
            }
            QPushButton:hover {
                color: white;
            }
        """)
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    return b


# ---------------- STEAM CAPSULE ----------------

def get_steam_capsule(appid: int, allow_download=True):
    os.makedirs(COVERS_DIR, exist_ok=True)
    local_path = os.path.join(COVERS_DIR, f"{appid}.jpg")

    local_steam_cover = _find_local_steam_library_cover(appid)
    if local_steam_cover:
        try:
            shutil.copyfile(local_steam_cover, local_path)
            return local_path
        except Exception:
            # If copy fails (locked/permissions), still try to use the source path directly.
            return local_steam_cover

    if os.path.exists(local_path):
        return local_path

    if not allow_download:
        return None

    url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200 and r.content:
            with open(local_path, "wb") as f:
                f.write(r.content)
            return local_path
    except Exception:
        pass

    return None


def _looks_like_image_file(path: str):
    try:
        with open(path, "rb") as f:
            header = f.read(16)
    except Exception:
        return False

    if header.startswith(b"\xFF\xD8\xFF"):  # JPEG
        return True
    if header.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
        return True
    if header.startswith(b"RIFF") and b"WEBP" in header:  # WEBP
        return True
    return False


def _find_local_steam_library_cover(appid: int):
    steam_roots = [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
    ]

    for steam_root in steam_roots:
        app_cache_dir = os.path.join(steam_root, "appcache", "librarycache", str(appid))
        if not os.path.isdir(app_cache_dir):
            continue

        # Only use these explicit Steam local library art filenames.
        target_names = {"library_600x900.jpg", "library_capsule.jpg"}
        # Prefer library_600x900 over capsule when both exist.
        priority = {"library_600x900.jpg": 0, "library_capsule.jpg": 1}
        candidates = []
        try:
            for root, _dirs, files in os.walk(app_cache_dir):
                for filename in files:
                    lower = filename.casefold()
                    if lower in target_names:
                        p = os.path.join(root, filename)
                        if os.path.isfile(p) and _looks_like_image_file(p):
                            candidates.append((priority[lower], p))
        except Exception:
            pass

        if candidates:
            candidates.sort(key=lambda c: c[0])
            return candidates[0][1]

    return None


def _load_appid_cache():
    if not os.path.exists(APPID_CACHE_FILE):
        return {}
    try:
        with open(APPID_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_appid_cache(cache):
    try:
        with open(APPID_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _load_steam_tags_cache():
    if not os.path.exists(STEAM_TAGS_CACHE_FILE):
        return {}
    try:
        with open(STEAM_TAGS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_steam_tags_cache(cache):
    try:
        with open(STEAM_TAGS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def get_steam_app_tags(appid: int, allow_network=True):
    try:
        appid = int(appid)
    except Exception:
        return []
    if appid <= 0:
        return []

    cache = _load_steam_tags_cache()
    cached = cache.get(str(appid))
    if isinstance(cached, dict):
        cached_tags = cached.get("tags", [])
        if isinstance(cached_tags, list) and bool(cached.get("includes_community")):
            return [str(t).strip() for t in cached_tags if str(t).strip()]
    elif isinstance(cached, list):
        # Legacy cache entries stored only a plain list. Refresh once when
        # network is available so we can add community tags.
        if not allow_network:
            return [str(t).strip() for t in cached if str(t).strip()]

    if not allow_network:
        return []

    url = "https://store.steampowered.com/api/appdetails"
    params = {"appids": appid, "l": "english", "filters": "genres,categories"}
    tags = []
    seen = set()
    try:
        r = requests.get(url, params=params, timeout=8)
        if r.status_code == 200:
            payload = r.json()
            entry = payload.get(str(appid), {}) if isinstance(payload, dict) else {}
            data = entry.get("data", {}) if isinstance(entry, dict) else {}
            genres = data.get("genres", []) if isinstance(data, dict) else []
            categories = data.get("categories", []) if isinstance(data, dict) else []

            for item in (genres + categories):
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("description", "")).strip()
                key = desc.casefold()
                if desc and key not in seen:
                    seen.add(key)
                    tags.append(desc)
    except Exception:
        tags = []

    # Community tags from store page markup.
    try:
        page = requests.get(
            f"https://store.steampowered.com/app/{appid}/?l=english",
            timeout=8,
            headers={"User-Agent": "MyLauncher/0.1 (PyQt6)"},
        )
        if page.status_code == 200 and page.text:
            matches = re.findall(
                r'<a[^>]*class="app_tag[^"]*"[^>]*>(.*?)</a>',
                page.text,
                re.IGNORECASE | re.DOTALL,
            )
            for raw in matches:
                cleaned = re.sub(r"<[^>]+>", "", raw or "")
                cleaned = html.unescape(cleaned).strip()
                cleaned = re.sub(r"\s+", " ", cleaned)
                cleaned = cleaned.lstrip("+").strip()
                key = cleaned.casefold()
                if cleaned and key not in seen:
                    seen.add(key)
                    tags.append(cleaned)
    except Exception:
        pass

    cache[str(appid)] = {
        "tags": tags,
        "includes_community": True,
    }
    _save_steam_tags_cache(cache)
    return tags


def lookup_steam_appid_by_name(game_name: str, allow_network=True):
    normalized = re.sub(r"[^a-z0-9]+", " ", (game_name or "").casefold()).strip()
    key = " ".join(normalized.split())
    if not key:
        return None
    if "unreal engine" in key:
        return None

    cache = _load_appid_cache()
    cached = cache.get(key)
    if cached is not None:
        try:
            return int(cached)
        except Exception:
            return None

    if not allow_network:
        return None

    # Lightweight lookup by title, avoids downloading full app list.
    url = "https://store.steampowered.com/api/storesearch/"
    params = {"term": game_name, "l": "english", "cc": "us"}
    try:
        r = requests.get(url, params=params, timeout=6)
        if r.status_code != 200:
            cache[key] = None
            _save_appid_cache(cache)
            return None
        data = r.json()
    except Exception:
        return None

    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        cache[key] = None
        _save_appid_cache(cache)
        return None

    exact_match = None
    for item in items:
        if not isinstance(item, dict):
            continue
        appid = item.get("id")
        name = str(item.get("name", "")).strip()
        name_key = " ".join(re.sub(r"[^a-z0-9]+", " ", name.casefold()).split())
        if name_key == key and appid is not None:
            exact_match = appid
            break

    chosen = exact_match
    try:
        chosen = int(chosen) if chosen is not None else None
    except Exception:
        chosen = None

    cache[key] = chosen
    _save_appid_cache(cache)
    return chosen


def get_owned_games(api_key: str, steamid64: str, *, include_free: bool = True, timeout: int = 12) -> list[dict[str, Any]]:
    if not api_key or not isinstance(api_key, str):
        raise ValueError("api_key is required")
    if not steamid64 or not steamid64.isdigit():
        raise ValueError("steamid64 must be a numeric SteamID64 string")

    url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
    params = {
        "key": api_key,
        "steamid": steamid64,
        "include_appinfo": 1,
        "include_played_free_games": 1 if include_free else 0,
        "format": "json",
    }
    headers = {"User-Agent": "MyLauncher/0.1 (PyQt6)"}

    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()

    payload = response.json()
    data = payload.get("response", {}) if isinstance(payload, dict) else {}
    games = data.get("games", [])

    out = []
    for game in games:
        if not isinstance(game, dict):
            continue
        appid = game.get("appid")
        if appid is None:
            continue
        try:
            appid = int(appid)
        except Exception:
            continue
        out.append({
            "appid": appid,
            "name": str(game.get("name") or "").strip(),
            "playtime_forever": int(game.get("playtime_forever", 0) or 0),
            "img_icon_url": game.get("img_icon_url", ""),
            "img_logo_url": game.get("img_logo_url", ""),
        })
    return out


def _is_likely_game_from_steam(name: str, app_type: str | None):
    normalized_name = (name or "").strip().casefold()
    normalized_type = (app_type or "").strip().casefold()

    if normalized_type and normalized_type not in {"game"}:
        return False

    blocked_terms = (
        "unreal engine",
        "soundtrack",
        "ost",
        "redistributable",
        "redistributables",
        "common redist",
        "dedicated server",
        "server",
        "benchmark",
        "sdk",
        "editor",
        "tool",
        "dlc",
        "test server",
        "bootstrapper",
        "installer",
        "eos",
    )
    return not any(term in normalized_name for term in blocked_terms)


def _is_globally_blocked_title(name: str):
    normalized_name = (name or "").strip().casefold()
    blocked_terms = (
        "unreal engine",
        "soundtrack",
        "redistributable",
        "common redist",
    )
    return any(term in normalized_name for term in blocked_terms)


# ---------------- DATE FORMAT ----------------

def format_steam_date(date_obj: datetime | None):
    if not date_obj:
        return ""
    now = datetime.now()
    if date_obj.year == now.year:
        return date_obj.strftime("%b %d")        # Feb 14
    return date_obj.strftime("%b %d, %Y")        # Feb 14, 2024


def format_playtime(playtime_minutes: int | None):
    if not playtime_minutes:
        return "0 h"
    hours = playtime_minutes / 60.0
    if hours >= 100:
        return f"{int(round(hours))} hrs"
    if hours >= 10:
        return f"{hours:.1f} hrs"
    return f"{hours:.1f} h"


# ---------------- GAME CARD ----------------

class GameCard(QWidget):
    """
    Outer widget is layout-controlled and NEVER changes geometry.
    Hover animation is applied to an inner content widget so it can't drift.
    """
    def __init__(self, appid=None, name="", path=None, last_played=None, playtime_forever=0, metadata_mode="playtime", tags=None, installed=True, platform=None, epic_tracked_minutes=0, epic_manual_override_minutes=None, custom_cover_path=None, on_launch=None, on_context_menu=None, parent=None):
        super().__init__(parent)

        self.appid = appid
        self.name = name
        self.path = path
        self.last_played = last_played
        self.playtime_forever = int(playtime_forever or 0)
        self.metadata_mode = metadata_mode
        self.tags = list(tags or [])
        self.installed = installed
        self.platform = platform
        self.epic_tracked_minutes = int(epic_tracked_minutes or 0)
        self.epic_manual_override_minutes = (int(epic_manual_override_minutes) if epic_manual_override_minutes is not None else None)
        self.custom_cover_path = str(custom_cover_path).strip() if custom_cover_path else None
        self.on_launch = on_launch
        self.on_context_menu = on_context_menu

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pixmap = None
        self._base_rect = QRect(0, 0, 0, 0)
        self._hovered = False
        self._has_cover = False
        self._using_custom_cover = False
        self.hover_summary = ""

        # Inner content widget (animated)
        self.content = QWidget(self)
        self.content.setStyleSheet("background: transparent;")

        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Image
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border-radius: 6px;")
        content_layout.addWidget(self.image_label, 1)

        # Dedicated footer area for metadata (play time / last played).
        self.meta_footer = QWidget()
        self.meta_footer.setFixedHeight(30)
        self.meta_footer.setStyleSheet("""
            QWidget{
                background: transparent;
            }
        """)
        footer_layout = QHBoxLayout(self.meta_footer)
        footer_layout.setContentsMargins(8, 4, 8, 4)
        footer_layout.setSpacing(0)
        footer_layout.addStretch(1)

        self.date_pill = QLabel()
        self.date_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(0,0,0,160);
                color: #c7d5e0;
                padding: 3px 10px;
                border-radius: 10px;
                font-size: 12px;
            }
        """)
        footer_layout.addWidget(self.date_pill, 0)
        footer_layout.addStretch(1)
        content_layout.addWidget(self.meta_footer, 0)

        # Shadow on OUTER widget (fine, doesn’t affect layout)
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(26)
        self.shadow.setOffset(0, 8)
        self.shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(self.shadow)

        # Hover animation on inner content geometry
        self.anim = QPropertyAnimation(self.content, b"geometry")
        self.anim.setDuration(170)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Prevent startup flicker/ghost card at (0,0) before first reflow.
        self.hide()
        self.load_cover()
        self.update_tags(self.tags)

    def load_cover(self, allow_lookup=False, allow_download=False):
        if self.custom_cover_path and os.path.exists(self.custom_cover_path):
            self._has_cover = True
            self._using_custom_cover = True
            self._pixmap = QPixmap(self.custom_cover_path)
            self.image_label.setText("")
            self._apply_image_frame_style()
            if self.metadata_mode == "last_played":
                txt = format_steam_date(self.last_played) if self.last_played else ""
            else:
                txt = format_playtime(self.playtime_forever)
            self.date_pill.setText(txt)
            self.date_pill.setVisible(bool(txt))
            self._apply_pixmap()
            return

        if not self.appid and self.platform != "Epic" and allow_lookup:
            self.appid = lookup_steam_appid_by_name(self.name, allow_network=True)
        path = get_steam_capsule(self.appid, allow_download=allow_download) if self.appid else None
        if path:
            self._has_cover = True
            self._using_custom_cover = False
            self._pixmap = QPixmap(path)
            self.image_label.setText("")
        else:
            self._has_cover = False
            self._using_custom_cover = False
            self._pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(self.name)

        self._apply_image_frame_style()

        if self.metadata_mode == "last_played":
            txt = format_steam_date(self.last_played) if self.last_played else ""
        else:
            txt = format_playtime(self.playtime_forever)
        self.date_pill.setText(txt)
        self.date_pill.setVisible(bool(txt))

        self._apply_pixmap()

    def refresh_metadata_pill(self):
        if self.metadata_mode == "last_played":
            txt = format_steam_date(self.last_played) if self.last_played else ""
        else:
            txt = format_playtime(self.playtime_forever)
        self.date_pill.setText(txt)
        self.date_pill.setVisible(bool(txt))
        self.refresh_hover_summary()

    def update_tags(self, tags):
        self.tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        self.refresh_hover_summary()

    def refresh_hover_summary(self):
        platform = str(self.platform or "Unknown")
        playtime = format_playtime(self.playtime_forever) or "No playtime"
        if self.last_played:
            last_played = self.last_played.strftime("%b %d, %Y %I:%M %p")
        else:
            last_played = "Never"
        tags = ", ".join(self.tags[:12]) if self.tags else "No tags yet"
        self.hover_summary = (
            f"Platform: {platform}\n"
            f"Play Time: {playtime}\n"
            f"Last Played: {last_played}\n"
            f"Tags: {tags}"
        )

    def cover_pixmap(self):
        return self._pixmap

    def _apply_image_frame_style(self):
        if self._hovered:
            border = "2px solid rgba(128,210,255,0.95)"
        else:
            border = "1px solid rgba(255,255,255,0.08)"

        if self._has_cover:
            self.image_label.setStyleSheet(
                f"border-radius: 6px; border: {border};"
            )
            return

        self.image_label.setStyleSheet(
            f"background-color:#1b2838;color:white;border-radius:6px;border:{border};"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and callable(self.on_launch):
            self.on_launch(self)
        elif event.button() == Qt.MouseButton.RightButton and callable(self.on_context_menu):
            self.on_context_menu(self, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def _apply_pixmap(self):
        if not self._pixmap:
            return
        w = self.image_label.width()
        h = self.image_label.height()
        if w <= 0 or h <= 0:
            return
        aspect_mode = (
            Qt.AspectRatioMode.IgnoreAspectRatio
            if self._using_custom_cover
            else Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )
        scaled = self._pixmap.scaled(w, h, aspect_mode, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._base_rect = QRect(0, 0, self.width(), self.height())
        self.content.setGeometry(self._base_rect)
        self._apply_pixmap()

    def enterEvent(self, event):
        self.raise_()
        self._hovered = True
        self._apply_image_frame_style()
        grow = 10
        target = self._base_rect.adjusted(-grow, -grow, grow, grow)
        self.anim.stop()
        self.anim.setStartValue(self.content.geometry())
        self.anim.setEndValue(target)
        self.anim.start()
        self.shadow.setBlurRadius(64)
        self.shadow.setOffset(0, 16)
        self.shadow.setColor(QColor(78, 169, 255, 180))
        window = self.window()
        if hasattr(window, "show_card_hover_popup"):
            window.show_card_hover_popup(self)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_image_frame_style()
        self.anim.stop()
        self.anim.setStartValue(self.content.geometry())
        self.anim.setEndValue(self._base_rect)
        self.anim.start()
        self.shadow.setBlurRadius(26)
        self.shadow.setOffset(0, 8)
        self.shadow.setColor(QColor(0, 0, 0, 170))
        window = self.window()
        if hasattr(window, "hide_card_hover_popup"):
            window.hide_card_hover_popup()


class GameHoverPopup(QFrame):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("gameHoverPopup")
        self.setStyleSheet("""
            QFrame#gameHoverPopup{
                background-color: #1a2836;
                border: 1px solid rgba(92, 141, 173, 0.65);
                border-radius: 0px;
            }
            QLabel{
                color: #d4e8f7;
                background: transparent;
            }
            QLabel#hoverTitle{
                background-color: #2f3f4c;
                color: #f2fbff;
                font-size: 13px;
                font-weight: 700;
                padding: 8px 10px;
            }
            QLabel#hoverMeta{
                color: #a9c5d8;
                font-size: 12px;
                padding: 6px 10px 10px 10px;
            }
        """)
        self.setFixedWidth(330)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel()
        self.title_label.setObjectName("hoverTitle")
        self.title_label.setWordWrap(False)
        layout.addWidget(self.title_label)

        self.preview_label = QLabel()
        self.preview_label.setFixedHeight(170)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color:#10202b; border:none; color:#9ab5c8; font-size:12px;"
        )
        layout.addWidget(self.preview_label)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("hoverMeta")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

    def update_from_card(self, card):
        title = str(card.name or "Unknown Game")
        self.title_label.setText(title)

        pixmap = card.cover_pixmap()
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.width(),
                self.preview_label.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        else:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("No Preview")

        platform = str(card.platform or "Unknown")
        playtime = format_playtime(card.playtime_forever) or "No playtime"
        last_played = card.last_played.strftime("%b %d, %Y %I:%M %p") if card.last_played else "Never"
        tags = ", ".join(card.tags[:8]) if card.tags else "No tags yet"
        self.meta_label.setText(
            f"<b>Platform:</b> {platform}<br>"
            f"<b>Play Time:</b> {playtime}<br>"
            f"<b>Last Played:</b> {last_played}<br>"
            f"<b>Tags:</b> {tags}"
        )
        self.adjustSize()


class SortComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d8ecff"))

        cy = self.rect().center().y()
        right = self.rect().right() - 7
        w = 6
        h = 4
        points = [
            QPoint(right - w, cy - h // 2),
            QPoint(right, cy - h // 2),
            QPoint(right - (w // 2), cy + h // 2),
        ]
        painter.drawPolygon(*points)
        painter.end()


class ComboContextListView(QListView):
    # Keep right-click for context menu only; do not change current selection.
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)


class InstalledFilterButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedSize(24, 24)
        self.setToolTip("Installed Only")
        self.setStyleSheet("QPushButton{background: transparent; border: none;}")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = self.rect().adjusted(1, 1, -1, -1)
        bg = QColor("#1a2431")
        border = QColor(74, 108, 136, 150)
        if self.underMouse():
            border = QColor(132, 210, 255, 220)
        painter.setPen(border)
        painter.setBrush(bg)
        painter.drawRoundedRect(outer, 5, 5)

        icon_color = QColor("#1a9fff") if self.isChecked() else QColor(123, 170, 204, 185)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(icon_color)
        cx, cy = outer.center().x(), outer.center().y()
        tri = [
            QPoint(cx - 3, cy - 4),
            QPoint(cx - 3, cy + 4),
            QPoint(cx + 4, cy),
        ]
        painter.drawPolygon(*tri)
        painter.end()


class SettingsPopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("settingsPopup")
        self.setStyleSheet("""
            QDialog#settingsPopup{
                background-color: #121822;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
            }
            QLabel{
                color: #c7d5e0;
            }
            QSlider::groove:horizontal{
                height: 4px;
                background: rgba(255,255,255,0.18);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal{
                background: #66c0f4;
                border-radius: 2px;
            }
            QSlider::handle:horizontal{
                background: #d9f2ff;
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("Settings")
        title.setStyleSheet("color:#e8f3ff; font-size:13px; font-weight:600;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.size_label = QLabel("Game Size")
        self.percent_label = QLabel("75%")
        self.percent_label.setStyleSheet("color:#9ab7d1;")
        row.addWidget(self.size_label)
        row.addStretch()
        row.addWidget(self.percent_label)
        layout.addLayout(row)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(50, 125)
        self.size_slider.setSingleStep(1)
        self.size_slider.setPageStep(5)
        layout.addWidget(self.size_slider)

        row_gap_row = QHBoxLayout()
        row_gap_row.setContentsMargins(0, 0, 0, 0)
        row_gap_row.setSpacing(8)
        self.row_gap_label = QLabel("Row Distance")
        self.row_gap_percent_label = QLabel("75%")
        self.row_gap_percent_label.setStyleSheet("color:#9ab7d1;")
        row_gap_row.addWidget(self.row_gap_label)
        row_gap_row.addStretch()
        row_gap_row.addWidget(self.row_gap_percent_label)
        layout.addLayout(row_gap_row)

        self.row_gap_slider = QSlider(Qt.Orientation.Horizontal)
        self.row_gap_slider.setRange(50, 150)
        self.row_gap_slider.setSingleStep(1)
        self.row_gap_slider.setPageStep(5)
        layout.addWidget(self.row_gap_slider)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 4, 0, 0)
        meta_row.setSpacing(8)
        self.meta_label = QLabel("Card Info")
        self.meta_box = QComboBox()
        self.meta_box.addItems(["Play Time", "Last Played"])
        self.meta_box.setFixedHeight(26)
        self.meta_box.setStyleSheet("""
            QComboBox{
                background: #0b121a;
                color: #e8f3ff;
                border: 1px solid rgba(102,192,244,0.85);
                border-radius: 9px;
                padding: 0px 18px 0px 8px;
                min-width: 132px;
                max-width: 132px;
            }
            QComboBox::drop-down{
                width: 0px;
                border: none;
            }
            QComboBox:hover{
                border: 1px solid rgba(132,210,255,0.95);
            }
            QComboBox:focus{
                border: 1px solid rgba(132,210,255,1.0);
            }
            QComboBox QAbstractItemView{
                background-color: #0f1a24;
                color: #c7d5e0;
                border: 1px solid rgba(255,255,255,0.12);
                selection-background-color: rgba(102,192,244,0.2);
            }
        """)
        meta_row.addWidget(self.meta_label)
        meta_row.addStretch()
        meta_row.addWidget(self.meta_box)
        layout.addLayout(meta_row)

        shortcut_row = QHBoxLayout()
        shortcut_row.setContentsMargins(0, 4, 0, 0)
        shortcut_row.setSpacing(8)
        self.shortcut_label = QLabel("Desktop Shortcut")
        self.shortcut_button = QPushButton("Create")
        self.shortcut_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.shortcut_button.setFixedHeight(26)
        self.shortcut_button.setStyleSheet("""
            QPushButton{
                background: #0f1a24;
                color: #e8f3ff;
                border: 1px solid rgba(102,192,244,0.85);
                border-radius: 9px;
                padding: 0px 10px;
                min-width: 132px;
            }
            QPushButton:hover{
                border: 1px solid rgba(132,210,255,0.95);
            }
            QPushButton:disabled{
                color: #7a92a8;
                border: 1px solid rgba(122,146,168,0.55);
            }
        """)
        shortcut_row.addWidget(self.shortcut_label)
        shortcut_row.addStretch()
        shortcut_row.addWidget(self.shortcut_button)
        layout.addLayout(shortcut_row)

        self.setFixedWidth(280)


class IntegrationsPopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("integrationsPopup")
        self.setStyleSheet("""
            QDialog#integrationsPopup{
                background-color: #121822;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
            }
            QLabel{
                color: #c7d5e0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("Integrations")
        title.setStyleSheet("color:#e8f3ff; font-size:13px; font-weight:600;")
        layout.addWidget(title)

        self.steam_button = QPushButton("Steam")
        self.steam_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.steam_button.setStyleSheet("""
            QPushButton{
                background-color: #0f1a24;
                color: #c7d5e0;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                text-align: left;
                padding: 8px 10px;
                font-size: 12px;
            }
            QPushButton:hover{
                border: 1px solid rgba(102,192,244,0.9);
                color: #e8f3ff;
            }
        """)
        layout.addWidget(self.steam_button)

        self.epic_button = QPushButton("Epic")
        self.epic_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.epic_button.setStyleSheet("""
            QPushButton{
                background-color: #0f1a24;
                color: #c7d5e0;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                text-align: left;
                padding: 8px 10px;
                font-size: 12px;
            }
            QPushButton:hover{
                border: 1px solid rgba(102,192,244,0.9);
                color: #e8f3ff;
            }
        """)
        layout.addWidget(self.epic_button)

        self.setFixedWidth(220)


class SteamCredentialsDialog(QDialog):
    def __init__(self, steamid64="", api_key="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Integration")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._validation_ok = False
        self.setStyleSheet("""
            QDialog{
                background-color: #121822;
            }
            QWidget{
                background-color: #121822;
            }
            QLabel{
                color: #c7d5e0;
                background: transparent;
            }
            QLineEdit{
                background:#0b121a;
                color:#e8f3ff;
                border:1px solid rgba(255,255,255,0.12);
                border-radius:8px;
                padding: 7px 8px;
                font-size:12px;
            }
            QLineEdit:focus{
                border:1px solid rgba(102,192,244,0.9);
            }
            QPushButton{
                background:#1b2838;
                color:#d7e9f8;
                border:1px solid rgba(255,255,255,0.12);
                border-radius:8px;
                padding: 7px 12px;
                font-size:12px;
            }
            QPushButton:hover{
                border:1px solid rgba(102,192,244,0.9);
                color:#ffffff;
            }
            QPushButton#infoBubble{
                background:#0f1a24;
                border:1px solid rgba(102,192,244,0.55);
                border-radius:8px;
                color:#9fd8ff;
                min-width:16px;
                max-width:16px;
                min-height:16px;
                max-height:16px;
                padding:0px;
                font-size:11px;
                font-weight:600;
            }
            QPushButton#infoBubble:hover{
                border:1px solid rgba(102,192,244,0.95);
                color:#e8f7ff;
            }
            QLabel#helperNote{
                color:#8fb3cc;
                font-size:11px;
            }
            QLabel#validationState{
                font-size:11px;
                color:#8fb3cc;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel("Steam Account")
        title.setStyleSheet("color:#e8f3ff; font-size:14px; font-weight:600;")
        layout.addWidget(title)

        def show_info_popup(message: str):
            popup = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            popup.setStyleSheet("""
                QDialog{
                    background-color:#0f1a24;
                    border:1px solid rgba(102,192,244,0.75);
                    border-radius:8px;
                }
                QLabel{
                    color:#d4e9fb;
                    background:transparent;
                    font-size:12px;
                }
            """)
            popup_layout = QVBoxLayout(popup)
            popup_layout.setContentsMargins(10, 8, 10, 8)
            popup_layout.setSpacing(0)
            text = QLabel(message)
            text.setWordWrap(True)
            popup_layout.addWidget(text)
            popup.resize(340, popup.sizeHint().height())
            pos = QCursor.pos() + QPoint(10, 10)
            popup.move(pos)
            popup.show()

        def make_info_bubble(message: str):
            b = QPushButton("?")
            b.setObjectName("infoBubble")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(message)
            b.clicked.connect(lambda: show_info_popup(message))
            return b

        step1 = QLabel("Step 1: Steam ID64")
        step1.setStyleSheet("color:#e8f3ff; font-size:12px; font-weight:600;")
        layout.addWidget(step1)

        id_row = QHBoxLayout()
        id_row.setContentsMargins(0, 0, 0, 0)
        id_row.setSpacing(6)
        id_label = QLabel("Steam ID64 or profile URL")
        id_row.addWidget(id_label)
        id_row.addWidget(make_info_bubble(
            "1. Open Steam and go to your profile.\n"
            "2. Right-click the page and Copy Page URL.\n"
            "3. If it includes a numeric profile ID, paste it directly here.\n"
            "4. You can also paste the numeric SteamID64 directly."
        ))
        id_row.addStretch()
        layout.addLayout(id_row)
        self.steamid_input = QLineEdit()
        self.steamid_input.setPlaceholderText("7656119... or https://steamcommunity.com/profiles/...")
        self.steamid_input.setText(steamid64)
        layout.addWidget(self.steamid_input)

        id_actions = QHBoxLayout()
        id_actions.setContentsMargins(0, 0, 0, 0)
        id_actions.setSpacing(8)
        open_profile_btn = QPushButton("Open Steam Profile")
        open_profile_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://steamcommunity.com/my")))
        id_actions.addWidget(open_profile_btn)
        id_actions.addStretch()
        layout.addLayout(id_actions)

        step2 = QLabel("Step 2: Steam Web API Key")
        step2.setStyleSheet("color:#e8f3ff; font-size:12px; font-weight:600;")
        layout.addWidget(step2)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(6)
        key_label = QLabel("Steam Web API Key")
        key_row.addWidget(key_label)
        key_row.addWidget(make_info_bubble(
            "1. Sign in at https://steamcommunity.com/dev/apikey.\n"
            "2. Enter localhost.\n"
            "3. Create/submit and copy the generated key."
        ))
        key_row.addStretch()
        layout.addLayout(key_row)
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter your Steam API key")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.api_key_input.setText(api_key)
        layout.addWidget(self.api_key_input)

        key_actions = QHBoxLayout()
        key_actions.setContentsMargins(0, 0, 0, 0)
        key_actions.setSpacing(8)
        open_key_page_btn = QPushButton("Open API Key Page")
        open_key_page_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://steamcommunity.com/dev/apikey")))
        key_actions.addWidget(open_key_page_btn)
        key_actions.addStretch()
        layout.addLayout(key_actions)

        note = QLabel("Credentials are stored locally on this PC.")
        note.setObjectName("helperNote")
        layout.addWidget(note)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("validationState")
        layout.addWidget(self.validation_label)

        actions = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        validate_btn = QPushButton("Validate Connection")
        save_btn = QPushButton("Save")
        cancel_btn.clicked.connect(self.reject)
        validate_btn.clicked.connect(self.validate_connection)
        save_btn.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(validate_btn)
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        layout.addLayout(actions)

        self.steamid_input.textChanged.connect(self._on_inputs_changed)
        self.api_key_input.textChanged.connect(self._on_inputs_changed)
        self._on_inputs_changed()

    def normalized_steamid64(self):
        return extract_steam_id64(self.steamid_input.text())

    def _set_validation_state(self, text: str, ok=False, warn=False):
        color = "#8fb3cc"
        if ok:
            color = "#9fe3b3"
        elif warn:
            color = "#f2ce7e"
        self.validation_label.setStyleSheet(f"color:{color}; font-size:11px;")
        self.validation_label.setText(text)

    def _on_inputs_changed(self):
        self._validation_ok = False
        raw_value = self.steamid_input.text().strip()
        normalized = self.normalized_steamid64()
        key = self.api_key_input.text().strip()
        if raw_value and not normalized:
            self._set_validation_state("Steam ID64 not detected. Paste the numeric ID or a URL containing it.", warn=True)
            return
        if not raw_value or not key:
            self._set_validation_state("Enter Steam ID64 and API key, then validate.")
            return
        self._set_validation_state("Ready to validate connection.")

    def validate_connection(self):
        steamid64 = self.normalized_steamid64()
        api_key = self.api_key_input.text().strip()
        if not steamid64:
            self._set_validation_state("Steam ID64 not detected in the value you entered.", warn=True)
            return
        if not api_key:
            self._set_validation_state("Steam Web API key is required.", warn=True)
            return
        try:
            get_owned_games(api_key=api_key, steamid64=steamid64, include_free=False, timeout=10)
            self._validation_ok = True
            self._set_validation_state("Connection verified. You can save now.", ok=True)
        except Exception as exc:
            self._validation_ok = False
            self._set_validation_state(f"Could not verify connection: {exc}", warn=True)


class EpicIntegrationDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self.setWindowTitle("Epic Integration")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet("""
            QDialog{ background-color:#121822; }
            QLabel{ color:#c7d5e0; background: transparent; }
            QCheckBox{ color:#d7e8f7; }
            QComboBox, QDoubleSpinBox{
                background:#0b121a; color:#e8f3ff; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 6px 8px;
            }
            QPushButton{
                background:#1b2838; color:#d7e9f8; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 7px 12px; font-size:12px;
            }
            QPushButton:hover{
                border:1px solid rgba(102,192,244,0.9);
                color:#ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title = QLabel("Epic Integration")
        title.setStyleSheet("color:#e8f3ff; font-size:14px; font-weight:600;")
        layout.addWidget(title)

        playtime_title = QLabel("Playtime")
        playtime_title.setStyleSheet("color:#e8f3ff; font-size:13px; font-weight:600;")
        layout.addWidget(playtime_title)

        self.local_tracking_box = QCheckBox("Enable local playtime tracking")
        self.local_tracking_box.setChecked(bool(self._app._is_epic_local_tracking_enabled()))
        layout.addWidget(self.local_tracking_box)

        note = QLabel("Tracks runtime for Epic games launched from this app.")
        note.setStyleSheet("color:#8fb3cc; font-size:11px;")
        layout.addWidget(note)

        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_row.addWidget(QLabel("Game"))
        self.game_box = QComboBox()
        combo_font = self.game_box.font()
        combo_font.setPointSize(10)
        self.game_box.setFont(combo_font)
        if self.game_box.view() is not None:
            view_font = self.game_box.view().font()
            view_font.setPointSize(10)
            self.game_box.view().setFont(view_font)
        game_row.addWidget(self.game_box, 1)
        layout.addLayout(game_row)

        hours_row = QHBoxLayout()
        hours_row.setSpacing(8)
        hours_row.addWidget(QLabel("Manual Hours Override"))
        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setRange(0.0, 50000.0)
        self.hours_spin.setDecimals(1)
        self.hours_spin.setSingleStep(0.5)
        self.hours_spin.setSuffix(" hrs")
        hours_row.addWidget(self.hours_spin)
        layout.addLayout(hours_row)

        override_actions = QHBoxLayout()
        self.apply_override_btn = QPushButton("Apply Override")
        self.reset_override_btn = QPushButton("Reset Override")
        self.refresh_diag_btn = QPushButton("Refresh Diagnostics")
        override_actions.addWidget(self.apply_override_btn)
        override_actions.addWidget(self.reset_override_btn)
        override_actions.addStretch(1)
        override_actions.addWidget(self.refresh_diag_btn)
        layout.addLayout(override_actions)

        diag_title = QLabel("Diagnostics")
        diag_title.setStyleSheet("color:#e8f3ff; font-size:13px; font-weight:600;")
        layout.addWidget(diag_title)

        self.diag_last_scan = QLabel("")
        self.diag_detected = QLabel("")
        self.diag_imported = QLabel("")
        self.diag_missing_exe = QLabel("")
        self.diag_unresolved_covers = QLabel("")
        layout.addWidget(self.diag_last_scan)
        layout.addWidget(self.diag_detected)
        layout.addWidget(self.diag_imported)
        layout.addWidget(self.diag_missing_exe)
        layout.addWidget(self.diag_unresolved_covers)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Close")
        save_btn = QPushButton("Save")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._save_and_close)
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        layout.addLayout(actions)

        self.apply_override_btn.clicked.connect(self._apply_override)
        self.reset_override_btn.clicked.connect(self._reset_override)
        self.refresh_diag_btn.clicked.connect(self._refresh_content)
        self.game_box.currentIndexChanged.connect(self._sync_hours_spin_from_selection)
        self._refresh_content()

    def _selected_game_name(self):
        return str(self.game_box.currentText() or "").strip()

    def _refresh_content(self):
        epic_names = self._app._epic_game_names()
        current = self._selected_game_name()
        self.game_box.blockSignals(True)
        self.game_box.clear()
        self.game_box.addItems(epic_names)
        if current:
            idx = self.game_box.findText(current)
            if idx >= 0:
                self.game_box.setCurrentIndex(idx)
        self.game_box.blockSignals(False)
        has_games = bool(epic_names)
        self.game_box.setEnabled(has_games)
        self.hours_spin.setEnabled(has_games)
        self.apply_override_btn.setEnabled(has_games)
        self.reset_override_btn.setEnabled(has_games)
        self._sync_hours_spin_from_selection()

        d = self._app._epic_diagnostics()
        self.diag_last_scan.setText(f"Last Epic scan: {d.get('last_scan', 'Never')}")
        self.diag_detected.setText(f"Epic games detected in scan: {d.get('detected_count', 0)}")
        self.diag_imported.setText(f"Epic games imported in library: {d.get('imported_count', 0)}")
        self.diag_missing_exe.setText(f"Missing executable entries: {d.get('missing_executable_count', 0)}")
        self.diag_unresolved_covers.setText(f"Epic unresolved covers: {d.get('unresolved_cover_count', 0)}")

    def _sync_hours_spin_from_selection(self):
        game_name = self._selected_game_name()
        minutes = self._app._epic_effective_playtime_minutes(game_name)
        self.hours_spin.blockSignals(True)
        self.hours_spin.setValue(round((minutes / 60.0), 1) if minutes > 0 else 0.0)
        self.hours_spin.blockSignals(False)

    def _apply_override(self):
        game_name = self._selected_game_name()
        if not game_name:
            QMessageBox.information(self, "Epic Override", "No Epic game selected.")
            return
        minutes = max(0, int(round(float(self.hours_spin.value()) * 60.0)))
        if not self._app._set_epic_manual_override_minutes(game_name, minutes):
            QMessageBox.warning(self, "Epic Override", f"Could not apply override for {game_name}.")
            return
        QMessageBox.information(self, "Epic Override", f"Applied manual playtime to {game_name}.")
        self._refresh_content()

    def _reset_override(self):
        game_name = self._selected_game_name()
        if not game_name:
            QMessageBox.information(self, "Epic Override", "No Epic game selected.")
            return
        if not self._app._clear_epic_manual_override(game_name):
            QMessageBox.warning(self, "Epic Override", f"Could not reset override for {game_name}.")
            return
        QMessageBox.information(self, "Epic Override", f"Reset manual override for {game_name}.")
        self._refresh_content()

    def _save_and_close(self):
        self._app._set_epic_local_tracking_enabled(self.local_tracking_box.isChecked())
        self.accept()


class ManualCollectionDialog(QDialog):
    def __init__(self, all_game_names, existing_name="", selected_games=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Collection")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet("""
            QDialog{ background-color:#121822; }
            QLabel{ color:#c7d5e0; }
            QLineEdit{
                background:#0b121a; color:#e8f3ff; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 7px 8px; font-size:12px;
            }
            QListWidget{
                background:#0b121a; color:#d7e8f7; border:1px solid rgba(255,255,255,0.12); border-radius:8px;
            }
            QPushButton{
                background:#1b2838; color:#d7e9f8; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 7px 12px; font-size:12px;
            }
        """)
        selected = set(selected_games or [])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Collection Name"))

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("My collection")
        self.name_input.setText(existing_name)
        layout.addWidget(self.name_input)

        layout.addWidget(QLabel("Games"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games...")
        layout.addWidget(self.search_input)
        self.games_list = QListWidget()
        for game_name in sorted(all_game_names, key=lambda n: n.casefold()):
            item = QListWidgetItem(game_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if game_name in selected else Qt.CheckState.Unchecked)
            self.games_list.addItem(item)
        layout.addWidget(self.games_list)
        self.search_input.textChanged.connect(self._filter_games)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        save_btn = QPushButton("Save")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        layout.addLayout(actions)

    def _filter_games(self, text):
        query = (text or "").strip().casefold()
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            name = item.text().casefold()
            item.setHidden(bool(query) and query not in name)

    def selected_game_names(self):
        selected = []
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        return selected


class TagPickerPopup(QDialog):
    def __init__(self, all_tags, selected_tags=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setMinimumWidth(360)
        self.setStyleSheet("""
            QDialog{ background-color:#121822; border:1px solid rgba(255,255,255,0.12); border-radius:8px; }
            QLineEdit{
                background:#0b121a; color:#e8f3ff; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 6px 8px; font-size:12px;
            }
            QListWidget{
                background:#0b121a; color:#d7e8f7; border:1px solid rgba(255,255,255,0.12); border-radius:8px;
            }
            QPushButton{
                background:#1b2838; color:#d7e9f8; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 6px 10px; font-size:12px;
            }
        """)
        selected = {str(t).strip() for t in (selected_tags or []) if str(t).strip()}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tags...")
        layout.addWidget(self.search_input)

        self.tags_list = QListWidget()
        for tag in sorted({str(t).strip() for t in (all_tags or []) if str(t).strip()}, key=lambda t: t.casefold()):
            item = QListWidgetItem(tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tag in selected else Qt.CheckState.Unchecked)
            self.tags_list.addItem(item)
        layout.addWidget(self.tags_list)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        apply_btn = QPushButton("Apply")
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.accept)
        actions.addWidget(cancel_btn)
        actions.addWidget(apply_btn)
        layout.addLayout(actions)

        self.search_input.textChanged.connect(self._filter_tags)

    def _filter_tags(self, text):
        query = (text or "").strip().casefold()
        for i in range(self.tags_list.count()):
            item = self.tags_list.item(i)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def selected_tags(self):
        out = []
        for i in range(self.tags_list.count()):
            item = self.tags_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out


class DynamicCollectionDialog(QDialog):
    def __init__(self, all_platforms, all_tags=None, existing_name="", existing_filters=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dynamic Collection")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet("""
            QDialog{ background-color:#121822; }
            QLabel{ color:#c7d5e0; }
            QLineEdit, QComboBox, QSpinBox{
                background:#0b121a; color:#e8f3ff; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 6px 8px; font-size:12px;
            }
            QPushButton{
                background:#1b2838; color:#d7e9f8; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 7px 12px; font-size:12px;
            }
        """)

        filters = dict(existing_filters or {})
        selected_platforms = set(filters.get("platforms", []))
        self.all_tags = sorted({str(t).strip() for t in (all_tags or []) if str(t).strip()}, key=lambda t: t.casefold())
        self.selected_tags = [str(t).strip() for t in filters.get("tags", []) if str(t).strip()]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Collection Name"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ready to play")
        self.name_input.setText(existing_name)
        layout.addWidget(self.name_input)

        platform_row = QHBoxLayout()
        platform_row.setSpacing(8)
        platform_row.addWidget(QLabel("Platforms"))
        self.platform_checks = []
        for platform in sorted(all_platforms):
            cb = QCheckBox(platform)
            cb.setChecked(platform in selected_platforms)
            cb.setStyleSheet("QCheckBox{color:#c7d5e0;}")
            self.platform_checks.append(cb)
            platform_row.addWidget(cb)
        platform_row.addStretch()
        layout.addLayout(platform_row)

        played_row = QHBoxLayout()
        played_row.addWidget(QLabel("Play State"))
        self.played_box = QComboBox()
        self.played_box.addItems(["Any", "Played", "Unplayed"])
        played_value = str(filters.get("played_state", "any")).strip().casefold()
        if played_value == "played":
            self.played_box.setCurrentIndex(1)
        elif played_value == "unplayed":
            self.played_box.setCurrentIndex(2)
        played_row.addWidget(self.played_box)
        layout.addLayout(played_row)

        installed_row = QHBoxLayout()
        installed_row.addWidget(QLabel("Install State"))
        self.installed_box = QComboBox()
        self.installed_box.addItems(["Any", "Installed", "Not Installed"])
        installed_value = str(filters.get("installed_state", "any")).strip().casefold()
        if installed_value == "installed":
            self.installed_box.setCurrentIndex(1)
        elif installed_value == "not_installed":
            self.installed_box.setCurrentIndex(2)
        installed_row.addWidget(self.installed_box)
        layout.addLayout(installed_row)

        hours_row = QHBoxLayout()
        hours_row.addWidget(QLabel("Min Hours Played"))
        self.min_hours_spin = QSpinBox()
        self.min_hours_spin.setRange(0, 20000)
        self.min_hours_spin.setValue(int(filters.get("min_hours", 0) or 0))
        hours_row.addWidget(self.min_hours_spin)
        layout.addLayout(hours_row)

        layout.addWidget(QLabel("Required Tags"))
        self.tags_picker_btn = QPushButton()
        self.tags_picker_btn.setStyleSheet("""
            QPushButton{
                background:#0b121a; color:#e8f3ff; border:1px solid rgba(255,255,255,0.12);
                border-radius:8px; padding: 7px 10px; font-size:12px; text-align:left;
            }
            QPushButton:hover{ border:1px solid rgba(102,192,244,0.9); }
        """)
        self.tags_picker_btn.clicked.connect(self._open_tags_picker)
        layout.addWidget(self.tags_picker_btn)
        self._refresh_tags_picker_text()

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        save_btn = QPushButton("Save")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        layout.addLayout(actions)

    def build_filters(self):
        played_map = {0: "any", 1: "played", 2: "unplayed"}
        installed_map = {0: "any", 1: "installed", 2: "not_installed"}
        return {
            "platforms": [cb.text() for cb in self.platform_checks if cb.isChecked()],
            "played_state": played_map.get(self.played_box.currentIndex(), "any"),
            "installed_state": installed_map.get(self.installed_box.currentIndex(), "any"),
            "min_hours": int(self.min_hours_spin.value()),
            "tags": list(self.selected_tags),
        }

    def _refresh_tags_picker_text(self):
        if not self.selected_tags:
            self.tags_picker_btn.setText("Select tags...")
            return
        if len(self.selected_tags) <= 2:
            self.tags_picker_btn.setText(", ".join(self.selected_tags))
            return
        self.tags_picker_btn.setText(f"{self.selected_tags[0]}, {self.selected_tags[1]} +{len(self.selected_tags)-2}")

    def _open_tags_picker(self):
        popup = TagPickerPopup(self.all_tags, self.selected_tags, self)
        anchor = self.tags_picker_btn.mapToGlobal(QPoint(0, self.tags_picker_btn.height() + 4))
        popup.move(anchor)
        if popup.exec() == QDialog.DialogCode.Accepted:
            self.selected_tags = popup.selected_tags()
            self._refresh_tags_picker_text()


class ResizeHandle(QWidget):
    def __init__(self, parent, direction):
        super().__init__(parent)
        self.direction = direction
        self._dragging = False
        self._start_global = None
        self._start_geom = QRect()
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)

        cursor_by_dir = {
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(QCursor(cursor_by_dir[direction]))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        window = self.window()
        if window.isMaximized():
            return
        self._dragging = True
        self._start_global = event.globalPosition().toPoint()
        self._start_geom = window.geometry()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return

        window = self.window()
        delta = event.globalPosition().toPoint() - self._start_global
        g = self._start_geom
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        dx, dy = delta.x(), delta.y()

        min_w = max(1, window.minimumWidth())
        min_h = max(1, window.minimumHeight())
        d = self.direction

        if "r" in d:
            w = max(min_w, w + dx)
        if "l" in d:
            new_w = max(min_w, w - dx)
            x += w - new_w
            w = new_w
        if "b" in d:
            h = max(min_h, h + dy)
        if "t" in d:
            new_h = max(min_h, h - dy)
            y += h - new_h
            h = new_h

        screen = QApplication.screenAt(event.globalPosition().toPoint()) or window.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        w = min(w, avail.width())
        h = min(h, avail.height())
        x = min(max(x, avail.left()), avail.left() + max(0, avail.width() - w))
        y = min(max(y, avail.top()), avail.top() + max(0, avail.height() - h))

        window.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event):
        self._dragging = False


# ---------------- MAIN WINDOW ----------------

class GameGridApp(QWidget):
    coverResolved = pyqtSignal(object, object)
    runtimeTracked = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self._settings = QSettings("LauncherProject", "GameGridApp")
        self.card_size_percent = self._settings.value("ui/card_size_percent", 75, type=int)
        self.card_size_percent = max(50, min(125, self.card_size_percent))
        self.card_metadata_mode = str(self._settings.value("ui/card_metadata_mode", "playtime", type=str) or "playtime").strip().casefold()
        if self.card_metadata_mode not in {"playtime", "last_played"}:
            self.card_metadata_mode = "playtime"
        saved_row_spacing = self._settings.value("ui/vertical_spacing_percent")
        if saved_row_spacing is None:
            saved_row_spacing = self._settings.value("ui/horizontal_spacing_percent", 75, type=int)
        self.vertical_spacing_percent = max(50, min(150, int(saved_row_spacing)))
        self._epic_local_tracking_enabled = bool(self._settings.value("integrations/epic_local_tracking_enabled", True, type=bool))
        self._settings_popup = None
        self._integrations_popup = None
        self._epic_dialog = None
        self._steam_dialog = None
        self._hover_popup = GameHoverPopup()
        self.coverResolved.connect(self._apply_resolved_cover)
        self.runtimeTracked.connect(self._apply_epic_runtime_minutes)
        self._did_initial_post_show_layout = False
        self._cover_prefetch_running = False
        self._pixmap_refresh_pending = False
        self._is_live_resizing = False
        self._last_live_reflow_ts = 0.0
        self._resize_live_timer = QTimer(self)
        self._resize_live_timer.setSingleShot(True)
        self._resize_live_timer.timeout.connect(self._run_live_resize_reflow)
        self._resize_settle_timer = QTimer(self)
        self._resize_settle_timer.setSingleShot(True)
        self._resize_settle_timer.timeout.connect(self._on_resize_settled)
        self._epic_last_scan_at = None
        self._epic_last_detected_count = 0
        self._epic_missing_executable_count = 0

        # Frameless window
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("background-color:#171a21;")
        self.resize(1280, 800)
        self.setMinimumSize(800, 500)

        # Resize/drag system
        self._resize_margin = 8
        self._drag_active = False
        self._create_resize_handles()

        self.games = self._discover_real_games()
        self.total_owned = len(self.games)
        self.collections = self._load_collections()
        self.current_collection_name = str(self._settings.value("collections/current_name", "All Games", type=str) or "All Games")

        # ---------------- MAIN LAYOUT ----------------
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---------------- TOP BAR ----------------
        self.topbar = QWidget()
        self.topbar.setFixedHeight(36)
        self.topbar.setStyleSheet("background-color: #0f1a24;")

        topbar_layout = QHBoxLayout(self.topbar)
        topbar_layout.setContentsMargins(12, 0, 12, 0)
        topbar_layout.setSpacing(6)

        self.btn_integrations = make_topbar_button("Integrations")
        self.btn_settings = make_topbar_button("Settings")
        self.steam_status_chip = QLabel("")
        self.steam_status_chip.setStyleSheet("""
            QLabel{
                color:#b7cbda;
                background:#0b121a;
                border:1px solid rgba(255,255,255,0.14);
                border-radius:9px;
                padding: 3px 8px;
                font-size:11px;
                font-weight:600;
            }
        """)

        topbar_layout.addWidget(self.btn_integrations)
        topbar_layout.addWidget(self.btn_settings)
        topbar_layout.addWidget(self.steam_status_chip)
        topbar_layout.addStretch()

        # Window controls
        btn_min = make_topbar_button("—", kind="window")
        btn_max = make_topbar_button("⛶", kind="window")
        btn_close = make_topbar_button("✕", kind="window")

        btn_min.clicked.connect(self.showMinimized)

        def toggle_max():
            if self.isMaximized():
                self._restore_from_maximized()
            else:
                self.showMaximized()

        btn_max.clicked.connect(toggle_max)

        btn_close.setStyleSheet(btn_close.styleSheet() + """
            QPushButton:hover { background-color: rgba(232,17,35,0.85); color: white; }
        """)
        btn_close.clicked.connect(self.close)
        self.btn_integrations.clicked.connect(self.open_integrations_popup)
        self.btn_settings.clicked.connect(self.open_settings_popup)
        self._update_steam_status_chip()

        topbar_layout.addWidget(btn_min)
        topbar_layout.addWidget(btn_max)
        topbar_layout.addWidget(btn_close)

        main_layout.addWidget(self.topbar)
        self.bottom_bar = self.build_bottom_bar()
        main_layout.addWidget(self.bottom_bar)
        self._update_search_bar_width()

        # ---------------- SCROLL + GRID ----------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("border: none;")

        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(40)
        self.grid.setContentsMargins(40, 40, 40, 40)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.scroll.setWidget(self.container)
        main_layout.addWidget(self.scroll)

        # ---------------- CREATE CARDS ONCE ----------------
        self.cards = self._build_cards(self.games)
        self.update_all_games_label()
        self._load_window_state()
        self._start_cover_prefetch()
        QTimer.singleShot(0, self._run_startup_prompts)
    
    def build_bottom_bar(self):
        bar = QWidget()
        bar.setFixedHeight(60)
        bar.setStyleSheet("background-color:#171a21;")

        layout = QGridLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)

        # Left cluster: collections + installed filter + sort
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        self.collection_box = SortComboBox()
        self.collection_view = ComboContextListView(self.collection_box)
        self.collection_box.setView(self.collection_view)
        self.collection_box.setFixedHeight(24)
        self.collection_box.setStyleSheet("""
            QComboBox{
                background: #0b121a;
                color: #e8f3ff;
                border: 1px solid rgba(102,192,244,0.85);
                border-radius: 9px;
                padding: 0px 18px 0px 8px;
                min-width: 96px;
                max-width: 132px;
            }
            QComboBox::drop-down{
                width: 0px;
                border: none;
            }
            QComboBox:hover{
                border: 1px solid rgba(132,210,255,0.95);
            }
            QComboBox QAbstractItemView{
                background-color: #0f1a24;
                color: #c7d5e0;
                border: 1px solid rgba(255,255,255,0.12);
                selection-background-color: rgba(102,192,244,0.2);
            }
        """)
        self.collections_help_bubble = QPushButton("?")
        self.collections_help_bubble.setObjectName("collectionsHelpBubble")
        self.collections_help_bubble.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.collections_help_bubble.setFixedSize(16, 16)
        self.collections_help_bubble.setToolTip(
            "Collections Tips:\n"
            "1. Select a collection, then right-click the closed collection box to Edit/Delete it.\n"
            "2. Right-click a game card to add it to a manual collection quickly."
        )
        self.collections_help_bubble.setStyleSheet("""
            QPushButton#collectionsHelpBubble{
                background:#0f1a24;
                border:1px solid rgba(102,192,244,0.6);
                border-radius:8px;
                color:#9fd8ff;
                font-size:10px;
                font-weight:600;
                padding:0px;
            }
            QPushButton#collectionsHelpBubble:hover{
                border:1px solid rgba(102,192,244,0.95);
                color:#e8f7ff;
            }
        """)
        self.installed_toggle_btn = InstalledFilterButton()

        self.sort_box = SortComboBox()
        self.sort_box.addItems(["Last Played", "Playtime", "A → Z", "Z → A"])
        sort_font = self.sort_box.font()
        sort_font.setPointSize(10)
        self.sort_box.setFont(sort_font)
        self.sort_box.setFixedHeight(24)
        self.sort_box.setStyleSheet("""
            QComboBox{
                background: #0b121a;
                color: #e8f3ff;
                border: 1px solid rgba(102,192,244,0.85);
                border-radius: 9px;
                padding: 0px 18px 0px 8px;
                min-width: 92px;
                max-width: 92px;
            }
            QComboBox::drop-down{
                width: 0px;
                border: none;
            }
            QComboBox:hover{
                border: 1px solid rgba(132,210,255,0.95);
            }
            QComboBox:focus{
                border: 1px solid rgba(132,210,255,1.0);
            }
            QComboBox QAbstractItemView{
                background-color: #0f1a24;
                color: #c7d5e0;
                border: 1px solid rgba(255,255,255,0.12);
                selection-background-color: rgba(102,192,244,0.2);
            }
        """)

        left_layout.addWidget(self.collection_box)
        left_layout.addWidget(self.collections_help_bubble)
        left_layout.addWidget(self.installed_toggle_btn)
        left_layout.addWidget(self.sort_box)

        # Search centered on same row
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setFixedHeight(30)
        self.search_bar.setFixedWidth(self._search_width_for_window())
        self.search_bar.setStyleSheet("""
            QLineEdit{
                background:#0b121a;
                color:#c7d5e0;
                border:1px solid rgba(255,255,255,0.10);
                border-radius:10px;
                padding: 6px 10px;
                font-size:13px;
            }
            QLineEdit:focus{
                border:1px solid rgba(255,255,255,0.22);
            }
        """)
        self.search_bar.textChanged.connect(self._on_search_changed)

        layout.addWidget(left_container, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.search_bar, 0, 1, Qt.AlignmentFlag.AlignCenter)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 1)

        self.sort_box.currentIndexChanged.connect(self._on_sort_changed)
        self.installed_toggle_btn.toggled.connect(self._on_installed_filter_toggled)
        self.collection_box.currentIndexChanged.connect(self._on_collection_changed)
        self.collection_box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.collection_box.customContextMenuRequested.connect(self._on_selected_collection_context_menu)

        self._rebuild_collection_dropdown()

        return bar

    def _search_width_for_window(self):
        base_window_width = 1920
        base_search_width = 300
        scaled_width = int(self.width() * base_search_width / base_window_width)
        return max(180, scaled_width)

    def _update_search_bar_width(self):
        if hasattr(self, "search_bar"):
            self.search_bar.setFixedWidth(self._search_width_for_window())

    def _load_collections(self):
        if not os.path.exists(COLLECTIONS_FILE):
            return []
        try:
            with open(COLLECTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return []
            out = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                ctype = str(item.get("type", "")).strip().casefold()
                if not name or ctype not in {"manual", "dynamic"}:
                    continue
                if ctype == "manual":
                    out.append({
                        "name": name,
                        "type": "manual",
                        "games": list(item.get("games", []) or []),
                    })
                else:
                    out.append({
                        "name": name,
                        "type": "dynamic",
                        "filters": dict(item.get("filters", {}) or {}),
                    })
            return out
        except Exception:
            return []

    def _save_collections(self):
        try:
            with open(COLLECTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.collections, f, indent=2)
        except Exception:
            pass

    def _all_collection_names(self):
        return ["All Games"] + [c["name"] for c in self.collections]

    def _manual_collections(self):
        return [c for c in self.collections if c.get("type") == "manual"]

    def _available_dynamic_tags(self):
        tags = set()
        for game in self.games:
            for tag in game.get("tags", []) or []:
                t = str(tag).strip()
                if t:
                    tags.add(t)
        return sorted(tags, key=lambda t: t.casefold())

    def _current_collection(self):
        if self.current_collection_name == "All Games":
            return None
        for collection in self.collections:
            if collection.get("name") == self.current_collection_name:
                return collection
        return None

    def _rebuild_collection_dropdown(self):
        if not hasattr(self, "collection_box"):
            return
        real_names = self._all_collection_names()
        if self.current_collection_name not in real_names:
            self.current_collection_name = "All Games"
        names = [NEW_COLLECTION_OPTION] + real_names
        self.collection_box.blockSignals(True)
        self.collection_box.clear()
        self.collection_box.addItems(names)
        self.collection_box.setCurrentText(self.current_collection_name)
        self.collection_box.blockSignals(False)
        self._settings.setValue("collections/current_name", self.current_collection_name)
        self._settings.sync()

    def _on_collection_changed(self, _index):
        selected = self.collection_box.currentText() or "All Games"
        if selected == NEW_COLLECTION_OPTION:
            previous = self.current_collection_name
            self._create_collection()
            if self.current_collection_name == NEW_COLLECTION_OPTION:
                self.current_collection_name = previous if previous in self._all_collection_names() else "All Games"
            self._rebuild_collection_dropdown()
            return

        self.current_collection_name = selected
        self._settings.setValue("collections/current_name", self.current_collection_name)
        self.update_all_games_label()
        self.reflow_grid()

    def _on_selected_collection_context_menu(self, pos):
        collection_name = self.current_collection_name
        if collection_name in {"All Games", NEW_COLLECTION_OPTION}:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{
                background:#0f1a24;
                color:#d7e8f7;
                border:1px solid rgba(255,255,255,0.12);
            }
            QMenu::item{
                padding: 6px 24px 6px 12px;
            }
            QMenu::item:selected{
                background: rgba(102,192,244,0.2);
            }
        """)
        edit_action = QAction("Edit Collection", self)
        delete_action = QAction("Delete Collection", self)
        edit_action.triggered.connect(lambda _checked=False, n=collection_name: self._edit_collection_by_name(n))
        delete_action.triggered.connect(lambda _checked=False, n=collection_name: self._delete_collection_by_name(n))
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(self.collection_box.mapToGlobal(pos))

    def _create_collection(self):
        choice = QMessageBox(self)
        choice.setWindowTitle("New Collection")
        choice.setText("Choose collection type")
        choice.setStyleSheet("QMessageBox{background:#121822;color:#d7e9f8;} QPushButton{min-width:120px;}")
        manual_btn = choice.addButton("Collection", QMessageBox.ButtonRole.ActionRole)
        dynamic_btn = choice.addButton("Dynamic Collection", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = choice.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        choice.exec()
        clicked = choice.clickedButton()
        if clicked == cancel_btn or clicked is None:
            return
        if clicked == manual_btn:
            self._create_manual_collection()
        elif clicked == dynamic_btn:
            self._create_dynamic_collection()

    def _create_manual_collection(self):
        dialog = ManualCollectionDialog([g.get("name", "") for g in self.games], parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Collection name is required.")
            return
        if name in self._all_collection_names():
            QMessageBox.warning(self, "Duplicate Name", "Collection name already exists.")
            return
        self.collections.append({
            "name": name,
            "type": "manual",
            "games": dialog.selected_game_names(),
        })
        self._save_collections()
        self.current_collection_name = name
        self._rebuild_collection_dropdown()
        self.update_all_games_label()
        self.reflow_grid()

    def _create_dynamic_collection(self):
        platforms = {str(g.get("platform") or "Unknown") for g in self.games}
        dialog = DynamicCollectionDialog(platforms, self._available_dynamic_tags(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Collection name is required.")
            return
        if name in self._all_collection_names():
            QMessageBox.warning(self, "Duplicate Name", "Collection name already exists.")
            return
        self.collections.append({
            "name": name,
            "type": "dynamic",
            "filters": dialog.build_filters(),
        })
        self._save_collections()
        self.current_collection_name = name
        self._rebuild_collection_dropdown()
        self.update_all_games_label()
        self.reflow_grid()

    def _edit_current_collection(self):
        self._edit_collection_by_name(self.current_collection_name)

    def _edit_collection_by_name(self, collection_name):
        collection = None
        for c in self.collections:
            if c.get("name") == collection_name:
                collection = c
                break
        if collection is None:
            QMessageBox.information(self, "Collections", "Select a user collection to edit.")
            return
        if collection.get("type") == "manual":
            dialog = ManualCollectionDialog(
                [g.get("name", "") for g in self.games],
                existing_name=collection.get("name", ""),
                selected_games=collection.get("games", []),
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_name = dialog.name_input.text().strip()
            if not new_name:
                QMessageBox.warning(self, "Invalid Name", "Collection name is required.")
                return
            for other in self.collections:
                if other is collection:
                    continue
                if other.get("name") == new_name:
                    QMessageBox.warning(self, "Duplicate Name", "Collection name already exists.")
                    return
            collection["name"] = new_name
            collection["games"] = dialog.selected_game_names()
        else:
            platforms = {str(g.get("platform") or "Unknown") for g in self.games}
            dialog = DynamicCollectionDialog(
                platforms,
                self._available_dynamic_tags(),
                existing_name=collection.get("name", ""),
                existing_filters=collection.get("filters", {}),
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_name = dialog.name_input.text().strip()
            if not new_name:
                QMessageBox.warning(self, "Invalid Name", "Collection name is required.")
                return
            for other in self.collections:
                if other is collection:
                    continue
                if other.get("name") == new_name:
                    QMessageBox.warning(self, "Duplicate Name", "Collection name already exists.")
                    return
            collection["name"] = new_name
            collection["filters"] = dialog.build_filters()

        self.current_collection_name = collection.get("name", "All Games")
        self._save_collections()
        self._rebuild_collection_dropdown()
        self.update_all_games_label()
        self.reflow_grid()

    def _delete_current_collection(self):
        self._delete_collection_by_name(self.current_collection_name)

    def _delete_collection_by_name(self, collection_name):
        collection = None
        for c in self.collections:
            if c.get("name") == collection_name:
                collection = c
                break
        if collection is None:
            QMessageBox.information(self, "Collections", "Select a user collection to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Delete Collection",
            f"Delete collection '{collection.get('name', '')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.collections = [c for c in self.collections if c is not collection]
        self.current_collection_name = "All Games"
        self._save_collections()
        self._rebuild_collection_dropdown()
        self.update_all_games_label()
        self.reflow_grid()

    def _show_card_context_menu(self, card, global_pos):
        manual_collections = self._manual_collections()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{
                background:#0f1a24;
                color:#d7e8f7;
                border:1px solid rgba(255,255,255,0.12);
            }
            QMenu::item{
                padding: 6px 24px 6px 12px;
            }
            QMenu::item:selected{
                background: rgba(102,192,244,0.2);
            }
        """)

        if manual_collections:
            add_menu = menu.addMenu("Add to Collection")
            for collection in sorted(manual_collections, key=lambda c: str(c.get("name", "")).casefold()):
                name = str(collection.get("name", "")).strip()
                if not name:
                    continue
                action = QAction(name, self)
                action.triggered.connect(lambda _checked=False, n=name, c=card: self._add_card_to_manual_collection(c, n))
                add_menu.addAction(action)

        set_custom_action = QAction("Set Custom Artwork...", self)
        set_custom_action.triggered.connect(lambda _checked=False, c=card: self._set_custom_artwork_for_card(c))
        menu.addAction(set_custom_action)

        clear_custom_action = QAction("Clear Custom Artwork", self)
        clear_custom_action.setEnabled(bool(card and card.custom_cover_path))
        clear_custom_action.triggered.connect(lambda _checked=False, c=card: self._clear_custom_artwork_for_card(c))
        menu.addAction(clear_custom_action)

        menu.exec(global_pos)

    def _add_card_to_manual_collection(self, card, collection_name):
        if card is None:
            return
        for collection in self.collections:
            if collection.get("type") != "manual" or collection.get("name") != collection_name:
                continue
            games = list(collection.get("games", []) or [])
            if card.name not in games:
                games.append(card.name)
                collection["games"] = games
                self._save_collections()
                if self.current_collection_name == collection_name:
                    self.update_all_games_label()
                    self.reflow_grid()
            return

    def _set_custom_artwork_for_card(self, card):
        if card is None or not card.name:
            return
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            f"Select Custom Artwork - {card.name}",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not file_path:
            return
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Custom Artwork", "Selected file does not exist.")
            return
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            ext = ".jpg"

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", card.name).strip("._")
        if not safe_name:
            safe_name = "game"

        try:
            os.makedirs(CUSTOM_COVERS_DIR, exist_ok=True)
            dest_path = os.path.join(CUSTOM_COVERS_DIR, f"{safe_name}{ext}")
            shutil.copyfile(file_path, dest_path)
        except Exception:
            QMessageBox.warning(self, "Custom Artwork", "Could not copy selected artwork.")
            return

        card.custom_cover_path = dest_path
        card.load_cover(allow_lookup=False, allow_download=False)
        for game in self.games:
            if game.get("name") == card.name:
                game["custom_cover_path"] = dest_path
                break
        self._save_game_runtime_state(card)
        self.reflow_grid()

    def _clear_custom_artwork_for_card(self, card):
        if card is None:
            return
        card.custom_cover_path = None
        card.load_cover(allow_lookup=False, allow_download=False)
        for game in self.games:
            if game.get("name") == card.name:
                game["custom_cover_path"] = None
                break
        self._save_game_runtime_state(card)
        self._start_cover_prefetch()
        self.reflow_grid()

    def _build_cards(self, games):
        return [
            GameCard(
                appid=g.get("appid"),
                name=g.get("name", ""),
                path=g.get("path"),
                last_played=g.get("last_played"),
                playtime_forever=g.get("playtime_forever", 0),
                metadata_mode=self.card_metadata_mode,
                tags=g.get("tags", []),
                installed=g.get("installed", True),
                platform=g.get("platform"),
                epic_tracked_minutes=g.get("epic_tracked_minutes", 0),
                epic_manual_override_minutes=g.get("epic_manual_override_minutes"),
                custom_cover_path=g.get("custom_cover_path"),
                on_launch=self._launch_game_from_card,
                on_context_menu=self._show_card_context_menu,
                parent=self.container,
            )
            for g in games
        ]

    def _apply_resolved_cover(self, card, appid):
        if appid is not None:
            card.appid = appid
        card.load_cover(allow_lookup=False, allow_download=False)

    def _write_missing_covers_report(self, unresolved):
        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(unresolved),
            "games": unresolved,
        }
        try:
            with open(MISSING_COVERS_FILE, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        except Exception:
            pass

    def _start_cover_prefetch(self, write_report=False):
        if self._cover_prefetch_running:
            return
        self._cover_prefetch_running = True
        cards = list(self.cards)

        def worker():
            unresolved = []
            try:
                def resolve_card_cover(card):
                    platform = str(card.platform or "")
                    appid = card.appid
                    if not appid:
                        appid = lookup_steam_appid_by_name(card.name, allow_network=True)
                    if not appid:
                        return None, {
                            "name": card.name,
                            "platform": platform,
                            "reason": "appid_not_found",
                        }

                    local_path = get_steam_capsule(appid, allow_download=False)
                    if local_path is None:
                        local_path = get_steam_capsule(appid, allow_download=True)
                    if local_path is None:
                        return None, {
                            "name": card.name,
                            "platform": platform,
                            "appid": appid,
                            "reason": "cover_not_found",
                        }

                    return (card, appid), None

                max_workers = max(4, min(12, (os.cpu_count() or 8)))
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = [pool.submit(resolve_card_cover, card) for card in cards]
                    for future in as_completed(futures):
                        resolved, issue = future.result()
                        if issue is not None:
                            unresolved.append(issue)
                            continue
                        card, appid = resolved
                        self.coverResolved.emit(card, appid)
            finally:
                if write_report:
                    self._write_missing_covers_report(unresolved)
                self._cover_prefetch_running = False

        threading.Thread(target=worker, daemon=True).start()

    def _discover_real_games(self):
        games_by_name = {}

        for game in self._load_saved_library_games():
            games_by_name[game["name"]] = game

        for game in self._discover_steam_games():
            existing = games_by_name.get(game["name"])
            if existing:
                prior_last_played = existing.get("last_played")
                prior_playtime = int(existing.get("playtime_forever", 0) or 0)
                prior_tags = list(existing.get("tags", []) or [])
                existing.update(game)
                if existing.get("last_played") is None and prior_last_played is not None:
                    existing["last_played"] = prior_last_played
                if int(existing.get("playtime_forever", 0) or 0) <= 0 and prior_playtime > 0:
                    existing["playtime_forever"] = prior_playtime
                if not existing.get("tags"):
                    existing["tags"] = prior_tags
            else:
                games_by_name[game["name"]] = game

        for game in self._discover_epic_games():
            existing = games_by_name.get(game["name"])
            if existing:
                existing["installed"] = game.get("installed", existing.get("installed", True))
                existing["platform"] = game.get("platform", existing.get("platform"))
                existing["path"] = game.get("path", existing.get("path"))
            else:
                games_by_name[game["name"]] = game

        games = []
        for game in games_by_name.values():
            platform = str(game.get("platform", "")).casefold()
            name = game.get("name", "")

            if _is_globally_blocked_title(name):
                continue

            # Final guard: remove non-game Steam entries even when loaded
            # from saved library data instead of live manifests.
            if platform == "steam" and not _is_likely_game_from_steam(name, None):
                continue

            games.append(game)
        games.sort(key=lambda g: g["name"].casefold())
        return games

    def _load_saved_library_games(self):
        if not os.path.exists(SAVE_FILE):
            return []
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return []

        if not isinstance(saved, dict):
            return []

        games = []
        for name, data in saved.items():
            if not isinstance(data, dict):
                continue
            path = data.get("path")
            appid = data.get("appid")
            try:
                appid = int(appid) if appid is not None else None
            except Exception:
                appid = None

            last_played = None
            last_played_raw = data.get("last_launched_at")
            if isinstance(last_played_raw, str) and last_played_raw.strip():
                try:
                    last_played = datetime.fromisoformat(last_played_raw.strip())
                except Exception:
                    last_played = None

            try:
                playtime_forever = int(data.get("playtime_forever", 0) or 0)
            except Exception:
                playtime_forever = 0
            try:
                epic_tracked_minutes = int(data.get("epic_tracked_minutes", playtime_forever) or 0)
            except Exception:
                epic_tracked_minutes = playtime_forever
            epic_manual_override_minutes = None
            if data.get("epic_manual_override_minutes") is not None:
                try:
                    epic_manual_override_minutes = int(data.get("epic_manual_override_minutes"))
                except Exception:
                    epic_manual_override_minutes = None

            games.append({
                "name": name,
                "appid": appid,
                "path": path,
                "platform": data.get("platform", "Manual"),
                "installed": bool(path and os.path.exists(path)),
                "last_played": last_played,
                "playtime_forever": playtime_forever,
                "epic_tracked_minutes": epic_tracked_minutes,
                "epic_manual_override_minutes": epic_manual_override_minutes,
                "custom_cover_path": str(data.get("custom_cover_path") or "").strip() or None,
                "tags": list(data.get("tags", []) or []),
            })
        for game in games:
            if str(game.get("platform", "")).casefold() != "epic":
                continue
            override = game.get("epic_manual_override_minutes")
            tracked = int(game.get("epic_tracked_minutes", 0) or 0)
            if override is not None:
                game["playtime_forever"] = int(override or 0)
            else:
                game["playtime_forever"] = tracked
        return games

    def _discover_local_steam_games(self):
        possible_steam_paths = [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
        ]
        steam_path = next((p for p in possible_steam_paths if os.path.exists(p)), None)
        if not steam_path:
            return []

        steamapps_path = os.path.join(steam_path, "steamapps")
        if not os.path.exists(steamapps_path):
            return []

        libraries = [steamapps_path]
        library_file = os.path.join(steamapps_path, "libraryfolders.vdf")
        if os.path.exists(library_file):
            try:
                with open(library_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                paths = re.findall(r'"path"\s+"([^"]+)"', content)
                for path in paths:
                    lib_path = os.path.join(path.replace("\\\\", "\\"), "steamapps")
                    if os.path.exists(lib_path):
                        libraries.append(lib_path)
            except Exception:
                pass

        games = []
        seen = set()
        for lib in libraries:
            try:
                files = os.listdir(lib)
            except Exception:
                continue
            for filename in files:
                if not (filename.startswith("appmanifest") and filename.endswith(".acf")):
                    continue
                manifest_path = os.path.join(lib, filename)
                try:
                    with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = f.read()
                except Exception:
                    continue

                name_match = re.search(r'"name"\s+"([^"]+)"', data)
                appid_match = re.search(r'"appid"\s+"([^"]+)"', data)
                type_match = re.search(r'"type"\s+"([^"]+)"', data)
                if not name_match:
                    continue

                game_name = name_match.group(1).strip()
                app_type = type_match.group(1).strip() if type_match else None
                if not game_name or game_name in seen:
                    continue
                if not _is_likely_game_from_steam(game_name, app_type):
                    continue

                appid = None
                if appid_match:
                    try:
                        appid = int(appid_match.group(1))
                    except Exception:
                        appid = None

                games.append({
                    "name": game_name,
                    "appid": appid,
                    "path": None,
                    "platform": "Steam",
                    "installed": True,
                    "last_played": None,
                    "playtime_forever": 0,
                    "tags": [],
                })
                seen.add(game_name)
        return games

    def _discover_steam_games(self):
        local_games = self._discover_local_steam_games()
        steamid64, api_key = self._load_steam_credentials()
        if not steamid64 or not api_key:
            return local_games

        local_by_appid = {}
        local_by_name = {}
        for game in local_games:
            appid = game.get("appid")
            if isinstance(appid, int):
                local_by_appid[appid] = game
            local_by_name[game.get("name", "").casefold()] = game

        try:
            owned_games = get_owned_games(api_key=api_key, steamid64=steamid64, include_free=True)
        except Exception:
            return local_games

        merged = []
        seen_appids = set()
        seen_names = set()

        for owned in owned_games:
            name = str(owned.get("name", "")).strip()
            appid = owned.get("appid")
            playtime_forever = int(owned.get("playtime_forever", 0) or 0)
            if not name:
                continue
            if not _is_likely_game_from_steam(name, "game"):
                continue

            local = local_by_appid.get(appid) or local_by_name.get(name.casefold())
            merged.append({
                "name": name,
                "appid": appid,
                "path": local.get("path") if local else None,
                "platform": "Steam",
                "installed": bool(local and local.get("installed", False)),
                "last_played": local.get("last_played") if local else None,
                "playtime_forever": playtime_forever,
                "tags": local.get("tags", []) if local else get_steam_app_tags(appid, allow_network=False),
            })
            if isinstance(appid, int):
                seen_appids.add(appid)
            seen_names.add(name.casefold())

        for game in local_games:
            appid = game.get("appid")
            name = str(game.get("name", "")).strip()
            if (isinstance(appid, int) and appid in seen_appids) or (name.casefold() in seen_names):
                continue
            merged.append(game)
        return merged

    def _discover_epic_games(self):
        manifest_root = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
        if not os.path.exists(manifest_root):
            self._epic_last_scan_at = datetime.now()
            self._epic_last_detected_count = 0
            self._epic_missing_executable_count = 0
            return []

        try:
            files = os.listdir(manifest_root)
        except Exception:
            self._epic_last_scan_at = datetime.now()
            self._epic_last_detected_count = 0
            self._epic_missing_executable_count = 0
            return []

        games = []
        missing_executable_count = 0
        for filename in files:
            if not filename.endswith(".item"):
                continue
            manifest_file = os.path.join(manifest_root, filename)
            try:
                with open(manifest_file, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
            except Exception:
                continue

            game_name = data.get("DisplayName")
            install_location = data.get("InstallLocation")
            executable = data.get("LaunchExecutable")
            if not (game_name and install_location and executable):
                missing_executable_count += 1
                continue
            full_path = os.path.join(install_location, executable)
            installed = os.path.exists(full_path)
            if not installed:
                missing_executable_count += 1
            games.append({
                "name": str(game_name).strip(),
                "appid": None,
                "path": full_path,
                "platform": "Epic",
                "installed": installed,
                "last_played": None,
                "playtime_forever": 0,
                "epic_tracked_minutes": 0,
                "epic_manual_override_minutes": None,
                "tags": [],
            })
        self._epic_last_scan_at = datetime.now()
        self._epic_last_detected_count = len(games)
        self._epic_missing_executable_count = missing_executable_count
        return games

    def refresh_game_library(self):
        self.games = self._discover_real_games()
        self.total_owned = len(self.games)
        self.cards = self._build_cards(self.games)
        self._rebuild_collection_dropdown()
        self.sort_games()
        self._start_cover_prefetch(write_report=True)

    def open_settings_popup(self):
        if self._settings_popup is None:
            self._settings_popup = SettingsPopup(self)
            self._settings_popup.size_slider.valueChanged.connect(self._on_card_size_changed)
            self._settings_popup.row_gap_slider.valueChanged.connect(self._on_vertical_spacing_changed)
            self._settings_popup.meta_box.currentIndexChanged.connect(self._on_card_metadata_mode_changed)
            self._settings_popup.shortcut_button.clicked.connect(self._on_shortcut_button_clicked)

        self._settings_popup.size_slider.blockSignals(True)
        self._settings_popup.size_slider.setValue(self.card_size_percent)
        self._settings_popup.percent_label.setText(f"{self.card_size_percent}%")
        self._settings_popup.size_slider.blockSignals(False)
        self._settings_popup.row_gap_slider.blockSignals(True)
        self._settings_popup.row_gap_slider.setValue(self.vertical_spacing_percent)
        self._settings_popup.row_gap_percent_label.setText(f"{self.vertical_spacing_percent}%")
        self._settings_popup.row_gap_slider.blockSignals(False)
        self._settings_popup.meta_box.blockSignals(True)
        self._settings_popup.meta_box.setCurrentIndex(1 if self.card_metadata_mode == "last_played" else 0)
        self._settings_popup.meta_box.blockSignals(False)
        self._refresh_shortcut_button_state()

        popup_pos = self.btn_settings.mapToGlobal(QPoint(0, self.btn_settings.height() + 6))
        self._settings_popup.move(popup_pos)
        self._settings_popup.show()

    def _desktop_shortcut_path(self):
        desktop_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop_dir:
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        return os.path.join(desktop_dir, "Game Launcher.lnk")

    def _desktop_shortcut_exists(self):
        return os.path.exists(self._desktop_shortcut_path())

    def _refresh_shortcut_button_state(self):
        if self._settings_popup is None:
            return
        if os.name != "nt":
            self._settings_popup.shortcut_button.setEnabled(False)
            self._settings_popup.shortcut_button.setText("Windows Only")
            return
        if not getattr(sys, "frozen", False):
            self._settings_popup.shortcut_button.setEnabled(False)
            self._settings_popup.shortcut_button.setText("Portable EXE Only")
            return
        self._settings_popup.shortcut_button.setEnabled(True)
        if self._desktop_shortcut_exists():
            self._settings_popup.shortcut_button.setText("Remove")
        else:
            self._settings_popup.shortcut_button.setText("Create")

    def _create_desktop_shortcut(self, show_feedback=True):
        if os.name != "nt":
            if show_feedback:
                QMessageBox.warning(self, "Desktop Shortcut", "Desktop shortcuts are only supported on Windows.")
            return False
        target_path = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
        working_dir = os.path.dirname(target_path)
        shortcut_path = self._desktop_shortcut_path()

        try:
            os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
        except Exception:
            pass

        def _ps_quote(text):
            return str(text).replace("'", "''")

        script = (
            "$w = New-Object -ComObject WScript.Shell; "
            f"$s = $w.CreateShortcut('{_ps_quote(shortcut_path)}'); "
            f"$s.TargetPath = '{_ps_quote(target_path)}'; "
            f"$s.WorkingDirectory = '{_ps_quote(working_dir)}'; "
            f"$s.IconLocation = '{_ps_quote(target_path)},0'; "
            "$s.Save();"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            created = self._desktop_shortcut_exists()
            if show_feedback:
                if created:
                    QMessageBox.information(self, "Desktop Shortcut", "Desktop shortcut created.")
                else:
                    QMessageBox.warning(self, "Desktop Shortcut", "Could not verify shortcut creation.")
            return created
        except Exception:
            if show_feedback:
                QMessageBox.warning(self, "Desktop Shortcut", "Failed to create desktop shortcut.")
            return False

    def _remove_desktop_shortcut(self, show_feedback=True):
        shortcut_path = self._desktop_shortcut_path()
        if not os.path.exists(shortcut_path):
            if show_feedback:
                QMessageBox.information(self, "Desktop Shortcut", "Desktop shortcut is already removed.")
            return True
        try:
            os.remove(shortcut_path)
            if show_feedback:
                QMessageBox.information(self, "Desktop Shortcut", "Desktop shortcut removed.")
            return True
        except Exception:
            if show_feedback:
                QMessageBox.warning(self, "Desktop Shortcut", "Failed to remove desktop shortcut.")
            return False

    def _on_shortcut_button_clicked(self):
        if self._desktop_shortcut_exists():
            self._remove_desktop_shortcut(show_feedback=True)
        else:
            self._create_desktop_shortcut(show_feedback=True)
        self._refresh_shortcut_button_state()

    def _maybe_prompt_desktop_shortcut(self):
        if os.name != "nt" or not getattr(sys, "frozen", False):
            return
        prompted = bool(self._settings.value("ui/desktop_shortcut_prompted", False, type=bool))
        if prompted:
            return
        self._settings.setValue("ui/desktop_shortcut_prompted", True)
        self._settings.sync()
        if self._desktop_shortcut_exists():
            return
        answer = QMessageBox.question(
            self,
            "Desktop Shortcut",
            "Create a desktop shortcut for Game Launcher?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._create_desktop_shortcut(show_feedback=True)

    def _run_startup_prompts(self):
        self._maybe_prompt_desktop_shortcut()
        QTimer.singleShot(0, self._maybe_show_onboarding_hints)

    def _maybe_show_onboarding_hints(self):
        shown = bool(self._settings.value("ui/onboarding_hints_shown", False, type=bool))
        if shown:
            return
        QMessageBox.information(
            self,
            "Quick Start",
            "1. Open Integrations to connect Steam for richer metadata.\n"
            "2. Use the ? next to Collections for quick tips.\n"
            "3. Right-click a game card to add it to a manual collection.",
        )
        self._settings.setValue("ui/onboarding_hints_shown", True)
        self._settings.sync()

    def _update_steam_status_chip(self):
        steamid64, api_key = self._load_steam_credentials()
        connected = bool(steamid64 and api_key)
        if connected:
            self.steam_status_chip.setText("Steam: Connected")
            self.steam_status_chip.setStyleSheet("""
                QLabel{
                    color:#bff2cd;
                    background:#10211a;
                    border:1px solid rgba(126,224,156,0.45);
                    border-radius:9px;
                    padding: 3px 8px;
                    font-size:11px;
                    font-weight:600;
                }
            """)
        else:
            self.steam_status_chip.setText("Steam: Not Connected")
            self.steam_status_chip.setStyleSheet("""
                QLabel{
                    color:#b7cbda;
                    background:#0b121a;
                    border:1px solid rgba(255,255,255,0.14);
                    border-radius:9px;
                    padding: 3px 8px;
                    font-size:11px;
                    font-weight:600;
                }
            """)

    def open_integrations_popup(self):
        if self._integrations_popup is None:
            self._integrations_popup = IntegrationsPopup(self)
            self._integrations_popup.steam_button.clicked.connect(self.open_steam_credentials_dialog)
            self._integrations_popup.epic_button.clicked.connect(self.open_epic_integration_dialog)

        popup_pos = self.btn_integrations.mapToGlobal(QPoint(0, self.btn_integrations.height() + 6))
        self._integrations_popup.move(popup_pos)
        self._integrations_popup.show()

    def _load_steam_credentials(self):
        steamid64 = str(self._settings.value("integrations/steam_id64", "", type=str) or "").strip()
        api_key = str(self._settings.value("integrations/steam_api_key", "", type=str) or "").strip()
        return steamid64, api_key

    def _save_steam_credentials(self, steamid64: str, api_key: str):
        self._settings.setValue("integrations/steam_id64", steamid64)
        self._settings.setValue("integrations/steam_api_key", api_key)
        self._settings.sync()

    def open_steam_credentials_dialog(self):
        if self._integrations_popup is not None:
            self._integrations_popup.hide()

        saved_id, saved_key = self._load_steam_credentials()
        dialog = SteamCredentialsDialog(saved_id, saved_key, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        steamid64 = dialog.normalized_steamid64()
        api_key = dialog.api_key_input.text().strip()
        if not steamid64:
            QMessageBox.warning(self, "Invalid Steam ID", "Paste a numeric SteamID64 or a URL containing one.")
            return
        if not api_key:
            QMessageBox.warning(self, "Invalid API Key", "Steam Web API key is required.")
            return

        self._save_steam_credentials(steamid64, api_key)
        self._update_steam_status_chip()
        self.refresh_game_library()

    def open_epic_integration_dialog(self):
        if self._integrations_popup is not None:
            self._integrations_popup.hide()
        dialog = EpicIntegrationDialog(self, self)
        dialog.exec()

    def _is_epic_local_tracking_enabled(self):
        return bool(self._epic_local_tracking_enabled)

    def _set_epic_local_tracking_enabled(self, enabled):
        self._epic_local_tracking_enabled = bool(enabled)
        self._settings.setValue("integrations/epic_local_tracking_enabled", self._epic_local_tracking_enabled)
        self._settings.sync()

    def _epic_game_names(self):
        names = []
        for card in self.cards:
            if str(card.platform or "").casefold() == "epic":
                names.append(card.name)
        return sorted(names, key=lambda n: n.casefold())

    def _epic_diagnostics(self):
        unresolved_cover_count = 0
        if os.path.exists(MISSING_COVERS_FILE):
            try:
                with open(MISSING_COVERS_FILE, "r", encoding="utf-8") as f:
                    report = json.load(f)
                games = report.get("games", [])
                unresolved_cover_count = sum(1 for g in games if str(g.get("platform", "")).casefold() == "epic")
            except Exception:
                unresolved_cover_count = 0
        last_scan = "Never"
        if isinstance(self._epic_last_scan_at, datetime):
            last_scan = self._epic_last_scan_at.strftime("%b %d, %Y %I:%M:%S %p")
        imported_count = sum(1 for g in self.games if str(g.get("platform", "")).casefold() == "epic")
        return {
            "last_scan": last_scan,
            "detected_count": int(self._epic_last_detected_count or 0),
            "imported_count": int(imported_count),
            "missing_executable_count": int(self._epic_missing_executable_count or 0),
            "unresolved_cover_count": int(unresolved_cover_count),
        }

    def _find_card_by_name(self, game_name):
        for card in self.cards:
            if card.name == game_name:
                return card
        return None

    def _find_game_entry_by_name(self, game_name):
        for game in self.games:
            if game.get("name") == game_name:
                return game
        return None

    def _epic_effective_playtime_minutes(self, game_name):
        card = self._find_card_by_name(game_name)
        if card is None or str(card.platform or "").casefold() != "epic":
            return 0
        if card.epic_manual_override_minutes is not None:
            return int(card.epic_manual_override_minutes or 0)
        return int(card.epic_tracked_minutes or card.playtime_forever or 0)

    def _set_epic_manual_override_minutes(self, game_name, minutes):
        card = self._find_card_by_name(game_name)
        if card is None or str(card.platform or "").casefold() != "epic":
            return False
        override = max(0, int(minutes or 0))
        card.epic_manual_override_minutes = override
        card.playtime_forever = override
        card.refresh_metadata_pill()
        game = self._find_game_entry_by_name(game_name)
        if isinstance(game, dict):
            game["epic_manual_override_minutes"] = override
            game["epic_tracked_minutes"] = int(card.epic_tracked_minutes or 0)
            game["playtime_forever"] = override
        self._save_game_runtime_state(card)
        self.update_all_games_label()
        self.reflow_grid()
        return True

    def _clear_epic_manual_override(self, game_name):
        card = self._find_card_by_name(game_name)
        if card is None or str(card.platform or "").casefold() != "epic":
            return False
        card.epic_manual_override_minutes = None
        card.playtime_forever = int(card.epic_tracked_minutes or 0)
        card.refresh_metadata_pill()
        game = self._find_game_entry_by_name(game_name)
        if isinstance(game, dict):
            game["epic_manual_override_minutes"] = None
            game["epic_tracked_minutes"] = int(card.epic_tracked_minutes or 0)
            game["playtime_forever"] = int(card.playtime_forever or 0)
        self._save_game_runtime_state(card)
        self.update_all_games_label()
        self.reflow_grid()
        return True

    def _on_card_size_changed(self, value):
        self.card_size_percent = value
        self._settings.setValue("ui/card_size_percent", value)
        if self._settings_popup is not None:
            self._settings_popup.percent_label.setText(f"{value}%")
        self.reflow_grid()

    def _on_vertical_spacing_changed(self, value):
        self.vertical_spacing_percent = value
        self._settings.setValue("ui/vertical_spacing_percent", value)
        if self._settings_popup is not None:
            self._settings_popup.row_gap_percent_label.setText(f"{value}%")
        self.reflow_grid()

    def _on_card_metadata_mode_changed(self, index):
        self.card_metadata_mode = "last_played" if index == 1 else "playtime"
        self._settings.setValue("ui/card_metadata_mode", self.card_metadata_mode)
        for card in self.cards:
            card.metadata_mode = self.card_metadata_mode
            card.refresh_metadata_pill()

    def _load_window_state(self):
        was_maximized = self._settings.value("window/maximized", False, type=bool)
        saved_rect = self._settings.value("window/normal_rect")
        saved_geometry = self._settings.value("window/geometry")
        saved_sort_index = self._settings.value("sort/index", 0, type=int)
        installed_only = self._settings.value("filter/installed_only", False, type=bool)

        if not was_maximized:
            self._force_normal_state()
            restored = False

            # Preferred path: explicit normal-rect persistence avoids Qt state issues.
            if isinstance(saved_rect, (list, tuple)) and len(saved_rect) == 4:
                try:
                    x, y, w, h = [int(v) for v in saved_rect]
                    self.setGeometry(x, y, w, h)
                    self._clamp_to_available_screen()
                    restored = True
                except Exception:
                    restored = False

            # Backward-compatible fallback for older settings.
            if saved_geometry and not restored:
                self.restoreGeometry(saved_geometry)
                self._clamp_to_available_screen()

        if was_maximized:
            self.showMaximized()

        if self.sort_box.count() > 0:
            saved_sort_index = max(0, min(saved_sort_index, self.sort_box.count() - 1))
            self.sort_box.blockSignals(True)
            self.sort_box.setCurrentIndex(saved_sort_index)
            self.sort_box.blockSignals(False)
        self.installed_toggle_btn.blockSignals(True)
        self.installed_toggle_btn.setChecked(installed_only)
        self.installed_toggle_btn.blockSignals(False)

        if hasattr(self, "cards"):
            self.sort_games()

    def _clamp_to_available_screen(self):
        screens = QApplication.screens()
        if not screens:
            return

        frame = self.frameGeometry()
        frame_rect = QRect(frame)

        def intersect_area(a, b):
            inter = a.intersected(b)
            if inter.isEmpty():
                return 0
            return inter.width() * inter.height()

        target_screen = max(
            screens,
            key=lambda s: intersect_area(frame_rect, s.geometry())
        )
        avail = target_screen.geometry()

        min_w = max(1, self.minimumWidth())
        min_h = max(1, self.minimumHeight())

        width = max(min_w, min(self.width(), avail.width()))
        height = max(min_h, min(self.height(), avail.height()))

        max_x = avail.left() + max(0, avail.width() - width)
        max_y = avail.top() + max(0, avail.height() - height)
        x = min(max(self.x(), avail.left()), max_x)
        y = min(max(self.y(), avail.top()), max_y)

        self.setGeometry(x, y, width, height)

    def _available_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def _clamped_rect_to_available(self, rect: QRect):
        avail = self._available_geometry()
        min_w = max(1, self.minimumWidth())
        min_h = max(1, self.minimumHeight())
        w = max(min_w, min(rect.width(), avail.width()))
        h = max(min_h, min(rect.height(), avail.height()))
        max_x = avail.left() + max(0, avail.width() - w)
        max_y = avail.top() + max(0, avail.height() - h)
        x = min(max(rect.x(), avail.left()), max_x)
        y = min(max(rect.y(), avail.top()), max_y)
        return QRect(x, y, w, h)

    def _virtual_geometry(self):
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        rect = QRect(screens[0].geometry())
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        return rect

    def _force_normal_state(self):
        # Ensure Windows does not treat this frameless window as maximized
        # when we are applying a normal geometry rectangle.
        self.setWindowState(Qt.WindowState.WindowNoState)

    def _restore_target_rect(self):
        g = self.normalGeometry()
        if g.isNull() or g.width() <= 0 or g.height() <= 0:
            saved_rect = self._settings.value("window/normal_rect")
            if isinstance(saved_rect, (list, tuple)) and len(saved_rect) == 4:
                try:
                    x, y, w, h = [int(v) for v in saved_rect]
                    g = QRect(x, y, w, h)
                except Exception:
                    g = QRect()
        if not g.isNull() and g.width() >= self.minimumWidth() and g.height() >= self.minimumHeight():
            return g

        avail = self._available_geometry()
        target_w = max(self.minimumWidth(), min(1280, int(avail.width() * 0.75)))
        target_h = max(self.minimumHeight(), min(800, int(avail.height() * 0.75)))
        x = avail.left() + max(0, (avail.width() - target_w) // 2)
        y = avail.top() + max(0, (avail.height() - target_h) // 2)
        return QRect(x, y, target_w, target_h)

    def _restore_from_maximized(self):
        target = self._restore_target_rect()
        self._force_normal_state()
        self.showNormal()
        self.setWindowState(Qt.WindowState.WindowNoState)
        QTimer.singleShot(0, lambda t=QRect(target): self._apply_restored_geometry(t))

    def _apply_restored_geometry(self, target: QRect):
        self._force_normal_state()
        self.showNormal()
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.setGeometry(self._clamped_rect_to_available(target))
        self._clamp_to_available_screen()

    def _save_window_state(self):
        is_maximized = self.isMaximized()
        self._settings.setValue("window/maximized", is_maximized)

        if is_maximized:
            g = self.normalGeometry()
            if g.isNull() or g.width() <= 0 or g.height() <= 0:
                g = self.geometry()
        else:
            g = self.geometry()

        self._settings.setValue("window/normal_rect", [g.x(), g.y(), g.width(), g.height()])
        # Keep legacy key for compatibility with older app versions.
        if not is_maximized:
            self._settings.setValue("window/geometry", self.saveGeometry())

        self._settings.setValue("sort/index", self.sort_box.currentIndex())
        self._settings.setValue("filter/installed_only", self.installed_toggle_btn.isChecked())
        self._settings.setValue("ui/card_size_percent", self.card_size_percent)
        self._settings.setValue("ui/vertical_spacing_percent", self.vertical_spacing_percent)
        self._settings.setValue("ui/card_metadata_mode", self.card_metadata_mode)
        self._settings.sync()

    def _load_saved_library_blob(self):
        if not os.path.exists(SAVE_FILE):
            return {}
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_saved_library_blob(self, data):
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _save_game_runtime_state(self, card):
        if not card or not card.name:
            return
        saved = self._load_saved_library_blob()
        existing = saved.get(card.name)
        if not isinstance(existing, dict):
            existing = {}
        existing["path"] = card.path
        existing["platform"] = card.platform or existing.get("platform", "Manual")
        existing["appid"] = card.appid
        existing["playtime_forever"] = int(card.playtime_forever or 0)
        existing["tags"] = list(card.tags or [])
        existing["custom_cover_path"] = card.custom_cover_path if card.custom_cover_path else None
        if str(card.platform or "").casefold() == "epic":
            existing["epic_tracked_minutes"] = int(card.epic_tracked_minutes or 0)
            existing["epic_manual_override_minutes"] = (
                int(card.epic_manual_override_minutes)
                if card.epic_manual_override_minutes is not None
                else None
            )
        existing["last_launched_at"] = card.last_played.isoformat() if isinstance(card.last_played, datetime) else None
        saved[card.name] = existing
        self._save_saved_library_blob(saved)

    def _launch_game_from_card(self, card):
        if card is None:
            return
        self.hide_card_hover_popup()

        launched = False
        runtime_process = None
        runtime_started = None
        platform = str(card.platform or "").casefold()
        try:
            if card.path and os.path.exists(card.path):
                if platform == "epic" and self._is_epic_local_tracking_enabled():
                    try:
                        runtime_process = subprocess.Popen([card.path], cwd=os.path.dirname(card.path) or None)
                        runtime_started = time.monotonic()
                        launched = True
                    except Exception:
                        os.startfile(card.path)
                        launched = True
                else:
                    os.startfile(card.path)
                    launched = True
            elif platform == "steam" and card.appid:
                os.startfile(f"steam://rungameid/{card.appid}")
                launched = True
        except Exception:
            launched = False

        if not launched:
            QMessageBox.warning(self, "Launch Failed", f"Could not launch {card.name}.")
            return

        card.last_played = datetime.now()
        card.refresh_metadata_pill()

        for game in self.games:
            if game.get("name") == card.name:
                game["last_played"] = card.last_played
                break
        self._save_game_runtime_state(card)
        if platform == "epic" and runtime_process is not None and runtime_started is not None:
            self._track_epic_runtime(card.name, runtime_process, runtime_started)

        if self.sort_box.currentText() == "Last Played":
            self.sort_games()

    def _track_epic_runtime(self, game_name, process, started_at):
        def worker():
            try:
                process.wait()
            except Exception:
                return
            elapsed = max(0.0, time.monotonic() - started_at)
            minutes = int(elapsed // 60.0)
            if (elapsed % 60.0) >= 30.0:
                minutes += 1
            if minutes <= 0:
                return
            self.runtimeTracked.emit(game_name, minutes)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_epic_runtime_minutes(self, game_name, minutes):
        if int(minutes or 0) <= 0:
            return
        card = self._find_card_by_name(game_name)
        if card is None or str(card.platform or "").casefold() != "epic":
            return

        card.epic_tracked_minutes = int(card.epic_tracked_minutes or 0) + int(minutes)
        if card.epic_manual_override_minutes is None:
            card.playtime_forever = int(card.epic_tracked_minutes or 0)
            card.refresh_metadata_pill()

        game = self._find_game_entry_by_name(game_name)
        if isinstance(game, dict):
            game["epic_tracked_minutes"] = int(card.epic_tracked_minutes or 0)
            game["epic_manual_override_minutes"] = card.epic_manual_override_minutes
            if card.epic_manual_override_minutes is None:
                game["playtime_forever"] = int(card.playtime_forever or 0)

        self._save_game_runtime_state(card)
        if self.sort_box.currentText() == "Playtime":
            self.sort_games()
        else:
            self.update_all_games_label()
            self.reflow_grid()

    def show_card_hover_popup(self, card):
        if card is None:
            return
        self._hover_popup.update_from_card(card)

        anchor = card.mapToGlobal(QPoint(0, 0))
        gap = 14
        popup_w = self._hover_popup.width()
        popup_h = self._hover_popup.height()
        target_x = anchor.x() + card.width() + gap
        target_y = anchor.y() + 36

        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            if target_x + popup_w > g.right():
                target_x = anchor.x() - popup_w - gap
            target_x = max(g.left() + 6, min(target_x, g.right() - popup_w - 6))
            target_y = max(g.top() + 6, min(target_y, g.bottom() - popup_h - 6))

        self._hover_popup.move(target_x, target_y)
        self._hover_popup.show()

    def hide_card_hover_popup(self):
        if self._hover_popup.isVisible():
            self._hover_popup.hide()

    def _on_sort_changed(self, index):
        self._settings.setValue("sort/index", index)
        if hasattr(self, "cards"):
            self.sort_games()

    def _on_installed_filter_toggled(self, checked):
        self._settings.setValue("filter/installed_only", checked)
        self.update_all_games_label()
        self.reflow_grid()

    def update_all_games_label(self):
        visible_count = len(self._filtered_cards())
        if hasattr(self, "collection_box"):
            self.collection_box.setToolTip(f"{self.current_collection_name}: {visible_count}/{self.total_owned}")

    def _collection_filtered_cards(self):
        cards = self.cards
        collection = self._current_collection()
        if collection is None:
            return cards

        ctype = collection.get("type")
        if ctype == "manual":
            names = {str(n).casefold() for n in collection.get("games", [])}
            return [card for card in cards if card.name.casefold() in names]

        if ctype == "dynamic":
            filters = dict(collection.get("filters", {}) or {})
            platforms = {str(p).casefold() for p in filters.get("platforms", [])}
            played_state = str(filters.get("played_state", "any")).casefold()
            installed_state = str(filters.get("installed_state", "any")).casefold()
            min_hours = int(filters.get("min_hours", 0) or 0)
            tag_terms = [str(t).strip().casefold() for t in filters.get("tags", []) if str(t).strip()]

            out = []
            for card in cards:
                if platforms and str(card.platform or "").casefold() not in platforms:
                    continue
                if played_state == "played" and int(card.playtime_forever or 0) <= 0:
                    continue
                if played_state == "unplayed" and int(card.playtime_forever or 0) > 0:
                    continue
                if installed_state == "installed" and not card.installed:
                    continue
                if installed_state == "not_installed" and card.installed:
                    continue
                if min_hours > 0 and (int(card.playtime_forever or 0) / 60.0) < min_hours:
                    continue
                if tag_terms:
                    tag_haystack = " ".join(str(t).casefold() for t in (card.tags or []))
                    if not all(term in tag_haystack for term in tag_terms):
                        continue
                out.append(card)
            return out

        return cards

    def _filtered_cards(self):
        cards = self._collection_filtered_cards()
        if hasattr(self, "installed_toggle_btn") and self.installed_toggle_btn.isChecked():
            cards = [card for card in cards if card.installed]

        if not hasattr(self, "search_bar"):
            return cards
        query = self.search_bar.text().strip().casefold()
        if not query:
            return cards

        # Steam-like behavior: every typed term must exist in the title.
        terms = [t for t in query.split() if t]
        if not terms:
            return cards

        def matches(card):
            name = card.name.casefold()
            tag_text = " ".join(str(t).casefold() for t in (card.tags or []))
            haystack = f"{name} {tag_text}".strip()
            return all(term in haystack for term in terms)

        return [card for card in cards if matches(card)]

    def _on_search_changed(self, _text):
        self.update_all_games_label()
        self.reflow_grid()

    # ---------------- SORT ----------------
    def sort_games(self):
        choice = self.sort_box.currentText()

        if choice == "Last Played":
            self.cards.sort(key=lambda c: c.last_played or datetime.min, reverse=True)
        elif choice == "Playtime":
            self.cards.sort(key=lambda c: int(c.playtime_forever or 0), reverse=True)
        elif choice == "A → Z":
            self.cards.sort(key=lambda c: c.name.lower())
        elif choice == "Z → A":
            self.cards.sort(key=lambda c: c.name.lower(), reverse=True)

        self.update_all_games_label()
        self.reflow_grid()

    # ---------------- GRID REFLOW ----------------
    def reflow_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()

        viewport_width = max(1, self.scroll.viewport().width())

        if self.isMaximized():
            edge_margin = 32
            spacing_baseline = 24
            min_card_width = 120
            base_columns = 6
        else:
            edge_margin = max(20, min(40, viewport_width // 50))
            spacing_baseline = max(12, min(30, viewport_width // 45))
            min_card_width = 140
            baseline_target = max(min_card_width, int(viewport_width * 0.18))
            base_columns = max(1, (viewport_width + spacing_baseline) // (baseline_target + spacing_baseline))

        base_spacing = spacing_baseline
        vertical_spacing_scale = max(0.4, self.vertical_spacing_percent / 75.0)
        vertical_spacing = max(8, int(spacing_baseline * vertical_spacing_scale))

        self.grid.setContentsMargins(edge_margin, edge_margin, edge_margin, edge_margin)

        usable_width = max(1, viewport_width - (2 * edge_margin))
        size_scale = max(0.4, self.card_size_percent / 75.0)
        base_width_at_75 = max(
            min_card_width,
            (usable_width - spacing_baseline * (base_columns - 1)) // max(1, base_columns),
        )
        min_safe_card_width = 120
        target_card_width = max(min_safe_card_width, int(base_width_at_75 * size_scale))
        columns = max(1, (usable_width + base_spacing) // (target_card_width + base_spacing))
        card_width = max(min_safe_card_width, min(target_card_width, usable_width))

        # Use leftover row width to enlarge equal gaps between cards,
        # instead of pushing empty space to the outer edges.
        if columns > 1:
            remaining = max(0, usable_width - (columns * card_width))
            spacing = max(base_spacing, remaining // (columns - 1))
        else:
            spacing = base_spacing
        self.grid.setHorizontalSpacing(spacing)
        self.grid.setVerticalSpacing(vertical_spacing)

        # Keep cover image area fixed and allocate separate footer area for metadata.
        image_height = int(card_width * 1.60)
        card_height = image_height + 30

        visible_cards = self._filtered_cards()
        if not visible_cards:
            if not self.cards:
                empty_panel = QFrame()
                empty_panel.setStyleSheet("""
                    QFrame{
                        background:#101722;
                        border:1px solid rgba(255,255,255,0.10);
                        border-radius:10px;
                    }
                    QLabel{
                        color:#8aa6c1;
                        background:transparent;
                    }
                    QPushButton{
                        background:#1b2838;
                        color:#d7e9f8;
                        border:1px solid rgba(255,255,255,0.12);
                        border-radius:8px;
                        padding: 7px 12px;
                        font-size:12px;
                    }
                    QPushButton:hover{
                        border:1px solid rgba(102,192,244,0.9);
                        color:#ffffff;
                    }
                """)
                panel_layout = QVBoxLayout(empty_panel)
                panel_layout.setContentsMargins(18, 16, 18, 16)
                panel_layout.setSpacing(10)

                title = QLabel("No games found yet.")
                title.setStyleSheet("color:#c7d5e0; font-size:14px; font-weight:600;")
                body = QLabel("Try refreshing your library or opening Integrations to connect Steam.")
                body.setWordWrap(True)

                actions = QHBoxLayout()
                refresh_btn = QPushButton("Refresh Library")
                integrations_btn = QPushButton("Open Integrations")
                refresh_btn.clicked.connect(self.refresh_game_library)
                integrations_btn.clicked.connect(self.open_integrations_popup)
                actions.addWidget(refresh_btn)
                actions.addWidget(integrations_btn)
                actions.addStretch()

                panel_layout.addWidget(title)
                panel_layout.addWidget(body)
                panel_layout.addLayout(actions)

                self.grid.addWidget(
                    empty_panel,
                    0,
                    0,
                    1,
                    max(1, columns),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                )
            else:
                no_results = QLabel("No games match your search.")
                no_results.setStyleSheet("color:#8aa6c1; font-size:14px;")
                no_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.grid.addWidget(
                    no_results,
                    0,
                    0,
                    1,
                    max(1, columns),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                )
            return

        row = col = 0
        for card in visible_cards:
            card.show()
            card.setFixedSize(card_width, card_height)
            card.image_label.setFixedHeight(image_height)
            card.meta_footer.setFixedHeight(30)
            self.grid.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

            col += 1
            if col >= columns:
                col = 0
                row += 1

        self._schedule_pixmap_refresh()

    def _schedule_pixmap_refresh(self):
        if self._is_live_resizing:
            return
        if self._pixmap_refresh_pending:
            return
        self._pixmap_refresh_pending = True
        QTimer.singleShot(0, self._refresh_visible_card_pixmaps)

    def _refresh_visible_card_pixmaps(self):
        self._pixmap_refresh_pending = False
        for card in self.cards:
            if card.isVisible():
                card._apply_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._is_live_resizing = True
        self._update_search_bar_width()
        self._layout_resize_handles()

        min_interval = 1.0 / 30.0  # Cap heavy reflow work to ~30 FPS during drag resize.
        now = time.monotonic()
        elapsed = now - self._last_live_reflow_ts
        if elapsed >= min_interval:
            self._run_live_resize_reflow()
        else:
            remaining_ms = max(1, int((min_interval - elapsed) * 1000))
            if not self._resize_live_timer.isActive():
                self._resize_live_timer.start(remaining_ms)

        self._resize_settle_timer.start(110)

    def _run_live_resize_reflow(self):
        if not self._is_live_resizing:
            return
        self._last_live_reflow_ts = time.monotonic()
        self.reflow_grid()

    def _on_resize_settled(self):
        self._is_live_resizing = False
        if self._resize_live_timer.isActive():
            self._resize_live_timer.stop()
        self.reflow_grid()
        self._schedule_pixmap_refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._did_initial_post_show_layout:
            self._did_initial_post_show_layout = True
            QTimer.singleShot(0, self._post_show_layout_sync)

    def _post_show_layout_sync(self):
        self._update_search_bar_width()
        self.reflow_grid()
        self._layout_resize_handles()

    def _create_resize_handles(self):
        self._resize_handles = {
            "l": ResizeHandle(self, "l"),
            "r": ResizeHandle(self, "r"),
            "t": ResizeHandle(self, "t"),
            "b": ResizeHandle(self, "b"),
            "tl": ResizeHandle(self, "tl"),
            "tr": ResizeHandle(self, "tr"),
            "bl": ResizeHandle(self, "bl"),
            "br": ResizeHandle(self, "br"),
        }
        self._layout_resize_handles()

    def _layout_resize_handles(self):
        m = self._resize_margin
        w = self.width()
        h = self.height()

        self._resize_handles["l"].setGeometry(0, m, m, max(0, h - (2 * m)))
        self._resize_handles["r"].setGeometry(max(0, w - m), m, m, max(0, h - (2 * m)))
        self._resize_handles["t"].setGeometry(m, 0, max(0, w - (2 * m)), m)
        self._resize_handles["b"].setGeometry(m, max(0, h - m), max(0, w - (2 * m)), m)

        self._resize_handles["tl"].setGeometry(0, 0, m, m)
        self._resize_handles["tr"].setGeometry(max(0, w - m), 0, m, m)
        self._resize_handles["bl"].setGeometry(0, max(0, h - m), m, m)
        self._resize_handles["br"].setGeometry(max(0, w - m), max(0, h - m), m, m)

        for handle in self._resize_handles.values():
            handle.raise_()

    # ---------------- RESIZE + DRAG SUPPORT ----------------
    def _hit_test_resize(self, pos):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self._resize_margin

        left = x <= m
        right = x >= w - m
        top = y <= m
        bottom = y >= h - m

        if top and left: return "tl"
        if top and right: return "tr"
        if bottom and left: return "bl"
        if bottom and right: return "br"
        if left: return "l"
        if right: return "r"
        if top: return "t"
        if bottom: return "b"
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.isMaximized():
            # only drag on topbar when maximized
            if event.position().y() <= self.topbar.height():
                self._drag_active = True
                self._drag_pos = event.globalPosition().toPoint()
            return

        if event.position().y() <= self.topbar.height():
            self._drag_active = True
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_active and event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            next_pos = self.pos() + delta
            avail = self._virtual_geometry()
            max_x = avail.left() + max(0, avail.width() - self.width())
            max_y = avail.top() + max(0, avail.height() - self.height())
            x = min(max(next_pos.x(), avail.left()), max_x)
            y = min(max(next_pos.y(), avail.top()), max_y)
            self.move(x, y)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self._drag_active = False

    # Double-click on topbar OR border to maximize/restore
    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position().toPoint()
        on_topbar = pos.y() <= self.topbar.height()
        on_border = self._hit_test_resize(pos) is not None

        if on_topbar or on_border:
            if self.isMaximized():
                self._restore_from_maximized()
            else:
                self.showMaximized()

    def closeEvent(self, event):
        self.hide_card_hover_popup()
        self._save_window_state()
        super().closeEvent(event)


# ---------------- RUN ----------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QToolTip {
            background-color: #1c2c39;
            color: #d9ecfb;
            border: 1px solid rgba(112, 182, 226, 0.75);
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 12px;
        }
    """)
    window = GameGridApp()
    window.show()
    sys.exit(app.exec())
