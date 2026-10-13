"""
Maya Renamer Pro
================

A small Maya tool to rename the selected objects in bulk: add a prefix or a
suffix, number them, search and replace text in names, or strip characters.

Requirements: Autodesk Maya 2025+ (the UI uses PySide6).

How to launch (Script Editor, Python tab):

    import maya_renamer_pro
    maya_renamer_pro.show_renamer()

The code is organized in three layers:
    1. Logic functions (rename_safe, add_prefix, ...): they only deal with
       names and know nothing about the UI.
    2. The UI class (MayaRenamerUI): it reads the values from the widgets
       and calls the logic functions.
    3. The launcher (show_renamer): it opens the window.
"""

import maya.cmds as cmds
import re
from contextlib import contextmanager
from PySide6 import QtWidgets, QtCore
from maya import OpenMayaUI as omui
from shiboken6 import wrapInstance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def undo_chunk():
    """Group everything done inside a `with undo_chunk():` block into a
    single undo step.

    `yield` marks the point where the code inside the `with` block runs.
    The `finally` part always runs, even if an error happens, so the chunk
    is never left open (an open chunk breaks Maya's undo queue).
    """
    cmds.undoInfo(openChunk=True)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


def get_user_selection(outline_order=True):
    """Return the list of selected transform nodes (as full DAG paths).

    outline_order=True  -> objects are sorted as they appear in the Outliner.
    outline_order=False -> objects keep the order in which the user selected them.

    Returns an empty list (and prints a warning) if no valid object is selected.
    """
    # long=True returns full paths like "|group1|pCube1" instead of "pCube1".
    # Full paths are needed to tell apart objects that share the same short name
    # in different hierarchies.
    # objectsOnly=True turns selected components (vertices, faces...) into
    # their parent node, so we never get names like "pCube1.vtx[0]".
    user_selection = cmds.ls(selection=True, long=True, objectsOnly=True)

    # Keep only transform nodes (also groups, joints, locators...). Shape nodes
    # are discarded: Maya renames them automatically with their transform.
    user_selection = [obj for obj in user_selection if cmds.objectType(obj, isAType='transform')]

    # An empty list is "falsy" in Python, so "if not list" means "if it is empty".
    if not user_selection:
        cmds.warning("No Valid Objects selected by the user. Please select at least one Valid object to rename.")
        return []

    if outline_order:
        # A set makes "obj in user_set" much faster than searching a list.
        user_set = set(user_selection)

        # All nodes of the scene, in Outliner order (dag=True means only nodes
        # that live in a hierarchy, so no shaders etc.).
        scene_list = cmds.ls(dag=True, long=True)

        # List comprehension: keep the scene objects that are also selected.
        # It is the short version of:
        #
        #   ordered_selection = []
        #   for obj in scene_list:
        #       if obj in user_set:
        #           ordered_selection.append(obj)
        ordered_selection = [obj for obj in scene_list if obj in user_set]

        print(f"User selection: {ordered_selection}")  # Debug output
        return ordered_selection

    else:  # Technically redundant (the if above returns), kept for clarity.
        print(f"User selection: {user_selection}")  # Debug output
        return user_selection


def rename_safe(pairs):
    """Rename objects from the deepest in the hierarchy up to the top.

    `pairs` is a list of tuples: [(full_path, new_short_name), ...]

    Why the order matters: renaming a parent changes the full path of all its
    children. If a child were renamed after its parent, the path stored in the
    list would not exist anymore and Maya would raise an error. Children always
    have more "|" in their path than their parents, so sorting by the number of
    "|" (deepest first) guarantees every path is still valid when it is used.
    """
    with undo_chunk():
        for obj, renamed in sorted(pairs, key=lambda p: p[0].count("|"), reverse=True):
            cmds.rename(obj, renamed)


# ---------------------------------------------------------------------------
# Renaming functions
#
# All of them follow the same two-phase pattern:
#   1. Collect: loop over the objects and build the list of (path, new name)
#      pairs WITHOUT touching the scene.
#   2. Apply: pass the complete list to rename_safe().
# The apply phase must happen after the loop is finished, so the list is
# complete and the renaming order can be decided on all the objects together.
# ---------------------------------------------------------------------------

def add_prefix(prefix, selected):
    """Add `prefix` at the beginning of each name (skips names that already have it)."""
    pairs = []

    for obj in selected:
        # "|group1|group2|object1" -> split("|") -> ['', 'group1', 'group2', 'object1']
        # and [-1] picks the last element: the short name "object1".
        short_name = obj.split("|")[-1]

        if short_name.startswith(prefix):
            cmds.warning(f"Object '{short_name}' already has the prefix '{prefix}'. Skipping renaming.")
            continue  # Jump to the next object

        renamed = prefix + short_name
        # The double parentheses are intended: the outer ones belong to append(),
        # the inner ones create the tuple (path, new_name).
        pairs.append((obj, renamed))

    rename_safe(pairs)


def add_suffix(suffix, selected):
    """Add `suffix` at the end of each name (skips names that already have it)."""
    pairs = []

    for obj in selected:
        short_name = obj.split("|")[-1]
        if short_name.endswith(suffix):
            cmds.warning(f"Object '{short_name}' already has the suffix '{suffix}'. Skipping renaming.")
            continue

        renamed = short_name + suffix
        pairs.append((obj, renamed))

    rename_safe(pairs)


def add_progressive(selected, start_num=1, fill=2, spacing="_", strip_num=False):
    """Add a progressive number to each name, e.g. "cube" -> "cube_001".

    start_num -- number given to the first object
    fill      -- minimum number of digits (zeros are added on the left)
    spacing   -- text placed between the name and the number
    strip_num -- if True, an existing trailing number ("cube_07") is removed first
    """
    pairs = []

    # enumerate() gives both the counter (i) and the object (obj).
    # The counter starts from start_num instead of 0.
    for i, obj in enumerate(selected, start=start_num):

        # str(7).zfill(3) -> "007"
        num_str = str(i).zfill(fill)

        short_name = obj.split("|")[-1]

        # base_name is the part of the name we keep. By default it is the whole name.
        base_name = short_name

        if strip_num and spacing in short_name:
            # rsplit splits from the right, only once:
            # "rock_03".rsplit("_", 1) -> ["rock", "03"]
            parts = short_name.rsplit(spacing, 1)

            try:
                target_part = parts[-1]  # Text after the last spacing
                int(target_part)  # Raises ValueError if it is not a number

                if parts[0]:
                    base_name = parts[0]  # Keep only the part before the number

            except ValueError:
                # The text after the spacing is not a number (e.g. "rock_a"):
                # there is nothing to strip, so base_name stays the same.
                pass

        renamed = base_name + spacing + num_str
        pairs.append((obj, renamed))

    rename_safe(pairs)


def search_and_replace(selected, search_str, replace_str, c_sensitive=True):
    """Replace every occurrence of `search_str` with `replace_str` in the names."""
    pairs = []

    if not search_str:
        cmds.warning("Search string cannot be empty.")
        return

    flags = 0 if c_sensitive else re.IGNORECASE

    # re.escape makes special characters (. * ( ...) be read as plain text
    # instead of regular expression commands.
    pattern = re.escape(search_str)

    for obj in selected:
        short_name = obj.split("|")[-1]

        if re.search(pattern, short_name, flags=flags):
            # The replacement is passed as a function (lambda) so it is used
            # literally: a plain string would give special meaning to backslashes
            # (e.g. "\1" would be read as "first captured group" and raise an error).
            renamed = re.sub(pattern, lambda m: replace_str, short_name, flags=flags)
            pairs.append((obj, renamed))

    rename_safe(pairs)


def strip_str(selected, start_active=False, start_val=0, end_active=False, end_val=1, ranged_active=False, start_range=0, end_range=1):
    """Remove characters from the names.

    start_active / start_val -- remove `start_val` characters from the beginning
    end_active / end_val     -- remove `end_val` characters from the end
    ranged_active            -- instead, remove the characters from index
                                `start_range` up to (but excluding) `end_range`
    """
    pairs = []

    for obj in selected:
        short_name = obj.split("|")[-1]

        if ranged_active:
            # Slicing: short_name[:a] is the text before index a,
            # short_name[b:] is the text from index b on. Joined, they skip [a, b).
            renamed = short_name[:start_range] + short_name[end_range:]
        else:
            # s = number of characters to skip at the start (0 = skip nothing)
            s = start_val if start_active else 0
            # e = negative index counted from the end (None = go up to the end)
            e = -end_val if (end_active and end_val > 0) else None
            renamed = short_name[s:e]

        # An empty name is not valid: skip this object and warn the user.
        if not renamed:
            cmds.warning(f"Object {short_name} new name is Empty")
            continue

        pairs.append((obj, renamed))

    rename_safe(pairs)


# ---------------------------------------------------------------------------
# User interface
# ---------------------------------------------------------------------------

version = 'v1.1.0'


class MayaRenamerUI(QtWidgets.QDialog):
    """The tool window. It only reads values from the widgets and calls the
    logic functions above."""

    def __init__(self, parent=None):
        # Call the constructor of the parent class (QDialog).
        # `parent` is the window this dialog belongs to (Maya's main window).
        super().__init__(parent)
        self.setWindowTitle("Maya Renamer Pro {}".format(version))
        self.resize(300, 450)

        self.setup_ui()

    def setup_ui(self):
        """Create all the widgets and place them in layouts."""
        # Layouts arrange widgets automatically: QVBoxLayout stacks them
        # vertically, QHBoxLayout side by side, QFormLayout in label/field rows.
        main_layout = QtWidgets.QVBoxLayout(self)

        # The title is a button styled to look like a clickable link.
        self.title_btn = QtWidgets.QPushButton("Maya Renamer Pro {}".format(version))
        self.title_btn.setCursor(QtCore.Qt.PointingHandCursor)  # Hand cursor on hover
        self.title_btn.setStyleSheet("""
            QPushButton {
                font-size: 13pt;
                font-weight: bold;
                text-decoration: underline;
                border: none;
                background: transparent;
                margin-bottom: 5px;
                text-align: center;
            }
            QPushButton:hover {
                color: #3daee9; /* Slight color change on hover, like a link */
            }
        """)

        main_layout.addWidget(self.title_btn)

        # Signals and slots: when the button emits "clicked", the method
        # on_about_clicked is called. Note that there are no () after the name:
        # we pass the method itself, Qt will call it later.
        self.title_btn.clicked.connect(self.on_about_clicked)

        # Horizontal divider line under the title
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        main_layout.addWidget(line)

        # --- SORT ORDER SECTION ---
        self.sort_group = QtWidgets.QGroupBox("Sort Order")
        sort_layout = QtWidgets.QHBoxLayout(self.sort_group)

        self.rb_outl_order = QtWidgets.QRadioButton("Outliner Order")
        self.rb_outl_order.setChecked(True)  # Selected by default
        self.rb_sel_order = QtWidgets.QRadioButton("User Selection Order")
        self.rb_sel_order.setChecked(False)

        sort_layout.addWidget(self.rb_outl_order)
        sort_layout.addWidget(self.rb_sel_order)

        # Group the radio buttons so only one can be selected at a time
        self.sort_button_group = QtWidgets.QButtonGroup(self)
        self.sort_button_group.addButton(self.rb_outl_order, id=0)
        self.sort_button_group.addButton(self.rb_sel_order, id=1)

        main_layout.addWidget(self.sort_group)

        # --- ADD PREFIX SECTION ---
        prefix_group = QtWidgets.QGroupBox("Add Prefix")
        prefix_layout = QtWidgets.QHBoxLayout(prefix_group)

        self.prefix_input = QtWidgets.QLineEdit()
        self.prefix_input.setPlaceholderText("Enter prefix")
        prefix_layout.addWidget(self.prefix_input)

        self.prefix_btn = QtWidgets.QPushButton("Add Prefix")
        prefix_layout.addWidget(self.prefix_btn)

        main_layout.addWidget(prefix_group)

        self.prefix_btn.clicked.connect(self.on_add_prefix_clicked)

        # --- ADD SUFFIX SECTION ---
        suffix_group = QtWidgets.QGroupBox("Add Suffix")
        suffix_layout = QtWidgets.QHBoxLayout(suffix_group)

        self.suffix_input = QtWidgets.QLineEdit()
        self.suffix_input.setPlaceholderText("Enter suffix")
        suffix_layout.addWidget(self.suffix_input)

        self.suffix_btn = QtWidgets.QPushButton("Add Suffix")
        suffix_layout.addWidget(self.suffix_btn)

        main_layout.addWidget(suffix_group)

        self.suffix_btn.clicked.connect(self.on_add_suffix_clicked)

        # --- PROGRESSIVE NUMBERING SECTION ---
        prog_group = QtWidgets.QGroupBox("Progressive Numbering")
        prog_v_layout = QtWidgets.QVBoxLayout(prog_group)

        # 1. Checkbox to strip existing numbers
        self.strip_num_cb = QtWidgets.QCheckBox("Strip existing numbers")
        self.strip_num_cb.setChecked(True)
        prog_v_layout.addWidget(self.strip_num_cb)

        # 2. Horizontal row with Separator, Start and Padding
        spin_h_layout = QtWidgets.QHBoxLayout()

        self.separator_input = QtWidgets.QLineEdit()
        self.separator_input.setText("_")
        self.separator_input.setMaximumWidth(40)

        self.start_spin = QtWidgets.QSpinBox()
        self.start_spin.setValue(1)
        self.start_spin.setRange(0, 9999)

        self.padding_spin = QtWidgets.QSpinBox()
        self.padding_spin.setValue(3)
        self.padding_spin.setRange(1, 6)

        spin_h_layout.addWidget(QtWidgets.QLabel("Sep:"))
        spin_h_layout.addWidget(self.separator_input)
        spin_h_layout.addWidget(QtWidgets.QLabel("Start:"))
        spin_h_layout.addWidget(self.start_spin)
        spin_h_layout.addWidget(QtWidgets.QLabel("Padding:"))
        spin_h_layout.addWidget(self.padding_spin)

        prog_v_layout.addLayout(spin_h_layout)

        # 3. Button and connection
        self.prog_btn = QtWidgets.QPushButton("Apply Progressive")
        prog_v_layout.addWidget(self.prog_btn)
        self.prog_btn.clicked.connect(self.on_apply_progressive)

        main_layout.addWidget(prog_group)

        # --- SEARCH AND REPLACE SECTION ---
        replace_group = QtWidgets.QGroupBox("Search and Replace")
        replace_v_layout = QtWidgets.QVBoxLayout(replace_group)

        form_layout = QtWidgets.QFormLayout()

        self.cb_c_sensitive_cb = QtWidgets.QCheckBox("Lower and Upper case sensitive search")
        self.cb_c_sensitive_cb.setChecked(True)
        replace_v_layout.addWidget(self.cb_c_sensitive_cb)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search for")
        self.replace_input = QtWidgets.QLineEdit()
        self.replace_input.setPlaceholderText("Replace with")

        form_layout.addRow("Search:", self.search_input)
        form_layout.addRow("Replace:", self.replace_input)

        replace_v_layout.addLayout(form_layout)

        self.replace_btn = QtWidgets.QPushButton("Apply Replace")
        replace_v_layout.addWidget(self.replace_btn)

        main_layout.addWidget(replace_group)
        self.replace_btn.clicked.connect(self.on_apply_replace_clicked)

        # --- STRIP CHARACTERS SECTION ---
        strip_group = QtWidgets.QGroupBox("Strip Characters")
        strip_v_layout = QtWidgets.QVBoxLayout(strip_group)

        # 1. From Start
        start_h_layout = QtWidgets.QHBoxLayout()
        self.strip_start_cb = QtWidgets.QCheckBox("From Start:")
        self.strip_start_spin = QtWidgets.QSpinBox()
        self.strip_start_spin.setValue(1)
        self.strip_start_spin.setRange(0, 99)
        start_h_layout.addWidget(self.strip_start_cb)
        start_h_layout.addWidget(self.strip_start_spin)
        strip_v_layout.addLayout(start_h_layout)

        # 2. From End
        end_h_layout = QtWidgets.QHBoxLayout()
        self.strip_end_cb = QtWidgets.QCheckBox("From End:")
        self.strip_end_spin = QtWidgets.QSpinBox()
        self.strip_end_spin.setValue(1)
        self.strip_end_spin.setRange(0, 99)
        end_h_layout.addWidget(self.strip_end_cb)
        end_h_layout.addWidget(self.strip_end_spin)
        strip_v_layout.addLayout(end_h_layout)

        # 3. Ranged Strip (mutually exclusive with Start/End)
        self.strip_range_cb = QtWidgets.QCheckBox("Ranged Strip (Index slice)")
        strip_v_layout.addWidget(self.strip_range_cb)

        range_h_layout = QtWidgets.QHBoxLayout()
        self.strip_range_start = QtWidgets.QSpinBox()
        self.strip_range_start.setRange(0, 99)
        self.strip_range_end = QtWidgets.QSpinBox()
        self.strip_range_end.setValue(1)
        self.strip_range_end.setRange(0, 99)
        range_h_layout.addWidget(QtWidgets.QLabel("From:"))
        range_h_layout.addWidget(self.strip_range_start)
        range_h_layout.addWidget(QtWidgets.QLabel("To:"))
        range_h_layout.addWidget(self.strip_range_end)
        strip_v_layout.addLayout(range_h_layout)

        # The range fields start disabled; they are enabled by the checkbox.
        self.strip_range_start.setEnabled(False)
        self.strip_range_end.setEnabled(False)
        self.strip_range_cb.toggled.connect(self.on_toggle_range_strip)

        self.strip_btn = QtWidgets.QPushButton("Apply Strip")
        strip_v_layout.addWidget(self.strip_btn)
        main_layout.addWidget(strip_group)
        self.strip_btn.clicked.connect(self.on_apply_strip)

    # -- Button callbacks ---------------------------------------------------
    # Every on_... method follows the same pattern: read the values from the
    # widgets, get the selection, and call the matching logic function only if
    # there is something to do.

    def on_add_prefix_clicked(self):
        prefix_text = self.prefix_input.text()

        selected_objs = get_user_selection(self.rb_outl_order.isChecked())

        if selected_objs and prefix_text:
            add_prefix(prefix_text, selected_objs)
            print(f"Added prefix '{prefix_text}' to selected objects: {selected_objs}")

    def on_add_suffix_clicked(self):
        suffix_text = self.suffix_input.text()

        selected_objs = get_user_selection(self.rb_outl_order.isChecked())

        if selected_objs and suffix_text:
            add_suffix(suffix_text, selected_objs)
            print(f"Added suffix '{suffix_text}' to selected objects: {selected_objs}")

    def on_apply_progressive(self):
        separator_val = self.separator_input.text()
        start_val = self.start_spin.value()
        padding_val = self.padding_spin.value()
        strip_num_val = self.strip_num_cb.isChecked()
        selected_objs = get_user_selection(self.rb_outl_order.isChecked())
        print(f"DEBUG Check Outliner Order: {self.rb_outl_order.isChecked()}")

        if selected_objs:
            add_progressive(selected_objs, start_val, padding_val, separator_val, strip_num_val)
            print("Progressive renumbering applied to selected objects.")

    def on_apply_replace_clicked(self):
        search_text = self.search_input.text()
        replace_text = self.replace_input.text()
        c_sensitive = self.cb_c_sensitive_cb.isChecked()

        selected_objs = get_user_selection(self.rb_outl_order.isChecked())

        if selected_objs and search_text:
            search_and_replace(selected_objs, search_text, replace_text, c_sensitive)
            print(f"Replaced '{search_text}' with '{replace_text}' in selected objects: {selected_objs}")

    def on_toggle_range_strip(self, checked):
        # `checked` is True/False, passed automatically by the "toggled" signal.
        # Ranged Strip and From Start/From End are mutually exclusive:
        # enable one group and disable the other.
        self.strip_start_cb.setEnabled(not checked)
        self.strip_start_spin.setEnabled(not checked)
        self.strip_end_cb.setEnabled(not checked)
        self.strip_end_spin.setEnabled(not checked)

        self.strip_range_start.setEnabled(checked)
        self.strip_range_end.setEnabled(checked)

    def on_apply_strip(self):
        start_active = self.strip_start_cb.isChecked()
        start_val = self.strip_start_spin.value()
        end_active = self.strip_end_cb.isChecked()
        end_val = self.strip_end_spin.value()
        ranged_active = self.strip_range_cb.isChecked()
        start_range = self.strip_range_start.value()
        end_range = self.strip_range_end.value()

        # With From >= To the slice would be meaningless (or duplicate characters).
        if ranged_active and start_range >= end_range:
            cmds.warning("Ranged Strip: 'From' must be smaller than 'To'.")
            return

        selected_objs = get_user_selection(self.rb_outl_order.isChecked())
        if selected_objs:
            strip_str(selected_objs, start_active, start_val, end_active, end_val, ranged_active, start_range, end_range)
            print("Strip characters applied to selected objects.")

    def on_about_clicked(self):
        # Adjacent string literals are joined by Python into one string,
        # so mind the spaces at the end of each line.
        QtWidgets.QMessageBox.about(
            self,
            "About Maya Renamer Pro",
            "<h3>Maya Renamer Pro {}</h3>"
            "<i>Made by @thepainteye_cg <br>GitHub: thepainteyecg</i>"
            "<hr>"
            "<p>Pro Tool for renaming and organizing objects in Autodesk Maya 2025+ (due to the PySide6 GUI).</p>"
            "<hr>"
            "<b>Note about Selection:</b><br>"
            "If you use the <i>click and drag</i> method inside the Outliner, Maya returns "
            "the selection in its visual order (top to bottom).<br>"
            "To use your custom selection order, select objects with <i>Shift + Click</i> or one by one. <br>"
            "<br><b>AI use disclosure</b><br>"
            "I coded this tool as a way to learn python. I used to do C/C++ and HTML in high school but because some years have passed "
            "I used AI assistant that helped me <i>learn</i>. I didn't want to 'vibe code': "
            "I used them to suggest Maya commands, explain logic and functions, and review the code I wrote when I had doubts. "
            "But I wrote the core logic and learned. The UI started from AI-generated code that I then reviewed until I understood it. "
            "There will surely be tons of ways to have written this script better, cleaner or faster, but I had to start somewhere.<br>"
            "Looking forward to hearing your feedback, happy renaming!".format(version)
        )


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------

def maya_main_window():
    """Return Maya's main window as a Qt widget, to be used as parent of the tool window."""
    # MQtUtil.mainWindow() gives the memory address of the window (a C++ pointer);
    # wrapInstance casts it to a Python object of type QWidget.
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def show_renamer():
    """Open the tool window (closing the previous one, if any)."""
    global renamer_window
    try:
        renamer_window.close()
        renamer_window.deleteLater()
    except (NameError, RuntimeError):
        # NameError: the window was never opened in this session.
        # RuntimeError: Qt already destroyed the window object.
        pass

    renamer_window = MayaRenamerUI(parent=maya_main_window())
    renamer_window.show()


# When the file is run directly (e.g. pasted in the Script Editor) the window
# opens right away. When it is imported (e.g. by a shelf button) nothing opens
# until show_renamer() is called.
if __name__ == "__main__":
    show_renamer()
