"""
Maya Renamer Pro - drag & drop installer
========================================

Usage: drag this file from your file explorer into a Maya viewport.
Maya runs the file and calls onMayaDroppedPythonFile() below.

What the installer does:
    1. Copies maya_renamer_pro.py into your Maya user scripts folder.
    2. Copies the icon into your Maya user icons folder.
    3. Creates a button in the currently active shelf (once: if the button
       already exists, it is not duplicated).

Expected repository layout (this file sits at the root):

    maya-renamer-pro/
    |-- install.py
    |-- maya_renamer_pro.py
    `-- icons/
        `-- maya_renamer_pro.png
"""

import os
import shutil

import maya.cmds as cmds
import maya.mel as mel

TOOL_FILE = "maya_renamer_pro.py"
ICON_FILE = "maya_renamer_pro.png"
BUTTON_LABEL = "Renamer Pro"
BUTTON_TOOLTIP = "Maya Renamer Pro: prefix, suffix, numbering, search & replace, strip"

# Python code executed when the shelf button is clicked.
BUTTON_COMMAND = (
    "import maya_renamer_pro\n"
    "import importlib\n"
    "importlib.reload(maya_renamer_pro)\n"
    "maya_renamer_pro.show_renamer()\n"
)


def onMayaDroppedPythonFile(*args):
    """Entry point: Maya calls this function with this exact name when the
    file is dropped into the viewport. *args collects (and ignores) the
    arguments Maya passes."""
    install()


def install():
    # Folder that contains this installer (and the files to install).
    source_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Copy the tool into the user scripts folder, which is already on Maya's
    #    Python path (so "import maya_renamer_pro" works from anywhere).
    scripts_dir = cmds.internalVar(userScriptDir=True)
    shutil.copy2(os.path.join(source_dir, TOOL_FILE), scripts_dir)

    # 2. Copy the icon into the user icons folder, where shelf buttons look for icons.
    icons_dir = cmds.internalVar(userBitmapsDir=True)
    shutil.copy2(os.path.join(source_dir, "icons", ICON_FILE), icons_dir)

    # 3. Find the shelf that is currently open.
    top_shelf = mel.eval("$tmp = $gShelfTopLevel")
    current_shelf = cmds.tabLayout(top_shelf, query=True, selectTab=True)

    # Do not create a second button if one with our label is already there.
    for button in cmds.shelfLayout(current_shelf, query=True, childArray=True) or []:
        if cmds.shelfButton(button, exists=True) and cmds.shelfButton(button, query=True, label=True) == BUTTON_LABEL:
            cmds.warning("Maya Renamer Pro: the shelf button already exists.")
            return

    cmds.shelfButton(
        parent=current_shelf,
        label=BUTTON_LABEL,
        annotation=BUTTON_TOOLTIP,
        image1=ICON_FILE,
        sourceType="python",
        command=BUTTON_COMMAND,
    )
    print("Maya Renamer Pro installed in shelf: {}".format(current_shelf))
