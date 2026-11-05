# SPDX-License-Identifier: GPL-3.0-or-later
"""Shots for guides/models: the model button, the model menu and its submenu,
the Other Model dialog and the preference for new chats."""

from tests.docshots.spec import Shot, popup, preferences, sidebar

SHOTS = [
    Shot("model-button", "The composer with the model button beside Send.", sidebar(crop=(8, 305, 242, 100)),
         scenario="model_menu"),
    Shot("model-menu", "The model menu over a chat on Sonnet 5.5.", scenario="model_menu"),
    Shot("older-models", "The Older Models submenu, one column per family.", scenario="model_menu_older"),
    Shot("other-model", "The Other Model dialog.", popup(operator="whittle.chat_model", props={"model": ""}),
         scenario="model_menu"),
    Shot("new-chats-preference", "Model for New Chats in the preferences.", preferences(crop=(172, 278, 655, 140))),
]
