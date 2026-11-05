# SPDX-License-Identifier: GPL-3.0-or-later
"""The screenshots of the Chats guide."""

from tests.docshots.spec import Shot, sidebar

SHOTS = [
    Shot("chat-menu", "The chat menu over three chats.", scenario="chat_menu"),
    Shot("new-chat", "After New Chat: an empty conversation, the scene as it was.", scenario="new_chat"),
    Shot("switched-chat", "Back in an earlier chat, with the note that the scene stayed as it is.",
         scenario="switched_chat"),
    Shot("delete-confirm", "The confirmation of deleting one chat.", scenario="delete_confirm"),
    Shot("delete-many", "The Delete Chats dialog on Older Than a Month.", scenario="delete_many"),
    Shot("continue-chat", "A chat made on another machine, asking to be continued.", scenario="continue_chat"),
    Shot("open-elsewhere", "The line shown while another Blender has the same file open.", sidebar(crop=(0, 0, 280, 130)),
         scenario="open_elsewhere"),
]
